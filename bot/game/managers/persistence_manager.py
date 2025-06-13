# bot/game/managers/persistence_manager.py

import asyncio
import traceback # Will be removed
import logging # Added
from typing import Dict, Optional, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union, Tuple

from bot.services.db_service import DBService

if TYPE_CHECKING:
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.crafting_manager import CraftingManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.skill_manager import SkillManager
    from bot.game.managers.spell_manager import SpellManager

logger = logging.getLogger(__name__) # Added
logger.debug("DEBUG: persistence_manager.py module loaded.") # Changed

class PersistenceManager:
    def __init__(self,
                 event_manager: "EventManager",
                 character_manager: "CharacterManager",
                 location_manager: "LocationManager",
                 db_service: Optional[DBService] = None,
                 npc_manager: Optional["NpcManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 item_manager: Optional["ItemManager"] = None,
                 time_manager: Optional["TimeManager"] = None,
                 status_manager: Optional["StatusManager"] = None,
                 crafting_manager: Optional["CraftingManager"] = None,
                 economy_manager: Optional["EconomyManager"] = None,
                 party_manager: Optional["PartyManager"] = None,
                 quest_manager: Optional["QuestManager"] = None,
                 relationship_manager: Optional["RelationshipManager"] = None,
                 game_log_manager: Optional["GameLogManager"] = None,
                 dialogue_manager: Optional["DialogueManager"] = None,
                 skill_manager: Optional["SkillManager"] = None,
                 spell_manager: Optional["SpellManager"] = None,
                ):
        logger.info("Initializing PersistenceManager...") # Changed
        self._db_service: Optional[DBService] = db_service
        self._event_manager: "EventManager" = event_manager
        self._character_manager: "CharacterManager" = character_manager
        self._location_manager: "LocationManager" = location_manager
        self._npc_manager: Optional["NpcManager"] = npc_manager
        self._combat_manager: Optional["CombatManager"] = combat_manager
        self._item_manager: Optional["ItemManager"] = item_manager
        self._time_manager: Optional["TimeManager"] = time_manager
        self._status_manager: Optional["StatusManager"] = status_manager
        self._crafting_manager: Optional["CraftingManager"] = crafting_manager
        self._economy_manager: Optional["EconomyManager"] = economy_manager
        self._party_manager: Optional["PartyManager"] = party_manager
        self._quest_manager: Optional["QuestManager"] = quest_manager
        self._relationship_manager: Optional["RelationshipManager"] = relationship_manager
        self._game_log_manager: Optional["GameLogManager"] = game_log_manager
        self._dialogue_manager: Optional["DialogueManager"] = dialogue_manager
        self._skill_manager: Optional["SkillManager"] = skill_manager
        self._spell_manager: Optional["SpellManager"] = spell_manager
        logger.info("PersistenceManager initialized.") # Changed

    async def save_game_state(self, guild_ids: List[str], **kwargs: Any) -> None:
        if not guild_ids:
            logger.info("PersistenceManager: No guild IDs provided for save. Skipping state save.") # Changed
            return
        logger.info("PersistenceManager: Initiating game state save for %s guilds: %s", len(guild_ids), guild_ids) # Changed

        call_kwargs = {**kwargs}
        if self._db_service is None or self._db_service.adapter is None:
            logger.warning("PersistenceManager: Database service or adapter not provided. Managers will simulate save.") # Changed
            for guild_id in guild_ids:
                 await self._call_manager_save(guild_id, **call_kwargs)
            logger.info("PersistenceManager: Game state save simulation finished.") # Changed
        else:
            logger.info("PersistenceManager: Database adapter found, attempting to save via managers.") # Changed
            try:
                for guild_id in guild_ids:
                    logger.info("PersistenceManager: Saving state for guild %s...", guild_id) # Added
                    await self._call_manager_save(guild_id, **call_kwargs)
                logger.info("PersistenceManager: Game state save delegation finished for all specified guilds.") # Changed
            except Exception as e:
                logger.error("PersistenceManager: Error during game state save delegation via managers: %s", e, exc_info=True) # Changed
                raise

    async def _call_manager_save(self, guild_id: str, **kwargs: Any) -> None:
         call_kwargs = {'guild_id': guild_id, **kwargs}
         managers_to_save = [
             (self._event_manager, 'save_state'), (self._character_manager, 'save_state'),
             (self._location_manager, 'save_state'), (self._npc_manager, 'save_state'),
             (self._item_manager, 'save_state'), (self._combat_manager, 'save_state'),
             (self._time_manager, 'save_state'), (self._status_manager, 'save_state'),
             (self._crafting_manager, 'save_state'), (self._economy_manager, 'save_state'),
             (self._party_manager, 'save_state'), (self._quest_manager, 'save_state'),
             (self._relationship_manager, 'save_state'), (self._game_log_manager, 'save_state'),
             (self._dialogue_manager, 'save_state'), (self._skill_manager, 'save_state'),
             (self._spell_manager, 'save_state'),
         ]
         for manager_attr, method_name in managers_to_save:
              manager = manager_attr
              if manager and hasattr(manager, method_name):
                   try:
                       logger.debug("PersistenceManager: Calling %s.%s for guild %s", type(manager).__name__, method_name, guild_id) # Added
                       await getattr(manager, method_name)(**call_kwargs)
                   except Exception as e:
                       logger.error("PersistenceManager: Error saving state for guild %s in manager %s: %s", guild_id, type(manager).__name__, e, exc_info=True) # Changed
              elif manager is None: # Only log if manager was expected to be there (i.e., not an optional one that's None)
                  # This check might be too verbose if many managers are optional and often None.
                  # For core managers, it's a critical issue.
                  # For now, let's assume optional managers being None is handled by their respective init or not an error here.
                  pass


    async def load_game_state(self, guild_ids: List[str], **kwargs: Any) -> None:
        if not guild_ids:
            logger.info("PersistenceManager: No guild IDs provided for load. Skipping state load.") # Changed
            return
        logger.info("PersistenceManager: Initiating game state load for %s guilds: %s", len(guild_ids), guild_ids) # Changed

        call_kwargs = {**kwargs}
        if self._db_service is None or self._db_service.adapter is None:
            logger.warning("PersistenceManager: Database service or adapter not provided. Loading placeholder state (simulated loading).") # Changed
            for guild_id in guild_ids:
                 await self._call_manager_load(guild_id, **call_kwargs)
                 await self._call_manager_rebuild_caches(guild_id, **call_kwargs)
            logger.info("PersistenceManager: Game state load simulation finished.") # Changed
        else:
            logger.info("PersistenceManager: Database adapter found, attempting to load via managers.") # Changed
            try:
                 for guild_id in guild_ids:
                     logger.info("PersistenceManager: Loading state for guild %s via managers...", guild_id) # Changed
                     await self._call_manager_load(guild_id, **call_kwargs)
                     logger.info("PersistenceManager: Load delegation finished for guild %s.", guild_id) # Changed
                 logger.info("PersistenceManager: Rebuilding runtime caches for loaded guilds...") # Changed
                 for guild_id in guild_ids:
                      logger.info("PersistenceManager: Rebuilding caches for guild %s via managers...", guild_id) # Changed
                      await self._call_manager_rebuild_caches(guild_id, **call_kwargs)
                      logger.info("PersistenceManager: Rebuild delegation finished for guild %s.", guild_id) # Changed
                 logger.info("PersistenceManager: Game state loaded successfully (via managers).") # Changed
            except Exception as e:
                 logger.critical("PersistenceManager: CRITICAL ERROR during game state load via managers: %s", e, exc_info=True) # Changed
                 raise

    async def _call_manager_load(self, guild_id: str, **kwargs: Any) -> None:
         call_kwargs = {'guild_id': guild_id, **kwargs}
         managers_to_load = [
             (self._event_manager, 'load_state'), (self._character_manager, 'load_state'),
             (self._location_manager, 'load_state'), (self._npc_manager, 'load_state'),
             (self._item_manager, 'load_state'), (self._combat_manager, 'load_state'),
             (self._time_manager, 'load_state'), (self._status_manager, 'load_state'),
             (self._crafting_manager, 'load_state'), (self._economy_manager, 'load_state'),
             (self._party_manager, 'load_state'), (self._quest_manager, 'load_state'),
             (self._relationship_manager, 'load_state'), (self._game_log_manager, 'load_state'),
             (self._dialogue_manager, 'load_state'), (self._skill_manager, 'load_state'),
             (self._spell_manager, 'load_state'),
         ]
         for manager_attr, method_name in managers_to_load:
              manager = manager_attr
              if manager and hasattr(manager, method_name):
                   try:
                       logger.debug("PersistenceManager: Calling %s.%s for guild %s", type(manager).__name__, method_name, guild_id) # Added
                       await getattr(manager, method_name)(**call_kwargs)
                   except Exception as e:
                       logger.error("PersistenceManager: Error loading state for guild %s in manager %s: %s", guild_id, type(manager).__name__, e, exc_info=True) # Changed
              # else: logger.debug for optional managers if needed

    async def _call_manager_rebuild_caches(self, guild_id: str, **kwargs: Any) -> None:
         call_kwargs = {'guild_id': guild_id, **kwargs}
         managers_to_rebuild = [
             (self._event_manager, 'rebuild_runtime_caches'), (self._character_manager, 'rebuild_runtime_caches'),
             (self._location_manager, 'rebuild_runtime_caches'), (self._npc_manager, 'rebuild_runtime_caches'),
             (self._item_manager, 'rebuild_runtime_caches'), (self._combat_manager, 'rebuild_runtime_caches'),
             (self._time_manager, 'rebuild_runtime_caches'), (self._status_manager, 'rebuild_runtime_caches'),
             (self._crafting_manager, 'rebuild_runtime_caches'), (self._economy_manager, 'rebuild_runtime_caches'),
             (self._party_manager, 'rebuild_runtime_caches'), (self._quest_manager, 'rebuild_runtime_caches'),
             (self._relationship_manager, 'rebuild_runtime_caches'), (self._game_log_manager, 'rebuild_runtime_caches'),
             (self._dialogue_manager, 'rebuild_runtime_caches'), (self._skill_manager, 'rebuild_runtime_caches'),
             (self._spell_manager, 'rebuild_runtime_caches'),
         ]
         for manager_attr, method_name in managers_to_rebuild:
              manager = manager_attr
              if manager and hasattr(manager, method_name):
                   try:
                       logger.debug("PersistenceManager: Calling %s.%s for guild %s", type(manager).__name__, method_name, guild_id) # Added
                       await getattr(manager, method_name)(**call_kwargs)
                   except Exception as e:
                       logger.error("PersistenceManager: Error rebuilding caches for guild %s in manager %s: %s", guild_id, type(manager).__name__, e, exc_info=True) # Changed
              # else: logger.debug for optional managers if needed

logger.debug("DEBUG: persistence_manager.py module loaded.") # Changed
