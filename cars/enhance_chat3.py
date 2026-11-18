with open('models.py') as f:
    c = f.read()
c = c.replace("        ('user', 'Visitor'),\n        ('bot', 'Chatbot'),\n    ]", 
              "        ('user', 'Visitor'),\n        ('bot', 'Chatbot'),\n        ('staff', 'Staff'),\n    ]")
old = "    sender = models.CharField(max_length=8, choices=SENDER_CHOICES)\n    text = models.TextField()\n    intent = models.CharField(max_length=50, blank=True)\n    created_at = models.DateTimeField(auto_now_add=True)"
new = "    sender = models.CharField(max_length=8, choices=SENDER_CHOICES)\n    sender_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages_sent')\n    text = models.TextField()\n    intent = models.CharField(max_length=50, blank=True)\n    is_read = models.BooleanField(default=False)\n    created_at = models.DateTimeField(auto_now_add=True)"
if old in c:
    c2 = c.replace(old, new)
    with open('models.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('skip')
