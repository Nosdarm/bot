from fastapi import APIRouter, Depends, HTTPException, Body, Request, Header
from typing import Dict, Any, List, Optional

# from sqlalchemy.orm import Session # Not used directly for now
from bot.api.dependencies import get_db_session # Changed from get_db_service
from bot.game.managers.quest_manager import QuestManager
# from bot.services.db_service import DBService # Not directly used here if get_db_session is from dependencies
from bot.api.schemas.quest_schemas import PlayerEventPayloadSchema, QuestSchema, AIQuestGenerationRequestSchema # UPDATED Import

# Type hinting for GameManager and sub-components
from bot.game.managers.game_manager import GameManager
from bot.ai.prompt_context_collector import PromptContextCollector
from bot.ai.ai_data_models import GenerationContext

import logging
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/quests",
    tags=["quests"],
    responses={404: {"description": "Not found"}},
)

# Updated Dependency to get GameManager instance
async def get_game_manager(request: Request) -> GameManager:
    if not hasattr(request.app.state, 'game_manager') or not isinstance(request.app.state.game_manager, GameManager):
        logger.error("GameManager not found or not initialized correctly in app.state.")
        raise HTTPException(status_code=500, detail="Game services are not available.")
    return request.app.state.game_manager

# Placeholder for GM authentication
async def get_current_active_gm_user(user_id: Optional[str] = Header(None, alias="X-GM-User-ID")) -> str: # Example using a header
    if not user_id: # Replace with actual auth logic
        # raise HTTPException(status_code=403, detail="Not authorized as GM")
        logger.warning("GM Auth not implemented! Allowing /generate quest for 'test_gm_user'.")
        return "test_gm_user"
    return user_id

@router.post("/handle_event", summary="Handle a player event related to quests")
async def handle_player_event_endpoint(
    payload: PlayerEventPayloadSchema = Body(...),
    game_manager: GameManager = Depends(get_game_manager)
):
    """
    Receives an event from a player and processes it for quest progression.

    - **guild_id**: The ID of the guild where the event occurs.
    - **character_id**: The ID of the character triggering or involved in the event.
    - **event_data**: A dictionary containing details of the event (e.g., event_type, parameters).
    """
    logger.info(f"Received event for quest handling: Guild {payload.guild_id}, Char {payload.character_id}, Event Type: {payload.event_data.get('event_type')}")

    if not game_manager.quest_manager:
        logger.error("QuestManager not available via GameManager.")
        raise HTTPException(status_code=500, detail="Quest management service unavailable.")

    try:
        await game_manager.quest_manager.handle_player_event_for_quest(
            guild_id=payload.guild_id,
            character_id=payload.character_id,
            event_data=payload.event_data
        )
        return {"status": "success", "message": "Event processed for quests."}
    except NotImplementedError as nie: # Should ideally not happen if GameManager is correctly initialized
        logger.error(f"QuestManager functionality not fully resolved via GameManager: {nie}")
        raise HTTPException(status_code=501, detail="Quest processing functionality is not fully implemented.")
    except Exception as e:
        logger.error(f"Error processing player event for quests: Guild {payload.guild_id}, Char {payload.character_id}, Event {payload.event_data.get('event_type')}. Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while processing the event: {str(e)}")

@router.post(
    "/generate",
    response_model=Optional[QuestSchema],
    summary="Generate a new quest using AI (GM Only)"
)
async def generate_ai_quest(
    payload: AIQuestGenerationRequestSchema = Body(...),
    game_manager: GameManager = Depends(get_game_manager),
    gm_user: str = Depends(get_current_active_gm_user)
):
    logger.info(f"GM User '{gm_user}' initiating AI quest generation for guild '{payload.guild_id}'. Idea: '{payload.quest_idea}'")

    if not game_manager.prompt_context_collector:
        logger.error("PromptContextCollector not available via GameManager.")
        raise HTTPException(status_code=500, detail="AI context generation service unavailable.")
    if not game_manager.quest_manager:
        logger.error("QuestManager not available via GameManager.")
        raise HTTPException(status_code=500, detail="Quest management service unavailable.")

    try:
        # 1. Construct GenerationContext
        target_entity_id_for_context = payload.target_character_id
        target_entity_type_for_context = "character" if payload.target_character_id else None

        request_params_for_context = {"quest_idea": payload.quest_idea}

        gen_context = await game_manager.prompt_context_collector.get_full_context(
            guild_id=payload.guild_id,
            request_type="ai_quest_generation_gm",
            request_params=request_params_for_context,
            target_entity_id=target_entity_id_for_context,
            target_entity_type=target_entity_type_for_context
        )

        # 2. Call QuestManager to generate the quest
        generated_quest_pydantic = await game_manager.quest_manager.generate_quest_details_from_ai(
            guild_id=payload.guild_id,
            quest_idea=payload.quest_idea,
            generation_context_obj=gen_context,
            triggering_entity_id=payload.triggering_entity_id
        )

        if generated_quest_pydantic:
            return generated_quest_pydantic
        else:
            raise HTTPException(status_code=500, detail="AI quest generation failed or result was invalid.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during AI quest generation endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/character/{character_id}/active", response_model=List[QuestSchema], summary="List active quests for a character")
async def list_active_quests(
    character_id: str,
    guild_id: str,
    game_manager: GameManager = Depends(get_game_manager)
):
    """
    Retrieves a list of active quests for a given character in a specific guild.

    - **character_id**: The ID of the character whose active quests are to be listed.
    - **guild_id**: The ID of the guild to scope the search.
    """
    if not game_manager.quest_manager:
        logger.error("QuestManager not available via GameManager for listing active quests.")
        raise HTTPException(status_code=500, detail="Quest listing service unavailable.")
    try:
        active_quests_pydantic = await game_manager.quest_manager.get_active_quests_for_character(guild_id, character_id)
        return active_quests_pydantic
    except Exception as e:
        logger.error(f"Error listing active quests for char {character_id} in guild {guild_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while listing active quests: {str(e)}")

@router.get("/character/{character_id}/completed", response_model=List[QuestSchema], summary="List completed quests for a character")
async def list_completed_quests(
    character_id: str,
    guild_id: str,
    game_manager: GameManager = Depends(get_game_manager)
):
    """
    Retrieves a list of completed quests for a given character in a specific guild.

    - **character_id**: The ID of the character whose completed quests are to be listed.
    - **guild_id**: The ID of the guild to scope the search.
    """
    if not game_manager.quest_manager:
        logger.error("QuestManager not available via GameManager for listing completed quests.")
        raise HTTPException(status_code=500, detail="Quest listing service unavailable.")
    try:
        completed_quests_pydantic = await game_manager.quest_manager.get_completed_quests_for_character(guild_id, character_id)
        return completed_quests_pydantic
    except Exception as e:
        logger.error(f"Error listing completed quests for char {character_id} in guild {guild_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while listing completed quests: {str(e)}")
