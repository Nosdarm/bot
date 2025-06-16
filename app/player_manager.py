from sqlalchemy.orm import Session
from app import models # To access models.Player
from typing import List
from app.config import logger # For logging, if needed

# Note: These functions generally expect 'db' session to be passed by a calling context
# that manages the transaction.

def get_players_in_location(db: Session, guild_id: int, location_id: int) -> List[models.Player]:
    """Fetches all players in a specific location within a guild."""
    logger.debug(f"Fetching players in location_id: {location_id} for guild_id: {guild_id}")
    return db.query(models.Player).filter(
        models.Player.guild_id == guild_id,
        models.Player.current_location_id == location_id
    ).all()

def get_player_by_id(db: Session, player_id: int) -> models.Player | None:
    """Fetches a player by their primary key (id)."""
    logger.debug(f"Fetching player by ID: {player_id}")
    return db.query(models.Player).filter(models.Player.id == player_id).first()

# get_player_by_discord_id was already added to crud.py, which is a more general place.
# If more player-specific complex logic arises, this manager can be expanded.
