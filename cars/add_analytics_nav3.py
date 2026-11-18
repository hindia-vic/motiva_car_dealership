with open('templates/base.html') as f:
    c = f.read()
if 'analytics_dashboard' not in c:
    old = "                                <li><a class=\"dropdown-item {% if request.resolver_match.url_name == 'dashboard' %}active{% endif %}\" href=\"{% url 'cars:dashboard' %}\"><i class=\"bi bi-speedometer2\"></i> Dashboard</a></li>\n"
    if old in c:
        new = old + "                                <li><a class=\"dropdown-item {% if request.resolver_match.url_name == 'analytics_dashboard' %}active{% endif %}\" href=\"{% url 'cars:analytics_dashboard' %}\"><i class=\"bi bi-graph-up\"></i> Analytics</a></li>\n"
        with open('templates/base.html', 'w') as f2:
            f2.write(c.replace(old, new))
        print('done')
    else:
        print('no')
else:
    print('skip')
