with open('templates/base.html') as f:
    c = f.read()
if 'audit_log' not in c:
    old = "                                <li><a class=\"dropdown-item {% if request.resolver_match.url_name == 'livechat_inbox' or request.resolver_match.url_name == 'livechat_session_detail' %}active{% endif %}\" href=\"{% url 'cars:livechat_inbox' %}\"><i class=\"bi bi-chat-dots\"></i> Live Chat Inbox</a></li>\n"
    if old in c:
        new = old + "                                <li><a class=\"dropdown-item {% if request.resolver_match.url_name == 'audit_log' %}active{% endif %}\" href=\"{% url 'cars:audit_log' %}\"><i class=\"bi bi-clock-history\"></i> Audit Log</a></li>\n"
        with open('templates/base.html', 'w') as f2:
            f2.write(c.replace(old, new))
        print('done')
    else:
        print('skip')
else:
    print('has')
