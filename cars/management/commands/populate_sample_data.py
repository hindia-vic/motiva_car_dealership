from django.core.management.base import BaseCommand
from django.utils import timezone
from cars.models import Car, Inventory, Customer, SalesTransaction, ServiceRecord
from decimal import Decimal


class Command(BaseCommand):
    help = 'Populate the database with sample car dealership data'

    def handle(self, *args, **options):
        # Sample car data
        cars_data = [
            {
                'make': 'Toyota',
                'model': 'Camry',
                'year': 2023,
                'vin': '4T1F11AK5PU521212',
                'color': 'Silver',
                'body_type': 'sedan',
                'transmission': 'automatic',
                'fuel_type': 'gasoline',
                'mileage': 5000,
                'engine_size': '2.5L',
                'horsepower': 203,
                'purchase_price': Decimal('25000.00'),
                'asking_price': Decimal('28500.00'),
                'condition': 'used',
                'status': 'available',
                'description': 'Well-maintained Toyota Camry with full service history.',
                'air_conditioning': True,
                'power_steering': True,
                'power_windows': True,
                'power_locks': True,
                'cruise_control': True,
                'backup_camera': True,
                'bluetooth': True,
                'leather_seats': False,
            },
            {
                'make': 'Honda',
                'model': 'Civic',
                'year': 2022,
                'vin': '2HGFC2F55MH521234',
                'color': 'Blue',
                'body_type': 'sedan',
                'transmission': 'automatic',
                'fuel_type': 'gasoline',
                'mileage': 12000,
                'engine_size': '1.5L',
                'horsepower': 174,
                'purchase_price': Decimal('18000.00'),
                'asking_price': Decimal('21000.00'),
                'condition': 'used',
                'status': 'available',
                'description': 'Reliable Honda Civic with excellent fuel economy.',
                'air_conditioning': True,
                'power_steering': True,
                'power_windows': True,
                'power_locks': True,
                'cruise_control': False,
                'backup_camera': True,
                'bluetooth': True,
                'leather_seats': False,
            },
            {
                'make': 'Ford',
                'model': 'F-150',
                'year': 2023,
                'vin': '1FTFW1ET5DFC15178',
                'color': 'Black',
                'body_type': 'truck',
                'transmission': 'automatic',
                'fuel_type': 'gasoline',
                'mileage': 8000,
                'engine_size': '3.5L',
                'horsepower': 400,
                'purchase_price': Decimal('35000.00'),
                'asking_price': Decimal('42000.00'),
                'condition': 'used',
                'status': 'available',
                'description': 'Powerful Ford F-150 pickup truck with towing package.',
                'air_conditioning': True,
                'power_steering': True,
                'power_windows': True,
                'power_locks': True,
                'cruise_control': True,
                'backup_camera': True,
                'bluetooth': True,
                'navigation_system': True,
                'leather_seats': True,
            },
            {
                'make': 'Chevrolet',
                'model': 'Equinox',
                'year': 2021,
                'vin': '2G1FB1E30M1205849',
                'color': 'White',
                'body_type': 'suv',
                'transmission': 'automatic',
                'fuel_type': 'gasoline',
                'mileage': 22000,
                'engine_size': '2.0L',
                'horsepower': 170,
                'purchase_price': Decimal('20000.00'),
                'asking_price': Decimal('24500.00'),
                'condition': 'used',
                'status': 'available',
                'description': 'Spacious Chevrolet Equinox SUV perfect for families.',
                'air_conditioning': True,
                'power_steering': True,
                'power_windows': True,
                'power_locks': True,
                'cruise_control': True,
                'backup_camera': True,
                'bluetooth': True,
                'all_wheel_drive': True,
            },
        ]

        # Create cars
        for car_data in cars_data:
            car, created = Car.objects.get_or_create(
                vin=car_data['vin'],
                defaults=car_data
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created car: {car.year} {car.make} {car.model}')
                )
                # Create inventory for each car
                Inventory.objects.get_or_create(
                    car=car,
                    defaults={'quantity_in_stock': 1, 'location': 'Main Lot'}
                )

        # Sample customer data
        customers_data = [
            {
                'first_name': 'John',
                'last_name': 'Smith',
                'email': 'john.smith@email.com',
                'phone_number': '555-0101',
                'gender': 'M',
                'address': '123 Main St',
                'city': 'Springfield',
                'state': 'IL',
                'zip_code': '62701',
                'credit_score': 750,
            },
            {
                'first_name': 'Sarah',
                'last_name': 'Johnson',
                'email': 'sarah.johnson@email.com',
                'phone_number': '555-0102',
                'gender': 'F',
                'address': '456 Oak Ave',
                'city': 'Chicago',
                'state': 'IL',
                'zip_code': '60601',
                'credit_score': 800,
            },
            {
                'first_name': 'Mike',
                'last_name': 'Williams',
                'email': 'mike.williams@email.com',
                'phone_number': '555-0103',
                'gender': 'M',
                'address': '789 Elm Rd',
                'city': 'New York',
                'state': 'NY',
                'zip_code': '10001',
                'credit_score': 700,
            },
        ]

        # Create customers
        for customer_data in customers_data:
            customer, created = Customer.objects.get_or_create(
                email=customer_data['email'],
                defaults=customer_data
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created customer: {customer.first_name} {customer.last_name}')
                )

        # Sample sales transactions
        cars_list = Car.objects.all()[:2]
        customers_list = Customer.objects.all()[:2]

        if cars_list and customers_list:
            sales_data = [
                {
                    'car': cars_list[0],
                    'customer': customers_list[0],
                    'salesperson': 'John Dealer',
                    'sale_date': timezone.now(),
                    'sale_price': cars_list[0].asking_price,
                    'trade_in_value': Decimal('3000.00'),
                    'down_payment': Decimal('5000.00'),
                    'total_amount': cars_list[0].asking_price - Decimal('3000.00'),
                    'payment_method': 'financing',
                    'financed_amount': cars_list[0].asking_price - Decimal('3000.00') - Decimal('5000.00'),
                    'interest_rate': Decimal('4.5'),
                    'loan_term_months': 60,
                    'invoice_number': 'INV-2024-001',
                },
                {
                    'car': cars_list[1],
                    'customer': customers_list[1],
                    'salesperson': 'Jane Dealer',
                    'sale_date': timezone.now(),
                    'sale_price': cars_list[1].asking_price,
                    'trade_in_value': Decimal('2500.00'),
                    'down_payment': Decimal('7000.00'),
                    'total_amount': cars_list[1].asking_price - Decimal('2500.00'),
                    'payment_method': 'cash',
                    'invoice_number': 'INV-2024-002',
                },
            ]

            for sale_data in sales_data:
                sale, created = SalesTransaction.objects.get_or_create(
                    invoice_number=sale_data['invoice_number'],
                    defaults=sale_data
                )
                if created:
                    self.stdout.write(
                        self.style.SUCCESS(f'Created sales transaction: {sale.invoice_number}')
                    )

        self.stdout.write(
            self.style.SUCCESS('Successfully populated database with sample data!')
        )
