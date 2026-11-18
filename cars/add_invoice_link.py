with open('templates/cars/sales_list.html') as f:
    c = f.read()
if 'sale_invoice_pdf' not in c:
    old = "                                    <a href=\"{% url 'cars:sale_detail' sale.pk %}\" class=\"btn btn-sm btn-outline-primary\">"
    new = "                                    <a href=\"{% url 'cars:sale_invoice_pdf' sale.pk %}\" class=\"btn btn-sm btn-outline-secondary\" target=\"_blank\"><i class=\"bi bi-file-pdf\"></i> PDF</a>\n                                    <a href=\"{% url 'cars:sale_detail' sale.pk %}\" class=\"btn btn-sm btn-outline-primary\">"
    if old in c:
        with open('templates/cars/sales_list.html', 'w') as f2:
            f2.write(c.replace(old, new))
        print('done')
    else:
        print('no')
else:
    print('exists')
