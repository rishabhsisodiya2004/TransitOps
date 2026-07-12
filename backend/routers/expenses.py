"""
TransitOps - Fuel & Expenses Router (CRUD)
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.database import get_db
from backend.security import get_current_user, require_roles

router = APIRouter(prefix="/expenses", tags=["Fuel & Expenses"])


@router.post(
    "/",
    response_model=schemas.ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a fuel fill or vehicle expense",
)
def create_expense(
    payload: schemas.ExpenseCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(
            models.UserRole.FLEET_MANAGER,
            models.UserRole.FINANCIAL_ANALYST,
        )
    ),
):
    # Ensure vehicle exists
    vehicle = db.query(models.Vehicle).filter(
        models.Vehicle.registration_number == payload.vehicle_id
    ).first()

    if not vehicle:
        raise HTTPException(
            status_code=404,
            detail=f"Vehicle '{payload.vehicle_id}' not found."
        )

    expense = models.FuelExpense(**payload.model_dump())

    db.add(expense)
    db.commit()
    db.refresh(expense)

    return expense


@router.get(
    "/",
    response_model=List[schemas.ExpenseResponse],
    summary="List all expenses",
)
def list_expenses(
    skip: int = 0,
    limit: int = 100,
    vehicle_id: str = None,
    expense_type: schemas.ExpenseType = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.FuelExpense)

    if vehicle_id:
        query = query.filter(
            models.FuelExpense.vehicle_id == vehicle_id
        )

    if expense_type:
        query = query.filter(
            models.FuelExpense.expense_type == expense_type
        )

    return query.offset(skip).limit(limit).all()


@router.get(
    "/{expense_id}",
    response_model=schemas.ExpenseResponse,
    summary="Get an expense",
)
def get_expense(
    expense_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    expense = db.query(models.FuelExpense).filter(
        models.FuelExpense.id == expense_id
    ).first()

    if not expense:
        raise HTTPException(
            status_code=404,
            detail="Expense not found."
        )

    return expense


@router.patch(
    "/{expense_id}",
    response_model=schemas.ExpenseResponse,
    summary="Update an expense record",
)
def update_expense(
    payload: schemas.ExpenseUpdate,
    expense_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(
            models.UserRole.FLEET_MANAGER,
            models.UserRole.FINANCIAL_ANALYST,
        )
    ),
):
    expense = db.query(models.FuelExpense).filter(
        models.FuelExpense.id == expense_id
    ).first()

    if not expense:
        raise HTTPException(
            status_code=404,
            detail="Expense not found."
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(expense, field, value)

    db.commit()
    db.refresh(expense)

    return expense


@router.delete(
    "/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an expense",
)
def delete_expense(
    expense_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: models.User = Depends(
        require_roles(
            models.UserRole.FLEET_MANAGER,
            models.UserRole.FINANCIAL_ANALYST,
        )
    ),
):
    expense = db.query(models.FuelExpense).filter(
        models.FuelExpense.id == expense_id
    ).first()

    if not expense:
        raise HTTPException(
            status_code=404,
            detail="Expense not found."
        )

    db.delete(expense)
    db.commit()