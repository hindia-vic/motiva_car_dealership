with open('views.py') as f:
    c = f.read()
# Add decorator if missing
if 'def staff_required' not in c:
    add = "from functools import wraps\nfrom django.contrib.admin.views.decorators import staff_member_required\n\ndef staff_required(view_func):\n    decorated = staff_member_required(view_func)\n    @wraps(decorated)\n    def _wrapped_view(request, *args, **kwargs):\n        return decorated(request, *args, **kwargs)\n    return _wrapped_view\n\n"
    # Prepend after imports
    c2 = add + c
    with open('views.py', 'w') as f2:
        f2.write(c2)
    print('done')
else:
    print('exists')
