"""
TransitOps - SQLAlchemy ORM Models

Defines all database entities, enumerations, and their relationships.
"""

import enum
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


# ═══════════════════════════════════════════════════════════════════════════════
#  Python Enumerations  (single source of truth — also imported by schemas.py)
# ═══════════════════════════════════════════════════════════════════════════════

class UserRole(str, enum.Enum):
    FLEET_MANAGER    = "Fleet Manager"
    DRIVER           = "Driver"
    SAFETY_OFFICER   = "Safety Officer"
    FINANCIAL_ANALYST = "Financial Analyst"


class VehicleStatus(str, enum.Enum):
    AVAILABLE = "Available"
    ON_TRIP   = "On Trip"
    IN_SHOP   = "In Shop"
    RETIRED   = "Retired"


class VehicleType(str, enum.Enum):
    TRUCK      = "Truck"
    VAN        = "Van"
    BUS        = "Bus"
    CAR        = "Car"
    MOTORCYCLE = "Motorcycle"
    OTHER      = "Other"


class DriverStatus(str, enum.Enum):
    AVAILABLE = "Available"
    ON_TRIP   = "On Trip"
    OFF_DUTY  = "Off Duty"
    SUSPENDED = "Suspended"


class TripStatus(str, enum.Enum):
    DRAFT      = "Draft"
    DISPATCHED = "Dispatched"
    COMPLETED  = "Completed"
    CANCELLED  = "Cancelled"


class MaintenanceStatus(str, enum.Enum):
    ACTIVE = "Active"
    CLOSED = "Closed"


class ExpenseType(str, enum.Enum):
    FUEL        = "Fuel"
    TOLL        = "Toll"
    MAINTENANCE = "Maintenance"


# ═══════════════════════════════════════════════════════════════════════════════
#  Mixin — Timestamps
# ═══════════════════════════════════════════════════════════════════════════════

class TimestampMixin:
    """Adds created_at / updated_at columns to any model."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Model: User
# ═══════════════════════════════════════════════════════════════════════════════

class User(TimestampMixin, Base):
    """Platform users with role-based access."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, default=UserRole.FLEET_MANAGER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role}>"


# ═══════════════════════════════════════════════════════════════════════════════
#  Model: Vehicle
# ═══════════════════════════════════════════════════════════════════════════════

class Vehicle(TimestampMixin, Base):
    """Fleet vehicles tracked by registration number."""

    __tablename__ = "vehicles"

    registration_number: Mapped[str] = mapped_column(
        String(50), primary_key=True, index=True
    )
    name_model: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[VehicleType] = mapped_column(
        SAEnum(VehicleType, name="vehicle_type"), nullable=False
    )
    max_load_capacity: Mapped[float] = mapped_column(Float, nullable=False)  # in kg
    odometer: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # in km
    acquisition_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[VehicleStatus] = mapped_column(
        SAEnum(VehicleStatus, name="vehicle_status"),
        nullable=False,
        default=VehicleStatus.AVAILABLE,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    trips: Mapped[List["Trip"]] = relationship(
        "Trip", back_populates="vehicle", lazy="select"
    )
    maintenance_logs: Mapped[List["MaintenanceLog"]] = relationship(
        "MaintenanceLog", back_populates="vehicle", lazy="select"
    )
    expenses: Mapped[List["FuelExpense"]] = relationship(
        "FuelExpense", back_populates="vehicle", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Vehicle reg={self.registration_number!r} status={self.status}>"


# ═══════════════════════════════════════════════════════════════════════════════
#  Model: Driver
# ═══════════════════════════════════════════════════════════════════════════════

class Driver(TimestampMixin, Base):
    """Licensed drivers operating fleet vehicles."""

    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    license_number: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    license_category: Mapped[str] = mapped_column(String(20), nullable=False)
    license_expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    contact_number: Mapped[str] = mapped_column(String(20), nullable=False)
    safety_score: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    status: Mapped[DriverStatus] = mapped_column(
        SAEnum(DriverStatus, name="driver_status"),
        nullable=False,
        default=DriverStatus.AVAILABLE,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    trips: Mapped[List["Trip"]] = relationship(
        "Trip", back_populates="driver", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Driver id={self.id} name={self.name!r} status={self.status}>"


# ═══════════════════════════════════════════════════════════════════════════════
#  Model: Trip
# ═══════════════════════════════════════════════════════════════════════════════

class Trip(TimestampMixin, Base):
    """A cargo delivery journey from source to destination."""

    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    vehicle_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("vehicles.registration_number", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    cargo_weight: Mapped[float] = mapped_column(Float, nullable=False)      # in kg
    planned_distance: Mapped[float] = mapped_column(Float, nullable=False)  # in km
    status: Mapped[TripStatus] = mapped_column(
        SAEnum(TripStatus, name="trip_status"),
        nullable=False,
        default=TripStatus.DRAFT,
    )
    # Populated on completion
    final_odometer: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fuel_consumed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # in liters
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="trips")
    driver: Mapped["Driver"] = relationship("Driver", back_populates="trips")

    def __repr__(self) -> str:
        return f"<Trip id={self.id} {self.source!r}->{self.destination!r} status={self.status}>"


# ═══════════════════════════════════════════════════════════════════════════════
#  Model: MaintenanceLog
# ═══════════════════════════════════════════════════════════════════════════════

class MaintenanceLog(TimestampMixin, Base):
    """Scheduled or corrective maintenance work on a vehicle."""

    __tablename__ = "maintenance_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vehicle_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("vehicles.registration_number", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[MaintenanceStatus] = mapped_column(
        SAEnum(MaintenanceStatus, name="maintenance_status"),
        nullable=False,
        default=MaintenanceStatus.ACTIVE,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="maintenance_logs")

    def __repr__(self) -> str:
        return f"<MaintenanceLog id={self.id} vehicle={self.vehicle_id!r} status={self.status}>"


# ═══════════════════════════════════════════════════════════════════════════════
#  Model: FuelExpense
# ═══════════════════════════════════════════════════════════════════════════════

class FuelExpense(TimestampMixin, Base):
    """Fuel fills, toll charges, and miscellaneous vehicle expenses."""

    __tablename__ = "fuel_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vehicle_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("vehicles.registration_number", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    expense_type: Mapped[ExpenseType] = mapped_column(
        SAEnum(ExpenseType, name="expense_type"), nullable=False
    )
    liters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # fuel-only
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="expenses")

    def __repr__(self) -> str:
        return f"<FuelExpense id={self.id} type={self.expense_type} cost={self.cost}>"
