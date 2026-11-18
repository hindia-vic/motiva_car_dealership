with open('views.py') as f:
    content = f.read()
old = """class ReviewListCreateView(View):
    \"\"\"List approved reviews and allow logged-in customers to submit one.\"\"\"
    template_name = 'cars/reviews.html'

    def get(self, request):
        reviews = Testimonial.objects.filter(is_visible=True).select_related('user')
        form = ReviewForm()
        return render(request, self.template_name, {'reviews': reviews, 'form': form})

    def post(self, request):
        if not request.user.is_authenticated:
            messages.error(request, 'Please sign in to leave a review.')
            return redirect('accounts:login')

        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.user = request.user
            name = (request.user.get_full_name() or '').strip() or request.user.username
            review.customer_name = name
            review.is_visible = False
            review.save()
            messages.success(
                request,
                'Thanks for your review! It will appear once staff have approved it.',
            )
            return redirect('cars:reviews')
        reviews = Testimonial.objects.filter(is_visible=True).select_related('user')
        return render(request, self.template_name, {'reviews': reviews, 'form': form})"""
new = """class ReviewListCreateView(View):
    \"\"\"List approved reviews and allow logged-in customers to submit one.\"\"\"
    template_name = 'cars/reviews.html'

    def get(self, request):
        reviews = Testimonial.objects.filter(is_visible=True).select_related('user').prefetch_related('photos')
        form = ReviewForm()
        return render(request, self.template_name, {'reviews': reviews, 'form': form})

    def post(self, request):
        if not request.user.is_authenticated:
            messages.error(request, 'Please sign in to leave a review.')
            return redirect('accounts:login')

        form = ReviewForm(request.POST, request.FILES)
        if form.is_valid():
            review = form.save(commit=False)
            review.user = request.user
            name = (request.user.get_full_name() or '').strip() or request.user.username
            review.customer_name = name
            review.is_visible = False
            review.save()
            from .models import TestimonialPhoto
            for uploaded in request.FILES.getlist('photos'):
                if uploaded and getattr(uploaded, 'size', 0):
                    try:
                        TestimonialPhoto.objects.create(testimonial=review, photo=uploaded)
                    except Exception:
                        logger.exception('Failed to save review photo')
            messages.success(
                request,
                'Thanks for your review! It will appear once staff have approved it.',
            )
            return redirect('cars:reviews')
        reviews = Testimonial.objects.filter(is_visible=True).select_related('user').prefetch_related('photos')
        return render(request, self.template_name, {'reviews': reviews, 'form': form})"""
if old in content:
    content = content.replace(old, new)
    with open('views.py', 'w') as f:
        f.write(content)
    print('done')
else:
    print('not found')
