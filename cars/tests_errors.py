"""Tests for the branded error pages."""

from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(DEBUG=False)
class CustomNotFoundPageTests(TestCase):
    def test_unknown_url_uses_the_custom_404_page(self):
        response = self.client.get('/this-page-does-not-exist/')

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertContains(response, '404', status_code=404)
        self.assertContains(response, 'Wrong Turn', status_code=404)
        self.assertContains(response, 'noindex, nofollow', status_code=404)

    def test_404_page_offers_inventory_search_and_useful_links(self):
        response = self.client.get('/still-missing/')

        self.assertContains(
            response,
            f'action="{reverse("cars:browse_cars")}"',
            status_code=404,
        )
        self.assertContains(response, 'name="search"', status_code=404)
        self.assertContains(response, reverse('cars:home'), status_code=404)
        self.assertContains(response, reverse('cars:contact'), status_code=404)
        self.assertContains(response, reverse('cars:faq'), status_code=404)

    def test_missing_object_also_uses_the_custom_page(self):
        response = self.client.get('/car/999999/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Wrong Turn', status_code=404)
