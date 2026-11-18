with open('urls.py') as f:
    c = f.read()
if 'audit_log' not in c:
    c = c.rstrip()
    if c.endswith(']'):
        c = c[:-1] + "    path('audit-log/', views.AuditLogView.as_view(), name='audit_log'),\n]\n"
        with open('urls.py', 'w') as f:
            f.write(c)
        print('done')
    else:
        print('bad')
else:
    print('exists')
