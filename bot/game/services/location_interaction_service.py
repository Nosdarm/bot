import logging
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Player, Location
from bot.database.crud_utils import get_entity_by_id # Assuming player_id and location_id are PKs

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__)

class LocationInteractionService:
    def __init__(self, game_manager: "GameManager"):
        self.game_manager = game_manager
        if not self.game_manager:
            logger.critical("LocationInteractionService initialized without a valid GameManager instance!")
        logger.info("LocationInteractionService initialized.")

    async def handle_intra_location_action(
        self,
        guild_id: str,
        player_id: str, # This is Player.id (PK)
        action_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Placeholder method to handle actions within a location.
        Currently, it loads player and location and returns a placeholder message.
        Actual interaction logic (e.g., with features, items, NPCs in the location) will be added later.
        """
        log_prefix = f"IntraLocationAction (Guild: {guild_id}, Player: {player_id})"
        logger.info(f"{log_prefix}: Received action. Data: {action_data}")

        if not self.game_manager or not self.game_manager.db_service:
            logger.error(f"{log_prefix}: GameManager or DBService not available.")
            return False, "Core services are unavailable. Please try again later."

        db_service = self.game_manager.db_service

        async with db_service.get_session() as session:
            try:
                # Load Player
                player = await get_entity_by_id(session, Player, player_id)
                if not player:
                    logger.warning(f"{log_prefix}: Player not found.")
                    return False, "Player not found. Have you registered?"
                if player.guild_id != guild_id:
                    logger.error(f"{log_prefix}: Player {player_id} guild mismatch (player actual: {player.guild_id}).")
                    return False, "Player data mismatch."

                # Load Current Location of the Player
                if not player.current_location_id:
                    logger.warning(f"{log_prefix}: Player {player_id} has no current_location_id.")
                    return False, "Your current location is unknown."

                location = await get_entity_by_id(session, Location, player.current_location_id)
                if not location:
                    logger.warning(f"{log_prefix}: Current location {player.current_location_id} for player {player_id} not found in DB.")
                    return False, "Your current location data seems to be missing."
                if location.guild_id != guild_id: # Should be redundant if player.current_location_id is always valid for the guild
                    logger.error(f"{log_prefix}: Location {location.id} guild mismatch (location actual: {location.guild_id}).")
                    return False, "Location data mismatch."

                # Extract Intent and Target Name
                intent = action_data.get("intent")
                target_object_name = ""
                entities = action_data.get("entities", [])
                if entities and isinstance(entities, list):
                    for entity in entities: # Iterate to find the target object/NPC name
                        if entity.get("type") in ["target_object_name", "target_npc_name", "target_location_identifier"]: # target_location_identifier for completeness if NLU provides it for features
                            target_object_name = entity.get("name", "").lower().strip()
                            break # Use the first one found

                if not intent:
                    logger.warning(f"{log_prefix}: Action intent unclear. Data: {action_data}")
                    return False, "Your action's intent is unclear."

                location_name_for_log = location.name_i18n.get('en', location.id) if location.name_i18n else location.id
                logger.info(f"{log_prefix}: Player {player.id} attempts to '{intent}' with target '{target_object_name}' in location {location.id} ('{location_name_for_log}').")

                # Handle "examine_object" Intent
                if intent == "examine_object":
                    if not target_object_name:
                        return False, "What exactly do you want to examine?"

                    normalized_target_key = target_object_name.lower().strip().replace(" ", "_") # Added strip()
                    logger.debug(f"{log_prefix}: Normalized target key for examine: '{normalized_target_key}' from raw '{target_object_name}'.")

                    player_lang = player.selected_language or await self.game_manager.get_rule(guild_id, 'default_language', 'en')

                    description_to_send = None
                    description_found = False

                    if location.details_i18n and isinstance(location.details_i18n, dict):
                        # Try player's language first
                        lang_specific_details = location.details_i18n.get(player_lang)
                        if isinstance(lang_specific_details, dict):
                            description = lang_specific_details.get(normalized_target_key)
                            if description and isinstance(description, str) and description.strip():
                                description_to_send = description
                                description_found = True
                                logger.info(f"{log_prefix}: Found description for '{normalized_target_key}' in location.details_i18n (lang: {player_lang}).")

                        # If not found in player's language, try English as fallback (if player_lang is not 'en')
                        if not description_found and player_lang != 'en':
                            en_details = location.details_i18n.get('en')
                            if isinstance(en_details, dict):
                                description = en_details.get(normalized_target_key)
                                if description and isinstance(description, str) and description.strip():
                                    description_to_send = description
                                    description_found = True
                                    logger.info(f"{log_prefix}: Found description for '{normalized_target_key}' in location.details_i18n (lang: en fallback).")

                    if not description_found:
                         # Fallback if details_i18n is missing or doesn't contain the key in any relevant language.
                         logger.info(f"{log_prefix}: No specific examinable detail found for '{normalized_target_key}' (raw: '{target_object_name}').")
                         # Use the raw target_object_name for the feedback message to the user for clarity.
                         return False, f"You look closely at the {target_object_name}, but can't discern any specific details, or it's not something you can examine here."

                    return True, description_to_send

                elif intent in ["take_item", "use_item", "open_container", "search_container_or_area", "initiate_dialogue"]:
                    if not target_object_name and intent != "search_container_or_area": # search can be general
                         return False, f"What do you want to {intent.replace('_', ' ')}?"
                    target_display_name = target_object_name if target_object_name else "the area"
                    logger.info(f"{log_prefix}: Intent '{intent}' for target '{target_display_name}' is under development.")
                    return True, f"You attempt to {intent.replace('_', ' ')} '{target_display_name}'. This specific action is still under development."

                else:
                    logger.warning(f"{log_prefix}: Unknown or unsupported intent '{intent}'.")
                    return False, f"You're not sure how to '{intent}'."

            except Exception as e:
                logger.error(f"{log_prefix}: Error during intra-location action: {e}", exc_info=True)
                return False, "An unexpected error occurred while performing your action."
