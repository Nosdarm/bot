import json
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession # For type hinting, though session is from db_service

from bot.database.models import Player
# Assuming get_entities and update_entity are suitable.
# If direct session usage (session.add for updates) is preferred, update_entity might not be strictly needed.
from bot.database.crud_utils import get_entities, update_entity

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
                # Fetch players who have submitted actions
                players_to_process = await get_entities(
                    session,
                    Player,
                    # guild_id argument in get_entities is for filtering by Player.guild_id directly
                    # if the table has a guild_id column, which Player does.
                    conditions=[Player.current_game_status == "actions_submitted", Player.guild_id == guild_id]
                )

                if not players_to_process:
                    logger.info(f"No players with submitted actions found in guild {guild_id}.")
                    # No commit needed if no changes are made.
                    return

                logger.info(f"Found {len(players_to_process)} players with submitted actions in guild {guild_id}.")

                for player in players_to_process:
                    try:
                        logger.info(f"Processing turn for player {player.id} (Discord: {player.discord_id}) in guild {guild_id}.")

                        # 1. Load and Parse Actions
                        actions_json_str = player.collected_actions_json
                        actions_list: List[Dict[str, Any]] = []
                        if actions_json_str:
                            try:
                                actions_list = json.loads(actions_json_str)
                                if not isinstance(actions_list, list):
                                    logger.warning(f"Player {player.id} actions JSON is not a list: {actions_json_str}. Treating as empty.")
                                    actions_list = []
                            except json.JSONDecodeError:
                                logger.error(f"Failed to decode actions JSON for player {player.id}: '{actions_json_str}'", exc_info=True)
                                # Potentially keep status as "actions_submitted" or move to an error state?
                                # For now, we'll clear actions and set to active, but this might need refinement.

                        logger.debug(f"Player {player.id} actions to process: {actions_list}")

                        # --- Action Execution Placeholder ---
                        # For this subtask, actual execution of actions is out of scope.
                        # In a full implementation, this is where each action in actions_list
                        # would be dispatched to the appropriate handler (e.g., CharacterActionProcessor).
                        if actions_list:
                            logger.info(f"Player {player.id} submitted {len(actions_list)} actions. Processing...")
                            for action_data in actions_list:
                                intent = action_data.get("intent")
                                entities = action_data.get("entities", [])
                                original_text = action_data.get("original_text", "")
                                logger.debug(f"Player {player.id} action: Intent='{intent}', Entities='{entities}', Original='{original_text}'")

                                if intent == "move":
                                    target_identifier = None
                                    for entity in entities:
                                        if entity.get("type") == "target_location_identifier":
                                            target_identifier = entity.get("name")
                                            break

                                    if not target_identifier:
                                        logger.error(f"Move intent for player {player.id} missing 'target_location_identifier' entity. Action: {action_data}")
                                        # Optionally send feedback to player about malformed move command
                                        if self.game_manager.notification_service:
                                            await self.game_manager.notification_service.send_player_feedback(
                                                guild_id, player.id, "Your move command was unclear. Please specify a target.", "action_error"
                                            )
                                        continue # Skip this action

                                    if not self.game_manager.location_manager:
                                        logger.error(f"LocationManager not available for move action, player {player.id}.")
                                        if self.game_manager.notification_service: # Inform player if possible
                                            await self.game_manager.notification_service.send_player_feedback(
                                                guild_id, player.id, "Movement system is currently unavailable. Please try again later.", "system_error"
                                            )
                                        continue # Skip this action

                                    logger.info(f"Executing move for player {player.id} to '{target_identifier}'.")
                                    success, message = await self.game_manager.location_manager.handle_move_action(
                                        guild_id, player.id, target_identifier
                                    )
                                    logger.info(f"Move action for player {player.id} to '{target_identifier}': Success={success}, Msg='{message}'")

                                    if self.game_manager.notification_service:
                                        await self.game_manager.notification_service.send_player_feedback(
                                            guild_id, player.id, message, "action_result" if success else "action_error"
                                        )
                                    else:
                                        logger.warning(f"NotificationService not available to send move feedback to player {player.id}.")
                                else:
                                    logger.info(f"Player {player.id} action intent '{intent}' not yet supported or understood in this context.")
                                    if self.game_manager.notification_service: # Inform player about unsupported action
                                        await self.game_manager.notification_service.send_player_feedback(
                                            guild_id, player.id, f"The action '{original_text}' (intent: {intent}) is not recognized or supported yet.", "action_error"
                                        )


                        # 2. Clear Actions and Update Status (after processing all actions for the player)
                        player.collected_actions_json = "[]"  # Clear actions
                        player.current_game_status = "active" # Set back to active or "idle"

                        # Add player to session to mark for update.
                        # update_entity is an alternative if we want to specify fields,
                        # but modifying the ORM object and adding to session is standard.
                        session.add(player)
                        # Example if using update_entity (less common for direct ORM object manipulation):
                        # await update_entity(session, player, {
                        #     "collected_actions_json": "[]",
                        #     "current_game_status": "active"
                        # })

                        players_processed_count += 1
                        logger.info(f"Player {player.id} actions cleared and status set to 'active'.")

                    except Exception as e_player:
                        logger.error(f"Error processing turn for player {player.id} in guild {guild_id}: {e_player}", exc_info=True)
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
