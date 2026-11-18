with open('urls.py') as f:
    c = f.read()
if 'advanced_search' not in c:
    old = "    path('cars/', views.CarListView.as_view(), name='browse_cars'),\n"
    new = old + "    path('search/advanced/', views.AdvancedSearchView.as_view(), name='advanced_search'),\n"
    c2 = c.replace(old, new)
    with open('urls.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('exists')
