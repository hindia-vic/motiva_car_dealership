from django.shortcuts import render, get_object_or_404, redirect
import random
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView
from django.db.models import Q, Count, Sum, Avg
from django.urls import reverse, reverse_lazy
from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from .models import (
    Car, CarImage, Customer, SalesTransaction, ServiceRecord, Inquiry, Order,
    Appointment, ContactMessage, NewsletterSubscription, Testimonial, ContactInfo,
    SavedSearch, Post,
)
from .forms import (
    InquiryForm, OrderForm, AppointmentForm, ContactForm, NewsletterForm,
    TestimonialForm, CarForm, CustomerForm, SalesTransactionForm, ContactInfoForm,
    SavedSearchForm,
)
from .emails import (
    send_inquiry_notification, send_order_notification,
    send_appointment_notification, send_appointment_status_email,
    send_contact_notification, send_testimonial_notification,
    send_saved_search_alert_email,
)
from .exports import stream_csv, stream_pdf


# ==================== CUSTOMER FACING VIEWS ====================

class HomeView(View):
    """Homepage with featured cars and customer testimonials"""
    def get(self, request):
        featured_cars = Car.objects.filter(status='available')[:6]
        total_cars = Car.objects.filter(status='available').count()
        context = {
            'featured_cars': featured_cars,
            'total_cars': total_cars,
            'testimonials': Testimonial.objects.filter(is_visible=True),
            'latest_posts': Post.objects.filter(is_published=True)[:3],
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
        queryset = Car.objects.filter(status='available').prefetch_related('images')
        
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
        context['makes'] = Car.objects.filter(status='available').values_list('make', flat=True).distinct()
        context['years'] = sorted(Car.objects.filter(status='available').values_list('year', flat=True).distinct(), reverse=True)
        context['body_types'] = Car.objects.filter(status='available').values_list('body_type', flat=True).distinct()
        context['fuel_types'] = Car.objects.filter(status='available').values_list('fuel_type', flat=True).distinct()
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
            Car.objects.filter(pk__in=car_ids, status='available').prefetch_related('images')
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
        context['is_favorited'] = (
            self.request.user.is_authenticated
            and self.object.favorited_by.filter(user=self.request.user).exists()
        )
        return context


class AboutView(TemplateView):
    """Customer-facing about page with dealership vision and mission"""
    template_name = 'cars/about.html'


class FinancingView(TemplateView):
    """Public financing options page with payment calculator link"""
    template_name = 'cars/financing.html'


class FAQView(TemplateView):
    """Public frequently asked questions page"""
    template_name = 'cars/faq.html'


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
        messages.success(self.request, 'Your inquiry has been submitted! We will contact you soon.')
        response = super().form_valid(form)
        send_inquiry_notification(self.object, self.request)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        car_id = self.kwargs.get('car_id')
        context['car'] = get_object_or_404(Car, id=car_id)
        return context


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
        messages.success(self.request, 'Your order has been submitted! Our team will review it shortly.')
        response = super().form_valid(form)
        send_order_notification(self.object, self.request)
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
    """Thank you page after order submission"""
    return render(request, 'cars/order_thank_you.html')


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
        return context


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


class ContactView(View):
    """Public contact page: form + message saving + staff email"""
    def get(self, request):
        form = ContactForm()
        return render(request, 'cars/contact.html', {
            'form': form,
            'contact_info': ContactInfo.get_solo(),
        })

    def post(self, request):
        form = ContactForm(request.POST)
        if form.is_valid():
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

    def post(self, request):
        if not request.user.is_authenticated:
            messages.info(request, 'Please sign in to leave a review.')
            return redirect('accounts:login')

        form = TestimonialForm(request.POST)
        if form.is_valid():
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
        return {
            'testimonials': Testimonial.objects.filter(is_visible=True),
            'form': form,
        }


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
        
        context = {
            'total_cars': Car.objects.count(),
            'available_cars': Car.objects.filter(status='available').count(),
            'sold_cars': Car.objects.filter(status='sold').count(),
            'total_customers': Customer.objects.filter(is_active=True).count(),
            'pending_inquiries': Inquiry.objects.filter(status='new').count(),
            'pending_orders': Order.objects.filter(status='pending').count(),
            'pending_appointments': Appointment.objects.filter(status='pending').count(),
            'recent_inquiries': Inquiry.objects.all()[:5],
            'recent_orders': Order.objects.all()[:5],
            'recent_appointments': Appointment.objects.all()[:5],
            'total_sales_revenue': sum(s.sale_price for s in SalesTransaction.objects.filter(status='completed')),
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
    """Staff view: Display list of inquiries"""
    model = Inquiry
    template_name = 'cars/inquiries_list.html'
    context_object_name = 'inquiries'
    paginate_by = 20
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Inquiry.objects.all()
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
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = Inquiry.objects.values_list('status', flat=True).distinct()
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
        queryset = Order.objects.all()
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
        return queryset.order_by('-order_date')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = Order.objects.values_list('status', flat=True).distinct()
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


class CarRecordMixin(View):
    """Shared image upload handling for the staff Add/Edit Car forms"""
    action_verb = 'saved'

    def form_valid(self, form):
        files = self.request.FILES.getlist('images')
        if files and not all(self._is_valid_image(f) for f in files if f.size > 0):
            form.add_error('images', 'One or more uploaded files are not valid images.')
            return self.form_invalid(form)
        response = super().form_valid(form)
        self._save_images(files)
        messages.success(self.request, f'{self.object} {self.action_verb} successfully.')
        return response

    @staticmethod
    def _is_valid_image(uploaded_file):
        try:
            forms.ImageField().clean(uploaded_file)
            return True
        except ValidationError:
            return False

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
        inquiry.status = status
        inquiry.save(update_fields=['status', 'updated_at'])
        messages.success(request, f'Inquiry from {inquiry.customer_name} marked as {inquiry.get_status_display()}.')
    else:
        messages.error(request, 'Invalid status selected.')

    return redirect(_safe_next(request) or 'cars:inquiries_list')


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
        order.status = status
        order.save(update_fields=['status'])
        messages.success(request, f'Order #{order.id} marked as {order.get_status_display()}.')
    else:
        messages.error(request, 'Invalid status selected.')

    return redirect(_safe_next(request) or 'cars:orders_list')


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
         'VIN', 'Sale Price', 'Trade-In', 'Total Amount', 'Payment Method',
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
        ['Order ID', 'Customer Name', 'Email', 'Phone', 'Vehicle', 'Price',
         'Trade-In', 'Down Payment', 'Financing', 'Status', 'Order Date'],
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
    return stream_pdf(
        'sales-report.pdf',
        f'Sales Report - {timezone.now().strftime("%Y-%m-%d")}',
        ['Invoice', 'Sale Date', 'Customer', 'Email', 'Vehicle', 'VIN',
         'Sale Price', 'Total Amount', 'Payment Method', 'Status', 'Salesperson'],
        rows,
    )


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
