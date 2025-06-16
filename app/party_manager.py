from sqlalchemy.orm import Session
from typing import List
from app import models # Access to models.Party, models.Player
from app.config import logger
from app.db import transactional_session # For potential future use if functions here manage transactions
# from app import crud # If using generic CRUD functions as building blocks

# Note: These functions generally expect 'db' session to be passed by a calling context
# that manages the transaction (e.g., a command using 'with transactional_session(...)').

def get_party_by_id(db: Session, party_id: int) -> models.Party | None:
    """Fetches a party by its primary key (id)."""
    logger.debug(f"Fetching party by ID: {party_id}")
    return db.query(models.Party).filter(models.Party.id == party_id).first()

def get_party_by_name(db: Session, guild_id: int, name: str) -> models.Party | None:
    """Fetches a party by its guild_id and name."""
    logger.debug(f"Fetching party by name: {name} for guild_id: {guild_id}")
    return db.query(models.Party).filter(
        models.Party.guild_id == guild_id,
        models.Party.name == name
    ).first()

def get_player_party(db: Session, player_id: int) -> models.Party | None:
    """
    Fetches the party a player belongs to using Player.current_party_id.
    Assumes player_id is the Player's primary key (Player.id).
    """
    logger.debug(f"Fetching party for player_id: {player_id}")
    player = db.query(models.Player).filter(models.Player.id == player_id).first()
    if player and player.current_party_id:
        return get_party_by_id(db, player.current_party_id)
    return None

def add_player_to_party(db: Session, party: models.Party, player: models.Player) -> bool:
    """
    Adds a player to a party. Updates Party.player_ids_json and Player.current_party_id.
    Assumes 'db' is a session from a transactional context.
    Returns True if successful, False otherwise.
    """
    if not party or not player:
        logger.warning("add_player_to_party: Party or Player object is None.")
        return False

    # Ensure player_ids_json is a list
    if party.player_ids_json is None:
        party.player_ids_json = []

    # Check if player is already in a party or this party
    if player.current_party_id == party.id and player.id in party.player_ids_json:
        logger.info(f"Player {player.id} is already in party {party.id}.")
        return True # Or False if this should be an error condition

    if player.current_party_id is not None and player.current_party_id != party.id:
        # Player is in another party, handle this case (e.g., remove from old party first or error)
        logger.warning(f"Player {player.id} is already in another party ({player.current_party_id}). Cannot add to party {party.id}.")
        # Depending on game logic, you might auto-remove from the old party.
        # For now, let's prevent adding to a new party if already in one.
        return False

    # Add player
    if player.id not in party.player_ids_json:
        new_player_ids = list(party.player_ids_json) # Create a mutable copy
        new_player_ids.append(player.id)
        party.player_ids_json = new_player_ids # Re-assign to trigger SQLAlchemy change detection for JSON

    player.current_party_id = party.id

    # db.commit() and db.refresh() should be handled by the transactional_session wrapper
    logger.info(f"Player {player.id} added to party {party.id}. Party members: {party.player_ids_json}")
    return True


def remove_player_from_party(db: Session, player: models.Player) -> bool:
    """
    Removes a player from their current party.
    Updates Party.player_ids_json and sets Player.current_party_id to None.
    Assumes 'db' is a session from a transactional context.
    Returns True if successful, False otherwise.
    """
    if not player or player.current_party_id is None:
        logger.warning(f"remove_player_from_party: Player {player.id if player else 'None'} is not in any party.")
        return False

    party = get_party_by_id(db, player.current_party_id)
    if not party:
        logger.error(f"Party {player.current_party_id} not found for player {player.id}, but player record indicates membership.")
        player.current_party_id = None # Correct inconsistent data
        return False

    if party.player_ids_json and player.id in party.player_ids_json:
        new_player_ids = list(party.player_ids_json) # Create a mutable copy
        new_player_ids.remove(player.id)
        party.player_ids_json = new_player_ids # Re-assign to trigger SQLAlchemy change detection

    player.current_party_id = None

    # If party becomes empty, or leader leaves, specific game logic might be needed.
    # For example, disband party if empty, or assign new leader.
    # This basic function only removes the player.
    if not party.player_ids_json:
        logger.info(f"Party {party.id} is now empty after removing player {player.id}. Consider disbanding.")
    elif party.leader_id == player.id:
        logger.warning(f"Leader (Player {player.id}) left party {party.id}. New leader needs to be assigned.")

    # db.commit() and db.refresh() should be handled by the transactional_session wrapper
    logger.info(f"Player {player.id} removed from party {party.id}.")
    return True
