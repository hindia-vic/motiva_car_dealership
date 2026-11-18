"""Machine-readable vehicle feeds.

Two representations of the same inventory:

* ``/feeds/vehicles.json`` — for integrations, partners and ad platforms;
* ``/feeds/vehicles.xml`` — for crawlers and anything that wants XML.

Only **available** cars are advertised. Sold and reserved cars stay in the
sitemap so old links keep working, but a feed is a sales channel and must
never ship a car a customer can no longer buy.

Both endpoints support conditional GET (``ETag`` / ``Last-Modified``) and
carry a short ``Cache-Control`` so a polling partner cannot hammer the
database.
"""

import xml.etree.ElementTree as ET
from decimal import Decimal

from django.db.models import Count, Max
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import condition

from .models import Car
from .money import currency_code

#: How long a partner may cache a feed response.
FEED_CACHE_SECONDS = 900

#: Statuses that may appear in the feed.
FEED_STATUSES = ('available',)

#: Cap on photos per vehicle so a feed stays a reasonable size.
MAX_IMAGES = 12


def vehicle_queryset():
    """Available cars, with their photos, newest change first."""
    return (
        Car.objects.filter(status__in=FEED_STATUSES)
        .prefetch_related('images')
        .order_by('-last_updated')
    )


def _absolute(request, path):
    if not path:
        return ''
    if path.startswith(('http://', 'https://')):
        return path
    return request.build_absolute_uri(path)


def _images(car, request):
    urls = []
    for image in car.images.all()[:MAX_IMAGES]:
        if not image.image:
            continue
        try:
            urls.append(_absolute(request, image.image.url))
        except (ValueError, AttributeError):
            continue
    return urls


def serialize_vehicle(car, request):
    """One vehicle as a plain dict, shared by the JSON and XML writers."""
    return {
        'id': car.pk,
        'vin': car.vin,
        'make': car.make,
        'model': car.model,
        'year': car.year,
        'condition': car.get_condition_display(),
        'body_type': car.get_body_type_display(),
        'transmission': car.get_transmission_display(),
        'fuel_type': car.get_fuel_type_display(),
        'mileage': car.mileage,
        'color': car.color,
        'price': f'{Decimal(car.asking_price):.2f}',
        'currency': currency_code(),
        'availability': 'in stock',
        'url': _absolute(request, reverse('cars:car_detail', args=[car.pk])),
        'images': _images(car, request),
        'date_added': car.date_added.isoformat(),
        'date_modified': car.last_updated.isoformat(),
    }


def vehicle_feed_payload(request):
    vehicles = [serialize_vehicle(car, request) for car in vehicle_queryset()]
    return {
        'generated_at': timezone.now().isoformat(),
        'count': len(vehicles),
        'currency': currency_code(),
        'vehicles': vehicles,
    }


def vehicle_feed_etag(request):
    """Cheap version tag: row count plus the newest change."""
    summary = vehicle_queryset().aggregate(
        total=Count('pk'), newest=Max('last_updated'),
    )
    newest = summary['newest']
    stamp = int(newest.timestamp()) if newest else 0
    return f'"{summary["total"]}-{stamp}"'


def vehicle_feed_last_modified(request):
    return vehicle_queryset().aggregate(newest=Max('last_updated'))['newest']


def _cache_headers(response):
    response['Cache-Control'] = f'public, max-age={FEED_CACHE_SECONDS}'
    return response


@condition(
    etag_func=vehicle_feed_etag,
    last_modified_func=vehicle_feed_last_modified,
)
def vehicle_feed_json(request):
    payload = vehicle_feed_payload(request)
    response = JsonResponse(payload, json_dumps_params={'ensure_ascii': False})
    response['Content-Type'] = 'application/json; charset=utf-8'
    return _cache_headers(response)


def _text(parent, tag, value):
    """Append ``<tag>value</tag>`` when the value is present."""
    if value in (None, ''):
        return
    element = ET.SubElement(parent, tag)
    element.text = str(value)


@condition(
    etag_func=vehicle_feed_etag,
    last_modified_func=vehicle_feed_last_modified,
)
def vehicle_feed_xml(request):
    payload = vehicle_feed_payload(request)

    root = ET.Element('vehicles')
    root.set('generated_at', payload['generated_at'])
    root.set('count', str(payload['count']))
    root.set('currency', payload['currency'])

    for vehicle in payload['vehicles']:
        item = ET.SubElement(root, 'vehicle')
        _text(item, 'id', vehicle['id'])
        _text(item, 'vin', vehicle['vin'])
        _text(item, 'make', vehicle['make'])
        _text(item, 'model', vehicle['model'])
        _text(item, 'year', vehicle['year'])
        _text(item, 'condition', vehicle['condition'])
        _text(item, 'body_type', vehicle['body_type'])
        _text(item, 'transmission', vehicle['transmission'])
        _text(item, 'fuel_type', vehicle['fuel_type'])
        _text(item, 'mileage', vehicle['mileage'])
        _text(item, 'color', vehicle['color'])
        _text(item, 'price', vehicle['price'])
        _text(item, 'currency', vehicle['currency'])
        _text(item, 'availability', vehicle['availability'])
        _text(item, 'url', vehicle['url'])
        _text(item, 'date_added', vehicle['date_added'])
        _text(item, 'date_modified', vehicle['date_modified'])
        images = ET.SubElement(item, 'images')
        for url in vehicle['images']:
            _text(images, 'image', url)

    body = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    response = HttpResponse(body, content_type='application/xml; charset=utf-8')
    return _cache_headers(response)
