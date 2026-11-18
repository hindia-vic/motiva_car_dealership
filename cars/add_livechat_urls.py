with open('urls.py') as f:
    c = f.read()
if 'livechat' not in c:
    old = "    path('chatbot/transcripts/<int:pk>/', views.ChatSessionDetailView.as_view(), name='chatbot_session_detail'),\n"
    new = old + "    path('livechat/', views.LiveChatInboxView.as_view(), name='livechat_inbox'),\n    path('livechat/<int:pk>/', views.LiveChatSessionDetailView.as_view(), name='livechat_session_detail'),\n    path('livechat/<int:pk>/claim/', views.livechat_claim, name='livechat_claim'),\n    path('livechat/<int:pk>/reply/', views.livechat_reply, name='livechat_reply'),\n    path('livechat/<int:pk>/close/', views.livechat_close, name='livechat_close'),\n"
    c2 = c.replace(old, new)
    with open('urls.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('exists')
