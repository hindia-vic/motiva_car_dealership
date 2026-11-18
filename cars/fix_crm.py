with open('models.py') as f:
    c = f.read()
old = "assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_inquiries')"
new = "assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='crm_assigned_inquiries')"
c2 = c.replace(old, new)
with open('models.py','w') as f:
    f.write(c2)
print('done')
