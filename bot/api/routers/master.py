from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional, Dict, Any, List

# Placeholder for actual user model and retrieval - for testing purposes
class User:
    id: str
    roles: List[str]

async def get_current_active_user_placeholder() -> User:
    # In a real app, this would decode a token or get session user
    # For now, return a dummy admin user for testing
    # This dummy user has a role that check_master_permissions will recognize as admin-like
    return User(id="placeholder_admin_user_api", roles=["bot_admin_placeholder_role"])

# Dependency for checking master/admin permissions
async def check_master_permissions(
    request: Request,
    guild_id: str,
    current_user: User = Depends(get_current_active_user_placeholder)
):
    # Ensure game_manager is initialized and available on the app state
    if not hasattr(request.app.state, 'game_manager') or not request.app.state.game_manager:
        # This might happen if the app startup sequence for GameManager failed
        raise HTTPException(status_code=503, detail="GameManager not available. Service might be starting up or in an error state.")

    game_mngr = request.app.state.game_manager

    if not hasattr(game_mngr, '_settings') or not game_mngr._settings:
         raise HTTPException(status_code=500, detail="GameManager settings not loaded.")

    # Check if bot admin (using settings)
    # Ensure bot_admins is a list of strings for comparison
    bot_admin_ids = [str(id_val) for id_val in game_mngr._settings.get('bot_admins', [])]
    if current_user.id in bot_admin_ids:
        return True # Bot admin has access

    # Check guild master role (simplified for placeholder user)
    # In a real scenario, current_user.roles would be checked against master_role_id from a JWT or session
    master_role_id_str = await game_mngr.get_master_role_id(guild_id)

    if master_role_id_str:
        # For the placeholder user, if a master role is configured for the guild,
        # and the placeholder user has the special 'bot_admin_placeholder_role', grant access.
        # This simulates an admin user or a user who has been granted the master role.
        if "bot_admin_placeholder_role" in current_user.roles:
            return True
        # In a real application, you would check:
        # if master_role_id_str in current_user.guild_specific_roles.get(guild_id, []):
        #     return True
        # For now, if master_role_id is set, and user is not bot_admin (checked above)
        # and not the placeholder admin type, deny unless further logic is added.
        # This means a regular placeholder user without the special role would be denied if a master role is set.

    # If none of the above conditions met, deny access.
    raise HTTPException(status_code=403, detail="Not authorized for this guild's master commands")

# Initialize APIRouter
router = APIRouter(
    prefix="/guilds/{guild_id}/master", # All routes in this file will have this prefix
    dependencies=[Depends(check_master_permissions)] # Apply permission check to all routes
)

# Import Pydantic models for request/response
from bot.api.schemas.master_schemas import ResolveConflictRequest, EditNpcRequest
from fastapi.responses import JSONResponse
import logging # For logging within endpoints
import traceback # For detailed error logging

logger = logging.getLogger(__name__)

from fastapi import Path, Query, Body # Ensure these are imported at the top of the file

# API endpoints will be added below this line

@router.post(
    "/resolve_conflict/{conflict_id}",
    response_model=Dict[str, Any], # Replace with a more specific success/error schema if available
    summary="Manually resolve a pending conflict.",
    responses={
        403: {"description": "User not authorized for this guild's master commands."},
        404: {"description": "Conflict ID not found (Note: current underlying logic might return 500/503 if ConflictResolver itself is missing or fails to find the conflict)."},
        503: {"description": "A required game manager component (e.g., ConflictResolver, GameLogManager) is not available."},
        500: {"description": "Internal server error during conflict resolution."}
    }
)
async def resolve_conflict(
    request: Request,
    guild_id: str, # Added: guild_id is part of the path prefix and FastAPI provides it here
    conflict_id: str = Path(..., description="The unique identifier of the conflict to be resolved.", example="conflict_abc123"),
    payload: ResolveConflictRequest = Body(..., description="Payload containing the outcome type and parameters for the resolution.")
):
    """
    Manually resolves a pending conflict within the specified guild.

    A Game Master (GM) or admin uses this endpoint to choose an outcome for a game conflict
    that requires manual intervention.

    - **conflict_id**: The unique ID of the conflict instance that needs resolution.
    - **payload**:
        - `outcome_type` (str): The chosen method or result for resolving the conflict (e.g., "player_wins_battle", "npc_escapes", "item_looted"). This type should be understood by the ConflictResolver service.
        - `parameters` (Optional[Dict[str, Any]]): An optional dictionary of parameters that might be needed by the specific `outcome_type` to correctly process the resolution (e.g., specific items awarded, XP amounts, next quest stage ID).

    Requires master or admin permissions for the guild.
    The resolution action, including the chosen outcome and parameters, is logged.
    Returns a JSON object confirming success or detailing failure.
    """
    game_mngr = request.app.state.game_manager # game_mngr is validated by check_master_permissions
    # Specific check for this endpoint's needs beyond global game_mngr availability
    if not game_mngr.conflict_resolver or not game_mngr.game_log_manager:
        raise HTTPException(status_code=503, detail="ConflictResolver or GameLogManager component is not available.")

    try:
        resolution_result = await game_mngr.conflict_resolver.process_master_resolution(
            conflict_id=conflict_id,
            guild_id=guild_id, # Pass guild_id to process_master_resolution
            outcome_type=payload.outcome_type,
            parameters=payload.parameters
        )

        log_details = {
            "conflict_id": conflict_id,
            "guild_id": guild_id,
            "outcome_type": payload.outcome_type,
            "parameters": payload.parameters,
            "success": resolution_result.get("success", False),
            "message": resolution_result.get("message", "No message"),
            "resolved_by_api": True,
            # Assuming current_user might be available if check_master_permissions adds it to request state
            "resolver_admin_id": getattr(request.state, "current_user_id", "unknown_api_user")
        }
        await game_mngr.game_log_manager.log_event(
            guild_id=guild_id,
            event_type="master_api_resolve_conflict",
            details=log_details
        )

        if resolution_result.get("success"):
            return JSONResponse(status_code=200, content={"message": "Conflict resolved successfully.", "details": resolution_result.get("message")})
        else:
            return JSONResponse(status_code=400, content={"message": "Failed to resolve conflict.", "details": resolution_result.get("message")})

    except Exception as e:
        logger.error(f"Error in resolve_conflict API for guild {guild_id}, conflict {conflict_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put(
    "/npcs/{npc_id}",
    response_model=Dict[str, Any], # Consider a more specific response model
    summary="Edit an NPC's attribute.",
    responses={
        400: {"description": "Invalid attribute or value type provided."},
        403: {"description": "User not authorized."},
        404: {"description": "NPC or related entity (e.g., location_id) not found."},
        503: {"description": "A required game manager component is not available."},
        500: {"description": "Internal server error."}
    }
)
async def edit_npc(
    request: Request,
    guild_id: str, # Added
    npc_id: str = Path(..., description="The unique ID of the NPC to edit.", example="npc_goblin_shaman_001"),
    payload: EditNpcRequest = Body(..., description="Specifies the NPC attribute to change and its new value.")
):
    """
    Edits a specific attribute of an Non-Player Character (NPC) within the guild.

    This endpoint allows authorized users (GMs/admins) to modify various aspects of an NPC.

    Supported attributes for editing currently include:
    - **I18n fields**: Localized names, descriptions, or persona traits.
        - `name_i18n.{lang_code}` (e.g., `name_i18n.en`, `name_i18n.ru`)
        - `description_i18n.{lang_code}`
        - `persona_i18n.{lang_code}`
    - **Stats**: Core game statistics of the NPC.
        - `stats.{stat_name}` (e.g., `stats.hp`, `stats.strength`, `stats.mana_regen_rate`).
          The value type will be inferred based on the existing stat's type or attempted for common numeric conversions (int, float, bool).
    - **Direct properties**: Key identifying or stateful properties of the NPC.
        - `location_id`: Updates the NPC's current location. The provided ID will be validated.
        - `faction_id`: Assigns the NPC to a specific faction.
        - `archetype`: Changes the NPC's archetype (e.g., "warrior", "mage", "merchant").
        - `role`: Defines a specific role for the NPC within its context or faction.

    The `value` field in the request payload must be of a type that is appropriate for the attribute being modified
    (e.g., a string for `name_i18n.en`, a number for `stats.hp`, a valid location ID for `location_id`).

    The action is logged for auditing purposes.
    Returns a confirmation message with details of the change or an error message if the update fails.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr.npc_manager or not game_mngr.game_log_manager or not game_mngr.location_manager: # LocationManager needed for location_id validation
        raise HTTPException(status_code=503, detail="Required managers (NpcManager, GameLogManager, LocationManager) are not available.")

    npc = game_mngr.npc_manager.get_npc(guild_id, npc_id)
    if not npc:
        raise HTTPException(status_code=404, detail=f"NPC with ID '{npc_id}' not found in guild '{guild_id}'.")

    try:
        original_value_str = "N/A"
        processed_value: Any = payload.value
        log_value = str(payload.value)
        attribute_to_update = payload.attribute
        update_successful = False

        # Determine NPC name for logging (best effort)
        # Assuming game_mngr has get_default_bot_language method
        lang_for_log = await game_mngr.get_default_bot_language() if hasattr(game_mngr, 'get_default_bot_language') else "en"

        npc_name_for_log = npc.id
        if hasattr(npc, 'name_i18n') and isinstance(npc.name_i18n, dict):
            npc_name_for_log = npc.name_i18n.get(lang_for_log, npc.name_i18n.get("en", npc.id))
        elif hasattr(npc, 'name'):
            npc_name_for_log = npc.name

        # i18n fields
        if attribute_to_update.startswith("name_i18n.") or \
           attribute_to_update.startswith("description_i18n.") or \
           attribute_to_update.startswith("persona_i18n."):
            parts = attribute_to_update.split(".", 1)
            field_name, lang_code = parts[0], parts[1]

            if not hasattr(npc, field_name):
                raise HTTPException(status_code=400, detail=f"NPC model does not have i18n field: '{field_name}'.")

            current_i18n_dict = getattr(npc, field_name, {})
            if not isinstance(current_i18n_dict, dict): current_i18n_dict = {}

            original_value_str = str(current_i18n_dict.get(lang_code, "N/A"))
            current_i18n_dict[lang_code] = str(payload.value) # Ensure value is string for i18n text
            processed_value = current_i18n_dict

            if hasattr(game_mngr.npc_manager, 'update_npc_field'):
                update_successful = await game_mngr.npc_manager.update_npc_field(guild_id, npc_id, field_name, processed_value)
            else:
                setattr(npc, field_name, processed_value)
                game_mngr.npc_manager.mark_npc_dirty(guild_id, npc_id)
                update_successful = True
            log_value = f"{str(payload.value)} (lang: {lang_code})"

        # Stats fields
        elif attribute_to_update.startswith("stats."):
            stat_key = attribute_to_update.split(".", 1)[1]
            current_stats = npc.stats if isinstance(npc.stats, dict) else {}
            original_value_str = str(current_stats.get(stat_key, "N/A"))

            target_type = type(current_stats.get(stat_key)) if stat_key in current_stats and current_stats[stat_key] is not None else None

            try:
                if target_type == bool: processed_value = str(payload.value).lower() in ['true', '1', 'yes']
                elif target_type == int: processed_value = int(payload.value)
                elif target_type == float: processed_value = float(payload.value)
                else: # Attempt common types if target_type is None or string
                    try: processed_value = int(payload.value)
                    except ValueError:
                        try: processed_value = float(payload.value)
                        except ValueError: processed_value = str(payload.value) # Fallback to string
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid value type for stat '{stat_key}'. Expected {target_type.__name__ if target_type else 'number'}.")

            update_successful = await game_mngr.npc_manager.update_npc_stats(guild_id, npc_id, {stat_key: processed_value})
            log_value = str(processed_value)

        # Direct fields
        elif attribute_to_update in ["location_id", "faction_id", "archetype", "role"]:
            if not hasattr(npc, attribute_to_update):
                 raise HTTPException(status_code=400, detail=f"NPC model does not have field: '{attribute_to_update}'.")

            original_value_str = str(getattr(npc, attribute_to_update, "N/A"))
            current_value = str(payload.value) # Keep it simple, treat as string from API
            processed_value = current_value if current_value.lower() not in ["none", "null", ""] else None

            if attribute_to_update == "location_id" and processed_value is not None:
                if not game_mngr.location_manager.get_location_instance(guild_id, processed_value):
                    raise HTTPException(status_code=404, detail=f"Location with ID '{processed_value}' not found.")

            if hasattr(game_mngr.npc_manager, 'update_npc_field'):
                update_successful = await game_mngr.npc_manager.update_npc_field(guild_id, npc_id, attribute_to_update, processed_value)
            else:
                setattr(npc, attribute_to_update, processed_value)
                game_mngr.npc_manager.mark_npc_dirty(guild_id, npc_id)
                update_successful = True
            log_value = str(processed_value)

        else:
            raise HTTPException(status_code=400, detail=f"Attribute '{attribute_to_update}' is not supported for API editing.")

        if update_successful:
            if attribute_to_update.startswith("stats.") and hasattr(game_mngr.npc_manager, 'trigger_stats_recalculation'):
                await game_mngr.npc_manager.trigger_stats_recalculation(guild_id, npc_id)

            log_details = {
                "npc_id": npc_id, "npc_name": npc_name_for_log,
                "attribute_changed": attribute_to_update,
                "old_value": original_value_str, "new_value": log_value,
                "edited_by_api": True,
                "admin_id": getattr(request.state, "current_user_id", "unknown_api_user")
            }
            await game_mngr.game_log_manager.log_event(guild_id, "master_api_edit_npc", log_details)
            return JSONResponse(status_code=200, content={
                "message": f"NPC '{npc_name_for_log}' ({npc_id}) updated successfully.",
                "attribute": attribute_to_update, "old_value": original_value_str, "new_value": log_value
            })
        else:
            raise HTTPException(status_code=500, detail=f"Failed to update NPC attribute '{attribute_to_update}'.")

    except HTTPException: # Re-raise HTTPExceptions directly
        raise
    except Exception as e:
        logger.error(f"Error editing NPC via API (guild: {guild_id}, npc: {npc_id}, attr: {payload.attribute}): {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error while editing NPC: {str(e)}")


@router.put(
    "/characters/{character_id}",
    response_model=Dict[str, Any], # Consider a more specific response model
    summary="Edit a player character's attribute.",
    responses={
        400: {"description": "Invalid attribute or value type provided."},
        403: {"description": "User not authorized."},
        404: {"description": "Character or related entity (e.g., location_id) not found."},
        503: {"description": "A required game manager component is not available."},
        500: {"description": "Internal server error."}
    }
)
async def edit_character(
    request: Request,
    guild_id: str, # Added
    character_id: str = Path(..., description="The Character UUID (string) or Discord User ID (numeric string) of the player character to edit.", example="char_uuid_player1_abc"),
    payload: EditCharacterRequest = Body(..., description="Specifies the character attribute to change and its new value.")
):
    """
    Edits a specific attribute of a player character within the guild.

    The character can be identified either by their internal Character ID (a UUID string, e.g., `char_abc123`)
    or by the Discord User ID of the player controlling them (a numeric string, e.g., `123456789012345678`).

    Supported attributes for editing:
    - **I18n Name**: `name_i18n.{lang_code}` (e.g., `name_i18n.fr`).
    - **Stats**: Core game statistics.
        - `stats.{stat_name}` (e.g., `stats.intelligence`, `stats.hp_current`). Value type is inferred or attempted.
    - **Direct Properties**: Key character traits and states.
        - `level` (int)
        - `experience` (int)
        - `unspent_xp` (int)
        - `hp` (float or int, current health)
        - `max_health` (float or int)
        - `location_id` (str, UUID of a valid location, or null)
        - `character_class` (str, class identifier)
        - `selected_language` (str, language code like "en" or "ru")
        - `is_alive` (bool)
        - `gold` (int)

    The `value` in the request payload must be of a type suitable for the target attribute.
    Requires master or admin permissions. Logs the edit action.
    Returns a confirmation message with details of the change or an error message.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr.character_manager or not game_mngr.game_log_manager or not game_mngr.location_manager:
        raise HTTPException(status_code=503, detail="Required managers (CharacterManager, GameLogManager, LocationManager) are not available.")

    # Try fetching by Discord ID first if character_id is all digits, then by Character UUID
    char = None
    if character_id.isdigit():
        char = game_mngr.character_manager.get_character_by_discord_id(guild_id, int(character_id))
    if not char: # If not found by Discord ID or if character_id was not digits
        char = game_mngr.character_manager.get_character(guild_id, character_id)

    if not char:
        raise HTTPException(status_code=404, detail=f"Character with identifier '{character_id}' not found in guild '{guild_id}'.")

    try:
        original_value_str = "N/A"
        processed_value: Any = payload.value
        log_value = str(payload.value)
        attribute_to_update = payload.attribute
        update_successful = False

        # Determine Character name for logging
        lang_for_log = await game_mngr.get_default_bot_language() if hasattr(game_mngr, 'get_default_bot_language') else "en"
        char_name_for_log = char.id
        if hasattr(char, 'name_i18n') and isinstance(char.name_i18n, dict):
            char_name_for_log = char.name_i18n.get(lang_for_log, char.name_i18n.get("en", char.id))
        elif hasattr(char, 'name'):
            char_name_for_log = char.name

        # i18n fields (e.g., name_i18n.en)
        if attribute_to_update.startswith("name_i18n."): # Add other i18n fields if Character has them
            parts = attribute_to_update.split(".", 1)
            field_name, lang_code = parts[0], parts[1]
            if not hasattr(char, field_name):
                raise HTTPException(status_code=400, detail=f"Character model does not have i18n field: '{field_name}'.")

            current_i18n_dict = getattr(char, field_name, {})
            if not isinstance(current_i18n_dict, dict): current_i18n_dict = {}

            original_value_str = str(current_i18n_dict.get(lang_code, "N/A"))
            current_i18n_dict[lang_code] = str(payload.value)
            processed_value = current_i18n_dict

            # Assuming CharacterManager has a generic field update or direct setattr + mark_dirty
            setattr(char, field_name, processed_value)
            game_mngr.character_manager.mark_character_dirty(guild_id, char.id)
            update_successful = True
            log_value = f"{str(payload.value)} (lang: {lang_code})"

        # Stats fields (e.g., stats.hp, stats.strength)
        elif attribute_to_update.startswith("stats."):
            stat_key = attribute_to_update.split(".", 1)[1]
            current_stats = char.stats if isinstance(char.stats, dict) else {}
            original_value_str = str(current_stats.get(stat_key, "N/A"))
            target_type = type(current_stats.get(stat_key)) if stat_key in current_stats and current_stats[stat_key] is not None else None

            try:
                if target_type == bool: processed_value = str(payload.value).lower() in ['true', '1', 'yes']
                elif target_type == int: processed_value = int(payload.value)
                elif target_type == float: processed_value = float(payload.value)
                else: # Attempt common types
                    try: processed_value = int(payload.value)
                    except ValueError:
                        try: processed_value = float(payload.value)
                        except ValueError: processed_value = str(payload.value)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid value type for stat '{stat_key}'. Expected {target_type.__name__ if target_type else 'number'}.")

            update_successful = await game_mngr.character_manager.update_character_stats(guild_id, char.id, {stat_key: processed_value})
            log_value = str(processed_value)

        # Direct, simple fields (level, experience, hp, max_health, location_id, etc.)
        elif attribute_to_update in ["level", "experience", "unspent_xp", "hp", "max_health", "location_id", "character_class", "selected_language", "is_alive", "gold"]:
            if not hasattr(char, attribute_to_update):
                 raise HTTPException(status_code=400, detail=f"Character model does not have field: '{attribute_to_update}'.")
            original_value_str = str(getattr(char, attribute_to_update, "N/A"))

            # Type conversion for specific fields
            if attribute_to_update in ["level", "experience", "unspent_xp", "gold"]:
                try: processed_value = int(payload.value)
                except ValueError: raise HTTPException(status_code=400, detail=f"Invalid value for '{attribute_to_update}'. Expected integer.")
            elif attribute_to_update in ["hp", "max_health"]:
                try: processed_value = float(payload.value)
                except ValueError: raise HTTPException(status_code=400, detail=f"Invalid value for '{attribute_to_update}'. Expected float.")
            elif attribute_to_update == "is_alive":
                processed_value = str(payload.value).lower() in ['true', '1', 'yes']
            elif attribute_to_update == "location_id":
                processed_value = str(payload.value) if str(payload.value).lower() not in ["none", "null", ""] else None
                if processed_value and not game_mngr.location_manager.get_location_instance(guild_id, processed_value):
                    raise HTTPException(status_code=404, detail=f"Location with ID '{processed_value}' not found.")
            else: # character_class, selected_language - keep as string
                processed_value = str(payload.value)

            # Use specific update methods if they exist (like update_character_location)
            if attribute_to_update == "location_id":
                update_successful = await game_mngr.character_manager.update_character_location(char.id, processed_value, guild_id)
            elif attribute_to_update in ["level", "experience", "unspent_xp", "hp", "max_health", "is_alive", "gold"]: # These are often stats
                 update_successful = await game_mngr.character_manager.update_character_stats(guild_id, char.id, {attribute_to_update: processed_value})
            else: # Fallback for other direct fields like character_class, selected_language
                setattr(char, attribute_to_update, processed_value)
                game_mngr.character_manager.mark_character_dirty(guild_id, char.id)
                if attribute_to_update == "character_class": # Stats might depend on class
                    await game_mngr.character_manager.trigger_stats_recalculation(guild_id, char.id)
                update_successful = True
            log_value = str(processed_value)

        else:
            raise HTTPException(status_code=400, detail=f"Attribute '{attribute_to_update}' is not supported for API editing on Characters.")

        if update_successful:
            # Some attributes might require stats recalculation
            if attribute_to_update.startswith("stats.") or attribute_to_update in ["level", "character_class"]:
                 if hasattr(game_mngr.character_manager, 'trigger_stats_recalculation'):
                    await game_mngr.character_manager.trigger_stats_recalculation(guild_id, char.id)

            log_details = {
                "character_id": char.id, "character_name": char_name_for_log, "discord_user_id": str(char.discord_user_id),
                "attribute_changed": attribute_to_update,
                "old_value": original_value_str, "new_value": log_value,
                "edited_by_api": True,
                "admin_id": getattr(request.state, "current_user_id", "unknown_api_user")
            }
            await game_mngr.game_log_manager.log_event(guild_id, "master_api_edit_character", log_details)
            return JSONResponse(status_code=200, content={
                "message": f"Character '{char_name_for_log}' ({char.id}) updated successfully.",
                "attribute": attribute_to_update, "old_value": original_value_str, "new_value": log_value
            })
        else:
            # This path might not be reached if updates directly raise errors or return False and are handled.
            raise HTTPException(status_code=500, detail=f"Failed to update Character attribute '{attribute_to_update}'.")

    except HTTPException: # Re-raise HTTPExceptions directly
        raise
    except Exception as e:
        logger.error(f"Error editing Character via API (guild: {guild_id}, char_id: {character_id}, attr: {payload.attribute}): {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error while editing Character: {str(e)}")


@router.put(
    "/items/{item_instance_id}",
    response_model=Dict[str, Any], # Consider a more specific response model
    summary="Edit an item instance's attribute.",
    responses={
        400: {"description": "Invalid attribute, value type, or quantity provided."},
        403: {"description": "User not authorized."},
        404: {"description": "Item instance not found."},
        503: {"description": "A required game manager component is not available."},
        500: {"description": "Internal server error."}
    }
)
async def edit_item_instance(
    request: Request,
    guild_id: str, # Added
    item_instance_id: str = Path(..., description="The unique ID of the item instance to be edited.", example="item_instance_xyz789"),
    payload: EditItemRequest = Body(..., description="Specifies the item attribute to change and its new value.")
):
    """
    Edits a specific attribute of an existing item instance within the guild.

    Item instances are unique occurrences of item templates, potentially owned by characters, NPCs, or located on the ground.

    Supported attributes for editing:
    - **State Variables**: Custom key-value pairs stored on the item.
        - `state_variables.{key_name}` (e.g., `state_variables.charges_remaining`, `state_variables.is_activated`).
          The type of the value will be inferred if the key exists, otherwise common types (bool, int, float, str) are attempted.
    - **Quantity**: `quantity`. Must be a positive number (float or int).
    - **Ownership/Location**:
        - `owner_id` (str, UUID of a Character or NPC): Assigns the item to an entity. Clears `location_id`.
        - `owner_type` (str, "Character" or "NPC"): Must be set if `owner_id` is set.
        - `location_id` (str, UUID of a Location): Places the item on the ground at a location. Clears `owner_id` and `owner_type`.

    The `value` in the request payload must be appropriate for the attribute being modified.
    Requires master or admin permissions. Logs the edit action.
    Returns a confirmation message or an error.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr.item_manager or not game_mngr.game_log_manager:
        raise HTTPException(status_code=503, detail="ItemManager or GameLogManager is not available.")

    item_instance = game_mngr.item_manager.get_item_instance(guild_id, item_instance_id)
    if not item_instance:
        raise HTTPException(status_code=404, detail=f"Item instance with ID '{item_instance_id}' not found in guild '{guild_id}'.")

    try:
        original_value_str = "N/A"
        processed_payload_for_update: Dict[str, Any] = {} # Payload for ItemManager.update_item_instance
        log_new_value = str(payload.value) # For logging, generally stringified version of input
        attribute_to_update = payload.attribute

        # Item name for logging
        item_template_name = item_instance.template_id
        template = game_mngr.item_manager.get_item_template(item_instance.template_id)
        if template:
            lang_for_log = await game_mngr.get_default_bot_language() if hasattr(game_mngr, 'get_default_bot_language') else "en"
            item_template_name = template.get("name_i18n", {}).get(lang_for_log, template.get("name_i18n", {}).get("en", item_instance.template_id))

        # state_variables.some_key
        if attribute_to_update.startswith("state_variables."):
            key = attribute_to_update.split(".", 1)[1]
            if not isinstance(item_instance.state_variables, dict):
                item_instance.state_variables = {} # Ensure it's a dict

            original_value_str = str(item_instance.state_variables.get(key, "N/A"))

            # Try to infer type from existing value if possible, else flexible conversion
            typed_value = payload.value
            if key in item_instance.state_variables and item_instance.state_variables[key] is not None:
                try: typed_value = type(item_instance.state_variables[key])(payload.value)
                except (ValueError, TypeError): pass # Keep payload.value if type cast fails
            elif isinstance(payload.value, str): # Common conversions for string input
                 if payload.value.lower() == 'true': typed_value = True
                 elif payload.value.lower() == 'false': typed_value = False
                 elif payload.value.isdigit(): typed_value = int(payload.value)
                 else:
                    try: typed_value = float(payload.value)
                    except ValueError: pass # Keep as string if not floatable

            item_instance.state_variables[key] = typed_value
            processed_payload_for_update["state_variables"] = item_instance.state_variables
            log_new_value = str(typed_value)

        # quantity
        elif attribute_to_update == "quantity":
            original_value_str = str(item_instance.quantity)
            try:
                new_quantity = float(payload.value)
                if new_quantity <= 0:
                    raise HTTPException(status_code=400, detail="Quantity must be positive.")
                processed_payload_for_update["quantity"] = new_quantity
                log_new_value = str(new_quantity)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid quantity. Expected a number.")

        # owner_id, owner_type, location_id
        elif attribute_to_update in ["owner_id", "owner_type", "location_id"]:
            original_value_str = str(getattr(item_instance, attribute_to_update, "N/A"))
            new_val = str(payload.value) if str(payload.value).lower() not in ["none", "null", ""] else None
            processed_payload_for_update[attribute_to_update] = new_val
            log_new_value = str(new_val)

            # Logic for clearing other owner/location fields if one is set
            if attribute_to_update == "owner_id" and new_val:
                processed_payload_for_update["location_id"] = None
                # owner_type should be explicitly set if owner_id is set.
                # If not provided in this request, it might need to be part of the same request or handled by manager.
            elif attribute_to_update == "location_id" and new_val:
                processed_payload_for_update["owner_id"] = None
                processed_payload_for_update["owner_type"] = None

        else:
            raise HTTPException(status_code=400, detail=f"Attribute '{attribute_to_update}' is not supported for item instance editing via API.")

        if not processed_payload_for_update:
             raise HTTPException(status_code=400, detail="No valid changes detected for the item instance.")

        update_successful = await game_mngr.item_manager.update_item_instance(guild_id, item_instance_id, processed_payload_for_update)

        if update_successful:
            game_mngr.item_manager.mark_item_dirty(guild_id, item_instance_id) # Ensure cache is updated if necessary
            log_details = {
                "item_instance_id": item_instance_id, "item_template_name": item_template_name,
                "attribute_changed": attribute_to_update,
                "old_value": original_value_str, "new_value": log_new_value,
                "edited_by_api": True,
                "admin_id": getattr(request.state, "current_user_id", "unknown_api_user")
            }
            await game_mngr.game_log_manager.log_event(guild_id, "master_api_edit_item", log_details)
            return JSONResponse(status_code=200, content={
                "message": f"Item instance '{item_template_name}' ({item_instance_id}) updated successfully.",
                "attribute": attribute_to_update, "old_value": original_value_str, "new_value": log_new_value
            })
        else:
            raise HTTPException(status_code=500, detail=f"Failed to update item instance attribute '{attribute_to_update}'.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error editing item instance via API (guild: {guild_id}, item: {item_instance_id}, attr: {payload.attribute}): {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error while editing item instance: {str(e)}")


@router.post(
    "/launch_event",
    response_model=Dict[str, Any], # Consider a more specific response model for created event
    summary="Manually launch a game event from a template.",
    status_code=201, # For successful creation
    responses={
        400: {"description": "Invalid payload (e.g., bad channel_id format, missing required template_id)."},
        403: {"description": "User not authorized."},
        404: {"description": "Event template, specified location, or a player ID not found."},
        503: {"description": "A required game manager component is not available."},
        500: {"description": "Internal server error during event launch."}
    }
)
async def launch_event(
    request: Request,
    guild_id: str, # Added
    payload: LaunchEventRequest = Body(..., description="Details of the event to launch, including the template ID and optional overrides for location, channel, and involved players.")
):
    """
    Manually launches a game event within the specified guild based on a pre-defined event template.

    This allows GMs or admins to trigger specific game occurrences or storylines at will.

    - **payload**:
        - `template_id` (str): The unique ID of the event template to be used for creating the event instance. This template must exist in the guild's configuration.
        - `location_id` (Optional[str]): If provided, specifies the ID of the location where the event should occur or be primarily associated. The location must exist.
        - `channel_id` (Optional[str]): If provided, specifies a Discord channel ID to associate with this event instance, potentially for notifications or event-specific interactions. Must be a numeric string.
        - `player_ids` (Optional[List[str]]): A list of player character IDs to directly involve in this event. Each player character ID must exist.

    Requires master or admin permissions for the guild.
    The launch of the event instance is logged.
    Returns a JSON object with details of the newly created event instance upon successful launch, otherwise an error message.
    """
    game_mngr = request.app.state.game_manager
    # Validation within the endpoint also checks for location_manager and character_manager if IDs are provided in payload
    if not game_mngr.event_manager or not game_mngr.game_log_manager:
        raise HTTPException(status_code=503, detail="Required managers (EventManager, GameLogManager, etc.) are not available.")

    event_template = game_mngr.event_manager.get_event_template(guild_id, payload.template_id)
    if not event_template:
        raise HTTPException(status_code=404, detail=f"Event template with ID '{payload.template_id}' not found in guild '{guild_id}'.")

    # Validate optional location_id if provided
    if payload.location_id and not game_mngr.location_manager.get_location_instance(guild_id, payload.location_id):
        raise HTTPException(status_code=404, detail=f"Location with ID '{payload.location_id}' not found.")

    # Validate optional channel_id (basic check if it's a digit string)
    processed_channel_id: Optional[int] = None
    if payload.channel_id:
        if not payload.channel_id.isdigit():
            raise HTTPException(status_code=400, detail="Invalid channel_id format. Expected digits.")
        processed_channel_id = int(payload.channel_id)

    # Validate player_ids if provided (check if characters exist)
    if payload.player_ids:
        for p_id in payload.player_ids:
            if not game_mngr.character_manager.get_character(guild_id, p_id):
                 # Also check if it's a discord ID
                if not (p_id.isdigit() and game_mngr.character_manager.get_character_by_discord_id(guild_id, int(p_id))):
                    raise HTTPException(status_code=404, detail=f"Player with ID '{p_id}' not found.")

    try:
        created_event_instance = await game_mngr.event_manager.create_event_from_template(
            guild_id=guild_id,
            template_id=payload.template_id,
            location_id=payload.location_id,
            player_ids=payload.player_ids,
            channel_id_override=processed_channel_id,
            # context_entities might be needed if your create_event_from_template supports it
        )

        if created_event_instance:
            event_name_for_log = getattr(created_event_instance, 'name', payload.template_id)
            log_details = {
                "event_id": created_event_instance.id,
                "event_name": event_name_for_log,
                "template_id": payload.template_id,
                "location_id": payload.location_id,
                "channel_id": processed_channel_id,
                "player_ids": payload.player_ids,
                "launched_by_api": True,
                "admin_id": getattr(request.state, "current_user_id", "unknown_api_user")
            }
            await game_mngr.game_log_manager.log_event(guild_id, "master_api_launch_event", log_details)

            return JSONResponse(status_code=201, content={ # 201 Created
                "message": f"Event '{event_name_for_log}' (ID: {created_event_instance.id}) launched successfully from template '{payload.template_id}'.",
                "event_id": created_event_instance.id,
                "event_name": event_name_for_log
            })
        else:
            raise HTTPException(status_code=500, detail=f"Failed to launch event from template '{payload.template_id}'.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error launching event via API (guild: {guild_id}, template: {payload.template_id}): {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error while launching event: {str(e)}")


@router.post(
    "/set_rule",
    response_model=Dict[str, Any], # Consider a more specific response model
    summary="Set or update a specific game rule for the guild.",
    responses={
        400: {"description": "Invalid rule_key format or value type inconsistent with existing rule structure."},
        403: {"description": "User not authorized."},
        503: {"description": "A required game manager component (DBService, GameLogManager, RuleEngine) is not available."},
        500: {"description": "Internal server error while setting the rule or reloading RuleEngine."}
    }
)
async def set_rule(
    request: Request,
    guild_id: str, # Added
    payload: SetRuleRequest = Body(..., description="The game rule key (using dot-notation for nesting) and its new value. The value can be any valid JSON type (string, number, boolean, array, object).")
):
    """
    Sets or updates a specific game rule for the guild.

    Game rules are typically stored in a structured format (e.g., a JSON object within the database's `rules_config` table)
    and can have nested properties. The `rule_key` uses dot-notation (e.g., `combat.max_rounds`,
    `economy.shop_restock_interval_hours`, `player_start.initial_items`) to specify the exact path to the rule
    that needs to be modified or created.

    - **payload**:
        - `rule_key` (str): The dot-separated path to the rule. If the path or parts of it do not exist, they will be created.
        - `value` (Any): The new value for the rule. This can be any valid JSON type: a string, number, boolean, list (array), or dictionary (object).
                         FastAPI will parse the JSON value from the request body into the appropriate Python type.

    Requires master or admin permissions for the guild.
    The action of setting or updating a rule is logged. After successfully saving the change to the database,
    the RuleEngine's configuration for the specific guild is reloaded to ensure the change takes immediate effect in the game logic.
    Returns a confirmation message including the rule key and its new value, or an error message if the update fails.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr.db_service or not game_mngr.game_log_manager or not game_mngr.rule_engine:
        raise HTTPException(status_code=503, detail="DBService, GameLogManager, or RuleEngine is not available.")

    try:
        # Fetch current rules_config for the guild
        # Assuming 'rules_config' table and 'guild_id' as PK, 'config_data' as JSON column
        # This part is highly dependent on DBService.get_entity or a specific method for rules_config
        rules_entity = await game_mngr.db_service.get_entity(
            table_name='rules_config',
            entity_id=guild_id,
            id_field='guild_id' # Assuming guild_id is the primary key or unique ID for rules_config
        )

        current_config_data: Dict[str, Any]
        if rules_entity and 'config_data' in rules_entity:
            config_data_from_db = rules_entity['config_data']
            if isinstance(config_data_from_db, str):
                try:
                    current_config_data = json.loads(config_data_from_db)
                except json.JSONDecodeError:
                    # This case should ideally not happen if data is saved correctly.
                    # Consider if a default structure should be used or error out.
                    logger.error(f"Corrupted JSON in rules_config for guild {guild_id}. Starting with new default.")
                    current_config_data = {} # Or load a default schema
            elif isinstance(config_data_from_db, dict):
                current_config_data = config_data_from_db
            else:
                logger.error(f"Unexpected type for rules_config data for guild {guild_id}: {type(config_data_from_db)}. Starting new.")
                current_config_data = {}
        else:
            logger.info(f"No existing rules_config for guild {guild_id}. Creating new one.")
            current_config_data = {} # Start with an empty config if none exists

        # Parse rule_key and update nested dictionary
        keys = payload.rule_key.split('.')
        temp_dict = current_config_data
        original_value_str = "N/A (key might be new)"

        for i, key_part in enumerate(keys[:-1]):
            if key_part not in temp_dict or not isinstance(temp_dict[key_part], dict):
                # If path doesn't exist, create it.
                temp_dict[key_part] = {}
            temp_dict = temp_dict[key_part]

        final_key = keys[-1]
        if final_key in temp_dict:
            original_value_str = str(temp_dict[final_key])

        # FastAPI has already parsed payload.value from JSON body to Python type
        temp_dict[final_key] = payload.value

        # Save updated rules_config back to DB
        # Assuming DBService.update_entity or a specific method for rules_config
        # If rules_entity was None, this means we need to create a new record.
        if rules_entity:
            update_success = await game_mngr.db_service.update_entity(
                table_name='rules_config',
                entity_id=guild_id, # guild_id is the PK for rules_config
                data={'config_data': current_config_data}, # Pass the whole updated dict
                id_field='guild_id'
            )
        else: # Create new rules_config entry
            # The create_entity method needs to handle the case where 'id' is not part of data if id_field is different
            # For rules_config, guild_id is the identifier.
            created_id = await game_mngr.db_service.create_entity(
                table_name='rules_config',
                data={'guild_id': guild_id, 'config_data': current_config_data},
                id_field='guild_id'
            )
            update_success = created_id is not None


        if not update_success:
            raise HTTPException(status_code=500, detail="Failed to save updated game rules to database.")

        # Reload rules in RuleEngine for the guild
        await game_mngr.rule_engine.load_rules_config_for_guild(guild_id)

        log_details = {
            "guild_id": guild_id,
            "rule_key": payload.rule_key,
            "old_value": original_value_str,
            "new_value": payload.value, # Log the direct Python value
            "set_by_api": True,
            "admin_id": getattr(request.state, "current_user_id", "unknown_api_user")
        }
        await game_mngr.game_log_manager.log_event(guild_id, "master_api_set_rule", log_details)

        return JSONResponse(status_code=200, content={
            "message": f"Game rule '{payload.rule_key}' for guild '{guild_id}' updated successfully.",
            "rule_key": payload.rule_key,
            "new_value": payload.value
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting game rule via API (guild: {guild_id}, key: {payload.rule_key}): {e}\n{traceback.format_exc()}")
        # Need to import json for this specific exception handling if it's still needed due to direct json.loads
        # from json import JSONDecodeError
        # if isinstance(e, JSONDecodeError): # Should not happen if payload.value is used directly
        #    raise HTTPException(status_code=400, detail=f"Invalid JSON format for value: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error while setting game rule: {str(e)}")

# Need to import Simulators and SimpleReportFormatter, uuid
from bot.game.simulation import BattleSimulator, QuestSimulator, ActionConsequenceModeler
from bot.game.services.report_formatter import SimpleReportFormatter
import uuid
# Also ensure master_schemas are imported if not already at the top
from bot.api.schemas.master_schemas import RunSimulationRequest, SimulationReportResponse
import json # Required for get_entity in set_rule, and potentially in view_simulation_report if details are strings

@router.post(
    "/simulations/run",
    response_model=SimulationReportResponse,
    summary="Run a game simulation (battle, quest, action consequence).",
    status_code=200, # Or 201 if a simulation instance resource were created and identifiable by URL
    responses={
        400: {"description": "Invalid simulation_type or parameters provided."},
        403: {"description": "User not authorized."},
        503: {"description": "A required game manager or simulation component is not available."},
        500: {"description": "Internal server error during simulation execution."}
    }
)
async def run_simulation(
    request: Request,
    guild_id: str, # Added
    payload: RunSimulationRequest = Body(..., description="Specifies the type of simulation to run, its parameters, and the desired language for the report output.")
):
    """
    Runs a game simulation based on the provided type and parameters.

    This endpoint allows for testing game mechanics, balancing, or predicting outcomes by simulating
    complex game scenarios such as battles, quest progressions, or the consequences of specific actions.

    - **payload**:
        - `simulation_type` (str): Defines the type of simulation to execute.
          Valid types are: "battle", "quest", "action_consequence".
        - `params` (Dict[str, Any]): A dictionary containing parameters specific to the chosen `simulation_type`.
          For example, for a "battle" simulation, this might include lists of participants for each team and any battle-specific rules.
          For a "quest", it might include the quest ID and participating character IDs.
        - `language` (Optional[str]): The language code (e.g., "en", "ru") for generating the `formatted_report`. Defaults to "en".

    Requires master or admin permissions.
    The simulation run, including its parameters and the raw output, is logged with a unique `report_id`.
    The response includes this `report_id`, the `simulation_type`, a human-readable `formatted_report` of the outcome,
    and the `raw_report` data (structured JSON).
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr:
        raise HTTPException(status_code=503, detail="GameManager not available.")

    # Check for essential managers needed by all simulations or the process itself
    required_managers = ['character_manager', 'npc_manager', 'rule_engine', 'game_log_manager',
                         'item_manager', 'event_manager', 'combat_manager', 'relationship_manager',
                         'location_manager']
    if payload.simulation_type == "quest":
        required_managers.append('quest_manager')

    for manager_name in required_managers:
        if not hasattr(game_mngr, manager_name) or getattr(game_mngr, manager_name) is None:
            raise HTTPException(status_code=500, detail=f"{manager_name.replace('_', ' ').capitalize()} not available.")

    report_id = str(uuid.uuid4())
    raw_report_data: Optional[Dict[str, Any]] = None # For battle/quest
    raw_report_data_list: Optional[List[Dict[str, Any]]] = None # For action_consequence
    formatted_report_str: str = ""

    sim_params = payload.params

    try:
        formatter = SimpleReportFormatter(game_mngr, guild_id)

        if payload.simulation_type == "battle":
            simulator = BattleSimulator(guild_id, game_mngr.character_manager, game_mngr.npc_manager,
                                        game_mngr.combat_manager, game_mngr.rule_engine, game_mngr.item_manager)
            raw_report_data = await simulator.simulate_full_battle(
                participants_setup=sim_params.get('participants_setup', []),
                rules_config_override_data=sim_params.get('rules_config_override_data'),
                max_rounds=sim_params.get('max_rounds', 50)
            )
            if raw_report_data:
                formatted_report_str = formatter.format_battle_report(raw_report_data, payload.language)

        elif payload.simulation_type == "quest":
            quest_definitions = getattr(game_mngr.quest_manager, 'get_all_quest_definitions', lambda gid: {})(guild_id)
            if not quest_definitions and not sim_params.get('quest_definitions_override'):
                raise HTTPException(status_code=400, detail="Quest definitions not found and no override provided.")

            simulator = QuestSimulator(guild_id, game_mngr.character_manager, game_mngr.event_manager,
                                       game_mngr.rule_engine, sim_params.get('quest_definitions_override', quest_definitions))
            raw_report_data = await simulator.simulate_full_quest(
                quest_id=sim_params.get('quest_id', ''),
                character_ids=sim_params.get('character_ids', []),
                rules_config_override_data=sim_params.get('rules_config_override_data'),
                max_stages=sim_params.get('max_stages', 20)
            )
            if raw_report_data:
                formatted_report_str = formatter.format_quest_report(raw_report_data, payload.language)

        elif payload.simulation_type == "action_consequence":
            simulator = ActionConsequenceModeler(guild_id, game_mngr.character_manager, game_mngr.npc_manager,
                                                 game_mngr.rule_engine, game_mngr.relationship_manager, game_mngr.event_manager)
            # Ensure action_description is a dict, not a string, if the modeler expects a dict.
            action_desc = sim_params.get('action_description', {})
            if isinstance(action_desc, str): # Basic check, might need more robust parsing if stringified JSON is possible
                try: action_desc = json.loads(action_desc)
                except json.JSONDecodeError: raise HTTPException(status_code=400, detail="action_description must be a valid JSON object if provided as string.")

            raw_report_data_list = await simulator.analyze_action_consequences(
                action_description=action_desc,
                actor_id=sim_params.get('actor_id', ''),
                actor_type=sim_params.get('actor_type', ''),
                target_id=sim_params.get('target_id'),
                target_type=sim_params.get('target_type'),
                rules_config_override_data=sim_params.get('rules_config_override_data')
            )
            if raw_report_data_list: # This simulator returns a List[Dict]
                formatted_report_str = formatter.format_action_consequence_report(raw_report_data_list, payload.language)
                # For logging, we'll store the list as the 'report' value.
                # For the response, SimulationReportResponse expects raw_report: Dict.
                # We'll wrap the list in a dict for consistency or adjust the response model.
                # For now, wrapping:
                raw_report_data = {"consequences": raw_report_data_list}


        else:
            raise HTTPException(status_code=400, detail=f"Unknown simulation type: {payload.simulation_type}")

        if raw_report_data is None and raw_report_data_list is None: # if simulation didn't produce data
             raise HTTPException(status_code=500, detail="Simulation did not produce any data.")


        log_details = {
            "report_id": report_id,
            "simulation_type": payload.simulation_type,
            "params": payload.params,
            "report_data": raw_report_data if raw_report_data is not None else raw_report_data_list, # Log the actual raw data structure
            "run_by_api": True,
            "admin_id": getattr(request.state, "current_user_id", "unknown_api_user")
        }
        await game_mngr.game_log_manager.log_event(guild_id, "master_api_simulation_run", log_details)

        # Ensure raw_report for the response is a Dict[str, Any]
        final_raw_report_for_response = raw_report_data if raw_report_data is not None else \
                                       ({"consequences": raw_report_data_list} if raw_report_data_list is not None else {})


        return SimulationReportResponse(
            report_id=report_id,
            simulation_type=payload.simulation_type,
            formatted_report=formatted_report_str,
            raw_report=final_raw_report_for_response
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running simulation via API (guild: {guild_id}, type: {payload.simulation_type}): {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error while running simulation: {str(e)}")


@router.get(
    "/simulations/reports/{report_id}",
    response_model=SimulationReportResponse,
    summary="Retrieve a previously run simulation report by its ID.",
    responses={
        403: {"description": "User not authorized."},
        404: {"description": "Simulation report with the given ID not found."},
        503: {"description": "GameLogManager component is not available."},
        500: {"description": "Internal server error, or error parsing stored report data."}
    }
)
async def get_simulation_report(
    request: Request,
    guild_id: str, # Added
    report_id: str = Path(..., description="The unique ID of the simulation report to retrieve. This ID is returned by the `/simulations/run` endpoint.", example="sim_report_uuid_123"),
    language: Optional[str] = Query('en', description="Language code for localizing the formatted report output. Defaults to 'en'.")
):
    """
    Retrieves a previously generated simulation report using its unique report ID.

    - **report_id**: The ID of the simulation report (obtained from a prior call to the `/simulations/run` endpoint).
    - **language**: Optional query parameter to specify the language for the `formatted_report` in the response. Defaults to "en".

    Requires master or admin permissions.
    If the report is found, the endpoint returns the `report_id`, the original `simulation_type`,
    a human-readable `formatted_report` (localized to the requested language), and the `raw_report` data.
    If the report ID is not found or if there's an issue retrieving or parsing the stored data,
    an appropriate error (404 or 500) is returned.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr or not game_mngr.game_log_manager:
        raise HTTPException(status_code=503, detail="GameLogManager not available.")

    try:
        log_entry = await game_mngr.game_log_manager.get_log_by_detail(
            guild_id=guild_id,
            event_type="master_api_simulation_run",
            detail_key="report_id",
            detail_value=report_id
        )

        if not log_entry:
            raise HTTPException(status_code=404, detail=f"Simulation report with ID '{report_id}' not found.")

        # The details field from the log_entry should contain the report_id, simulation_type, and report_data
        log_details = log_entry.get('details')
        if isinstance(log_details, str):
            try: log_details = json.loads(log_details)
            except json.JSONDecodeError:
                raise HTTPException(status_code=500, detail=f"Corrupted log details for report ID '{report_id}'.")

        if not isinstance(log_details, dict):
             raise HTTPException(status_code=500, detail=f"Invalid log details format for report ID '{report_id}'.")

        raw_report_data = log_details.get('report_data')
        simulation_type = log_details.get('simulation_type')

        if raw_report_data is None or simulation_type is None:
            raise HTTPException(status_code=500, detail=f"Report data or simulation type missing in log for report ID '{report_id}'.")

        formatter = SimpleReportFormatter(game_mngr, guild_id)
        formatted_report_str = ""

        # Determine which formatting method to call based on simulation_type
        if simulation_type == "battle":
            if not isinstance(raw_report_data, dict): # Battle report should be dict
                 raise HTTPException(status_code=500, detail=f"Invalid raw report format for battle simulation '{report_id}'. Expected dict.")
            formatted_report_str = formatter.format_battle_report(raw_report_data, language)
        elif simulation_type == "quest":
            if not isinstance(raw_report_data, dict): # Quest report should be dict
                 raise HTTPException(status_code=500, detail=f"Invalid raw report format for quest simulation '{report_id}'. Expected dict.")
            formatted_report_str = formatter.format_quest_report(raw_report_data, language)
        elif simulation_type == "action_consequence":
             # Action consequence report_data might be a list of outcomes (wrapped in a dict for storage)
            if isinstance(raw_report_data, dict) and "consequences" in raw_report_data and isinstance(raw_report_data["consequences"], list):
                formatted_report_str = formatter.format_action_consequence_report(raw_report_data["consequences"], language)
            elif isinstance(raw_report_data, list): # If stored directly as list (older logs?)
                formatted_report_str = formatter.format_action_consequence_report(raw_report_data, language)
            else:
                 raise HTTPException(status_code=500, detail=f"Invalid raw report format for action_consequence simulation '{report_id}'. Expected list or dict with 'consequences' list.")
        else:
            formatted_report_str = formatter.format_generic_report(raw_report_data, language)

        # Ensure raw_report for the response is Dict[str, Any]
        # If raw_report_data was a list (e.g. for action_consequence from older logs), wrap it.
        final_raw_report_for_response = raw_report_data
        if isinstance(raw_report_data, list):
            final_raw_report_for_response = {"consequences": raw_report_data}


        return SimulationReportResponse(
            report_id=report_id,
            simulation_type=simulation_type,
            formatted_report=formatted_report_str,
            raw_report=final_raw_report_for_response
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving simulation report (guild: {guild_id}, report_id: {report_id}): {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error while retrieving simulation report: {str(e)}")

# Import new schemas for monitoring
from bot.api.schemas.master_schemas import (
    EventLogResponse, LogEntryItem, AllLocationsResponse, BasicLocationInfo,
    LocationDetailsResponse, LocationNpcInfo, LocationCharacterInfo, LocationEventInfo,
    NpcListResponse, NpcDetails, PlayerStatsResponse
)
from bot.game.services.report_formatter import ReportFormatter # For more detailed log formatting if needed

@router.get(
    "/monitoring/event_log",
    response_model=EventLogResponse,
    summary="Retrieve game log entries for the guild.",
    responses={
        403: {"description": "User not authorized."},
        503: {"description": "A required game manager component (GameLogManager, CharacterManager, NpcManager) is not available."},
        500: {"description": "Internal server error."}
    }
)
async def get_event_log(
    request: Request,
    guild_id: str, # Added
    event_type_filter: Optional[str] = Query(None, description="Filter logs by a specific event type (e.g., 'PLAYER_MOVE', 'NPC_INTERACTION', 'master_api_edit_npc').", example="PLAYER_MOVE"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of log entries to return per page.", example=50),
    offset: int = Query(0, ge=0, description="Offset for paginating through log entries, starting from 0.", example=0),
    language: Optional[str] = Query('en', description="Language for formatting localized log messages (e.g., from `description_key`). Defaults to 'en'.", example="ru")
):
    """
    Retrieves game log entries for the specified guild, with support for filtering and pagination.

    This endpoint is crucial for monitoring game activities, auditing master actions, and debugging.
    Log messages that are structured for localization (i.e., possess a `description_key` and `description_params_json`)
    will be formatted into human-readable strings using the specified `language`.
    Other messages or those where formatting fails will be returned more rawly.

    - **event_type_filter** (optional query param): Filters logs to only include those of a specific type.
    - **limit** (optional query param): Controls how many log entries are returned in a single request (defaults to 50, max 200).
    - **offset** (optional query param): Used for pagination, indicating the number of initial entries to skip (defaults to 0).
    - **language** (optional query param): Specifies the language for localizing messages that support it (e.g., "en", "ru"). Defaults to "en".

    Requires master or admin permissions for the guild.
    Returns an `EventLogResponse` object containing a list of `LogEntryItem` objects and the `total_logs` count
    that matches the filter (useful for client-side pagination calculations).
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr or not game_mngr.game_log_manager:
        raise HTTPException(status_code=503, detail="GameLogManager not available.")
    if not game_mngr.character_manager or not game_mngr.npc_manager:
        raise HTTPException(status_code=503, detail="CharacterManager or NpcManager not available for log formatting, which is used by ReportFormatter.")

    # Use a more capable ReportFormatter if available and desired for story-like logs
    # Fallback to SimpleReportFormatter or basic formatting if not.
    # For now, assuming ReportFormatter (the more complex one) is suitable here.
    # If SimpleReportFormatter is preferred for its _get_entity_name, instantiate that.
    # The existing ReportFormatter seems designed for format_story_log_entry.
    log_formatter = ReportFormatter(
        character_manager=game_mngr.character_manager,
        npc_manager=game_mngr.npc_manager,
        item_manager=game_mngr.item_manager # Pass item_manager if available and used by formatter
    )
    # If SimpleReportFormatter is preferred for its _get_entity_name for simple messages:
    # simple_log_formatter = SimpleReportFormatter(game_mngr, guild_id)


    try:
        # Assuming get_logs_by_guild_paginated exists or adapting get_logs_by_guild
        # For now, let's assume get_logs_by_guild can take offset for simplicity if paginated isn't there.
        # A proper paginated method would also return total count.

        # Placeholder: if get_logs_by_guild_paginated is not available, simulate with get_logs_by_guild
        if hasattr(game_mngr.game_log_manager, "get_logs_by_guild_paginated"):
            total_logs, raw_logs = await game_mngr.game_log_manager.get_logs_by_guild_paginated(
                guild_id=guild_id,
                limit=limit,
                offset=offset,
                event_type_filter=event_type_filter
            )
        else: # Fallback/simulation
            all_logs = await game_mngr.game_log_manager.get_logs_by_guild(
                guild_id=guild_id,
                limit=10000, # Fetch more to simulate pagination, not ideal for production
                event_type_filter=event_type_filter
            )
            raw_logs = all_logs[offset:offset+limit]
            total_logs = len(all_logs) # Total before pagination slice

        processed_logs: List[LogEntryItem] = []
        for log_row in raw_logs:
            # Ensure guild_id is in log_row for formatter if it expects it
            if 'guild_id' not in log_row: log_row['guild_id'] = guild_id

            formatted_message = log_row.get('message', '') # Default to raw message if any
            if log_row.get('description_key'): # If it's a structured log for story formatting
                try:
                    # Make sure the formatter's language context is set if it's stateful,
                    # or pass lang to the formatting method.
                    formatted_message = await log_formatter.format_story_log_entry(log_row, language or 'en')
                except Exception as format_exc:
                    logger.error(f"Error formatting log entry {log_row.get('log_id')}: {format_exc}")
                    # Fallback to a simpler representation or raw message
                    formatted_message = f"Raw: {log_row.get('description_key')} (Params: {log_row.get('description_params_json')})"

            details_dict = None
            if log_row.get('details'):
                if isinstance(log_row['details'], str):
                    try: details_dict = json.loads(log_row['details'])
                    except json.JSONDecodeError: details_dict = {"error": "failed to parse details JSON"}
                elif isinstance(log_row['details'], dict):
                    details_dict = log_row['details']

            processed_logs.append(LogEntryItem(
                timestamp=log_row['timestamp'].isoformat() if hasattr(log_row['timestamp'], 'isoformat') else str(log_row['timestamp']),
                event_type=log_row['event_type'],
                message=formatted_message,
                details=details_dict
            ))

        return EventLogResponse(logs=processed_logs, total_logs=total_logs)

    except Exception as e:
        logger.error(f"Error retrieving event log for guild {guild_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get(
    "/monitoring/map",
    response_model=AllLocationsResponse,
    summary="Retrieve a list of all game locations in the guild.",
    responses={
        403: {"description": "User not authorized."},
        503: {"description": "LocationManager component is not available."},
        500: {"description": "Internal server error."}
    }
)
async def get_all_locations_map(
    request: Request,
    guild_id: str, # Added
    language: Optional[str] = Query('en', description="Language code for localizing location names. Defaults to 'en'.", example="ru")
):
    """
    Retrieves a list of all game locations defined within the specified guild.

    This endpoint provides a basic overview of the game world's map structure, returning
    each location's unique ID and its name, localized to the requested `language`.

    - **language** (optional query param): Specifies the language for location names. Defaults to "en".

    Requires master or admin permissions for the guild.
    Returns an `AllLocationsResponse` object containing a list of `BasicLocationInfo` objects.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr or not game_mngr.location_manager:
        raise HTTPException(status_code=503, detail="LocationManager not available.")

    try:
        # Assuming LocationManager.get_all_location_instances returns model objects
        all_location_models = game_mngr.location_manager.get_all_location_instances(guild_id)
        if not all_location_models: # Check if the list is empty
            return AllLocationsResponse(locations=[])

        processed_locations: List[BasicLocationInfo] = []
        default_lang = language or 'en'

        for loc_model in all_location_models:
            loc_name = loc_model.id # Fallback name is ID
            if hasattr(loc_model, 'name_i18n') and isinstance(loc_model.name_i18n, dict):
                loc_name = loc_model.name_i18n.get(default_lang, loc_model.name_i18n.get('en', loc_model.id))
            elif hasattr(loc_model, 'name') and isinstance(loc_model.name, str): # Non-i18n name
                loc_name = loc_model.name

            processed_locations.append(BasicLocationInfo(
                id=loc_model.id,
                name=loc_name
            ))

        return AllLocationsResponse(locations=processed_locations)

    except Exception as e:
        logger.error(f"Error retrieving all locations for guild {guild_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get(
    "/monitoring/map/{location_id}",
    response_model=LocationDetailsResponse,
    summary="Get detailed information about a specific game location.",
    responses={
        403: {"description": "User not authorized."},
        404: {"description": "Location with the given ID not found."},
        503: {"description": "One or more required game manager components are not available."},
        500: {"description": "Internal server error."}
    }
)
async def get_location_details(
    request: Request,
    guild_id: str, # Added
    location_id: str = Path(..., description="The unique ID of the location for which to retrieve detailed information.", example="loc_town_square"),
    language: Optional[str] = Query('en', description="Language for localizing names and descriptions within the location details. Defaults to 'en'.")
):
    """
    Retrieves comprehensive details about a specific game location within the guild.

    This endpoint provides a snapshot of a location, including:
    - Its localized name and description.
    - Formatted exits, showing the direction and the localized name of the target location.
    - A list of Non-Player Characters (NPCs) currently present, with their IDs and localized names.
    - A list of Player Characters currently present, with their IDs, localized names, and Discord User IDs.
    - A list of active game events linked to this location, with their IDs, names (if available), and template IDs.

    - **location_id**: The ID of the location to inspect.
    - **language** (optional query param): Specifies the language for all localizable text elements
      (location name/description, exit names, NPC/character names, event names). Defaults to "en".

    Requires master or admin permissions for the guild.
    Returns a `LocationDetailsResponse` object. If the location ID is not found, a 404 error is returned.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr or not game_mngr.location_manager or \
       not game_mngr.npc_manager or not game_mngr.character_manager or \
       not game_mngr.event_manager:
        raise HTTPException(status_code=503, detail="One or more required game managers (Location, NPC, Character, Event) are not available.")

    loc = game_mngr.location_manager.get_location_instance(guild_id, location_id)
    if not loc:
        raise HTTPException(status_code=404, detail=f"Location with ID '{location_id}' not found.")

    try:
        default_lang = language or 'en'

        # Location Name and Description
        loc_name = loc.id
        if hasattr(loc, 'name_i18n') and isinstance(loc.name_i18n, dict):
            loc_name = loc.name_i18n.get(default_lang, loc.name_i18n.get('en', loc.id))
        elif hasattr(loc, 'name'): loc_name = loc.name

        loc_desc = "No description available."
        # Assuming display_description is a property or method that handles i18n for descriptions
        if hasattr(loc, 'display_description') and callable(loc.display_description):
             loc_desc = loc.display_description(default_lang)
        elif hasattr(loc, 'display_description') and isinstance(loc.display_description, str): # if it's already a simple string attribute
            loc_desc = loc.display_description
        elif hasattr(loc, 'descriptions_i18n') and isinstance(loc.descriptions_i18n, dict):
            loc_desc = loc.descriptions_i18n.get(default_lang, loc.descriptions_i18n.get('en', loc_desc))

        # Exits
        formatted_exits: Dict[str, str] = {}
        if hasattr(loc, 'exits') and isinstance(loc.exits, dict):
            for direction, exit_data in loc.exits.items():
                target_loc_id = ""
                if isinstance(exit_data, str): # Simple exit: "loc_id_2"
                    target_loc_id = exit_data
                elif isinstance(exit_data, dict) and 'target_location_id' in exit_data: # Complex exit: {"target_location_id": "loc_id_2", ...}
                    target_loc_id = exit_data['target_location_id']

                if target_loc_id:
                    target_loc = game_mngr.location_manager.get_location_instance(guild_id, target_loc_id)
                    target_loc_name = target_loc_id # Fallback
                    if target_loc:
                        if hasattr(target_loc, 'name_i18n') and isinstance(target_loc.name_i18n, dict):
                            target_loc_name = target_loc.name_i18n.get(default_lang, target_loc.name_i18n.get('en', target_loc_id))
                        elif hasattr(target_loc, 'name'): target_loc_name = target_loc.name
                    formatted_exits[direction] = f"{target_loc_name} (`{target_loc_id}`)"
                else:
                    formatted_exits[direction] = "Unknown"

        # NPCs
        location_npcs: List[LocationNpcInfo] = []
        npcs_in_loc = game_mngr.npc_manager.get_npcs_in_location(guild_id, location_id)
        for npc in npcs_in_loc:
            npc_name = npc.id
            if hasattr(npc, 'name_i18n') and isinstance(npc.name_i18n, dict):
                npc_name = npc.name_i18n.get(default_lang, npc.name_i18n.get('en', npc.id))
            elif hasattr(npc, 'name'): npc_name = npc.name
            location_npcs.append(LocationNpcInfo(id=npc.id, name=npc_name))

        # Characters
        location_chars: List[LocationCharacterInfo] = []
        chars_in_loc = game_mngr.character_manager.get_characters_in_location(guild_id, location_id)
        for char in chars_in_loc:
            char_name = char.id
            if hasattr(char, 'name_i18n') and isinstance(char.name_i18n, dict):
                char_name = char.name_i18n.get(default_lang, char.name_i18n.get('en', char.id))
            elif hasattr(char, 'name'): char_name = char.name
            location_chars.append(LocationCharacterInfo(
                id=char.id, name=char_name,
                discord_user_id=str(char.discord_user_id) if hasattr(char, 'discord_user_id') else None
            ))

        # Events
        location_events: List[LocationEventInfo] = []
        # Assuming EventManager.get_active_events can be filtered or a specific method exists
        all_active_events = game_mngr.event_manager.get_active_events(guild_id) # This might fetch all, then filter
        for event in all_active_events:
            # Check if event is linked to this location_id
            event_loc_id = None
            if hasattr(event, 'location_id') and event.location_id == location_id:
                 event_loc_id = event.location_id
            elif hasattr(event, 'state_variables') and isinstance(event.state_variables, dict) and \
                 event.state_variables.get('linked_location_id') == location_id:
                 event_loc_id = location_id # Event is linked via state_variables

            if event_loc_id:
                event_name = getattr(event, 'name', None) # Events might not have i18n names directly
                if isinstance(event_name, dict): # If name itself is an i18n dict
                     event_name = event_name.get(default_lang, event_name.get('en', event.id))

                location_events.append(LocationEventInfo(
                    id=event.id,
                    name=event_name or event.template_id, # Fallback to template_id if no name
                    template_id=event.template_id
                ))

        return LocationDetailsResponse(
            id=loc.id, name=loc_name, description=loc_desc,
            exits=formatted_exits, npcs=location_npcs,
            characters=location_chars, events=location_events
        )

    except Exception as e:
        logger.error(f"Error retrieving details for location {location_id} in guild {guild_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get(
    "/monitoring/npcs",
    response_model=NpcListResponse,
    summary="List NPCs in the guild, optionally filtered by location.",
    responses={
        403: {"description": "User not authorized."},
        404: {"description": "Location specified in `location_id_filter` not found."},
        503: {"description": "A required game manager component (NpcManager, LocationManager) is not available."},
        500: {"description": "Internal server error."}
    }
)
async def get_guild_npcs(
    request: Request,
    guild_id: str, # Added
    location_id_filter: Optional[str] = Query(None, description="Optional ID of a specific location to filter the NPC list by. If not provided, NPCs from all locations are listed.", example="loc_market_square"),
    language: Optional[str] = Query('en', description="Language for localizing NPC names and their current location names. Defaults to 'en'.")
):
    """
    Retrieves a list of Non-Player Characters (NPCs) within the specified guild.
    An optional filter can be applied to list NPCs only from a particular location.

    For each NPC, the response includes:
    - Unique ID.
    - Localized name.
    - Current location ID and its localized name (if applicable).
    - Current and maximum health points.

    - **location_id_filter** (optional query param): If provided, the list will only contain NPCs currently at this location. If the location ID is invalid, a 404 error is returned.
    - **language** (optional query param): Specifies the language for NPC and location names. Defaults to "en".

    Requires master or admin permissions for the guild.
    Returns an `NpcListResponse` object containing a list of `NpcDetails`.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr or not game_mngr.npc_manager or not game_mngr.location_manager:
        raise HTTPException(status_code=503, detail="NpcManager or LocationManager not available.")

    try:
        npc_models: List[Any] # List of NPC model instances
        if location_id_filter:
            if not game_mngr.location_manager.get_location_instance(guild_id, location_id_filter):
                raise HTTPException(status_code=404, detail=f"Filter location ID '{location_id_filter}' not found.")
            npc_models = game_mngr.npc_manager.get_npcs_in_location(guild_id, location_id_filter)
        else:
            npc_models = game_mngr.npc_manager.get_all_npcs(guild_id)

        if not npc_models:
            return NpcListResponse(npcs=[])

        processed_npcs: List[NpcDetails] = []
        default_lang = language or 'en'

        for npc_model in npc_models:
            npc_name = npc_model.id
            if hasattr(npc_model, 'name_i18n') and isinstance(npc_model.name_i18n, dict):
                npc_name = npc_model.name_i18n.get(default_lang, npc_model.name_i18n.get('en', npc_model.id))
            elif hasattr(npc_model, 'name'): npc_name = npc_model.name

            loc_name: Optional[str] = None
            npc_loc_id: Optional[str] = getattr(npc_model, 'location_id', None)
            if npc_loc_id:
                loc_instance = game_mngr.location_manager.get_location_instance(guild_id, npc_loc_id)
                if loc_instance:
                    if hasattr(loc_instance, 'name_i18n') and isinstance(loc_instance.name_i18n, dict):
                        loc_name = loc_instance.name_i18n.get(default_lang, loc_instance.name_i18n.get('en', npc_loc_id))
                    elif hasattr(loc_instance, 'name'): loc_name = loc_instance.name
                    else: loc_name = npc_loc_id # Fallback if name attributes are missing
                else: loc_name = f"Unknown ({npc_loc_id})"


            processed_npcs.append(NpcDetails(
                id=npc_model.id,
                name=npc_name,
                location_id=npc_loc_id,
                location_name=loc_name,
                hp=getattr(npc_model, 'hp', None),
                max_health=getattr(npc_model, 'max_health', None)
            ))

        return NpcListResponse(npcs=processed_npcs)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving NPCs for guild {guild_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get(
    "/monitoring/players/{character_id_or_discord_id}",
    response_model=PlayerStatsResponse,
    summary="Get detailed statistics for a player character.",
    responses={
        403: {"description": "User not authorized."},
        404: {"description": "Character with the given ID (Character UUID or Discord ID) not found."},
        503: {"description": "A required game manager component is not available."},
        500: {"description": "Internal server error."}
    }
)
async def get_player_stats(
    request: Request,
    guild_id: str, # Added
    character_id_or_discord_id: str = Path(..., description="The Character UUID (string) or Discord User ID (numeric string) of the player character whose stats are to be retrieved.", example="char_player_fighter_007"),
    language: Optional[str] = Query('en', description="Language for localizing names (character, class, location). Defaults to 'en'.")
):
    """
    Retrieves detailed statistics and information for a specific player character within the guild.

    The character can be identified either by their internal Character ID (a UUID string) or by the
    Discord User ID of the player who controls them (a numeric string).

    The response includes:
    - Localized character name.
    - Discord User ID.
    - Level, current experience, and unspent experience points.
    - Current and maximum health points.
    - Localized character class name.
    - The character's selected language.
    - Current location ID and its localized name.
    - A dictionary of base statistics (e.g., strength, dexterity).
    - An optional dictionary of effective statistics (after buffs, equipment, etc.), if available.

    - **character_id_or_discord_id**: The identifier for the character.
    - **language** (optional query param): Specifies the language for localizing textual information
      such as character name, class name, and location name. Defaults to "en".

    Requires master or admin permissions for the guild.
    Returns a `PlayerStatsResponse` object. If the character is not found, a 404 error is returned.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr or not game_mngr.character_manager or not game_mngr.location_manager: # RuleEngine might be needed for class name i18n
        raise HTTPException(status_code=503, detail="CharacterManager, LocationManager, or other components needed for full details are not available.")

    char_model = None
    if character_id_or_discord_id.isdigit():
        char_model = game_mngr.character_manager.get_character_by_discord_id(guild_id, int(character_id_or_discord_id))
    if not char_model: # If not found by Discord ID or if it wasn't digits
        char_model = game_mngr.character_manager.get_character(guild_id, character_id_or_discord_id)

    if not char_model:
        raise HTTPException(status_code=404, detail=f"Character with identifier '{character_id_or_discord_id}' not found.")

    try:
        default_lang = language or 'en'

        char_name = char_model.id
        if hasattr(char_model, 'name_i18n') and isinstance(char_model.name_i18n, dict):
            char_name = char_model.name_i18n.get(default_lang, char_model.name_i18n.get('en', char_model.id))
        elif hasattr(char_model, 'name'): char_name = char_model.name

        char_class_name = getattr(char_model, 'character_class', None)
        # Assuming class names might also be i18n. This depends on how class names are stored/managed.
        # For example, if RuleEngine has class definitions:
        if char_class_name and hasattr(game_mngr.rule_engine, 'get_class_definition'):
            class_def = game_mngr.rule_engine.get_class_definition(char_class_name) # This method may not exist
            if class_def and hasattr(class_def, 'name_i18n') and isinstance(class_def.name_i18n, dict) :
                char_class_name = class_def.name_i18n.get(default_lang, class_def.name_i18n.get('en', char_class_name))
            elif class_def and hasattr(class_def, 'name'):
                 char_class_name = class_def.name

        loc_name: Optional[str] = None
        char_loc_id: Optional[str] = getattr(char_model, 'location_id', getattr(char_model, 'current_location_id', None))
        if char_loc_id:
            loc_instance = game_mngr.location_manager.get_location_instance(guild_id, char_loc_id)
            if loc_instance:
                if hasattr(loc_instance, 'name_i18n') and isinstance(loc_instance.name_i18n, dict):
                    loc_name = loc_instance.name_i18n.get(default_lang, loc_instance.name_i18n.get('en', char_loc_id))
                elif hasattr(loc_instance, 'name'): loc_name = loc_instance.name
                else: loc_name = char_loc_id
            else: loc_name = f"Unknown ({char_loc_id})"

        effective_stats_dict: Optional[Dict[str, Any]] = None
        if hasattr(char_model, 'effective_stats_json') and isinstance(char_model.effective_stats_json, str):
            try: effective_stats_dict = json.loads(char_model.effective_stats_json)
            except json.JSONDecodeError: logger.warning(f"Could not parse effective_stats_json for char {char_model.id}")
        elif hasattr(char_model, 'effective_stats') and isinstance(char_model.effective_stats, dict): # If it's already a dict
            effective_stats_dict = char_model.effective_stats


        return PlayerStatsResponse(
            id=char_model.id,
            name=char_name,
            discord_user_id=str(getattr(char_model, 'discord_user_id', None)),
            level=getattr(char_model, 'level', 1),
            experience=getattr(char_model, 'experience', 0),
            unspent_xp=getattr(char_model, 'unspent_xp', 0),
            hp=getattr(char_model, 'hp', 0.0),
            max_health=getattr(char_model, 'max_health', 0.0),
            character_class=char_class_name,
            language=getattr(char_model, 'selected_language', None),
            location_id=char_loc_id,
            location_name=loc_name,
            stats=getattr(char_model, 'stats', {}), # Base stats
            effective_stats=effective_stats_dict
        )

    except Exception as e:
        logger.error(f"Error retrieving player stats for {character_id_or_discord_id} in guild {guild_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post(
    "/simulations/compare_reports",
    response_model=CompareReportsResponse,
    summary="Compare two simulation reports.",
    responses={
        400: {"description": "Reports are of different simulation types and cannot be compared, or other validation error."},
        403: {"description": "User not authorized."},
        404: {"description": "One or both simulation report IDs not found."},
        503: {"description": "GameLogManager component is not available."},
        500: {"description": "Internal server error during comparison."}
    }
)
async def compare_simulation_reports(
    request: Request,
    guild_id: str, # Added
    payload: CompareReportsRequest = Body(..., description="Specifies the IDs of the two simulation reports to compare and the desired language for the comparison summary output.")
):
    """
    Compares two previously generated simulation reports.

    This endpoint fetches two simulation reports by their IDs, performs a basic comparison of their
    key metrics (if they are of the same simulation type), and returns both structured comparison
    details and a human-readable formatted summary.

    - **payload**:
        - `report_id_1` (str): The unique ID of the first simulation report.
        - `report_id_2` (str): The unique ID of the second simulation report.
        - `language` (Optional[str]): The language code (e.g., "en", "ru") for generating the
          `formatted_comparison`. Defaults to "en".

    Requires master or admin permissions.
    An error is returned if the reports are not found or if they are of different simulation types,
    as comparison is only meaningful for reports of the same type.
    The comparison action itself is logged.
    """
    game_mngr = request.app.state.game_manager
    if not game_mngr or not game_mngr.game_log_manager:
        raise HTTPException(status_code=503, detail="GameLogManager not available.")

    async def get_report_log_details(report_id_str: str) -> Optional[Dict[str, Any]]:
        log_entry = await game_mngr.game_log_manager.get_log_by_detail(
            guild_id=guild_id,
            event_type="master_api_simulation_run",
            detail_key="report_id",
            detail_value=report_id_str
        )
        if not log_entry: return None

        details = log_entry.get('details')
        if isinstance(details, str):
            try: return json.loads(details)
            except json.JSONDecodeError: return None
        return details if isinstance(details, dict) else None

    report1_log_details = await get_report_log_details(payload.report_id_1)
    report2_log_details = await get_report_log_details(payload.report_id_2)

    if not report1_log_details:
        return CompareReportsResponse(report_id_1=payload.report_id_1, report_id_2=payload.report_id_2,
                                      comparison_details={}, formatted_comparison="",
                                      error=f"Report ID {payload.report_id_1} not found.")
    if not report2_log_details:
        return CompareReportsResponse(report_id_1=payload.report_id_1, report_id_2=payload.report_id_2,
                                      comparison_details={}, formatted_comparison="",
                                      error=f"Report ID {payload.report_id_2} not found.")

    sim_type1 = report1_log_details.get('simulation_type')
    sim_type2 = report2_log_details.get('simulation_type')
    raw_report1 = report1_log_details.get('report_data', {})
    raw_report2 = report2_log_details.get('report_data', {})

    if sim_type1 != sim_type2:
        return CompareReportsResponse(
            report_id_1=payload.report_id_1, report_id_2=payload.report_id_2,
            simulation_type_1=sim_type1, simulation_type_2=sim_type2,
            comparison_details={}, formatted_comparison="",
            error="Cannot compare reports of different simulation types."
        )

    comparison_details_dict: Dict[str, Any] = {
        "report_id_1": payload.report_id_1, "simulation_type_1": sim_type1,
        "report_id_2": payload.report_id_2, "simulation_type_2": sim_type2,
        "report_1_metrics": {}, "report_2_metrics": {}, "diff": {}
    }

    # Basic comparison logic based on simulation type
    if sim_type1 == "battle":
        m1 = comparison_details_dict["report_1_metrics"] = {
            "winning_team": raw_report1.get("winning_team"),
            "total_rounds": raw_report1.get("total_rounds"),
            "participants_summary": raw_report1.get("participants_summary", []) # List of dicts
        }
        m2 = comparison_details_dict["report_2_metrics"] = {
            "winning_team": raw_report2.get("winning_team"),
            "total_rounds": raw_report2.get("total_rounds"),
            "participants_summary": raw_report2.get("participants_summary", [])
        }
        if m1["winning_team"] != m2["winning_team"]:
            comparison_details_dict["diff"]["winning_team"] = {"report_1": m1["winning_team"], "report_2": m2["winning_team"]}
        if m1["total_rounds"] != m2["total_rounds"]:
            comparison_details_dict["diff"]["total_rounds"] = {"report_1": m1["total_rounds"], "report_2": m2["total_rounds"]}
        # Further diff for participants could be added here (e.g. survivor count diff)

    elif sim_type1 == "quest":
        m1 = comparison_details_dict["report_1_metrics"] = {
            "final_status": raw_report1.get("final_status"),
            "stages_simulated_count": raw_report1.get("stages_simulated_count"),
            "final_stage_reached": raw_report1.get("final_stage_reached")
        }
        m2 = comparison_details_dict["report_2_metrics"] = {
            "final_status": raw_report2.get("final_status"),
            "stages_simulated_count": raw_report2.get("stages_simulated_count"),
            "final_stage_reached": raw_report2.get("final_stage_reached")
        }
        for key in m1:
            if m1[key] != m2.get(key):
                comparison_details_dict["diff"][key] = {"report_1": m1[key], "report_2": m2.get(key)}

    elif sim_type1 == "action_consequence":
        # raw_report for action_consequence is {"consequences": List[Dict]}
        outcomes1 = raw_report1.get("consequences", []) if isinstance(raw_report1, dict) else (raw_report1 if isinstance(raw_report1, list) else [])
        outcomes2 = raw_report2.get("consequences", []) if isinstance(raw_report2, dict) else (raw_report2 if isinstance(raw_report2, list) else [])

        comparison_details_dict["report_1_metrics"]["outcomes"] = outcomes1
        comparison_details_dict["report_2_metrics"]["outcomes"] = outcomes2
        if len(outcomes1) != len(outcomes2):
            comparison_details_dict["diff"]["outcome_count_diff"] = {"report_1": len(outcomes1), "report_2": len(outcomes2)}
        # More detailed outcome comparison would involve matching/diffing individual outcomes.

    else:
        comparison_details_dict["error"] = f"Comparison for simulation type '{sim_type1}' is not implemented."

    formatter = SimpleReportFormatter(game_mngr, guild_id)
    formatted_comparison_str = formatter.format_comparison_report(comparison_details_dict, sim_type1, payload.language)

    # Log the comparison action
    log_details_compare = {
        "report_id_1": payload.report_id_1,
        "report_id_2": payload.report_id_2,
        "simulation_type_common": sim_type1,
        "compared_by_api": True,
        "admin_id": getattr(request.state, "current_user_id", "unknown_api_user")
    }
    await game_mngr.game_log_manager.log_event(guild_id, "master_api_simulation_compare", log_details_compare)

    return CompareReportsResponse(
        report_id_1=payload.report_id_1,
        report_id_2=payload.report_id_2,
        simulation_type_1=sim_type1,
        simulation_type_2=sim_type2,
        comparison_details=comparison_details_dict,
        formatted_comparison=formatted_comparison_str,
        error=comparison_details_dict.get("error")
    )
