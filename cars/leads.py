"""Lead follow-up.

``Inquiry`` and ``ContactMessage`` both carry ``assigned_to`` and
``follow_up_date``, but nothing used them: every lead was a row in a list
that nobody owned. This module is the one place that decides what "open",
"overdue" and "needs a reminder" mean, so the two list pages, the
dashboard and the Celery task cannot drift apart.

A lead is worked in place: assigning an owner and a date, logging a
contact, and moving the status are separate actions because a real
dealership does them at different times.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from notifications.services import notify, notify_staff

from .models import ContactMessage, Inquiry

#: Statuses where a lead still needs work.
OPEN_INQUIRY_STATUSES = Inquiry.OPEN_STATUSES
OPEN_CONTACT_STATUSES = ContactMessage.OPEN_STATUSES

#: How long an unassigned lead may sit before staff are nudged about it.
UNASSIGNED_GRACE_HOURS = 24

#: Sentinel so ``assign()`` can tell "leave the date alone" from "clear it".
_UNSET = object()


def _today():
    return timezone.localdate()


def inquiry_leads():
    """Inquiries with the car and owner joined in, ready for a list page."""
    return Inquiry.objects.select_related('car', 'assigned_to')


def contact_leads():
    """Contact-page messages with the owner joined in."""
    return ContactMessage.objects.select_related('assigned_to')


def open_inquiries(queryset=None):
    queryset = queryset if queryset is not None else inquiry_leads()
    return queryset.filter(status__in=OPEN_INQUIRY_STATUSES)


def open_contact_messages(queryset=None):
    queryset = queryset if queryset is not None else contact_leads()
    return queryset.filter(status__in=OPEN_CONTACT_STATUSES)


def overdue(queryset, today=None):
    """Leads whose follow-up date has already passed."""
    today = today or _today()
    return queryset.filter(follow_up_date__lt=today)


def due_today(queryset, today=None):
    today = today or _today()
    return queryset.filter(follow_up_date=today)


def due_within(queryset, days, today=None):
    """Leads due today or in the next ``days`` days."""
    today = today or _today()
    return queryset.filter(follow_up_date__lte=today + timedelta(days=days))


def unassigned(queryset):
    return queryset.filter(assigned_to__isnull=True)


def staff_users():
    """Everyone who can own a lead, for the assignment dropdown."""
    return get_user_model().objects.filter(
        is_staff=True, is_active=True,
    ).order_by('username')


def lead_kind(lead):
    """``'message'`` for a contact message, ``'inquiry'`` otherwise."""
    return 'message' if isinstance(lead, ContactMessage) else 'inquiry'


def lead_url(lead):
    """A deep link to this lead on its staff list page."""
    name = (
        'cars:contact_messages_list'
        if isinstance(lead, ContactMessage)
        else 'cars:inquiries_list'
    )
    return f'{reverse(name)}?open={lead.pk}#lead-{lead.pk}'


def _append_note(lead, text, actor=None):
    """Keep an append-only trail of what was done, in the notes field."""
    stamp = timezone.localtime().strftime('%Y-%m-%d %H:%M')
    who = getattr(actor, 'username', '') or 'system'
    line = f'[{stamp}] {who}: {text}'
    lead.notes = f'{lead.notes}\n{line}'.strip()


def assign(lead, assignee, follow_up_date=_UNSET, note='', actor=None):
    """Give a lead an owner and, optionally, a next follow-up date.

    ``follow_up_date=None`` clears the date; omit the argument to leave it
    alone. A new owner or a new date resets the reminder flag so the next
    reminder is not swallowed by an old one.
    """
    previous_owner = lead.assigned_to_id
    lead.assigned_to = assignee
    changed_owner = previous_owner != getattr(assignee, 'pk', None)

    date_changed = follow_up_date is not _UNSET
    if date_changed:
        lead.follow_up_date = follow_up_date

    if note:
        _append_note(lead, note, actor)

    if changed_owner or date_changed:
        lead.reminder_sent_at = None

    lead.save()

    if (
        changed_owner
        and assignee is not None
        and getattr(assignee, 'pk', None) != getattr(actor, 'pk', None)
    ):
        notify(
            assignee,
            'A lead was assigned to you',
            f'{lead} is now yours to follow up.',
            obj=lead,
            url=lead_url(lead),
        )
    return lead


def log_contact(lead, actor=None, note=''):
    """Record that somebody actually spoke to the lead."""
    lead.last_contacted_at = timezone.now()
    if lead.status == 'new':
        lead.status = 'contacted'
    if note:
        _append_note(lead, note, actor)
    lead.save()
    return lead


def lead_counts(today=None):
    """The three numbers the dashboard and the list pages care about."""
    today = today or _today()
    inquiries = open_inquiries()
    messages = open_contact_messages()
    return {
        'overdue': (
            overdue(inquiries, today).count()
            + overdue(messages, today).count()
        ),
        'due_today': (
            due_today(inquiries, today).count()
            + due_today(messages, today).count()
        ),
        'unassigned': (
            unassigned(inquiries).count()
            + unassigned(messages).count()
        ),
    }


def _reminder_due(lead, today):
    if not lead.reminder_sent_at:
        return True
    return timezone.localdate(lead.reminder_sent_at) < today


def send_lead_reminders(now=None):
    """Notify owners about due follow-ups and staff about unowned leads.

    Runs from Celery beat once a day. It is safe to run twice: an owner is
    reminded at most once per day, and an unowned lead is announced once
    (until it is assigned or its date changes).
    """
    now = now or timezone.now()
    today = timezone.localdate(now)

    owner_reminders = 0
    due_leads = list(
        open_inquiries().filter(
            follow_up_date__lte=today, assigned_to__isnull=False,
        )
    ) + list(
        open_contact_messages().filter(
            follow_up_date__lte=today, assigned_to__isnull=False,
        )
    )
    for lead in due_leads:
        if not _reminder_due(lead, today):
            continue
        notify(
            lead.assigned_to,
            f'Follow up: {lead}',
            'This lead is due for a follow-up.',
            level='warning' if lead.follow_up_date < today else 'info',
            obj=lead,
            url=lead_url(lead),
        )
        lead.reminder_sent_at = now
        lead.save(update_fields=['reminder_sent_at'])
        owner_reminders += 1

    cutoff = now - timedelta(hours=UNASSIGNED_GRACE_HOURS)
    stale_unassigned = list(
        open_inquiries().filter(
            assigned_to__isnull=True,
            reminder_sent_at__isnull=True,
            created_at__lt=cutoff,
        )
    ) + list(
        open_contact_messages().filter(
            assigned_to__isnull=True,
            reminder_sent_at__isnull=True,
            sent_at__lt=cutoff,
        )
    )

    unassigned_digest = 0
    if stale_unassigned:
        notify_staff(
            'Leads nobody owns',
            f'{len(stale_unassigned)} lead(s) have been waiting for an '
            'owner for over a day.',
            level='warning',
            url=f'{reverse("cars:inquiries_list")}?assignee=unassigned',
        )
        for lead in stale_unassigned:
            lead.reminder_sent_at = now
            lead.save(update_fields=['reminder_sent_at'])
        unassigned_digest = len(stale_unassigned)

    return owner_reminders, unassigned_digest
