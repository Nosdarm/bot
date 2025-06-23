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

## Game API Endpoints
The following sections describe endpoints related to the main game functionalities, typically prefixed by `/api/v1/` (this prefix is configured in the main FastAPI application).

### Item Endpoints
- **Prefix:** `/api/v1/items`

- **`POST /` - Create Item**
  - Description: Creates a new item template.
  - Request Body: `NewItemCreate` (fields: `name: str`, `description: Optional[str]`, `item_type: str`, `item_metadata: Optional[dict]`)
  - Response Body: `NewItemRead`

- **`GET /` - List Items**
  - Description: Retrieves a list of all item templates.
  - Query Parameters: `skip: int = 0` (optional), `limit: int = 100` (optional)
  - Response Body: `List[NewItemRead]`

- **`GET /{item_id}` - Get Item**
  - Description: Retrieves a specific item template by its ID.
  - Path Parameters: `item_id: UUID`
  - Response Body: `NewItemRead`

- **`PUT /{item_id}` - Update Item**
  - Description: Updates an existing item template.
  - Path Parameters: `item_id: UUID`
  - Request Body: `NewItemUpdate` (fields: `name: Optional[str]`, `description: Optional[str]`, `item_type: Optional[str]`, `item_metadata: Optional[dict]`)
  - Response Body: `NewItemRead`

- **`DELETE /{item_id}` - Delete Item**
  - Description: Deletes an item template. This operation will fail if the item is currently present in any character's inventory.
  - Path Parameters: `item_id: UUID`
  - Response Body: `NewItemRead` (representing the item that was deleted)

### Character Endpoints
These endpoints manage characters within a specific guild.
- **Prefix:** `/api/v1/guilds/{guild_id}` (where `{guild_id}` is the ID of the guild)

Note: The following character routes are relative to the prefix above (e.g., `/api/v1/guilds/{guild_id}/players/{player_id}/characters/`).

- **`POST /players/{player_id}/characters/` - Create Character**
    - Description: Creates a new character for a specific player within the guild.
    - Path Parameters: `guild_id`, `player_id`.
    - Request Body: `CharacterCreate` schema.
    - Response Body: `CharacterResponse` schema.

- **`GET /players/{player_id}/characters/` - List Player's Characters**
    - Description: Lists all characters belonging to a specific player within the guild.
    - Path Parameters: `guild_id`, `player_id`.
    - Response Body: List of `CharacterResponse` schema.

- **`GET /characters/{character_id}` - Get Character**
    - Description: Retrieves a specific character by its ID within the guild.
    - Path Parameters: `guild_id`, `character_id`.
    - Response Body: `CharacterResponse` schema.

- **`PUT /characters/{character_id}` - Update Character**
    - Description: Updates a specific character by its ID within the guild.
    - Path Parameters: `guild_id`, `character_id`.
    - Request Body: `CharacterUpdate` schema.
    - Response Body: `CharacterResponse` schema.

- **`DELETE /characters/{character_id}` - Delete Character**
    - Description: Deletes a specific character by its ID within the guild.
    - Path Parameters: `guild_id`, `character_id`.
    - Response: `204 No Content`.

#### Character Progression and Stats
The following endpoints are relative to `/api/v1/guilds/{guild_id}/characters/{character_id}`.

*   **Method & Path:** `POST /gain_xp`
*   **Description:** Adds a specified amount of experience points (XP) to a character. If the character gains enough XP to level up, their level and base stats will be increased automatically. This process can repeat if enough XP is gained for multiple levels.
*   **Path Parameters (from prefix):**
    *   `guild_id` (string): The ID of the guild the character belongs to.
    *   `character_id` (string): The ID of the character gaining XP.
*   **Request Body:**
    ```json
    {
        "amount": 150
    }
    ```
    *   `amount` (integer, required): The amount of XP to grant. Must be a positive integer. (Corresponds to `GainXPRequest` schema)
*   **Response Body (200 OK):**
    *   Returns the updated Character object, reflecting any changes to XP, level, and stats. (Corresponds to `CharacterResponse` schema)
*   **Error Responses:**
    *   `400 Bad Request`: If the `amount` is not positive or other validation fails.
    *   `404 Not Found`: If the specified `character_id` or `guild_id` does not exist.

*   **Method & Path:** `GET /stats`
*   **Description:** Retrieves detailed statistics for a character, including their base attributes, current level, experience points, and calculated effective/derived stats (like Max HP, Attack, Defense).
*   **Path Parameters (from prefix):**
    *   `guild_id` (string): The ID of the guild the character belongs to.
    *   `character_id` (string): The ID of the character.
*   **Response Body (200 OK):**
    *   Returns a JSON object with the character's statistics:
    ```json
    {
        "base_stats": {
            "base_strength": 10,
            "base_dexterity": 10,
            "base_constitution": 10,
            "base_intelligence": 10,
            "base_wisdom": 10,
            "base_charisma": 10
        },
        "level": 1,
        "experience": 50,
        "effective_stats": {
            "max_hp": 125,
            "attack": 10,
            "defense": 10
            // ... other effective stats calculated by the system
        }
    }
    ```
    (Corresponds to `CharacterStatsResponse` schema.)
*   **Error Responses:**
    *   `404 Not Found`: If the specified `character_id` or `guild_id` does not exist.

### Character Inventory Endpoints
These endpoints manage items within a specific character's inventory.
- **Prefix:** `/api/v1/characters/{character_id}` (where `{character_id}` is the ID of the character)
  *Note: This prefix seems different from the guild-based character endpoints above. Clarification might be needed on whether inventory is guild-specific or global character based.*

- **`GET /inventory` - Get Character Inventory**
  - Description: Retrieves all items in the specified character's inventory.
  - Path Parameters: `character_id: str`
  - Response Body: `List[InventoryItemRead]` (each entry includes full item details and quantity)
    - `InventoryItemRead` schema: `{ "item": NewItemRead, "quantity": int }`

- **`POST /inventory/add` - Add Item to Inventory**
  - Description: Adds an item to the character's inventory. If the item already exists in the inventory, its quantity is increased.
  - Path Parameters: `character_id: str`
  - Request Body: `NewCharacterItemCreate` (fields: `item_id: UUID`, `quantity: int = 1`)
  - Response Body: `NewCharacterItemRead` (includes item details, character ID, and new quantity)

- **`POST /inventory/remove` - Remove Item from Inventory**
  - Description: Removes a specified quantity of an item from the character's inventory. If the quantity to remove is greater than or equal to the current quantity, the item is completely removed from the inventory.
  - Path Parameters: `character_id: str`
  - Request Body: `NewCharacterItemCreate` (fields: `item_id: UUID`, `quantity: int = 1` (represents quantity to remove))
  - Response Body: `NewCharacterItemRead` (if quantity is reduced but item remains) or HTTP `204 No Content` (if item is fully removed from inventory).

Refer to the API documentation at `/docs` (Swagger UI) or `/redoc` when the FastAPI application is running for detailed request/response schemas and interactive testing. These new endpoints will also be available there.

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
    export DATABASE_URL="postgresql+asyncpg://neondb_owner:npg_O2HrF6JYDPpG@ep-old-hat-a9ctb4yy-pooler.gwc.azure.neon.tech:5432/neondb?sslmode=require"
    ```
    The default URL if `DATABASE_URL` is not set is `postgresql+asyncpg://neondb_owner:npg_O2HrF6JYDPpG@ep-old-hat-a9ctb4yy-pooler.gwc.azure.neon.tech:5432/neondb?sslmode=require` (defined in `bot/database/postgres_adapter.py`).

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
