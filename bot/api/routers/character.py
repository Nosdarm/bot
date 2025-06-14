# bot/api/routers/character.py
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
import uuid # For generating character IDs if not using auto-increment or other DB mechanism
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
import uuid
import logging
from typing import List, Dict, Any # Added Dict, Any
import json # Added json

from bot.api.dependencies import get_db_session
# Updated schema imports
from bot.api.schemas.character_schemas import (
    CharacterCreate, CharacterUpdate, CharacterRead, CharacterStatsSchema # Renamed CharacterResponse to CharacterRead
)
from bot.database.models import Character as DBCharacter, Player # Renamed Character to DBCharacter to avoid conflict
# Assuming CharacterManager can be directly imported. This is a simplification.
# For a real app, this would likely come from a DI system.
from bot.game.managers.character_manager import CharacterManager
# Assuming calculate_effective_stats can be imported. Also a simplification.
from bot.game.utils.stats_calculator import calculate_effective_stats

# Pydantic model for gain_xp request
from pydantic import BaseModel, Field # Added Field

logger = logging.getLogger(__name__)
router = APIRouter() # Prefix will be /api/v1/guilds/{guild_id} from main.py


class GainXPRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount of XP to gain, must be positive")

# Pydantic model for the /stats endpoint response
class CharacterStatsResponse(BaseModel):
    base_stats: CharacterStatsSchema
    level: int
    experience: int # Changed from xp to experience to match schema updates
    effective_stats: Dict[str, Any]

    # orm_mode is not strictly needed if not mapping directly from a DB model with this exact structure
    # class Config:
    #     orm_mode = True

# Note: guild_id is expected to be a path parameter provided by the include_router prefix in main.py

@router.post(
    "/players/{player_id}/characters/", # Assuming this path is acceptable (POST /characters/ was in req)
    response_model=CharacterRead,      # Use CharacterRead
    status_code=status.HTTP_201_CREATED,
    summary="Create a new character for a player"
)
async def create_character_for_player(
    path_guild_id: str = Path(..., description="Guild ID from path prefix", alias="guild_id"),
    path_player_id: str = Path(..., description="ID of the player to create the character for", alias="player_id"),
    character_data: CharacterCreate, # Removed Depends()
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Attempting to create character for player {character_data.player_id} in guild {character_data.guild_id}")

    if path_guild_id != character_data.guild_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Guild ID in path ({path_guild_id}) does not match Guild ID in body ({character_data.guild_id})."
        )
    if path_player_id != character_data.player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Player ID in path ({path_player_id}) does not match Player ID in body ({character_data.player_id})."
        )

    # Verify player exists and belongs to the guild
    player_stmt = select(Player).where(Player.id == character_data.player_id, Player.guild_id == character_data.guild_id)
    result = await db.execute(player_stmt)
    db_player = result.scalars().first()
    if not db_player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player with ID {character_data.player_id} not found in guild {character_data.guild_id}"
        )

    character_id = str(uuid.uuid4())
    # Use DBCharacter for instantiation
    db_character_instance = DBCharacter(
        id=character_id,
        player_id=character_data.player_id, # Use from body after validation
        guild_id=character_data.guild_id,   # Use from body after validation
        # Ensure character_data fields match DBCharacter model expectations
        # Notably, 'experience' from schema maps to 'xp' in DB model
        # and 'stats' from schema (CharacterStatsSchema object) maps to 'stats' (JSON) in DB
        name_i18n=character_data.name_i18n,
        class_i18n=character_data.class_i18n,
        description_i18n=character_data.description_i18n,
        level=character_data.level,
        xp=character_data.experience, # Map 'experience' from schema to 'xp' in DB
        stats=character_data.stats.dict() if character_data.stats else CharacterStatsSchema().dict(), # Convert CharacterStatsSchema to dict for JSON
        current_hp=character_data.current_hp,
        max_hp=character_data.max_hp,
        abilities=character_data.abilities,
        inventory=character_data.inventory,
        npc_relationships=character_data.npc_relationships,
        is_active_char=character_data.is_active_char
    )
    db.add(db_character_instance)
    try:
        await db.commit()
        await db.refresh(db_character_instance)
    except IntegrityError as e: # Catch potential DB errors like FK violations if any
        await db.rollback()
        logger.error(f"IntegrityError creating character for player {character_data.player_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create character due to data integrity issue.")
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating character for player {character_data.player_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create character.")
    return db_character_instance

@router.get(
    "/players/{player_id}/characters/",
    response_model=List[CharacterRead], # Use CharacterRead
    summary="List all characters for a specific player"
)
async def list_characters_for_player(
    guild_id: str = Path(..., description="Guild ID from path prefix"), # Retain guild_id from path
    player_id: str = Path(..., description="ID of the player whose characters to list"), # Retain player_id from path
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Listing characters for player {player_id} in guild {guild_id}")
    # Verify player exists and belongs to the guild (optional, but good for context)
    player_stmt = select(Player).where(Player.id == player_id, Player.guild_id == guild_id)
    result = await db.execute(player_stmt)
    if not result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player with ID {player_id} not found in guild {guild_id}"
        )

    stmt = select(DBCharacter).where(DBCharacter.player_id == player_id, DBCharacter.guild_id == guild_id)
    result = await db.execute(stmt)
    characters = result.scalars().all()
    return characters

@router.get(
    "/characters/{character_id}",
    response_model=CharacterRead, # Use CharacterRead
    summary="Get a specific character by Character ID"
)
async def get_character(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    character_id: str = Path(..., description="ID of the character to retrieve"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Fetching character {character_id} in guild {guild_id}")
    stmt = select(DBCharacter).where(DBCharacter.id == character_id, DBCharacter.guild_id == guild_id)
    result = await db.execute(stmt)
    db_character_instance = result.scalars().first()
    if not db_character_instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found in this guild")
    return db_character_instance

@router.put(
    "/characters/{character_id}",
    response_model=CharacterRead, # Use CharacterRead
    summary="Update a character's details"
)
async def update_character(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    character_id: str = Path(..., description="ID of the character to update"),
    character_update_data: CharacterUpdate, # Removed Depends()
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Updating character {character_id} in guild {guild_id}")
    stmt = select(DBCharacter).where(DBCharacter.id == character_id, DBCharacter.guild_id == guild_id)
    result = await db.execute(stmt)
    db_character_instance = result.scalars().first()

    if not db_character_instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found in this guild")

    update_data = character_update_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        if key == "experience": # Map schema 'experience' to DB 'xp'
            setattr(db_character_instance, "xp", value)
        elif key == "stats" and value is not None: # Ensure stats is dict for JSON
             setattr(db_character_instance, "stats", value if isinstance(value, dict) else value.dict())
        else:
            setattr(db_character_instance, key, value)

    db.add(db_character_instance)
    try:
        await db.commit()
        await db.refresh(db_character_instance)
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating character {character_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update character.")
    return db_character_instance

@router.delete(
    "/characters/{character_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a character"
)
async def delete_character(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    character_id: str = Path(..., description="ID of the character to delete"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Attempting to delete character {character_id} in guild {guild_id}")
    stmt = select(DBCharacter).where(DBCharacter.id == character_id, DBCharacter.guild_id == guild_id)
    result = await db.execute(stmt)
    db_character_instance = result.scalars().first()

    if not db_character_instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found in this guild")

    await db.delete(db_character_instance)
    try:
        await db.commit()
    except Exception as e: # Could be DB error if character is linked elsewhere with restrict
        await db.rollback()
        logger.error(f"Error deleting character {character_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete character.")
    return # Implicitly returns 204 No Content


# --- Endpoints below are existing and not part of the current CRUD subtask ---
# --- They will be updated to use CharacterRead if they use CharacterResponse ---

@router.post(
    "/characters/{character_id}/gain_xp",
    response_model=CharacterRead, # Use CharacterRead
    summary="Grant experience to a character and handle level ups"
)
async def gain_xp_for_character(
    guild_id: str = Path(..., description="Guild ID character belongs to"),
    character_id: str = Path(..., description="ID of the character gaining XP"),
    payload: GainXPRequest, # Removed Depends()
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Attempting to grant {payload.amount} XP to character {character_id} in guild {guild_id}")

    char_stmt = select(DBCharacter).where(DBCharacter.id == character_id, DBCharacter.guild_id == guild_id)
    result = await db.execute(char_stmt)
    db_character_model_instance = result.scalars().first()
    if not db_character_model_instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Character with ID {character_id} not found in guild {guild_id}"
        )

    # Using MockCharacterManager as per subtask instructions due to DI complexity
    class MockCharacterManager:
        async def gain_xp(self, guild_id: str, character_id: str, amount: int, current_level: int, current_xp: int) -> Dict[str, Any]:
            # Simulate XP gain and potential level up
            # This mock is highly simplified. A real manager would interact with game logic.
            new_xp = current_xp + amount
            new_level = current_level
            levels_gained = 0
            xp_for_next_level = new_level * 100 # Consistent with manager's logic

            while new_xp >= xp_for_next_level:
                new_xp -= xp_for_next_level
                new_level += 1
                levels_gained += 1
                xp_for_next_level = new_level * 100

            # Simulate updated stats - in reality, manager's level_up would change these
            simulated_stats = db_character_model_instance.stats if isinstance(db_character_model_instance.stats, dict) else json.loads(db_character_model_instance.stats or '{}')
            if levels_gained > 0: # If level up, simulate stat increase
                for stat_key in ["base_strength", "base_dexterity", "base_constitution", "base_intelligence", "base_wisdom", "base_charisma"]:
                    simulated_stats[stat_key] = simulated_stats.get(stat_key, 10) + levels_gained

            mock_char_data_from_mgr = {
                "id": character_id,
                "player_id": db_character_model_instance.player_id,
                "guild_id": guild_id,
                "name_i18n": db_character_model_instance.name_i18n,
                "class_i18n": db_character_model_instance.class_i18n,
                "description_i18n": db_character_model_instance.description_i18n,
                "level": new_level,
                "experience": new_xp, # This is the new 'experience' field
                "stats": simulated_stats, # This should be CharacterStatsSchema compatible
                "current_hp": db_character_model_instance.current_hp, # Assuming HP doesn't change on XP gain unless level up implies full heal (manager logic)
                "max_hp": db_character_model_instance.max_hp, # Max HP might change with level up (manager logic)
                "abilities": db_character_model_instance.abilities,
                "inventory": db_character_model_instance.inventory,
                "npc_relationships": db_character_model_instance.npc_relationships,
                "is_active_char": db_character_model_instance.is_active_char,
            }
            return {"updated_character_data": mock_char_data_from_mgr, "levels_gained": levels_gained, "xp_added": amount}

    character_manager_instance = MockCharacterManager()

    try:
        result_data = await character_manager_instance.gain_xp(
            guild_id, character_id, payload.amount,
            db_character_model_instance.level, db_character_model_instance.xp # Pass current level and DB xp
        )

        # The manager returns data that should be compatible with CharacterRead
        # The key is that 'updated_character_data' now contains 'experience' and 'stats' as a dict
        api_response_data = result_data['updated_character_data']

        # We need to ensure the 'stats' field in api_response_data is a dict that CharacterStatsSchema can validate
        # If it's already a CharacterStatsSchema object from the manager, .dict() might be needed by CharacterRead
        # If it's a dict from the manager, CharacterRead should handle it if its 'stats' field is Type[CharacterStatsSchema]
        if isinstance(api_response_data["stats"], CharacterStatsSchema):
             api_response_data["stats"] = api_response_data["stats"].dict() # Ensure it's a dict for Pydantic model

        # Also, CharacterRead expects player_id, which should be in api_response_data from the mock
        return CharacterRead(**api_response_data)

    except ValueError as e:
        logger.warning(f"ValueError in gain_xp for char {character_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in gain_xp endpoint for char {character_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error while granting XP.")


@router.get(
    "/characters/{character_id}/stats",
    response_model=CharacterStatsResponse,
    summary="Get a character's base and derived stats"
)
async def get_character_stats_details(
    guild_id: str = Path(..., description="Guild ID character belongs to"),
    character_id: str = Path(..., description="ID of the character"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Fetching stats for character {character_id} in guild {guild_id}")

    stmt = select(DBCharacter).where(DBCharacter.id == character_id, DBCharacter.guild_id == guild_id)
    result = await db.execute(stmt)
    db_character_model_instance = result.scalars().first()

    if not db_character_model_instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found in this guild")

    # Mocking the call to calculate_effective_stats as per subtask instructions
    # In a real app, this would involve calling the actual stats_calculator function
    # which requires numerous manager dependencies.
    mock_effective_stats = {
        "max_hp": 120 + (db_character_model_instance.level * 5), # Example dynamic mock
        "attack": 15 + db_character_model_instance.level,
        "defense": 12 + db_character_model_instance.level,
        "base_strength": (db_character_model_instance.stats or {}).get("base_strength", 10), # Reflect base stats if available
        "base_dexterity": (db_character_model_instance.stats or {}).get("base_dexterity", 10),
        "base_constitution": (db_character_model_instance.stats or {}).get("base_constitution", 10),
        "base_intelligence": (db_character_model_instance.stats or {}).get("base_intelligence", 10),
        "base_wisdom": (db_character_model_instance.stats or {}).get("base_wisdom", 10),
        "base_charisma": (db_character_model_instance.stats or {}).get("base_charisma", 10),
        # ... other stats that calculate_effective_stats might return
    }

    # Prepare base_stats from db_character.stats
    db_stats_json_str = db_character_model_instance.stats
    db_stats_dict = {}
    if isinstance(db_stats_json_str, str):
        try:
            db_stats_dict = json.loads(db_stats_json_str or '{}')
        except json.JSONDecodeError:
            logger.warning(f"Could not parse stats JSON for character {character_id}: {db_stats_json_str}")
            db_stats_dict = {} # Default to empty if parsing fails
    elif isinstance(db_stats_json_str, dict): # If already a dict (e.g. from previous operations)
        db_stats_dict = db_stats_json_str

    # Ensure all base stats fields are present for CharacterStatsSchema, defaulting if necessary
    base_stats_data = {
        "base_strength": db_stats_dict.get("base_strength", 10),
        "base_dexterity": db_stats_dict.get("base_dexterity", 10),
        "base_constitution": db_stats_dict.get("base_constitution", 10),
        "base_intelligence": db_stats_dict.get("base_intelligence", 10),
        "base_wisdom": db_stats_dict.get("base_wisdom", 10),
        "base_charisma": db_stats_dict.get("base_charisma", 10),
    }
    character_base_stats_obj = CharacterStatsSchema(**base_stats_data)

    response_data = CharacterStatsResponse(
        base_stats=character_base_stats_obj,
        level=db_character_model_instance.level,
        experience=db_character_model_instance.xp, # Map DB 'xp' to schema 'experience'
        effective_stats=mock_effective_stats
    )
    return response_data
