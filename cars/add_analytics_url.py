with open('urls.py') as f:
    c = f.read()
if 'analytics_dashboard' not in c:
    old = "    path('dashboard/', views.StaffDashboardView.as_view(), name='dashboard'),\n"
    new = old + "    path('analytics/', views.AnalyticsDashboardView.as_view(), name='analytics_dashboard'),\n"
    c2 = c.replace(old, new)
    with open('urls.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('exists')
