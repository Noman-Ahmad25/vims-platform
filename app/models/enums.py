from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    """Roles stored on the ``users`` table and checked by the RBAC layer."""

    VOLUNTEER = "volunteer"
    STAFF = "staff"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class UserStatus(str, enum.Enum):
    """Account lifecycle status."""

    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class AvailabilityType(str, enum.Enum):
    """When a volunteer is available."""

    WEEKDAYS = "weekdays"
    WEEKENDS = "weekends"
    EVENINGS = "evenings"
    FLEXIBLE = "flexible"
    FULL_TIME = "full_time"


class SkillLevel(str, enum.Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class OpportunityStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class OpportunityCategory(str, enum.Enum):
    EDUCATION = "education"
    HEALTH = "health"
    ENVIRONMENT = "environment"
    COMMUNITY = "community"
    ARTS = "arts"
    SPORTS = "sports"
    TECHNOLOGY = "technology"
    DISASTER_RELIEF = "disaster_relief"
    ANIMAL_WELFARE = "animal_welfare"
    OTHER = "other"


class ApplicationStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WAITLISTED = "waitlisted"
    WITHDRAWN = "withdrawn"
    COMPLETED = "completed"


class ApplicationOutcome(str, enum.Enum):
    """Post-completion outcome recorded by staff."""

    SATISFACTORY = "satisfactory"
    OUTSTANDING = "outstanding"
    UNSATISFACTORY = "unsatisfactory"
    NO_SHOW = "no_show"
    INCOMPLETE = "incomplete"