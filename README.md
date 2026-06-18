# 🌟 Volunteer Information Management System (VIMS)

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115.5-green.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
[![Live Demo](https://img.shields.io/badge/Live-Demo-brightgreen.svg)](https://vims-platform.onrender.com)

**Production-ready, scalable backend architecture for managing volunteer opportunities and application workflows**

Connect volunteers with meaningful community service opportunities through a secure, role-based platform. Built with FastAPI and PostgreSQL, VIMS provides a complete solution for organizations to manage the entire volunteer lifecycle from opportunity creation to application completion.


---

## ✨ Features

✅ **Comprehensive Volunteer Management**
- Complete volunteer profiles with skills, availability, and contact information
- Detailed application tracking with status workflows
- Role-based access control for volunteers, staff, and administrators

✅ **Opportunity Management System**
- Create, publish, and manage community service opportunities
- Set availability dates, locations, and capacity constraints
- Track application statuses and outcomes

✅ **Secure Authentication & Authorization**
- JWT-based authentication with access/refresh tokens
- Email verification system
- Password reset functionality
- Role-based permission system (volunteer, staff, admin, super_admin)

✅ **Production-Ready Architecture**
- Async database operations with SQLAlchemy 2.0
- Comprehensive error handling and validation
- Pagination and rate limiting
- Environment-aware configuration

✅ **Developer-Friendly**
- Clean, modular code structure
- Comprehensive API documentation
- Built-in testing framework
- Docker-ready deployment

---

## 🛠️ Tech Stack

**Core Technologies:**
- Python 3.10+
- FastAPI (async web framework)
- PostgreSQL (relational database)
- SQLAlchemy 2.0 (ORM)
- Pydantic (data validation)

**Security:**
- JWT (JSON Web Tokens)
- Argon2 password hashing
- OAuth2 password flow
- CORS configuration

**Development Tools:**
- Alembic (database migrations)
- pytest (testing)
- Ruff (code linting)
- mypy (static type checking)
- Docker (containerization)

**System Requirements:**
- Python 3.10 or higher
- PostgreSQL 13+
- Redis (for production deployments)
- SMTP server (for email functionality)

---

## 📦 Installation

### Prerequisites

Before you begin, ensure you have the following installed:
- Python 3.10+
- PostgreSQL 13+
- Redis (optional, for production)
- Docker (optional, for containerized deployment)

### Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Noman-Ahmad25/vims-platform.git
   cd vims-platform
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
   ```

3. **Install dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Set up environment variables:**
   ```bash
   cp .env.example .env
   ```
   Edit the `.env` file with your configuration (see [Configuration](#-configuration) section)

5. **Set up the database:**
   ```bash
   alembic revision --autogenerate -m "initial migration"
   alembic upgrade head
   ```

6. **Run the development server:**
   ```bash
   uvicorn app.main:app --reload --workers 1
   ```

### Alternative Installation Methods

**Using Docker:**
```bash
docker-compose up --build
```

**Development Setup:**
```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run code linter
ruff check .

# Run type checker
mypy app/
```

---

## 🎯 Usage

### Basic API Endpoints

**Authentication:**
```bash
# Register a new volunteer account
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "volunteer@example.com",
    "password": "SecurePass123!@#",
    "confirm_password": "SecurePass123!@#",
    "first_name": "John",
    "last_name": "Doe"
  }'

# Login to get tokens
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "volunteer@example.com",
    "password": "SecurePass123!@#"
  }'
```

**Volunteer Profile:**
```bash
# Create volunteer profile (requires authentication)
curl -X POST "http://localhost:8000/api/v1/volunteer/profile" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+15551234567",
    "bio": "Community volunteer passionate about education",
    "skills": ["Teaching", "Mentoring"],
    "availability": "flexible"
  }'
```

**Opportunity Management:**
```bash
# Create a new opportunity (requires staff/admin role)
curl -X POST "http://localhost:8000/api/v1/admin/opportunities" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Community Reading Program",
    "description": "Help organize and lead weekly reading sessions for children",
    "category": "education",
    "start_date": "2023-12-01T10:00:00Z",
    "end_date": "2023-12-31T17:00:00Z",
    "application_deadline": "2023-11-30T23:59:59Z",
    "slots_total": 10,
    "location_name": "Central Library",
    "city": "New York",
    "country": "USA"
  }'
```

### Advanced Usage with Python Client

```python
from fastapi import FastAPI
from httpx import AsyncClient

async def test_volunteer_flow():
    app = FastAPI()
    async with AsyncClient(app=app, base_url="http://test") as client:

        # Register
        register_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "TestPass123!@#",
                "confirm_password": "TestPass123!@#",
                "first_name": "Test",
                "last_name": "User"
            }
        )
        token = register_resp.json()["detail"]["email_verification_token"]

        # Verify email
        verify_resp = await client.get(f"/api/v1/auth/verify-email?token={token}")
        assert verify_resp.status_code == 200

        # Login
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.com",
                "password": "TestPass123!@#"
            }
        )
        access_token = login_resp.json()["access_token"]

        # Create profile
        profile_resp = await client.post(
            "/api/v1/volunteer/profile",
            json={
                "phone_number": "+15551234567",
                "skills": ["Community Service"]
            },
            headers={"Authorization": f"Bearer {access_token}"}
        )
        assert profile_resp.status_code == 201

        # Apply to opportunity
        apply_resp = await client.post(
            "/api/v1/volunteer/applications",
            json={
                "opportunity_id": "some-opportunity-uuid",
                "hours_committed": 10
            },
            headers={"Authorization": f"Bearer {access_token}"}
        )
        assert apply_resp.status_code == 201

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_volunteer_flow())
```

---

## 📁 Project Structure

```
vims-platform/
├── alembic/                  # Database migrations
│   ├── env.py                # Alembic environment configuration
│   ├── README                # Migration documentation
│   └── versions/             # Migration scripts
├── app/                      # Application source code
│   ├── api/                  # API endpoints
│   │   ├── v1/               # API version 1
│   │   │   ├── endpoints/    # Route handlers
│   │   │   └── router.py     # API router configuration
│   ├── core/                 # Core application components
│   │   ├── config.py         # Configuration management
│   │   ├── database.py       # Database connection and models
│   │   └── security.py       # Authentication and authorization
│   ├── models/               # Database models
│   │   ├── __init__.py       # Model imports
│   │   ├── base.py           # Base model mixins
│   │   ├── enums.py          # Enumeration types
│   │   ├── opportunity.py    # Opportunity model
│   │   └── user.py           # User model
│   ├── schemas/              # Data schemas
│   ├── services/             # Business logic services
│   ├── utils/                # Utility functions
│   ├── main.py               # Application entry point
│   └── tests/                # Integration tests
├── tests/                    # Unit tests
│   ├── conftest.py           # Test fixtures
│   ├── test_auth.py          # Authentication tests
│   ├── test_opportunity.py   # Opportunity tests
│   └── ...                   # Other test files
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules
├── LICENSE                   # License file
├── pyproject.toml            # Project configuration
├── README.md                 # This file
└── docker-compose.yml        # Docker configuration (if exists)
```

---

## 🔧 Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure your environment:

```ini
# Application settings
APP_NAME="Volunteer Information Management System"
APP_VERSION="1.0.0"
ENVIRONMENT=development
DEBUG=false

# Security settings
SECRET_KEY=your_64_byte_random_secret_string_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Database configuration
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/vims_db

# CORS configuration
BACKEND_CORS_ORIGINS='["http://localhost:3000", "http://127.0.0.1:3000"]'

# Email configuration (optional)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=email@example.com
SMTP_PASSWORD=your_email_password
EMAILS_FROM_NAME="VIMS Platform"
EMAILS_FROM_EMAIL=noreply@yourdomain.com

# Pagination settings
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=100
```

### Database Configuration

VIMS uses PostgreSQL with SQLAlchemy 2.0 for async database operations. The connection pool is configured for optimal performance:

```python
# Database connection settings in app/core/database.py
SQLALCHEMY_POOL_SIZE=10
SQLALCHEMY_MAX_OVERFLOW=20
SQLALCHEMY_POOL_TIMEOUT=30
SQLALCHEMY_POOL_RECYCLE=1800
```

### SSL Configuration

For production deployments, SSL is automatically configured for PostgreSQL connections:

```python
# SSL configuration in app/core/database.py
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
```

---

## 🤝 Contributing

We welcome contributions from the community! Here's how you can help:

### Development Setup

1. Fork the repository and clone your fork
2. Set up your development environment as described in [Installation](#-installation)
3. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

### Code Style Guidelines

- Follow PEP 8 style guidelines
- Use type hints throughout the codebase
- Write comprehensive docstrings for all public functions and classes
- Keep functions small and focused (preferably < 20 lines)
- Use consistent naming conventions (snake_case for variables/functions, PascalCase for classes)

### Pull Request Process

1. Create a new branch for your feature or bugfix
2. Make your changes and ensure they pass all tests
3. Update documentation if necessary
4. Submit a pull request with a clear description of your changes
5. Be responsive to feedback and make any requested changes

### Testing

VIMS includes comprehensive test coverage:

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_auth.py

# Run tests with coverage report
pytest tests/ --cov=app --cov-report=term-missing
```

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👥 Authors & Contributors

**Maintainer:**
- [Noman Ahmad](https://github.com/Noman-Ahmad25) - Initial development and architecture

---

## 🐛 Issues & Support

### Reporting Issues

If you encounter a problem or have a feature request:
1. Search the [issue tracker](https://github.com/Noman-Ahmad25/vims-platform/issues) to see if it's already reported
2. If not, open a new issue with:
   - Clear description of the problem
   - Steps to reproduce
   - Expected behavior
   - Any relevant error messages
   - Your environment information

### Getting Help

For questions or support:
- Open an issue on GitHub

### FAQ

**Q: How do I deploy this to production?** 
A: See our [Deployment Guide](docs/deployment.md) for production setup instructions.

**Q: Can I customize the email templates?**
A: Yes! Modify the email templates in `app/templates/email/` and configure the SMTP settings in your `.env` file.

**Q: How do I add a new role?**
A: Add a new enum value to `app/models/enums.py` and update the permission checks in `app/core/security.py`.

---

## 🗺️ Roadmap

### Planned Features

1. **Q1 2024:**
   - [ ] Add multi-factor authentication (MFA)
   - [ ] Implement opportunity search with filters
   - [ ] Add analytics dashboard for admins

2. **Q2 2024:**
   - [ ] Integrate with calendar services (Google Calendar, Outlook)
   - [ ] Add volunteer certification system
   - [ ] Implement API rate limiting

3. **Q3 2024:**
   - [ ] Add mobile app support
   - [ ] Implement payment processing for premium features
   - [ ] Add internationalization (i18n) support

### Future Improvements

- Add WebSocket support for real-time notifications
- Implement caching layer for frequently accessed data
- Add support for more database backends (MySQL, SQLite)
- Create a CLI tool for common administrative tasks

---

## 🚀 Getting Started

Ready to contribute or use VIMS in your project? Let's get started!

1. **Star this repository** to show your support
2. **Fork the project** to start your own development
3. **Clone your fork** and begin making changes
4. **Submit a pull request** with your improvements

Join our community and help build the future of volunteer management!

```bash
# Clone and contribute today!
git clone https://github.com/Noman-Ahmad25/vims-platform.git
cd vims-platform
pip install -e ".[dev]"
# Start coding!
```

Thank you for using VIMS! We're excited to see what you build with this platform.
```
