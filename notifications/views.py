from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from .models import Notification


def _safe_next(request, default):
    """Only follow a ``next`` value that stays on this site."""
    target = request.POST.get('next', '')
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return default


class NotificationListView(LoginRequiredMixin, ListView):
    """The signed-in user's own notifications, newest first."""

    model = Notification
    template_name = 'notifications/list.html'
    context_object_name = 'notifications'
    paginate_by = 25

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


@login_required
def notification_open(request, pk):
    """Mark one notification read, then follow its link when it is safe."""
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.mark_read()

    target = notification.url
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)
    return redirect('notifications:list')


@login_required
@require_POST
def notification_mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.mark_read()
    return redirect(_safe_next(request, reverse('notifications:list')))


@login_required
@require_POST
def notifications_mark_all_read(request):
    request.user.notifications.filter(is_read=False).update(
        is_read=True, read_at=timezone.now(),
    )
    return redirect(_safe_next(request, reverse('notifications:list')))
