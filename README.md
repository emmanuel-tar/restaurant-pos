# Restaurant POS System

A Django-based restaurant point-of-sale and operations platform built for cafés and small to medium restaurants. The system provides order management, table/session handling, kitchen and receipt printing, reporting, inventory tracking, expense management, and staff administration in a single application.

## Features

- Restaurant POS workflow for order creation and billing
- Table and token-based session handling
- Menu categories, deals, and item management
- Kitchen/Voucher and printing support for POS hardware
- Sales, ledger, and financial reporting modules
- Expense and bank account tracking
- Staff and role management
- Purchase order and raw material inventory tracking
- Customer data and order history support
- Admin dashboard powered by Django
- SQLite default database for quick local deployment

## Tech Stack

- Python 3
- Django 4.2
- SQLite
- Bootstrap / crispy forms for UI
- ReportLab, xhtml2pdf, and QR-related support for reports and documents
- Python ESC/POS integration for thermal printers

## Project Structure

```text
restaurant-pos/
├── restuarent_app/
│   ├── manage.py
│   ├── requirements.txt
│   ├── db.sqlite3
│   ├── start_server.bat
│   ├── core/
│   │   ├── admin.py
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── forms.py
│   │   ├── reports.py
│   │   ├── kitchen.py
│   │   ├── ledger.py
│   │   ├── expenses.py
│   │   ├── staff_management.py
│   │   ├── escpos_printers.py
│   │   ├── escpos_utils.py
│   │   ├── printing.py
│   │   ├── templates/
│   │   ├── static/
│   │   └── migrations/
│   └── restuarent_app/
│       ├── settings.py
│       ├── urls.py
│       ├── wsgi.py
│       └── asgi.py
├── .gitignore
├── setup.py
├── setup.ps1
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.10 or later
- pip
- Virtual environment support

### Clone the repository

```bash
git clone https://github.com/emmanuel-tar/restaurant-pos.git
cd restaurant-pos/restuarent_app
```

### Create a virtual environment

#### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
```

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Apply database migrations

```bash
python manage.py migrate
```

### Create an admin user

```bash
python manage.py createsuperuser
```

### Run the application

```bash
python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/
```

For Windows users, a quick launcher is also included:

```powershell
start_server.bat
```

## Configuration

The project uses Django settings in `restuarent_app/restuarent_app/settings.py`.

Key settings you may want to customize:

- `RESTAURANT_NAME`
- `TIME_ZONE`
- `LOGO_PATH`
- `STATIC_URL` / media configuration
- database settings
- login/dashboard redirect paths

## Database

The repository ships with a local SQLite database by default, which makes local setup and testing simple. For production, you may want to move to PostgreSQL or another managed database backend.

## Customization Ideas

This project is a good base for a restaurant management system and can be extended with:

- branded dashboard themes
- customer loyalty or reward features
- online ordering and delivery integration
- WhatsApp or SMS notifications
- payment gateway integrations
- advanced reports and export tools
- employee attendance and payroll modules

## Useful Commands

```bash
# Run migrations
python manage.py migrate

# Create a new migration after model changes
python manage.py makemigrations

# Run Django shell
python manage.py shell

# Collect static files
python manage.py collectstatic
```

## License

This project does not currently declare a license file in the repository. If you intend to distribute or commercialize it, consider adding a license such as MIT or Apache 2.0.

## Notes

This app appears to be designed for a local restaurant environment with physical POS operations and printer support. It is highly customizable and suitable as a foundation for a branded restaurant or café management system.

## Contributing

Contributions are welcome. To contribute:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Open a pull request

## Support

If you are customizing this app for your own restaurant, you may need to update:

- branding and naming
- menu data
- printer configuration
- reports and business logic
- staff roles and permissions

