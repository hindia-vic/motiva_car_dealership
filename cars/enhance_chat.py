with open('models.py') as f:
    c = f.read()

old = """class ChatSession(models.Model):
    \"\"\"A visitor's chatbot conversation (one row per browser, keyed by a token
    stored client-side so it works without an account).\"\"\"
    session_key = models.CharField(max_length=40, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_sessions',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_escalated = models.BooleanField(default=False)
    contact_message = models.ForeignKey(
        ContactMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_sessions',
        help_text=\"The contact message created when the visitor asked for a human.\",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_activity_at']

    def __str__(self):
        who = self.user.get_username() if self.user_id else self.session_key[:8]
        return f'Chat session {who} ({self.message_count} messages)'

    @property
    def message_count(self):
        return self.messages.count()"""

new = """class ChatSession(models.Model):
    \"\"\"A visitor's chatbot conversation (one row per browser, keyed by a token
    stored client-side so it works without an account).\"\"\"
    STATUS_CHOICES = [
        ('bot', 'Bot Only'),
        ('waiting', 'Waiting for Agent'),
        ('active', 'Live Chat Active'),
        ('closed', 'Closed'),
    ]
    session_key = models.CharField(max_length=40, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_sessions',
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_live_chats',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='bot')
    is_escalated = models.BooleanField(default=False)
    contact_message = models.ForeignKey(
        ContactMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_sessions',
        help_text=\"The contact message created when the visitor asked for a human.\",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_activity_at']

    def __str__(self):
        who = self.user.get_username() if self.user_id else self.session_key[:8]
        return f'Chat session {who} ({self.message_count} messages)'

    @property
    def message_count(self):
        return self.messages.count()

    @property
    def unread_for_staff(self):
        return self.messages.filter(sender='user', is_read=False).count()

    @property
    def unread_for_user(self):
        return self.messages.filter(sender__in=['bot', 'staff'], is_read=False).count()"""

if old in c:
    c2 = c.replace(old, new)
    with open('models.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('skip')
