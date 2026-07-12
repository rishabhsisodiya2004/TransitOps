"""
TransitOps - Dashboard & Analytics Router

GET /dashboard/kpis     — Real-time fleet KPI aggregations
GET /reports/analytics  — Fuel efficiency, operational cost, and vehicle ROI
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.database import get_db
from backend.security import get_current_user

router = APIRouter(tags=["Dashboard & Analytics"])


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /dashboard/kpis
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/dashboard/kpis",
    response_model=schemas.DashboardKPIs,
    summary="Real-time fleet KPI dashboard",
)
def get_dashboard_kpis(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
) -> schemas.DashboardKPIs:
    """
    Aggregates fleet-wide KPIs in a single round-trip using SQLAlchemy's
    conditional aggregation (CASE WHEN … THEN 1 ELSE 0 END counts).
    """
    # ── Vehicle aggregations ─────────────────────────────────────────────────
    v_stats = db.query(
        func.count(models.Vehicle.registration_number).label("total"),
        func.sum(
            case(
                (models.Vehicle.status != models.VehicleStatus.RETIRED, 1),
                else_=0,
            )
        ).label("active"),
        func.sum(
            case((models.Vehicle.status == models.VehicleStatus.AVAILABLE, 1), else_=0)
        ).label("available"),
        func.sum(
            case((models.Vehicle.status == models.VehicleStatus.ON_TRIP, 1), else_=0)
        ).label("on_trip"),
        func.sum(
            case((models.Vehicle.status == models.VehicleStatus.IN_SHOP, 1), else_=0)
        ).label("in_shop"),
        func.sum(
            case((models.Vehicle.status == models.VehicleStatus.RETIRED, 1), else_=0)
        ).label("retired"),
    ).one()

    total_vehicles    = v_stats.total or 0
    active_vehicles   = int(v_stats.active or 0)
    available_vehicles = int(v_stats.available or 0)
    vehicles_on_trip  = int(v_stats.on_trip or 0)
    vehicles_in_shop  = int(v_stats.in_shop or 0)
    retired_vehicles  = int(v_stats.retired or 0)

    fleet_utilization = (
        round((vehicles_on_trip / active_vehicles) * 100, 2) if active_vehicles else 0.0
    )

    # ── Driver aggregations ──────────────────────────────────────────────────
    d_stats = db.query(
        func.count(models.Driver.id).label("total"),
        func.sum(
            case((models.Driver.status == models.DriverStatus.AVAILABLE, 1), else_=0)
        ).label("available"),
        func.sum(
            case((models.Driver.status == models.DriverStatus.ON_TRIP, 1), else_=0)
        ).label("on_trip"),
        func.sum(
            case((models.Driver.status == models.DriverStatus.SUSPENDED, 1), else_=0)
        ).label("suspended"),
    ).one()

    total_drivers     = d_stats.total or 0
    available_drivers = int(d_stats.available or 0)
    drivers_on_trip   = int(d_stats.on_trip or 0)
    suspended_drivers = int(d_stats.suspended or 0)

    # ── Trip aggregations ────────────────────────────────────────────────────
    t_stats = db.query(
        func.count(models.Trip.id).label("total"),
        func.sum(
            case((models.Trip.status == models.TripStatus.DISPATCHED, 1), else_=0)
        ).label("active"),
        func.sum(
            case((models.Trip.status == models.TripStatus.COMPLETED, 1), else_=0)
        ).label("completed"),
        func.sum(
            case((models.Trip.status == models.TripStatus.CANCELLED, 1), else_=0)
        ).label("cancelled"),
    ).one()

    total_trips     = t_stats.total or 0
    active_trips    = int(t_stats.active or 0)
    completed_trips = int(t_stats.completed or 0)
    cancelled_trips = int(t_stats.cancelled or 0)

    # ── Maintenance aggregations ─────────────────────────────────────────────
    m_stats = db.query(
        func.count(models.MaintenanceLog.id).label("total"),
        func.sum(
            case((models.MaintenanceLog.status == models.MaintenanceStatus.ACTIVE, 1), else_=0)
        ).label("open"),
    ).one()

    total_maintenance = m_stats.total or 0
    open_maintenance  = int(m_stats.open or 0)

    # ── Expense total ────────────────────────────────────────────────────────
    total_expenses_result = db.query(func.coalesce(func.sum(models.FuelExpense.cost), 0.0)).scalar()
    total_expenses = float(total_expenses_result)

    return schemas.DashboardKPIs(
        total_vehicles=total_vehicles,
        active_vehicles=active_vehicles,
        available_vehicles=available_vehicles,
        vehicles_on_trip=vehicles_on_trip,
        vehicles_in_shop=vehicles_in_shop,
        retired_vehicles=retired_vehicles,
        fleet_utilization_pct=fleet_utilization,
        total_drivers=total_drivers,
        available_drivers=available_drivers,
        drivers_on_trip=drivers_on_trip,
        suspended_drivers=suspended_drivers,
        total_trips=total_trips,
        active_trips=active_trips,
        completed_trips=completed_trips,
        cancelled_trips=cancelled_trips,
        total_maintenance_logs=total_maintenance,
        open_maintenance_logs=open_maintenance,
        total_expenses=total_expenses,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /reports/analytics
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/reports/analytics",
    response_model=schemas.FleetAnalyticsReport,
    summary="Per-vehicle fuel efficiency, operational cost & ROI report",
)
def get_fleet_analytics(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
) -> schemas.FleetAnalyticsReport:
    """
    Calculates for each vehicle:

    1. Fuel Efficiency  = Total distance driven (km) / Total fuel consumed (L)
                         (using planned_distance of completed trips as proxy)

    2. Operational Cost = Total fuel expense cost + Total maintenance cost

    3. ROI (%)          = (Total Revenue − Operational Cost) / Acquisition Cost × 100

    Fleet-level aggregates are also computed.
    """
    vehicles = db.query(models.Vehicle).all()
    vehicle_analytics: list[schemas.VehicleAnalytics] = []

    fleet_total_distance   = 0.0
    fleet_total_fuel_liters = 0.0
    fleet_total_fuel_cost  = 0.0
    fleet_total_maint_cost = 0.0
    fleet_total_revenue    = 0.0

    for vehicle in vehicles:
        reg = vehicle.registration_number

        # ── Distance: sum planned_distance of COMPLETED trips ────────────────
        distance_result = (
            db.query(func.coalesce(func.sum(models.Trip.planned_distance), 0.0))
            .filter(
                models.Trip.vehicle_id == reg,
                models.Trip.status == models.TripStatus.COMPLETED,
            )
            .scalar()
        )
        total_distance = float(distance_result)

        # ── Fuel: sum liters from FuelExpense (type=Fuel) ────────────────────
        fuel_liters_result = (
            db.query(func.coalesce(func.sum(models.FuelExpense.liters), 0.0))
            .filter(
                models.FuelExpense.vehicle_id == reg,
                models.FuelExpense.expense_type == models.ExpenseType.FUEL,
            )
            .scalar()
        )
        total_fuel_liters = float(fuel_liters_result)

        # Also use fuel_consumed from completed trips (more accurate)
        trip_fuel_result = (
            db.query(func.coalesce(func.sum(models.Trip.fuel_consumed), 0.0))
            .filter(
                models.Trip.vehicle_id == reg,
                models.Trip.status == models.TripStatus.COMPLETED,
                models.Trip.fuel_consumed.isnot(None),
            )
            .scalar()
        )
        trip_fuel_liters = float(trip_fuel_result)

        # Prefer trip-recorded fuel if available, else use expense records
        effective_fuel = trip_fuel_liters if trip_fuel_liters > 0 else total_fuel_liters

        # ── Fuel efficiency ──────────────────────────────────────────────────
        fuel_efficiency: Optional[float] = (
            round(total_distance / effective_fuel, 2) if effective_fuel > 0 else None
        )

        # ── Fuel cost ────────────────────────────────────────────────────────
        fuel_cost_result = (
            db.query(func.coalesce(func.sum(models.FuelExpense.cost), 0.0))
            .filter(
                models.FuelExpense.vehicle_id == reg,
                models.FuelExpense.expense_type == models.ExpenseType.FUEL,
            )
            .scalar()
        )
        total_fuel_cost = float(fuel_cost_result)

        # ── Maintenance cost ─────────────────────────────────────────────────
        maint_cost_result = (
            db.query(func.coalesce(func.sum(models.MaintenanceLog.cost), 0.0))
            .filter(models.MaintenanceLog.vehicle_id == reg)
            .scalar()
        )
        total_maintenance_cost = float(maint_cost_result)

        # Also include maintenance-type expenses
        maint_expense_result = (
            db.query(func.coalesce(func.sum(models.FuelExpense.cost), 0.0))
            .filter(
                models.FuelExpense.vehicle_id == reg,
                models.FuelExpense.expense_type == models.ExpenseType.MAINTENANCE,
            )
            .scalar()
        )
        total_maintenance_cost += float(maint_expense_result)

        total_operational_cost = total_fuel_cost + total_maintenance_cost

        # ── Revenue: sum revenue from COMPLETED trips ────────────────────────
        revenue_result = (
            db.query(func.coalesce(func.sum(models.Trip.revenue), 0.0))
            .filter(
                models.Trip.vehicle_id == reg,
                models.Trip.status == models.TripStatus.COMPLETED,
                models.Trip.revenue.isnot(None),
            )
            .scalar()
        )
        total_revenue = float(revenue_result)

        # ── ROI ─────────────────────────────────────────────────────────────
        # ROI = (Revenue − (Maintenance + Fuel)) / Acquisition Cost × 100
        roi: Optional[float] = None
        if vehicle.acquisition_cost > 0:
            roi = round(
                ((total_revenue - total_operational_cost) / vehicle.acquisition_cost) * 100, 2
            )

        # ── Accumulate fleet totals ──────────────────────────────────────────
        fleet_total_distance    += total_distance
        fleet_total_fuel_liters += effective_fuel
        fleet_total_fuel_cost   += total_fuel_cost
        fleet_total_maint_cost  += total_maintenance_cost
        fleet_total_revenue     += total_revenue

        vehicle_analytics.append(
            schemas.VehicleAnalytics(
                registration_number=reg,
                name_model=vehicle.name_model,
                acquisition_cost=vehicle.acquisition_cost,
                total_distance_km=round(total_distance, 2),
                total_fuel_liters=round(effective_fuel, 2),
                fuel_efficiency_km_per_liter=fuel_efficiency,
                total_fuel_cost=round(total_fuel_cost, 2),
                total_maintenance_cost=round(total_maintenance_cost, 2),
                total_operational_cost=round(total_operational_cost, 2),
                total_revenue=round(total_revenue, 2),
                roi_pct=roi,
            )
        )

    # ── Fleet-level aggregates ────────────────────────────────────────────────
    fleet_fuel_efficiency: Optional[float] = (
        round(fleet_total_distance / fleet_total_fuel_liters, 2)
        if fleet_total_fuel_liters > 0
        else None
    )
    fleet_total_operational = round(fleet_total_fuel_cost + fleet_total_maint_cost, 2)

    # Fleet ROI: total acquisition cost
    fleet_acquisition = db.query(
        func.coalesce(func.sum(models.Vehicle.acquisition_cost), 0.0)
    ).scalar()
    fleet_acquisition = float(fleet_acquisition)

    fleet_roi: Optional[float] = (
        round(
            ((fleet_total_revenue - fleet_total_operational) / fleet_acquisition) * 100, 2
        )
        if fleet_acquisition > 0
        else None
    )

    return schemas.FleetAnalyticsReport(
        generated_at=datetime.now(timezone.utc),
        fleet_fuel_efficiency_km_per_liter=fleet_fuel_efficiency,
        fleet_total_operational_cost=fleet_total_operational,
        fleet_total_revenue=round(fleet_total_revenue, 2),
        fleet_roi_pct=fleet_roi,
        vehicles=vehicle_analytics,
    )
