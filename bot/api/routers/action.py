# bot/api/routers/action.py
from fastapi import APIRouter, Depends, HTTPException, Path, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field # Import BaseModel and Field

from bot.api.dependencies import get_db_session
from bot.database.models import Character, Ability, RulesConfig, GameLog
# Assuming GameLogEntryCreate is available for logging the event
from bot.api.schemas.game_log_schemas import GameLogEntryCreate, GameLogEntryResponse, ParticipatingEntity

logger = logging.getLogger(__name__)
router = APIRouter() # Prefix will be /api/v1/guilds/{guild_id} from main.py

# --- Pydantic Schemas for this router ---
class AbilityActivationRequest(BaseModel):
    ability_id: str = Field(..., description="ID of the ability to activate.")
    target_ids: Optional[List[str]] = Field(None, description="Optional list of target entity IDs.")
    # Add any other parameters an ability might need, e.g., specific coordinates, choices.
    additional_params: Optional[Dict[str, Any]] = Field(None, description="Additional parameters for the ability activation.")

class AbilityActivationEffect(BaseModel): # Part of the response
    description: str
    details: Optional[Dict[str, Any]] = None

class AbilityActivationResponse(BaseModel):
    success: bool
    message: str
    caster_id: str
    ability_id: str
    targets: Optional[List[str]] = None
    effects_summary: List[AbilityActivationEffect] = []
    log_entry: Optional[GameLogEntryResponse] = None # Include the log entry created

# --- Helper to log ability activation ---
async def log_ability_activation(
    db: AsyncSession,
    guild_id: str,
    character_id: str,
    player_id_for_log: Optional[str], # Added to pass player_id
    ability_id: str,
    ability_name_i18n: Dict[str, str],
    request_data: AbilityActivationRequest,
    success: bool,
    message: str,
    consequences: Optional[Dict[str, Any]] = None
) -> Optional[GameLog]: # Return type changed to actual GameLog model for refresh
    event_type = "ability_activated_success" if success else "ability_activated_failure"

    # Construct a user-friendly description
    char_name_placeholder = f"Character({character_id})" # In a real system, fetch character name
    ability_name_en = ability_name_i18n.get("en", ability_id)
    description_map = {
        "en": f"{char_name_placeholder} attempted to activate ability '{ability_name_en}'. Result: {message}",
        # Add other languages as needed
    }
    if not description_map.get("en"): # Fallback if 'en' name missing
         description_map["en"] = f"Character {character_id} action: ability {ability_id}. Result: {message}"


    participating_entities_list = [ParticipatingEntity(type="character", id=character_id)]
    if request_data.target_ids:
        for target_id in request_data.target_ids:
            # In a real system, you might want to determine target type (NPC, other player, item etc.)
            participating_entities_list.append(ParticipatingEntity(type="target", id=target_id))

    log_create_data = GameLogEntryCreate(
        event_type=event_type,
        player_id=player_id_for_log,
        description_i18n=description_map,
        involved_entities_ids=participating_entities_list,
        consequences_data=consequences or {},
        details={"ability_id": ability_id, "raw_request": request_data.dict(exclude_none=True), "outcome_message": message}
    )

    db_log_entry = GameLog(guild_id=guild_id, **log_create_data.dict(exclude_none=True))
    db.add(db_log_entry)
    try:
        # This commit is part of the session from get_db_session.
        # If the main endpoint also commits, this might be redundant or needs careful handling
        # of the overall transaction. For now, let logging commit its own entry.
        # However, it's often better to pass the log entry back to the main function
        # and let it be committed as part of the single unit of work.
        # For now, let's remove the commit here and assume main endpoint handles it.
        # await db.commit()
        # await db.refresh(db_log_entry)
        # The log entry will be added to the session. The main endpoint's commit will save it.
        return db_log_entry
    except Exception as e:
        logger.error(f"Failed to stage log for ability activation (char {character_id}, ability {ability_id}): {e}", exc_info=True)
        # Don't let logging failure fail the main operation, but log it.
        # await db.rollback() # Rollback should be handled by main context if this fails
    return None

@router.post(
    "/characters/{character_id}/activate_ability",
    response_model=AbilityActivationResponse,
    summary="Activate an ability for a character"
)
async def activate_ability_endpoint(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    character_id: str = Path(..., description="ID of the character activating the ability"),
    request_data: AbilityActivationRequest = Body(...),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Character {character_id} in guild {guild_id} attempting to activate ability {request_data.ability_id}")

    # 1. Fetch Character
    char_stmt = select(Character).where(Character.id == character_id, Character.guild_id == guild_id)
    char_result = await db.execute(char_stmt)
    db_character = char_result.scalars().first()
    if not db_character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Caster character {character_id} not found in guild {guild_id}.")

    # 2. Fetch Ability
    ability_stmt = select(Ability).where(Ability.id == request_data.ability_id, Ability.guild_id == guild_id)
    ability_result = await db.execute(ability_stmt)
    db_ability = ability_result.scalars().first()
    if not db_ability:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ability {request_data.ability_id} not found in guild {guild_id}.")

    # 3. Fetch Guild RulesConfig (example of using it)
    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    rules_result = await db.execute(rules_stmt)
    db_rules_config = rules_result.scalars().first()
    if not db_rules_config:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Guild configuration not found.")

    # --- Start Placeholder Logic for Ability Activation ---
    # TODO: Verify character owns/can use the ability (e.g., check db_character.abilities JSON)
    # TODO: Check RuleConfig for restrictions/modifiers (e.g., db_rules_config.config_data.get('disable_certain_abilities'))
    # TODO: Validate requirements (db_ability.requirements vs db_character.level, db_character.stats)
    # TODO: Deduct costs (db_ability.cost from db_character.current_hp, mp, etc.)

    activation_success = True
    activation_message = f"Ability '{db_ability.name_i18n.get('en', db_ability.id)}' activated by {db_character.name_i18n.get('en', db_character.id)}."
    simulated_effects = []
    consequences_for_log = {}

    if db_ability.cost:
        cost_str = ", ".join([f"{v} {k}" for k, v in db_ability.cost.items()])
        simulated_effects.append(AbilityActivationEffect(description=f"Cost deducted: {cost_str}"))
        consequences_for_log['cost_deducted'] = db_ability.cost
        # Actual deduction logic for db_character.current_hp, db_character.stats etc. would go here
        # e.g. db_character.current_hp -= db_ability.cost.get('hp',0)
        # db.add(db_character) # Mark character as dirty if stats change

    # --- End Placeholder Logic ---

    # 4. Stage the log entry (it will be committed with other changes)
    log_entry_model = await log_ability_activation(
        db, guild_id, character_id, db_character.player_id, # Pass player_id for log
        request_data.ability_id, db_ability.name_i18n,
        request_data, activation_success, activation_message, consequences_for_log
    )

    # If character stats or other models were changed, they are already added to the session (db.add(...)).
    # The commit will be handled by the get_db_session dependency wrapper.
    # If log_ability_activation fails to return a model, we might choose to proceed without it or error.
    # For now, we'll pass it to the response; if it's None, Pydantic will handle it if the field is Optional.

    # The actual commit of game state changes (character stats, etc.) and the log entry
    # will be handled by the `get_db_session` dependency manager when the endpoint successfully returns.
    # If any unhandled exception occurs here or before, `get_db_session` will roll back.

    return AbilityActivationResponse(
        success=activation_success,
        message=activation_message,
        caster_id=character_id,
        ability_id=request_data.ability_id,
        targets=request_data.target_ids,
        effects_summary=simulated_effects,
        log_entry=log_entry_model # Pass the GameLog model instance
    )
