import json
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession # For type hinting, though session is from db_service

from bot.database.models import Character # MODIFIED: Import Character instead of Player
# Assuming get_entities and update_entity are suitable.
# If direct session usage (session.add for updates) is preferred, update_entity might not be strictly needed.
from bot.database.crud_utils import get_entities # update_entity might not be needed if using session.add

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__)

class TurnProcessor:
    def __init__(self, game_manager: "GameManager"):
        self.game_manager = game_manager
        if not self.game_manager:
            # This should ideally not happen if GameManager ensures it passes itself.
            logger.critical("TurnProcessor initialized without a valid GameManager instance!")
            # Depending on design, could raise an error or operate in a disabled state.
            # For now, logging critical error. Subsequent calls will likely fail if game_manager is None.

    async def process_turns_for_guild(self, guild_id: str) -> None:
        """
        Processes turns for all players in a given guild who have submitted their actions.
        """
        if not self.game_manager or not self.game_manager.db_service:
            logger.error(f"TurnProcessor: GameManager or DBService not available for guild {guild_id}. Cannot process turns.")
            return

        db_service = self.game_manager.db_service
        players_processed_count = 0

        logger.info(f"Starting turn processing for guild {guild_id}.")

        async with db_service.get_session() as session:
            try:
                # Fetch RuleConfig for the guild
                if not self.game_manager.rule_engine:
                    logger.error(f"TurnProcessor: RuleEngine not available for guild {guild_id}. Cannot process turns with conflict resolution.")
                    return

                # Assuming RuleEngine has a way to provide the CoreGameRulesConfig
                # This might involve RuleEngine loading it if not already cached for the guild.
                # For now, let's assume RuleEngine has a property or method for this.
                # This part might need adjustment based on RuleEngine's exact API.
                # rules_config_data = await self.game_manager.rule_engine.get_rules_config(guild_id) # Expects CoreGameRulesConfig Pydantic model
                rules_config_data = await self.game_manager.get_core_rules_config_for_guild(guild_id) # Use the new method
                if not rules_config_data:
                    logger.error(f"TurnProcessor: Failed to load CoreGameRulesConfig for guild {guild_id}. Cannot process turns with conflict resolution.")
                    return

                # Fetch characters who have submitted actions
                characters_with_submitted_actions = await get_entities(
                    db_session=session,
                    model_class=Character,
                    guild_id=guild_id,
                    conditions=[Character.current_game_status == "actions_submitted"]
                )

                if not characters_with_submitted_actions:
                    logger.info(f"No characters with submitted actions found in guild {guild_id}.")
                    return

                logger.info(f"Found {len(characters_with_submitted_actions)} characters with submitted actions in guild {guild_id}.")

                # --- Stage 1: Collect all actions for conflict analysis ---
                player_actions_map_for_conflict: Dict[str, List[Dict[str, Any]]] = {}
                character_map: Dict[str, Character] = {char.id: char for char in characters_with_submitted_actions}

                for character in characters_with_submitted_actions:
                    actions_json_str = character.collected_actions_json
                    if actions_json_str:
                        try:
                            actions_list = json.loads(actions_json_str)
                            if isinstance(actions_list, list) and actions_list:
                                player_actions_map_for_conflict[character.id] = actions_list
                        except json.JSONDecodeError:
                            logger.error(f"Failed to decode actions JSON for conflict analysis, character {character.id}: '{actions_json_str}'", exc_info=True)

                # --- Stage 2: Conflict Resolution ---
                conflict_analysis_result = None
                if player_actions_map_for_conflict and self.game_manager.conflict_resolver:
                    conflict_analysis_result = await self.game_manager.conflict_resolver.analyze_actions_for_conflicts(
                        player_actions_map=player_actions_map_for_conflict,
                        guild_id=guild_id,
                        rules_config=rules_config_data # Pass the loaded CoreGameRulesConfig
                    )

                actions_to_execute_this_turn: List[Dict[str, Any]] = []
                if conflict_analysis_result:
                    if conflict_analysis_result.get("requires_manual_resolution"):
                        logger.info(f"TurnProcessor: Manual conflict resolution required for guild {guild_id}.")
                        for conflict_detail in conflict_analysis_result.get("pending_conflict_details", []):
                            # Save PendingConflict to DB (this should ideally be a service call)
                            # For now, conceptual:
                            # await self.game_manager.db_service.create_entity(PendingConflict, conflict_detail_with_guild_id_and_status)
                            logger.info(f"Conflict details for manual resolution: {conflict_detail}")
                            # Notify GM (NotificationService should be used here by ConflictResolver or GMAppCmds)

                            # Update status for involved characters
                            for char_id_in_conflict in conflict_detail.get("involved_player_ids", []):
                                if char_id_in_conflict in character_map:
                                    char_in_conflict = character_map[char_id_in_conflict]
                                    char_in_conflict.current_game_status = "ожидание_разрешения_конфликта"
                                    # Keep their actions in collected_actions_json until resolved
                                    session.add(char_in_conflict)
                                    logger.info(f"Character {char_id_in_conflict} status set to 'ожидание_разрешения_конфликта'.")

                    # Add auto-resolved or non-conflicting actions to the execution list
                    actions_to_execute_this_turn.extend(conflict_analysis_result.get("actions_to_execute", []))

                    # Log auto-resolution outcomes (if any)
                    for auto_res_outcome in conflict_analysis_result.get("auto_resolution_outcomes", []):
                        logger.info(f"Auto-resolved conflict outcome: {auto_res_outcome}")
                        # Potentially send feedback to players involved in auto-resolved conflicts
                else: # No conflicts or resolver not available, all actions go to execution
                    for char_id, actions in player_actions_map_for_conflict.items():
                        for action_data in actions:
                            actions_to_execute_this_turn.append({"character_id": char_id, "action_data": action_data})

                # --- Stage 3: Execute Cleared Actions ---
                # Group actions by character_id for sequential processing per character
                actions_by_character: Dict[str, List[Dict[str,Any]]] = {}
                for exec_action in actions_to_execute_this_turn:
                    char_id = exec_action["character_id"]
                    actions_by_character.setdefault(char_id, []).append(exec_action["action_data"])

                for character_id, char_actions_list in actions_by_character.items():
                    character = character_map.get(character_id)
                    if not character or character.current_game_status == "ожидание_разрешения_конфликта":
                        # Skip if character not found (should not happen if actions_by_character is built correctly)
                        # or if character is now waiting for manual conflict resolution
                        continue

                    try:
                        player_discord_id_for_log = "N/A" # Default
                        if character.player_id and self.game_manager.character_manager: # CharacterManager has Player cache
                            player_obj = await self.game_manager.character_manager.get_player_account_by_char_id(character.id, guild_id)
                            if player_obj:
                                player_discord_id_for_log = player_obj.discord_id

                        logger.info(f"Processing turn for character {character.id} (Player Discord: {player_discord_id_for_log}) in guild {guild_id}.")

                        # 1. Load and Parse Actions
                        actions_json_str = character.collected_actions_json # MODIFIED: Use character attribute
                        actions_list: List[Dict[str, Any]] = []
                        if actions_json_str:
                            try:
                                actions_list = json.loads(actions_json_str)
                                if not isinstance(actions_list, list):
                                    logger.warning(f"Character {character.id} actions JSON is not a list: {actions_json_str}. Treating as empty.")
                                    actions_list = []
                            except json.JSONDecodeError:
                                logger.error(f"Failed to decode actions JSON for character {character.id}: '{actions_json_str}'", exc_info=True)

                        logger.debug(f"Character {character.id} actions to process: {actions_list}")

                        if actions_list:
                            logger.info(f"Character {character.id} submitted {len(actions_list)} actions. Processing...")
                            for action_data in actions_list:
                                intent = action_data.get("intent")
                                entities = action_data.get("entities", [])
                                original_text = action_data.get("original_text", "")
                                logger.debug(f"Character {character.id} action: Intent='{intent}', Entities='{entities}', Original='{original_text}'")

                                # --- Action Execution (Placeholder for new dispatcher) ---
                        # --- Action Execution Dispatcher ---
                        # This loop processes actions for a single character sequentially.
                        # Each action should ideally be in its own GuildTransaction if it modifies DB state.
                        # However, if CharacterActionProcessor methods are already transactional, that's fine.

                        character_had_successful_action = False
                        for action_data_to_exec in char_actions_list:
                            intent = action_data_to_exec.get("intent")
                            original_text = action_data_to_exec.get("original_text", "")
                            logger.debug(f"Character {character.id} executing action: Intent='{intent}', Data='{action_data_to_exec}'")

                            action_result: Optional[Dict[str, Any]] = None

                            # We need CharacterActionProcessor here. GameManager should have it.
                            if not self.game_manager.character_action_processor:
                                logger.error(f"CharacterActionProcessor not available for guild {guild_id}. Cannot execute action for char {character.id}.")
                                if self.game_manager.notification_service:
                                    await self.game_manager.notification_service.send_character_feedback(
                                        guild_id, character.id, "Action processing system is currently unavailable.", "system_error"
                                    )
                                break # Stop processing actions for this character if CAP is missing

                            # Context for CharacterActionProcessor
                            cap_context = {
                                'guild_id': guild_id,
                                'author_id': player_discord_id_for_log, # Assuming this is discord_id str
                                'channel_id': None, # TurnProcessor doesn't have a specific channel, feedback goes via NotificationService
                                'game_manager': self.game_manager,
                                'db_session': session, # Pass the current session
                                # Other managers are accessed via game_manager inside CAP
                            }

                            try:
                                # CharacterActionProcessor.process_action is a placeholder name;
                                # it should be a method that takes character_id, intent, action_data (entities etc.), and context.
                                # For now, using a conceptual routing based on intent.
                                # This needs to be mapped to actual CharacterActionProcessor methods.

                                # Example of how it might be structured:
                                # action_request = ActionRequest(guild_id=guild_id, actor_id=character.id, action_type=intent, action_data=action_data_to_exec)
                                # action_result = await self.game_manager.character_action_processor.process_action_from_request(
                                #    action_request, character, cap_context
                                # )

                                # Simplified direct calls for now, assuming CAP has methods per intent or a dispatcher
                                if intent == "INTENT_MOVE":
                                    target_entity_data = action_data_to_exec.get('primary_target_entity')
                                    target_identifier = None
                                    if target_entity_data and target_entity_data.get('type') in ['location', 'direction', 'location_feature', 'location_tag']:
                                        target_identifier = target_entity_data.get('name')
                                    elif action_data_to_exec.get('entities'):
                                        for ent in action_data_to_exec.get('entities', []):
                                            if ent.get('type') in ['location', 'direction']: target_identifier = ent.get('name'); break
                                    if not target_identifier and action_data_to_exec.get('original_text'):
                                        parts = action_data_to_exec['original_text'].lower().split("to "); target_identifier = parts[1].strip() if len(parts) > 1 else None

                                    if target_identifier:
                                        move_success = await self.game_manager.handle_move_action(guild_id, character.id, target_identifier, session=session)
                                        action_result = {"success": move_success, "message": "Moved." if move_success else "Could not move."}
                                    else:
                                        action_result = {"success": False, "message": "Move target unclear."}

                                elif intent == "INTENT_LOOK":
                                     action_result = await self.game_manager.character_action_processor.handle_explore_action(
                                         character, guild_id, action_data_to_exec.get('primary_target_entity', {}).get('name'), cap_context.get('channel_id'), session=session
                                     )
                                # ... other intent handlers ...
                                else:
                                    logger.info(f"Intent '{intent}' for char {character.id} not fully handled by TurnProcessor yet.")
                                    action_result = {"success": True, "message": f"Action '{original_text}' acknowledged (Intent: {intent}). Full processing pending."}

                                if action_result and action_result.get("success"):
                                    character_had_successful_action = True
                                    if action_result.get("message") and self.game_manager.notification_service:
                                        await self.game_manager.notification_service.send_character_feedback(
                                            guild_id, character.id, action_result["message"], "action_result"
                                        )
                                elif action_result and self.game_manager.notification_service: # Action failed
                                    await self.game_manager.notification_service.send_character_feedback(
                                        guild_id, character.id, action_result.get("message", "Action failed."), "action_error"
                                    )

                                # If an action has significant consequences (e.g., starting combat, ending dialogue),
                                # it might change character.current_game_status.
                                # The loop should break if status is no longer 'active' or 'actions_submitted'.
                                if character.current_game_status not in ["active", "actions_submitted"]:
                                    logger.info(f"Character {character.id} status changed to '{character.current_game_status}' during action processing. Ending turn early.")
                                    break

                            except Exception as e_action_exec:
                                logger.error(f"Error executing action '{intent}' for character {character.id}: {e_action_exec}", exc_info=True)
                                if self.game_manager.notification_service:
                                    await self.game_manager.notification_service.send_character_feedback(
                                        guild_id, character.id, f"An error occurred while performing action: {original_text}", "system_error"
                                    )
                                # Decide if we should break or continue other actions for this character.
                                # For now, let's break if one action errors out.
                                break

                        # After all actions for a character are attempted:
                        if character.current_game_status == "actions_submitted": # Only change if not already changed by an action
                            character.current_game_status = "active"
                        character.collected_actions_json = "[]" # Clear actions
                        session.add(character) # Mark for update

                        players_processed_count += 1
                        logger.info(f"Character {character.id} actions processed. Status set to 'active'.")

                    except Exception as e_char_processing:
                        logger.error(f"Error processing turn for character {character.id} in guild {guild_id}: {e_char_processing}", exc_info=True)
                        # Optionally, set character status to 'error' or similar
                        try:
                            character.current_game_status = "error_processing_turn"
                            character.collected_actions_json = "[]" # Clear actions even on error to prevent reprocessing loop
                            session.add(character)
                        except Exception as e_status_update:
                            logger.error(f"Failed to update character {character.id} status to error: {e_status_update}", exc_info=True)
                        # Continue to next character

                await session.commit()
                logger.info(f"Successfully processed and committed turns for {players_processed_count} characters in guild {guild_id}.")

            except Exception as e_guild_processing:
                logger.error(f"Critical error during turn processing for guild {guild_id} (outer loop or commit): {e_guild_processing}", exc_info=True)
                try:
                    await session.rollback()
                    logger.info(f"Session rolled back for guild {guild_id} due to critical error.")
                except Exception as e_rollback:
                    logger.error(f"Failed to rollback session for guild {guild_id} after critical error: {e_rollback}", exc_info=True)

        logger.info(f"Turn processing cycle finished for guild {guild_id}.")
