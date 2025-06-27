# bot/api/routers/combat.py
from fastapi import APIRouter, Depends, HTTPException, Path, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import logging
from typing import List, Optional, Dict, Any
import uuid # For Combat ID if model doesn't auto-gen (it does now)
import random # For initiative example

from bot.api.dependencies import get_db_session
from bot.api.schemas.combat_schemas import (
    CombatEncounterCreate, CombatEncounterResponse, CombatParticipantData,
    CombatActionRequest, CombatActionResponse, CombatTurnLogEntry, CombatActionEffect,
    CombatResolutionRequest
)
from bot.database.models import Combat, Character, NPC, RulesConfig, GameLogEntry # Assuming NPC model exists, Changed GameLog
# For logging:
from bot.api.schemas.game_log_schemas import GameLogEntryCreate, ParticipatingEntity
from bot.game.combat_rewards import apply_post_combat_updates # Import the new function

logger = logging.getLogger(__name__)
router = APIRouter() # Prefix will be /api/v1/guilds/{guild_id}/combats

# --- Helper Functions (Placeholder) ---
async def calculate_initiative(participants: List[CombatParticipantData]) -> List[str]:
    # Basic initiative: random shuffle or could be based on participant stats
    # Returns ordered list of entity_ids
    # For this placeholder, just use the order they came in or shuffle
    # In a real system: roll dice (e.g., d20 + dexterity_modifier)

    # Ensure participants have an initiative value for sorting.
    # Pydantic's CombatParticipantData has initiative: Optional[int] = None.
    # We need to handle None if it's not set by the client.

    # Create a list of tuples (initiative_value, original_index, participant_data)
    # to ensure stable sort and handle None initiatives.
    indexed_participants: List[Tuple[int, int, CombatParticipantData]] = []
    for i, p_data in enumerate(participants):
        # Default initiative to 0 if None, or use a random roll if preferred for None.
        # For deterministic sorting in tests if no initiative is passed, 0 is fine.
        # In a real game, you might want to roll for None or use a default stat.
        initiative_val = p_data.initiative if p_data.initiative is not None else random.randint(1, 20)
        indexed_participants.append((initiative_val, i, p_data))

    # Sort by initiative (highest first), then by original index to maintain stability for ties.
    # Pydantic model instances are not directly comparable unless __lt__ etc. are defined.
    # Sorting based on a key that extracts the initiative value is correct.
    # The lambda p_tuple: p_tuple[0] correctly extracts the initiative value.
    sorted_indexed_participants = sorted(indexed_participants, key=lambda p_tuple: p_tuple[0], reverse=True)

    return [p_tuple[2].entity_id for p_tuple in sorted_indexed_participants]

async def process_combat_action(
    db: AsyncSession,
    guild_id: str,
    combat: Combat,
    action_request: CombatActionRequest,
    rules_config: Optional[RulesConfig] # RulesConfig can be None if not found, handle gracefully
) -> CombatActionResponse: # Return type is the Pydantic schema
    # Placeholder for detailed combat logic engine
    # 1. Validate action (actor's turn, ability/item usable, target valid, costs met etc.)
    # 2. Determine effects (damage, healing, status, movement)
    # 3. Update combat state (HP of participants, positions, status effects)
    # 4. Generate structured log entry for the action

    actor_id = action_request.actor_entity_id
    action_desc_i18n = {"en": f"{actor_id} performed {action_request.action_type}"}
    if action_request.target_entity_id:
        action_desc_i18n["en"] += f" on {action_request.target_entity_id}"
    if action_request.ability_id:
        action_desc_i18n["en"] += f" using ability {action_request.ability_id}"

    log_entry_data = CombatTurnLogEntry(
        round=combat.current_round,
        actor_entity_id=actor_id,
        action_description_i18n=action_desc_i18n,
        raw_action_details=action_request.dict()
    )

    effects = []
    if action_request.action_type == "attack" and action_request.target_entity_id:
        damage_amount = random.randint(5, 15)
        effects.append(CombatActionEffect(
            target_entity_id=action_request.target_entity_id,
            effect_type="damage",
            description_i18n={"en": f"Dealt {damage_amount} damage."},
            magnitude=damage_amount
        ))

        # Update target's current_hp in combat.participants (which is JSON data)
        # This requires careful handling as combat.participants is stored as JSON in DB
        # For the ORM model, combat.participants would be a Python list/dict
        if isinstance(combat.participants, list):
            for p_data_dict in combat.participants: # Assuming participants is a list of dicts
                if p_data_dict.get("entity_id") == action_request.target_entity_id:
                    p_data_dict["current_hp"] = max(0, p_data_dict.get("current_hp", 0) - damage_amount)
                    # Mark the combat object as modified if participants is a mutable JSON type
                    # For SQLAlchemy, if JSON is mutable (e.g. JSONB with mutable=True), this is enough.
                    # Otherwise, you might need to re-assign: combat.participants = list(combat.participants)
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(combat, "participants")
                    break

    # Ensure turn_log_structured is a list before appending
    current_log = combat.turn_log_structured
    if not isinstance(current_log, list):
        current_log = [] # Initialize if None or not a list
    current_log.append(log_entry_data.model_dump()) # Use model_dump() for Pydantic V2
    combat.turn_log_structured = current_log # Assign back if it was re-initialized

    from sqlalchemy.orm.attributes import flag_modified # Ensure import
    flag_modified(combat, "turn_log_structured")

    turn_order_list = combat.turn_order
    if isinstance(turn_order_list, list) and turn_order_list: # Ensure turn_order is a non-empty list
        current_turn_idx = combat.current_turn_index if isinstance(combat.current_turn_index, int) else 0
        new_turn_idx = (current_turn_idx + 1) % len(turn_order_list)
        combat.current_turn_index = new_turn_idx

        current_round_val = combat.current_round if isinstance(combat.current_round, int) else 0
        if new_turn_idx == 0:
            combat.current_round = current_round_val + 1
    else: # Handle empty or invalid turn_order
        logger.warning(f"Combat {combat.id}: Turn order is empty or invalid. Cannot advance turn.")
        # Optionally set combat status to error or handle as per game rules

    # The calling function will add 'combat' to session and commit.
    # This will be done after commit and refresh in the main endpoint.
    # For now, return parts needed for CombatActionResponse, updated_combat_state will be filled by caller.

    # Ensure updated_combat_state is None as it will be filled by the caller
    return CombatActionResponse(
        success=True,
        message_i18n={"en": "Action processed."},
        action_log_entry=log_entry_data,
        effects=effects,
        updated_combat_state=None
    )


# --- API Endpoints ---
@router.post("/start", response_model=CombatEncounterResponse, status_code=status.HTTP_201_CREATED, summary="Start a new combat encounter")
async def start_combat(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    combat_create_data: CombatEncounterCreate = Body(...),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Starting new combat in guild {guild_id} at location {combat_create_data.location_id}")

    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id) # Assuming RulesConfig model has guild_id
    rules_result = await db.execute(rules_stmt)
    db_rules_config_row = rules_result.scalars().first() # This is a RulesConfig DB model instance

    # Extract config_data (JSON) from the RulesConfig DB model instance
    rules_config_data_dict: Optional[Dict[str, Any]] = None
    if db_rules_config_row and hasattr(db_rules_config_row, 'config_data'):
        config_data_val = getattr(db_rules_config_row, 'config_data')
        if isinstance(config_data_val, dict):
            rules_config_data_dict = config_data_val
        elif isinstance(config_data_val, str):
            try:
                rules_config_data_dict = json.loads(config_data_val)
            except json.JSONDecodeError:
                logger.error(f"Could not parse RulesConfig.config_data JSON for guild {guild_id}")
                rules_config_data_dict = {} # Default if parsing fails
        else:
            rules_config_data_dict = {} # Default if not dict or str

    turn_order_ids = await calculate_initiative(combat_create_data.participants_data)
    participants_as_dicts = [p.model_dump() for p in combat_create_data.participants_data] # Use model_dump()

    db_combat = Combat(
        guild_id=guild_id,
        location_id=combat_create_data.location_id,
        participants=participants_as_dicts, # Should be List[Dict]
        initial_positions=combat_create_data.initial_positions, # Optional[Dict[str, Any]]
        combat_rules_snapshot=combat_create_data.combat_rules_snapshot or rules_config_data_dict or {}, # Ensure it's a dict
        status="active",
        current_round=1, # Ensure this is int
        turn_order=turn_order_ids, # Should be List[str]
        current_turn_index=0, # Ensure this is int
        turn_log_structured=[] # Should be List[Dict]
    )
    db.add(db_combat)
    try:
        await db.commit()
        await db.refresh(db_combat)
    except Exception as e:
        await db.rollback()
        logger.error(f"Error starting combat: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not start combat.")

    return CombatEncounterResponse.from_orm(db_combat)


@router.post("/{combat_id}/actions", response_model=CombatActionResponse, summary="Submit an action in a combat encounter")
async def submit_combat_action(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    combat_id: str = Path(..., description="ID of the ongoing combat"),
    action_request: CombatActionRequest = Body(...),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Action received for combat {combat_id} in guild {guild_id} by {action_request.actor_entity_id}")

    stmt = select(Combat).where(Combat.id == combat_id, Combat.guild_id == guild_id)
    result = await db.execute(stmt)
    db_combat = result.scalars().first()

    if not db_combat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Combat encounter not found.")

    combat_status = getattr(db_combat, 'status', None) # Safe access
    if combat_status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Combat is not active (status: {combat_status}).")

    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    rules_result = await db.execute(rules_stmt)
    db_rules_config_model = rules_result.scalars().first() # This is the SQLAlchemy model instance

    action_response_parts = await process_combat_action(db, guild_id, db_combat, action_request, db_rules_config_model) # Pass model

    db.add(db_combat) # db_combat was modified in process_combat_action
    try:
        await db.commit()
        await db.refresh(db_combat)
    except Exception as e:
        await db.rollback()
        logger.error(f"Error processing combat action for combat {combat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process combat action.")

    action_response_parts.updated_combat_state = CombatEncounterResponse.from_orm(db_combat)
    return action_response_parts


@router.post("/{combat_id}/end", response_model=CombatEncounterResponse, summary="End a combat encounter")
async def end_combat(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    combat_id: str = Path(..., description="ID of the combat to end"),
    resolution_data: CombatResolutionRequest = Body(...),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Ending combat {combat_id} in guild {guild_id} with outcome: {resolution_data.outcome}")
    stmt = select(Combat).where(Combat.id == combat_id, Combat.guild_id == guild_id)
    result = await db.execute(stmt)
    db_combat = result.scalars().first()

    if not db_combat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Combat encounter not found.")

    combat_status = getattr(db_combat, 'status', None) # Safe access
    if combat_status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Combat is not currently active (status: {combat_status}). Cannot end.")

    db_combat.status = f"completed_{resolution_data.outcome}" # Ensure status is string
    db.add(db_combat)

    await apply_post_combat_updates(db, guild_id, db_combat)

    try:
        await db.commit()
        await db.refresh(db_combat)
    except Exception as e:
        await db.rollback()
        logger.error(f"Error ending combat {combat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not end combat.")

    return CombatEncounterResponse.from_orm(db_combat)


@router.get("/{combat_id}", response_model=CombatEncounterResponse, summary="Get details of a specific combat encounter")
async def get_combat_encounter(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    combat_id: str = Path(..., description="ID of the combat encounter"),
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(Combat).where(Combat.id == combat_id, Combat.guild_id == guild_id)
    result = await db.execute(stmt)
    db_combat = result.scalars().first()
    if not db_combat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Combat encounter not found.")
    return CombatEncounterResponse.from_orm(db_combat)


@router.get("/", response_model=List[CombatEncounterResponse], summary="List combat encounters for the guild")
async def list_combat_encounters(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    status_filter: Optional[str] = Query(None, description="Filter by combat status (e.g., 'active', 'completed_victory_team_a')"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(Combat).where(Combat.guild_id == guild_id)
    if status_filter:
        stmt = stmt.where(Combat.status == status_filter)
    stmt = stmt.order_by(Combat.id.desc()) # Assuming new combats have later IDs or use a timestamp

    # Apply pagination after filtering and ordering
    stmt = stmt.offset(skip).limit(limit)

    result = await db.execute(stmt)
    combats = result.scalars().all()
    return [CombatEncounterResponse.from_orm(c) for c in combats]
