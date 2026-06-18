from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ────────────────────────────────────────────────────────────────────────────
# Happy Path: Complete Volunteer Onboarding Flow
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_volunteer_onboarding_flow(client: AsyncClient) -> None:
    """
    Sequential happy path workflow:
    1. Register a volunteer account
    2. Verify email using the token from registration
    3. Login to get access and refresh tokens
    4. Check that profile doesn't exist (404)
    5. Create volunteer profile
    """

    # ── Step 1: Register ────────────────────────────────────────────────────

    register_payload = {
        "email": "alice@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Alice",
        "last_name": "Wonder",
    }

    resp = await client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["message"] == "Registration successful. Please verify your email."
    assert "email_verification_token" in data["detail"]
    assert "user_id" in data["detail"]
    email_token = data["detail"]["email_verification_token"]

    # ── Step 2: Verify Email ────────────────────────────────────────────────

    resp = await client.get(f"/api/v1/auth/verify-email?token={email_token}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Email verified successfully. You can now log in."

    # ── Step 3: Login ───────────────────────────────────────────────────────

    login_payload = {
        "email": "alice@example.com",
        "password": "SecurePass123!@#",
    }

    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    access_token = data["access_token"]

    # ── Step 4: Check Profile (should not exist) ────────────────────────────

    headers = {"Authorization": f"Bearer {access_token}"}
    resp = await client.get("/api/v1/volunteer/profile", headers=headers)
    assert resp.status_code == 404

    # ── Step 5: Create Volunteer Profile ────────────────────────────────────

    profile_payload = {
        "phone_number": "+1-555-123-4567",
        "bio": "Passionate about community service.",
        "city": "San Francisco",
        "state_province": "CA",
        "country": "USA",
        "skills": ["Python", "Community Outreach"],
        "languages_spoken": ["English", "Spanish"],
        "hours_per_week": 10,
    }

    resp = await client.post(
        "/api/v1/volunteer/profile",
        json=profile_payload,
        headers=headers,
    )
    assert resp.status_code == 201
    profile_data = resp.json()
    assert profile_data["user_id"]
    assert profile_data["phone_number"] == "+15551234567"
    assert profile_data["bio"] == "Passionate about community service."
    assert profile_data["city"] == "San Francisco"
    assert profile_data["skills"] == ["Python", "Community Outreach"]
    assert profile_data["languages_spoken"] == ["English", "Spanish"]
    assert profile_data["hours_per_week"] == 10


# ────────────────────────────────────────────────────────────────────────────
# Negative Tests: Registration
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient) -> None:
    """Registration fails with invalid email format."""
    payload = {
        "email": "not-an-email",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Test",
        "last_name": "User",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert "Validation failed" in data["error"]


@pytest.mark.asyncio
async def test_register_missing_required_field(client: AsyncClient) -> None:
    """Registration fails when required field is missing."""
    payload = {
        "email": "bob@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        # missing first_name
        "last_name": "User",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_register_password_confirm_mismatch(client: AsyncClient) -> None:
    """Registration fails when password and confirm_password don't match."""
    payload = {
        "email": "charlie@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "DifferentPass123!@#",
        "first_name": "Charlie",
        "last_name": "Brown",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert "Validation failed" in data["error"]


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient) -> None:
    """Registration fails with weak password (missing requirements)."""
    weak_passwords = [
        "short",  # too short, missing uppercase, digit, special
        "NoDigitOrSpecial!",  # missing digit
        "nouppercaseorspecial1",  # missing uppercase
        "NoLowercaseOrSpecial1",  # missing lowercase
    ]
    
    for weak_pass in weak_passwords:
        payload = {
            "email": f"user_{weak_pass[:5]}@example.com",
            "password": weak_pass,
            "confirm_password": weak_pass,
            "first_name": "Test",
            "last_name": "User",
        }
        resp = await client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    """Registration fails when email is already registered."""
    payload = {
        "email": "duplicate@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "First",
        "last_name": "User",
    }
    
    # First registration succeeds
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201
    
    # Second registration with same email fails
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409
    data = resp.json()
    assert "error" in data


# ────────────────────────────────────────────────────────────────────────────
# Negative Tests: Email Verification
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_email_invalid_token(client: AsyncClient) -> None:
    """Email verification fails with invalid token."""
    resp = await client.get("/api/v1/auth/verify-email?token=invalid_token_xyz")
    assert resp.status_code == 410
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_verify_email_missing_token(client: AsyncClient) -> None:
    """Email verification fails when token query param is missing."""
    resp = await client.get("/api/v1/auth/verify-email")
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_verify_email_already_verified(client: AsyncClient) -> None:
    """Email verification fails when email is already verified."""
    # Register and verify
    payload = {
        "email": "alreadyverified@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Already",
        "last_name": "Verified",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201
    token = resp.json()["detail"]["email_verification_token"]
    
    # Verify once
    resp = await client.get(f"/api/v1/auth/verify-email?token={token}")
    assert resp.status_code == 200
    
    # Try to verify again with same token
    resp = await client.get(f"/api/v1/auth/verify-email?token={token}")
    assert resp.status_code == 410
    data = resp.json()
    assert "error" in data


# ────────────────────────────────────────────────────────────────────────────
# Negative Tests: Login
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_invalid_email(client: AsyncClient) -> None:
    """Login fails with invalid email format."""
    payload = {
        "email": "not-an-email",
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_login_missing_email(client: AsyncClient) -> None:
    """Login fails when email is missing."""
    payload = {
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_login_missing_password(client: AsyncClient) -> None:
    """Login fails when password is missing."""
    payload = {
        "email": "someone@example.com",
    }
    resp = await client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_login_unverified_email(client: AsyncClient) -> None:
    """Login fails when email is registered but not verified."""
    # Register but don't verify
    payload = {
        "email": "unverified@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Unverified",
        "last_name": "User",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201
    
    # Try to login without verifying email
    login_payload = {
        "email": "unverified@example.com",
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 403
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    """Login fails with incorrect password."""
    # Register and verify
    payload = {
        "email": "wrongpass@example.com",
        "password": "CorrectPass123!@#",
        "confirm_password": "CorrectPass123!@#",
        "first_name": "Wrong",
        "last_name": "Pass",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    token = resp.json()["detail"]["email_verification_token"]
    await client.get(f"/api/v1/auth/verify-email?token={token}")
    
    # Try to login with wrong password
    login_payload = {
        "email": "wrongpass@example.com",
        "password": "WrongPass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient) -> None:
    """Login fails for non-existent email."""
    payload = {
        "email": "nonexistent@example.com",
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=payload)
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data


# ────────────────────────────────────────────────────────────────────────────
# Negative Tests: Profile Access
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profile_unauthorized_no_token(client: AsyncClient) -> None:
    """Accessing the profile endpoint without an Authorization header fails."""
    resp = await client.get("/api/v1/volunteer/profile")
    assert resp.status_code == 401
    data = resp.json()
    assert "detail" in data
    assert data["detail"] == "Not authenticated"



@pytest.mark.asyncio
async def test_profile_unauthorized_invalid_token(client: AsyncClient) -> None:
    """Accessing the profile endpoint with an invalid token fails."""
    headers = {"Authorization": "Bearer invalid_token_value_xyz"}
    resp = await client.get("/api/v1/volunteer/profile", headers=headers)
    assert resp.status_code == 401
    data = resp.json()
    assert "detail" in data
    assert data["detail"] == "Could not validate credentials."



@pytest.mark.asyncio
async def test_profile_create_missing_fields(client: AsyncClient) -> None:
    """Profile creation still works with all optional fields."""
    # Register and verify to get valid token
    payload = {
        "email": "minimalprofile@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Minimal",
        "last_name": "Profile",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    token = resp.json()["detail"]["email_verification_token"]
    await client.get(f"/api/v1/auth/verify-email?token={token}")
    
    # Login
    login_payload = {
        "email": "minimalprofile@example.com",
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    access_token = resp.json()["access_token"]
    
    # Create profile with empty payload (all optional)
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = await client.post("/api/v1/volunteer/profile", json={}, headers=headers)
    assert resp.status_code == 201
    profile_data = resp.json()
    assert profile_data["user_id"]
    assert profile_data["country"] == "India"  # default


@pytest.mark.asyncio
async def test_profile_create_invalid_phone(client: AsyncClient) -> None:
    """Profile creation fails with invalid phone number."""
    # Register and verify
    payload = {
        "email": "invalidphone@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Invalid",
        "last_name": "Phone",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    token = resp.json()["detail"]["email_verification_token"]
    await client.get(f"/api/v1/auth/verify-email?token={token}")
    
    # Login
    login_payload = {
        "email": "invalidphone@example.com",
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    access_token = resp.json()["access_token"]
    
    # Create profile with invalid phone
    headers = {"Authorization": f"Bearer {access_token}"}
    profile_payload = {
        "phone_number": "invalid",
    }
    resp = await client.post(
        "/api/v1/volunteer/profile",
        json=profile_payload,
        headers=headers,
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_profile_create_invalid_dob(client: AsyncClient) -> None:
    """Profile creation fails with future date of birth."""
    # Register and verify
    payload = {
        "email": "futuredob@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Future",
        "last_name": "DOB",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    token = resp.json()["detail"]["email_verification_token"]
    await client.get(f"/api/v1/auth/verify-email?token={token}")
    
    # Login
    login_payload = {
        "email": "futuredob@example.com",
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    access_token = resp.json()["access_token"]
    
    # Create profile with future DOB
    headers = {"Authorization": f"Bearer {access_token}"}
    profile_payload = {
        "date_of_birth": "2099-12-31",
    }
    resp = await client.post(
        "/api/v1/volunteer/profile",
        json=profile_payload,
        headers=headers,
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_profile_create_invalid_hours(client: AsyncClient) -> None:
    """Profile creation fails with invalid hours per week."""
    # Register and verify
    payload = {
        "email": "badhours@example.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Bad",
        "last_name": "Hours",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    token = resp.json()["detail"]["email_verification_token"]
    await client.get(f"/api/v1/auth/verify-email?token={token}")
    
    # Login
    login_payload = {
        "email": "badhours@example.com",
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    access_token = resp.json()["access_token"]
    
    # Create profile with invalid hours (> 168)
    headers = {"Authorization": f"Bearer {access_token}"}
    profile_payload = {
        "hours_per_week": 200,
    }
    resp = await client.post(
        "/api/v1/volunteer/profile",
        json=profile_payload,
        headers=headers,
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_profile_duplicate_creation(client: AsyncClient) -> None:
    """Profile creation fails if volunteer profile already exists."""
    # Register and verify
    payload = {
        "email": "duplicate@profile.com",
        "password": "SecurePass123!@#",
        "confirm_password": "SecurePass123!@#",
        "first_name": "Duplicate",
        "last_name": "Profile",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    token = resp.json()["detail"]["email_verification_token"]
    await client.get(f"/api/v1/auth/verify-email?token={token}")
    
    # Login
    login_payload = {
        "email": "duplicate@profile.com",
        "password": "SecurePass123!@#",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    access_token = resp.json()["access_token"]
    
    # Create profile first time
    headers = {"Authorization": f"Bearer {access_token}"}
    profile_payload = {"bio": "First profile"}
    resp = await client.post(
        "/api/v1/volunteer/profile",
        json=profile_payload,
        headers=headers,
    )
    assert resp.status_code == 201
    
    # Try to create profile again
    resp = await client.post(
        "/api/v1/volunteer/profile",
        json=profile_payload,
        headers=headers,
    )
    assert resp.status_code == 409
    data = resp.json()
    assert "error" in data
