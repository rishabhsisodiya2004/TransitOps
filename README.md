# TransitOps

TransitOps is a FastAPI fleet operations app that can run on SQLite for quick local development or PostgreSQL for a more realistic setup.

## PostgreSQL setup

1. Install the Python dependencies.

   ```powershell
   pip install -r requirements.txt
   ```

2. Start PostgreSQL with Docker.

   ```powershell
   docker compose up -d postgres
   ```

3. Create a `.env` file from `.env.example` and switch `DATABASE_URL` to PostgreSQL.

   ```env
   DATABASE_URL=postgresql+psycopg2://transitops:transitops@localhost:5432/transitops
   ```

4. Run the API.

   ```powershell
   uvicorn app.main:app --reload
   ```

5. Optional: seed demo data after the database is up.

   ```powershell
   python seed.py
   ``

  
  ## Security Features

- JWT Authentication
- Password Hashing (bcrypt)
- Role-Based Access Control (RBAC)
- Secure CORS Configuration
- HTTP Security Headers
- Protected REST APIs


## Notes

- The app creates tables on startup through SQLAlchemy metadata.
- SQLite files are ignored so you can keep a local dev database without polluting git.
