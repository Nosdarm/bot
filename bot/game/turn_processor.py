import json
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Character
from bot.database.crud_utils import get_entities

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.conflict_resolver import ConflictResolver
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.services.notification_service import NotificationService
    from bot.services.db_service import DBService
    from bot.game.rules.rule_engine import RuleEngine
    from bot.ai.rules_schema import CoreGameRulesConfig


logger = logging.getLogger(__name__)

class TurnProcessor:
    def __init__(self, game_manager: "GameManager"):
        self.game_manager = game_manager
        if not self.game_manager:
            logger.critical("TurnProcessor initialized without a valid GameManager instance!")

    async def process_turns_for_guild(self, guild_id: str) -> None:
        if not self.game_manager:
            logger.error(f"TurnProcessor: GameManager is None for guild {guild_id}. Cannot process turns.")
            return

        db_service: Optional["DBService"] = getattr(self.game_manager, 'db_service', None)
        if not db_service or not hasattr(db_service, 'get_session') or not callable(db_service.get_session):
            logger.error(f"TurnProcessor: DBService or get_session not available for guild {guild_id}. Cannot process turns.")
            return

        players_processed_count = 0
        logger.info(f"Starting turn processing for guild {guild_id}.")

        active_session: Optional[AsyncSession] = None
        try:
            async with db_service.get_session() as session_context:
                active_session = cast(AsyncSession, session_context)

                rule_engine: Optional["RuleEngine"] = getattr(self.game_manager, 'rule_engine', None)
                if not rule_engine or not hasattr(rule_engine, 'get_core_rules_config_for_guild') or not callable(getattr(rule_engine, 'get_core_rules_config_for_guild')):
                    logger.error(f"TurnProcessor: RuleEngine or get_core_rules_config_for_guild not available for guild {guild_id}.")
                    return

                rules_config_data: Optional["CoreGameRulesConfig"] = await rule_engine.get_core_rules_config_for_guild(guild_id)
                if not rules_config_data:
                    logger.error(f"TurnProcessor: Failed to load CoreGameRulesConfig for guild {guild_id}.")
                    return

                characters_with_submitted_actions_result = await get_entities(
                    db_session=active_session, # Pass AsyncSession
                    model_class=Character,
                    guild_id=guild_id,
                    conditions=[Character.current_game_status == "actions_submitted"] # type: ignore
                )
                characters_with_submitted_actions: List[Character] = characters_with_submitted_actions_result if characters_with_submitted_actions_result else []


                if not characters_with_submitted_actions:
                    logger.info(f"No characters with submitted actions found in guild {guild_id}.")
                    return
                logger.info(f"Found {len(characters_with_submitted_actions)} characters with submitted actions in guild {guild_id}.")

                player_actions_map_for_conflict: Dict[str, List[Dict[str, Any]]] = {}
                character_map: Dict[str, Character] = {str(char.id): char for char in characters_with_submitted_actions if hasattr(char, 'id')}


                for character in characters_with_submitted_actions:
                    char_id_str = str(getattr(character, 'id', None))
                    if not char_id_str: continue

                    actions_json_val = getattr(character, 'collected_actions_json', None)
                    actions_list: Optional[List[Dict[str, Any]]] = None
                    if isinstance(actions_json_val, list): # Already parsed
                        actions_list = actions_json_val
                    elif isinstance(actions_json_val, str):
                        try:
                            parsed_val = json.loads(actions_json_val)
                            if isinstance(parsed_val, list): actions_list = parsed_val
                        except json.JSONDecodeError:
                            logger.error(f"Failed to decode actions JSON for conflict, char {char_id_str}: '{actions_json_val}'", exc_info=True)

                    if actions_list:
                        player_actions_map_for_conflict[char_id_str] = actions_list

                conflict_analysis_result: Optional[Dict[str, Any]] = None
                conflict_resolver: Optional["ConflictResolver"] = getattr(self.game_manager, 'conflict_resolver', None)
                if player_actions_map_for_conflict and conflict_resolver and \
                   hasattr(conflict_resolver, 'analyze_actions_for_conflicts') and \
                   callable(getattr(conflict_resolver, 'analyze_actions_for_conflicts')):
                    conflict_analysis_result = await conflict_resolver.analyze_actions_for_conflicts(
                        player_actions_map=player_actions_map_for_conflict,
                        guild_id=guild_id,
                        rules_config=rules_config_data
                    )

                actions_to_execute_this_turn: List[Dict[str, Any]] = []
                if conflict_analysis_result:
                    if conflict_analysis_result.get("requires_manual_resolution"):
                        logger.info(f"TurnProcessor: Manual conflict resolution required for guild {guild_id}.")
                        for conflict_detail in conflict_analysis_result.get("pending_conflict_details", []):
                            logger.info(f"Conflict details for manual resolution: {conflict_detail}")
                            for char_id_in_conflict in conflict_detail.get("involved_player_ids", []):
                                if char_id_in_conflict in character_map:
                                    char_in_conflict = character_map[char_id_in_conflict]
                                    char_in_conflict.current_game_status = "ожидание_разрешения_конфликта"
                                    active_session.add(char_in_conflict)
                                    logger.info(f"Character {char_id_in_conflict} status set to 'ожидание_разрешения_конфликта'.")
                    actions_to_execute_this_turn.extend(conflict_analysis_result.get("actions_to_execute", []))
                    for auto_res_outcome in conflict_analysis_result.get("auto_resolution_outcomes", []):
                        logger.info(f"Auto-resolved conflict outcome: {auto_res_outcome}")
                else:
                    for char_id, actions in player_actions_map_for_conflict.items():
                        for action_data in actions:
                            actions_to_execute_this_turn.append({"character_id": char_id, "action_data": action_data})

                actions_by_character: Dict[str, List[Dict[str,Any]]] = {}
                for exec_action in actions_to_execute_this_turn:
                    char_id = str(exec_action["character_id"])
                    actions_by_character.setdefault(char_id, []).append(exec_action["action_data"])

                for character_id_str_loop, char_actions_list in actions_by_character.items():
                    character = character_map.get(character_id_str_loop)
                    if not character or character.current_game_status == "ожидание_разрешения_конфликта":
                        continue

                    char_id_for_processing = str(getattr(character, 'id', 'UNKNOWN'))
                    player_discord_id_for_log = "N/A"
                    char_manager: Optional["CharacterManager"] = getattr(self.game_manager, 'character_manager', None)
                    if hasattr(character, 'player_id') and character.player_id and char_manager and \
                       hasattr(char_manager, 'get_player_account_by_char_id') and \
                       callable(getattr(char_manager, 'get_player_account_by_char_id')):
                        player_obj = await char_manager.get_player_account_by_char_id(char_id_for_processing, guild_id)
                        if player_obj and hasattr(player_obj, 'discord_id'):
                            player_discord_id_for_log = str(player_obj.discord_id)

                    logger.info(f"Processing turn for character {char_id_for_processing} (Player Discord: {player_discord_id_for_log}) in guild {guild_id}.")

                    cap: Optional["CharacterActionProcessor"] = getattr(self.game_manager, 'character_action_processor', None)
                    notification_svc: Optional["NotificationService"] = getattr(self.game_manager, 'notification_service', None)

                    for action_data_to_exec in char_actions_list:
                        intent = action_data_to_exec.get("intent")
                        original_text = action_data_to_exec.get("original_text", "")
                        logger.debug(f"Character {char_id_for_processing} executing action: Intent='{intent}', Data='{action_data_to_exec}'")

                        action_result: Optional[Dict[str, Any]] = None
                        if not cap or not hasattr(cap, 'handle_explore_action') or not hasattr(cap, 'process_action_from_request'): # Check for specific methods if used directly
                            logger.error(f"CharacterActionProcessor or required methods not available for guild {guild_id}.")
                            if notification_svc and hasattr(notification_svc, 'send_character_feedback') and callable(getattr(notification_svc, 'send_character_feedback')):
                                await notification_svc.send_character_feedback(guild_id, char_id_for_processing, "Action processing system unavailable.", "system_error")
                            break

                        cap_context = { 'guild_id': guild_id, 'author_id': player_discord_id_for_log, 'channel_id': None, 'game_manager': self.game_manager, 'db_session': active_session }

                        try:
                            if intent == "INTENT_MOVE":
                                # Simplified, direct call to GameManager method, assuming it exists and is transactional or uses the session
                                move_target_name = action_data_to_exec.get('primary_target_entity', {}).get('name') # Example
                                if hasattr(self.game_manager, 'handle_move_action') and callable(getattr(self.game_manager, 'handle_move_action')):
                                    move_success = await self.game_manager.handle_move_action(guild_id, char_id_for_processing, move_target_name) # Removed session=
                                    action_result = {"success": move_success, "message": "Moved." if move_success else "Could not move."}
                                else: action_result = {"success": False, "message": "Move handling unavailable."}
                            elif intent == "INTENT_LOOK":
                                 action_result = await cap.handle_explore_action(character, guild_id, action_data_to_exec.get('primary_target_entity', {}).get('name'), cap_context.get('channel_id')) # Removed session=
                            else:
                                logger.info(f"Intent '{intent}' for char {char_id_for_processing} not fully handled by TurnProcessor yet.")
                                action_result = {"success": True, "message": f"Action '{original_text}' (Intent: {intent}) acknowledged."}

                            if notification_svc and hasattr(notification_svc, 'send_character_feedback') and callable(getattr(notification_svc, 'send_character_feedback')):
                                if action_result and action_result.get("success") and action_result.get("message"):
                                    await notification_svc.send_character_feedback(guild_id, char_id_for_processing, action_result["message"], "action_result")
                                elif action_result and action_result.get("message"):
                                    await notification_svc.send_character_feedback(guild_id, char_id_for_processing, action_result.get("message", "Action failed."), "action_error")

                            if character.current_game_status not in ["active", "actions_submitted"]:
                                logger.info(f"Character {char_id_for_processing} status changed. Ending turn early.")
                                break
                        except Exception as e_action_exec:
                            logger.error(f"Error executing action '{intent}' for char {char_id_for_processing}: {e_action_exec}", exc_info=True)
                            if notification_svc and hasattr(notification_svc, 'send_character_feedback') and callable(getattr(notification_svc, 'send_character_feedback')):
                                await notification_svc.send_character_feedback(guild_id, char_id_for_processing, f"Error: {original_text}", "system_error")
                            break

                    if character.current_game_status == "actions_submitted":
                        character.current_game_status = "active"

                    # Ensure collected_actions_json is assigned a JSON string or compatible type
                    if hasattr(character, 'collected_actions_json'):
                        character.collected_actions_json = "[]" # Assigning JSON string for Text/String column

                    active_session.add(character)
                    players_processed_count += 1
                    logger.info(f"Character {char_id_for_processing} actions processed. Status: '{character.current_game_status}'.")

                if hasattr(active_session, 'commit') and callable(active_session.commit):
                    await active_session.commit()
                logger.info(f"Successfully processed and committed turns for {players_processed_count} characters in guild {guild_id}.")

        except Exception as e_guild_processing:
            logger.error(f"Critical error during turn processing for guild {guild_id}: {e_guild_processing}", exc_info=True)
            if active_session and hasattr(active_session, 'is_active') and active_session.is_active and \
               hasattr(active_session, 'rollback') and callable(active_session.rollback):
                try:
                    await active_session.rollback()
                    logger.info(f"Session rolled back for guild {guild_id} due to critical error.")
                except Exception as e_rollback:
                    logger.error(f"Failed to rollback session for guild {guild_id}: {e_rollback}", exc_info=True)
        logger.info(f"Turn processing cycle finished for guild {guild_id}.")
