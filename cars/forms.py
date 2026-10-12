from django import forms
from django.utils import timezone
from .models import (
    Car, Customer, SalesTransaction, ServiceRecord, Inquiry, Order,
    Appointment, ContactMessage, NewsletterSubscription, Testimonial, ContactInfo,
    SavedSearch, AboutInfo,
)


class MultipleImageInput(forms.ClearableFileInput):
    """File input allowing multiple image selection"""
    allow_multiple_selected = True


class InquiryForm(forms.ModelForm):
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


class OrderForm(forms.ModelForm):
    """Form for customer orders"""
    class Meta:
        model = Order
        fields = ['customer_name', 'customer_email', 'customer_phone', 'customer_address',
                  'price', 'trade_in_value', 'down_payment', 'financing_needed', 'notes']
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
        }


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
            'car', 'customer', 'salesperson', 'sale_price', 'trade_in_value',
            'down_payment', 'payment_method', 'financed_amount', 'interest_rate',
            'loan_term_months', 'status', 'notes'
        ]
        widgets = {
            'car': forms.Select(attrs={'class': 'form-control'}),
            'customer': forms.Select(attrs={'class': 'form-control'}),
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

class AppointmentForm(forms.ModelForm):
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


class ContactForm(forms.ModelForm):
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


class NewsletterForm(forms.Form):
    """Footer newsletter signup form"""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'you@example.com',
            'aria-label': 'Email address',
        }),
    )


class TestimonialForm(forms.ModelForm):
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
        fields = ['address', 'phone', 'email', 'hours']
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


class SavedSearchForm(forms.ModelForm):
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
                  'body_type', 'fuel_type']
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
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        makes = list(Car.objects.filter(status='available')
                     .values_list('make', flat=True).distinct().order_by('make'))
        self.fields['make'].choices = [('', 'All Makes')] + [(m, m) for m in makes]
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
