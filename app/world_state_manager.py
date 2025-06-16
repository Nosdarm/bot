from sqlalchemy.orm import Session # Keep for potential type hinting
from app.config import logger
from app import crud
from app.db import transactional_session
from app.models import WorldState

_world_state_cache = {} # Optional: Caching for world state if frequently read
DEFAULT_WORLD_STATE = {"game_time": "Year 1, Day 1", "era": "Age of Beginnings"}

def load_world_state(guild_id: int) -> dict:
    if guild_id in _world_state_cache:
        logger.debug(f"Returning cached WorldState for guild {guild_id}")
        return _world_state_cache[guild_id].copy() # Return a copy

    logger.debug(f"Loading WorldState for guild {guild_id} from DB.")
    with transactional_session(guild_id=guild_id) as db:
        # Assuming a generic getter or direct query.
        # For consistency, a crud.get_world_state_by_guild_id would be good.
        ws_entity = db.query(WorldState).filter(WorldState.guild_id == guild_id).first()

        if not ws_entity:
            logger.info(f"No WorldState found for guild {guild_id}. Creating with default state.")
            ws_data = {"guild_id": guild_id, "state_data": DEFAULT_WORLD_STATE.copy()}
            ws_entity = crud.create_entity(db, WorldState, ws_data)

        if ws_entity and ws_entity.state_data is not None:
            _world_state_cache[guild_id] = ws_entity.state_data.copy()
            return ws_entity.state_data.copy()
        else: # Should not happen if creation works
            logger.error(f"WorldState entity for guild {guild_id} has null state_data after load/create. Returning default.")
            _world_state_cache[guild_id] = DEFAULT_WORLD_STATE.copy()
            return DEFAULT_WORLD_STATE.copy()

def update_world_state_key(guild_id: int, key: str, value: any) -> dict:
    logger.debug(f"Updating WorldState for guild {guild_id}: {key} = {value}")
    with transactional_session(guild_id=guild_id) as db:
        ws_entity = db.query(WorldState).filter(WorldState.guild_id == guild_id).first()

        new_state_data = {}
        if not ws_entity:
            # If no world state, load_world_state will create one with defaults.
            # Then we can update it.
            logger.warning(f"WorldState not found for guild {guild_id} during update. Loading to create default first.")
            current_state_data = load_world_state(guild_id) # This ensures it's created and cached
            ws_entity = db.query(WorldState).filter(WorldState.guild_id == guild_id).first() # Re-fetch
            if not ws_entity: # Should absolutely not happen now
                logger.error(f"Failed to create/fetch WorldState for guild {guild_id} even after load_world_state. Aborting update.")
                return {} # Or raise error
            new_state_data = ws_entity.state_data.copy() if ws_entity.state_data else {}
        else:
            new_state_data = ws_entity.state_data.copy() if ws_entity.state_data else {}

        new_state_data[key] = value
        ws_entity.state_data = new_state_data # Re-assign to trigger SQLAlchemy change detection

        # crud.update_entity(db, ws_entity, {"state_data": new_state_data}) would also work
        # but direct assignment is fine if commit is handled by transactional_session.

        _world_state_cache[guild_id] = new_state_data.copy()
        return new_state_data.copy()
