with open('templates/base.html') as f:
    c = f.read()
# Add saved searches
if 'my_saved_searches' not in c:
    old = "                                <li><a class=\"dropdown-item {% if request.resolver_match.url_name == 'my_favorites' %}active{% endif %}\" href=\"{% url 'accounts:my_favorites' %}\"><i class=\"bi bi-heart\"></i> My Wishlist</a></li>\n"
    if old in c:
        new = old + "                                <li><a class=\"dropdown-item {% if request.resolver_match.url_name == 'my_saved_searches' %}active{% endif %}\" href=\"{% url 'cars:my_saved_searches' %}\"><i class=\"bi bi-bookmark\"></i> Saved Searches</a></li>\n"
        c = c.replace(old, new)
        with open('templates/base.html', 'w') as f2:
            f2.write(c)
        print('done')
    else:
        print('skip')
else:
    print('has')
