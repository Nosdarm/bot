# bot/game/managers/npc_manager.py

from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union

# Use NPC from database.models if that's what calculate_effective_stats expects
from bot.database.models import NPC # Changed from bot.game.models.npc
from bot.game.utils import stats_calculator # Added
import json # Already present, ensure it is used if needed by new methods

from builtins import dict, set, list, int, float, str, bool


if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.game_manager import GameManager # Added for type hint
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.services.campaign_loader import CampaignLoader
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.services.openai_service import OpenAIService
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.services.notification_service import NotificationService

logger = logging.getLogger(__name__) # Added
logger.debug("DEBUG: npc_manager.py module loaded.") # Changed

class NpcManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _npcs: Dict[str, Dict[str, "NPC"]]
    _entities_with_active_action: Dict[str, Set[str]]
    _dirty_npcs: Dict[str, Set[str]]
    _deleted_npc_ids: Dict[str, Set[str]]
    _npc_archetypes: Dict[str, Dict[str, Any]]
    _game_manager: Optional['GameManager'] # Added

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        combat_manager: Optional["CombatManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None,
        openai_service: Optional["OpenAIService"] = None,
        ai_validator: Optional["AIResponseValidator"] = None,
        campaign_loader: Optional["CampaignLoader"] = None,
        notification_service: Optional["NotificationService"] = None,
        game_manager: Optional['GameManager'] = None # Added
    ):
        logger.info("Initializing NpcManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._game_manager = game_manager # Added
        self._campaign_loader = campaign_loader
        self._npc_archetypes = {}
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager
        self._location_manager = location_manager
        self._game_log_manager = game_log_manager
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service
        self._ai_validator = ai_validator
        self._notification_service = notification_service
        self._npcs = {}
        self._entities_with_active_action = {}
        self._dirty_npcs = {}
        self._deleted_npc_ids = {}
        self._load_npc_archetypes()
        logger.info("NpcManager initialized.") # Changed

    async def create_npc_from_ai_concept(
        self,
        guild_id: str,
        npc_concept: Dict[str, Any],
        lang: str,
        location_id: Optional[str] = None, # Optional initial location
        context: Optional[Dict[str, Any]] = None # For additional info like role
    ) -> Optional[NPC]:
        """
        Creates an NPC based on an AI-generated concept.

        Args:
            guild_id: The ID of the guild.
            npc_concept: A dictionary containing AI-generated NPC details.
                         Expected keys: 'name_i18n' (dict), 'description_i18n' (dict),
                                        'persona_i18n' (dict), 'role' (str, optional),
                                        'stats_suggestion' (dict, optional),
                                        'inventory_suggestion' (list of item_ids/concepts, optional),
                                        'faction_id_suggestion' (str, optional from context).
            lang: The primary language of the provided concept.
            location_id: Optional ID of the location to spawn the NPC.
            context: Optional dictionary for additional context e.g. {'role': 'faction_leader'}.

        Returns:
            The created NPC object, or None if creation failed.
        """
        guild_id_str = str(guild_id)
        # _ensure_guild_cache_exists is not defined in the provided NpcManager snippet,
        # but it's good practice. If it's missing, create_npc should handle cache internally.
        # For now, assuming create_npc or subsequent get_npc will handle cache.

        name_i18n = npc_concept.get("name_i18n")
        description_i18n = npc_concept.get("description_i18n", {})
        persona_i18n = npc_concept.get("persona_i18n", {})

        role = npc_concept.get("role", context.get("role") if context else None)

        stats = npc_concept.get("stats_suggestion", {})
        inventory = npc_concept.get("inventory_suggestion", [])

        faction_id = npc_concept.get("faction_id_suggestion", context.get("faction_id") if context else None)

        if not name_i18n or not isinstance(name_i18n, dict) or not name_i18n.get(lang):
            logger.error(f"NpcManager: AI NPC concept for guild {guild_id_str} is missing 'name_i18n' or name for lang '{lang}'. Concept: {str(npc_concept)[:200]}")
            return None

        for i18n_field_dict in [name_i18n, description_i18n, persona_i18n]:
            if isinstance(i18n_field_dict, dict) and lang != 'en' and 'en' not in i18n_field_dict and i18n_field_dict.get(lang):
                i18n_field_dict['en'] = i18n_field_dict[lang]

        npc_template_id = npc_concept.get("npc_template_id", "generic_humanoid_ai")

        creation_kwargs = {
            "name_i18n_override": name_i18n,
            "description_i18n_override": description_i18n,
            "persona_i18n_override": persona_i18n,
            "base_stats_override": stats if stats else None,
            "initial_inventory_override": inventory if inventory else None,
            "faction_id_override": faction_id if faction_id else None,
            "role_override": role if role else None,
            "state_variables_override": npc_concept.get("state_variables", None)
        }
        creation_kwargs = {k: v for k, v in creation_kwargs.items() if v is not None}

        try:
            # Assuming create_npc handles these overrides and can bypass further AI generation/moderation
            # if these direct values are provided.
            npc_id_or_moderation_data = await self.create_npc(
                guild_id=guild_id_str,
                npc_template_id=npc_template_id,
                location_id=location_id,
                **creation_kwargs
            )

            if isinstance(npc_id_or_moderation_data, str):
                created_npc_id = npc_id_or_moderation_data
                # self._ensure_guild_cache_exists(guild_id_str) # Ensure cache before get
                new_npc = self.get_npc(guild_id_str, created_npc_id) # get_npc should load from DB if not in cache
                if new_npc:
                    logger.info(f"NpcManager: Successfully created NPC '{new_npc.name}' (ID: {new_npc.id}) from AI concept in guild {guild_id_str}.")
                    return new_npc
                else: # This case implies create_npc returned an ID but get_npc failed right after.
                    logger.error(f"NpcManager: NPC ID {created_npc_id} returned by create_npc, but get_npc failed for guild {guild_id_str}. This might indicate an issue with immediate data persistence or caching if create_npc doesn't populate cache directly.")
                    # As a fallback, try to construct a temporary NPC object if all data is available,
                    # though this is not ideal as it bypasses the standard loading path.
                    # For now, returning None is safer.
                    return None
            elif isinstance(npc_id_or_moderation_data, dict):
                logger.warning(f"NpcManager: NPC creation from AI concept for guild {guild_id_str} resulted in moderation request. Direct creation failed. Concept: {str(npc_concept)[:200]}")
                return None
            else: # create_npc returned None or unexpected type
                logger.error(f"NpcManager: Failed to create NPC from AI concept for guild {guild_id_str}. create_npc returned: {npc_id_or_moderation_data}. Concept: {str(npc_concept)[:200]}")
                return None

        except Exception as e:
            logger.error(f"NpcManager: Unexpected error creating NPC from AI concept in guild {guild_id_str}: {e}. Concept: {str(npc_concept)[:200]}", exc_info=True)
            return None

    async def _recalculate_and_store_effective_stats_for_npc(self, guild_id: str, npc_id: str, npc_model: Optional[NPC] = None) -> None:
        if not self._game_manager:
            logger.error(f"NpcManager: GameManager not available for effective stats recalc for NPC {npc_id}.")
            return

        npc_to_use = npc_model
        if not npc_to_use:
            # Assuming self.get_npc returns the model instance directly from cache or DB
            # If it's a method that fetches from DB and is async, it should be awaited.
            # For now, assuming get_npc is synchronous and returns from cache.
            # If get_npc needs to be async, this method needs to be refactored or get_npc called before.
            npc_instance_from_cache = self.get_npc(guild_id, npc_id)
            if not npc_instance_from_cache : # Check if it's a valid NPC model instance
                logger.error(f"NpcManager: NPC {npc_id} not found in guild {guild_id} for effective stats recalc.")
                return
            npc_to_use = npc_instance_from_cache # Assign if valid

        if not npc_to_use: # Double check after potential fetch
            logger.error(f"NpcManager: NPC {npc_id} could not be obtained for effective stats recalc in guild {guild_id}.")
            return

        if not hasattr(npc_to_use, 'effective_stats_json'):
            logger.warning(f"NpcManager: NPC model for {npc_id} (type: {type(npc_to_use)}) does not have 'effective_stats_json' attribute.")
            # Depending on strictness, you might want to return or proceed cautiously.
            # If the attribute is expected to always exist on a valid model, this is an issue.
            # For now, let's assume it's a dynamic attribute that might be added.
            # setattr(npc_to_use, 'effective_stats_json', json.dumps({})) # Initialize if missing

        try:
            effective_stats_dict = await stats_calculator.calculate_effective_stats(
                entity=npc_to_use,
                guild_id=guild_id,
                game_manager=self._game_manager
            )
            setattr(npc_to_use, 'effective_stats_json', json.dumps(effective_stats_dict or {}))
            # self.mark_npc_dirty(guild_id, npc_id) # If NpcManager has a dirty marking mechanism
            logger.debug(f"NpcManager: Recalculated effective_stats for NPC {npc_id} in guild {guild_id}.")
        except Exception as e:
            logger.error(f"NpcManager: ERROR recalculating effective_stats for NPC {npc_id} in guild {guild_id}: {e}", exc_info=True)
            if hasattr(npc_to_use, 'effective_stats_json'): # Check again before setting error state
                setattr(npc_to_use, 'effective_stats_json', json.dumps({"error": "calculation_failed"}))

    async def trigger_npc_stats_recalculation(self, guild_id: str, npc_id: str) -> None:
        # Assuming self.get_npc is synchronous and returns from cache.
        # If get_npc needs to be async, this method should be async and await get_npc.
        npc = self.get_npc(guild_id, npc_id) # This might return a dict or a model instance

        # We need the model instance for _recalculate_and_store_effective_stats_for_npc
        # If get_npc returns a dict, we might need another method to get the model instance
        # or ensure get_npc always returns the model instance.
        # For now, assuming get_npc returns the actual NPC model object (or None).

        if npc and isinstance(npc, NPC): # Ensure it's the model instance
            await self._recalculate_and_store_effective_stats_for_npc(guild_id, npc_id, npc)
            self.mark_npc_dirty(guild_id, npc_id) # Mark dirty after successful recalc
            logger.info(f"NpcManager: Stats recalculation triggered and completed for NPC {npc_id} in guild {guild_id}.")
        elif npc: # It's not None, but not an NPC model instance
             logger.warning(f"NpcManager: trigger_npc_stats_recalculation - NPC {npc_id} found but is not a model instance (type: {type(npc)}). Cannot recalc.")
        else:
            logger.warning(f"NpcManager: trigger_npc_stats_recalculation - NPC {npc_id} not found in guild {guild_id}.")

    def _load_npc_archetypes(self):
        logger.info("NpcManager: Loading NPC archetypes...")
        self._npc_archetypes = {}  # Initialize as an empty dictionary

        # Get archetypes pre-loaded by GameManager from the campaign file
        campaign_archetypes = {}
        if self._settings and isinstance(self._settings.get('loaded_npc_archetypes_from_campaign'), dict):
            campaign_archetypes = self._settings['loaded_npc_archetypes_from_campaign']
            logger.info("NpcManager: Received %s NPC archetypes pre-loaded from campaign data via settings.", len(campaign_archetypes))
        elif self._settings and self._settings.get('loaded_npc_archetypes_from_campaign') is not None:
             logger.warning("NpcManager: 'loaded_npc_archetypes_from_campaign' in settings was not a dict, type: %s.", type(self._settings.get('loaded_npc_archetypes_from_campaign')).__name__)


        # Get archetypes defined directly in NpcManager's own settings (e.g., global fallbacks or overrides)
        # These would typically be under a key like 'npc_archetypes' directly in the 'npc_settings' block.
        direct_settings_archetypes = {}
        if self._settings and isinstance(self._settings.get('npc_archetypes'), dict):
            direct_settings_archetypes = self._settings['npc_archetypes']
            logger.info("NpcManager: Found %s NPC archetypes in direct NpcManager settings.", len(direct_settings_archetypes))
        elif self._settings and self._settings.get('npc_archetypes') is not None:
             logger.warning("NpcManager: 'npc_archetypes' in direct NpcManager settings was not a dict, type: %s.", type(self._settings.get('npc_archetypes')).__name__)

        # Merge dictionaries. Direct settings can overwrite campaign archetypes if keys conflict.
        self._npc_archetypes.update(campaign_archetypes)
        self._npc_archetypes.update(direct_settings_archetypes) # Direct settings take precedence

        if not self._npc_archetypes:
             logger.warning("NpcManager: No NPC archetypes found after attempting to load from pre-loaded campaign data and direct settings.")
        else:
             logger.info("NpcManager: NPC archetypes successfully loaded/merged, resulting in %s final archetypes.", len(self._npc_archetypes))

        # Ensure archetypes have basic structure (existing loop for validation)
        for arch_id, arch_data in self._npc_archetypes.items():
            if not isinstance(arch_data, dict):
                logger.warning("NpcManager: Archetype %s data is not a dict after loading and merging. Skipping. Data: %s", arch_id, arch_data)
                continue
            arch_data.setdefault('name', f"Archetype {arch_id}") # Fallback name using arch_id
            # Ensure name_i18n exists for display_name logic elsewhere
            if not isinstance(arch_data.get('name_i18n'), dict) or not arch_data.get('name_i18n'):
                arch_data['name_i18n'] = {'en': arch_data['name']} # Create from plain name or fallback
            arch_data.setdefault('stats', {"max_health": 50.0})
            for i18n_key in ['description_i18n', 'backstory_i18n', 'persona_i18n']:
                current_value = arch_data.get(i18n_key)
                if not isinstance(current_value, dict):
                    if current_value is not None:
                        logger.warning("NpcManager: Archetype %s had a non-dict value for %s ('%s'). Initializing to empty dict.", arch_id, i18n_key, current_value)
                    arch_data[i18n_key] = {}


    def get_npc(self, guild_id: str, npc_id: str) -> Optional["NPC"]:
        # ... (logic as before)
        return None # Placeholder
    def get_all_npcs(self, guild_id: str) -> List["NPC"]:
        # ... (logic as before)
        return [] # Placeholder
    def get_npcs_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List["NPC"]:
        # ... (logic as before)
        return [] # Placeholder
    def get_entities_with_active_action(self, guild_id: str) -> Set[str]:
        # ... (logic as before)
        return set() # Placeholder
    def is_busy(self, guild_id: str, npc_id: str) -> bool:
        # ... (logic as before)
        return False # Placeholder

    async def create_npc(
        self, guild_id: str, npc_template_id: str,
        location_id: Optional[str] = None, **kwargs: Any,
    ) -> Optional[Union[str, Dict[str, str]]]:
        guild_id_str = str(guild_id)
        log_prefix = f"NpcManager.create_npc(guild='{guild_id_str}', template='{npc_template_id}'):" # Added
        # ... (AI path logic leading to return for moderation) ...
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("%s DBService is None.", log_prefix) # Added
            return None
        
        # ... (rest of create_npc logic, use log_prefix and logger for messages) ...
        # Example: logger.error("%s Error creating NPC (non-AI path): %s", log_prefix, e, exc_info=True)
        return None # Placeholder

    async def remove_npc(self, guild_id: str, npc_id: str, **kwargs: Any) -> Optional[str]:
        logger.info("NpcManager: Removing NPC %s from guild %s.", npc_id, guild_id) # Added
        # ... (original logic, ensure guild_id in logs) ...
        return None
    async def add_item_to_inventory(self, guild_id: str, npc_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
        logger.debug("NpcManager: Adding %s of item %s to NPC %s inventory in guild %s.", quantity, item_id, npc_id, guild_id) # Added
        # ... (original logic) ...
        return False
    async def remove_item_from_inventory(self, guild_id: str, npc_id: str, item_id: str, **kwargs: Any) -> bool:
        logger.debug("NpcManager: Removing item %s from NPC %s inventory in guild %s.", item_id, npc_id, guild_id) # Added
        # ... (original logic) ...
        return False
    async def add_status_effect(self, guild_id: str, npc_id: str, status_type: str, duration: Optional[float], source_id: Optional[str] = None, **kwargs: Any) -> Optional[str]:
        logger.info("NpcManager: Adding status %s (duration: %s) to NPC %s in guild %s from source %s.", status_type, duration, npc_id, guild_id, source_id) # Added
        # ... (original logic) ...
        return None
    async def remove_status_effect(self, guild_id: str, npc_id: str, status_effect_id: str, **kwargs: Any) -> Optional[str]:
        logger.info("NpcManager: Removing status %s from NPC %s in guild %s.", status_effect_id, npc_id, guild_id) # Added
        # ... (original logic) ...
        return None
    async def update_npc_stats(self, guild_id: str, npc_id: str, stats_update: Dict[str, Any], **kwargs: Any) -> bool:
        logger.info("NpcManager: Updating stats for NPC %s in guild %s. Update: %s", npc_id, guild_id, stats_update) # Added
        # ... (original logic, add logging for specific changes if needed) ...
        return False
    async def generate_npc_details_from_ai(self, guild_id: str, npc_id_concept: str, player_level_for_scaling: Optional[int] = None) -> Optional[Dict[str, Any]]:
        logger.info("NpcManager: Generating AI NPC details for concept '%s' in guild %s.", npc_id_concept, guild_id) # Added
        # ... (original logic) ...
        return None
    async def save_npc(self, npc: "NPC", guild_id: str) -> bool:
        # ... (original logic, ensure guild_id in logs for errors) ...
        # Example: logger.error("Error saving NPC %s to DB for guild %s: %s", npc_id, guild_id_str, e, exc_info=True)
        # Example: logger.debug("NpcManager: NPC %s saved for guild %s.", npc_id, guild_id_str)
        return False # Placeholder
    async def create_npc_from_moderated_data(self, guild_id: str, npc_data: Dict[str, Any], context: Dict[str, Any]) -> Optional[str]:
        logger.info("NpcManager: Creating NPC from moderated data for guild %s. Data: %s", guild_id, npc_data) # Added
        # ... (original logic, ensure guild_id in logs for errors) ...
        return None
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.debug("NpcManager: Saving state for guild %s.", guild_id) # Added
        # ... (original logic, relies on save_npc, ensure guild_id in logs for errors) ...
        pass
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("NpcManager: Loading state for guild %s.", guild_id) # Added
        # ... (original logic, ensure guild_id in logs for errors/warnings) ...
        pass
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("NpcManager: Rebuilding runtime caches for guild %s.", guild_id) # Added
        self._load_npc_archetypes() # Ensure archetypes are reloaded if they can change
        pass
    def mark_npc_dirty(self, guild_id: str, npc_id: str) -> None:
         if str(guild_id) in self._npcs and npc_id in self._npcs[str(guild_id)]:
              self._dirty_npcs.setdefault(str(guild_id), set()).add(npc_id)
              # logger.debug("NpcManager: Marked NPC %s in guild %s as dirty.", npc_id, guild_id) # Too noisy
    def set_active_action(self, guild_id: str, npc_id: str, action_details: Optional[Dict[str, Any]]) -> None: pass
    def add_action_to_queue(self, guild_id: str, npc_id: str, action_details: Dict[str, Any]) -> None: pass
    def get_next_action_from_queue(self, guild_id: str, npc_id: str) -> Optional[Dict[str, Any]]: return None
    async def revert_npc_spawn(self, guild_id: str, npc_id: str, **kwargs: Any) -> bool: return True
    async def recreate_npc_from_data(self, guild_id: str, npc_data: Dict[str, Any], **kwargs: Any) -> bool: return True
    async def revert_npc_location_change(self, guild_id: str, npc_id: str, old_location_id: Optional[str], **kwargs: Any) -> bool: return True
    async def revert_npc_hp_change(self, guild_id: str, npc_id: str, old_hp: float, old_is_alive: bool, **kwargs: Any) -> bool: return True
    async def revert_npc_stat_changes(self, guild_id: str, npc_id: str, stat_changes: List[Dict[str, Any]], **kwargs: Any) -> bool: return True
    async def revert_npc_inventory_changes(self, guild_id: str, npc_id: str, inventory_changes: List[Dict[str, Any]], **kwargs: Any) -> bool: return True
    async def revert_npc_party_change(self, guild_id: str, npc_id: str, old_party_id: Optional[str], **kwargs: Any) -> bool: return True
    async def revert_npc_state_variables_change(self, guild_id: str, npc_id: str, old_state_variables_json: str, **kwargs: Any) -> bool: return True

    async def generate_and_save_npcs(
        self,
        guild_id: str,
        context_details: Dict[str, Any]
    ) -> List[DBGeneratedNpc]:
        """
        Generates new NPCs using AI based on context_details,
        validates the response, and saves valid NPCs to the database.

        Args:
            guild_id: The ID of the guild for which to generate NPCs.
            context_details: A dictionary containing contextual details to guide NPC generation
                             (e.g., location_id, faction_id, role_suggestion,
                              theme_keywords, num_npcs_to_generate).

        Returns:
            A list of successfully created and saved DBGeneratedNpc objects,
            or an empty list if any part of the process fails.
        """
        log_prefix = f"NpcGeneration (Guild: {guild_id})"
        num_to_generate = context_details.get("num_npcs_to_generate", 1)
        logger.info(f"{log_prefix}: Starting NPC generation. Context: {context_details}, Num: {num_to_generate}.")

        if not hasattr(self, 'game_manager') or not self.game_manager:
            logger.error(f"{log_prefix}: GameManager not available on NpcManager instance.")
            return []

        # 1. Access Services via self.game_manager
        services_to_check = {
            "multilingual_prompt_generator": self.game_manager.multilingual_prompt_generator,
            "openai_service": self.game_manager.openai_service,
            "ai_response_validator": self.game_manager.ai_response_validator,
            "db_service": self._db_service # NpcManager has its own self._db_service
        }
        for service_name, service_instance in services_to_check.items():
            if not service_instance:
                logger.error(f"{log_prefix}: Service '{service_name}' is missing.")
                return []

        prompt_generator = self.game_manager.multilingual_prompt_generator
        openai_service = self.game_manager.openai_service
        validator = self.game_manager.ai_response_validator
        db_service = self._db_service

        created_npcs_db: List[DBGeneratedNpc] = []
        target_location_id = context_details.get("location_id")
        target_location_instance: Optional[DBLocation] = None

        async with db_service.get_session() as session: # type: ignore
            try:
                # Fetch target location if specified, to update its npc_ids list
                if target_location_id:
                    target_location_instance = await get_entity_by_id(session, DBLocation, target_location_id)
                    if not target_location_instance:
                        logger.warning(f"{log_prefix}: Target location_id '{target_location_id}' provided but location not found. NPCs will be created without being added to this location's list.")
                    elif target_location_instance.guild_id != guild_id:
                        logger.warning(f"{log_prefix}: Target location_id '{target_location_id}' (guild {target_location_instance.guild_id}) does not match current guild {guild_id}. NPCs will not be added to this location's list.")
                        target_location_instance = None # Invalidate if guild mismatch

                # 2. Prepare Prompt
                logger.debug(f"{log_prefix}: Preparing NPC generation prompt.")
                prompt = await prompt_generator.prepare_npc_generation_prompt(
                    guild_id, session, self.game_manager, context_details
                )
                if not prompt or prompt.startswith("Error:"):
                    logger.error(f"{log_prefix}: Failed to generate NPC prompt. Details: {prompt}")
                    return []
                logger.debug(f"{log_prefix}: NPC Prompt generated (first 300 chars): {prompt[:300]}...")

                # 3. Call OpenAI Service
                logger.debug(f"{log_prefix}: Requesting completion from OpenAI for NPCs.")
                raw_ai_output = await openai_service.get_completion(prompt_text=prompt)
                if not raw_ai_output:
                    logger.error(f"{log_prefix}: AI service returned no output for NPC generation.")
                    return []
                logger.debug(f"{log_prefix}: Raw AI output for NPCs received (first 100 chars): {raw_ai_output[:100]}")

                # 4. Validate AI Response
                logger.debug(f"{log_prefix}: Validating AI response for NPCs.")
                validated_npc_data_list = await validator.parse_and_validate_npc_generation_response(
                    raw_ai_output, guild_id, self.game_manager
                )
                if not validated_npc_data_list:
                    logger.error(f"{log_prefix}: AI NPC response validation failed or returned no valid NPCs. Raw output: {raw_ai_output}")
                    return []
                logger.info(f"{log_prefix}: AI NPC response validated. Found {len(validated_npc_data_list)} valid NPCs.")

                # 5. Create and Save GeneratedNpc Entities
                for npc_data in validated_npc_data_list:
                    npc_id = str(uuid.uuid4())
                    npc_model_data = {
                        "id": npc_id,
                        "guild_id": guild_id,
                        "name_i18n": npc_data.get("name_i18n"),
                        "description_i18n": npc_data.get("description_i18n"),
                        "backstory_i18n": npc_data.get("backstory_i18n"),
                        "persona_i18n": npc_data.get("persona_i18n"),
                        # The DB model GeneratedNpc does not have a direct 'archetype' field.
                        # This info would typically go into a JSONB 'details' or 'state_variables' field,
                        # or a dedicated 'archetype' column if added to the model.
                        # For now, storing it in a conceptual 'details' field within effective_stats_json or similar if it existed.
                        # Since GeneratedNpc has no such generic JSONB field in the provided model, we can store it
                        # as part of persona_i18n or log it, or it needs a model update.
                        # Let's assume for now it's a top-level attribute in the AI response but not directly mapped to GeneratedNpc.
                        # We can add it to a new 'details' field if we assume it's JSONB.
                        # For this pass, we'll include it if GeneratedNpc schema is updated, or omit.
                        # Current GeneratedNpc model: id, name_i18n, description_i18n, backstory_i18n, persona_i18n, effective_stats_json, guild_id
                        # We can put archetype and other non-i18n fields into effective_stats_json if it's a general JSONB store.
                        # Or, the AI prompt should be adjusted to put 'archetype' inside 'persona_i18n' or similar.
                        # For now, let's include it in a new 'details' field for the model instance, assuming model can take it.
                        # This will likely fail if 'details' is not on DBGeneratedNpc model.
                        # "details": {"archetype": npc_data.get("archetype")}, # Example
                        # initial_dialogue_greeting_i18n can be part of persona or a new field
                        # faction_id is also not directly on GeneratedNpc DB model.
                    }
                    # Add archetype to a conceptual details field if it exists
                    details_for_npc = {}
                    if npc_data.get("archetype"):
                        details_for_npc["archetype"] = npc_data.get("archetype")
                    if npc_data.get("initial_dialogue_greeting_i18n"):
                         details_for_npc["initial_dialogue_greeting_i18n"] = npc_data.get("initial_dialogue_greeting_i18n")
                    if npc_data.get("faction_affiliation_id"): # This is a suggested name/concept
                         details_for_npc["faction_affiliation_suggestion"] = npc_data.get("faction_affiliation_id")

                    if details_for_npc: # If there are any details to add
                        # Assuming GeneratedNpc has an 'effective_stats_json' that can store this, or a 'details' field.
                        # For now, let's try to merge into persona_i18n for simplicity if no generic JSONB field.
                        # This is not ideal. A 'details' JSONB field on GeneratedNpc would be better.
                        # Given the current GeneratedNpc model, these extra fields cannot be directly saved.
                        # We will save what the model supports.
                        logger.info(f"{log_prefix}: NPC data from AI contains extra fields not directly on GeneratedNpc model: archetype, initial_dialogue, faction_affiliation_id. These will be logged but not directly saved unless model is updated or they are part of a JSONB field.")
                        logger.debug(f"{log_prefix}: Extra AI fields for NPC {npc_id}: {details_for_npc}")


                    # Filter for actual model fields, excluding Nones for nullable fields if desired
                    final_npc_model_data = {
                        k: v for k, v in npc_model_data.items() if v is not None
                    }
                    if not final_npc_model_data.get("name_i18n"): # Name is required
                        logger.warning(f"{log_prefix}: Skipping NPC due to missing 'name_i18n'. Data: {npc_data}")
                        continue

                    new_npc = DBGeneratedNpc(**final_npc_model_data)
                    session.add(new_npc)
                    created_npcs_db.append(new_npc)
                    logger.debug(f"{log_prefix}: Prepared and added new GeneratedNpc {new_npc.id} to session.")

                    if target_location_instance:
                        if target_location_instance.npc_ids is None:
                            target_location_instance.npc_ids = []
                        # Ensure npc_ids is a list, handle if it's somehow a string from DB (should be JSONB list)
                        if not isinstance(target_location_instance.npc_ids, list):
                            try:
                                # Attempt to parse if it's a JSON string representing a list
                                current_npc_ids = json.loads(str(target_location_instance.npc_ids)) if isinstance(target_location_instance.npc_ids, str) else []
                                if not isinstance(current_npc_ids, list): current_npc_ids = []
                                target_location_instance.npc_ids = current_npc_ids
                            except json.JSONDecodeError:
                                target_location_instance.npc_ids = [] # Reset if invalid JSON string

                        if npc_id not in target_location_instance.npc_ids:
                            target_location_instance.npc_ids.append(npc_id)
                            flag_modified(target_location_instance, "npc_ids") # Mark JSONB as modified
                            session.add(target_location_instance) # Add location to session to save updated npc_ids
                            logger.info(f"{log_prefix}: NPC {npc_id} added to location {target_location_id}'s npc_ids list.")


                if created_npcs_db:
                    await session.commit()
                    logger.info(f"{log_prefix}: Successfully generated and saved {len(created_npcs_db)} NPCs to DB.")
                    for npc in created_npcs_db:
                        await session.refresh(npc)
                else:
                    logger.info(f"{log_prefix}: No valid NPCs were processed to be saved.")

                return created_npcs_db

            except Exception as e:
                logger.error(f"{log_prefix}: Error during NPC generation and saving pipeline: {e}", exc_info=True)
                if 'session' in locals() and session.is_active: # Check if session was defined and is active
                    await session.rollback() # type: ignore
                return []

logger.debug("DEBUG: npc_manager.py module loaded.") # Changed
