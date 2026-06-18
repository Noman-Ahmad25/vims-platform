"""
ORM model package.

Importing this package registers every model class onto ``Base.metadata``
so that ``Base.metadata.create_all()`` and Alembic autogenerate can
discover them without side-effect imports elsewhere.
"""
from app.models.enums import (
    ApplicationOutcome,
    ApplicationStatus,
    AvailabilityType,
    OpportunityCategory,
    OpportunityStatus,
    SkillLevel,
    UserRole,
    UserStatus,
)
from app.models.opportunity import Application, Opportunity
from app.models.user import User, VolunteerProfile

__all__ = [
    # enums
    "UserRole",
    "UserStatus",
    "AvailabilityType",
    "SkillLevel",
    "OpportunityCategory",
    "OpportunityStatus",
    "ApplicationStatus",
    "ApplicationOutcome",
    # models
    "User",
    "VolunteerProfile",
    "Opportunity",
    "Application",
]