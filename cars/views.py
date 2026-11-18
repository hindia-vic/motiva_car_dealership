from django.contrib.auth.decorators import login_required
from functools import wraps
from django.contrib.admin.views.decorators import staff_member_required

def staff_required(view_func):
    decorated = staff_member_required(view_func)
    @wraps(decorated)
    def _wrapped_view(request, *args, **kwargs):
        return decorated(request, *args, **kwargs)
    return _wrapped_view

from django.shortcuts import render, get_object_or_404, redirect
import json
import logging
import random
import re
import secrets
from datetime import timedelta
from django.http import JsonResponse, Http404
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView
from django.views.decorators.http import require_POST
from django.db.models import Q, Count, Sum, Avg
from django.urls import reverse, reverse_lazy
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from .models import (
    Car, CarImage, Customer, SalesTransaction, ServiceRecord, Inquiry, Order,
    Appointment, ContactMessage, NewsletterSubscription, Testimonial, ContactInfo,
    SavedSearch, Post, AboutInfo, CarPriceHistory, CarStatusHistory, DealershipInfo,
    ChatSession, ChatMessage, ListingRequest, ListingRequestPhoto,
    FinancingApplication, Branch,
)
from .forms import (
    InquiryForm, OrderForm, AppointmentForm, ContactForm, NewsletterForm,
    TestimonialForm, CarForm, CustomerForm, SalesTransactionForm, ContactInfoForm,
    SavedSearchForm, AboutInfoForm, DealershipInfoForm, TradeInForm,
    ListingRequestForm, ListingRequestReviewForm, ListingPublishForm,
    FinancingApplicationForm, FinancingReviewForm,
)
from .emails import (
    send_inquiry_notification, send_order_notification,
    send_appointment_notification, send_appointment_status_email,
    send_contact_notification, send_testimonial_notification,
    send_saved_search_alert_email, send_order_status_email,
    send_order_confirmation_email,
    send_inquiry_status_email, send_listing_request_notification,
    send_listing_request_status_email, send_financing_notification,
    send_financing_status_email,
)
from .antispam import rate_limit, captcha_required, verify_captcha, client_ip
from .alerts import send_pending_alerts
from . import leads
from . import orders as order_recovery
from .images import validate_image_upload
from .listing import listing_fee
from .deposits import order_deposit
from .financing import (
    MIN_DEPOSIT_RATIO, LOAN_TERMS, interest_rate, monthly_payment, total_repayable,
)
from .tradein import breakdown as tradein_breakdown
from .tradein import estimate as tradein_estimate
from traffic.analytics import parse_period
from traffic.conversion import conversion_rows, source_for_visitor, visitor_id_from
from .exports import stream_csv, stream_pdf
from .money import currency_code
from .structured_data import (
    blog_posting_node, breadcrumb_node, dealer_node, faq_node, json_ld,
    vehicle_node, website_node,
)
from .chatbot import get_reply as chatbot_get_reply, MAX_MESSAGE_LENGTH
from traffic.models import PageView
from hiring.models import HireBooking, HireCar
from payments.models import MpesaTransaction
from accounts.models import Profile
from notifications.services import notify, notify_staff
try:
    from cars.models import HistoricalCar
except ImportError:
    HistoricalCar = None
try:
    from hiring.models import HistoricalHireBooking
except ImportError:
    try:
        from hiring.models import HireBooking as HistoricalHireBooking
    except ImportError:
        HistoricalHireBooking = None


logger = logging.getLogger(__name__)


# ==================== CUSTOMER FACING VIEWS ====================

class HomeView(View):
    """Homepage with featured cars and customer testimonials"""
    def get(self, request):
        featured_cars = (
            Car.objects.filter(status='available')
            .prefetch_related('images')[:6]
        )
        total_cars = Car.objects.filter(status='available').count()

        # Photos for the hero background slider. Only cars that actually have
        # a photo are considered, so the hero never falls back to an empty
        # slide when the newest arrivals have not been photographed yet.
        hero_cars = (
            Car.objects.filter(status='available', images__isnull=False)
            .prefetch_related('images')
            .distinct()[:4]
        )
        hero_images = []
        for car in hero_cars:
            image = car.images.first()
            if image and image.image:
                hero_images.append(image)

        context = {
            'featured_cars': featured_cars,
            'total_cars': total_cars,
            'hero_images': hero_images,
            'testimonials': Testimonial.objects.filter(is_visible=True),
            'latest_posts': Post.objects.filter(is_published=True)[:3],
            'hire_cars': HireCar.objects.filter(
                status__in=HireCar.PUBLIC_STATUSES
            ).prefetch_related('images')[:3],
            'structured_data': [
                json_ld(dealer_node(request)),
                json_ld(website_node(request)),
            ],
        }
        return render(request, 'cars/home.html', context)


# Whitelist of allowed sort options on the browse page
SORT_OPTIONS = {
    'newest': '-date_added',
    'price_asc': 'asking_price',
    'price_desc': '-asking_price',
    'year_desc': '-year',
    'year_asc': 'year',
    'mileage_asc': 'mileage',
}

SORT_LABELS = {
    'newest': 'Newest First',
    'price_asc': 'Price: Low to High',
    'price_desc': 'Price: High to Low',
    'year_desc': 'Year: Newest First',
    'year_asc': 'Year: Oldest First',
    'mileage_asc': 'Mileage: Lowest First',
}


class CarBrowseView(ListView):
    """Customer-facing car listing with filters"""
    model = Car
    template_name = 'cars/browse_cars.html'
    context_object_name = 'cars'
    paginate_by = 12
    
    def get_queryset(self):
        # Sold vehicles stay in the listing: the page a visitor already has
        # open should not turn into a 404, and the sold badge plus the
        # similar-vehicles block give them something to look at instead.
        queryset = Car.objects.filter(
            status__in=Car.PUBLIC_STATUSES
        ).prefetch_related('images')
        
        # Filter by body type
        body_type = self.request.GET.get('body_type')
        if body_type:
            queryset = queryset.filter(body_type=body_type)
        
        # Filter by make
        make = self.request.GET.get('make')
        if make:
            queryset = queryset.filter(make=make)
        
        # Filter by year
        year = self.request.GET.get('year')
        if year:
            queryset = queryset.filter(year=year)
        
        # Filter by price range
        min_price = self.request.GET.get('min_price')
        max_price = self.request.GET.get('max_price')
        if min_price:
            queryset = queryset.filter(asking_price__gte=min_price)
        if max_price:
            queryset = queryset.filter(asking_price__lte=max_price)
        
        # Filter by fuel type
        fuel_type = self.request.GET.get('fuel_type')
        if fuel_type:
            queryset = queryset.filter(fuel_type=fuel_type)
        
        # Search
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(make__icontains=search) |
                Q(model__icontains=search) |
                Q(color__icontains=search)
            )
        
        # Sort (whitelisted, defaults to newest)
        order = SORT_OPTIONS.get(self.request.GET.get('sort'), SORT_OPTIONS['newest'])
        return queryset.order_by(order)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        listed = Car.objects.filter(status__in=Car.PUBLIC_STATUSES)
        context['makes'] = listed.values_list('make', flat=True).distinct()
        context['years'] = sorted(listed.values_list('year', flat=True).distinct(), reverse=True)
        context['body_types'] = listed.values_list('body_type', flat=True).distinct()
        context['fuel_types'] = listed.values_list('fuel_type', flat=True).distinct()
        context['sort_options'] = SORT_OPTIONS.keys()
        context['sort_labels'] = SORT_LABELS
        context['current_sort'] = self.request.GET.get('sort', 'newest')
        context['saved_search_form'] = SavedSearchForm()
        return context


class CarCompareView(View):
    """Side-by-side comparison of up to 4 selected vehicles"""
    template_name = 'cars/compare.html'
    max_cars = 4

    def get(self, request):
        raw_ids = request.GET.get('ids', '')
        car_ids = []
        for raw in raw_ids.split(','):
            raw = raw.strip()
            if raw.isdigit():
                car_ids.append(int(raw))

        cars = list(
            Car.objects.filter(pk__in=car_ids, status__in=Car.PUBLIC_STATUSES)
            .prefetch_related('images')
        )
        # Show cars in the order the visitor selected them
        order = {pk: index for index, pk in enumerate(car_ids)}
        cars.sort(key=lambda car: order.get(car.pk, 0))
        return render(request, self.template_name, {'cars': cars[:self.max_cars]})


class CarDetailView(DetailView):
    """Customer-facing car detail page"""
    model = Car
    template_name = 'cars/car_view.html'
    context_object_name = 'car'
    
    def get_queryset(self):
        # Allow viewing of all cars, even if sold
        return Car.objects.prefetch_related('images')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        initial = {}
        if self.request.user.is_authenticated:
            if self.request.user.get_full_name():
                initial['customer_name'] = self.request.user.get_full_name()
            elif self.request.user.username:
                initial['customer_name'] = self.request.user.username
            if self.request.user.email:
                initial['customer_email'] = self.request.user.email

        context['inquiry_form'] = InquiryForm(initial=initial)
        context['order_form'] = OrderForm()
        context['appointment_form'] = AppointmentForm(initial=initial)
        context['status_choices'] = Car.STATUS_CHOICES
        favorite = None
        if self.request.user.is_authenticated:
            favorite = self.object.favorited_by.filter(user=self.request.user).first()
        context['favorite'] = favorite
        context['is_favorited'] = favorite is not None

        # Similar vehicles: same make or body type first, newest first
        similar = list(
            Car.objects.filter(status='available')
            .exclude(pk=self.object.pk)
            .filter(Q(make__iexact=self.object.make) | Q(body_type=self.object.body_type))
            .prefetch_related('images')
            .order_by('-year')[:4]
        )
        if not similar:
            similar = list(
                Car.objects.filter(status='available')
                .exclude(pk=self.object.pk)
                .prefetch_related('images')
                .order_by('-date_added')[:4]
            )
        context['similar_cars'] = similar

        # Recently viewed cars, kept in the session (most recent first)
        recent_ids = self.request.session.get('recently_viewed', [])
        others = [pk for pk in recent_ids if pk != self.object.pk][:5]
        cars_by_id = {
            car.pk: car
            for car in Car.objects.filter(pk__in=others).prefetch_related('images')
        }
        context['recently_viewed'] = [cars_by_id[pk] for pk in others if pk in cars_by_id]
        self.request.session['recently_viewed'] = ([self.object.pk] + others)[:6]
        self.request.session.modified = True

        context['structured_data'] = [
            json_ld(vehicle_node(self.object, self.request)),
            json_ld(breadcrumb_node(self.request, [
                ('Home', '/'),
                ('Browse Cars', reverse('cars:browse_cars')),
                (f'{self.object.year} {self.object.make} {self.object.model}',
                 reverse('cars:car_detail', args=[self.object.pk])),
            ])),
        ]
        return context


class AboutView(TemplateView):
    """Customer-facing about page with dealership vision and mission"""
    template_name = 'cars/about.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['about_info'] = AboutInfo.get_solo()
        return context


class FinancingView(TemplateView):
    """Public financing options page with payment calculator link"""
    template_name = 'cars/financing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['rate'] = interest_rate()
        context['min_deposit_ratio'] = int(MIN_DEPOSIT_RATIO * 100)
        return context


class FAQView(TemplateView):
    """Public frequently asked questions page"""
    template_name = 'cars/faq.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['structured_data'] = [json_ld(faq_node(self.request))]
        return context


class PrivacyPolicyView(TemplateView):
    template_name = 'cars/privacy_policy.html'


class TermsOfServiceView(TemplateView):
    template_name = 'cars/terms_of_service.html'


class GDPRDataRequestView(LoginRequiredMixin, TemplateView):
    template_name = 'cars/gdpr_data_request.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['user'] = self.request.user
        return ctx

    def post(self, request, *args, **kwargs):
        messages.success(request, 'Your data request has been submitted. We will process it within 30 days as required by GDPR.')
        return redirect('cars:gdpr_data_request')


class PostListView(ListView):
    """Public blog/news listing"""
    model = Post
    template_name = 'cars/blog_list.html'
    context_object_name = 'posts'
    paginate_by = 6

    def get_queryset(self):
        return Post.objects.filter(is_published=True)


class PostDetailView(DetailView):
    """Public single blog/news article"""
    model = Post
    template_name = 'cars/blog_detail.html'
    context_object_name = 'post'

    def get_queryset(self):
        return Post.objects.filter(is_published=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['structured_data'] = [
            json_ld(blog_posting_node(self.object, self.request)),
            json_ld(breadcrumb_node(self.request, [
                ('Home', '/'),
                ('News', reverse('cars:blog_list')),
                (self.object.title, reverse('cars:blog_detail', args=[self.object.slug])),
            ])),
        ]
        return context


def _record_conversion_source(request, instance):
    """Remember where this visitor came from, for the conversion funnel.

    The token and the source are copied onto the record rather than
    looked up later, because page views are pruned after the retention
    window and a lead has to keep its history.
    """
    instance.visitor_id = visitor_id_from(request)
    instance.source = source_for_visitor(instance.visitor_id)


def _trade_in_estimate_for(form):
    """Our own trade-in estimate for the vehicle the customer described.

    The order form carries the estimate in a hidden field so the customer
    sees the same number we do. That field is the customer's to change, so
    the number we keep is worked out again from the details they gave us.
    """
    year = form.cleaned_data.get('trade_in_year')
    if not year:
        return None
    _, _, mid = tradein_estimate(
        year,
        form.cleaned_data.get('trade_in_make') or '',
        model=form.cleaned_data.get('trade_in_model') or '',
        mileage=form.cleaned_data.get('trade_in_mileage') or 0,
        condition=form.cleaned_data.get('trade_in_condition') or 'good',
        body_type=form.cleaned_data.get('trade_in_body_type') or '',
    )
    return mid or None


@method_decorator(rate_limit('inquiry', limit=10, window=3600), name='dispatch')
@method_decorator(captcha_required, name='dispatch')
class InquiryCreateView(CreateView):
    """Handle customer inquiry submission"""
    model = Inquiry
    form_class = InquiryForm
    template_name = 'cars/inquiry_form.html'
    success_url = reverse_lazy('cars:inquiry_thank_you')

    def form_valid(self, form):
        # Get the car from the URL parameter
        car_id = self.kwargs.get('car_id')
        car = get_object_or_404(Car, id=car_id)
        form.instance.car = car
        if self.request.user.is_authenticated:
            form.instance.user = self.request.user
        _record_conversion_source(self.request, form.instance)
        messages.success(self.request, 'Your inquiry has been submitted! We will contact you soon.')
        response = super().form_valid(form)
        send_inquiry_notification(self.object, self.request)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        car_id = self.kwargs.get('car_id')
        context['car'] = get_object_or_404(Car, id=car_id)
        return context


@method_decorator(rate_limit('order', limit=10, window=3600), name='dispatch')
@method_decorator(captcha_required, name='dispatch')
class OrderCreateView(CreateView):
    """Handle customer order submission"""
    model = Order
    form_class = OrderForm
    template_name = 'cars/order_form.html'
    success_url = reverse_lazy('cars:order_thank_you')
    
    def form_valid(self, form):
        # Get the car from the URL parameter
        car_id = self.kwargs.get('car_id')
        car = get_object_or_404(Car, id=car_id)
        form.instance.car = car
        if self.request.user.is_authenticated:
            form.instance.user = self.request.user
        # The estimate is worked out again here, so what we store is our
        # own number and not something typed into a hidden form field.
        form.instance.trade_in_estimate = _trade_in_estimate_for(form)
        # The deposit is quoted from the price and trade-in on the order,
        # and copied onto it, so a later change to the rule does not
        # rewrite what this customer was shown.
        form.instance.deposit_amount = order_deposit(
            form.instance.price, form.instance.trade_in_value,
        )
        _record_conversion_source(self.request, form.instance)
        messages.success(self.request, 'Your order has been submitted! Our team will review it shortly.')
        response = super().form_valid(form)
        self.request.session['order_id'] = self.object.pk
        send_order_notification(self.object, self.request)
        send_order_confirmation_email(self.object, self.request)
        notify_staff(
            f'New order #{self.object.pk}',
            f'{self.object.customer_name} placed an order for {self.object.car}.',
            obj=self.object,
            url=reverse('cars:orders_list'),
            exclude_user=(
                self.request.user if self.request.user.is_authenticated else None
            ),
        )
        return response
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        car_id = self.kwargs.get('car_id')
        context['car'] = get_object_or_404(Car, id=car_id)
        return context


def inquiry_thank_you(request):
    """Thank you page after inquiry submission"""
    return render(request, 'cars/inquiry_thank_you.html')


def order_thank_you(request):
    """Thank you page after order submission, with the deposit payment card."""
    order = None
    order_id = request.session.get('order_id')
    if order_id:
        order = Order.objects.filter(pk=order_id).select_related('car').first()

    context = {'order': order}
    if order is not None:
        from payments import services as payment_services
        context['deposit'] = order.deposit_due()
        context['order_token'] = payment_services.order_token(order)
        context['mpesa_enabled'] = bool(
            getattr(settings, 'MPESA_CONSUMER_KEY', '')
        )
    return render(request, 'cars/order_thank_you.html', context)


def _order_for_payment(request, pk):
    """The order, if this visitor is allowed to pay its deposit."""
    from payments import services as payment_services

    order = get_object_or_404(Order, pk=pk)
    token = request.POST.get('token') or request.GET.get('token')
    token_order_id = payment_services.read_order_token(token)

    is_owner = (
        request.user.is_authenticated and order.user_id == request.user.pk
    )
    in_session = request.session.get('order_id') == order.pk

    if is_owner or request.user.is_staff or in_session or token_order_id == order.pk:
        return order
    return None


@require_POST
def order_pay_deposit(request, pk):
    """Start an M-Pesa deposit for an order (POST only)."""
    from payments import services as payment_services

    order = _order_for_payment(request, pk)
    if order is None:
        messages.error(request, 'That order could not be found.')
        return redirect('cars:home')

    if order.is_deposit_paid():
        messages.info(request, 'The deposit for this order has already been paid.')
        return redirect('cars:my_activity' if request.user.is_authenticated else 'cars:home')

    if order.status == 'cancelled':
        messages.error(request, 'This order has been cancelled.')
        return redirect('cars:my_activity' if request.user.is_authenticated else 'cars:home')

    phone = (request.POST.get('phone_number') or order.customer_phone).strip()
    txn, result, error = payment_services.start_payment(
        request,
        phone_number=phone,
        amount=order.deposit_due(),
        purpose='order',
        order=order,
    )

    if error:
        messages.error(request, error)
    elif txn and result:
        messages.info(
            request,
            'An M-Pesa request has been sent to your phone. '
            'Enter your PIN to complete the deposit.',
        )
        return redirect(payment_services.payment_status_url(txn))

    # Fall back to whichever page the customer came from.
    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(next_url)
    if request.user.is_authenticated:
        return redirect('cars:my_activity')
    return redirect('cars:order_thank_you')


@method_decorator(rate_limit('appointment', limit=10, window=3600), name='dispatch')
@method_decorator(captcha_required, name='dispatch')
class AppointmentCreateView(CreateView):
    """Public test-drive booking form for a specific car"""
    model = Appointment
    form_class = AppointmentForm
    template_name = 'cars/appointment_form.html'
    success_url = reverse_lazy('cars:car_appointment_thank_you')

    def form_valid(self, form):
        car = get_object_or_404(Car, id=self.kwargs.get('car_id'))
        form.instance.car = car
        if self.request.user.is_authenticated:
            form.instance.user = self.request.user
        _record_conversion_source(self.request, form.instance)
        messages.success(
            self.request,
            f'Your test drive of the {car.year} {car.make} {car.model} is requested! '
            'We will confirm your appointment by email.',
        )
        response = super().form_valid(form)
        send_appointment_notification(self.object, self.request)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['car'] = get_object_or_404(Car, id=self.kwargs.get('car_id'))
        return context


def car_appointment_thank_you(request):
    """Thank you page after booking a test drive"""
    return render(request, 'cars/appointment_thank_you.html')


class TradeInView(TemplateView):
    """Public page: what is my vehicle worth as a trade-in?"""

    template_name = 'cars/trade_in.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('form', TradeInForm())
        context.setdefault('estimate', None)
        return context

    def post(self, request, *args, **kwargs):
        """Estimate without JavaScript: the form posts back to the page."""
        form = TradeInForm(request.POST)
        estimate = None
        if form.is_valid():
            estimate = tradein_breakdown(**form.cleaned_data)
        context = self.get_context_data()
        context['form'] = form
        context['estimate'] = estimate
        return render(request, self.template_name, context)


@require_POST
@rate_limit('trade_in', limit=60, window=3600)
def trade_in_estimate(request):
    """Return a trade-in estimate as JSON (used by the order form)."""
    data = request.POST.dict() if request.POST else _read_json(request)
    form = TradeInForm(data)
    if not form.is_valid():
        return JsonResponse(
            {'error': 'Please check the details you entered.'},
            status=400,
        )

    estimate = tradein_breakdown(**form.cleaned_data)
    return JsonResponse({
        'low': estimate['low'],
        'high': estimate['high'],
        'mid': estimate['mid'],
        'breakdown': {
            'age': estimate['age'],
            'new_price': estimate['new_price'],
            'make_factor': round(estimate['make_factor'], 3),
            'model_factor': round(estimate['model_factor'], 3),
            'age_factor': round(estimate['age_factor'], 3),
            'mileage_factor': round(estimate['mileage_factor'], 3),
            'condition_factor': round(estimate['condition_factor'], 3),
        },
    })


class MyActivityView(LoginRequiredMixin, TemplateView):
    """Logged-in customer's inquiries, orders, and test drives"""
    template_name = 'cars/my_activity.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['inquiries'] = Inquiry.objects.filter(user=user).select_related('car')
        context['orders'] = Order.objects.filter(user=user).select_related('car')
        context['appointments'] = Appointment.objects.filter(user=user).select_related('car')
        context['saved_searches'] = SavedSearch.objects.filter(user=user)
        context['listing_requests'] = ListingRequest.objects.filter(user=user)
        context['financing_applications'] = FinancingApplication.objects.filter(user=user)
        context['hire_bookings'] = HireBooking.objects.filter(
            user=user
        ).select_related('hire_car')
        context['alert_profile'] = Profile.objects.get_or_create(user=user)[0]
        return context


@rate_limit('saved_search', limit=5, window=600)
@captcha_required
def saved_search_create(request):
    """Create a saved search and email any current matches (POST only)"""
    if request.method != 'POST':
        return redirect('cars:browse_cars')

    form = SavedSearchForm(request.POST)
    if form.is_valid():
        search = form.save(commit=False)
        if request.user.is_authenticated:
            search.user = request.user
        search.save()
        matches = list(search.match_cars()[:10])
        if matches:
            send_saved_search_alert_email(search, matches, request)
            messages.success(
                request,
                f'Search saved. We emailed you {len(matches)} matching vehicle{"s" if len(matches) != 1 else ""}.',
            )
        else:
            messages.success(
                request,
                'Search saved. We will email you when matching vehicles arrive.',
            )
    else:
        messages.error(request, 'Please check the alert form: a valid email address is required.')

    return redirect(_safe_next(request) or 'cars:browse_cars')


def saved_search_delete(request, pk):
    """Remove one of the logged-in user's saved searches (POST only)"""
    if request.method != 'POST':
        return redirect('cars:my_activity')
    if not request.user.is_authenticated:
        return redirect('accounts:login')

    search = get_object_or_404(SavedSearch, pk=pk, user=request.user)
    search.delete()
    messages.success(request, 'Saved search removed.')
    return redirect('cars:my_activity')


def saved_search_edit(request, pk):
    """Edit one of the logged-in user's saved searches and preview matches"""
    if not request.user.is_authenticated:
        return redirect('accounts:login')

    search = get_object_or_404(SavedSearch, pk=pk, user=request.user)

    if request.method == 'POST':
        form = SavedSearchForm(request.POST, instance=search)
        if form.is_valid():
            form.save()
            messages.success(request, 'Saved search updated.')
            return redirect('cars:my_activity')
    else:
        form = SavedSearchForm(instance=search)

    context = {
        'form': form,
        'search': search,
        'matches': list(search.match_cars()[:10]),
    }
    return render(request, 'cars/saved_search_form.html', context)


class ContactView(View):
    """Public contact page: form + message saving + staff email"""
    def get(self, request):
        form = ContactForm()
        return render(request, 'cars/contact.html', {
            'form': form,
            'contact_info': ContactInfo.get_solo(),
        })

    @method_decorator(rate_limit('contact', limit=5, window=600))
    def post(self, request):
        form = ContactForm(request.POST)
        if form.is_valid():
            if not verify_captcha(request):
                messages.error(request, 'Please complete the verification and try again.')
                return render(request, 'cars/contact.html', {
                    'form': form,
                    'contact_info': ContactInfo.get_solo(),
                }, status=400)
            message = form.save()
            send_contact_notification(message)
            messages.success(
                request,
                'Thank you for your message! We will get back to you shortly.',
            )
            return redirect('cars:contact')
        return render(request, 'cars/contact.html', {
            'form': form,
            'contact_info': ContactInfo.get_solo(),
        }, status=400)


class ReviewListCreateView(View):
    """Public reviews page: visible testimonials + submission form for
    logged-in customers. New submissions await staff approval."""
    template_name = 'cars/reviews.html'

    def get(self, request):
        initial = {}
        if request.user.is_authenticated:
            initial['customer_name'] = request.user.get_full_name() or request.user.username
        return render(request, self.template_name, self._context(request, TestimonialForm(initial=initial)))

    @method_decorator(rate_limit('review', limit=10, window=3600))
    def post(self, request):
        if not request.user.is_authenticated:
            messages.info(request, 'Please sign in to leave a review.')
            return redirect('accounts:login')

        form = TestimonialForm(request.POST)
        if form.is_valid():
            if not verify_captcha(request):
                messages.error(request, 'Please complete the verification and try again.')
                return render(request, self.template_name, self._context(request, form), status=400)
            testimonial = form.save(commit=False)
            testimonial.user = request.user
            testimonial.is_visible = False
            testimonial.save()
            send_testimonial_notification(testimonial)
            messages.success(
                request,
                'Thank you! Your review has been submitted and will appear once approved.',
            )
            return redirect('cars:reviews')
        return render(request, self.template_name, self._context(request, form), status=400)

    def _context(self, request, form):
        testimonials = Testimonial.objects.filter(is_visible=True)
        return {
            'testimonials': testimonials,
            'form': form,
            'structured_data': [json_ld(dealer_node(request, testimonials))],
        }


@rate_limit('newsletter', limit=5, window=600)
@captcha_required
def newsletter_subscribe(request):
    """Footer newsletter signup (POST only)"""
    if request.method != 'POST':
        return redirect('cars:home')

    form = NewsletterForm(request.POST)
    if form.is_valid():
        email = form.cleaned_data['email']
        subscription, created = NewsletterSubscription.objects.get_or_create(
            email=email,
            defaults={'is_active': True},
        )
        if not created and not subscription.is_active:
            subscription.is_active = True
            subscription.save(update_fields=['is_active'])
        messages.success(request, 'You are subscribed to our newsletter. Welcome aboard!')
    else:
        messages.error(request, 'Please enter a valid email address.')

    return redirect(_safe_next(request) or 'cars:home')


# ==================== STAFF/ADMIN VIEWS ====================

class DashboardView(View):
    """Staff dashboard with dealership statistics"""
    def get(self, request):
        if not request.user.is_staff:
            return redirect('cars:home')

        # Traffic counters for the "Website traffic" card.
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=6)
        today_views = PageView.objects.filter(created_at__gte=today_start)
        week_views = PageView.objects.filter(created_at__gte=week_start)

        context = {
            'total_cars': Car.objects.count(),
            'available_cars': Car.objects.filter(status='available').count(),
            'sold_cars': Car.objects.filter(status='sold').count(),
            'total_customers': Customer.objects.filter(is_active=True).count(),
            'pending_inquiries': Inquiry.objects.filter(status='new').count(),
            'pending_orders': Order.objects.filter(status='pending').count(),
            'pending_appointments': Appointment.objects.filter(status='pending').count(),
            'open_listing_requests': ListingRequest.objects.filter(
                status__in=ListingRequest.OPEN_STATUSES
            ).count(),
            'open_financing_applications': FinancingApplication.objects.filter(
                status__in=FinancingApplication.OPEN_STATUSES
            ).count(),
            'hire_cars_available': HireCar.objects.filter(
                status__in=HireCar.PUBLIC_STATUSES
            ).count(),
            'pending_hire_bookings': HireBooking.objects.filter(
                status='pending'
            ).count(),
            'pending_payments': MpesaTransaction.objects.filter(
                status=MpesaTransaction.STATUS_PENDING
            ).count(),
            'lead_counts': leads.lead_counts(),
            'awaiting_deposit_orders': order_recovery.awaiting_deposit().count(),
            'stale_orders': order_recovery.stale_orders().count(),
            'recent_inquiries': Inquiry.objects.all()[:5],
            'recent_orders': Order.objects.all()[:5],
            'recent_appointments': Appointment.objects.all()[:5],
            'total_sales_revenue': sum(s.sale_price for s in SalesTransaction.objects.filter(status='completed')),
            'pending_alerts': (
                CarPriceHistory.objects.filter(notified_at__isnull=True).count()
                + CarStatusHistory.objects.filter(notified_at__isnull=True).count()
            ),
            'traffic_views_today': today_views.count(),
            'traffic_visitors_today': today_views.values('visitor_id').distinct().count(),
            'traffic_views_week': week_views.count(),
            'traffic_visitors_week': week_views.values('visitor_id').distinct().count(),
        }
        return render(request, 'cars/dashboard.html', context)


class CustomerListView(ListView):
    """Staff view: Display list of customers"""
    model = Customer
    template_name = 'cars/customer_list.html'
    context_object_name = 'customers'
    paginate_by = 20
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Customer.objects.filter(is_active=True)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone_number__icontains=search)
            )
        state = self.request.GET.get('state')
        if state:
            queryset = queryset.filter(state=state)
        return queryset.order_by('last_name', 'first_name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['states'] = Customer.objects.filter(is_active=True).values_list('state', flat=True).distinct()
        return context


class InquiriesListView(ListView):
    """Staff view: the inquiry lead queue."""
    model = Inquiry
    template_name = 'cars/inquiries_list.html'
    context_object_name = 'inquiries'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = leads.inquiry_leads()
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(customer_name__icontains=search) |
                Q(customer_email__icontains=search) |
                Q(car__make__icontains=search)
            )
        assignee = self.request.GET.get('assignee')
        if assignee == 'me':
            queryset = queryset.filter(assigned_to=self.request.user)
        elif assignee == 'unassigned':
            queryset = queryset.filter(assigned_to__isnull=True)
        elif assignee and assignee.isdigit():
            queryset = queryset.filter(assigned_to_id=int(assignee))

        follow_up = self.request.GET.get('follow_up')
        today = timezone.localdate()
        if follow_up == 'overdue':
            queryset = leads.overdue(queryset, today)
        elif follow_up == 'today':
            queryset = leads.due_today(queryset, today)
        elif follow_up == 'week':
            queryset = leads.due_within(queryset, 7, today)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = Inquiry.STATUS_CHOICES
        context['staff_users'] = leads.staff_users()
        context['today'] = timezone.localdate()
        context['lead_counts'] = leads.lead_counts()
        return context


class ContactMessageListView(ListView):
    """Staff view: contact-page messages, worked the same way as inquiries."""
    model = ContactMessage
    template_name = 'cars/contact_messages_list.html'
    context_object_name = 'messages'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = leads.contact_leads()
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(email__icontains=search) |
                Q(subject__icontains=search)
            )
        assignee = self.request.GET.get('assignee')
        if assignee == 'me':
            queryset = queryset.filter(assigned_to=self.request.user)
        elif assignee == 'unassigned':
            queryset = queryset.filter(assigned_to__isnull=True)
        elif assignee and assignee.isdigit():
            queryset = queryset.filter(assigned_to_id=int(assignee))

        follow_up = self.request.GET.get('follow_up')
        today = timezone.localdate()
        if follow_up == 'overdue':
            queryset = leads.overdue(queryset, today)
        elif follow_up == 'today':
            queryset = leads.due_today(queryset, today)
        elif follow_up == 'week':
            queryset = leads.due_within(queryset, 7, today)

        return queryset.order_by('-sent_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = ContactMessage.STATUS_CHOICES
        context['staff_users'] = leads.staff_users()
        context['today'] = timezone.localdate()
        context['lead_counts'] = leads.lead_counts()
        return context


class OrdersListView(ListView):
    """Staff view: Display list of orders"""
    model = Order
    template_name = 'cars/orders_list.html'
    context_object_name = 'orders'
    paginate_by = 20
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Order.objects.select_related('car')
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(customer_name__icontains=search) |
                Q(customer_email__icontains=search) |
                Q(car__make__icontains=search)
            )
        view_filter = self.request.GET.get('filter')
        if view_filter == 'awaiting_deposit':
            queryset = order_recovery.awaiting_deposit(queryset)
        elif view_filter == 'stale':
            queryset = order_recovery.stale_orders(queryset=queryset)
        return queryset.order_by('-order_date')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = Order.STATUS_CHOICES
        context['stale_count'] = order_recovery.stale_orders().count()
        context['awaiting_deposit_count'] = (
            order_recovery.awaiting_deposit().count()
        )
        context['stale_after_days'] = order_recovery.STALE_AFTER_DAYS
        context['stale_ids'] = set(
            order_recovery.stale_orders().values_list('pk', flat=True)
        )
        return context


class AppointmentsListView(ListView):
    """Staff view: Display list of test-drive appointments"""
    model = Appointment
    template_name = 'cars/appointments_list.html'
    context_object_name = 'appointments'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Appointment.objects.select_related('car')
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(customer_name__icontains=search) |
                Q(customer_email__icontains=search) |
                Q(car__make__icontains=search)
            )
        return queryset.order_by('preferred_date', 'preferred_time')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = Appointment.objects.values_list('status', flat=True).distinct()
        return context


def update_appointment_status(request, pk):
    """Staff view: Update an appointment's status (POST only)"""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:appointments_list')

    appointment = get_object_or_404(Appointment, pk=pk)
    status = request.POST.get('status')
    valid_statuses = [choice[0] for choice in Appointment.STATUS_CHOICES]
    if status in valid_statuses:
        appointment.status = status
        appointment.save(update_fields=['status', 'updated_at'])
        messages.success(
            request,
            f'Appointment for {appointment.customer_name} marked as {appointment.get_status_display()}.',
        )
        send_appointment_status_email(appointment)
    else:
        messages.error(request, 'Invalid status selected.')

    return redirect(_safe_next(request) or 'cars:appointments_list')


class SalesListView(ListView):
    """Staff view: Display list of sales transactions"""
    model = SalesTransaction
    template_name = 'cars/sales_list.html'
    context_object_name = 'sales'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = SalesTransaction.objects.select_related('car', 'customer')

        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search) |
                Q(customer__first_name__icontains=search) |
                Q(customer__last_name__icontains=search) |
                Q(car__vin__icontains=search) |
                Q(car__make__icontains=search) |
                Q(car__model__icontains=search)
            )

        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        date_from = self.request.GET.get('date_from')
        if date_from:
            queryset = queryset.filter(sale_date__date__gte=date_from)

        date_to = self.request.GET.get('date_to')
        if date_to:
            queryset = queryset.filter(sale_date__date__lte=date_to)

        return queryset.order_by('-sale_date')


class SalesDetailView(View):
    """Staff view: Display a single sales transaction"""
    def get(self, request, pk):
        if not request.user.is_staff:
            return redirect('cars:home')
        sale = get_object_or_404(SalesTransaction, pk=pk)
        return render(request, 'cars/sales_detail.html', {'sale': sale})


class CustomerDetailView(View):
    """Staff view: Display a customer profile with purchase history"""
    def get(self, request, pk):
        if not request.user.is_staff:
            return redirect('cars:home')
        customer = get_object_or_404(Customer, pk=pk)
        purchases = SalesTransaction.objects.filter(customer=customer).select_related('car')
        context = {
            'customer': customer,
            'purchases': purchases,
        }
        return render(request, 'cars/customer_detail.html', context)


class StaffRequiredMixin(View):
    """Allow only staff (incl. staff-created accounts and admins)"""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)


class CustomerCreateView(StaffRequiredMixin, CreateView):
    """Staff view: add a new customer record on the website"""
    model = Customer
    form_class = CustomerForm
    template_name = 'cars/customer_form.html'

    def form_valid(self, form):
        messages.success(self.request, f'Customer {form.instance} created successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('cars:customer_detail', args=[self.object.pk])


class CustomerUpdateView(StaffRequiredMixin, UpdateView):
    """Staff view: edit an existing customer record on the website"""
    model = Customer
    form_class = CustomerForm
    template_name = 'cars/customer_form.html'

    def form_valid(self, form):
        messages.success(self.request, f'Customer {form.instance} updated successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('cars:customer_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = True
        return context


def _generate_invoice_number():
    """Return a unique invoice number like INV-20261008-4821"""
    stamp = timezone.now().strftime('%Y%m%d%H%M%S')
    while True:
        candidate = f'INV-{stamp}-{random.randint(1000, 9999)}'
        if not SalesTransaction.objects.filter(invoice_number=candidate).exists():
            return candidate


class SaleRecordMixin:
    """Compute total_amount (sale price minus trade-in) for staff sale forms"""
    def form_valid(self, form):
        trade_in = form.cleaned_data.get('trade_in_value') or 0
        form.instance.total_amount = form.cleaned_data['sale_price'] - trade_in
        return super().form_valid(form)


class SaleCreateView(StaffRequiredMixin, SaleRecordMixin, CreateView):
    """Staff view: record a new sale on the website"""
    model = SalesTransaction
    form_class = SalesTransactionForm
    template_name = 'cars/sale_form.html'

    def form_valid(self, form):
        form.instance.invoice_number = _generate_invoice_number()
        messages.success(self.request, f'Sale {form.instance.invoice_number} recorded successfully.')
        return super().form_valid(form)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['car'].queryset = Car.objects.exclude(status='sold')
        return form

    def get_success_url(self):
        return reverse('cars:sales_detail', args=[self.object.pk])


class SaleUpdateView(StaffRequiredMixin, SaleRecordMixin, UpdateView):
    """Staff view: edit an existing sale record on the website"""
    model = SalesTransaction
    form_class = SalesTransactionForm
    template_name = 'cars/sale_form.html'

    def form_valid(self, form):
        messages.success(self.request, f'Sale {form.instance.invoice_number} updated successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('cars:sales_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = True
        return context


class ContactInfoUpdateView(StaffRequiredMixin, UpdateView):
    """Staff view: edit the 'Visit or Call' details on the contact page"""
    model = ContactInfo
    form_class = ContactInfoForm
    template_name = 'cars/contact_info_form.html'

    def get_object(self, queryset=None):
        return ContactInfo.get_solo()

    def form_valid(self, form):
        messages.success(self.request, 'Contact info updated successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('cars:contact')


class AboutInfoUpdateView(StaffRequiredMixin, UpdateView):
    """Staff view: edit the content shown on the About page"""
    model = AboutInfo
    form_class = AboutInfoForm
    template_name = 'cars/about_info_form.html'

    def get_object(self, queryset=None):
        return AboutInfo.get_solo()

    def form_valid(self, form):
        messages.success(self.request, 'About page updated successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('cars:about')


class DealershipInfoUpdateView(StaffRequiredMixin, UpdateView):
    """Staff view: edit the dealership name and logo used site-wide"""
    model = DealershipInfo
    form_class = DealershipInfoForm
    template_name = 'cars/dealership_info_form.html'

    def get_object(self, queryset=None):
        return DealershipInfo.get_solo()

    def form_valid(self, form):
        messages.success(self.request, 'Dealership settings updated successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('cars:dealership_info_edit')


# ==================== CHATBOT ====================

_SESSION_KEY_RE = re.compile(r'^[A-Za-z0-9_-]{8,40}$')
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _chat_session_for(request, raw_key):
    """Fetch (or create) the ChatSession for this browser and return it + key.

    ``raw_key`` is untrusted input from the client; anything malformed is
    replaced with a fresh random key.
    """
    if isinstance(raw_key, str) and _SESSION_KEY_RE.match(raw_key):
        key = raw_key
    else:
        key = secrets.token_hex(16)

    ip = client_ip(request)
    try:
        validate_ipv46_address(ip)
    except ValidationError:
        ip = None

    user = request.user if request.user.is_authenticated else None
    session = ChatSession.objects.filter(session_key=key).first()
    if session is None:
        session = ChatSession.objects.create(session_key=key, ip_address=ip, user=user)
    elif user is not None and session.user_id is None:
        session.user = user
        session.save(update_fields=['user'])
    return session, key


def _read_json(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return {}


@require_POST
@rate_limit('chatbot', limit=30, window=600)
def chatbot_message(request):
    """Answer a visitor's chat message (JSON in, JSON out) and log the exchange."""
    payload = _read_json(request)
    text = (payload.get('message') or '').strip()
    if not text:
        return JsonResponse({'error': 'Please type a message.'}, status=400)
    text = text[:MAX_MESSAGE_LENGTH]

    session, key = _chat_session_for(request, payload.get('session_key'))
    # Link session to user if logged in
    if request.user.is_authenticated and not session.user:
        session.user = request.user
        session.save(update_fields=['user'])
    ChatMessage.objects.create(session=session, sender='user', text=text)

    result = chatbot_get_reply(text, user=session.user)
    ChatMessage.objects.create(
        session=session,
        sender='bot',
        text=result['reply'],
        intent=result['intent'],
    )
    session.save(update_fields=['last_activity_at'])


    return JsonResponse({
        'reply': result['reply'],
        'suggestions': result['suggestions'],
        'links': result['links'],
        'escalate': result['escalate'],
        'session_key': key,
    })


@require_POST
@rate_limit('chatbot_handoff', limit=5, window=3600)
def chatbot_handoff(request):
    """Turn a chatbot conversation into a contact message for staff to follow up."""
    payload = _read_json(request)
    name = (payload.get('name') or '').strip()[:100]
    email = (payload.get('email') or '').strip()[:254]

    errors = {}
    if not name:
        errors['name'] = 'Please enter your name.'
    if not _EMAIL_RE.match(email):
        errors['email'] = 'Please enter a valid email address.'
    if errors:
        return JsonResponse({'errors': errors}, status=400)

    session, key = _chat_session_for(request, payload.get('session_key'))
    transcript = "\n".join(
        f"{message.get_sender_display()}: {message.text}"
        for message in session.messages.all()
    ) or "(no messages yet)"

    message = ContactMessage.objects.create(
        name=name,
        email=email,
        subject=f"Chatbot follow-up request from {name}"[:150],
        message=(
            "A visitor asked to be contacted after using the site chatbot.\n\n"
            f"--- Conversation ---\n{transcript}"
        ),
    )
    session.is_escalated = True
    session.contact_message = message
    session.save(update_fields=['is_escalated', 'contact_message', 'last_activity_at'])
    send_contact_notification(message)

    return JsonResponse({'ok': True, 'session_key': key})


class ChatSessionListView(StaffRequiredMixin, ListView):
    """Staff view: review chatbot conversations, newest first"""
    model = ChatSession
    template_name = 'cars/chat_session_list.html'
    context_object_name = 'sessions'
    paginate_by = 25

    def get_queryset(self):
        queryset = ChatSession.objects.all()
        if self.request.GET.get('escalated') == '1':
            queryset = queryset.filter(is_escalated=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['escalated_only'] = self.request.GET.get('escalated') == '1'
        context['escalated_count'] = ChatSession.objects.filter(is_escalated=True).count()
        return context


class ChatSessionDetailView(StaffRequiredMixin, DetailView):
    """Staff view: read a single chatbot conversation in full"""
    model = ChatSession
    template_name = 'cars/chat_session_detail.html'
    context_object_name = 'chat_session'

    def get_queryset(self):
        return ChatSession.objects.prefetch_related('messages')


class CarRecordMixin(View):
    """Shared image upload handling for the staff Add/Edit Car forms"""
    action_verb = 'saved'

    def form_valid(self, form):
        files = self.request.FILES.getlist('images')
        invalid = self._invalid_image(files)
        if invalid:
            form.add_error('images', invalid)
            return self.form_invalid(form)
        response = super().form_valid(form)
        self._save_images(files)
        messages.success(self.request, f'{self.object} {self.action_verb} successfully.')
        return response

    @staticmethod
    def _invalid_image(files):
        """The error message for the first file that cannot be used, if any.

        Photos are checked before they are stored: the file type, the real
        content and the size all matter, and the file itself is resized and
        re-encoded when it is saved.
        """
        for uploaded in files:
            if uploaded is None or uploaded.size == 0:
                continue
            try:
                validate_image_upload(uploaded)
            except ValidationError as exc:
                return '; '.join(exc.messages)
        return None

    def _save_images(self, files):
        raise NotImplementedError


class CarCreateView(StaffRequiredMixin, CarRecordMixin, CreateView):
    """Staff view: allow creating an inventory car on the website"""
    model = Car
    form_class = CarForm
    template_name = 'cars/car_form.html'
    action_verb = 'added to inventory'

    def get_success_url(self):
        return reverse('cars:car_detail', args=[self.object.pk])

    def _save_images(self, files):
        for i, f in enumerate(files):
            if f is None or f.size == 0:
                continue
            CarImage.objects.create(car=self.object, image=f, is_primary=(i == 0))


class CarUpdateView(StaffRequiredMixin, CarRecordMixin, UpdateView):
    """Staff view: edit an existing inventory car on the website"""
    model = Car
    form_class = CarForm
    template_name = 'cars/car_form.html'
    action_verb = 'updated'

    def get_success_url(self):
        return reverse('cars:car_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = True
        context['existing_images'] = self.object.images.all()
        return context

    def _save_images(self, files):
        has_existing = self.object.images.exists()
        for i, f in enumerate(files):
            if f is None or f.size == 0:
                continue
            CarImage.objects.create(
                car=self.object,
                image=f,
                is_primary=(i == 0 and not has_existing),
            )


def _safe_next(request):
    """Return the validated ?next= target, or None"""
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return None


def update_inquiry_status(request, pk):
    """Staff view: Update the status of an inquiry (POST only)"""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:inquiries_list')

    inquiry = get_object_or_404(Inquiry, pk=pk)
    status = request.POST.get('status')
    valid_statuses = [choice[0] for choice in Inquiry.STATUS_CHOICES]
    if status in valid_statuses:
        changed = status != inquiry.status
        inquiry.status = status
        inquiry.save(update_fields=['status', 'updated_at'])
        messages.success(request, f'Inquiry from {inquiry.customer_name} marked as {inquiry.get_status_display()}.')
        if changed:
            try:
                send_inquiry_status_email(inquiry)
            except Exception:
                logger.exception('Failed to send inquiry status email for inquiry %s', inquiry.pk)
            try:
                from .sms import send_inquiry_status_sms
                send_inquiry_status_sms(inquiry)
            except Exception:
                logger.exception('Failed to send inquiry status SMS for inquiry %s', inquiry.pk)
    else:
        messages.error(request, 'Invalid status selected.')

    return redirect(_safe_next(request) or 'cars:inquiries_list')


def _lead_from_kind(kind, pk):
    """Resolve the ``kind`` URL segment to a lead, or 404."""
    if kind == 'inquiry':
        return get_object_or_404(Inquiry, pk=pk)
    if kind == 'message':
        return get_object_or_404(ContactMessage, pk=pk)
    raise Http404('Unknown lead type')


def assign_lead(request, kind, pk):
    """Staff view: give a lead an owner and a follow-up date (POST only)."""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:inquiries_list')

    lead = _lead_from_kind(kind, pk)

    assignee = None
    assignee_id = request.POST.get('assigned_to', '').strip()
    if assignee_id:
        assignee = get_object_or_404(
            get_user_model(), pk=assignee_id, is_staff=True, is_active=True,
        )

    raw_date = request.POST.get('follow_up_date', '').strip()
    follow_up = None
    if raw_date:
        follow_up = parse_date(raw_date)
        if follow_up is None:
            messages.error(request, 'That follow-up date could not be read.')
            return redirect(_safe_next(request) or leads.lead_url(lead))

    leads.assign(
        lead,
        assignee,
        follow_up_date=follow_up,
        note=request.POST.get('note', '').strip(),
        actor=request.user,
    )
    messages.success(request, f'Lead updated for {lead}.')
    return redirect(_safe_next(request) or leads.lead_url(lead))


def log_lead_contact(request, kind, pk):
    """Staff view: record that the lead was actually contacted (POST only)."""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:inquiries_list')

    lead = _lead_from_kind(kind, pk)
    leads.log_contact(
        lead, actor=request.user, note=request.POST.get('note', '').strip(),
    )
    messages.success(request, f'Contact logged for {lead}.')
    return redirect(_safe_next(request) or leads.lead_url(lead))


def update_contact_message_status(request, pk):
    """Staff view: move a contact message through the lead statuses."""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:contact_messages_list')

    message = get_object_or_404(ContactMessage, pk=pk)
    status = request.POST.get('status')
    valid_statuses = [choice[0] for choice in ContactMessage.STATUS_CHOICES]
    if status in valid_statuses:
        message.status = status
        message.save(update_fields=['status'])
        messages.success(
            request,
            f'Message from {message.name} marked as '
            f'{message.get_status_display()}.',
        )
    else:
        messages.error(request, 'Invalid status selected.')

    return redirect(_safe_next(request) or 'cars:contact_messages_list')


def update_order_status(request, pk):
    """Staff view: Update the status of an order (POST only)"""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:orders_list')

    order = get_object_or_404(Order, pk=pk)
    status = request.POST.get('status')
    valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]
    if status in valid_statuses:
        changed = status != order.status
        order.status = status
        order.save(update_fields=['status'])
        messages.success(request, f'Order #{order.id} marked as {order.get_status_display()}.')
        if changed:
            send_order_status_email(order)
            notify(
                order.user,
                f'Order #{order.id} is now {order.get_status_display().lower()}',
                f'Your order for {order.car} has been updated to '
                f'{order.get_status_display()}.',
                level='warning' if order.status == 'cancelled' else 'info',
                obj=order,
                url=reverse('cars:my_activity'),
            )
    else:
        messages.error(request, 'Invalid status selected.')

    return redirect(_safe_next(request) or 'cars:orders_list')


def release_order_view(request, pk):
    """Staff view: release a stale order and free the vehicle (POST only)."""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:orders_list')

    order = get_object_or_404(Order, pk=pk)
    if not order.is_awaiting_deposit():
        messages.error(
            request,
            'Only a pending order with no deposit can be released.',
        )
    elif order_recovery.release_order(
        order,
        actor=request.user,
        reason=request.POST.get('reason', ''),
    ):
        messages.success(
            request,
            f'Order #{order.id} released. The vehicle is back on the lot '
            'if nothing else is holding it.',
        )
    else:
        messages.error(request, 'That order could not be released.')

    return redirect(_safe_next(request) or 'cars:orders_list')


def update_car_status(request, pk):
    """Staff view: mark a car's status (e.g. sold) from the detail page (POST only)"""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:car_detail', pk=pk)

    car = get_object_or_404(Car, pk=pk)
    status = request.POST.get('status')
    valid_statuses = [choice[0] for choice in Car.STATUS_CHOICES]
    if status in valid_statuses:
        car.status = status
        car.save(update_fields=['status'])
        messages.success(request, f'{car} marked as {car.get_status_display()}.')
    else:
        messages.error(request, 'Invalid status selected.')

    return redirect(_safe_next(request) or reverse('cars:car_detail', args=[car.pk]))


def send_alerts_now(request):
    """Staff view: send pending price-drop / back-in-stock alerts immediately"""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:dashboard')

    result = send_pending_alerts()
    messages.success(
        request,
        f"Alerts sent: {result['price_emails']} price-drop and "
        f"{result['stock_emails']} back-in-stock email(s).",
    )
    return redirect('cars:dashboard')


# ==================== STAFF CSV EXPORTS ====================

def export_sales_csv(request):
    """Staff view: download the (filtered) sales list as CSV"""
    if not request.user.is_staff:
        return redirect('cars:home')
    sales = SalesListView(request=request).get_queryset()
    rows = (
        [
            sale.invoice_number,
            sale.sale_date.strftime('%Y-%m-%d %H:%M'),
            sale.customer.first_name,
            sale.customer.last_name,
            sale.customer.email,
            f'{sale.car.year} {sale.car.make} {sale.car.model}',
            sale.car.vin,
            sale.sale_price,
            sale.trade_in_value,
            sale.total_amount,
            sale.payment_method,
            sale.status,
            sale.salesperson,
        ]
        for sale in sales
    )
    return stream_csv(
        'sales.csv',
        ['Invoice', 'Sale Date', 'First Name', 'Last Name', 'Email', 'Vehicle',
         'VIN', f'Sale Price ({currency_code()})', f'Trade-In ({currency_code()})',
         f'Total Amount ({currency_code()})', 'Payment Method',
         'Status', 'Salesperson'],
        rows,
    )


def export_customers_csv(request):
    """Staff view: download the (filtered) customer list as CSV"""
    if not request.user.is_staff:
        return redirect('cars:home')
    customers = CustomerListView(request=request).get_queryset()
    rows = (
        [
            customer.first_name,
            customer.last_name,
            customer.email,
            customer.phone_number,
            customer.city,
            customer.state,
            customer.zip_code,
            customer.country,
            customer.credit_score or '',
            'yes' if customer.preferred_financing else 'no',
            'active' if customer.is_active else 'inactive',
            customer.date_registered.strftime('%Y-%m-%d'),
        ]
        for customer in customers
    )
    return stream_csv(
        'customers.csv',
        ['First Name', 'Last Name', 'Email', 'Phone', 'City', 'State',
         'Zip Code', 'Country', 'Credit Score', 'Preferred Financing',
         'Status', 'Registered'],
        rows,
    )


def export_inquiries_csv(request):
    """Staff view: download the (filtered) inquiry list as CSV"""
    if not request.user.is_staff:
        return redirect('cars:home')
    inquiries = InquiriesListView(request=request).get_queryset()
    rows = (
        [
            inquiry.id,
            inquiry.customer_name,
            inquiry.customer_email,
            inquiry.customer_phone,
            f'{inquiry.car.year} {inquiry.car.make} {inquiry.car.model}',
            inquiry.message,
            inquiry.status,
            inquiry.created_at.strftime('%Y-%m-%d %H:%M'),
        ]
        for inquiry in inquiries
    )
    return stream_csv(
        'inquiries.csv',
        ['ID', 'Customer Name', 'Email', 'Phone', 'Vehicle', 'Message',
         'Status', 'Created'],
        rows,
    )


def export_orders_csv(request):
    """Staff view: download the (filtered) order list as CSV"""
    if not request.user.is_staff:
        return redirect('cars:home')
    orders = OrdersListView(request=request).get_queryset()
    rows = (
        [
            order.id,
            order.customer_name,
            order.customer_email,
            order.customer_phone,
            f'{order.car.year} {order.car.make} {order.car.model}',
            order.price,
            order.trade_in_value,
            order.down_payment,
            'yes' if order.financing_needed else 'no',
            order.status,
            order.order_date.strftime('%Y-%m-%d %H:%M'),
        ]
        for order in orders
    )
    return stream_csv(
        'orders.csv',
        ['Order ID', 'Customer Name', 'Email', 'Phone', 'Vehicle',
         f'Price ({currency_code()})', f'Trade-In ({currency_code()})',
         f'Down Payment ({currency_code()})', 'Financing', 'Status',
         'Order Date'],
        rows,
    )


def export_traffic_csv(request):
    """Staff view: download the conversion funnel as a CSV."""
    if not request.user.is_staff:
        return redirect('cars:home')

    days = parse_period(request.GET.get('days'))
    since = timezone.now() - timedelta(days=days)

    rows = (
        [
            row['source'],
            row['visitors'],
            row['inquiries'],
            row['orders'],
            row['appointments'],
            row['sales'],
            row['leads'],
            row['conversion_rate'],
            row['revenue'],
        ]
        for row in conversion_rows(since)
    )
    return stream_csv(
        'traffic-conversions.csv',
        ['Source', 'Visitors', 'Inquiries', 'Orders', 'Appointments', 'Sales',
         'Leads', 'Lead Rate %', f'Revenue ({currency_code()})'],
        rows,
    )


def export_sales_pdf(request):
    """Staff view: download the (filtered) sales list as a PDF report"""
    if not request.user.is_staff:
        return redirect('cars:home')
    sales = SalesListView(request=request).get_queryset()
    rows = (
        [
            sale.invoice_number,
            sale.sale_date.strftime('%Y-%m-%d %H:%M'),
            f'{sale.customer.first_name} {sale.customer.last_name}',
            sale.customer.email,
            f'{sale.car.year} {sale.car.make} {sale.car.model}',
            sale.car.vin,
            sale.sale_price,
            sale.total_amount,
            sale.payment_method,
            sale.status,
            sale.salesperson,
        ]
        for sale in sales
    )
    try:
        return stream_pdf(
            'sales-report.pdf',
            f'Sales Report - {timezone.now().strftime("%Y-%m-%d")}',
            ['Invoice', 'Sale Date', 'Customer', 'Email', 'Vehicle', 'VIN',
             f'Sale Price ({currency_code()})', f'Total Amount ({currency_code()})',
             'Payment Method', 'Status', 'Salesperson'],
            rows,
        )
    except ImportError as exc:
        # ReportLab missing: report it cleanly instead of a 500
        messages.error(request, str(exc))
        return redirect('cars:sales_list')


# ==================== STAFF REVIEW MODERATION ====================

class TestimonialListView(ListView):
    """Staff view: moderate customer reviews (approve/hide)"""
    model = Testimonial
    template_name = 'cars/testimonial_list.html'
    context_object_name = 'testimonials'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Testimonial.objects.all()
        visible = self.request.GET.get('visible')
        if visible in ('0', '1'):
            queryset = queryset.filter(is_visible=(visible == '1'))
        return queryset


def update_testimonial_visibility(request, pk):
    """Staff view: publish or hide a review (POST only)"""
    if not request.user.is_staff:
        return redirect('cars:home')
    if request.method != 'POST':
        return redirect('cars:testimonial_list')

    testimonial = get_object_or_404(Testimonial, pk=pk)
    visible = request.POST.get('visible')
    if visible in ('0', '1'):
        testimonial.is_visible = visible == '1'
        testimonial.save(update_fields=['is_visible'])
        action = 'published' if testimonial.is_visible else 'hidden'
        messages.success(request, f'Review by {testimonial.customer_name} {action}.')
        if testimonial.is_visible:
            notify(
                testimonial.user,
                'Your review is live',
                'Thank you! Your review now appears on our reviews page.',
                obj=testimonial,
                url=reverse('cars:reviews'),
            )
    else:
        messages.error(request, 'Invalid visibility value.')

    return redirect(_safe_next(request) or 'cars:testimonial_list')


class ReportsView(View):
    """Staff view: Sales and pipeline analytics"""
    def get(self, request):
        if not request.user.is_staff:
            return redirect('cars:home')

        completed_sales = SalesTransaction.objects.filter(status='completed').select_related('car', 'customer')

        # Monthly revenue for the last 6 months
        now = timezone.now()
        anchor = _months_ago(now, 5).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = []
        for offset in range(6):
            month_start = _add_months(anchor, offset)
            month_end = _next_month(month_start)
            revenue = completed_sales.filter(sale_date__gte=month_start, sale_date__lt=month_end) \
                                     .aggregate(total=Sum('sale_price'))['total'] or 0
            monthly_revenue.append({
                'label': month_start.strftime('%b %Y'),
                'revenue': float(revenue),
            })

        sales_by_make = list(
            completed_sales.values('car__make')
            .annotate(count=Count('id'), revenue=Sum('sale_price'))
            .order_by('-revenue')
        )

        revenue_by_payment = list(
            completed_sales.values('payment_method')
            .annotate(count=Count('id'), revenue=Sum('sale_price'))
            .order_by('-revenue')
        )

        top_models = list(
            completed_sales.values('car__make', 'car__model')
            .annotate(count=Count('id'), revenue=Sum('sale_price'))
            .order_by('-count')[:5]
        )

        total_revenue = completed_sales.aggregate(total=Sum('sale_price'))['total'] or 0
        avg_sale_price = completed_sales.aggregate(avg=Avg('sale_price'))['avg'] or 0

        total_inquiries = Inquiry.objects.count()
        total_orders = Order.objects.count()
        total_sales = completed_sales.count()
        open_items = (
            Inquiry.objects.exclude(status__in=['closed', 'not_interested']).count()
            + Order.objects.exclude(status__in=['completed', 'cancelled']).count()
        )

        inquiries_by_status = list(
            Inquiry.objects.values('status').annotate(count=Count('id')).order_by('status')
        )
        orders_by_status = list(
            Order.objects.values('status').annotate(count=Count('id')).order_by('status')
        )

        context = {
            'monthly_revenue': monthly_revenue,
            'sales_by_make': sales_by_make,
            'revenue_by_payment': revenue_by_payment,
            'top_models': top_models,
            'total_revenue': total_revenue,
            'avg_sale_price': avg_sale_price,
            'total_inquiries': total_inquiries,
            'total_orders': total_orders,
            'total_sales': total_sales,
            'open_items': open_items,
            'inquiry_to_order': round(total_orders / total_inquiries * 100, 1) if total_inquiries else 0,
            'sale_from_order': round(total_sales / total_orders * 100, 1) if total_orders else 0,
            'inquiries_by_status': inquiries_by_status,
            'orders_by_status': orders_by_status,
        }
        return render(request, 'cars/reports.html', context)


def _prev_month(dt):
    """Return a datetime one calendar month before dt"""
    year, month = dt.year, dt.month
    if month == 1:
        return dt.replace(year=year - 1, month=12)
    return dt.replace(month=month - 1)


def _next_month(dt):
    """Return a datetime one calendar month after dt"""
    year, month = dt.year, dt.month
    if month == 12:
        return dt.replace(year=year + 1, month=1)
    return dt.replace(month=month + 1)


def _months_ago(dt, count):
    """Return a datetime count calendar months before dt"""
    result = dt
    for _ in range(count):
        result = _prev_month(result)
    return result


def _add_months(dt, count):
    """Return a datetime count calendar months after dt"""
    result = dt
    for _ in range(count):
        result = _next_month(result)
    return result

# ==================== LIST YOUR CAR ====================

def _listing_initial(listing):
    """The listing details prefilled from what the owner told us.

    Staff get the owner's own description of the car to work from; the
    review page is where they correct it and add what the owner could
    not know.
    """
    return {
        'make': listing.make,
        'model': listing.model,
        'year': listing.year,
        'vin': listing.vin,
        'color': listing.color,
        'body_type': listing.body_type,
        'transmission': listing.transmission,
        'fuel_type': listing.fuel_type,
        'mileage': listing.mileage,
        'engine_size': listing.engine_size,
        'asking_price': listing.asking_price,
        'description': listing.description,
        'condition': 'used',
        'status': 'available',
    }


@method_decorator(rate_limit('listing_request', limit=5, window=3600), name='post')
@method_decorator(captcha_required, name='post')
class ListingRequestCreateView(LoginRequiredMixin, CreateView):
    """Public form: ask us to list your car on the website for a fee.

    Only a signed-in customer can make a request, because the request is
    tied to their account and they need somewhere to follow it.
    """
    model = ListingRequest
    form_class = ListingRequestForm
    template_name = 'cars/listing_request_form.html'
    success_url = reverse_lazy('cars:listing_request_thank_you')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        user = self.request.user
        initial.setdefault('owner_name', user.get_full_name() or user.username)
        initial.setdefault('owner_email', user.email)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['fee'] = listing_fee()
        return context

    def form_valid(self, form):
        listing = form.save(commit=False)
        listing.user = self.request.user
        # The fee is copied onto the request, so a later change to the
        # price never rewrites what this customer was quoted.
        listing.fee_amount = listing_fee()
        listing.save()
        self.object = listing
        self._save_photos(listing)
        self.request.session['listing_request_id'] = listing.pk
        messages.success(
            self.request,
            'Your request has been received. We will be in touch shortly.',
        )
        send_listing_request_notification(listing, self.request)
        from payments import services as payment_services
        phone = listing.owner_phone
        if getattr(settings, 'MPESA_CONSUMER_KEY', '') and phone and listing.fee_amount:
            try:
                txn, result, err = payment_services.start_payment(
                    self.request,
                    phone_number=phone,
                    amount=listing.fee_amount,
                    purpose='listing',
                    listing_request=listing,
                )
                if txn and result and not err:
                    self.request.session['mpesa_ref'] = txn.reference
                    messages.info(self.request, 'An M-Pesa STK Push has been sent for the listing fee. Please enter your PIN to complete payment.')
                    return redirect(payment_services.payment_status_url(txn))
            except Exception:
                logger.exception('Could not start the listing fee payment')
        return redirect(self.success_url)

    def _save_photos(self, listing):
        """Store the owner's photos and the logbook scan with the request."""
        for photo in self.request.FILES.getlist('photos'):
            if photo is None or not photo.size:
                continue
            ListingRequestPhoto.objects.create(
                request=listing,
                kind=ListingRequestPhoto.KIND_VEHICLE,
                photo=photo,
            )
        logbook = self.request.FILES.get('logbook_photo')
        if logbook and logbook.size:
            ListingRequestPhoto.objects.create(
                request=listing,
                kind=ListingRequestPhoto.KIND_LOGBOOK,
                photo=logbook,
            )


def listing_request_thank_you(request):
    """Confirmation page shown after a listing request is submitted."""
    listing = None
    listing_id = request.session.pop('listing_request_id', None)
    if listing_id and request.user.is_authenticated:
        listing = ListingRequest.objects.filter(
            pk=listing_id, user=request.user
        ).first()
    return render(
        request,
        'cars/listing_request_thank_you.html',
        {'listing_request': listing},
    )


class MyListingRequestsView(LoginRequiredMixin, ListView):
    """The customer's own listing requests, newest first."""
    model = ListingRequest
    template_name = 'cars/my_listing_requests.html'
    context_object_name = 'listing_requests'
    paginate_by = 20

    def get_queryset(self):
        return ListingRequest.objects.filter(
            user=self.request.user
        ).prefetch_related('photos')


class ListingRequestDetailView(LoginRequiredMixin, DetailView):
    """One listing request: owners see their own, staff see any of them."""
    model = ListingRequest
    template_name = 'cars/listing_request_detail.html'
    context_object_name = 'listing_request'

    def get_queryset(self):
        queryset = ListingRequest.objects.all()
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        listing = context['listing_request']
        context['vehicle_photos'] = listing.vehicle_photos()
        context['logbook_photos'] = listing.logbook_photos()
        return context


@require_POST
def listing_request_pay_fee(request, pk):
    """Owner retry: pay the listing fee with M-Pesa (POST only)."""
    from payments import services as payment_services

    listing = get_object_or_404(ListingRequest, pk=pk)
    is_owner = listing.user_id and listing.user_id == request.user.pk
    if not (is_owner or request.user.is_staff):
        messages.error(request, 'That listing request could not be found.')
        return redirect('cars:home')

    if listing.is_settled():
        messages.info(request, 'The listing fee has already been settled.')
        return redirect('cars:listing_request_detail', pk=listing.pk)

    if listing.status in ('cancelled', 'rejected'):
        messages.error(request, 'This listing request is no longer open.')
        return redirect('cars:listing_request_detail', pk=listing.pk)

    phone = (request.POST.get('phone_number') or listing.owner_phone).strip()
    txn, result, error = payment_services.start_payment(
        request,
        phone_number=phone,
        amount=listing.fee_amount,
        purpose='listing',
        listing_request=listing,
    )

    if error:
        messages.error(request, error)
        return redirect('cars:listing_request_detail', pk=listing.pk)

    if txn and result:
        messages.info(
            request,
            'An M-Pesa request has been sent to your phone. '
            'Enter your PIN to pay the listing fee.',
        )
        return redirect(payment_services.payment_status_url(txn))

    messages.error(request, 'We could not start the M-Pesa payment. Please try again.')
    return redirect('cars:listing_request_detail', pk=listing.pk)


class ListingRequestsListView(StaffRequiredMixin, ListView):
    """Staff view: every request to list a customer's car."""
    model = ListingRequest
    template_name = 'cars/listing_requests_list.html'
    context_object_name = 'listing_requests'
    paginate_by = 20

    def get_queryset(self):
        queryset = ListingRequest.objects.select_related('user', 'car')

        status = self.request.GET.get('status', '').strip()
        if status:
            queryset = queryset.filter(status=status)

        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(owner_name__icontains=search)
                | Q(owner_email__icontains=search)
                | Q(vin__icontains=search)
                | Q(make__icontains=search)
                | Q(model__icontains=search)
            )

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_filter'] = self.request.GET.get('status', '')
        context['search'] = self.request.GET.get('search', '')
        context['status_choices'] = ListingRequest.STATUS_CHOICES
        context['open_count'] = ListingRequest.objects.filter(
            status__in=ListingRequest.OPEN_STATUSES
        ).count()
        return context


class ListingRequestReviewView(StaffRequiredMixin, View):
    """Staff view: verify the request, then publish the listing."""
    template_name = 'cars/listing_request_review.html'

    def get(self, request, pk):
        listing = get_object_or_404(ListingRequest, pk=pk)
        return render(request, self.template_name, self._context(listing))

    def _context(self, listing, review_form=None, publish_form=None):
        return {
            'listing_request': listing,
            'review_form': review_form or ListingRequestReviewForm(instance=listing),
            'publish_form': publish_form or ListingPublishForm(
                initial=_listing_initial(listing)
            ),
            'vehicle_photos': listing.vehicle_photos(),
            'logbook_photos': listing.logbook_photos(),
            'can_publish': listing.can_be_published(),
        }


@require_POST
def listing_request_update(request, pk):
    """Staff view: record the verification, the fee and the notes (POST only).

    The same form saves progress and rejects the request; the button that
    was pressed says which one it was.
    """
    if not request.user.is_staff:
        return redirect('cars:home')

    listing = get_object_or_404(ListingRequest, pk=pk)
    back = reverse('cars:listing_request_review', args=[listing.pk])

    if request.POST.get('action') == 'reject':
        reason = (request.POST.get('rejection_reason') or '').strip()
        if not reason:
            messages.error(request, 'Please give a reason for rejecting the request.')
            return redirect(back)
        listing.status = 'rejected'
        listing.rejection_reason = reason
        listing.reviewed_by = request.user
        listing.reviewed_at = timezone.now()
        listing.save(update_fields=[
            'status', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'updated_at',
        ])
        send_listing_request_status_email(listing)
        messages.success(request, f'Request {listing.reference} rejected. The owner has been emailed.')
        return redirect(back)

    previous_status = listing.status
    form = ListingRequestReviewForm(request.POST, instance=listing)
    if not form.is_valid():
        messages.error(request, 'Please check the details you entered.')
        return redirect(back)

    listing = form.save(commit=False)
    if not form.cleaned_data.get('status'):
        # Staff left the status alone, so it stays where it was.
        listing.status = previous_status
    if listing.is_settled() and not listing.payment_received_at:
        listing.payment_received_at = timezone.now()
    if listing.status == 'submitted':
        listing.status = 'under_review'
    listing.reviewed_by = request.user
    listing.reviewed_at = timezone.now()
    listing.save()

    if listing.status != previous_status:
        send_listing_request_status_email(listing)

    messages.success(request, f'Request {listing.reference} updated.')
    return redirect(back)


@require_POST
def listing_request_publish(request, pk):
    """Staff view: publish the listing on the owner's behalf (POST only).

    The gate is the whole point of the feature: nothing goes live until
    the car and the logbook have both been verified and the listing fee
    has been settled.
    """
    if not request.user.is_staff:
        return redirect('cars:home')

    listing = get_object_or_404(ListingRequest, pk=pk)
    back = reverse('cars:listing_request_review', args=[listing.pk])

    if listing.status == 'listed':
        messages.error(request, 'This request has already been published.')
        return redirect(back)

    form = ListingPublishForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Please check the listing details before publishing.')
        return redirect(back)

    if not listing.vehicle_verified:
        messages.error(
            request,
            'Tick "vehicle verified" and save the request before publishing.',
        )
        return redirect(back)
    if not listing.logbook_verified:
        messages.error(
            request,
            'Tick "logbook verified" and save the request before publishing.',
        )
        return redirect(back)
    if not listing.is_settled():
        messages.error(
            request,
            'Record the listing fee as paid (or waived) before publishing.',
        )
        return redirect(back)

    car = form.save(commit=False)
    # We do not buy the car, so there is no purchase price unless staff
    # valued it for the stock books.
    car.purchase_price = form.cleaned_data.get('purchase_price') or 0
    car.status = form.cleaned_data.get('status') or 'available'
    car.save()

    # The owner's photos become the photos of the listing.
    for index, photo in enumerate(listing.vehicle_photos()):
        try:
            with photo.photo.open('rb') as handle:
                CarImage.objects.create(
                    car=car,
                    image=handle,
                    is_primary=(index == 0),
                )
        except Exception:
            logger.warning(
                'Could not copy the owner photo %s onto listing %s',
                photo.pk, car, exc_info=True,
            )

    # Photos staff took while they inspected the car.
    for uploaded in request.FILES.getlist('images'):
        if uploaded is None or not uploaded.size:
            continue
        CarImage.objects.create(car=car, image=uploaded, is_primary=False)

    listing.car = car
    listing.status = 'listed'
    listing.reviewed_by = request.user
    listing.reviewed_at = timezone.now()
    listing.save()

    messages.success(
        request,
        f'{listing.vehicle_description()} is now listed on the website.',
    )
    send_listing_request_status_email(listing, car=car)
    return redirect(reverse('cars:car_detail', args=[car.pk]))


# ==================== FINANCING APPLICATIONS ====================
#
# A customer asks us to finance a car; we work out what the loan would
# look like and hand it to a human to decide. Nothing here approves
# anything by itself.


def _financing_initial(user, car_id=None):
    """Prefill the application with who is asking and, if given, the car."""
    initial = {}
    if user.is_authenticated:
        initial['customer_name'] = user.get_full_name() or user.username
        initial['customer_email'] = user.email
    if car_id:
        car = Car.objects.filter(pk=car_id, status='available').first()
        if car:
            initial['car'] = car
            initial['price'] = car.asking_price
    return initial


def _financing_context(form=None):
    return {
        'form': form or FinancingApplicationForm(),
        'rate': interest_rate(),
        'terms': FinancingApplication.TERM_CHOICES,
        'min_deposit_ratio': int(MIN_DEPOSIT_RATIO * 100),
    }


@method_decorator(rate_limit('financing_application', limit=5, window=3600), name='post')
@method_decorator(captcha_required, name='post')
class FinancingApplyView(View):
    """Public form: ask us to finance a car, with no obligation.

    Anyone may apply - they do not have to have an account yet - but a
    signed-in customer has it linked to theirs so they can follow it.
    """

    template_name = 'cars/financing_apply.html'

    def get(self, request):
        form = FinancingApplicationForm(
            initial=_financing_initial(request.user, request.GET.get('car'))
        )
        return render(request, self.template_name, _financing_context(form))

    def post(self, request):
        form = FinancingApplicationForm(request.POST)
        if not form.is_valid():
            return render(
                request, self.template_name, _financing_context(form), status=400,
            )

        application = form.save(commit=False)
        if request.user.is_authenticated:
            application.user = request.user
        # The rate we quote now is copied onto the application, so a later
        # change to it never rewrites this customer's figures.
        application.interest_rate = interest_rate()
        application.recalculate()
        application.save()

        request.session['financing_application_id'] = application.pk
        messages.success(
            request,
            'Your application has been received. Our finance team will be in touch shortly.',
        )
        send_financing_notification(application, request)
        return redirect('cars:financing_thank_you')


def financing_thank_you(request):
    """Confirmation page shown after a financing application is submitted."""
    application = None
    application_id = request.session.pop('financing_application_id', None)
    if application_id:
        queryset = FinancingApplication.objects.all()
        if not request.user.is_staff:
            if request.user.is_authenticated:
                queryset = queryset.filter(user=request.user)
            else:
                queryset = queryset.filter(user__isnull=True)
        application = queryset.filter(pk=application_id).first()
    return render(
        request,
        'cars/financing_thank_you.html',
        {'application': application},
    )


class MyFinancingApplicationsView(LoginRequiredMixin, ListView):
    """The customer's own financing applications, newest first."""
    model = FinancingApplication
    template_name = 'cars/my_financing_applications.html'
    context_object_name = 'applications'
    paginate_by = 20

    def get_queryset(self):
        return FinancingApplication.objects.filter(user=self.request.user)


class FinancingApplicationDetailView(LoginRequiredMixin, DetailView):
    """One financing application: the customer sees their own, staff any."""
    model = FinancingApplication
    template_name = 'cars/financing_application_detail.html'
    context_object_name = 'application'

    def get_queryset(self):
        queryset = FinancingApplication.objects.all()
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)


class FinancingApplicationsListView(StaffRequiredMixin, ListView):
    """Staff view: every financing application, with the quote on it."""
    model = FinancingApplication
    template_name = 'cars/financing_applications_list.html'
    context_object_name = 'applications'
    paginate_by = 20

    def get_queryset(self):
        queryset = FinancingApplication.objects.select_related('user', 'car')

        status = self.request.GET.get('status', '').strip()
        if status:
            queryset = queryset.filter(status=status)

        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(customer_name__icontains=search)
                | Q(customer_email__icontains=search)
                | Q(customer_phone__icontains=search)
                | Q(car_label__icontains=search)
            )

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_filter'] = self.request.GET.get('status', '')
        context['search'] = self.request.GET.get('search', '')
        context['status_choices'] = FinancingApplication.STATUS_CHOICES
        context['open_count'] = FinancingApplication.objects.filter(
            status__in=FinancingApplication.OPEN_STATUSES
        ).count()
        return context


class FinancingApplicationReviewView(StaffRequiredMixin, View):
    """Staff view: read the application and record the decision."""
    template_name = 'cars/financing_application_review.html'

    def get(self, request, pk):
        application = get_object_or_404(FinancingApplication, pk=pk)
        return render(request, self.template_name, self._context(application))

    def _context(self, application, form=None):
        form = form or FinancingReviewForm(instance=application)
        return {
            'application': application,
            'form': form,
            'quote_table': financing_quote_table(application),
        }


def financing_quote_table(application):
    """What the loan looks like over each term we offer.

    Staff see the whole ladder, because the right answer is often a
    different term from the one the customer asked for.
    """
    rows = []
    for months in LOAN_TERMS:
        payment = monthly_payment(application.requested_amount, application.interest_rate, months)
        rows.append({
            'months': months,
            'monthly': payment,
            'total': total_repayable(application.requested_amount, application.interest_rate, months),
        })
    return rows


@require_POST
def financing_application_update(request, pk):
    """Staff view: record the decision on an application (POST only)."""
    if not request.user.is_staff:
        return redirect('cars:home')

    application = get_object_or_404(FinancingApplication, pk=pk)
    back = reverse('cars:financing_application_review', args=[application.pk])

    previous_status = application.status
    form = FinancingReviewForm(request.POST, instance=application)
    if not form.is_valid():
        messages.error(request, 'Please check the decision you entered.')
        return render(
            request,
            'cars/financing_application_review.html',
            FinancingApplicationReviewView()._context(application, form),
            status=400,
        )

    application = form.save(commit=False)
    if not form.cleaned_data.get('status'):
        # Staff left the status alone, so it stays where it was.
        application.status = previous_status
    if application.status == 'approved' and application.approved_amount is None:
        application.approved_amount = application.requested_amount
    application.reviewed_by = request.user
    application.reviewed_at = timezone.now()
    application.save()

    if application.status != previous_status:
        send_financing_status_email(application)

    messages.success(request, f'Application {application.reference} updated.')
    return redirect(back)


# Service bookings
class ServiceBookingCreateView(CreateView):
    model = ServiceRecord
    template_name = 'cars/service_booking.html'
    fields = ['service_type', 'service_date', 'description', 'customer_name', 'customer_email', 'customer_phone']
    success_url = '/service-booking/thank-you/'

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['service_type'].widget.attrs.update({'class': 'form-select'})
        form.fields['service_date'].widget.attrs.update({'class': 'form-control', 'type': 'datetime-local'})
        form.fields['description'].widget.attrs.update({'class': 'form-control', 'rows': '4', 'placeholder': 'Describe the service needed or issue...'})
        form.fields['customer_name'].widget.attrs.update({'class': 'form-control'})
        form.fields['customer_email'].widget.attrs.update({'class': 'form-control', 'type': 'email'})
        form.fields['customer_phone'].widget.attrs.update({'class': 'form-control'})
        if self.request.user.is_authenticated:
            if not form.initial.get('customer_name') and hasattr(self.request.user, 'get_full_name'):
                form.initial['customer_name'] = self.request.user.get_full_name() or self.request.user.username
            if not form.initial.get('customer_email'):
                form.initial['customer_email'] = self.request.user.email
        return form

    def form_valid(self, form):
        obj = form.save(commit=False)
        if self.request.user.is_authenticated:
            obj.user = self.request.user
            if not obj.customer_name:
                obj.customer_name = self.request.user.get_full_name() or self.request.user.username
            if not obj.customer_email:
                obj.customer_email = self.request.user.email
        obj.status = 'scheduled'
        obj.save()
        messages.success(self.request, 'Your service booking request has been submitted.')
        return redirect(self.success_url)

def service_booking_thank_you(request):
    return render(request, 'cars/service_booking_thank_you.html')

class MyServiceBookingsView(LoginRequiredMixin, ListView):
    model = ServiceRecord
    template_name = 'cars/my_service_bookings.html'
    context_object_name = 'bookings'
    def get_queryset(self):
        return ServiceRecord.objects.filter(user=self.request.user).order_by('-service_date')

class ServiceBookingListView(StaffRequiredMixin, ListView):
    model = ServiceRecord
    template_name = 'cars/service_bookings_list.html'
    context_object_name = 'bookings'
    paginate_by = 20
    def get_queryset(self):
        return ServiceRecord.objects.all().order_by('-service_date')

class ServiceBookingDetailView(StaffRequiredMixin, DetailView):
    model = ServiceRecord
    template_name = 'cars/service_booking_detail.html'
    context_object_name = 'booking'

@require_POST
@staff_required
def service_booking_status(request, pk):
    booking = get_object_or_404(ServiceRecord, pk=pk)
    status = request.POST.get('status')
    valid = [c[0] for c in ServiceRecord.STATUS_CHOICES]
    if status in valid:
        booking.status = status
        booking.save(update_fields=['status', 'updated_at'])
        messages.success(request, 'Service booking status updated.')
    return redirect('cars:service_booking_detail', pk=booking.pk)


# Live Chat
@require_POST
@staff_required
def livechat_claim(request, pk):
    session = get_object_or_404(ChatSession, pk=pk)
    session.assigned_to = request.user
    session.status = 'active'
    session.is_escalated = True
    session.save(update_fields=['assigned_to', 'status', 'is_escalated', 'updated_at', 'last_activity_at'])
    messages.success(request, 'Chat claimed.')
    return redirect('cars:livechat_session_detail', pk=session.pk)

@require_POST
@staff_required
def livechat_reply(request, pk):
    session = get_object_or_404(ChatSession, pk=pk)
    payload = _read_json(request) if request.content_type == 'application/json' else None
    text = (payload.get('message') if payload else request.POST.get('message')) or ''
    text = text.strip()[:1000]
    if not text:
        if payload:
            return JsonResponse({'error': 'Empty'}, status=400)
        messages.error(request, 'Message required')
        return redirect('cars:livechat_session_detail', pk=session.pk)
    ChatMessage.objects.create(session=session, sender='staff', sender_user=request.user, text=text, is_read=False)
    session.assigned_to = session.assigned_to or request.user
    session.status = 'active'
    session.save(update_fields=['assigned_to', 'status', 'last_activity_at', 'updated_at'])
    if payload:
        return JsonResponse({'ok': True})
    messages.success(request, 'Reply sent.')
    return redirect('cars:livechat_session_detail', pk=session.pk)

@require_POST
@staff_required
def livechat_close(request, pk):
    session = get_object_or_404(ChatSession, pk=pk)
    session.status = 'closed'
    session.save(update_fields=['status', 'updated_at', 'last_activity_at'])
    messages.success(request, 'Chat closed.')
    return redirect('cars:livechat_inbox')

class LiveChatInboxView(StaffRequiredMixin, ListView):
    model = ChatSession
    template_name = 'cars/livechat_inbox.html'
    context_object_name = 'sessions'
    paginate_by = 30
    def get_queryset(self):
        return ChatSession.objects.exclude(status='closed').order_by('-last_activity_at')

class LiveChatSessionDetailView(StaffRequiredMixin, DetailView):
    model = ChatSession
    template_name = 'cars/livechat_session_detail.html'
    context_object_name = 'chat_session'
    def get_queryset(self):
        return ChatSession.objects.prefetch_related('messages')
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        ChatMessage.objects.filter(session=self.object, sender='user', is_read=False).update(is_read=True)
        return response


# Advanced Search
class AdvancedSearchView(ListView):
    model = Car
    template_name = 'cars/advanced_search.html'
    context_object_name = 'cars'
    paginate_by = 12
    def get_queryset(self):
        try:
            qs = Car.objects.filter(status='available').select_related('inventory').prefetch_related('images')
        except Exception:
            try:
                qs = Car.objects.filter(status='available').prefetch_related('images')
            except Exception:
                qs = Car.objects.filter(status='available')
        q = self.request.GET.get('q')
        make = self.request.GET.get('make')
        model_name = self.request.GET.get('model')
        body_type = self.request.GET.get('body_type')
        fuel_type = self.request.GET.get('fuel_type')
        transmission = self.request.GET.get('transmission')
        min_price = self.request.GET.get('min_price')
        max_price = self.request.GET.get('max_price')
        min_year = self.request.GET.get('min_year')
        max_year = self.request.GET.get('max_year')
        min_mileage = self.request.GET.get('min_mileage')
        max_mileage = self.request.GET.get('max_mileage')
        branch = self.request.GET.get('branch')
        if q:
            qs = qs.filter(Q(make__icontains=q) | Q(model__icontains=q) | Q(description__icontains=q) | Q(color__icontains=q))
        if make: qs = qs.filter(make__iexact=make)
        if model_name: qs = qs.filter(model__icontains=model_name)
        if body_type: qs = qs.filter(body_type=body_type)
        if fuel_type: qs = qs.filter(fuel_type=fuel_type)
        if transmission: qs = qs.filter(transmission=transmission)
        if branch:
            try:
                qs = qs.filter(inventory__location__icontains=branch)
            except Exception:
                pass
        if min_price:
            try: qs = qs.filter(asking_price__gte=min_price)
            except: pass
        if max_price:
            try: qs = qs.filter(asking_price__lte=max_price)
            except: pass
        if min_year:
            try: qs = qs.filter(year__gte=min_year)
            except: pass
        if max_year:
            try: qs = qs.filter(year__lte=max_year)
            except: pass
        if min_mileage:
            try: qs = qs.filter(mileage__gte=min_mileage)
            except: pass
        if max_mileage:
            try: qs = qs.filter(mileage__lte=max_mileage)
            except: pass
        try:
            return qs.order_by('-date_added')
        except Exception:
            return qs.order_by('-id')
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['makes'] = Car.objects.filter(status='available').values_list('make', flat=True).distinct().order_by('make')
        try:
            ctx['branches'] = Branch.objects.all()
        except Exception:
            ctx['branches'] = []
        return ctx


# Analytics Dashboard
from django.db.models import Count, Sum, Avg
from django.utils import timezone
from datetime import timedelta

class AnalyticsDashboardView(StaffRequiredMixin, TemplateView):
    template_name = 'cars/analytics_dashboard.html'
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.now().date()
        thirty_days_ago = today - timedelta(days=30)
        ctx['total_cars'] = Car.objects.count()
        ctx['available_cars'] = Car.objects.filter(status='available').count()
        ctx['sold_cars'] = Car.objects.filter(status='sold').count()
        ctx['total_inquiries'] = Inquiry.objects.count()
        ctx['recent_inquiries'] = Inquiry.objects.filter(created_at__date__gte=thirty_days_ago).count()
        ctx['total_sales'] = SalesTransaction.objects.count()
        ctx['recent_sales'] = SalesTransaction.objects.filter(sale_date__gte=thirty_days_ago).count()
        ctx['revenue_total'] = SalesTransaction.objects.aggregate(total=Sum('total_amount'))['total'] or 0
        ctx['revenue_30d'] = SalesTransaction.objects.filter(sale_date__gte=thirty_days_ago).aggregate(total=Sum('total_amount'))['total'] or 0
        ctx['hire_bookings'] = HireBooking.objects.count()
        ctx['service_bookings'] = ServiceRecord.objects.count()
        ctx['top_makes'] = Car.objects.filter(status='available').values('make').annotate(count=Count('id')).order_by('-count')[:5]
        ctx['recent_sales_list'] = SalesTransaction.objects.order_by('-sale_date')[:10]
        ctx['recent_inquiries_list'] = Inquiry.objects.order_by('-created_at')[:10]
        # Monthly sales data for chart
        months = []
        for i in range(6):
            month_start = (today.replace(day=1) - timedelta(days=30*i)).replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            count = SalesTransaction.objects.filter(sale_date__gte=month_start, sale_date__lte=month_end).count()
            months.append({'month': month_start.strftime('%b'), 'count': count})
        ctx['monthly_sales'] = list(reversed(months))
        return ctx


# Saved Searches
@login_required
def save_search(request):
    if request.method == 'POST':
        data = request.POST
        SavedSearch.objects.create(
            user=request.user,
            email=request.user.email,
            make=data.get('make',''),
            model=data.get('model',''),
            body_type=data.get('body_type',''),
            fuel_type=data.get('fuel_type',''),
            transmission=data.get('transmission',''),
        )
        messages.success(request, 'Search saved successfully.')
    return redirect(request.META.get('HTTP_REFERER','cars:advanced_search'))

class MySavedSearchesView(LoginRequiredMixin, ListView):
    model = SavedSearch
    template_name = 'cars/my_saved_searches.html'
    context_object_name = 'searches'
    def get_queryset(self):
        return SavedSearch.objects.filter(user=self.request.user).order_by('-created_at')

@login_required
def delete_saved_search(request, pk):
    search = get_object_or_404(SavedSearch, pk=pk, user=request.user)
    search.delete()
    messages.success(request, 'Saved search deleted.')
    return redirect('cars:my_saved_searches')


# Trade-in Valuation
class TradeInValuationView(CreateView):
    model = ListingRequest
    template_name = 'cars/trade_in_valuation.html'
    fields = ['owner_name', 'owner_email', 'owner_phone', 'make', 'model', 'year', 'mileage', 'description']
    success_url = '/trade-in/thank-you/'

    def form_valid(self, form):
        obj = form.save(commit=False)
        name = (self.request.POST.get('first_name', '') + ' ' + self.request.POST.get('last_name', '')).strip()
        if name and not obj.owner_name:
            obj.owner_name = name
        if not obj.owner_email:
            obj.owner_email = self.request.POST.get('email', '') or (self.request.user.email if self.request.user.is_authenticated else '')
        if not obj.owner_phone:
            obj.owner_phone = self.request.POST.get('phone', '')
        messages.success(self.request, 'Trade-in valuation request submitted.')
        obj.save()
        return redirect(self.success_url)

def trade_in_thank_you(request):
    return render(request, 'cars/trade_in_thank_you.html')


# Health Check
from django.http import JsonResponse
def health_check(request):
    return JsonResponse({'status': 'ok'})


# Audit Log
class AuditLogView(StaffRequiredMixin, TemplateView):
    template_name = 'cars/audit_log.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        try:
            if HistoricalCar is not None:
                ctx['car_history'] = HistoricalCar.objects.all().order_by('-history_date')[:50]
            else:
                ctx['car_history'] = []
            if HistoricalHireBooking is not None:
                ctx['hire_history'] = HistoricalHireBooking.objects.all().order_by('-history_date')[:50]
            else:
                ctx['hire_history'] = []
        except Exception:
            ctx.setdefault('car_history', [])
            ctx.setdefault('hire_history', [])
        return ctx
