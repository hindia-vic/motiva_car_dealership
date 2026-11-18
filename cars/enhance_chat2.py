with open('models.py') as f:
    c = f.read()
old = """class ChatMessage(models.Model):
    \"\"\"A single message within a chatbot conversation\"\"\"
    SENDER_CHOICES = [
        ('user', 'Visitor'),
        ('bot', 'Chatbot'),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.CharField(max_length=8, choices=SENDER_CHOICES)
    text = models.TextField()
    intent = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_sender_display()}: {self.text[:40]}' """
new = """class ChatMessage(models.Model):
    \"\"\"A single message within a chatbot conversation\"\"\"
    SENDER_CHOICES = [
        ('user', 'Visitor'),
        ('bot', 'Chatbot'),
        ('staff', 'Staff'),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.CharField(max_length=8, choices=SENDER_CHOICES)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_messages_sent',
    )
    text = models.TextField()
    intent = models.CharField(max_length=50, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_sender_display()}: {self.text[:40]}' """
if old in c:
    c2 = c.replace(old, new)
    with open('models.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('skip')
