from sqlalchemy.orm import Session
from typing import Tuple, Literal # For return type hint

from . import models # For models.Player, models.Location, models.Party
from . import player_manager, party_manager, locations_manager, rules_engine
from .config import logger

# Return type: A literal for success/failure, and a message string
MoveResult = Tuple[Literal['success', 'error'], str]

def handle_move_action(db: Session, guild_id: int, player_id: int, target_location_identifier: str) -> MoveResult:
    logger.info(f"Handling move action for player {player_id} in guild {guild_id} to '{target_location_identifier}'.")

    player = player_manager.get_player_by_id(db, player_id) # player_id is Player.id
    if not player:
        logger.error(f"Player {player_id} not found during move action.")
        return "error", "Player not found. Have you used `!start`?"

    if player.guild_id != guild_id: # Should ideally not happen if player_id is correctly fetched and scoped
        logger.error(f"Player {player_id} guild mismatch: expected {guild_id}, found {player.guild_id}.")
        return "error", "Player guild mismatch. This is an unexpected error."

    if not player.current_location_id:
        logger.warning(f"Player {player.id} (Discord: {player.discord_id}) has no current location.")
        return "error", "You are currently lost in the void (no current location). Cannot move."

    current_location = locations_manager.get_location(db, player.current_location_id)
    if not current_location:
        logger.error(f"Current location ID {player.current_location_id} for player {player.id} not found in DB.")
        return "error", "Your current location is invalid or does not exist. Cannot move."

    # Attempt to resolve target_location_identifier (currently assumes it's a static_id)
    target_location = locations_manager.get_location_by_static_id(db, guild_id, target_location_identifier)

    if not target_location:
        logger.warning(f"Target location '{target_location_identifier}' not found by static_id for guild {guild_id}.")
        # Future: Could try to resolve by i18n name here if static_id fails.
        return "error", f"Location '{target_location_identifier}' not found. Please use a valid location static ID."

    if current_location.id == target_location.id:
        return "success", "You are already at this location."

    # Check neighbor_locations_json for connectivity
    # Structure: {"target_static_id_1": {"en": "path", "ru": "тропа"}, ...}
    if not current_location.neighbor_locations_json or \
       target_location.static_id not in current_location.neighbor_locations_json:
        logger.info(f"Move denied: Location '{target_location.static_id}' is not a direct neighbor of '{current_location.static_id}'.")
        # We can use get_localized_text here if available from utils for a nicer message
        target_loc_name_for_msg = target_location.name_i18n.get(player.selected_language, target_location.static_id)
        return "error", f"You cannot move directly to '{target_loc_name_for_msg}' from your current location."

    # Check RuleConfig for movement rules (example)
    if not rules_engine.get_rule(guild_id, "global_movement_enabled", True): # Default to True if rule not set
        logger.info(f"Move denied for player {player.id}: Global movement disabled by Game Master for guild {guild_id}.")
        return "error", "Movement is currently disabled by the Game Master."
    # Future: Add more specific rule checks (e.g., location-specific, item requirements, status effects)

    # Update player's location
    player.current_location_id = target_location.id
    db.add(player) # Mark player object as changed for the session

    # Determine localized target location name for feedback
    # This requires importing get_localized_text or having it accessible.
    # For now, using direct dict access with fallback.
    target_loc_display_name = target_location.name_i18n.get(player.selected_language, target_location.name_i18n.get('en', target_location.static_id))
    feedback_message = f"You have moved to '{target_loc_display_name}'."

    # Handle party movement
    if player.current_party_id:
        party_moves_together = rules_engine.get_rule(guild_id, "party_movement_all_together", True)

        if party_moves_together:
            party = party_manager.get_party_by_id(db, player.current_party_id)
            if party and party.current_location_id != target_location.id:
                # Update party's canonical location
                party.current_location_id = target_location.id
                db.add(party)

                # Update all *other* online/active party members' locations as well.
                # The player initiating the move is already updated.
                # This ensures consistency if individual player locations are also primary.
                if party.player_ids_json:
                    for member_player_id_int in party.player_ids_json:
                        if member_player_id_int != player.id: # Don't re-process the initiating player
                            member_player = player_manager.get_player_by_id(db, member_player_id_int)
                            if member_player and member_player.current_location_id != target_location.id:
                                # Check if member is 'active' or similar status if needed
                                member_player.current_location_id = target_location.id
                                db.add(member_player)
                feedback_message += " Your party moves with you."

    # db.commit() will be handled by transactional_session in the command layer
    logger.info(f"Player {player.id} (Discord: {player.discord_id}) successfully moved to location {target_location.id} ('{target_location.static_id}').")
    return "success", feedback_message
