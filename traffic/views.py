"""Staff-facing traffic analytics views."""

from datetime import timedelta

from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import TruncDate
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from .analytics import PERIODS, page_label, parse_period
from .conversion import funnel_report
from .models import PageView


class TrafficView(View):
    """Staff view: website traffic analytics."""

    def get(self, request):
        if not request.user.is_staff:
            return redirect('cars:home')

        days = parse_period(request.GET.get('days'))
        now = timezone.now()
        since = now - timedelta(days=days)
        views = PageView.objects.filter(created_at__gte=since)

        total_views = views.count()
        unique_visitors = views.values('visitor_id').distinct().count()
        single_view_visitors = (
            views.values('visitor_id')
            .annotate(pageviews=Count('id'))
            .filter(pageviews=1)
            .count()
        )

        # The window immediately before this one, for a like-for-like comparison.
        previous = PageView.objects.filter(
            created_at__gte=since - timedelta(days=days),
            created_at__lt=since,
        )
        previous_views = previous.count()
        previous_visitors = previous.values('visitor_id').distinct().count()

        context = {
            'days': days,
            'periods': PERIODS,
            'total_views': total_views,
            'unique_visitors': unique_visitors,
            'avg_pages_per_visit': (
                round(total_views / unique_visitors, 2) if unique_visitors else 0
            ),
            'bounce_rate': (
                round(single_view_visitors / unique_visitors * 100, 1)
                if unique_visitors else 0
            ),
            'views_change': _percent_change(total_views, previous_views),
            'visitors_change': _percent_change(unique_visitors, previous_visitors),
            'daily_traffic': self._daily_series(views, days),
            'sources': list(
                views.values('source')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            ),
            'devices': list(
                views.values('device')
                .annotate(count=Count('id'))
                .order_by('-count')
            ),
            'browsers': list(
                views.values('browser')
                .annotate(count=Count('id'))
                .order_by('-count')[:8]
            ),
            'top_pages': [
                {
                    'label': page_label(row['url_name'], row['path']),
                    'path': row['path'],
                    'count': row['count'],
                }
                for row in views.values('path', 'url_name')
                .annotate(count=Count('id'))
                .order_by('-count')[:15]
            ],
            'top_cars': list(
                views.filter(car__isnull=False)
                .values('car__id', 'car__year', 'car__make', 'car__model')
                .annotate(
                    views=Count('id'),
                    visitors=Count('visitor_id', distinct=True),
                )
                .order_by('-views')[:10]
            ),
            'top_referrers': list(
                views.exclude(referrer='')
                .exclude(source__in=['Internal', 'Direct'])
                .values('referrer', 'source')
                .annotate(count=Count('id'))
                .order_by('-count')[:15]
            ),
            'landing_pages': list(
                self._landing_pages(views)
                .values('path')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            ),
            'campaigns': list(
                views.exclude(utm_source='')
                .values('utm_source', 'utm_campaign')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            ),
            'funnel': funnel_report(since),
        }
        return render(request, 'traffic/traffic.html', context)

    # -- internals ----------------------------------------------------

    def _daily_series(self, views, days):
        """A gap-free per-day series of views and unique visitors."""
        by_day = {
            row['day']: row
            for row in views.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(
                views=Count('id'),
                visitors=Count('visitor_id', distinct=True),
            )
        }

        today = timezone.localtime().date()
        series = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            row = by_day.get(day)
            series.append({
                'label': day.strftime('%b %d'),
                'views': row['views'] if row else 0,
                'visitors': row['visitors'] if row else 0,
            })
        return series

    def _landing_pages(self, views):
        """The pages each visitor landed on first within the period."""
        return views.filter(
            pk__in=Subquery(
                views.filter(visitor_id=OuterRef('visitor_id'))
                .order_by('created_at', 'pk')
                .values('pk')[:1]
            )
        )


def _percent_change(current, previous):
    """Percentage change against the previous period, rounded to one decimal."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)
