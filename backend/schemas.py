"""
TransitOps - Pydantic Schemas

All request/response data transfer objects, organized per entity.
Enumerations are imported from models.py to keep a single source of truth.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from backend.models import (
    DriverStatus,
    ExpenseType,
    MaintenanceStatus,
    TripStatus,
    UserRole,
    VehicleStatus,
    VehicleType,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Base helper
# ═══════════════════════════════════════════════════════════════════════════════

class OrmBase(BaseModel):
    """Common config enabling ORM-mode for all response schemas."""

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Seconds until expiry")
    user_role: UserRole
    user_id: int


# ═══════════════════════════════════════════════════════════════════════════════
#  USER
# ═══════════════════════════════════════════════════════════════════════════════

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Plaintext; hashed server-side")
    full_name: Optional[str] = None
    role: UserRole = UserRole.FLEET_MANAGER


class UserResponse(OrmBase):
    id: int
    email: EmailStr
    full_name: Optional[str]
    role: UserRole
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  VEHICLE
# ═══════════════════════════════════════════════════════════════════════════════

class VehicleCreate(BaseModel):
    registration_number: str = Field(..., max_length=50)
    name_model: str = Field(..., max_length=150)
    type: VehicleType
    region: Optional[str] = Field(None, max_length=100, description="Operating region / depot")
    max_load_capacity: float = Field(..., gt=0, description="Maximum cargo in kg")
    odometer: float = Field(0.0, ge=0, description="Current odometer reading in km")
    acquisition_cost: float = Field(..., ge=0, description="Purchase/lease cost")
    status: VehicleStatus = VehicleStatus.AVAILABLE


class VehicleUpdate(BaseModel):
    name_model: Optional[str] = None
    type: Optional[VehicleType] = None
    region: Optional[str] = Field(None, max_length=100)
    max_load_capacity: Optional[float] = Field(None, gt=0)
    odometer: Optional[float] = Field(None, ge=0)
    acquisition_cost: Optional[float] = Field(None, ge=0)
    status: Optional[VehicleStatus] = None


class VehicleResponse(OrmBase):
    registration_number: str
    name_model: str
    type: VehicleType
    region: Optional[str]
    max_load_capacity: float
    odometer: float
    acquisition_cost: float
    status: VehicleStatus
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════════════════════
#  DRIVER
# ═══════════════════════════════════════════════════════════════════════════════

class DriverCreate(BaseModel):
    name: str = Field(..., max_length=150)
    license_number: str = Field(..., max_length=100)
    license_category: str = Field(..., max_length=20, examples=["LMV", "HMV", "HGV"])
    license_expiry_date: date
    contact_number: str = Field(..., max_length=20)
    safety_score: float = Field(100.0, ge=0.0, le=100.0)
    status: DriverStatus = DriverStatus.AVAILABLE

    @field_validator("license_expiry_date")
    @classmethod
    def expiry_must_be_future(cls, v: date) -> date:
        if v < date.today():
            raise ValueError(
                f"license_expiry_date {v} is already expired. "
                "Cannot register a driver with an expired license."
            )
        return v


class DriverUpdate(BaseModel):
    name: Optional[str] = None
    license_category: Optional[str] = None
    license_expiry_date: Optional[date] = None
    contact_number: Optional[str] = None
    safety_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    status: Optional[DriverStatus] = None


class DriverResponse(OrmBase):
    id: int
    name: str
    license_number: str
    license_category: str
    license_expiry_date: date
    contact_number: str
    safety_score: float
    status: DriverStatus
    created_at: datetime
    updated_at: datetime


class LicenseReminder(OrmBase):
    """A driver whose license is expired or expiring soon (§ Safety Officer)."""
    id: int
    name: str
    license_number: str
    license_category: str
    license_expiry_date: date
    contact_number: str
    status: DriverStatus
    days_until_expiry: int   # negative if already expired
    is_expired: bool


# ═══════════════════════════════════════════════════════════════════════════════
#  TRIP
# ═══════════════════════════════════════════════════════════════════════════════

class TripCreate(BaseModel):
    source: str = Field(..., max_length=200)
    destination: str = Field(..., max_length=200)
    vehicle_id: str = Field(..., max_length=50)
    driver_id: int
    cargo_weight: float = Field(..., gt=0, description="Cargo weight in kg")
    planned_distance: float = Field(..., gt=0, description="Planned distance in km")
    revenue: Optional[float] = Field(None, ge=0, description="Expected revenue for ROI")

    @model_validator(mode="after")
    def source_and_destination_differ(self) -> "TripCreate":
        if self.source.strip().lower() == self.destination.strip().lower():
            raise ValueError("source and destination must be different locations.")
        return self


class TripUpdate(BaseModel):
    """General-purpose patch schema. Status transitions use TripStatusUpdate."""
    source: Optional[str] = None
    destination: Optional[str] = None
    cargo_weight: Optional[float] = Field(None, gt=0)
    planned_distance: Optional[float] = Field(None, gt=0)
    revenue: Optional[float] = Field(None, ge=0)
    final_odometer: Optional[float] = Field(None, ge=0)
    fuel_consumed: Optional[float] = Field(None, gt=0)


class TripStatusUpdate(BaseModel):
    """Dedicated schema for status transitions to make intent explicit."""
    status: TripStatus
    final_odometer: Optional[float] = Field(
        None, ge=0,
        description="Required when completing a trip"
    )
    fuel_consumed: Optional[float] = Field(
        None, gt=0,
        description="Required when completing a trip"
    )

    @model_validator(mode="after")
    def completion_requires_odometer_and_fuel(self) -> "TripStatusUpdate":
        if self.status == TripStatus.COMPLETED:
            if self.final_odometer is None:
                raise ValueError("final_odometer is required when completing a trip.")
            if self.fuel_consumed is None:
                raise ValueError("fuel_consumed is required when completing a trip.")
        return self


class TripResponse(OrmBase):
    id: int
    source: str
    destination: str
    vehicle_id: str
    driver_id: int
    cargo_weight: float
    planned_distance: float
    status: TripStatus
    final_odometer: Optional[float]
    fuel_consumed: Optional[float]
    revenue: Optional[float]
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════════════════════
#  MAINTENANCE LOG
# ═══════════════════════════════════════════════════════════════════════════════

class MaintenanceCreate(BaseModel):
    vehicle_id: str = Field(..., max_length=50)
    description: str
    cost: float = Field(..., ge=0)
    date: date
    status: MaintenanceStatus = MaintenanceStatus.ACTIVE


class MaintenanceUpdate(BaseModel):
    description: Optional[str] = None
    cost: Optional[float] = Field(None, ge=0)
    date: Optional[date] = None
    status: Optional[MaintenanceStatus] = None


class MaintenanceResponse(OrmBase):
    id: int
    vehicle_id: str
    description: str
    cost: float
    date: date
    status: MaintenanceStatus
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════════════════════
#  FUEL & EXPENSES
# ═══════════════════════════════════════════════════════════════════════════════

class ExpenseCreate(BaseModel):
    vehicle_id: str = Field(..., max_length=50)
    expense_type: ExpenseType
    liters: Optional[float] = Field(None, gt=0, description="Fuel volume (Fuel type only)")
    cost: float = Field(..., gt=0)
    date: date
    notes: Optional[str] = None

    @model_validator(mode="after")
    def fuel_requires_liters(self) -> "ExpenseCreate":
        if self.expense_type == ExpenseType.FUEL and self.liters is None:
            raise ValueError("'liters' is required for Fuel expense type.")
        if self.expense_type != ExpenseType.FUEL and self.liters is not None:
            raise ValueError("'liters' should only be provided for Fuel expense type.")
        return self


class ExpenseUpdate(BaseModel):
    expense_type: Optional[ExpenseType] = None
    liters: Optional[float] = Field(None, gt=0)
    cost: Optional[float] = Field(None, gt=0)
    date: Optional[date] = None
    notes: Optional[str] = None


class ExpenseResponse(OrmBase):
    id: int
    vehicle_id: str
    expense_type: ExpenseType
    liters: Optional[float]
    cost: float
    date: date
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD KPIs
# ═══════════════════════════════════════════════════════════════════════════════

class DashboardKPIs(BaseModel):
    total_vehicles: int
    active_vehicles: int           # Any status except Retired
    available_vehicles: int
    vehicles_on_trip: int
    vehicles_in_shop: int
    retired_vehicles: int
    fleet_utilization_pct: float   # (On Trip / Active) * 100

    total_drivers: int
    available_drivers: int
    drivers_on_trip: int
    suspended_drivers: int

    total_trips: int
    active_trips: int              # Dispatched
    pending_trips: int             # Draft (awaiting dispatch)
    completed_trips: int
    cancelled_trips: int

    total_maintenance_logs: int
    open_maintenance_logs: int

    total_expenses: float          # Sum of all costs


# ═══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class VehicleAnalytics(BaseModel):
    registration_number: str
    name_model: str
    region: Optional[str]
    acquisition_cost: float
    total_distance_km: float
    total_fuel_liters: float
    fuel_efficiency_km_per_liter: Optional[float]  # distance / fuel
    total_fuel_cost: float
    total_maintenance_cost: float
    total_operational_cost: float  # fuel_cost + maintenance_cost
    total_revenue: float
    roi_pct: Optional[float]       # (revenue - operational_cost) / acquisition_cost * 100


class FleetAnalyticsReport(BaseModel):
    generated_at: datetime
    fleet_fuel_efficiency_km_per_liter: Optional[float]
    fleet_total_operational_cost: float
    fleet_total_revenue: float
    fleet_roi_pct: Optional[float]
    vehicles: list[VehicleAnalytics]
