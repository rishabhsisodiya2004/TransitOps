"""
TransitOps - Seed Script

Populates the database with realistic demo data for hackathon demonstrations.
Run once: python seed.py
"""

from datetime import date, timedelta

from backend.database import SessionLocal, Base, engine
from backend import models
from backend.security import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()


def seed():
    # ── Users ────────────────────────────────────────────────────────────────
    users = [
        models.User(
            email="manager@transitops.io",
            password_hash=hash_password("Manager@123"),
            full_name="Alex Fleet",
            role=models.UserRole.FLEET_MANAGER,
        ),
        models.User(
            email="safety@transitops.io",
            password_hash=hash_password("Safety@123"),
            full_name="Sam Shield",
            role=models.UserRole.SAFETY_OFFICER,
        ),
        models.User(
            email="finance@transitops.io",
            password_hash=hash_password("Finance@123"),
            full_name="Fiona Books",
            role=models.UserRole.FINANCIAL_ANALYST,
        ),
    ]
    db.add_all(users)
    db.flush()

    # ── Vehicles ─────────────────────────────────────────────────────────────
    vehicles = [
        models.Vehicle(
            registration_number="TN01AB1234",
            name_model="Tata LPT 1615",
            type=models.VehicleType.TRUCK,
            region="South",
            max_load_capacity=16000.0,
            odometer=45200.0,
            acquisition_cost=2800000.0,
            status=models.VehicleStatus.AVAILABLE,
        ),
        models.Vehicle(
            registration_number="MH04CD5678",
            name_model="Ashok Leyland BOSS",
            type=models.VehicleType.TRUCK,
            region="West",
            max_load_capacity=12000.0,
            odometer=88000.0,
            acquisition_cost=2200000.0,
            status=models.VehicleStatus.AVAILABLE,
        ),
        models.Vehicle(
            registration_number="KA05EF9012",
            name_model="Mahindra Supro Van",
            type=models.VehicleType.VAN,
            region="South",
            max_load_capacity=750.0,
            odometer=32000.0,
            acquisition_cost=650000.0,
            status=models.VehicleStatus.AVAILABLE,
        ),
        models.Vehicle(
            registration_number="DL08GH3456",
            name_model="Eicher Pro 2049",
            type=models.VehicleType.TRUCK,
            region="North",
            max_load_capacity=5000.0,
            odometer=121000.0,
            acquisition_cost=1500000.0,
            status=models.VehicleStatus.IN_SHOP,
        ),
    ]
    db.add_all(vehicles)
    db.flush()

    # ── Drivers ──────────────────────────────────────────────────────────────
    drivers = [
        models.Driver(
            name="Rajan Kumar",
            license_number="TN2020DL00123",
            license_category="HMV",
            license_expiry_date=date.today() + timedelta(days=730),
            contact_number="+91-9876543210",
            safety_score=94.5,
            status=models.DriverStatus.AVAILABLE,
        ),
        models.Driver(
            name="Priya Sharma",
            license_number="MH2019DL00456",
            license_category="HMV",
            license_expiry_date=date.today() + timedelta(days=365),
            contact_number="+91-9123456789",
            safety_score=88.0,
            status=models.DriverStatus.AVAILABLE,
        ),
        models.Driver(
            name="Suresh Patel",
            license_number="KA2021DL00789",
            license_category="LMV",
            license_expiry_date=date.today() + timedelta(days=180),
            contact_number="+91-9988776655",
            safety_score=76.5,
            status=models.DriverStatus.OFF_DUTY,
        ),
    ]
    db.add_all(drivers)
    db.flush()

    # ── Maintenance Log ───────────────────────────────────────────────────────
    maintenance = [
        models.MaintenanceLog(
            vehicle_id="DL08GH3456",
            description="Engine overhaul — bearings replacement",
            cost=45000.0,
            date=date.today() - timedelta(days=2),
            status=models.MaintenanceStatus.ACTIVE,
        ),
    ]
    db.add_all(maintenance)
    db.flush()

    # ── Trips (completed with revenue) ───────────────────────────────────────
    trips = [
        models.Trip(
            source="Chennai",
            destination="Bangalore",
            vehicle_id="TN01AB1234",
            driver_id=drivers[0].id,
            cargo_weight=12000.0,
            planned_distance=350.0,
            status=models.TripStatus.COMPLETED,
            final_odometer=45550.0,
            fuel_consumed=52.0,
            revenue=28000.0,
        ),
        models.Trip(
            source="Mumbai",
            destination="Pune",
            vehicle_id="MH04CD5678",
            driver_id=drivers[1].id,
            cargo_weight=8000.0,
            planned_distance=150.0,
            status=models.TripStatus.COMPLETED,
            final_odometer=88150.0,
            fuel_consumed=22.0,
            revenue=12000.0,
        ),
    ]
    db.add_all(trips)
    db.flush()

    # ── Fuel & Expenses ───────────────────────────────────────────────────────
    expenses = [
        models.FuelExpense(
            vehicle_id="TN01AB1234",
            expense_type=models.ExpenseType.FUEL,
            liters=52.0,
            cost=5720.0,
            date=date.today() - timedelta(days=5),
            notes="Chennai→Bangalore run",
        ),
        models.FuelExpense(
            vehicle_id="MH04CD5678",
            expense_type=models.ExpenseType.FUEL,
            liters=22.0,
            cost=2420.0,
            date=date.today() - timedelta(days=3),
            notes="Mumbai→Pune run",
        ),
        models.FuelExpense(
            vehicle_id="DL08GH3456",
            expense_type=models.ExpenseType.MAINTENANCE,
            liters=None,
            cost=45000.0,
            date=date.today() - timedelta(days=2),
            notes="Engine overhaul",
        ),
        models.FuelExpense(
            vehicle_id="TN01AB1234",
            expense_type=models.ExpenseType.TOLL,
            liters=None,
            cost=480.0,
            date=date.today() - timedelta(days=5),
            notes="NH44 tolls",
        ),
    ]
    db.add_all(expenses)
    db.commit()
    print("[OK] Database seeded successfully!")
    print("   Login: manager@transitops.io / Manager@123")


if __name__ == "__main__":
    try:
        seed()
    except Exception as e:
        db.rollback()
        print(f"[FAIL] Seed failed: {e}")
        raise
    finally:
        db.close()
