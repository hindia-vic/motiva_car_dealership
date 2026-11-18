with open('urls.py') as f:
    c = f.read()
if 'health' not in c:
    c = c.rstrip()
    if c.endswith(']'):
        c = c[:-1] + "    path('health/', views.health_check, name='health_check'),\n]\n"
        with open('urls.py', 'w') as f:
            f.write(c)
        print('done')
    else:
        print('bad')
else:
    print('exists')
