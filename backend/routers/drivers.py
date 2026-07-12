"""
TransitOps - Drivers Router (CRUD)
"""

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import asc, desc
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
    summary="List all drivers (search / filter / sort)",
)
def list_drivers(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[schemas.DriverStatus] = None,
    search: Optional[str] = Query(None, description="Match name / license number (case-insensitive)"),
    sort_by: str = Query("name", description="name | safety_score | license_expiry_date | status"),
    order: str = Query("asc", description="asc | desc"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.Driver)

    if status_filter:
        query = query.filter(models.Driver.status == status_filter)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            models.Driver.name.ilike(pattern)
            | models.Driver.license_number.ilike(pattern)
        )

    sortable = {
        "name": models.Driver.name,
        "safety_score": models.Driver.safety_score,
        "license_expiry_date": models.Driver.license_expiry_date,
        "status": models.Driver.status,
    }
    sort_col = sortable.get(sort_by, models.Driver.name)
    query = query.order_by(desc(sort_col) if order == "desc" else asc(sort_col))

    return query.offset(skip).limit(limit).all()


@router.get(
    "/license-reminders",
    response_model=List[schemas.LicenseReminder],
    summary="Drivers with expired or soon-to-expire licenses (Safety Officer)",
)
def license_reminders(
    within_days: int = Query(
        30, ge=0, le=365,
        description="Include licenses expiring within this many days (plus already-expired).",
    ),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """
    Returns every driver whose license has already expired or expires within
    `within_days` days, sorted soonest-first. Backs the 'email reminders for
    expiring licenses' workflow — a scheduler/mailer can poll this endpoint.
    """
    today = date.today()
    cutoff = today + timedelta(days=within_days)

    drivers = (
        db.query(models.Driver)
        .filter(models.Driver.license_expiry_date <= cutoff)
        .order_by(asc(models.Driver.license_expiry_date))
        .all()
    )

    return [
        schemas.LicenseReminder(
            id=d.id,
            name=d.name,
            license_number=d.license_number,
            license_category=d.license_category,
            license_expiry_date=d.license_expiry_date,
            contact_number=d.contact_number,
            status=d.status,
            days_until_expiry=(d.license_expiry_date - today).days,
            is_expired=d.license_expiry_date < today,
        )
        for d in drivers
    ]


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