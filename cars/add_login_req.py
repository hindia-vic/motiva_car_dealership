with open('views.py') as f:
    c = f.read()
if 'from django.contrib.auth.decorators import login_required' not in c:
    c = 'from django.contrib.auth.decorators import login_required\n' + c
    with open('views.py', 'w') as f2:
        f2.write(c)
    print('done')
else:
    print('has')
