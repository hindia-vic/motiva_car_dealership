with open('views.py') as f:
    c = f.read()
old = """# Trade-in Valuation
class TradeInValuationView(CreateView):
    model = ListingRequest
    template_name = 'cars/trade_in_valuation.html'
    fields = ['first_name', 'last_name', 'email', 'phone', 'car_make', 'car_model', 'car_year', 'car_mileage', 'car_condition', 'message']
    success_url = '/trade-in/thank-you/'
    def form_valid(self, form):
        messages.success(self.request, 'Trade-in valuation request submitted.')
        return super().form_valid(form)

def trade_in_thank_you(request):
    return render(request, 'cars/trade_in_thank_you.html')"""
new = """# Trade-in Valuation
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
    return render(request, 'cars/trade_in_thank_you.html')"""
if old in c:
    c2 = c.replace(old, new)
    with open('views.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('skip')
