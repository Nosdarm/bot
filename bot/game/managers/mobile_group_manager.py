import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select # Added for querying

from bot.game.models.mobile_group import MobileGroup
from bot.database.models import MobileGroup as DBMobileGroup
from bot.game.managers.global_npc_manager import GlobalNpcManager # If direct interaction needed
from bot.game.managers.location_manager import LocationManager # If direct interaction needed
from bot.game.rules.rule_engine import RuleEngine # Example
from bot.game.managers.event_manager import EventManager # Example
# from bot.game.managers.character_manager import CharacterManager # Example for player interactions
import random # For random destination setting

# Assuming services are typed with Any for now
# from bot.services.db_service import DbService # Example
# from bot.services.persistence_manager import PersistenceManager # Example
# from bot.services.config_service import ConfigService # Example

logger = logging.getLogger(__name__)

class MobileGroupManager:
    def __init__(self, db_service: Any, persistence_manager: Any, config_service: Any,
                 location_manager: Any, global_npc_manager: Any):
        self.db_service = db_service
        self.persistence_manager = persistence_manager
        self.config_service = config_service
        self.location_manager = location_manager # For movement logic in process_tick
        self.global_npc_manager = global_npc_manager # For member details if needed

    def _get_db_session(self) -> Session:
        return self.db_service.get_session()

    def _map_db_to_pydantic(self, db_group: DBMobileGroup) -> MobileGroup:
        return MobileGroup(
            id=db_group.id,
            guild_id=db_group.guild_id,
            name_i18n=db_group.name_i18n or {},
            description_i18n=db_group.description_i18n or {},
            current_location_id=db_group.current_location_id,
            member_ids=db_group.member_ids or [],
            destination_location_id=db_group.destination_location_id,
            state_variables=db_group.state_variables or {},
            is_active=db_group.is_active
        )

    def _map_pydantic_to_db(self, pydantic_group: MobileGroup, db_group: Optional[DBMobileGroup] = None) -> DBMobileGroup:
        if db_group is None:
            db_group = DBMobileGroup(id=pydantic_group.id) # Ensure ID is set

        db_group.guild_id = pydantic_group.guild_id
        db_group.name_i18n = pydantic_group.name_i18n
        db_group.description_i18n = pydantic_group.description_i18n
        db_group.current_location_id = pydantic_group.current_location_id
        db_group.member_ids = pydantic_group.member_ids
        db_group.destination_location_id = pydantic_group.destination_location_id
        db_group.state_variables = pydantic_group.state_variables
        db_group.is_active = pydantic_group.is_active
        return db_group

    def get_mobile_group(self, guild_id: str, group_id: str) -> Optional[MobileGroup]:
        with self._get_db_session() as session:
            try:
                db_group = session.get(DBMobileGroup, group_id)
                if db_group and db_group.guild_id == guild_id and db_group.is_active:
                    return self._map_db_to_pydantic(db_group)
            except SQLAlchemyError as e:
                logger.error(f"Error fetching MobileGroup {group_id} for guild {guild_id}: {e}")
            return None

    def get_mobile_groups_by_guild(self, guild_id: str) -> List[MobileGroup]:
        groups = []
        with self._get_db_session() as session:
            try:
                stmt = select(DBMobileGroup).where(DBMobileGroup.guild_id == guild_id, DBMobileGroup.is_active == True)
                result = session.execute(stmt)
                db_groups = result.scalars().all()
                groups = [self._map_db_to_pydantic(db_group) for db_group in db_groups]
            except SQLAlchemyError as e:
                logger.error(f"Error fetching MobileGroups for guild {guild_id}: {e}")
        return groups

    def create_mobile_group(self, group_data: MobileGroup) -> Optional[MobileGroup]:
        db_group = self._map_pydantic_to_db(group_data)
        with self._get_db_session() as session:
            try:
                session.add(db_group)
                session.commit()
                session.refresh(db_group)
                logger.info(f"MobileGroup {db_group.id} created for guild {db_group.guild_id}.")
                return self._map_db_to_pydantic(db_group)
            except SQLAlchemyError as e:
                logger.error(f"Error creating MobileGroup for guild {group_data.guild_id}: {e}")
                session.rollback()
            return None

    def update_mobile_group(self, group_id: str, group_data: MobileGroup) -> Optional[MobileGroup]:
        with self._get_db_session() as session:
            try:
                db_group = session.get(DBMobileGroup, group_id)
                if db_group and db_group.guild_id == group_data.guild_id: # Check guild_id consistency
                    self._map_pydantic_to_db(group_data, db_group)
                    session.commit()
                    session.refresh(db_group)
                    logger.info(f"MobileGroup {group_id} updated for guild {group_data.guild_id}.")
                    return self._map_db_to_pydantic(db_group)
                else:
                    logger.warning(f"MobileGroup {group_id} not found or guild mismatch for update.")
            except SQLAlchemyError as e:
                logger.error(f"Error updating MobileGroup {group_id}: {e}")
                session.rollback()
            return None

    def delete_mobile_group(self, guild_id: str, group_id: str) -> bool:
        with self._get_db_session() as session:
            try:
                db_group = session.get(DBMobileGroup, group_id)
                if db_group and db_group.guild_id == guild_id:
                    db_group.is_active = False # Soft delete
                    session.commit()
                    logger.info(f"MobileGroup {group_id} deactivated for guild {guild_id}.")
                    return True
                else:
                    logger.warning(f"MobileGroup {group_id} not found or guild mismatch for deactivation.")
            except SQLAlchemyError as e:
                logger.error(f"Error deactivating MobileGroup {group_id}: {e}")
                session.rollback()
            return False

    def process_tick(self, guild_id: str, game_time_delta: float, **kwargs) -> None:
        # Placeholder for future simulation logic (e.g., movement towards destination_location_id)
        # Example:
        # active_groups = self.get_mobile_groups_by_guild(guild_id)
        # for group in active_groups:
        #     if group.destination_location_id and group.current_location_id != group.destination_location_id:
        #         # Simulate movement, potentially using self.location_manager
        #         # Update group.current_location_id or group.state_variables (e.g., travel progress)
        #         # self.update_mobile_group(group.id, group)
        #         logger.info(f"MobileGroup {group.id} is moving towards {group.destination_location_id}.")
        #     pass
        # logger.debug(f"Processing tick for MobileGroupManager in guild {guild_id} with delta {game_time_delta}s.")

        # 1. Retrieve Dependencies
        location_manager: Optional[LocationManager] = kwargs.get('location_manager')
        rule_engine: Optional[RuleEngine] = kwargs.get('rule_engine')
        event_manager: Optional[EventManager] = kwargs.get('event_manager')
        # global_npc_manager is self.global_npc_manager, already injected
        # character_manager: Optional[CharacterManager] = kwargs.get('character_manager')

        if not location_manager or not self.global_npc_manager:
            logger.warning(f"MobileGroupManager: Essential managers (LocationManager or own GlobalNpcManager) not available for guild {guild_id}. Skipping tick.")
            return

        # 2. Load Active MobileGroups
        try:
            active_groups = self.get_mobile_groups_by_guild(guild_id)
            if not active_groups:
                # logger.debug(f"MobileGroupManager: No active mobile groups to process for guild {guild_id}.")
                return
        except Exception as e:
            logger.error(f"MobileGroupManager: Error loading active mobile groups for guild {guild_id}: {e}")
            return

        # logger.info(f"MobileGroupManager: Processing tick for {len(active_groups)} MobileGroups in guild {guild_id}.")

        for group in active_groups:
            group_updated = False
            original_location_id = group.current_location_id

            if group.state_variables is None: # Ensure state_variables is a dict
                group.state_variables = {}

            try:
                # 3. Simulate Each MobileGroup
                # Group Movement Logic
                if group.destination_location_id and group.destination_location_id != group.current_location_id:
                    # Simple movement: assume direct travel for now.
                    # A real implementation might involve pathfinding via location_manager,
                    # checking travel time, terrain effects from group.state_variables, etc.

                    # For this example, let's assume it takes one tick to reach the destination if it's directly connected.
                    # In a real game, this would be more complex (e.g., based on distance, speed in state_variables).

                    # Check if locations are connected (optional, could be part of pathfinding)
                    # connected = await location_manager.are_locations_connected(guild_id, group.current_location_id, group.destination_location_id)
                    # if connected: # Or if path exists

                    group.current_location_id = group.destination_location_id # Arrived
                    logger.info(f"MobileGroup {group.id} ({group.name_i18n.get('en', 'Unknown')}) moved from {original_location_id} to {group.current_location_id} (Destination) in guild {guild_id}.")
                    group_updated = True

                    # Update Member Locations
                    if group.member_ids:
                        for member_id in group.member_ids:
                            # Assuming members are GlobalNPCs for now. Could check type if mixed.
                            member_npc = await self.global_npc_manager.get_global_npc(guild_id, member_id) # Assume async
                            if member_npc:
                                member_npc.current_location_id = group.current_location_id
                                await self.global_npc_manager.update_global_npc(member_npc.id, member_npc) # Assume async
                                # logger.debug(f"Updated location of member {member_npc.id} of group {group.id} to {group.current_location_id}")
                            # else:
                                # logger.warning(f"Could not find member NPC {member_id} to update location for group {group.id}")
                    # else: # At destination
                        # logger.info(f"MobileGroup {group.id} ({group.name_i18n.get('en', 'Unknown')}) reached destination {group.destination_location_id} in guild {guild_id}.")
                        # group.destination_location_id = None # Clear destination or set new one based on logic
                        # group_updated = True

                elif not group.destination_location_id and group.state_variables.get('allow_random_patrol', False): # If idle and allowed, pick a random destination
                    if group.current_location_id:
                        all_locations = await location_manager.get_all_locations(guild_id) # Assume async
                        if all_locations:
                            # Filter out current location and pick a random one
                            possible_destinations = [loc.id for loc in all_locations if loc.id != group.current_location_id]
                            if possible_destinations:
                                group.destination_location_id = random.choice(possible_destinations)
                                logger.info(f"MobileGroup {group.id} ({group.name_i18n.get('en', 'Unknown')}) is now heading towards a new random destination: {group.destination_location_id} from {group.current_location_id}.")
                                group_updated = True


                # Conflict/Encounter Logic (Placeholder)
                if group.current_location_id and rule_engine and event_manager:
                    # Example: Check for other mobile groups or global NPCs at the same location
                    # other_groups = self.get_mobile_groups_by_guild(guild_id) # This gets all, need to filter by location
                    # for other_entity in other_groups_or_npcs_at_location:
                    #    if rule_engine.evaluate_conflict(group, other_entity, context=kwargs):
                    #        logger.info(f"MobileGroup {group.id} encountered hostile entity {other_entity.id} at {group.current_location_id}.")
                    #        # event_manager.create_event_from_template("group_encounter_event", group.current_location_id, involved_entities=[group.id, other_entity.id])
                    #        # Or create PendingConflict
                    #        group_updated = True
                    pass

                # Update Group if Changed
                if group_updated:
                    self.update_mobile_group(group.id, group_data=group) # Pass Pydantic model

            except Exception as e:
                logger.error(f"MobileGroupManager: Error processing tick for group {group.id} in guild {guild_id}: {e}", exc_info=True)

        # logger.debug(f"MobileGroupManager: Finished processing tick for guild {guild_id}.")
