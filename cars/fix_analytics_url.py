with open('urls.py') as f:
    c = f.read()
if 'analytics_dashboard' not in c:
    c = c.rstrip()
    if c.endswith(']'):
        c = c[:-1] + "    path('analytics/', views.AnalyticsDashboardView.as_view(), name='analytics_dashboard'),\n]\n"
        with open('urls.py', 'w') as f:
            f.write(c)
        print('done')
    else:
        print('bad')
else:
    print('exists')
