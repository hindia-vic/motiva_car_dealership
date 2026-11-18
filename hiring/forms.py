"""Forms for car hire and tours & travel.

Three forms:

* :class:`HireCarForm` is the staff form for a car in the fleet.
* :class:`HireBookingForm` is the public form a customer fills in to
  ask for a car.
* :class:`HireBookingReviewForm` is the staff form for confirming a
  booking, taking the money and rejecting one.
"""

from datetime import date, timedelta
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.utils import timezone

from cars.antispam import AntiSpamMixin
from cars.forms import MultipleImageInput
from cars.images import validate_image_upload
from cars.money import format_money

from . import rules
from .models import (
    SERVICE_SELF_DRIVE, SERVICE_TOUR, HireAddOn, HireBooking, HireBookingAddOn,
    HireCar, TourPackage, TourPackageDay,
)


class HireCarForm(forms.ModelForm):
    """Staff form: add or edit a car in the hire fleet."""

    images = forms.Field(
        required=False,
        widget=MultipleImageInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
        }),
        help_text="The first photo becomes the main photo (jpg/png).",
    )

    class Meta:
        model = HireCar
        fields = [
            'make', 'model', 'year', 'color', 'body_type', 'transmission',
            'fuel_type', 'seats', 'luggage_capacity', 'hire_daily_rate',
            'tour_daily_rate', 'allows_tours', 'status', 'description',
        ]
        widgets = {
            'make': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Toyota',
            }),
            'model': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Fortuner',
            }),
            'year': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 2022',
                'min': '1900',
            }),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. White',
            }),
            'body_type': forms.Select(attrs={'class': 'form-control'}),
            'transmission': forms.Select(attrs={'class': 'form-control'}),
            'fuel_type': forms.Select(attrs={'class': 'form-control'}),
            'seats': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '60',
            }),
            'luggage_capacity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '60',
            }),
            'hire_daily_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '50',
                'min': '0',
                'placeholder': 'e.g. 6500',
            }),
            'tour_daily_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '50',
                'min': '0',
                'placeholder': 'e.g. 12000',
            }),
            'allows_tours': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Condition, features, anything a customer should know',
            }),
        }

    def clean_year(self):
        """A year that has not happened yet is a typo."""
        year = self.cleaned_data.get('year')
        if year and year > date.today().year + 1:
            raise ValidationError('That year is in the future.')
        return year

    def clean_images(self):
        """Check every photo before any of it is stored."""
        photos = self.cleaned_data.get('images') or []
        if not isinstance(photos, (list, tuple)):
            photos = [photos]
        for photo in photos:
            if not photo:
                continue
            try:
                validate_image_upload(photo)
            except ValidationError as exc:
                raise ValidationError('; '.join(exc.messages))
        return self.cleaned_data.get('images')

    def clean(self):
        """A car offered for tours has to have a tour rate."""
        cleaned = super().clean()
        if cleaned.get('allows_tours') and not cleaned.get('tour_daily_rate'):
            self.add_error(
                'tour_daily_rate',
                'Set the rate per day for tours, or untick "offers tours".',
            )
        return cleaned


class TourPackageForm(forms.ModelForm):
    """Staff form: add or edit a ready-made tour package."""

    images = forms.Field(
        required=False,
        widget=MultipleImageInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
        }),
        help_text="The first photo becomes the main photo (jpg/png).",
    )

    class Meta:
        model = TourPackage
        fields = [
            'name', 'slug', 'destination', 'summary', 'description',
            'duration_days', 'price_per_person', 'min_passengers',
            'includes', 'excludes', 'is_active', 'is_featured', 'sort_order',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Three days in the Mara',
            }),
            'slug': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'leave-blank-to-build-from-the-name',
            }),
            'destination': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Maasai Mara',
            }),
            'summary': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'One line for the package card',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'What makes this tour worth taking',
            }),
            'duration_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '60',
            }),
            'price_per_person': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '500',
                'min': '0',
                'placeholder': 'e.g. 35000',
            }),
            'min_passengers': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '60',
            }),
            'includes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Park fees\nMeals\nDriver and fuel',
            }),
            'excludes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Drinks\nTips\nSouvenirs',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
            }),
        }
        labels = {
            'duration_days': 'How many days?',
            'price_per_person': 'Price per person (KSh)',
            'min_passengers': 'Smallest group',
            'is_active': 'Show this package on the site',
            'is_featured': 'Feature it at the top of the list',
            'sort_order': 'Order',
        }

    def clean_images(self):
        """Check every photo before any of it is stored."""
        photos = self.cleaned_data.get('images') or []
        if not isinstance(photos, (list, tuple)):
            photos = [photos]
        for photo in photos:
            if not photo:
                continue
            try:
                validate_image_upload(photo)
            except ValidationError as exc:
                raise ValidationError('; '.join(exc.messages))
        return self.cleaned_data.get('images')


class HireExtraChoiceField(forms.ModelMultipleChoiceField):
    """Shows the price next to each add-on, so the customer knows the cost."""

    def label_from_instance(self, add_on):
        phrase = 'per day' if add_on.unit == 'per_day' else 'once'
        return f"{add_on.name} - {format_money(add_on.price)} {phrase}"


class HireBookingForm(AntiSpamMixin, forms.ModelForm):
    """Public form: ask to hire a car for a set of dates."""

    extras = HireExtraChoiceField(
        queryset=HireAddOn.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        label="Extras",
        help_text="Tick anything you need for the trip.",
    )

    class Meta:
        model = HireBooking
        fields = [
            'service_type', 'start_date', 'end_date', 'passengers',
            'destination', 'pickup_location', 'licence_number', 'id_number',
            'customer_name', 'customer_email', 'customer_phone', 'notes',
        ]
        widgets = {
            'service_type': forms.RadioSelect(),
            'start_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'passengers': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '60',
            }),
            'destination': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Lake Nakuru, Naivasha, Amboseli',
            }),
            'pickup_location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Where would you like to collect the car?',
            }),
            'licence_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'As printed on your driving licence',
            }),
            'id_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'National ID or passport number',
            }),
            'customer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your full name',
            }),
            'customer_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'you@example.com',
            }),
            'customer_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '07xx xxx xxx',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Anything else we should know',
            }),
        }
        labels = {
            'service_type': 'How would you like the car?',
            'start_date': 'Pick-up date',
            'end_date': 'Return date',
            'licence_number': 'Driving licence number',
            'id_number': 'National ID or passport number',
        }

    def __init__(self, *args, hire_car=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hire_car = hire_car
        self.fields['extras'].queryset = HireAddOn.objects.filter(is_active=True)

        if hire_car is not None:
            if not hire_car.allows_tours:
                # The car is self-drive only, so the choice is not offered.
                self.fields['service_type'].choices = [
                    (value, label)
                    for value, label in self.fields['service_type'].choices
                    if value != SERVICE_TOUR
                ]
            self.fields['passengers'].widget.attrs['max'] = str(hire_car.seats)
            self.fields['passengers'].help_text = (
                f'This car carries {hire_car.seats} people, the driver included.'
            )

        self.fields['start_date'].widget.attrs['min'] = str(timezone.localdate())
        self.fields['end_date'].widget.attrs['min'] = str(timezone.localdate())

    def clean(self):
        """The rules that decide whether this request makes sense."""
        cleaned = super().clean()

        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        service = cleaned.get('service_type')
        passengers = cleaned.get('passengers')
        car = self.hire_car

        if start and end and end < start:
            self.add_error(
                'end_date',
                'The return date cannot be before the pick-up date.',
            )

        if start and start < timezone.localdate():
            self.add_error('start_date', 'That pick-up date has already passed.')

        if car is not None and service == SERVICE_TOUR and not car.allows_tours:
            self.add_error(
                'service_type',
                'This car is not offered for tours and travel.',
            )

        if service == SERVICE_TOUR and not (cleaned.get('destination') or '').strip():
            self.add_error('destination', 'Tell us where the car is going.')

        if service == SERVICE_SELF_DRIVE and not (
            cleaned.get('licence_number') or ''
        ).strip():
            self.add_error(
                'licence_number',
                'Tell us the licence number of the person who will drive.',
            )

        if car is not None and passengers and passengers > car.seats:
            self.add_error(
                'passengers',
                f'This car carries {car.seats} people, the driver included.',
            )

        if car is not None and start and end:
            clash = HireBooking.blocking(car, start, end)
            if clash.exists():
                self.add_error(
                    'start_date',
                    'This car is already out for those dates. Please pick other dates.',
                )

        return cleaned


class HireBookingReviewForm(forms.ModelForm):
    """Staff form: confirm a booking, take the money, or turn it down."""

    deposit_received = forms.BooleanField(
        required=False,
        label="Security deposit received",
    )
    deposit_refunded = forms.BooleanField(
        required=False,
        label="Security deposit refunded",
    )

    class Meta:
        model = HireBooking
        fields = [
            'start_date', 'end_date', 'quoted_price', 'security_deposit',
            'deposit_retained', 'status', 'payment_status', 'payment_reference',
            'driver_name', 'staff_notes', 'rejection_reason',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'quoted_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '50',
                'min': '0',
            }),
            'security_deposit': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '500',
                'min': '0',
            }),
            'deposit_retained': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '100',
                'min': '0',
            }),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'payment_status': forms.Select(attrs={'class': 'form-control'}),
            'payment_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'M-Pesa or bank transfer reference',
            }),
            'driver_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'For tours: who is driving',
            }),
            'staff_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notes for your colleagues (not shown to the customer)',
            }),
            'rejection_reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Given to the customer when the booking is turned down',
            }),
        }
        labels = {
            'quoted_price': 'What the customer owes',
            'security_deposit': 'Security deposit (KSh)',
            'deposit_retained': 'Kept for damage or fuel (KSh)',
            'status': 'Where is the booking?',
            'payment_status': 'Payment',
            'payment_reference': 'Payment reference',
            'driver_name': 'Driver',
            'staff_notes': 'Internal notes',
            'rejection_reason': 'Reason for turning it down',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 'completed' is set when the car comes back, so it is not a state
        # staff pick from a dropdown - but it still has to show as the
        # current state of the booking.
        labels = dict(HireBooking.STATUS_CHOICES)
        choices = [('', '(leave as it is)')]
        choices += [
            (value, labels[value]) for value in HireBooking.MANUAL_STATUSES
        ]
        current = getattr(self.instance, 'status', None)
        if current and current not in [value for value, _ in choices]:
            choices.insert(1, (current, labels[current]))
        self.fields['status'].choices = choices
        self.fields['status'].required = False
        self.fields['status'].help_text = (
            'Use this to tell the customer where their booking has got to.'
        )

        # A deposit of zero is allowed (some customers leave a car with us
        # for a repeat booking), so neither amount is compulsory.
        self.fields['security_deposit'].required = False
        self.fields['deposit_retained'].required = False

        booking = self.instance
        if booking and booking.pk:
            self.fields['deposit_received'].initial = bool(booking.deposit_received_at)
            self.fields['deposit_refunded'].initial = bool(booking.deposit_refunded_at)
            suggested = rules.suggested_security_deposit(booking.hire_total())
            self.fields['security_deposit'].help_text = (
                f'Suggested for this hire: {format_money(suggested)}.'
            )

    def clean(self):
        """The rules a booking has to keep while staff work on it."""
        cleaned = super().clean()

        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end < start:
            self.add_error(
                'end_date',
                'The return date cannot be before the pick-up date.',
            )

        payment_status = cleaned.get('payment_status')
        reference = (cleaned.get('payment_reference') or '').strip()
        if payment_status == 'paid' and not reference:
            self.add_error(
                'payment_reference',
                'Record the M-Pesa or bank reference for the payment.',
            )

        if cleaned.get('status') == 'rejected' and not (cleaned.get('rejection_reason') or '').strip():
            self.add_error(
                'rejection_reason',
                'Tell the customer why the booking was turned down.',
            )

        # A blank amount means nothing is held, not an empty string in a
        # numeric column.
        deposit = cleaned.get('security_deposit') or Decimal('0')
        retained = cleaned.get('deposit_retained') or Decimal('0')
        cleaned['security_deposit'] = deposit
        cleaned['deposit_retained'] = retained

        if retained > deposit:
            self.add_error(
                'deposit_retained',
                'You cannot keep more than the deposit was.',
            )

        received = cleaned.get('deposit_received')
        already_received = getattr(self.instance, 'deposit_received_at', None)
        if retained and not (received or already_received):
            self.add_error(
                'deposit_received',
                'Record that the deposit was received before keeping part of it.',
            )
        if cleaned.get('deposit_refunded') and not (received or already_received):
            self.add_error(
                'deposit_received',
                'Record that the deposit was received before refunding it.',
            )

        return cleaned


HireBookingExtraFormSet = inlineformset_factory(
    HireBooking,
    HireBookingAddOn,
    fields=('add_on', 'quantity'),
    extra=1,
    can_delete=True,
    widgets={
        'add_on': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        'quantity': forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'min': '1',
        }),
    },
)
