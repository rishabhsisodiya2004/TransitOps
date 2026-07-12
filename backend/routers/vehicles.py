"""
TransitOps - Vehicles Router (CRUD)
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.database import get_db
from backend.security import get_current_user, require_roles

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.post(
    "/",
    response_model=schemas.VehicleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new vehicle",
)
def create_vehicle(
    payload: schemas.VehicleCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    existing = db.query(models.Vehicle).filter(
        models.Vehicle.registration_number == payload.registration_number
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Registration number '{payload.registration_number}' already exists.",
        )
    vehicle = models.Vehicle(**payload.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.get(
    "/",
    response_model=List[schemas.VehicleResponse],
    summary="List all vehicles (search / filter / sort)",
)
def list_vehicles(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[schemas.VehicleStatus] = None,
    type_filter: Optional[schemas.VehicleType] = Query(None, description="Filter by vehicle type"),
    region: Optional[str] = Query(None, description="Filter by operating region"),
    search: Optional[str] = Query(None, description="Match registration number / model (case-insensitive)"),
    sort_by: str = Query("registration_number", description="registration_number | odometer | acquisition_cost | status"),
    order: str = Query("asc", description="asc | desc"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.Vehicle)
    if status_filter:
        query = query.filter(models.Vehicle.status == status_filter)
    if type_filter:
        query = query.filter(models.Vehicle.type == type_filter)
    if region:
        query = query.filter(models.Vehicle.region == region)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            models.Vehicle.registration_number.ilike(pattern)
            | models.Vehicle.name_model.ilike(pattern)
        )

    sortable = {
        "registration_number": models.Vehicle.registration_number,
        "odometer": models.Vehicle.odometer,
        "acquisition_cost": models.Vehicle.acquisition_cost,
        "status": models.Vehicle.status,
    }
    sort_col = sortable.get(sort_by, models.Vehicle.registration_number)
    query = query.order_by(desc(sort_col) if order == "desc" else asc(sort_col))

    return query.offset(skip).limit(limit).all()


@router.get(
    "/{registration_number}",
    response_model=schemas.VehicleResponse,
    summary="Get a vehicle by registration",
)
def get_vehicle(
    registration_number: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = db.query(models.Vehicle).filter(
        models.Vehicle.registration_number == registration_number
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle


@router.patch(
    "/{registration_number}",
    response_model=schemas.VehicleResponse,
    summary="Update vehicle details",
)
def update_vehicle(
    payload: schemas.VehicleUpdate,
    registration_number: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    vehicle = db.query(models.Vehicle).filter(
        models.Vehicle.registration_number == registration_number
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)

    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.delete(
    "/{registration_number}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete (retire) a vehicle",
)
def delete_vehicle(
    registration_number: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    vehicle = db.query(models.Vehicle).filter(
        models.Vehicle.registration_number == registration_number
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    if vehicle.status == models.VehicleStatus.ON_TRIP:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a vehicle that is currently On Trip.",
        )

    db.delete(vehicle)
    db.commit()
    