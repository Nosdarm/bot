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
                # Fetch characters who have submitted actions
                characters_to_process = await get_entities(
                    session,
                    Character, # MODIFIED: Query Character model
                    conditions=[Character.current_game_status == "actions_submitted", Character.guild_id == guild_id]
                )

                if not characters_to_process:
                    logger.info(f"No characters with submitted actions found in guild {guild_id}.")
                    return

                logger.info(f"Found {len(characters_to_process)} characters with submitted actions in guild {guild_id}.")

                for character in characters_to_process: # MODIFIED: Iterate through characters
                    try:
                        # Attempt to get player_id for logging, if available
                        player_discord_id_for_log = "N/A"
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

                                if intent == "move":
                                    target_identifier = None
                                    for entity in entities:
                                        if entity.get("type") == "target_location_identifier":
                                            target_identifier = entity.get("name")
                                            break

                                    if not target_identifier:
                                        logger.error(f"Move intent for character {character.id} missing 'target_location_identifier' entity. Action: {action_data}")
                                        if self.game_manager.notification_service:
                                            await self.game_manager.notification_service.send_character_feedback( # MODIFIED: send_character_feedback
                                                guild_id, character.id, "Your move command was unclear. Please specify a target.", "action_error"
                                            )
                                        continue

                                    if not self.game_manager.location_manager:
                                        logger.error(f"LocationManager not available for move action, character {character.id}.")
                                        if self.game_manager.notification_service:
                                            await self.game_manager.notification_service.send_character_feedback( # MODIFIED
                                                guild_id, character.id, "Movement system is currently unavailable. Please try again later.", "system_error"
                                            )
                                        continue

                                    logger.info(f"Executing move for character {character.id} to '{target_identifier}'.")
                                    # handle_move_action in LocationManager likely expects character_id
                                    success, message = await self.game_manager.location_manager.handle_move_action(
                                        guild_id, character.id, target_identifier
                                    )
                                    logger.info(f"Move action for character {character.id} to '{target_identifier}': Success={success}, Msg='{message}'")

                                    if self.game_manager.notification_service:
                                        await self.game_manager.notification_service.send_character_feedback( # MODIFIED
                                            guild_id, character.id, message, "action_result" if success else "action_error"
                                        )
                                    else:
                                        logger.warning(f"NotificationService not available to send move feedback to character {character.id}.")
                                else:
                                    logger.info(f"Character {character.id} action intent '{intent}' not yet supported or understood in this context.")
                                    if self.game_manager.notification_service:
                                        await self.game_manager.notification_service.send_character_feedback( # MODIFIED
                                            guild_id, character.id, f"The action '{original_text}' (intent: {intent}) is not recognized or supported yet.", "action_error"
                                        )

                        character.collected_actions_json = "[]"
                        character.current_game_status = "active"

                        session.add(character) # MODIFIED: Add character to session

                        players_processed_count += 1 # This counter now refers to characters
                        logger.info(f"Character {character.id} actions cleared and status set to 'active'.")

                    except Exception as e_player: # Renamed to e_char for clarity
                        logger.error(f"Error processing turn for character {character.id} in guild {guild_id}: {e_player}", exc_info=True)
                        # Decide on error strategy: continue with other players, or rollback this player's changes?
                        # The current structure will commit successful player updates even if one fails.
                        # If atomicity per player is needed, a nested session or savepoint might be used,
                        # but for now, one failed player won't stop others.
                        # The overall session commit is outside this inner loop.

                # Commit all changes for the processed players in this guild
                await session.commit()
                logger.info(f"Successfully processed and committed turns for {players_processed_count} players in guild {guild_id}.")

            except Exception as e_guild:
                logger.error(f"Error during turn processing for guild {guild_id} (before or during commit): {e_guild}", exc_info=True)
                await session.rollback() # Rollback any changes if error occurs during fetching or outer loop
                logger.info(f"Session rolled back for guild {guild_id} due to error.")

        logger.info(f"Turn processing finished for guild {guild_id}.")
