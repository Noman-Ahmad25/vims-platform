from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.volunteer import router as volunteer_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(volunteer_router)
api_router.include_router(admin_router)