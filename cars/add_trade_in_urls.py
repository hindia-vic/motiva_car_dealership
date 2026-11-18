with open('urls.py') as f:
    c = f.read()
if 'trade_in' not in c:
    c = c.rstrip()
    if c.endswith(']'):
        c = c[:-1] + "    path('trade-in/', views.TradeInValuationView.as_view(), name='trade_in'),\n    path('trade-in/thank-you/', views.trade_in_thank_you, name='trade_in_thank_you'),\n]\n"
        with open('urls.py', 'w') as f:
            f.write(c)
        print('done')
    else:
        print('bad')
else:
    print('exists')
