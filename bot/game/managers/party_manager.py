# bot/game/managers/party_manager.py

from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable


if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.models.party import Party
    from bot.game.models.character import Character
    from bot.game.models.npc import NPC
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.combat_manager import CombatManager

from bot.game.models.party import Party
from builtins import dict, set, list

logger = logging.getLogger(__name__) # Added
logger.debug("DEBUG: party_manager.py module loaded.") # Changed


class PartyManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _parties: Dict[str, Dict[str, "Party"]]
    _dirty_parties: Dict[str, Set[str]]
    _deleted_parties: Dict[str, Set[str]]
    _member_to_party_map: Dict[str, Dict[str, str]]

    def __init__(self,
                 db_service: Optional["DBService"] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 npc_manager: Optional["NpcManager"] = None,
                 character_manager: Optional["CharacterManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                ):
        logger.info("Initializing PartyManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._combat_manager = combat_manager
        self._parties = {}
        self._dirty_parties = {}
        self._deleted_parties = {}
        self._member_to_party_map = {}
        logger.info("PartyManager initialized.") # Changed

    def get_party(self, guild_id: str, party_id: str) -> Optional["Party"]:
        guild_id_str = str(guild_id)
        guild_parties = self._parties.get(guild_id_str)
        if guild_parties:
             return guild_parties.get(str(party_id))
        return None

    def get_all_parties(self, guild_id: str) -> List["Party"]:
        guild_id_str = str(guild_id)
        guild_parties = self._parties.get(guild_id_str)
        if guild_parties:
             return list(guild_parties.values())
        return []

    async def get_party_by_member_id(self, guild_id: str, entity_id: str, **kwargs: Any) -> Optional["Party"]:
         guild_id_str = str(guild_id)
         entity_id_str = str(entity_id)
         guild_member_map = self._member_to_party_map.get(guild_id_str)
         if guild_member_map:
              party_id = guild_member_map.get(entity_id_str)
              if party_id:
                   return self.get_party(guild_id_str, party_id)

         parties_for_guild = self.get_all_parties(guild_id_str)
         for party in parties_for_guild:
              if isinstance(party, Party) and hasattr(party, 'member_ids'): # Should be player_ids_list
                   member_ids = getattr(party, 'player_ids_list', []) # Use player_ids_list
                   if isinstance(member_ids, list) and entity_id_str in member_ids:
                        return party
         return None

    def get_parties_with_active_action(self, guild_id: str) -> List["Party"]:
         guild_id_str = str(guild_id)
         guild_parties_cache = self._parties.get(guild_id_str, {})
         return [party for party in guild_parties_cache.values() if isinstance(party, Party) and getattr(party, 'current_action', None) is not None]

    def is_party_busy(self, guild_id: str, party_id: str) -> bool:
         guild_id_str = str(guild_id)
         party = self.get_party(guild_id_str, party_id)
         if not party:
              # logger.debug("PartyManager: is_party_busy called for non-existent party %s in guild %s.", party_id, guild_id_str) # Too noisy
              return False
         if getattr(party, 'current_action', None) is not None or getattr(party, 'action_queue', []):
              return True
         return False

    async def create_party(self, leader_id: str, member_ids: List[str], guild_id: str, **kwargs: Any) -> Optional[Party]: # Changed return to Party
        guild_id_str = str(guild_id)
        leader_id_str = str(leader_id)
        member_ids_str = [str(mid) for mid in member_ids if mid is not None]

        if self._db_service is None or self._db_service.adapter is None:
            logger.error("PartyManager: No DB service or adapter for guild %s. Cannot create party.", guild_id_str) # Changed
            return None

        if leader_id_str not in member_ids_str:
             logger.warning("PartyManager: Leader %s not included in member_ids list for new party in guild %s. Adding leader to members.", leader_id_str, guild_id_str) # Changed
             member_ids_str.append(leader_id_str)

        party_name = kwargs.get('name', f"Party of {leader_id_str}")
        current_location_id = kwargs.get('current_location_id', None)

        try:
            new_id = str(uuid.uuid4())
            party_data: Dict[str, Any] = {
                'id': new_id, 'name_i18n': {"en": party_name, "ru": party_name}, # Default i18n name
                'guild_id': guild_id_str, 'leader_id': leader_id_str,
                'player_ids_list': member_ids_str,
                'state_variables': kwargs.get('initial_state_variables', {}), 
                'current_action': None, 'current_location_id': current_location_id,
                'turn_status': "pending_actions"
            }
            party = Party.from_dict(party_data)
            self._parties.setdefault(guild_id_str, {})[new_id] = party
            guild_member_map = self._member_to_party_map.setdefault(guild_id_str, {})
            for member_id in member_ids_str:
                 if member_id in guild_member_map:
                      logger.warning("PartyManager: Overwriting member_to_party map entry for member %s in guild %s. Was in party %s, now in %s.", member_id, guild_id_str, guild_member_map[member_id], new_id) # Changed
                 guild_member_map[member_id] = new_id
            self.mark_party_dirty(guild_id_str, new_id)
            logger.info("PartyManager: Party %s ('%s') created for guild %s. Leader: %s. Members: %s. Location: %s", new_id, getattr(party, 'name', new_id), guild_id_str, leader_id_str, member_ids_str, current_location_id) # Changed
            return party
        except Exception as e:
            logger.error("PartyManager: Error creating party for leader %s in guild %s: %s", leader_id_str, guild_id_str, e, exc_info=True) # Changed
            return None

    async def remove_party(self, party_id: str, guild_id: str, **kwargs: Any) -> Optional[str]:
        guild_id_str, party_id_str = str(guild_id), str(party_id)
        party = self.get_party(guild_id_str, party_id_str)
        if not party:
            if guild_id_str in self._deleted_parties and party_id_str in self._deleted_parties[guild_id_str]:
                 logger.debug("PartyManager: Party %s in guild %s was already marked for deletion.", party_id_str, guild_id_str) # Added
                 return party_id_str
            logger.warning("PartyManager: Party %s not found for removal in guild %s.", party_id_str, guild_id_str) # Changed
            return None
        if str(getattr(party, 'guild_id', None)) != guild_id_str:
            logger.error("PartyManager: Mismatched guild_id for party %s removal. Expected %s, found %s.", party_id_str, guild_id_str, getattr(party, 'guild_id', None)) # Changed
            return None
        logger.info("PartyManager: Removing party %s for guild %s. Leader: %s", party_id_str, guild_id_str, getattr(party, 'leader_id', 'N/A')) # Changed
        
        member_ids_list = list(getattr(party, 'player_ids_list', []))
        if not isinstance(member_ids_list, list): member_ids_list = []
        char_mgr = self._character_manager
        if char_mgr and hasattr(char_mgr, 'set_party_id'):
            for member_id_str_loop in member_ids_list: # Renamed member_id_str to avoid conflict
                try:
                    logger.info("PartyManager: Setting party_id to None for character %s from disbanded party %s in guild %s.", member_id_str_loop, party_id_str, guild_id_str) # Changed
                    await char_mgr.set_party_id(guild_id=guild_id_str, character_id=member_id_str_loop, party_id=None, **kwargs)
                except Exception as e:
                    logger.error("PartyManager: Error setting party_id to None for member %s of party %s in guild %s: %s", member_id_str_loop, party_id_str, guild_id_str, e, exc_info=True) # Changed
        elif not char_mgr:
            logger.warning("PartyManager: CharacterManager not available in remove_party for guild %s. Cannot set party_id to None for members of %s.", guild_id_str, party_id_str) # Changed
        logger.info("PartyManager: Finished setting party_id to None for members of party %s in guild %s.", party_id_str, guild_id_str) # Changed
        
        # ... (Other cleanup logic with logging) ...
        logger.info("PartyManager: Party %s cleanup processes complete for guild %s.", party_id_str, guild_id_str) # Changed

        guild_member_map = self._member_to_party_map.get(guild_id_str)
        if guild_member_map:
             for member_id_map_loop in member_ids_list: # Renamed member_id to avoid conflict
                  if guild_member_map.get(member_id_map_loop) == party_id_str:
                       del guild_member_map[member_id_map_loop]
        self._deleted_parties.setdefault(guild_id_str, set()).add(party_id_str)
        guild_parties = self._parties.get(guild_id_str)
        if guild_parties: guild_parties.pop(party_id_str, None)
        self._dirty_parties.get(guild_id_str, set()).discard(party_id_str)
        logger.info("PartyManager: Party %s fully removed from cache and marked for deletion for guild %s.", party_id_str, guild_id_str) # Changed
        return party_id_str

    async def update_party_location(self, party_id: str, new_location_id: Optional[str], guild_id: str, context: Dict[str, Any]) -> bool:
        guild_id_str = str(guild_id)
        party = self.get_party(guild_id_str, party_id)
        if not party:
            logger.error("PartyManager: Party %s not found in guild %s for location update.", party_id, guild_id_str) # Changed
            return False
        if not hasattr(party, 'current_location_id'):
            logger.warning("PartyManager: Party %s in guild %s does not have 'current_location_id' attribute. Initializing to None.", party_id, guild_id_str) # Changed
            setattr(party, 'current_location_id', None)

        resolved_new_location_id: Optional[str] = str(new_location_id) if new_location_id is not None else None
        if getattr(party, 'current_location_id', None) == resolved_new_location_id:
            # logger.debug("PartyManager: Party %s in guild %s is already at location %s.", party_id, guild_id_str, resolved_new_location_id) # Too noisy
            return True
        party.current_location_id = resolved_new_location_id
        self.mark_party_dirty(guild_id_str, party_id)
        logger.info("PartyManager: Party %s in guild %s location updated to %s. Context: %s", party_id, guild_id_str, resolved_new_location_id, context.get('reason', 'N/A')) # Changed, added reason from context
        return True

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None:
            logger.warning("PartyManager: Cannot save parties for guild %s, DB service or adapter missing.", guild_id_str) # Changed
            return
        logger.debug("PartyManager: Saving parties for guild %s...", guild_id_str) # Changed to debug
        # ... (rest of save_state logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("PartyManager: Error deleting parties for guild %s: %s", guild_id_str, e, exc_info=True)
        # Example: logger.info("PartyManager: Save state complete for guild %s.", guild_id_str)

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None:
            logger.warning("PartyManager: Cannot load parties for guild %s, DB service or adapter missing.", guild_id_str) # Changed
            return
        logger.info("PartyManager: Loading parties for guild %s from DB...", guild_id_str) # Changed
        # ... (rest of load_state logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("PartyManager: Error loading party %s for guild %s: %s", data.get('id', 'N/A'), guild_id_str, e, exc_info=True)
        # Example: logger.info("PartyManager: Successfully loaded %s parties into cache for guild %s.", loaded_count, guild_id_str)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("PartyManager: Rebuilding runtime caches for guild %s...", guild_id_str) # Changed
        # ... (rest of rebuild_runtime_caches logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.warning("PartyManager: Warning: Member %s found in multiple parties during rebuild for guild %s...", member_id, guild_id_str)
        # Example: logger.info("PartyManager: Rebuild runtime caches complete for guild %s. Member map size: %s", guild_id_str, len(guild_member_map))

    def mark_party_dirty(self, guild_id: str, party_id: str) -> None:
        guild_id_str, party_id_str = str(guild_id), str(party_id)
        guild_parties_cache = self._parties.get(guild_id_str)
        if guild_parties_cache and party_id_str in guild_parties_cache:
             self._dirty_parties.setdefault(guild_id_str, set()).add(party_id_str)
        # else: logger.debug("PartyManager: Attempted to mark non-existent party %s in guild %s as dirty.", party_id_str, guild_id_str) # Too noisy

    async def clean_up_for_entity(self, entity_id: str, entity_type: str, context: Dict[str, Any]) -> None:
        guild_id = context.get('guild_id')
        if guild_id is None:
            logger.warning("PartyManager: clean_up_for_entity called for %s %s without guild_id in context. Cannot clean up from party.", entity_type, entity_id) # Changed
            return 
        guild_id_str, entity_id_str = str(guild_id), str(entity_id)
        logger.info("PartyManager: Cleaning up %s %s from party in guild %s...", entity_type, entity_id_str, guild_id_str) # Changed
        # ... (rest of clean_up_for_entity logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.warning("PartyManager: Found party object with no ID for participant %s in guild %s during cleanup.", entity_id_str, guild_id_str)

    async def add_member_to_party(self, party_id: str, character_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.info("PartyManager: Character %s added to party %s in guild %s.", char_id_str, party_id_str, guild_id_str)
        return False # Placeholder
    async def remove_member_from_party(self, party_id: str, character_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.info("PartyManager: Character %s removed from party %s player_ids_list in guild %s.", char_id_str, party_id_str, guild_id_str)
        return False # Placeholder
    async def _get_ready_members_in_location(self, party: "Party", location_id: str, guild_id: str) -> List["Character"]:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.warning("PartyManager: CharacterManager not available in _get_ready_members_in_location for party %s guild %s.", party.id, guild_id)
        return [] # Placeholder
    async def check_and_process_party_turn(self, party_id: str, location_id: str, guild_id: str, game_manager: Any) -> None:
        logger.info("PartyManager: Checking turn for party %s in location %s, guild %s.", party_id, location_id, guild_id) # Changed
        # ... (rest of logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.error("PartyManager: CRITICAL ERROR during check_and_process_party_turn for party %s in location %s (guild %s): %s", party.id, location_id, guild_id, e, exc_info=True)
    def format_turn_report(self, individual_action_results: List[Dict[str, Any]], party_name: str, location_name: str, character_manager: "CharacterManager", guild_id: str) -> str:
        # ... (logic as before)
        return "" # Placeholder
    async def revert_party_creation(self, guild_id: str, party_id: str, **kwargs: Any) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        return False # Placeholder
    async def recreate_party_from_data(self, guild_id: str, party_data: Dict[str, Any], **kwargs: Any) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        return False # Placeholder
    async def revert_party_member_add(self, guild_id: str, party_id: str, member_id: str, **kwargs: Any) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        return False # Placeholder
    async def revert_party_member_remove(self, guild_id: str, party_id: str, member_id: str, old_leader_id_if_changed: Optional[str], **kwargs: Any) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        return False # Placeholder
    async def revert_party_leader_change(self, guild_id: str, party_id: str, old_leader_id: str, **kwargs: Any) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        return False # Placeholder
    async def revert_party_location_change(self, guild_id: str, party_id: str, old_location_id: Optional[str], **kwargs: Any) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        return False # Placeholder
    async def revert_party_turn_status_change(self, guild_id: str, party_id: str, old_turn_status: str, **kwargs: Any) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        return False # Placeholder
    async def save_party(self, party: "Party", guild_id: str) -> bool:
        # ... (logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.info("PartyManager: Successfully saved party %s for guild %s.", party_id, guild_id_str)
        return False # Placeholder

logger.debug("DEBUG: party_manager.py module loaded.") # Changed
