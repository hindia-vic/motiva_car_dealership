from django.db import migrations


TESTIMONIALS = [
    {
        'customer_name': 'Sandra M.',
        'vehicle': '2023 Toyota Camry',
        'quote': ('Financing was completely seamless and the price was exactly what we '
                  'agreed on. No pressure, no surprises \u2014 they made buying a car '
                  'genuinely easy.'),
    },
    {
        'customer_name': 'Marcus T.',
        'vehicle': '2023 Ford F-150',
        'quote': ('I needed a truck for work hauling and they were upfront about every '
                  'detail of the condition. Best towing value I found anywhere in the region.'),
    },
    {
        'customer_name': 'Priya K.',
        'vehicle': '2021 Chevrolet Equinox',
        'quote': ('The Equinox fit our family perfectly, and their team checked in with '
                  'us weeks after the sale to make sure everything was going well. '
                  'That support matters.'),
    },
]


def seed_testimonials(apps, schema_editor):
    Testimonial = apps.get_model('cars', 'Testimonial')
    for item in TESTIMONIALS:
        Testimonial.objects.create(
            customer_name=item['customer_name'],
            vehicle=item['vehicle'],
            quote=item['quote'],
            rating=5,
            is_visible=True,
        )


def unseed_testimonials(apps, schema_editor):
    Testimonial = apps.get_model('cars', 'Testimonial')
    Testimonial.objects.filter(
        customer_name__in=[item['customer_name'] for item in TESTIMONIALS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cars', '0004_contactmessage_newslettersubscription_testimonial_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_testimonials, unseed_testimonials),
    ]