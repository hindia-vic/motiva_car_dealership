import json
from datetime import date
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    Car, Customer, SalesTransaction, ServiceRecord, Inquiry, Order,
    Appointment, ContactMessage, NewsletterSubscription, Testimonial, ContactInfo,
    SavedSearch, AboutInfo, DealershipInfo, ListingRequest, FinancingApplication,
)
from .antispam import AntiSpamMixin
from .tradein import BODY_TYPES, CONDITION_CHOICES as TRADE_IN_CONDITION_CHOICES
from .images import validate_image_upload
from .money import format_money
from .financing import (
    amount_financed, interest_rate, min_deposit, monthly_payment, affordability_ok,
)


class MultipleImageInput(forms.ClearableFileInput):
    """File input allowing multiple image selection"""
    allow_multiple_selected = True


class InquiryForm(AntiSpamMixin, forms.ModelForm):
    """Form for customer inquiries"""
    class Meta:
        model = Inquiry
        fields = ['customer_name', 'customer_email', 'customer_phone', 'message']
        widgets = {
            'customer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your Full Name'
            }),
            'customer_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'your.email@example.com'
            }),
            'customer_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '(555) 123-4567'
            }),
            'message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Tell us about your interest in this vehicle...'
            }),
        }


class OrderForm(AntiSpamMixin, forms.ModelForm):
    """Form for customer orders"""
    class Meta:
        model = Order
        fields = ['customer_name', 'customer_email', 'customer_phone', 'customer_address',
                  'price', 'trade_in_value', 'down_payment', 'financing_needed', 'notes',
                  'trade_in_year', 'trade_in_make', 'trade_in_model', 'trade_in_mileage',
                  'trade_in_condition', 'trade_in_body_type', 'trade_in_estimate']
        widgets = {
            'customer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your Full Name'
            }),
            'customer_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'your.email@example.com'
            }),
            'customer_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '(555) 123-4567'
            }),
            'customer_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Your delivery address'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Purchase price'
            }),
            'trade_in_value': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Trade-in value (if any)',
                'value': '0.00'
            }),
            'down_payment': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Down payment amount',
                'value': '0.00'
            }),
            'financing_needed': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional notes...'
            }),
            'trade_in_year': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Year',
                'min': '1900',
            }),
            'trade_in_make': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Make',
            }),
            'trade_in_model': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Model',
            }),
            'trade_in_mileage': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Mileage',
                'min': '0',
            }),
            'trade_in_condition': forms.Select(attrs={
                'class': 'form-control',
            }),
            'trade_in_body_type': forms.Select(attrs={
                'class': 'form-control',
            }),
            'trade_in_estimate': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('trade_in_year', 'trade_in_make', 'trade_in_model',
                     'trade_in_mileage', 'trade_in_condition', 'trade_in_body_type',
                     'trade_in_estimate'):
            self.fields[name].required = False
        self.fields['trade_in_condition'].choices = [
            ('', 'Not sure')] + list(TRADE_IN_CONDITION_CHOICES)
        self.fields['trade_in_body_type'].choices = [
            ('', 'Not sure')] + [
            (value, value.replace('_', ' ').title()) for value in BODY_TYPES
        ]


class TradeInForm(forms.Form):
    """The form on the trade-in valuation page."""
    year = forms.IntegerField(
        min_value=1900,
        max_value=date.today().year + 1,
        label='Year',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. 2018',
        }),
    )
    make = forms.CharField(
        max_length=100,
        label='Make',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Toyota',
        }),
    )
    model = forms.CharField(
        max_length=100,
        required=False,
        label='Model',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Camry',
        }),
    )
    mileage = forms.IntegerField(
        min_value=0,
        required=False,
        label='Mileage',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. 68000',
        }),
    )
    condition = forms.ChoiceField(
        choices=TRADE_IN_CONDITION_CHOICES,
        initial='good',
        label='Condition',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    body_type = forms.ChoiceField(
        required=False,
        choices=[('', 'Not sure')] + [
            (value, value.replace('_', ' ').title()) for value in BODY_TYPES
        ],
        label='Body type',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def clean_year(self):
        year = self.cleaned_data['year']
        if year > date.today().year + 1:
            raise ValidationError('That year is in the future.')
        return year


class CarForm(forms.ModelForm):
    """Form for creating/editing cars"""
    images = forms.Field(
        required=False,
        widget=MultipleImageInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
        }),
        help_text="The first photo becomes the main photo (jpg/png).",
    )

    class Meta:
        model = Car
        fields = [
            'make', 'model', 'year', 'vin', 'color', 'body_type',
            'transmission', 'fuel_type', 'mileage', 'engine_size', 'horsepower',
            'purchase_price', 'asking_price', 'condition', 'status',
            'air_conditioning', 'power_steering', 'power_windows', 'power_locks',
            'cruise_control', 'backup_camera', 'bluetooth', 'navigation_system',
            'leather_seats', 'sunroof', 'all_wheel_drive', 'description'
        ]
        widgets = {
            'make': forms.TextInput(attrs={'class': 'form-control'}),
            'model': forms.TextInput(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'vin': forms.TextInput(attrs={'class': 'form-control'}),
            'color': forms.TextInput(attrs={'class': 'form-control'}),
            'body_type': forms.Select(attrs={'class': 'form-control'}),
            'transmission': forms.Select(attrs={'class': 'form-control'}),
            'fuel_type': forms.Select(attrs={'class': 'form-control'}),
            'mileage': forms.NumberInput(attrs={'class': 'form-control'}),
            'engine_size': forms.TextInput(attrs={'class': 'form-control'}),
            'horsepower': forms.NumberInput(attrs={'class': 'form-control'}),
            'purchase_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'asking_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'condition': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'air_conditioning': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'power_steering': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'power_windows': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'power_locks': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'cruise_control': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'backup_camera': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'bluetooth': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'navigation_system': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'leather_seats': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sunroof': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'all_wheel_drive': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def clean_vin(self):
        vin = (self.cleaned_data.get('vin') or '').strip().upper()
        return vin


class CustomerForm(forms.ModelForm):
    """Form for creating/editing customers"""
    class Meta:
        model = Customer
        fields = [
            'first_name', 'last_name', 'email', 'phone_number', 'gender', 'date_of_birth',
            'address', 'city', 'state', 'zip_code', 'country',
            'credit_score', 'preferred_financing', 'is_active', 'notes'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'zip_code': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'credit_score': forms.NumberInput(attrs={'class': 'form-control'}),
            'preferred_financing': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }


class SalesTransactionForm(forms.ModelForm):
    """Form for creating/editing sales transactions"""
    class Meta:
        model = SalesTransaction
        fields = [
            'car', 'customer', 'order', 'salesperson', 'sale_price', 'trade_in_value',
            'down_payment', 'payment_method', 'financed_amount', 'interest_rate',
            'loan_term_months', 'status', 'notes'
        ]
        widgets = {
            'car': forms.Select(attrs={'class': 'form-control'}),
            'customer': forms.Select(attrs={'class': 'form-control'}),
            'order': forms.Select(attrs={'class': 'form-control'}),
            'salesperson': forms.TextInput(attrs={'class': 'form-control'}),
            'sale_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'trade_in_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'down_payment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
            'financed_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'interest_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'loan_term_months': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('trade_in_value', 'down_payment', 'financed_amount', 'interest_rate'):
            self.fields[name].required = False
            self.fields[name].initial = 0
        self.fields['order'].required = False
        self.fields['order'].empty_label = 'No online order'
        # What each order's customer claimed for their trade-in, so the
        # staff panel can show it next to the field.
        claimed = {
            str(order.pk): str(order.trade_in_value)
            for order in self.fields['order'].queryset.only('pk', 'trade_in_value')
        }
        self.fields['order'].widget.attrs['data-claimed'] = json.dumps(claimed)

    def clean(self):
        cleaned = super().clean()
        order = cleaned.get('order')
        trade_in_value = cleaned.get('trade_in_value')
        if order and not trade_in_value and order.trade_in_value:
            # The customer told us what their trade-in was worth when
            # they placed the order; start from that number.
            cleaned['trade_in_value'] = order.trade_in_value
        return cleaned


class ServiceRecordForm(forms.ModelForm):
    """Form for creating/editing service records"""
    class Meta:
        model = ServiceRecord
        fields = [
            'car', 'service_type', 'description', 'odometer_reading', 'cost', 'technician'
        ]
        widgets = {
            'car': forms.Select(attrs={'class': 'form-control'}),
            'service_type': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'odometer_reading': forms.NumberInput(attrs={'class': 'form-control'}),
            'cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'technician': forms.TextInput(attrs={'class': 'form-control'}),
        }


class CarFilterForm(forms.Form):
    """Form for filtering cars"""
    make = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    body_type = forms.CharField(max_length=50, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    year = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    min_price = forms.DecimalField(required=False, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}))
    max_price = forms.DecimalField(required=False, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}))
    fuel_type = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

class AppointmentForm(AntiSpamMixin, forms.ModelForm):
    """Public test-drive booking form"""
    class Meta:
        model = Appointment
        fields = ['customer_name', 'customer_email', 'customer_phone',
                  'preferred_date', 'preferred_time', 'message']
        widgets = {
            'customer_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Full Name'}),
            'customer_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'your.email@example.com'}),
            'customer_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '(555) 123-4567'}),
            'preferred_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'preferred_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'message': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Anything we should know before your visit?'}),
        }

    def clean_preferred_date(self):
        preferred = self.cleaned_data['preferred_date']
        if preferred < timezone.localdate():
            raise forms.ValidationError('The test drive must be scheduled for a future date.')
        return preferred


class ContactForm(AntiSpamMixin, forms.ModelForm):
    """Public contact message form"""
    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'your.email@example.com'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'How can we help?'}),
            'message': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Your message...'}),
        }


class NewsletterForm(AntiSpamMixin, forms.Form):
    """Footer newsletter signup form"""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'you@example.com',
            'aria-label': 'Email address',
        }),
    )


class TestimonialForm(AntiSpamMixin, forms.ModelForm):
    """Public customer review submission (saved as pending moderation)"""
    rating = forms.TypedChoiceField(
        choices=[(n, f'{n} star{"s" if n != 1 else ""}') for n in range(1, 6)],
        coerce=int,
        initial=5,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = Testimonial
        fields = ['customer_name', 'vehicle', 'quote', 'rating']
        widgets = {
            'customer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your Name',
            }),
            'vehicle': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 2023 Toyota Camry',
            }),
            'quote': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Share your experience with us...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehicle'].required = False
        self.fields['quote'].label = 'Your Review'

    def clean_quote(self):
        quote = (self.cleaned_data.get('quote') or '').strip()
        if len(quote) < 10:
            raise forms.ValidationError('Please write at least 10 characters.')
        return quote

    def clean_rating(self):
        rating = self.cleaned_data.get('rating')
        if rating is None or not 1 <= rating <= 5:
            raise forms.ValidationError('Please choose a rating between 1 and 5.')
        return rating


class ContactInfoForm(forms.ModelForm):
    """Staff form for editing the 'Visit or Call' section on the contact page"""
    class Meta:
        model = ContactInfo
        fields = ['address', 'phone', 'email', 'whatsapp', 'hours']
        widgets = {
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Street\nCity, State',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '(555) 123-4567',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'sales@example.com',
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '14155551234',
            }),
            'hours': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Mon – Sat: 9:00 AM – 7:00 PM\nSunday: Closed',
            }),
        }


class AboutInfoForm(forms.ModelForm):
    """Staff form for editing the content of the About page"""
    class Meta:
        model = AboutInfo
        fields = [
            'page_tagline', 'vision_text', 'mission_text',
            'value_one_title', 'value_one_text',
            'value_two_title', 'value_two_text',
            'value_three_title', 'value_three_text',
        ]
        widgets = {
            'page_tagline': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Vision, mission, and the values that guide us',
            }),
            'vision_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'mission_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'value_one_title': forms.TextInput(attrs={'class': 'form-control'}),
            'value_one_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'value_two_title': forms.TextInput(attrs={'class': 'form-control'}),
            'value_two_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'value_three_title': forms.TextInput(attrs={'class': 'form-control'}),
            'value_three_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class DealershipInfoForm(forms.ModelForm):
    """Staff form for editing the dealership name and logo used site-wide"""
    logo = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
        }),
        help_text='PNG or JPG, up to 5 MB. Leave empty to keep the current logo.',
    )

    class Meta:
        model = DealershipInfo
        fields = ['name', 'logo']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Car Dealership',
            }),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo and getattr(logo, 'size', 0) > 5 * 1024 * 1024:
            raise forms.ValidationError('Please choose an image smaller than 5 MB.')
        return logo


class SavedSearchForm(AntiSpamMixin, forms.ModelForm):
    """Public 'email me when a matching car arrives' form shown on the browse page"""
    make = forms.ChoiceField(
        required=False,
        choices=[],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Make',
    )

    class Meta:
        model = SavedSearch
        fields = ['email', 'make', 'year_min', 'year_max', 'price_min', 'price_max',
                  'body_type', 'fuel_type', 'notify_price_drops']
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'you@example.com',
            }),
            'year_min': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Min'}),
            'year_max': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Max'}),
            'price_min': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Min', 'step': '0.01'}),
            'price_max': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Max', 'step': '0.01'}),
            'body_type': forms.Select(attrs={'class': 'form-select'}),
            'fuel_type': forms.Select(attrs={'class': 'form-select'}),
            'notify_price_drops': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        makes = list(Car.objects.filter(status='available')
                     .values_list('make', flat=True).distinct().order_by('make'))
        # Keep the saved make selectable even if no cars currently match it
        current_make = self.instance.make if self.instance and self.instance.pk else ''
        make_choices = [('', 'All Makes')] + [(m, m) for m in makes]
        if current_make and current_make not in makes:
            make_choices.append((current_make, current_make))
        self.fields['make'].choices = make_choices
        self.fields['body_type'].choices = [('', 'All Body Types')] + [
            ('sedan', 'Sedan'), ('suv', 'SUV'), ('truck', 'Truck'), ('coupe', 'Coupe'),
            ('hatchback', 'Hatchback'), ('wagon', 'Wagon'), ('van', 'Van'), ('convertible', 'Convertible'),
        ]
        self.fields['fuel_type'].choices = [('', 'All Fuel Types')] + [
            ('gasoline', 'Gasoline'), ('diesel', 'Diesel'), ('hybrid', 'Hybrid'), ('electric', 'Electric'),
        ]
        for name in ('year_min', 'year_max', 'price_min', 'price_max'):
            self.fields[name].required = False
        for name in ('body_type', 'fuel_type'):
            self.fields[name].required = False


class ListingRequestForm(AntiSpamMixin, forms.ModelForm):
    """Public form: ask us to list your car on the website.

    The owner has to send us the logbook and at least one photo of the
    car, because staff check both before anything is published.
    """

    photos = forms.Field(
        required=True,
        widget=MultipleImageInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
            'multiple': True,
        }),
        help_text="At least one clear photo of the car (JPG, PNG or WEBP).",
        error_messages={
            'required': 'Please add at least one photo of the car.',
        },
    )

    logbook_photo = forms.FileField(
        required=True,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
        }),
        help_text=(
            "A photo of the front page of the logbook, showing the owner's "
            "name and the logbook number."
        ),
        error_messages={
            'required': 'Please upload a photo of the logbook.',
        },
    )

    class Meta:
        model = ListingRequest
        fields = [
            'owner_name', 'owner_email', 'owner_phone',
            'make', 'model', 'year', 'vin', 'color', 'body_type',
            'transmission', 'fuel_type', 'mileage', 'engine_size',
            'logbook_number', 'logbook_owner_name', 'asking_price', 'description',
        ]
        widgets = {
            'owner_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your Full Name',
            }),
            'owner_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'your.email@example.com',
            }),
            'owner_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '07xx xxx xxx',
            }),
            'make': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Toyota',
            }),
            'model': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Hilux',
            }),
            'year': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 2019',
                'min': '1900',
            }),
            'vin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '17-character VIN',
            }),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. White',
            }),
            'body_type': forms.Select(attrs={'class': 'form-control'}),
            'transmission': forms.Select(attrs={'class': 'form-control'}),
            'fuel_type': forms.Select(attrs={'class': 'form-control'}),
            'mileage': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 68000',
                'min': '0',
            }),
            'engine_size': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 2.8L',
            }),
            'logbook_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'As written in the logbook',
            }),
            'logbook_owner_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'The name on the logbook',
            }),
            'asking_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Price you want the car advertised at',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Tell us about the car - condition, history, what is included...',
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        for name in ('body_type', 'transmission', 'fuel_type'):
            self.fields[name].required = False
            self.fields[name].empty_label = 'Not sure'
        self.fields['year'].widget.attrs.setdefault('max', str(date.today().year + 1))

    def clean_year(self):
        """A year that has not happened yet is a typo."""
        year = self.cleaned_data.get('year')
        if year and year > date.today().year + 1:
            raise ValidationError('That year is in the future.')
        return year

    def clean_photos(self):
        """Check every photo of the car before anything is stored."""
        photos = self.cleaned_data.get('photos') or []
        if not isinstance(photos, (list, tuple)):
            photos = [photos]
        for photo in photos:
            self._check_image(photo)
        return self.cleaned_data.get('photos')

    def clean_logbook_photo(self):
        """Check the logbook scan before anything is stored."""
        photo = self.cleaned_data.get('logbook_photo')
        if photo:
            self._check_image(photo)
        return photo

    @staticmethod
    def _check_image(uploaded):
        """Reject a file that is not an image we can actually use."""
        if not uploaded:
            return
        try:
            validate_image_upload(uploaded)
        except ValidationError as exc:
            raise ValidationError('; '.join(exc.messages))

    def clean_vin(self):
        """Store the VIN uppercase and keep it to one vehicle."""
        vin = (self.cleaned_data.get('vin') or '').strip().upper()
        if not vin:
            return vin

        existing = Car.objects.filter(vin=vin).first()
        if existing:
            raise ValidationError(
                'This VIN is already listed on our website. '
                'Please contact us so we can update the existing listing.'
            )

        if self.user is not None and self.user.is_authenticated:
            duplicate = ListingRequest.objects.filter(
                user=self.user,
                vin=vin,
            ).exclude(status__in=('rejected', 'cancelled', 'listed'))
            if duplicate.exists():
                raise ValidationError(
                    'You already have a request open for this vehicle.'
                )
        return vin


class ListingRequestReviewForm(forms.ModelForm):
    """Staff form: verify the request and record the listing fee.

    This is the check that stands between an owner's description of a car
    and a listing on the website: staff tick the boxes only after they
    have seen the car and the logbook.
    """

    class Meta:
        model = ListingRequest
        fields = [
            'status', 'vehicle_verified', 'logbook_verified', 'payment_status',
            'payment_reference', 'staff_notes', 'rejection_reason',
        ]
        widgets = {
            'status': forms.Select(attrs={'class': 'form-control'}),
            'vehicle_verified': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'logbook_verified': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'payment_status': forms.Select(attrs={'class': 'form-control'}),
            'payment_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'M-Pesa or bank reference',
            }),
            'staff_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notes for your colleagues (not shown to the owner)',
            }),
            'rejection_reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Given to the owner when the request is rejected',
            }),
        }
        labels = {
            'status': 'Where is the request?',
            'vehicle_verified': 'I have inspected the vehicle and it is as described',
            'logbook_verified': 'I have verified the logbook against the vehicle',
            'payment_status': 'Listing fee',
            'payment_reference': 'Payment reference',
            'staff_notes': 'Internal notes',
            'rejection_reason': 'Reason for rejection',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 'listed' is not a choice here: a listing only goes live by being
        # published, never by picking it from a dropdown.
        labels = dict(ListingRequest.STATUS_CHOICES)
        self.fields['status'].choices = [
            (value, labels[value]) for value in ListingRequest.MANUAL_STATUSES
        ]
        self.fields['status'].help_text = (
            'Use this to tell the owner what is still needed from them.'
        )
        self.fields['status'].required = False
        self.fields['status'].empty_label = '(leave as it is)'


class ListingPublishForm(CarForm):
    """The listing that goes live when staff approve a request.

    Same fields as the staff "Add Car" form, so the listing looks like
    every other vehicle on the site - staff publish it on the owner's
    behalf.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # We do not buy the car, so there is no purchase price for it. Staff
        # can still record one if they valued the vehicle for the stock books.
        self.fields['purchase_price'].required = False
        self.fields['purchase_price'].initial = 0
        self.fields['purchase_price'].help_text = (
            'Internal purchase price. Leave at 0 for a listing taken on '
            "the owner's behalf."
        )
        self.fields['status'].initial = 'available'
        self.fields['status'].help_text = 'A new listing is normally Available.'


class FinancingApplicationForm(AntiSpamMixin, forms.ModelForm):
    """Public form: ask us to finance a vehicle for you.

    The customer picks a car out of stock, or tells us which one they
    have their eye on, and says what they earn and what they can put
    down. The website works out what would have to be borrowed and what
    it would cost each month - it does not approve anything.
    """

    car = forms.ModelChoiceField(
        required=False,
        queryset=Car.objects.none(),
        empty_label="Not from stock / I have not chosen yet",
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Which car?",
        help_text="Pick a car from our stock, or describe what you are after below.",
    )

    class Meta:
        model = FinancingApplication
        fields = [
            'car', 'car_label',
            'customer_name', 'customer_email', 'customer_phone',
            'employment_status', 'employer_name', 'job_title',
            'monthly_income', 'monthly_expenses',
            'price', 'deposit_amount', 'trade_in_value', 'loan_term_months',
        ]
        widgets = {
            'car_label': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 2018 Toyota Prado TXL',
            }),
            'customer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your Full Name',
            }),
            'customer_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'your.email@example.com',
            }),
            'customer_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '07xx xxx xxx',
            }),
            'employment_status': forms.Select(attrs={'class': 'form-select'}),
            'employer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Where you work',
            }),
            'job_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'What you do',
            }),
            'monthly_income': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Net monthly income',
            }),
            'monthly_expenses': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'What you already pay out each month',
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'The price of the car',
            }),
            'deposit_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'What you can put down today',
            }),
            'trade_in_value': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'What we value your current car at',
            }),
            'loan_term_months': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'car_label': 'Or tell us which vehicle',
            'monthly_income': 'Net monthly income (KSh)',
            'monthly_expenses': 'Monthly commitments (KSh)',
            'price': 'Vehicle price (KSh)',
            'deposit_amount': 'Deposit you can pay (KSh)',
            'trade_in_value': 'Trade-in value (KSh)',
            'loan_term_months': 'Loan term',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['car'].queryset = Car.objects.filter(
            status='available'
        ).order_by('make', 'model', 'year')
        for name in ('car_label', 'employer_name', 'job_title', 'monthly_expenses',
                     'trade_in_value'):
            self.fields[name].required = False
        # The price can be left blank when a car from stock was picked; it is
        # then taken from the car's asking price in clean().
        self.fields['price'].required = False
        self.fields['deposit_amount'].initial = 0
        self.fields['trade_in_value'].initial = 0
        self.fields['monthly_expenses'].initial = 0

    def clean(self):
        """Work out the quote, and check it is one we would stand behind."""
        cleaned = super().clean()
        car = cleaned.get('car')
        price = cleaned.get('price')
        deposit = cleaned.get('deposit_amount') or Decimal('0')
        trade_in = cleaned.get('trade_in_value') or Decimal('0')
        income = cleaned.get('monthly_income')
        months = cleaned.get('loan_term_months')
        car_label = (cleaned.get('car_label') or '').strip()

        if car and not car_label:
            car_label = str(car)
            cleaned['car_label'] = car_label
        if not car and not car_label:
            self.add_error('car_label', 'Tell us which vehicle you would like us to finance.')
            return cleaned

        if price is None and car is not None:
            # The customer did not type a price: ours is the asking price.
            price = car.asking_price
            cleaned['price'] = price

        if price is None:
            self.add_error('price', 'Tell us the price of the car.')
            return cleaned

        if price <= 0:
            self.add_error('price', 'The price of the car cannot be zero.')
            return cleaned
        if deposit < min_deposit(price):
            self.add_error(
                'deposit_amount',
                f'The smallest deposit we can accept for a {format_money(price)} car is '
                f'{format_money(min_deposit(price))}.',
            )
            return cleaned
        if deposit + trade_in >= price:
            self.add_error(
                'deposit_amount',
                'The deposit and the trade-in together must be less than the price '
                'of the car.',
            )
            return cleaned

        if income is None or income <= 0:
            return cleaned

        principal = amount_financed(price, deposit, trade_in)
        payment = monthly_payment(principal, interest_rate(), months)
        cleaned['estimated_monthly'] = payment
        if not affordability_ok(income, payment):
            self.add_error(
                'monthly_income',
                f'At {format_money(payment)} a month that is more than a third of your '
                f'net income. A larger deposit or a longer term usually brings it down.',
            )
        return cleaned


class FinancingReviewForm(forms.ModelForm):
    """Staff form: record the decision on a financing application.

    Nothing is decided automatically, because an approval is a credit
    decision. The website only records what a human decided.
    """

    class Meta:
        model = FinancingApplication
        fields = [
            'status', 'approved_amount', 'approved_term_months',
            'decision_notes', 'decline_reason',
        ]
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'approved_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
            }),
            'approved_term_months': forms.Select(attrs={
                'class': 'form-select',
                'include_blank': 'Same as requested',
            }),
            'decision_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notes for your colleagues (not shown to the customer)',
            }),
            'decline_reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Given to the customer when the application is declined',
            }),
        }
        labels = {
            'status': 'Where has the application got to?',
            'approved_amount': 'Amount approved (KSh)',
            'approved_term_months': 'Term approved',
            'decision_notes': 'Internal notes',
            'decline_reason': 'Reason for declining',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = [
            (value, label) for value, label in FinancingApplication.STATUS_CHOICES
            if value in FinancingApplication.MANUAL_STATUSES
        ]
        self.fields['status'].required = False
        self.fields['status'].empty_label = '(leave as it is)'
        self.fields['approved_amount'].required = False
        self.fields['approved_term_months'].required = False
        self.fields['approved_term_months'].choices = [
            ('', 'Same as requested'),
        ] + list(FinancingApplication.TERM_CHOICES)

    def clean(self):
        cleaned = super().clean()
        # A blank amount or term means "same as requested", not an empty
        # string in a numeric column.
        if not cleaned.get('approved_term_months'):
            cleaned['approved_term_months'] = None
        if cleaned.get('approved_amount') in ('', None):
            cleaned['approved_amount'] = None
        status = cleaned.get('status')
        decline_reason = (cleaned.get('decline_reason') or '').strip()

        if status == 'declined' and not decline_reason:
            self.add_error(
                'decline_reason',
                'Tell the customer why the application was declined.',
            )
        if status == 'approved':
            amount = cleaned.get('approved_amount')
            if amount is not None and amount <= 0:
                self.add_error('approved_amount', 'The approved amount cannot be zero.')
        return cleaned
