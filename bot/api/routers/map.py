# bot/api/routers/map.py
from fastapi import APIRouter, Depends, HTTPException, Path, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid

from bot.api.dependencies import get_db_session
from bot.database.models import Location
# Assuming LocationCreate and LocationResponse might be useful, or define specific ones
from bot.api.schemas.location_schemas import LocationResponse, LocationCreate

logger = logging.getLogger(__name__)
router = APIRouter() # Prefix will be /api/v1/guilds/{guild_id}/map from main.py

# --- Pydantic Schemas for Map Generation ---
class MapGenerationRequest(BaseModel):
    map_name: str = Field("default_map", description="A name for this map generation instance or area.")
    theme: Optional[str] = Field(None, description="Optional theme for map generation (e.g., 'forest', 'dungeon').")
    size_hint: Optional[str] = Field("small", description="Hint for map size (e.g., 'small', 'medium', 'large'). Not strictly enforced by basic generator.")
    # num_locations: Optional[int] = Field(3, ge=1, le=10, description="Number of locations to generate for basic generator.")

class GeneratedMapLocationInfo(BaseModel):
    id: str
    name_i18n: Dict[str, str]
    type_i18n: Dict[str, str]
    coordinates: Optional[Dict[str, Any]] = None
    exits: Optional[Dict[str, str]] = None

class MapGenerationResponse(BaseModel):
    guild_id: str
    map_name: str
    message: str
    generated_locations: List[GeneratedMapLocationInfo] = []

# --- Basic Map Generation Logic ---
async def generate_basic_map_locations(db: AsyncSession, guild_id: str, req: MapGenerationRequest) -> List[Location]:
    """
    Very basic map generator. Creates a few predefined locations and links them.
    This is a placeholder for more complex or AI-driven generation.
    """
    created_locations_db = []

    # Define a few locations
    loc_data = [
        {"name_key": "central_square", "type_key": "town_square", "coords": {"x":0, "y":0, "map_name": req.map_name}},
        {"name_key": "north_gate", "type_key": "gate", "coords": {"x":0, "y":1, "map_name": req.map_name}},
        {"name_key": "market_street", "type_key": "street", "coords": {"x":1, "y":0, "map_name": req.map_name}},
    ]

    # Names and types (simple i18n for now)
    loc_details_i18n = {
        "central_square": {"en": f"{req.map_name} Central Square", "ru": f"Центральная Площадь {req.map_name}"},
        "north_gate": {"en": f"{req.map_name} North Gate", "ru": f"Северные Ворота {req.map_name}"},
        "market_street": {"en": f"{req.map_name} Market Street", "ru": f"Рыночная Улица {req.map_name}"},
        "town_square": {"en": "Town Square", "ru": "Городская площадь"},
        "gate": {"en": "Gate", "ru": "Ворота"},
        "street": {"en": "Street", "ru": "Улица"},
        "generic_desc": {"en": "A notable location.", "ru": "Примечательное место."},
    }

    temp_loc_objects = [] # To store model instances before assigning IDs for exits

    for i, data in enumerate(loc_data):
        loc_id = str(uuid.uuid4())
        loc = Location(
            id=loc_id,
            guild_id=guild_id,
            name_i18n=loc_details_i18n[data["name_key"]],
            descriptions_i18n=loc_details_i18n["generic_desc"], # Generic description
            type_i18n=loc_details_i18n[data["type_key"]],
            coordinates=data["coords"],
            exits={}, # Will be filled later
            npc_ids=[],
            event_triggers=[],
            is_active=True
        )
        temp_loc_objects.append(loc)
        db.add(loc)
        # created_locations_db list will be populated after commit and refresh if needed
        # For now, we return the objects added to session, assuming commit in main function works.

    # Link them (simple linear for this example)
    # Central Square <-> North Gate
    # Central Square <-> Market Street
    if len(temp_loc_objects) >= 3:
        # Central Square exits
        temp_loc_objects[0].exits["north"] = temp_loc_objects[1].id # To North Gate
        temp_loc_objects[0].exits["east"] = temp_loc_objects[2].id  # To Market Street

        # North Gate exits
        temp_loc_objects[1].exits["south"] = temp_loc_objects[0].id # To Central Square

        # Market Street exits
        temp_loc_objects[2].exits["west"] = temp_loc_objects[0].id  # To Central Square

    # The objects in temp_loc_objects are already added to the session.
    # The calling function (generate_map_endpoint) will handle the commit.
    return temp_loc_objects # Return the model instances, not yet committed/refreshed


@router.post("/generate_map", response_model=MapGenerationResponse, summary="Generate a basic map for the guild")
async def generate_map_endpoint(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    request_body: MapGenerationRequest = Body(...),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Request to generate map for guild {guild_id} with parameters: {request_body.dict()}")

    # Commenting out PG-specific JSON query for now for broader compatibility / simplicity
    # existing_loc_stmt = select(Location.id).where(
    #     Location.guild_id == guild_id,
    #     Location.coordinates.op('->>')('map_name') == request_body.map_name
    # ).limit(1)
    # result = await db.execute(existing_loc_stmt)
    # if result.scalars().first():
    #     raise HTTPException(
    #         status_code=status.HTTP_409_CONFLICT,
    #         detail=f"A map or locations named '{request_body.map_name}' might already exist. Clear or use a different name."
    #     )

    generated_db_location_models = await generate_basic_map_locations(db, guild_id, request_body)

    # Commit changes made by generate_basic_map_locations (adding locations to session)
    try:
        await db.commit()
        for loc_model in generated_db_location_models:
            await db.refresh(loc_model) # Refresh each object to get DB defaults/final state
    except Exception as e:
        await db.rollback()
        logger.error(f"Error committing generated map locations for guild {guild_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save generated map locations.")

    response_locations = []
    for loc in generated_db_location_models: # Iterate over refreshed models
        response_locations.append(GeneratedMapLocationInfo(
            id=loc.id,
            name_i18n=loc.name_i18n,
            type_i18n=loc.type_i18n,
            coordinates=loc.coordinates,
            exits=loc.exits
        ))

    return MapGenerationResponse(
        guild_id=guild_id,
        map_name=request_body.map_name,
        message=f"Basic map '{request_body.map_name}' generated with {len(response_locations)} locations.",
        generated_locations=response_locations
    )
