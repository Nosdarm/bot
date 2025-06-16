# bot/api/main.py
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel # For error detail model
import logging
import time
import uvicorn # For running the app if this becomes the main entry point
import os # ADDED for os.getenv
from typing import Dict, Any, List, Optional # ADDED

from bot.game.managers.game_manager import GameManager # ADDED
from bot.services.db_service import DBService # ADDED
# from bot.services.config_service import ConfigService # Assuming a ConfigService exists or will be created
# For now, we can simulate config loading if ConfigService is not ready.

from bot.api.routers import guild as guild_router
from bot.api.routers import player as player_router
from bot.api.routers import character as character_router
from bot.api.routers import rule_config as rule_config_router
from bot.api.routers import ability as ability_router
from bot.api.routers import game_log as game_log_router
from bot.api.routers import action as action_router
from bot.api.routers import location as location_router
from bot.api.routers import map as map_router
from bot.api.routers import combat as combat_router
from bot.api.routers import rpg_character_api
from bot.api.routers import item_router  # New Item router
from bot.api.routers import inventory_router  # New Inventory router
from bot.api.routers import quest_router # ADDED: Import the new quest router
from bot.api.routers import master as master_router # ADDED: Import the new master router
# from bot.api.dependencies import create_db_and_tables # If you want to create tables on startup

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Kvelin RPG Bot API",
    description="API for managing Kvelin RPG Bot data and operations.",
    version="0.1.0"
)

# Middleware for logging requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    # Try to get guild_id from path parameters if available
    guild_id_in_path = request.path_params.get("guild_id", "N/A")

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000
    formatted_process_time = '{0:.2f}'.format(process_time)

    logger.info(
        f"Request: {request.method} {request.url.path} (Guild: {guild_id_in_path}) - "
        f"Status: {response.status_code} - Completed in: {formatted_process_time}ms"
    )
    return response

# Basic global error handler
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    guild_id_in_path = request.path_params.get("guild_id", "N/A") # For logging context
    logger.error(
        f"Unhandled error for request {request.method} {request.url.path} (Guild: {guild_id_in_path}): {exc}",
        exc_info=True # Include traceback
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"An internal server error occurred. Guild context: {guild_id_in_path}"},
    )

# Pydantic validation error handler (FastAPI default is good, but this shows customization)
class ValidationErrorDetail(BaseModel):
    loc: tuple[str, ...]
    msg: str
    type: str

class HTTPValidationError(BaseModel):
    detail: list[ValidationErrorDetail]

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    guild_id_in_path = request.path_params.get("guild_id", "N/A")
    logger.error(f"Request validation error for guild_id '{guild_id_in_path}': {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )

# Include routers
# The {guild_id} path parameter here will be passed to all endpoints in these routers
# if they declare it as a path parameter.
app.include_router(
    guild_router.router,
    prefix="/api/v1/guilds/{guild_id}",
    tags=["Guild Initialization"] # More specific tag
)
app.include_router(
    player_router.router,
    prefix="/api/v1/guilds/{guild_id}/players",
    tags=["Players"]
)
app.include_router(
    character_router.router,
    prefix="/api/v1/guilds/{guild_id}", # Character specific paths are defined within its router
    tags=["Characters"]
)
app.include_router(
    rule_config_router.router,
    prefix="/api/v1/guilds/{guild_id}/config",
    tags=["Guild Configuration"]
)
app.include_router(
    ability_router.router,
    prefix="/api/v1/guilds/{guild_id}/abilities",
    tags=["Abilities"]
)
app.include_router(
    game_log_router.router,
    prefix="/api/v1/guilds/{guild_id}", # Specific paths like /log_event, /events are in the router
    tags=["Game Log & Events"]
)
app.include_router(
    action_router.router,
    prefix="/api/v1/guilds/{guild_id}", # Specific paths like /characters/{char_id}/activate_ability are in the router
    tags=["Actions"]
)
app.include_router(
    location_router.router,
    prefix="/api/v1/guilds/{guild_id}/locations",
    tags=["Locations"]
)
app.include_router(
    map_router.router,
    prefix="/api/v1/guilds/{guild_id}/map",
    tags=["Map Management"]
)
app.include_router(
    combat_router.router,
    prefix="/api/v1/guilds/{guild_id}/combats",
    tags=["Combat"]
)
app.include_router(
    rpg_character_api.router,
    # The prefix "/characters" and tags ["RPG Characters"] are defined in rpg_character_api.py
)

# New Item Router
app.include_router(
    item_router.router,
    prefix="/api/v1/items",
    tags=["Items (New)"]
)

# New Inventory Router (associated with specific characters)
app.include_router(
    inventory_router.router,
    prefix="/api/v1/characters/{character_id}", # character_id will be passed to inventory_router endpoints
    tags=["Character Inventory (New)"]
)

# ADDED: Include the Quest router
# It's not guild-specific at the prefix level, as guild_id is part of its payload for /handle_event
app.include_router(
    quest_router.router,
    prefix="/api/v1", # The /quests prefix is defined within the router itself
    tags=["Quests"]
)

# ADDED: Include the Master router
# The prefix "/guilds/{guild_id}/master" is defined within the master_router itself.
app.include_router(
    master_router.router,
    prefix="/api/v1", # Base prefix for all API v1 routes
    tags=["Master Tools"] # Tag for Swagger UI grouping
)

@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI application startup...")
    # await create_db_and_tables() # Uncomment if you want to ensure tables are created on startup by FastAPI app
    # (Alembic should be the primary way to manage schema)

    # Initialize DBService
    # DB_TYPE can be an environment variable, e.g., "postgres" or "sqlite"
    # DB_URL (for Postgres) or DB_PATH (for SQLite) would also come from env/config
    db_service = DBService(db_type=os.getenv("DATABASE_TYPE", "postgres"))
    await db_service.connect()
    # Initialize database schema (e.g., create tables if they don't exist)
    # In a production setup, Alembic migrations are preferred over this.
    # await db_service.initialize_database()
    logger.info("DBService connected and initialized.")
    app.state.db_service = db_service # Make DBService available globally if needed by dependencies

    # Initialize ConfigService (simulated for now)
    # config_service = ConfigService(config_file_path="data/settings.json")
    # For this example, using a placeholder. A real app would load from file or env.
    game_settings: Dict[str, Any] = {
        "default_language": os.getenv("DEFAULT_LANGUAGE", "en"),
        "target_languages": ["en", "ru"], # Example
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        # Add other relevant global game settings if GameManager expects them directly
        # Guild-specific settings might be loaded by GameManager per guild.
    }
    logger.info("Simulated config loaded.")

    # Initialize GameManager
    # GameManager's __init__ should handle creating all its sub-managers and services,
    # passing them the db_service, relevant settings, and each other as needed.
    logger.info("Initializing GameManager...")
    game_manager = GameManager(
        settings=game_settings,
        db_service=db_service
    )

    # Assuming GameManager has a method to initialize its sub-managers and load initial data.
    # This might involve loading data for all guilds or preparing for on-demand loading.
    await game_manager.initialize_all_managers()
    logger.info("GameManager initialized its managers.")

    # Store GameManager in app.state to make it accessible in request handlers via dependencies
    app.state.game_manager = game_manager
    logger.info("GameManager instance stored in app.state.")

    logger.info("FastAPI application started successfully.")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI application shutting down...")
    if hasattr(app.state, 'db_service') and app.state.db_service:
        await app.state.db_service.close()
        logger.info("DBService connection closed.")
    # If GameManager has a specific shutdown method for its components:
    # if hasattr(app.state, 'game_manager') and app.state.game_manager:
    #     await app.state.game_manager.shutdown()
    #     logger.info("GameManager shutdown complete.")
    logger.info("FastAPI application shutdown complete.")

@app.get("/", tags=["Root"], summary="Root path for API health check")
async def read_root():
    return {"message": "Kvelin RPG Bot API is running."}

# To run this app (example, if not using a larger structure like the bot's main.py):
# if __name__ == "__main__":
#    uvicorn.run("bot.api.main:app", host="0.0.0.0", port=8000, reload=True)
