"""
TransitOps - Maintenance Router

Implements CRUD for MaintenanceLog with the vehicle status triggers:

Trigger 3a: Creating an Active maintenance log  ⟹  Vehicle status → 'In Shop'
            (Blocked if vehicle is Retired or currently On Trip)
Trigger 3b: Closing a maintenance log           ⟹  Vehicle status → 'Available'
            (Skipped if vehicle is Retired — Retired vehicles stay Retired)
"""

from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.database import get_db
from backend.security import get_current_user, require_roles

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
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


def _fetch_log_or_404(log_id: int, db: Session) -> models.MaintenanceLog:
    log = db.query(models.MaintenanceLog).filter(
        models.MaintenanceLog.id == log_id
    ).first()
    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MaintenanceLog id={log_id} not found.",
        )
    return log


def _apply_maintenance_open_trigger(vehicle: models.Vehicle) -> None:
    """
    Trigger 3a: New Active maintenance log created.
    """
    if vehicle.status == models.VehicleStatus.RETIRED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Vehicle '{vehicle.registration_number}' is Retired. "
                "Cannot create a maintenance log for a retired vehicle."
            ),
        )

    if vehicle.status == models.VehicleStatus.ON_TRIP:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Vehicle '{vehicle.registration_number}' is currently On Trip. "
                "Complete or cancel the active trip before scheduling maintenance."
            ),
        )

    vehicle.status = models.VehicleStatus.IN_SHOP


def _apply_maintenance_close_trigger(vehicle: models.Vehicle, db: Session) -> None:
    """
    Trigger 3b: Maintenance log closed.
    """
    if vehicle.status == models.VehicleStatus.RETIRED:
        return

    remaining_active = (
        db.query(models.MaintenanceLog)
        .filter(
            models.MaintenanceLog.vehicle_id == vehicle.registration_number,
            models.MaintenanceLog.status == models.MaintenanceStatus.ACTIVE,
        )
        .count()
    )

    if remaining_active == 0:
        vehicle.status = models.VehicleStatus.AVAILABLE


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/",
    response_model=schemas.MaintenanceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a maintenance log",
)
def create_maintenance_log(
    payload: schemas.MaintenanceCreate,
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    vehicle = _fetch_vehicle_or_404(payload.vehicle_id, db)

    log = models.MaintenanceLog(
        vehicle_id=payload.vehicle_id,
        description=payload.description,
        cost=payload.cost,
        date=payload.date,
        status=payload.status,
    )

    if payload.status == models.MaintenanceStatus.ACTIVE:
        _apply_maintenance_open_trigger(vehicle)

    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.get(
    "/",
    response_model=List[schemas.MaintenanceResponse],
    summary="List all maintenance logs",
)
def list_maintenance_logs(
    skip: int = 0,
    limit: int = 100,
    vehicle_id: str = None,
    status_filter: schemas.MaintenanceStatus = None,
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.MaintenanceLog)

    if vehicle_id:
        query = query.filter(models.MaintenanceLog.vehicle_id == vehicle_id)

    if status_filter:
        query = query.filter(models.MaintenanceLog.status == status_filter)

    return query.offset(skip).limit(limit).all()


@router.get(
    "/{log_id}",
    response_model=schemas.MaintenanceResponse,
    summary="Get a single maintenance log",
)
def get_maintenance_log(
    log_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(get_current_user),
):
    return _fetch_log_or_404(log_id, db)


@router.patch(
    "/{log_id}",
    response_model=schemas.MaintenanceResponse,
    summary="Update a maintenance log (triggers Trigger 3b on close)",
)
def update_maintenance_log(
    payload: schemas.MaintenanceUpdate,
    log_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    log = _fetch_log_or_404(log_id, db)
    old_status = log.status
    update_data = payload.model_dump(exclude_unset=True)

    new_status = update_data.get("status", old_status)

    for field, value in update_data.items():
        if field != "status":
            setattr(log, field, value)

    if new_status != old_status:
        vehicle = _fetch_vehicle_or_404(log.vehicle_id, db)

        if (
            old_status == models.MaintenanceStatus.ACTIVE
            and new_status == models.MaintenanceStatus.CLOSED
        ):
            log.status = models.MaintenanceStatus.CLOSED
            db.flush()
            _apply_maintenance_close_trigger(vehicle, db)

        elif (
            old_status == models.MaintenanceStatus.CLOSED
            and new_status == models.MaintenanceStatus.ACTIVE
        ):
            _apply_maintenance_open_trigger(vehicle)
            log.status = models.MaintenanceStatus.ACTIVE

        else:
            log.status = new_status

    db.commit()
    db.refresh(log)
    return log


@router.delete(
    "/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a maintenance log",
)
def delete_maintenance_log(
    log_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    log = _fetch_log_or_404(log_id, db)

    if log.status == models.MaintenanceStatus.ACTIVE:
        vehicle = _fetch_vehicle_or_404(log.vehicle_id, db)
        log.status = models.MaintenanceStatus.CLOSED
        db.flush()
        _apply_maintenance_close_trigger(vehicle, db)

    db.delete(log)
    db.commit()
    return 