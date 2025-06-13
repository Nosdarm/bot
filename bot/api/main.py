# bot/api/main.py
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel # For error detail model
import logging
import time
import uvicorn # For running the app if this becomes the main entry point

from bot.api.routers import guild as guild_router
from bot.api.routers import player as player_router
from bot.api.routers import character as character_router
from bot.api.routers import rule_config as rule_config_router
from bot.api.routers import ability as ability_router
from bot.api.routers import game_log as game_log_router
from bot.api.routers import action as action_router
from bot.api.routers import location as location_router
from bot.api.routers import map as map_router
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
    logger.error(f"Request validation error: {exc.errors()}")
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

@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI application startup...")
    # await create_db_and_tables() # Uncomment if you want to ensure tables are created on startup by FastAPI app
    # (Alembic should be the primary way to manage schema)
    logger.info("FastAPI application started.")

@app.get("/", tags=["Root"], summary="Root path for API health check")
async def read_root():
    return {"message": "Kvelin RPG Bot API is running."}

# To run this app (example, if not using a larger structure like the bot's main.py):
# if __name__ == "__main__":
#    uvicorn.run("bot.api.main:app", host="0.0.0.0", port=8000, reload=True)
