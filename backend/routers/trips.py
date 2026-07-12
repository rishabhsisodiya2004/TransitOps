"""
TransitOps - Trips Router

Implements full CRUD plus the complex business-rule validations and
automatic status-transition triggers defined in the spec.

Business Rules Implemented
──────────────────────────
Validation 1 : Vehicle & Driver must not be Retired/In-Shop/Suspended/On-Trip
Validation 2 : Driver's license must not be expired
Validation 3 : cargo_weight ≤ vehicle.max_load_capacity

Trigger 1 : Draft → Dispatched  ⟹  Vehicle + Driver set to "On Trip"
Trigger 2 : → Completed / Cancelled  ⟹  Vehicle + Driver reverted to "Available"
             (odometer is advanced on Completed)
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.database import get_db
from backend.security import get_current_user

router = APIRouter(prefix="/trips", tags=["Trips"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Internal helpers — reusable validation functions
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_vehicle_or_404(vehicle_id: str, db: Session) -> models.Vehicle:
    vehicle = db.query(models.Vehicle).filter(
        models.Vehicle.registration_number == vehicle_id
    ).first()
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle '{vehicle_id}' not found.",
        )
    return vehicle


def _fetch_driver_or_404(driver_id: int, db: Session) -> models.Driver:
    driver = db.query(models.Driver).filter(models.Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Driver id={driver_id} not found.",
        )
    return driver


def _fetch_trip_or_404(trip_id: int, db: Session) -> models.Trip:
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trip id={trip_id} not found.",
        )
    return trip


def _validate_vehicle_available_for_trip(vehicle: models.Vehicle) -> None:
    """
    Validation 1 (Vehicle):
    The vehicle must be in 'Available' status.  Reject if it is
    Retired, In Shop, or already On Trip.
    """
    blocked = {
        models.VehicleStatus.RETIRED,
        models.VehicleStatus.IN_SHOP,
        models.VehicleStatus.ON_TRIP,
    }
    if vehicle.status in blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Vehicle '{vehicle.registration_number}' cannot be assigned to a trip. "
                f"Current status: '{vehicle.status.value}'. "
                "Vehicle must be 'Available'."
            ),
        )


def _validate_driver_available_for_trip(driver: models.Driver) -> None:
    """
    Validation 1 (Driver) + Validation 2 (License):
    - Driver must not be Suspended or already On Trip.
    - Driver's license must not be expired.
    """
    # Status check
    blocked = {models.DriverStatus.SUSPENDED, models.DriverStatus.ON_TRIP}
    if driver.status in blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Driver id={driver.id} ('{driver.name}') cannot be assigned to a trip. "
                f"Current status: '{driver.status.value}'. "
                "Driver must be 'Available' or 'Off Duty'."
            ),
        )

    # License expiry check
    if driver.license_expiry_date < date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Driver id={driver.id} ('{driver.name}') has an expired license "
                f"(expired: {driver.license_expiry_date}). "
                "Trip assignment blocked."
            ),
        )


def _validate_cargo_weight(cargo_weight: float, vehicle: models.Vehicle) -> None:
    """
    Validation 3:
    cargo_weight must not exceed the vehicle's max_load_capacity.
    """
    if cargo_weight > vehicle.max_load_capacity:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cargo weight {cargo_weight} kg exceeds vehicle "
                f"'{vehicle.registration_number}' max load capacity of "
                f"{vehicle.max_load_capacity} kg."
            ),
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Status-transition triggers
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_dispatch_trigger(trip: models.Trip, db: Session) -> None:
    """
    Trigger 1: Draft → Dispatched
    Set Vehicle and Driver status to 'On Trip'.
    Re-validates availability at dispatch time (not just at creation).
    """
    vehicle = _fetch_vehicle_or_404(trip.vehicle_id, db)
    driver = _fetch_driver_or_404(trip.driver_id, db)

    # Re-run validations at dispatch moment
    _validate_vehicle_available_for_trip(vehicle)
    _validate_driver_available_for_trip(driver)

    vehicle.status = models.VehicleStatus.ON_TRIP
    driver.status = models.DriverStatus.ON_TRIP


def _apply_completion_trigger(
    trip: models.Trip,
    final_odometer: float,
    fuel_consumed: float,
    db: Session,
) -> None:
    """
    Trigger 2a: → Completed
    - Advance the vehicle's odometer.
    - Revert Vehicle + Driver to 'Available'.
    """
    vehicle = _fetch_vehicle_or_404(trip.vehicle_id, db)
    driver = _fetch_driver_or_404(trip.driver_id, db)

    if final_odometer <= vehicle.odometer:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"final_odometer ({final_odometer} km) must be greater than "
                f"the vehicle's current odometer ({vehicle.odometer} km)."
            ),
        )

    vehicle.odometer = final_odometer
    vehicle.status = models.VehicleStatus.AVAILABLE
    driver.status = models.DriverStatus.AVAILABLE


def _apply_cancellation_trigger(trip: models.Trip, db: Session) -> None:
    """
    Trigger 2b: → Cancelled
    Only revert statuses if the trip was already Dispatched (On Trip).
    Draft cancellations do not change vehicle/driver status.
    """
    if trip.status == models.TripStatus.DISPATCHED:
        vehicle = _fetch_vehicle_or_404(trip.vehicle_id, db)
        driver = _fetch_driver_or_404(trip.driver_id, db)
        vehicle.status = models.VehicleStatus.AVAILABLE
        driver.status = models.DriverStatus.AVAILABLE


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/",
    response_model=schemas.TripResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new trip (Draft)",
)
def create_trip(
    payload: schemas.TripCreate,
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(get_current_user),
):
    """
    Creates a new trip in Draft status.
    Runs all three validations before persisting.
    """
    vehicle = _fetch_vehicle_or_404(payload.vehicle_id, db)
    driver = _fetch_driver_or_404(payload.driver_id, db)

    # ── All three mandatory validations ──────────────────────────────────────
    _validate_vehicle_available_for_trip(vehicle)
    _validate_driver_available_for_trip(driver)
    _validate_cargo_weight(payload.cargo_weight, vehicle)

    trip = models.Trip(
        source=payload.source,
        destination=payload.destination,
        vehicle_id=payload.vehicle_id,
        driver_id=payload.driver_id,
        cargo_weight=payload.cargo_weight,
        planned_distance=payload.planned_distance,
        revenue=payload.revenue,
        status=models.TripStatus.DRAFT,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


@router.get(
    "/",
    response_model=List[schemas.TripResponse],
    summary="List all trips (filter / search / sort)",
)
def list_trips(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[schemas.TripStatus] = None,
    vehicle_id: Optional[str] = Query(None, description="Filter by vehicle registration number"),
    driver_id: Optional[int] = Query(None, description="Filter by driver id"),
    search: Optional[str] = Query(None, description="Match source / destination (case-insensitive)"),
    sort_by: str = Query("created_at", description="created_at | planned_distance | cargo_weight | status"),
    order: str = Query("desc", description="asc | desc"),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Trip)
    if status_filter:
        query = query.filter(models.Trip.status == status_filter)
    if vehicle_id:
        query = query.filter(models.Trip.vehicle_id == vehicle_id)
    if driver_id:
        query = query.filter(models.Trip.driver_id == driver_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            models.Trip.source.ilike(pattern)
            | models.Trip.destination.ilike(pattern)
        )

    sortable = {
        "created_at": models.Trip.created_at,
        "planned_distance": models.Trip.planned_distance,
        "cargo_weight": models.Trip.cargo_weight,
        "status": models.Trip.status,
    }
    sort_col = sortable.get(sort_by, models.Trip.created_at)
    query = query.order_by(desc(sort_col) if order == "desc" else asc(sort_col))

    return query.offset(skip).limit(limit).all()


@router.get(
    "/{trip_id}",
    response_model=schemas.TripResponse,
    summary="Get a single trip",
)
def get_trip(
    trip_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(get_current_user),
):
    return _fetch_trip_or_404(trip_id, db)


@router.patch(
    "/{trip_id}",
    response_model=schemas.TripResponse,
    summary="Update trip details (Draft only)",
)
def update_trip(
    payload: schemas.TripUpdate,
    trip_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(get_current_user),
):
    """
    General-purpose field update. Only allowed while trip is in Draft.
    For status changes, use the dedicated PATCH /{trip_id}/status endpoint.
    """
    trip = _fetch_trip_or_404(trip_id, db)

    if trip.status != models.TripStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Trip is in '{trip.status.value}' status and cannot be edited. Only Draft trips can be modified.",
        )

    update_data = payload.model_dump(exclude_unset=True)

    # If cargo_weight is changing, re-validate against vehicle capacity
    new_cargo = update_data.get("cargo_weight", trip.cargo_weight)
    if "cargo_weight" in update_data:
        vehicle = _fetch_vehicle_or_404(trip.vehicle_id, db)
        _validate_cargo_weight(new_cargo, vehicle)

    for field, value in update_data.items():
        setattr(trip, field, value)

    db.commit()
    db.refresh(trip)
    return trip


@router.patch(
    "/{trip_id}/status",
    response_model=schemas.TripResponse,
    summary="Transition trip status (with automatic triggers)",
)
def update_trip_status(
    payload: schemas.TripStatusUpdate,
    trip_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(get_current_user),
):
    """
    Handles all status transitions for a trip.

    Allowed transitions
    ───────────────────
    Draft       → Dispatched  (Trigger 1: mark vehicle + driver On Trip)
    Draft       → Cancelled
    Dispatched  → Completed   (Trigger 2a: advance odometer, revert statuses)
    Dispatched  → Cancelled   (Trigger 2b: revert statuses)

    All other transitions are rejected.
    """
    trip = _fetch_trip_or_404(trip_id, db)
    current = trip.status
    new = payload.status

    # ── Guard: validate allowed transitions ──────────────────────────────────
    ALLOWED_TRANSITIONS = {
        models.TripStatus.DRAFT: {
            models.TripStatus.DISPATCHED,
            models.TripStatus.CANCELLED,
        },
        models.TripStatus.DISPATCHED: {
            models.TripStatus.COMPLETED,
            models.TripStatus.CANCELLED,
        },
    }

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot transition trip from '{current.value}' to '{new.value}'. "
                f"Allowed transitions from '{current.value}': "
                f"{[s.value for s in allowed] or 'none'}."
            ),
        )

    # ── Trigger 1: Draft → Dispatched ────────────────────────────────────────
    if current == models.TripStatus.DRAFT and new == models.TripStatus.DISPATCHED:
        _apply_dispatch_trigger(trip, db)

    # ── Trigger 2a: Dispatched → Completed ───────────────────────────────────
    elif current == models.TripStatus.DISPATCHED and new == models.TripStatus.COMPLETED:
        _apply_completion_trigger(
            trip,
            payload.final_odometer,
            payload.fuel_consumed,
            db,
        )
        trip.final_odometer = payload.final_odometer
        trip.fuel_consumed = payload.fuel_consumed

    # ── Trigger 2b: Any → Cancelled ──────────────────────────────────────────
    elif new == models.TripStatus.CANCELLED:
        _apply_cancellation_trigger(trip, db)

    trip.status = new
    db.commit()
    db.refresh(trip)
    return trip


@router.delete(
    "/{trip_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a trip (Draft only)",
)
def delete_trip(
    trip_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(get_current_user),
):
    trip = _fetch_trip_or_404(trip_id, db)
    if trip.status != models.TripStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only Draft trips can be deleted. Cancel the trip first.",
        )
    db.delete(trip)
    db.commit()
