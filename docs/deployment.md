# Deployment Guide

VIMS is optimized for containerized environments.

## Production Checklist
1. **Environment Variables**: Ensure `SECRET_KEY`, `DATABASE_URL`, and `SMTP` settings are injected via secure environment variables.
2. **Migrations**: Always run `alembic upgrade head` as part of your CI/CD pipeline before starting the server.
3. **Database Pool**: The system is pre-configured for connection pooling (Pool Size: 10, Max Overflow: 20) to handle concurrent connections efficiently.
4. **SSL/TLS**: The database connection utilizes `ssl.create_default_context()` to ensure data in transit is encrypted.