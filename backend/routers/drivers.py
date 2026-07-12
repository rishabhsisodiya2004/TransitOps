"""
TransitOps - Drivers Router (CRUD)
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.database import get_db
from backend.security import get_current_user, require_roles

router = APIRouter(prefix="/drivers", tags=["Drivers"])


@router.post(
    "/",
    response_model=schemas.DriverResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new driver",
)
def create_driver(
    payload: schemas.DriverCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    existing = db.query(models.Driver).filter(
        models.Driver.license_number == payload.license_number
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"License number '{payload.license_number}' is already registered.",
        )

    driver = models.Driver(**payload.model_dump())

    db.add(driver)
    db.commit()
    db.refresh(driver)

    return driver


@router.get(
    "/",
    response_model=List[schemas.DriverResponse],
    summary="List all drivers",
)
def list_drivers(
    skip: int = 0,
    limit: int = 100,
    status_filter: schemas.DriverStatus = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.Driver)

    if status_filter:
        query = query.filter(models.Driver.status == status_filter)

    return query.offset(skip).limit(limit).all()


@router.get(
    "/{driver_id}",
    response_model=schemas.DriverResponse,
    summary="Get a driver",
)
def get_driver(
    driver_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    driver = db.query(models.Driver).filter(
        models.Driver.id == driver_id
    ).first()

    if not driver:
        raise HTTPException(
            status_code=404,
            detail="Driver not found."
        )

    return driver


@router.patch(
    "/{driver_id}",
    response_model=schemas.DriverResponse,
    summary="Update a driver",
)
def update_driver(
    payload: schemas.DriverUpdate,
    driver_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    driver = db.query(models.Driver).filter(
        models.Driver.id == driver_id
    ).first()

    if not driver:
        raise HTTPException(
            status_code=404,
            detail="Driver not found."
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(driver, field, value)

    db.commit()
    db.refresh(driver)

    return driver


@router.delete(
    "/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a driver",
)
def delete_driver(
    driver_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(models.UserRole.FLEET_MANAGER)
    ),
):
    driver = db.query(models.Driver).filter(
        models.Driver.id == driver_id
    ).first()

    if not driver:
        raise HTTPException(
            status_code=404,
            detail="Driver not found."
        )

    if driver.status == models.DriverStatus.ON_TRIP:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a driver who is currently On Trip.",
        )

    db.delete(driver)
    db.commit()