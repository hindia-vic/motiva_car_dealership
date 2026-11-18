"""Project-level views (not tied to a single app)."""

from django.http import JsonResponse
from django.shortcuts import render


def preview_404(request):
    """Render the branded 404 page locally.

    Only wired up when ``DEBUG`` is on (see ``config/urls.py``). With DEBUG on
    Django always shows its technical "Page not found" page instead of
    ``404.html``, so this route makes the real design reviewable without
    switching the whole project to production mode.
    """
    return render(request, '404.html', status=404)


def health(request):
    """Liveness probe for platform / uptime monitors.

    Returns 200 as long as the web process is serving. Deliberately does no
    database access, session work, or template rendering so a probe is cheap
    and never fails for reasons other than the process itself being down.
    """
    return JsonResponse({'status': 'ok'})
