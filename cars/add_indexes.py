with open('models.py') as f:
    c = f.read()
c2 = c.replace("    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')", 
               "    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available', db_index=True)")
c2 = c2.replace("    make = models.CharField(max_length=100)", "    make = models.CharField(max_length=100, db_index=True)")
c2 = c2.replace("    asking_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])", 
                "    asking_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))], db_index=True)")
c2 = c2.replace("    year = models.IntegerField(validators=[MinValueValidator(1900), MaxValueValidator(2100)])", 
                "    year = models.IntegerField(validators=[MinValueValidator(1900), MaxValueValidator(2100)], db_index=True)")
if c2 != c:
    with open('models.py', 'w') as f:
        f.write(c2)
    print('done')
else:
    print('skip')
