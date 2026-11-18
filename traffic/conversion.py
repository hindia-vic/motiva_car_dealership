"""Conversion funnel analytics.

The traffic dashboard answers "how many people were here?". This module
answers the question that actually matters: what did they do?

A visitor who reads three pages and leaves is not a lead. A visitor who
places an order is worth chasing. The funnel is worked out from the
conversion records themselves - inquiries, orders, test drives and sales -
each of which carries a copy of the visitor token and of the source the
visitor arrived from.

Nothing here needs a third-party package.
"""

from django.db.models import Count, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from .analytics import VISITOR_COOKIE
from .models import PageView

#: Source used when a visitor arrived without a referrer we could read.
DEFAULT_SOURCE = 'Direct'


def visitor_id_from(request):
    """The anonymous visitor token from the request cookie, if there is one."""
    return (request.COOKIES.get(VISITOR_COOKIE) or '')[:64]


def source_for_visitor(visitor_id):
    """The source a visitor arrived from, copied onto a conversion.

    The first source that is not an internal jump is used: a visitor who
    lands on the site from Google and then browses around should still be
    credited to Google when they place an order an hour later.
    """
    if not visitor_id:
        return ''

    source = (
        PageView.objects.filter(visitor_id=visitor_id)
        .exclude(source__in=['', 'Internal'])
        .order_by('created_at')
        .values_list('source', flat=True)
        .first()
    )
    if source:
        return source

    source = (
        PageView.objects.filter(visitor_id=visitor_id)
        .order_by('created_at')
        .values_list('source', flat=True)
        .first()
    )
    return source or ''


def _first_source_per_visitor(since):
    """``visitor_id -> source`` for the visitors seen since ``since``."""
    first_source = (
        PageView.objects.filter(visitor_id=OuterRef('visitor_id'))
        .exclude(source__in=['', 'Internal'])
        .order_by('created_at')
        .values('source')[:1]
    )
    rows = (
        PageView.objects.filter(created_at__gte=since)
        .values('visitor_id')
        .annotate(source=Coalesce(Subquery(first_source), Value(DEFAULT_SOURCE)))
        .values_list('visitor_id', 'source')
    )
    return dict(rows)


def _conversion_models():
    """The models that record a conversion, imported lazily."""
    from cars.models import Appointment, Car, Inquiry, Order, SalesTransaction

    return Inquiry, Order, Appointment, SalesTransaction, Car


def funnel_report(since):
    """The visitor -> inquiry -> order -> sale funnel for a period.

    Returns a dictionary with the headline numbers, a breakdown by
    source, and the vehicles that convert best.
    """
    Inquiry, Order, Appointment, SalesTransaction, _ = _conversion_models()

    visitors = PageView.objects.filter(created_at__gte=since)
    visitor_count = visitors.values('visitor_id').distinct().count()

    inquiries = Inquiry.objects.filter(created_at__gte=since)
    orders = Order.objects.filter(order_date__gte=since)
    appointments = Appointment.objects.filter(created_at__gte=since)
    sales = SalesTransaction.objects.filter(sale_date__gte=since, status='completed')

    inquiry_count = inquiries.count()
    order_count = orders.count()
    appointment_count = appointments.count()
    sale_count = sales.count()

    report = {
        'visitors': visitor_count,
        'inquiries': inquiry_count,
        'orders': order_count,
        'appointments': appointment_count,
        'sales': sale_count,
        'inquiry_rate': _rate(inquiry_count, visitor_count),
        'order_rate': _rate(order_count, visitor_count),
        'appointment_rate': _rate(appointment_count, visitor_count),
        'sale_rate': _rate(sale_count, visitor_count),
        'steps': [],
        'by_source': [],
        'by_car': [],
    }

    report['steps'] = [
        {
            'label': 'Visitors',
            'count': visitor_count,
            'rate': 100.0 if visitor_count else 0.0,
        },
        {
            'label': 'Inquiries',
            'count': inquiry_count,
            'rate': report['inquiry_rate'],
        },
        {
            'label': 'Orders',
            'count': order_count,
            'rate': report['order_rate'],
        },
        {
            'label': 'Sales',
            'count': sale_count,
            'rate': report['sale_rate'],
        },
    ]

    report['by_source'] = _by_source(since)
    report['by_car'] = _by_car(since)
    return report


def _rate(count, total):
    """A percentage of ``total``, rounded to one decimal."""
    if not total:
        return 0.0
    return round(count / total * 100, 1)


def _by_source(since):
    """Visitors, leads and revenue per source."""
    Inquiry, Order, Appointment, SalesTransaction, _ = _conversion_models()

    visitor_sources = _first_source_per_visitor(since)
    visitors_by_source = {}
    for source in visitor_sources.values():
        visitors_by_source[source] = visitors_by_source.get(source, 0) + 1

    inquiries_by_source = {}
    orders_by_source = {}
    appointments_by_source = {}
    # The visitors behind each source, so the lead rate is the share of
    # visitors who became a lead - not the share of lead records. A
    # visitor who inquires and then orders is one converting visitor, not
    # two. A lead with no visitor token (an old one, or one entered in the
    # office) is counted as one converting visitor of its own.
    converting_visitors = {}
    untokenized_leads = {}

    def _count(bucket, source, visitor_id):
        source = source or DEFAULT_SOURCE
        bucket[source] = bucket.get(source, 0) + 1
        if visitor_id:
            converting_visitors.setdefault(source, set()).add(visitor_id)

    def _count_lead(bucket, source, visitor_id):
        source = source or DEFAULT_SOURCE
        _count(bucket, source, visitor_id)
        if not visitor_id:
            untokenized_leads[source] = untokenized_leads.get(source, 0) + 1

    for source, visitor_id in (
        Inquiry.objects.filter(created_at__gte=since).values_list('source', 'visitor_id')
    ):
        _count_lead(inquiries_by_source, source, visitor_id)

    for source, visitor_id in (
        Order.objects.filter(order_date__gte=since).values_list('source', 'visitor_id')
    ):
        _count_lead(orders_by_source, source, visitor_id)

    for source, visitor_id in (
        Appointment.objects.filter(created_at__gte=since).values_list('source', 'visitor_id')
    ):
        _count(appointments_by_source, source, visitor_id)

    # Revenue only exists for sales that were linked back to the online
    # order they came from; sales recorded in the office have no source.
    revenue_by_source = {}
    sales_by_source = {}
    linked_sales = (
        SalesTransaction.objects
        .filter(sale_date__gte=since, status='completed', order__isnull=False)
        .values('order__source')
        .annotate(total=Sum('total_amount'), count=Count('id'))
    )
    for row in linked_sales:
        source = row['order__source'] or DEFAULT_SOURCE
        revenue_by_source[source] = revenue_by_source.get(source, 0) + float(row['total'] or 0)
        sales_by_source[source] = sales_by_source.get(source, 0) + row['count']

    sources = set(visitors_by_source) | set(inquiries_by_source) | set(orders_by_source)
    sources |= set(appointments_by_source) | set(revenue_by_source)

    rows = []
    for source in sources:
        visitors = visitors_by_source.get(source, 0)
        inquiries = inquiries_by_source.get(source, 0)
        orders = orders_by_source.get(source, 0)
        leads = inquiries + orders
        converted = (
            len(converting_visitors.get(source, ()))
            + untokenized_leads.get(source, 0)
        )
        rows.append({
            'source': source,
            'visitors': visitors,
            'inquiries': inquiries,
            'orders': orders,
            'appointments': appointments_by_source.get(source, 0),
            'sales': sales_by_source.get(source, 0),
            'leads': leads,
            'converting_visitors': converted,
            'conversion_rate': _rate(converted, visitors),
            'revenue': revenue_by_source.get(source, 0),
        })

    rows.sort(key=lambda row: (row['visitors'], row['leads']), reverse=True)
    return rows[:15]


def _by_car(since, limit=10):
    """The vehicles that turn page views into leads."""
    Inquiry, Order, Appointment, SalesTransaction, Car = _conversion_models()

    views = (
        PageView.objects.filter(created_at__gte=since, car__isnull=False)
        .values('car_id')
        .annotate(
            views=Count('id'),
            visitors=Count('visitor_id', distinct=True),
        )
    )
    view_rows = {row['car_id']: row for row in views}

    inquiries_by_car = {
        row['car_id']: row['count']
        for row in Inquiry.objects.filter(created_at__gte=since)
        .values('car_id').annotate(count=Count('id'))
    }
    orders_by_car = {
        row['car_id']: row['count']
        for row in Order.objects.filter(order_date__gte=since)
        .values('car_id').annotate(count=Count('id'))
    }
    appointments_by_car = {
        row['car_id']: row['count']
        for row in Appointment.objects.filter(created_at__gte=since)
        .values('car_id').annotate(count=Count('id'))
    }
    sales_by_car = {
        row['car_id']: row['count']
        for row in SalesTransaction.objects
        .filter(sale_date__gte=since, status='completed')
        .values('car_id').annotate(count=Count('id'))
    }

    # The viewers behind each vehicle's leads, so the rate is the share of
    # viewers who became a lead rather than the share of lead records.
    lead_visitors = {}
    untokenized_leads = {}
    for model, date_field in ((Inquiry, 'created_at'), (Order, 'order_date')):
        for car_id, visitor_id in (
            model.objects.filter(**{f'{date_field}__gte': since})
            .values_list('car_id', 'visitor_id')
        ):
            if visitor_id:
                lead_visitors.setdefault(car_id, set()).add(visitor_id)
            else:
                untokenized_leads[car_id] = untokenized_leads.get(car_id, 0) + 1

    rows = []
    cars = {
        car.pk: car
        for car in Car.objects.filter(pk__in=list(view_rows))
    }
    for car_id, view_row in view_rows.items():
        inquiries = inquiries_by_car.get(car_id, 0)
        orders = orders_by_car.get(car_id, 0)
        appointments = appointments_by_car.get(car_id, 0)
        sales = sales_by_car.get(car_id, 0)
        leads = inquiries + orders
        converted = (
            len(lead_visitors.get(car_id, ()))
            + untokenized_leads.get(car_id, 0)
        )
        rows.append({
            'car': cars.get(car_id),
            'car_id': car_id,
            'views': view_row['views'],
            'visitors': view_row['visitors'],
            'inquiries': inquiries,
            'orders': orders,
            'appointments': appointments,
            'sales': sales,
            'leads': leads,
            'converting_visitors': converted,
            'conversion_rate': _rate(converted, view_row['visitors']),
        })

    rows.sort(key=lambda row: (row['leads'], row['views']), reverse=True)
    return rows[:limit]


def conversion_rows(since):
    """Flat rows for the CSV export: one row per source."""
    rows = []
    for row in _by_source(since):
        rows.append({
            'source': row['source'],
            'visitors': row['visitors'],
            'inquiries': row['inquiries'],
            'orders': row['orders'],
            'appointments': row['appointments'],
            'sales': row['sales'],
            'leads': row['leads'],
            'conversion_rate': row['conversion_rate'],
            'revenue': round(row['revenue'], 2),
        })
    return rows
