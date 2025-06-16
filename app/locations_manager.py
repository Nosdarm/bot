from sqlalchemy.orm import Session
from app import models # To access models.Location
from app.config import logger # For logging, if needed
from .utils import get_localized_text # Import the new utility
# from app import crud # Not strictly needed for these basic getters yet
# from app.db import transactional_session # Not strictly needed for these basic getters yet

# Note: These initial functions operate on a passed 'db' session.
# They don't manage transactions themselves; that's up to the caller (e.g., using transactional_session).

def get_location(db: Session, location_id: int) -> models.Location | None:
    """Fetches a location by its primary key (id)."""
    logger.debug(f"Fetching location by ID: {location_id}")
    return db.query(models.Location).filter(models.Location.id == location_id).first()

def get_location_by_static_id(db: Session, guild_id: int, static_id: str) -> models.Location | None:
    """Fetches a location by its guild_id and static_id."""
    logger.debug(f"Fetching location by static_id: {static_id} for guild_id: {guild_id}")
    return db.query(models.Location).filter(
        models.Location.guild_id == guild_id,
        models.Location.static_id == static_id
    ).first()

# Example of a function that might use get_localized_text later (not part of this step's direct implementation)
# from .utils import get_localized_text
# def get_location_name(location: models.Location, language: str, default_lang: str = 'en') -> str:
#     return get_localized_text(location.name_i18n, language, default_lang)
