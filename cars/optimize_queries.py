with open('views.py') as f:
    c = f.read()
old = "class CarListView(ListView):\n    model = Car\n    template_name = 'cars/car_list.html'\n    context_object_name = 'cars'\n    paginate_by = 12\n\n    def get_queryset(self):\n        queryset = Car.objects.filter(status='available').order_by('-created_at')"
new = "class CarListView(ListView):\n    model = Car\n    template_name = 'cars/car_list.html'\n    context_object_name = 'cars'\n    paginate_by = 12\n\n    def get_queryset(self):\n        queryset = Car.objects.filter(status='available').select_related('branch').prefetch_related('images').order_by('-created_at')"
if old in c:
    c2 = c.replace(old, new)
    with open('views.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('skip')
