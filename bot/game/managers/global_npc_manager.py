import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select # Added for querying

from bot.game.models.global_npc import GlobalNpc
from bot.database.models import GlobalNpc as DBGlobalNpc
# from bot.game.models.location import Location # If needed for complex logic
# from bot.database.models import Location as DBLocation # If needed

# Assuming services are typed with Any for now, replace with actual types if available
# from bot.services.db_service import DbService # Example
# from bot.services.persistence_manager import PersistenceManager # Example
# from bot.services.config_service import ConfigService # Example
from bot.game.managers.location_manager import LocationManager # Example
from bot.game.rules.rule_engine import RuleEngine # Example
from bot.game.managers.event_manager import EventManager # Example
import random # For random movement

logger = logging.getLogger(__name__)

class GlobalNpcManager:
    def __init__(self, db_service: Any, persistence_manager: Any, config_service: Any, location_manager: Any):
        self.db_service = db_service
        self.persistence_manager = persistence_manager # May not be used in this basic version
        self.config_service = config_service # May not be used in this basic version
        self.location_manager = location_manager # May be used in process_tick later

    def _get_db_session(self) -> Session:
        return self.db_service.get_session()

    def _map_db_to_pydantic(self, db_npc: DBGlobalNpc) -> GlobalNpc:
        return GlobalNpc(
            id=db_npc.id,
            guild_id=db_npc.guild_id,
            name_i18n=db_npc.name_i18n or {},
            description_i18n=db_npc.description_i18n or {},
            current_location_id=db_npc.current_location_id,
            npc_template_id=db_npc.npc_template_id,
            state_variables=db_npc.state_variables or {},
            faction_id=db_npc.faction_id,
            is_active=db_npc.is_active
        )

    def _map_pydantic_to_db(self, pydantic_npc: GlobalNpc, db_npc: Optional[DBGlobalNpc] = None) -> DBGlobalNpc:
        if db_npc is None:
            db_npc = DBGlobalNpc(id=pydantic_npc.id) # Ensure ID is set for new instances

        db_npc.guild_id = pydantic_npc.guild_id
        db_npc.name_i18n = pydantic_npc.name_i18n
        db_npc.description_i18n = pydantic_npc.description_i18n
        db_npc.current_location_id = pydantic_npc.current_location_id
        db_npc.npc_template_id = pydantic_npc.npc_template_id
        db_npc.state_variables = pydantic_npc.state_variables
        db_npc.faction_id = pydantic_npc.faction_id
        db_npc.is_active = pydantic_npc.is_active
        return db_npc

    def get_global_npc(self, guild_id: str, npc_id: str) -> Optional[GlobalNpc]:
        with self._get_db_session() as session:
            try:
                db_npc = session.get(DBGlobalNpc, npc_id)
                if db_npc and db_npc.guild_id == guild_id and db_npc.is_active:
                    return self._map_db_to_pydantic(db_npc)
            except SQLAlchemyError as e:
                logger.error(f"Error fetching GlobalNpc {npc_id} for guild {guild_id}: {e}")
            return None

    def get_global_npcs_by_guild(self, guild_id: str) -> List[GlobalNpc]:
        npcs = []
        with self._get_db_session() as session:
            try:
                stmt = select(DBGlobalNpc).where(DBGlobalNpc.guild_id == guild_id, DBGlobalNpc.is_active == True)
                result = session.execute(stmt)
                db_npcs = result.scalars().all()
                npcs = [self._map_db_to_pydantic(db_npc) for db_npc in db_npcs]
            except SQLAlchemyError as e:
                logger.error(f"Error fetching GlobalNpcs for guild {guild_id}: {e}")
        return npcs

    def get_global_npcs_by_location(self, guild_id: str, location_id: str) -> List[GlobalNpc]:
        npcs = []
        with self._get_db_session() as session:
            try:
                stmt = select(DBGlobalNpc).where(
                    DBGlobalNpc.guild_id == guild_id,
                    DBGlobalNpc.current_location_id == location_id,
                    DBGlobalNpc.is_active == True
                )
                result = session.execute(stmt)
                db_npcs = result.scalars().all()
                npcs = [self._map_db_to_pydantic(db_npc) for db_npc in db_npcs]
            except SQLAlchemyError as e:
                logger.error(f"Error fetching GlobalNpcs for location {location_id} in guild {guild_id}: {e}")
        return npcs

    def create_global_npc(self, npc_data: GlobalNpc) -> Optional[GlobalNpc]:
        db_npc = self._map_pydantic_to_db(npc_data)
        with self._get_db_session() as session:
            try:
                session.add(db_npc)
                session.commit()
                session.refresh(db_npc) # To get any server-side defaults if applicable
                logger.info(f"GlobalNpc {db_npc.id} created for guild {db_npc.guild_id}.")
                return self._map_db_to_pydantic(db_npc)
            except SQLAlchemyError as e:
                logger.error(f"Error creating GlobalNpc for guild {npc_data.guild_id}: {e}")
                session.rollback()
            return None

    def update_global_npc(self, npc_id: str, npc_data: GlobalNpc) -> Optional[GlobalNpc]:
        with self._get_db_session() as session:
            try:
                db_npc = session.get(DBGlobalNpc, npc_id)
                if db_npc and db_npc.guild_id == npc_data.guild_id : # Check guild_id consistency
                    self._map_pydantic_to_db(npc_data, db_npc)
                    session.commit()
                    session.refresh(db_npc)
                    logger.info(f"GlobalNpc {npc_id} updated for guild {npc_data.guild_id}.")
                    return self._map_db_to_pydantic(db_npc)
                else:
                    logger.warning(f"GlobalNpc {npc_id} not found or guild mismatch for update.")
            except SQLAlchemyError as e:
                logger.error(f"Error updating GlobalNpc {npc_id}: {e}")
                session.rollback()
            return None

    def delete_global_npc(self, guild_id: str, npc_id: str) -> bool:
        with self._get_db_session() as session:
            try:
                db_npc = session.get(DBGlobalNpc, npc_id)
                if db_npc and db_npc.guild_id == guild_id:
                    db_npc.is_active = False # Soft delete
                    session.commit()
                    logger.info(f"GlobalNpc {npc_id} deactivated for guild {guild_id}.")
                    return True
                else:
                    logger.warning(f"GlobalNpc {npc_id} not found or guild mismatch for deactivation.")
            except SQLAlchemyError as e:
                logger.error(f"Error deactivating GlobalNpc {npc_id}: {e}")
                session.rollback()
            return False

    def process_tick(self, guild_id: str, game_time_delta: float, **kwargs) -> None:
        # Placeholder for future simulation logic
        # This method will be called periodically to update NPC states, handle movement, etc.
        # Example:
        # active_npcs = self.get_global_npcs_by_guild(guild_id)
        # for npc in active_npcs:
        #     # Simulate NPC behavior, decisions, movement
        #     # Update npc.state_variables or npc.current_location_id
        #     # self.update_global_npc(npc.id, npc)
        #     pass
        # logger.debug(f"Processing tick for GlobalNpcManager in guild {guild_id} with delta {game_time_delta}s.")

        # 1. Retrieve Dependencies from kwargs (guild_tick_context)
        location_manager: Optional[LocationManager] = kwargs.get('location_manager')
        rule_engine: Optional[RuleEngine] = kwargs.get('rule_engine') # For interaction logic
        event_manager: Optional[EventManager] = kwargs.get('event_manager') # For triggering events
        # Add other managers as needed, e.g., character_manager, mobile_group_manager for interactions

        if not location_manager: # RuleEngine and EventManager are optional for basic movement
            logger.warning(f"GlobalNpcManager: LocationManager not found in tick context for guild {guild_id}. Skipping tick.")
            return

        # 2. Load Active GlobalNPCs
        try:
            active_npcs = self.get_global_npcs_by_guild(guild_id)
            if not active_npcs:
                # logger.debug(f"GlobalNpcManager: No active GlobalNPCs to process for guild {guild_id}.")
                return
        except Exception as e:
            logger.error(f"GlobalNpcManager: Error loading active NPCs for guild {guild_id}: {e}")
            return

        # logger.info(f"GlobalNpcManager: Processing tick for {len(active_npcs)} GlobalNPCs in guild {guild_id}.")

        for npc in active_npcs:
            npc_updated = False
            original_location_id = npc.current_location_id

            # Ensure state_variables is a dict
            if npc.state_variables is None:
                npc.state_variables = {}

            try:
                # 3. Simulate Each GlobalNPC
                # Movement Logic
                patrol_points = npc.state_variables.get('patrol_points')
                if isinstance(patrol_points, list) and patrol_points:
                    current_patrol_index = npc.state_variables.get('current_patrol_index', 0)
                    if not isinstance(current_patrol_index, int) or current_patrol_index >= len(patrol_points) or current_patrol_index < 0:
                        current_patrol_index = 0 # Reset if invalid
                        npc.state_variables['current_patrol_index'] = 0

                    target_location_id = patrol_points[current_patrol_index]

                    if npc.current_location_id != target_location_id:
                        # Simulate movement - for now, assume direct travel if connected or if it's a general target
                        # More complex pathfinding could be added here via location_manager
                        # For simplicity, let's assume direct move if target is different.
                        # A real scenario would check connectivity or path.
                        npc.current_location_id = target_location_id
                        logger.info(f"GlobalNpc {npc.id} ({npc.name_i18n.get('en', 'Unknown')}) patrolling, moved to {target_location_id} in guild {guild_id}.")
                        npc_updated = True
                    else: # Arrived at current patrol point
                        logger.info(f"GlobalNpc {npc.id} ({npc.name_i18n.get('en', 'Unknown')}) reached patrol point {target_location_id} in guild {guild_id}.")
                        current_patrol_index = (current_patrol_index + 1) % len(patrol_points)
                        npc.state_variables['current_patrol_index'] = current_patrol_index
                        npc_updated = True

                # Simple random movement if no patrol logic executed and random_move flag is true
                elif npc.state_variables.get('allow_random_move', False): # Add a flag to enable/disable
                    if npc.current_location_id:
                        current_loc_obj = await location_manager.get_location(guild_id, npc.current_location_id) # Assume async
                        if current_loc_obj and current_loc_obj.exits:
                            # Filter out potential invalid exits if necessary
                            valid_exits = {k: v for k, v in current_loc_obj.exits.items() if v} # Basic check for non-empty exit target
                            if valid_exits:
                                chosen_exit_key = random.choice(list(valid_exits.keys()))
                                new_location_id = valid_exits[chosen_exit_key].get('target_location_id') # Assuming exit structure
                                if new_location_id and new_location_id != npc.current_location_id :
                                    npc.current_location_id = new_location_id
                                    logger.info(f"GlobalNpc {npc.id} ({npc.name_i18n.get('en', 'Unknown')}) randomly moved from {original_location_id} to {new_location_id} in guild {guild_id}.")
                                    npc_updated = True
                                # else:
                                    # logger.debug(f"GlobalNpc {npc.id} chose an invalid exit or same location, staying put.")
                            # else:
                                # logger.debug(f"GlobalNpc {npc.id} has no valid exits from {npc.current_location_id}.")
                        # else:
                            # logger.debug(f"GlobalNpc {npc.id} current location {npc.current_location_id} has no exits or not found.")
                    # else:
                        # logger.debug(f"GlobalNpc {npc.id} has no current_location_id for random movement.")


                # Interaction Logic (Placeholder)
                # Example: Check for other NPCs in the same location
                if npc.current_location_id and rule_engine and event_manager: # Ensure managers are available
                    # other_npcs_in_loc = self.get_global_npcs_by_location(guild_id, npc.current_location_id)
                    # for other_npc in other_npcs_in_loc:
                    #     if other_npc.id == npc.id: continue # Don't interact with self
                    #     # Use rule_engine to determine if interaction should occur
                    #     # e.g., based on faction_id, state_variables, etc.
                    #     interaction_details = rule_engine.evaluate_interaction(npc, other_npc, context=kwargs)
                    #     if interaction_details and interaction_details.get("should_interact"):
                    #         logger.info(f"GlobalNpc {npc.id} interacting with {other_npc.id} at {npc.current_location_id}.")
                    #         # Modify npc.state_variables or other_npc.state_variables
                    #         # event_manager.create_event_from_template("npc_encounter_event", npc.current_location_id, ...)
                    #         npc_updated = True # If state changed
                    #         # Potentially update other_npc as well
                    pass


                # Persist changes if NPC was updated
                if npc_updated:
                    self.update_global_npc(npc.id, npc_data=npc) # Pass the full pydantic model instance

            except Exception as e:
                logger.error(f"GlobalNpcManager: Error processing tick for NPC {npc.id} in guild {guild_id}: {e}", exc_info=True)

        # logger.debug(f"GlobalNpcManager: Finished processing tick for guild {guild_id}.")
