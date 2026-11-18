with open('urls.py') as f:
    c = f.read()
if 'saved-search' not in c:
    old = "    path('search/advanced/', views.AdvancedSearchView.as_view(), name='advanced_search'),\n"
    new = old + "    path('search/save/', views.save_search, name='save_search'),\n    path('my-saved-searches/', views.MySavedSearchesView.as_view(), name='my_saved_searches'),\n    path('saved-search/<int:pk>/delete/', views.delete_saved_search, name='delete_saved_search'),\n"
    c2 = c.replace(old, new)
    with open('urls.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('exists')
