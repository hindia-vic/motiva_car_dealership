# Car Dealership Django App

A comprehensive Django application for managing a car dealership business. This app handles inventory management, customer relationships, sales transactions, and service records.

## Features

### 1. **Car Inventory Management**
- Track vehicle details (make, model, year, VIN, color, body type, transmission, fuel type)
- Monitor vehicle condition (new, used, certified pre-owned)
- Track vehicle status (available, sold, reserved, in maintenance)
- Record technical specifications (engine size, horsepower, mileage)
- Manage pricing information (purchase price and asking price)
- Track vehicle features (air conditioning, power steering, backup camera, Bluetooth, leather seats, etc.)
- Maintain vehicle history with service records

### 2. **Customer Management**
- Store comprehensive customer information (personal details, contact information)
- Track customer demographics (gender, date of birth)
- Manage customer addresses and location data
- Monitor customer credit information (credit score)
- Track customer preferences (financing preferences)
- Record customer notes and purchase history
- Search and filter customers by various criteria

### 3. **Sales Transactions**
- Record complete sales information
- Track payment methods (cash, check, financing, lease)
- Calculate and manage financing details (loan amount, interest rate, term)
- Generate invoice numbers for each transaction
- Track trade-in values and down payments
- Calculate monthly loan payments automatically
- Monitor transaction status (pending, completed, cancelled)

### 4. **Service Records**
- Track vehicle maintenance and repairs
- Record service types (oil change, tire service, inspections, etc.)
- Maintain odometer readings for each service
- Track service costs
- Record technician information
- Build complete service history for each vehicle

### 5. **Inventory Tracking**
- Monitor stock levels for each vehicle
- Set and track reorder levels
- Track storage locations
- Identify low-stock vehicles

## Models

### Car
Main model for vehicle information:
- Basic info: make, model, year, VIN, color, body type
- Transmission & engine: transmission type, fuel type, engine size, horsepower
- Pricing: purchase price, asking price
- Condition & status: new/used/certified, available/sold/reserved/maintenance
- Features: air conditioning, power windows, leather seats, sunroof, etc.
- Timestamps: date added, last updated

### Inventory
Tracks stock information:
- Links to Car model (one-to-one relationship)
- Quantity in stock
- Reorder level
- Storage location
- Last counted timestamp

### Customer
Manages customer information:
- Personal data: name, email, phone, gender, date of birth
- Address information: full address details
- Financial info: credit score, financing preference
- Account info: registration date, active status, notes
- Related sales transactions

### SalesTransaction
Records vehicle sales:
- Links to Car and Customer
- Sale date and details
- Pricing information (sale price, trade-in, down payment, total amount)
- Payment method and status
- Financing details (financed amount, interest rate, loan term)
- Generates monthly payment calculations
- Invoice tracking

### ServiceRecord
Maintains maintenance history:
- Links to Car
- Service type and date
- Description and details
- Odometer reading
- Cost tracking
- Technician information

## Views and URLs

### Dashboard
- **URL**: `/`
- **View**: `dashboard`
- Displays dealership statistics and recent sales

### Cars Management
- **List Cars**: `/cars/` - Browse all available cars with filtering and search
- **Car Details**: `/cars/<id>/` - View detailed information about a specific car
- Filters: body type, make, year, price range, fuel type
- Search capability by make, model, or VIN

### Customer Management
- **List Customers**: `/customers/` - Browse all customers
- **Customer Details**: `/customers/<id>/` - View customer information and purchase history
- Filters: active status, state
- Search capability by name, email, or phone

### Sales Management
- **List Sales**: `/sales/` - View all sales transactions
- **Sales Details**: `/sales/<id>/` - View detailed sale information
- Filters: status, date range
- Search capability by invoice, customer, or VIN

## Admin Interface

A comprehensive Django admin interface is configured with:

### CarAdmin
- Display: year, make, model, VIN, condition, status, price, mileage
- Filters: status, condition, year, body type, fuel type
- Search: make, model, VIN, color
- Organized fieldsets for different information groups

### InventoryAdmin
- Display: car, quantity, reorder level, location, low stock indicator
- Filters: quantity levels
- Search: car details, location

### CustomerAdmin
- Display: name, email, phone, city, active status
- Filters: active status, registration date, state
- Search: name, email, phone
- Organized fieldsets for different information types

### SalesTransactionAdmin
- Display: invoice number, customer, car, sale date, price, status
- Filters: status, payment method, sale date
- Search: invoice number, customer, VIN

### ServiceRecordAdmin
- Display: car, service date, service type, cost, technician
- Filters: service type, service date
- Search: car details, technician, description

## Forms

All forms are configured with Bootstrap CSS classes for styling:
- `CarForm` - Create/edit car inventory
- `CustomerForm` - Create/edit customer information
- `SalesTransactionForm` - Create/edit sales records
- `ServiceRecordForm` - Create/edit service records
- `CarFilterForm` - Advanced car filtering

## Getting Started

### 1. Run Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 2. Create Superuser
```bash
python manage.py createsuperuser
```

### 3. Populate Sample Data (Optional)
```bash
python manage.py populate_sample_data
```

### 4. Start Development Server
```bash
python manage.py runserver
```

### 5. Access the Application
- Admin Interface: http://localhost:8000/admin/
- Dashboard: http://localhost:8000/
- Cars: http://localhost:8000/cars/
- Customers: http://localhost:8000/customers/
- Sales: http://localhost:8000/sales/

## Sample Data

The `populate_sample_data` management command provides:
- 4 sample vehicles (Toyota Camry, Honda Civic, Ford F-150, Chevrolet Equinox)
- 3 sample customers
- 2 sample sales transactions
- Inventory records for each vehicle

## Features Explained

### Vehicle Status Management
- **Available**: Ready for sale
- **Sold**: Vehicle has been sold
- **Reserved**: Vehicle is on hold for a customer
- **In Maintenance**: Vehicle is undergoing service

### Condition Types
- **New**: Brand new, never sold
- **Used**: Previously owned vehicle
- **Certified Pre-Owned**: Used vehicle that has been inspected and certified

### Financing Calculations
The SalesTransaction model includes a method `calculate_monthly_payment()` that computes loan payments using the standard amortization formula:

Monthly Payment = P × [r(1+r)^n] / [(1+r)^n - 1]

Where:
- P = Principal (financed amount)
- r = Monthly interest rate
- n = Number of months

### Search and Filter Capabilities
- **Cars**: Filter by body type, make, year, price range, fuel type; search by make, model, or VIN
- **Customers**: Filter by state, active status; search by name, email, or phone
- **Sales**: Filter by status and date range; search by invoice number, customer, or VIN

## API Endpoints (Views Available)

All views are class-based and include pagination:
- `CarListView` - Paginated list with 12 items per page
- `CarDetailView` - Detailed car information
- `CustomerListView` - Paginated list with 20 items per page
- `CustomerDetailView` - Customer details with purchase history
- `SalesListView` - Paginated list with 20 items per page
- `SalesDetailView` - Sale transaction details
- `dashboard` - Summary statistics

## Validation

Models include field validation:
- Validators for positive values (prices, mileage, horsepower)
- Year validation (must be 1900 or later)
- Unique VIN constraint
- Unique email constraint for customers
- Unique invoice number constraint for sales

## Best Practices

1. **Always record VIN accurately** - It's the unique identifier for vehicles
2. **Update vehicle status promptly** - Keep status current for accurate inventory
3. **Link service records to vehicles** - Maintain complete service history
4. **Use invoice numbers consistently** - Generate unique invoice numbers for each sale
5. **Track customer credit information** - Important for financing decisions

## Customization

To extend the app:
1. Add more fields to existing models
2. Create additional views for reports and analytics
3. Implement email notifications for low stock
4. Add document/image upload for vehicle photos
5. Implement financing calculations and payment tracking
6. Create customer portal for checking order status
7. Add vehicle comparison tools
8. Implement automated email reminders for service appointments

## Testing

Run migrations first before creating any data:
```bash
python manage.py migrate
```

Access the admin panel to manually create records or use the provided sample data command.

## Future Enhancements

- Add vehicle images and photo gallery
- Implement payment processing integration
- Add API endpoints for mobile app integration
- Create reporting and analytics dashboard
- Implement automated warranty tracking
- Add customer review system
- Create maintenance schedule notifications
- Add competitor price tracking
