with open('models.py') as f:
    c = f.read()
old = "assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='crm_assigned_inquiries')"
idx = c.find(old)
if idx >= 0:
    idx2 = c.find(old, idx+1)
    if idx2 >= 0:
        new = "assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='crm_assigned_contact_messages')"
        c2 = c[:idx2] + new + c[idx2+len(old):]
        with open('models.py', 'w') as f2:
            f2.write(c2)
        print('done')
    else:
        print('only1')
else:
    print('no')
