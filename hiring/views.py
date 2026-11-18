"""Views for car hire and tours & travel.

Two sides to this feature:

**Public.** A customer browses the fleet, picks a car, and sends a
*request* to hire it. Nothing is confirmed on the spot: the request goes
to staff, who check the dates, check the licence and ID, take the money
and confirm it. The customer can follow their own bookings.

**Staff.** Staff post the fleet, watch the requests coming in, and work
through them: confirm, price, record the payment, or turn one down.
"""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View
from django.views.decorators.http import require_POST
from datetime import date, timedelta

from traffic.conversion import source_for_visitor, visitor_id_from
from notifications.services import notify

from . import rules
from .emails import send_hire_booking_notification, send_hire_booking_status_email
from .forms import (
    HireBookingExtraFormSet, HireBookingForm, HireBookingReviewForm, HireCarForm,
)
from .models import (
    SERVICE_TOUR, HireAddOn, HireBooking, HireBookingAddOn, HireCar, HireCarImage,
)


logger = logging.getLogger(__name__)


class StaffRequiredMixin(View):
    """Allow only staff (incl. staff-created accounts and admins)"""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)


def _record_conversion_source(request, instance):
    """Remember where this visitor came from, for the conversion funnel.

    The token and the source are copied onto the booking rather than
    looked up later, because page views are pruned after the retention
    window and a booking has to keep its history.
    """
    instance.visitor_id = visitor_id_from(request)
    instance.source = source_for_visitor(instance.visitor_id)


def _safe_next(request):
    """Return the validated ?next= target, or None"""
    from django.utils.http import url_has_allowed_host_and_scheme

    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return None


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

class HireCarListView(ListView):
    """The cars in the hire fleet, with filters."""

    model = HireCar
    template_name = 'hiring/hire_car_list.html'
    context_object_name = 'hire_cars'
    paginate_by = 12

    #: Set by the tours page, which only shows cars we take out with a driver.
    tours_only = False

    #: The service the rates are shown for when the customer has not chosen.
    default_service = ''

    SORT_OPTIONS = {
        'cheapest': 'hire_daily_rate',
        'newest': '-created_at',
        'biggest': '-seats',
    }

    SORT_LABELS = {
        'cheapest': 'Cheapest first',
        'newest': 'Newest first',
        'biggest': 'Biggest first',
    }

    def get_service(self):
        """The service the customer is looking at (self-drive or tour)."""
        return (self.request.GET.get('service') or self.default_service).strip()

    def get_dates(self):
        """The pick-up and return dates the customer asked about."""
        start = (self.request.GET.get('start_date') or '').strip()
        end = (self.request.GET.get('end_date') or '').strip()
        try:
            start = parse_date(start) if start else None
        except ValueError:
            start = None
        try:
            end = parse_date(end) if end else None
        except ValueError:
            end = None
        return start, end

    def get_queryset(self):
        queryset = HireCar.objects.filter(
            status__in=HireCar.PUBLIC_STATUSES
        ).prefetch_related('images')

        service = self.get_service()

        if self.tours_only or service == SERVICE_TOUR:
            queryset = queryset.filter(allows_tours=True)

        body_type = (self.request.GET.get('body_type') or '').strip()
        if body_type:
            queryset = queryset.filter(body_type=body_type)

        transmission = (self.request.GET.get('transmission') or '').strip()
        if transmission:
            queryset = queryset.filter(transmission=transmission)

        seats = (self.request.GET.get('seats') or '').strip()
        if seats.isdigit():
            queryset = queryset.filter(seats__gte=int(seats))

        max_rate = (self.request.GET.get('max_rate') or '').strip()
        if max_rate:
            rate_field = 'tour_daily_rate' if service == SERVICE_TOUR else 'hire_daily_rate'
            queryset = queryset.filter(**{f'{rate_field}__lte': max_rate})

        search = (self.request.GET.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(make__icontains=search) | Q(model__icontains=search)
            )

        # Hide the cars that are already out for the dates asked about.
        start, end = self.get_dates()
        if start and end and start <= end:
            busy = HireBooking.objects.filter(
                start_date__lte=end,
                end_date__gte=start,
                status__in=rules.BLOCKING_STATUSES,
            ).values_list('hire_car_id', flat=True)
            queryset = queryset.exclude(pk__in=busy)

        order = self.SORT_OPTIONS.get(
            self.request.GET.get('sort'), self.SORT_OPTIONS['cheapest']
        )
        return queryset.order_by(order)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        listed = HireCar.objects.filter(status__in=HireCar.PUBLIC_STATUSES)
        context.update({
            'body_types': sorted(set(listed.values_list('body_type', flat=True))),
            'transmissions': sorted(set(listed.values_list('transmission', flat=True))),
            'sort_options': [
                (key, self.SORT_LABELS[key]) for key in self.SORT_OPTIONS
            ],
            'current_sort': self.request.GET.get('sort', 'cheapest'),
            'service': self.get_service(),
            'tours_only': self.tours_only,
            'body_type': self.request.GET.get('body_type', ''),
            'transmission': self.request.GET.get('transmission', ''),
            'seats': self.request.GET.get('seats', ''),
            'max_rate': self.request.GET.get('max_rate', ''),
            'search': self.request.GET.get('search', ''),
            'start_date': self.request.GET.get('start_date', ''),
            'end_date': self.request.GET.get('end_date', ''),
        })
        return context


class HireToursView(HireCarListView):
    """Tours and travel: the cars we take out with one of our drivers."""

    tours_only = True
    default_service = SERVICE_TOUR


class HireCarDetailView(DetailView):
    """One car in the fleet, with the booking form on it."""

    model = HireCar
    template_name = 'hiring/hire_car_detail.html'
    context_object_name = 'hire_car'

    def get_queryset(self):
        return HireCar.objects.prefetch_related('images')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        car = self.object
        context['bookable'] = car.is_publicly_listed()
        context['photos'] = car.images.all()
        context['next_free'] = car.next_free_from()
        context['add_ons'] = HireAddOn.objects.filter(is_active=True)
        context['deposit_ratio'] = int(rules.SECURITY_DEPOSIT_RATIO * 100)
        if 'form' not in context:
            context['form'] = HireBookingForm(hire_car=car, initial=self._initial())
        return context

    def _initial(self):
        """Pre-fill the contact details of a signed-in customer."""
        user = self.request.user
        initial = {}
        if user.is_authenticated:
            name = user.get_full_name() or getattr(user, 'username', '')
            if name:
                initial['customer_name'] = name
            if getattr(user, 'email', ''):
                initial['customer_email'] = user.email
        return initial

    def post(self, request, *args, **kwargs):
        """Take a booking request for this car."""
        self.object = self.get_object()
        car = self.object

        if not car.is_publicly_listed():
            messages.error(request, 'That car is not available at the moment.')
            return redirect(reverse('hiring:hire_car_list'))

        form = HireBookingForm(request.POST, hire_car=car)
        if not form.is_valid():
            context = self.get_context_data(form=form)
            return self.render_to_response(context)

        booking = form.save(commit=False)
        booking.hire_car = car
        booking.quoted_price = booking.price_quote()
        # The deposit is only suggested here; staff can change it when
        # they work through the request.
        booking.security_deposit = rules.suggested_security_deposit(
            booking.quoted_price
        )
        if request.user.is_authenticated:
            booking.user = request.user
        _record_conversion_source(request, booking)
        booking.save()

        for add_on in form.cleaned_data.get('extras') or []:
            HireBookingAddOn.objects.create(
                booking=booking,
                add_on=add_on,
                name=add_on.name,
                unit_price=add_on.price,
                unit=add_on.unit,
                quantity=1,
            )

        request.session['hire_booking_id'] = booking.pk
        messages.success(
            request,
            'Your request has been sent. We will confirm it once the car is '
            'checked and the payment is settled.',
        )
        send_hire_booking_notification(booking, request)
        try:
            from cars.sms import send_hire_booking_sms
            send_hire_booking_sms(booking)
        except Exception:
            pass
        # Offer M-Pesa payment option if configured
        from django.conf import settings
        from payments import services as payment_services
        phone = booking.customer_phone
        if getattr(settings, 'MPESA_CONSUMER_KEY', '') and phone:
            try:
                txn, result, err = payment_services.start_payment(
                    request,
                    phone_number=phone,
                    amount=booking.total_due(),
                    purpose='hire',
                    hire_booking=booking,
                )
                if txn and result and not err:
                    request.session['mpesa_ref'] = txn.reference
                    messages.info(request, 'An M-Pesa STK Push has been sent to your phone. Please enter your PIN to complete payment.')
                    return redirect(payment_services.payment_status_url(txn))
            except Exception:
                logger.exception('Could not start the hire payment')
        return redirect(reverse('hiring:hire_booking_thank_you'))


def hire_booking_thank_you(request):
    """The page shown after a booking request has been sent."""
    booking = None
    booking_id = request.session.pop('hire_booking_id', None)
    if booking_id:
        queryset = HireBooking.objects.filter(pk=booking_id).select_related('hire_car')
        if request.user.is_authenticated:
            queryset = queryset.filter(user=request.user)
        booking = queryset.first()

    return render(request, 'hiring/hire_booking_thank_you.html', {'booking': booking})


class MyHireBookingsView(LoginRequiredMixin, ListView):
    """The customer's own hire bookings."""

    model = HireBooking
    template_name = 'hiring/my_hire_bookings.html'
    context_object_name = 'bookings'
    paginate_by = 20

    def get_queryset(self):
        return HireBooking.objects.filter(
            user=self.request.user
        ).select_related('hire_car').prefetch_related('extras')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['open_count'] = self.get_queryset().filter(
            status__in=HireBooking.OPEN_STATUSES
        ).count()
        return context


class HireBookingDetailView(LoginRequiredMixin, DetailView):
    """One hire booking: a customer sees their own, staff see any."""

    model = HireBooking
    template_name = 'hiring/hire_booking_detail.html'
    context_object_name = 'booking'

    def get_queryset(self):
        queryset = HireBooking.objects.select_related('hire_car').prefetch_related(
            'extras'
        )
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)


@require_POST
def hire_booking_pay(request, pk):
    """Customer retry: pay for a hire booking with M-Pesa (POST only)."""
    from django.conf import settings
    from payments import services as payment_services

    booking = get_object_or_404(HireBooking, pk=pk)
    is_owner = booking.user_id and booking.user_id == request.user.pk
    if not (is_owner or request.user.is_staff):
        messages.error(request, 'That booking could not be found.')
        return redirect('cars:home')

    if booking.is_settled():
        messages.info(request, 'This booking has already been paid in full.')
        return redirect('hiring:hire_booking_detail', pk=booking.pk)

    if booking.status in ('rejected', 'cancelled'):
        messages.error(request, 'This booking is no longer open.')
        return redirect('hiring:hire_booking_detail', pk=booking.pk)

    if not getattr(settings, 'MPESA_CONSUMER_KEY', ''):
        messages.error(
            request,
            'Online M-Pesa payments are not switched on yet. '
            'Please pay by bank transfer or contact us.',
        )
        return redirect('hiring:hire_booking_detail', pk=booking.pk)

    phone = (request.POST.get('phone_number') or booking.customer_phone).strip()
    txn, result, error = payment_services.start_payment(
        request,
        phone_number=phone,
        amount=booking.total_due(),
        purpose='hire',
        hire_booking=booking,
    )

    if error:
        messages.error(request, error)
        return redirect('hiring:hire_booking_detail', pk=booking.pk)

    if txn and result:
        messages.info(
            request,
            'An M-Pesa request has been sent to your phone. '
            'Enter your PIN to complete payment.',
        )
        return redirect(payment_services.payment_status_url(txn))

    messages.error(request, 'We could not start the M-Pesa payment. Please try again.')
    return redirect('hiring:hire_booking_detail', pk=booking.pk)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

class StaffHireCarListView(StaffRequiredMixin, ListView):
    """The fleet, with how many bookings each car has."""

    model = HireCar
    template_name = 'hiring/staff_hire_car_list.html'
    context_object_name = 'hire_cars'
    paginate_by = 25

    def get_queryset(self):
        queryset = HireCar.objects.prefetch_related('images').annotate(
            booking_count=Count('bookings')
        )

        status = (self.request.GET.get('status') or '').strip()
        if status:
            queryset = queryset.filter(status=status)

        search = (self.request.GET.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(make__icontains=search)
                | Q(model__icontains=search)
                | Q(bookings__customer_name__icontains=search)
            ).distinct()

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_choices'] = HireCar.STATUS_CHOICES
        context['current_status'] = self.request.GET.get('status', '')
        context['search'] = self.request.GET.get('search', '')
        context['available_count'] = HireCar.objects.filter(
            status='available'
        ).count()
        return context


class StaffHireCarFormMixin(StaffRequiredMixin):
    """Shared behaviour for adding and editing a car in the fleet."""

    model = HireCar
    form_class = HireCarForm
    template_name = 'hiring/staff_hire_car_form.html'

    def form_valid(self, form):
        car = form.save(commit=False)
        car.save()
        self.object = car
        self.save_images(car)
        messages.success(self.request, f'{car} saved.')
        return redirect(reverse('hiring:staff_hire_car_edit', args=[car.pk]))

    def save_images(self, car):
        """Store the photos uploaded with the form."""
        primary_needed = not car.images.exists()
        for uploaded in self.request.FILES.getlist('images'):
            if not uploaded or not getattr(uploaded, 'size', 0):
                continue
            HireCarImage.objects.create(
                hire_car=car,
                image=uploaded,
                is_primary=primary_needed,
            )
            primary_needed = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['photos'] = self.object.images.all() if self.object else []
        context['is_edit'] = self.object is not None
        return context


class StaffHireCarCreateView(StaffHireCarFormMixin, CreateView):
    """Staff view: add a car to the hire fleet."""


class StaffHireCarEditView(StaffHireCarFormMixin, UpdateView):
    """Staff view: edit a car in the hire fleet."""


class StaffHireCalendarView(StaffRequiredMixin, ListView):
    """Staff view: availability calendar for all hire cars."""
    model = HireCar
    template_name = 'hiring/staff_hire_calendar.html'
    context_object_name = 'hire_cars'

    def get_queryset(self):
        return HireCar.objects.filter(status='available').order_by('make', 'model')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        start_date = today - timedelta(days=7)
        end_date = today + timedelta(days=60)
        bookings = HireBooking.objects.filter(
            hire_car__in=context['hire_cars'],
            end_date__gte=start_date,
            start_date__lte=end_date,
        ).exclude(status__in=rules.FREE_STATUSES).select_related('hire_car')
        context['start_date'] = start_date
        context['end_date'] = end_date
        context['bookings'] = bookings
        context['days'] = [(start_date + timedelta(days=i)) for i in range((end_date - start_date).days + 1)]
        return context


class StaffHireCarCalendarView(StaffRequiredMixin, DetailView):
    """Staff view: availability calendar for a single hire car."""
    model = HireCar
    template_name = 'hiring/staff_hire_car_calendar.html'
    context_object_name = 'hire_car'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        start_date = today - timedelta(days=7)
        end_date = today + timedelta(days=60)
        bookings = self.object.bookings.filter(
            end_date__gte=start_date,
            start_date__lte=end_date,
        ).exclude(status__in=rules.FREE_STATUSES)
        context['start_date'] = start_date
        context['end_date'] = end_date
        context['bookings'] = bookings
        context['days'] = [(start_date + timedelta(days=i)) for i in range((end_date - start_date).days + 1)]
        return context



class StaffHireBookingListView(StaffRequiredMixin, ListView):
    """The booking requests coming in."""

    model = HireBooking
    template_name = 'hiring/staff_hire_booking_list.html'
    context_object_name = 'bookings'
    paginate_by = 25

    def get_queryset(self):
        queryset = HireBooking.objects.select_related('hire_car', 'user').prefetch_related(
            'extras'
        )

        status = (self.request.GET.get('status') or '').strip()
        if status:
            queryset = queryset.filter(status=status)

        payment = (self.request.GET.get('payment') or '').strip()
        if payment:
            queryset = queryset.filter(payment_status=payment)

        search = (self.request.GET.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(customer_name__icontains=search)
                | Q(customer_email__icontains=search)
                | Q(customer_phone__icontains=search)
                | Q(hire_car__make__icontains=search)
                | Q(hire_car__model__icontains=search)
            )

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_choices'] = HireBooking.STATUS_CHOICES
        context['payment_choices'] = HireBooking.PAYMENT_STATUS_CHOICES
        # The row-level quick action can set any status, including
        # 'completed' (the car has come back). Rejecting needs a reason for
        # the customer, so that one has to be done on the review page.
        context['quick_status_choices'] = [
            (value, label) for value, label in HireBooking.STATUS_CHOICES
            if value != 'rejected'
        ]
        context['current_status'] = self.request.GET.get('status', '')
        context['current_payment'] = self.request.GET.get('payment', '')
        context['search'] = self.request.GET.get('search', '')
        context['pending_count'] = HireBooking.objects.filter(status='pending').count()
        context['unpaid_count'] = HireBooking.objects.filter(
            status='confirmed', payment_status__in=('pending', 'partial')
        ).count()
        return context


class StaffHireBookingReviewView(StaffRequiredMixin, View):
    """Staff view: work through one booking request."""

    template_name = 'hiring/staff_hire_booking_review.html'

    def get(self, request, pk):
        booking = get_object_or_404(
            HireBooking.objects.select_related('hire_car'), pk=pk
        )
        return render(request, self.template_name, self.build_context(booking))

    def build_context(self, booking, review_form=None, extras_formset=None):
        """Everything the review page needs."""
        if extras_formset is None:
            extras_formset = HireBookingExtraFormSet(
                instance=booking, prefix='extras'
            )
        return {
            'booking': booking,
            'review_form': review_form or HireBookingReviewForm(instance=booking),
            'extras_formset': extras_formset,
            'standard_quote': booking.price_quote(),
            'clashes': HireBooking.overlapping(
                booking.hire_car,
                booking.start_date,
                booking.end_date,
                exclude_pk=booking.pk,
            ),
        }

    def post(self, request, pk):
        booking = get_object_or_404(
            HireBooking.objects.select_related('hire_car'), pk=pk
        )
        previous_status = booking.status
        form = HireBookingReviewForm(request.POST, instance=booking)

        # The management form tells us whether the extras were posted at
        # all; some older links save the booking without them.
        if 'extras-TOTAL_FORMS' in request.POST:
            extras_formset = HireBookingExtraFormSet(
                request.POST, instance=booking, prefix='extras'
            )
            extras_valid = extras_formset.is_valid()
        else:
            extras_formset = None
            extras_valid = True

        if not form.is_valid() or not extras_valid:
            messages.error(request, 'Please check the details you entered.')
            return render(
                request,
                self.template_name,
                self.build_context(booking, form, extras_formset),
            )

        new_status = form.cleaned_data.get('status') or previous_status

        # The form may have moved the booking to new dates, so the clash
        # check has to look at the new ones.
        booking = form.save(commit=False)
        booking.status = new_status

        if new_status == 'confirmed' and new_status != previous_status:
            # Nothing is confirmed before the money is in: the customer's
            # place in the diary is only worth something once they have paid.
            if booking.payment_status not in rules.CONFIRMABLE_PAYMENT_STATUSES:
                messages.error(
                    request,
                    'Record the payment, or at least a deposit, before '
                    'confirming the booking.',
                )
                return redirect(
                    reverse('hiring:staff_hire_booking_review', args=[booking.pk])
                )

            clash = HireBooking.blocking(
                booking.hire_car,
                booking.start_date,
                booking.end_date,
                exclude_pk=booking.pk,
            ).first()
            if clash:
                messages.error(
                    request,
                    f'{booking.hire_car} is already out for those dates under '
                    f'booking {clash.reference}. Change the dates or cancel '
                    'that booking first.',
                )
                return redirect(
                    reverse('hiring:staff_hire_booking_review', args=[booking.pk])
                )

        if booking.is_settled() and not booking.payment_received_at:
            booking.payment_received_at = timezone.now()

        # The two deposit ticks say what has happened to the money. The
        # timestamps are ours, not the staff's, so nobody has to type one.
        now = timezone.now()
        if form.cleaned_data.get('deposit_received'):
            if not booking.deposit_received_at:
                booking.deposit_received_at = now
        else:
            booking.deposit_received_at = None
            booking.deposit_refunded_at = None
        if form.cleaned_data.get('deposit_refunded') and booking.deposit_received_at:
            if not booking.deposit_refunded_at:
                booking.deposit_refunded_at = now
        else:
            booking.deposit_refunded_at = None

        booking.reviewed_by = request.user
        booking.reviewed_at = timezone.now()
        booking.save()

        if extras_formset is not None:
            extras_formset.instance = booking
            extras_formset.save()

        if booking.status != previous_status:
            send_hire_booking_status_email(booking)
            try:
                from cars.sms import send_hire_booking_status_sms
                send_hire_booking_status_sms(booking)
            except Exception:
                pass
            notify(
                booking.user,
                f'Booking {booking.reference} is now '
                f'{booking.get_status_display().lower()}',
                f'Your booking for {booking.hire_car} has been updated to '
                f'{booking.get_status_display()}.',
                level=(
                    'warning'
                    if booking.status in ('rejected', 'cancelled')
                    else 'info'
                ),
                obj=booking,
                url=reverse('hiring:hire_booking_detail', args=[booking.pk]),
            )

        messages.success(request, f'Booking {booking.reference} updated.')
        return redirect(
            reverse('hiring:staff_hire_booking_review', args=[booking.pk])
        )


def hire_booking_status(request, pk):
    """Staff view: change a booking's status from the list (POST only)"""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('hiring:staff_hire_bookings')

    booking = get_object_or_404(HireBooking, pk=pk)
    status = request.POST.get('status')
    valid_statuses = [choice[0] for choice in HireBooking.STATUS_CHOICES]

    if status not in valid_statuses:
        messages.error(request, 'Invalid status selected.')
        return redirect(_safe_next(request) or 'hiring:staff_hire_bookings')

    if status == 'rejected':
        # A rejection has to carry a reason for the customer, and that is
        # collected on the review page.
        messages.error(
            request,
            'Open the booking to give the customer a reason for turning it down.',
        )
        return redirect(
            reverse('hiring:staff_hire_booking_review', args=[booking.pk])
        )

    if status == 'confirmed':
        if booking.payment_status not in rules.CONFIRMABLE_PAYMENT_STATUSES:
            messages.error(
                request,
                'Record the payment, or at least a deposit, before confirming '
                'the booking.',
            )
            return redirect(_safe_next(request) or 'hiring:staff_hire_bookings')

        clash = HireBooking.blocking(
            booking.hire_car,
            booking.start_date,
            booking.end_date,
            exclude_pk=booking.pk,
        ).first()
        if clash:
            messages.error(
                request,
                f'{booking.hire_car} is already out for those dates under '
                f'booking {clash.reference}.',
            )
            return redirect(_safe_next(request) or 'hiring:staff_hire_bookings')

    changed = status != booking.status
    booking.status = status
    booking.reviewed_by = request.user
    booking.reviewed_at = timezone.now()
    booking.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

    messages.success(
        request,
        f'Booking {booking.reference} marked as {booking.get_status_display()}.',
    )
    if changed:
        send_hire_booking_status_email(booking)
        notify(
            booking.user,
            f'Booking {booking.reference} is now '
            f'{booking.get_status_display().lower()}',
            f'Your booking for {booking.hire_car} has been updated to '
            f'{booking.get_status_display()}.',
            level=(
                'warning'
                if booking.status in ('rejected', 'cancelled')
                else 'info'
            ),
            obj=booking,
            url=reverse('hiring:hire_booking_detail', args=[booking.pk]),
        )

    return redirect(_safe_next(request) or 'hiring:staff_hire_bookings')
