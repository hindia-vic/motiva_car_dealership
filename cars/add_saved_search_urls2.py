with open('urls.py') as f:
    c = f.read()
if 'save_search' not in c:
    # Append
    c = c.rstrip()
    if c.endswith(']'):
        c = c[:-1] + "    path('search/save/', views.save_search, name='save_search'),\n    path('my-saved-searches/', views.MySavedSearchesView.as_view(), name='my_saved_searches'),\n    path('saved-search/<int:pk>/delete/', views.delete_saved_search, name='delete_saved_search'),\n]\n"
        with open('urls.py', 'w') as f:
            f.write(c)
        print('done')
    else:
        print('bad')
else:
    print('exists')
