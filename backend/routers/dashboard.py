"""
TransitOps - Dashboard & Analytics Router

GET /dashboard/kpis     — Real-time fleet KPI aggregations
GET /reports/analytics  — Fuel efficiency, operational cost, and vehicle ROI
"""

import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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
    vehicle_type: Optional[models.VehicleType] = Query(None, description="Filter by vehicle type"),
    status: Optional[models.VehicleStatus] = Query(None, description="Filter by vehicle status"),
    region: Optional[str] = Query(None, description="Filter by operating region"),
    _: models.User = Depends(get_current_user),
) -> schemas.DashboardKPIs:
    """
    Aggregates fleet-wide KPIs in a single round-trip using SQLAlchemy's
    conditional aggregation (CASE WHEN … THEN 1 ELSE 0 END counts).

    Optional filters (vehicle_type / status / region) scope every KPI to the
    matching subset of the fleet — including the trips and drivers attached to
    those vehicles.
    """
    # ── Apply optional filters to the vehicle set ────────────────────────────
    def _apply_vehicle_filters(q):
        if vehicle_type is not None:
            q = q.filter(models.Vehicle.type == vehicle_type)
        if status is not None:
            q = q.filter(models.Vehicle.status == status)
        if region is not None:
            q = q.filter(models.Vehicle.region == region)
        return q

    filters_active = any(v is not None for v in (vehicle_type, status, region))

    # Registration numbers in scope — used to constrain trip/driver KPIs.
    scoped_reg_query = _apply_vehicle_filters(
        db.query(models.Vehicle.registration_number)
    )
    scoped_regs = [r[0] for r in scoped_reg_query.all()]

    # ── Vehicle aggregations ─────────────────────────────────────────────────
    v_stats = _apply_vehicle_filters(db.query(
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
    )).one()

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
    # When a vehicle filter is active, "drivers" is scoped to those currently
    # driving one of the in-scope vehicles (via a Dispatched trip). Without
    # filters, all drivers are counted.
    d_query = db.query(
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
    )
    if filters_active:
        driver_ids_in_scope = (
            db.query(models.Trip.driver_id)
            .filter(
                models.Trip.vehicle_id.in_(scoped_regs or [None]),
                models.Trip.status == models.TripStatus.DISPATCHED,
            )
            .distinct()
        )
        d_query = d_query.filter(models.Driver.id.in_(driver_ids_in_scope))
    d_stats = d_query.one()

    total_drivers     = d_stats.total or 0
    available_drivers = int(d_stats.available or 0)
    drivers_on_trip   = int(d_stats.on_trip or 0)
    suspended_drivers = int(d_stats.suspended or 0)

    # ── Trip aggregations ────────────────────────────────────────────────────
    t_query = db.query(
        func.count(models.Trip.id).label("total"),
        func.sum(
            case((models.Trip.status == models.TripStatus.DISPATCHED, 1), else_=0)
        ).label("active"),
        func.sum(
            case((models.Trip.status == models.TripStatus.DRAFT, 1), else_=0)
        ).label("pending"),
        func.sum(
            case((models.Trip.status == models.TripStatus.COMPLETED, 1), else_=0)
        ).label("completed"),
        func.sum(
            case((models.Trip.status == models.TripStatus.CANCELLED, 1), else_=0)
        ).label("cancelled"),
    )
    if filters_active:
        t_query = t_query.filter(models.Trip.vehicle_id.in_(scoped_regs or [None]))
    t_stats = t_query.one()

    total_trips     = t_stats.total or 0
    active_trips    = int(t_stats.active or 0)
    pending_trips   = int(t_stats.pending or 0)
    completed_trips = int(t_stats.completed or 0)
    cancelled_trips = int(t_stats.cancelled or 0)

    # ── Maintenance aggregations ─────────────────────────────────────────────
    m_query = db.query(
        func.count(models.MaintenanceLog.id).label("total"),
        func.sum(
            case((models.MaintenanceLog.status == models.MaintenanceStatus.ACTIVE, 1), else_=0)
        ).label("open"),
    )
    if filters_active:
        m_query = m_query.filter(models.MaintenanceLog.vehicle_id.in_(scoped_regs or [None]))
    m_stats = m_query.one()

    total_maintenance = m_stats.total or 0
    open_maintenance  = int(m_stats.open or 0)

    # ── Expense total ────────────────────────────────────────────────────────
    e_query = db.query(func.coalesce(func.sum(models.FuelExpense.cost), 0.0))
    if filters_active:
        e_query = e_query.filter(models.FuelExpense.vehicle_id.in_(scoped_regs or [None]))
    total_expenses = float(e_query.scalar())

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
        pending_trips=pending_trips,
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
    region: Optional[str] = Query(None, description="Filter analytics by operating region"),
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
    vehicles_query = db.query(models.Vehicle)
    if region is not None:
        vehicles_query = vehicles_query.filter(models.Vehicle.region == region)
    vehicles = vehicles_query.all()
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
                region=vehicle.region,
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

    # Fleet ROI: total acquisition cost over the (optionally region-filtered) set
    fleet_acquisition = float(sum(v.acquisition_cost for v in vehicles))

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


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /reports/analytics.csv  — CSV export (spec §3.8)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/reports/analytics.csv",
    summary="Export the per-vehicle analytics report as CSV",
    response_class=StreamingResponse,
)
def export_fleet_analytics_csv(
    db: Session = Depends(get_db),
    region: Optional[str] = Query(None, description="Filter analytics by operating region"),
    _: models.User = Depends(get_current_user),
):
    """
    Streams the same per-vehicle analytics table produced by
    GET /reports/analytics as a downloadable CSV file.
    """
    report = get_fleet_analytics(db=db, region=region, _=_)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Registration Number",
        "Vehicle",
        "Region",
        "Acquisition Cost",
        "Total Distance (km)",
        "Total Fuel (L)",
        "Fuel Efficiency (km/L)",
        "Total Fuel Cost",
        "Total Maintenance Cost",
        "Total Operational Cost",
        "Total Revenue",
        "ROI (%)",
    ])
    for v in report.vehicles:
        writer.writerow([
            v.registration_number,
            v.name_model,
            v.region or "",
            v.acquisition_cost,
            v.total_distance_km,
            v.total_fuel_liters,
            "" if v.fuel_efficiency_km_per_liter is None else v.fuel_efficiency_km_per_liter,
            v.total_fuel_cost,
            v.total_maintenance_cost,
            v.total_operational_cost,
            v.total_revenue,
            "" if v.roi_pct is None else v.roi_pct,
        ])

    # Fleet summary row
    writer.writerow([])
    writer.writerow([
        "FLEET TOTAL", "", "", "", "", "",
        "" if report.fleet_fuel_efficiency_km_per_liter is None
        else report.fleet_fuel_efficiency_km_per_liter,
        "", "",
        report.fleet_total_operational_cost,
        report.fleet_total_revenue,
        "" if report.fleet_roi_pct is None else report.fleet_roi_pct,
    ])

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fleet_analytics.csv"},
    )
