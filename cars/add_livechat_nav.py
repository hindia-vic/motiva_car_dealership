with open('templates/base.html') as f:
    c = f.read()
if 'livechat_inbox' not in c:
    old = "                                <li><a class=\"dropdown-item {% if request.resolver_match.url_name == 'chatbot_sessions' or request.resolver_match.url_name == 'chatbot_session_detail' %}active{% endif %}\" href=\"{% url 'cars:chatbot_sessions' %}\"><i class=\"bi bi-chat-square-text\"></i> Chat Transcripts</a></li>\n"
    new = old + "                                <li><a class=\"dropdown-item {% if request.resolver_match.url_name == 'livechat_inbox' or request.resolver_match.url_name == 'livechat_session_detail' %}active{% endif %}\" href=\"{% url 'cars:livechat_inbox' %}\"><i class=\"bi bi-chat-dots\"></i> Live Chat Inbox</a></li>\n"
    c2 = c.replace(old, new)
    with open('templates/base.html', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('exists')
