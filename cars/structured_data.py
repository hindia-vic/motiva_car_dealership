"""schema.org structured data (JSON-LD) for the public pages.

Every node is a plain dict so it can be unit-tested without a template.
Templates never hand-build JSON: they receive already-serialised strings
from :func:`json_ld`, which escapes the characters that could otherwise
close the surrounding ``<script>`` tag.
"""

import json
from decimal import Decimal

from django.conf import settings

from .money import currency_code

#: Characters that must not appear raw inside a ``<script>`` block. ``json.dumps``
#: does not escape them, so a car description containing ``</script>`` would
#: otherwise break out of the tag.
_JSON_ESCAPES = {
    '<': '\\u003c',
    '>': '\\u003e',
    '&': '\\u0026',
    '\u2028': '\\u2028',
    '\u2029': '\\u2029',
}

#: schema.org condition URL per ``Car.condition`` choice.
_ITEM_CONDITION = {
    'new': 'https://schema.org/NewCondition',
    'used': 'https://schema.org/UsedCondition',
    'certified': 'https://schema.org/UsedCondition',
}

#: schema.org availability URL per ``Car.status``.
_AVAILABILITY = {
    'available': 'https://schema.org/InStock',
    'sold': 'https://schema.org/SoldOut',
    'reserved': 'https://schema.org/OutOfStock',
    'maintenance': 'https://schema.org/OutOfStock',
}


def json_ld(node):
    """Serialise a node as JSON that is safe inside a ``<script>`` element."""
    raw = json.dumps(node, ensure_ascii=False, separators=(',', ':'))
    for char, escaped in _JSON_ESCAPES.items():
        raw = raw.replace(char, escaped)
    return raw


def absolute_url(request, path):
    """Turn a path or a storage URL into an absolute URL.

    Falls back to ``SITE_BASE_URL`` when there is no request (management
    commands), and to an empty string when neither is available.
    """
    if not path:
        return ''
    if path.startswith(('http://', 'https://')):
        return path
    if request is not None:
        return request.build_absolute_uri(path)
    base = getattr(settings, 'SITE_BASE_URL', '').rstrip('/')
    return f'{base}{path}' if base else ''


def _image_url(request, image_field):
    if not image_field:
        return ''
    try:
        return absolute_url(request, image_field.url)
    except (ValueError, AttributeError):
        return ''


def _price(value):
    """A schema.org price is a string, never a float."""
    if value is None:
        return ''
    return f'{Decimal(value):.2f}'


def _dealer_base(request):
    """The dealership node shared by the home page and the seller offer."""
    from .models import ContactInfo, DealershipInfo

    try:
        info = DealershipInfo.get_solo()
    except Exception:
        info = None
    try:
        contact = ContactInfo.get_solo()
    except Exception:
        contact = None

    name = getattr(info, 'name', '') or DealershipInfo.DEFAULT_NAME
    node = {
        '@type': 'AutoDealer',
        '@id': absolute_url(request, '/') or None,
        'name': name,
        'url': absolute_url(request, '/') or None,
    }
    logo = _image_url(request, getattr(info, 'logo', None))
    if logo:
        node['logo'] = logo
        node['image'] = logo
    if contact is not None:
        if contact.phone:
            node['telephone'] = contact.phone
        if contact.email:
            node['email'] = contact.email
        if contact.address:
            node['address'] = {
                '@type': 'PostalAddress',
                'streetAddress': contact.address.strip(),
                'addressCountry': 'KE',
            }
        if contact.hours:
            node['openingHours'] = contact.hours.strip()
    # ``None`` values are dropped by the caller's JSON serialiser only if we
    # remove them here; keep the node clean.
    return {key: value for key, value in node.items() if value not in (None, '')}


def website_node(request):
    """A ``WebSite`` with a sitelink search box for the inventory.

    Paired with the ``AutoDealer`` node on the home page so a search engine
    knows which URL to offer as the site's search action.
    """
    from django.urls import reverse

    dealer = _dealer_base(request)
    # Append the template query after building the absolute URL: build_absolute_uri
    # percent-encodes braces, which would stop Google from recognising the
    # ``search_term_string`` placeholder in a SearchAction target.
    search_base = absolute_url(request, reverse('cars:advanced_search'))
    search_url = f'{search_base}?q={{search_term_string}}' if search_base else ''
    node = {
        '@context': 'https://schema.org',
        '@type': 'WebSite',
        '@id': absolute_url(request, '/') or None,
        'name': dealer['name'],
        'url': absolute_url(request, '/') or None,
        'publisher': {'@id': dealer.get('@id') or absolute_url(request, '/')},
    }
    if search_url:
        node['potentialAction'] = {
            '@type': 'SearchAction',
            'target': search_url,
            'query-input': 'required name=search_term_string',
        }
    return {key: value for key, value in node.items() if value not in (None, '')}


#: Questions and answers visible on the FAQ page. Kept here so the JSON-LD can
#: be unit-tested without a database; the page itself remains the source a
#: visitor reads.
FAQ_ENTRIES = (
    (
        'Do you offer financing?',
        'Yes. We offer auto loans, leases, and financing for first-time buyers. '
        'Learn more about our financing options, or use the payment calculator '
        'on any vehicle page to estimate your monthly payment.',
    ),
    (
        'Can I trade in my current vehicle?',
        'Absolutely. We offer free appraisals and apply the trade-in value toward '
        'your purchase. Just mention it when you place an order or contact us.',
    ),
    (
        'How do I book a test drive?',
        "Open any vehicle's detail page and click Book a Test Drive. Pick a date "
        'and time, and we will confirm your appointment by email.',
    ),
    (
        'Are the vehicles inspected before sale?',
        'Yes. Every vehicle passes our multi-point inspection, and certified '
        "pre-owned vehicles come with additional coverage. See the service "
        "history on any vehicle's detail page.",
    ),
    (
        'What do I need to buy a car?',
        "A valid driver's license, proof of insurance, and a form of payment or "
        'financing approval. If you are financing, we will walk you through '
        'the application with our finance team.',
    ),
    (
        "Can you help me find a vehicle that isn't listed?",
        'Yes — tell us what you are looking for and we can source it for you. '
        'You can also save a search on our browse page and we will email you '
        'when a matching vehicle arrives.',
    ),
    (
        'What are your hours and location?',
        'Find our address, phone, email, and opening hours on the contact page.',
    ),
)


def faq_node(request, entries=None):
    """An ``FAQPage`` built from the questions shown on the FAQ page."""
    from django.urls import reverse

    items = entries if entries is not None else FAQ_ENTRIES
    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        '@id': absolute_url(request, reverse('cars:faq')),
        'mainEntity': [
            {
                '@type': 'Question',
                'name': question,
                'acceptedAnswer': {'@type': 'Answer', 'text': answer},
            }
            for question, answer in items
        ],
    }


def dealer_node(request, testimonials=None):
    """The dealership, optionally carrying its review aggregate."""
    node = _dealer_base(request)
    node['@context'] = 'https://schema.org'

    reviews = list(testimonials or [])
    if reviews:
        ratings = [review.rating for review in reviews if review.rating]
        if ratings:
            node['aggregateRating'] = {
                '@type': 'AggregateRating',
                'ratingValue': f'{sum(ratings) / len(ratings):.1f}',
                'reviewCount': len(ratings),
                'bestRating': 5,
                'worstRating': 1,
            }
        node['review'] = [
            {
                '@type': 'Review',
                'author': {'@type': 'Person', 'name': review.customer_name},
                'reviewBody': review.quote,
                'reviewRating': {
                    '@type': 'Rating',
                    'ratingValue': review.rating,
                    'bestRating': 5,
                    'worstRating': 1,
                },
            }
            for review in reviews[:10]
        ]
    return node


def vehicle_node(car, request):
    """A ``Vehicle`` with its ``Offer``, ready for Google's vehicle listings."""
    from django.urls import reverse

    url = absolute_url(request, reverse('cars:car_detail', args=[car.pk]))
    name = f'{car.year} {car.make} {car.model}'

    images = []
    for image in car.images.all():
        image_url = _image_url(request, image.image)
        if image_url:
            images.append(image_url)

    node = {
        '@context': 'https://schema.org',
        '@type': 'Vehicle',
        'name': name,
        'url': url,
        'brand': {'@type': 'Brand', 'name': car.make},
        'model': car.model,
        'vehicleModelDate': str(car.year),
        'vehicleIdentificationNumber': car.vin,
        'color': car.color,
        'bodyType': car.get_body_type_display(),
        'vehicleTransmission': car.get_transmission_display(),
        'fuelType': car.get_fuel_type_display(),
        'mileageFromOdometer': {
            '@type': 'QuantitativeValue',
            'value': car.mileage,
            'unitCode': 'KMT',
        },
        'itemCondition': _ITEM_CONDITION.get(
            car.condition, 'https://schema.org/UsedCondition'
        ),
        'offers': {
            '@type': 'Offer',
            'price': _price(car.asking_price),
            'priceCurrency': currency_code(),
            'availability': _AVAILABILITY.get(
                car.status, 'https://schema.org/OutOfStock'
            ),
            'url': url,
            'seller': _dealer_base(request),
        },
    }
    if images:
        node['image'] = images
    if car.engine_size:
        node['vehicleEngine'] = {
            '@type': 'EngineSpecification',
            'engineDisplacement': car.engine_size,
        }
    if car.description:
        node['description'] = car.description
    return node


def breadcrumb_node(request, items):
    """Build a ``BreadcrumbList`` from ``(name, path_or_None)`` pairs."""
    elements = []
    for position, (name, path) in enumerate(items, start=1):
        element = {
            '@type': 'ListItem',
            'position': position,
            'name': name,
        }
        if path:
            element['item'] = absolute_url(request, path)
        elements.append(element)
    return {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': elements,
    }


def blog_posting_node(post, request):
    """A ``BlogPosting`` for a published news article."""
    from django.urls import reverse

    url = absolute_url(request, reverse('cars:blog_detail', args=[post.slug]))
    dealer = _dealer_base(request)
    node = {
        '@context': 'https://schema.org',
        '@type': 'BlogPosting',
        'headline': post.title,
        'url': url,
        'mainEntityOfPage': {'@type': 'WebPage', '@id': url},
        'datePublished': post.published_at.isoformat(),
        'dateModified': post.updated_at.isoformat(),
        'author': {'@type': 'Organization', 'name': dealer['name']},
        'publisher': dealer,
    }
    if post.excerpt:
        node['description'] = post.excerpt
    cover = _image_url(request, post.cover_image)
    if cover:
        node['image'] = cover
    return node
