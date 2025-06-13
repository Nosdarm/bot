# Kvelin RPG Bot Project

This project includes a Discord bot and an accompanying FastAPI application for managing game data.

## Features
- Discord Bot for interactive gameplay.
- FastAPI backend for data management and API access.
- PostgreSQL database for persistent storage.
- Alembic for database schema migrations.

## New RPG Character Management API
A new set of API endpoints has been added to manage simple RPG characters, independent of the main bot's more complex character system.

**API Endpoints (provided by FastAPI):**
- `POST /characters/`: Create a new character.
- `GET /characters/`: Get a list of all characters.
- `GET /characters/{character_id}`: Get a specific character by ID.
- `PUT /characters/{character_id}`: Update a character.
- `DELETE /characters/{character_id}`: Delete a character.

Refer to the API documentation at `/docs` (Swagger UI) or `/redoc` when the FastAPI application is running.

## Setup and Running

### 1. Prerequisites
- Python 3.8+
- PostgreSQL server

### 2. Installation
1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    (Note: Ensure `requirements.txt` is up-to-date with `fastapi`, `uvicorn`, `sqlalchemy`, `asyncpg`, `alembic`, `psycopg2-binary` (for Alembic sync operations) and any other necessary packages.)

### 3. Database Setup
1.  **Configure Database URL:**
    The application uses a PostgreSQL database. Set the `DATABASE_URL` environment variable.
    The format is `postgresql+asyncpg://user:password@host:port/dbname`.

    Example for local development (ensure your PostgreSQL server is running and configured with these credentials):
    ```bash
    export DATABASE_URL="postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot"
    ```
    The default URL if `DATABASE_URL` is not set is `postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot` (defined in `bot/database/postgres_adapter.py`).

2.  **Run Database Migrations:**
    This project uses Alembic for database schema management. The migration scripts are typically located in `bot/alembic/versions/`.
    To apply all migrations and create/update tables (including the new `rpg_characters` table), run:
    ```bash
    alembic upgrade head
    ```
    (This assumes your `alembic.ini` is configured correctly to find the migration environment and the `bot.database.models.Base` metadata.)
    If you encounter issues with Alembic finding the database or its configuration, you might need to specify the config path, e.g., `alembic -c alembic.ini upgrade head` if `alembic.ini` is in the root and properly configured.

### 4. Running the FastAPI Application
The FastAPI application is defined in `bot/api/main.py`. To run it using Uvicorn:
```bash
uvicorn bot.api.main:app --reload --host 0.0.0.0 --port 8000
```
- `--reload`: Enables auto-reloading on code changes (for development).
- `--host 0.0.0.0`: Makes the server accessible on your network.
- `--port 8000`: Specifies the port.

Once running, the API will be available at `http://localhost:8000`.
-   Interactive API documentation (Swagger UI): `http://localhost:8000/docs`
-   Alternative API documentation (ReDoc): `http://localhost:8000/redoc`

### 5. Running the Discord Bot
The main entry point for the Discord bot is `main.py`.
```bash
python main.py
```
Ensure your Discord bot token and other necessary configurations (e.g., via `.env` file as suggested by `load_dotenv()` in `main.py`) are set up.

## Project Structure
- `main.py`: Main entry point for the Discord bot.
- `bot/`: Core application logic.
  - `bot/bot_core.py`: Main logic for the Discord bot.
  - `bot/api/`: FastAPI application.
    - `bot/api/main.py`: FastAPI app definition and router inclusions.
    - `bot/api/routers/`: API endpoint routers.
      - `rpg_character_api.py`: Router for the new RPG character endpoints.
    - `bot/api/schemas/`: Pydantic schemas.
      - `rpg_character_schemas.py`: Schemas for the new RPG characters.
  - `bot/database/`: Database models and CRUD operations.
    - `models.py`: SQLAlchemy models (including `RPGCharacter`).
    - `rpg_character_crud.py`: CRUD functions for `RPGCharacter`.
    - `postgres_adapter.py`: Database connection adapter.
  - `bot/alembic/`: Alembic migration scripts and environment for the bot's database.
- `alembic.ini`: Alembic configuration file (likely for the bot's database, check `script_location`).
- `requirements.txt`: Python package dependencies.
- `README.md`: This file.
