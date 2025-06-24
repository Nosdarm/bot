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
    # For now, we'll just sort by a placeholder initiative if provided, or keep order.

    # If initiative is not set, assign a random one for sorting example
    for p in participants:
        if p.initiative is None:
            p.initiative = random.randint(1, 20)

    # Sort by initiative, highest first. Break ties by original order or another stat.
    sorted_participants = sorted(participants, key=lambda p: p.initiative, reverse=True)
    return [p.entity_id for p in sorted_participants]

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

    if combat.turn_log_structured is None: combat.turn_log_structured = []
    combat.turn_log_structured.append(log_entry_data.dict()) # Store as dict
    flag_modified(combat, "turn_log_structured")

    if combat.turn_order:
        combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
        if combat.current_turn_index == 0:
            combat.current_round += 1

    # The calling function will add 'combat' to session and commit.
    # We need to construct the CombatEncounterResponse from the potentially modified 'combat' model.
    # This will be done after commit and refresh in the main endpoint.
    # For now, return parts needed for CombatActionResponse, updated_combat_state will be filled by caller.
    return CombatActionResponse(
        success=True,
        message_i18n={"en": "Action processed."},
        action_log_entry=log_entry_data, # Pass the Pydantic model
        effects=effects,
        updated_combat_state=None # Placeholder, will be filled by caller
    )

# Note: apply_post_combat_updates_stub is now replaced by the imported function.
# The stub function definition has been removed.

# --- API Endpoints ---
@router.post("/start", response_model=CombatEncounterResponse, status_code=status.HTTP_201_CREATED, summary="Start a new combat encounter")
async def start_combat(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    combat_create_data: CombatEncounterCreate = Body(...),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Starting new combat in guild {guild_id} at location {combat_create_data.location_id}")

    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    rules_result = await db.execute(rules_stmt)
    db_rules_config = rules_result.scalars().first()

    turn_order_ids = await calculate_initiative(combat_create_data.participants_data)

    # Ensure participants_data is a list of dicts for the JSON field
    participants_as_dicts = [p.dict() for p in combat_create_data.participants_data]

    db_combat = Combat(
        guild_id=guild_id,
        location_id=combat_create_data.location_id,
        participants=participants_as_dicts,
        initial_positions=combat_create_data.initial_positions,
        combat_rules_snapshot=combat_create_data.combat_rules_snapshot or (db_rules_config.config_data if db_rules_config else {}),
        status="active",
        current_round=1,
        turn_order=turn_order_ids,
        current_turn_index=0,
        turn_log_structured=[]
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
    if db_combat.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Combat is not active (status: {db_combat.status}).")

    # TODO: Validate actor_entity_id is the current turn entity
    # if db_combat.turn_order and db_combat.turn_order[db_combat.current_turn_index] != action_request.actor_entity_id:
    #     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not the actor's turn.")

    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    rules_result = await db.execute(rules_stmt)
    db_rules_config = rules_result.scalars().first()

    action_response_parts = await process_combat_action(db, guild_id, db_combat, action_request, db_rules_config)

    db.add(db_combat)
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
    if db_combat.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Combat is not currently active (status: {db_combat.status}). Cannot end.")

    db_combat.status = f"completed_{resolution_data.outcome}"
    db.add(db_combat)

    await apply_post_combat_updates(db, guild_id, db_combat) # Use the new function

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
