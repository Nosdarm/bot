# bot/game/managers/ability_manager.py
from __future__ import annotations
import time # For cooldowns
from typing import Optional, Dict, Any, List, TYPE_CHECKING
import logging # Added

from ..models.ability import Ability # Import the Ability model

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.status_manager import StatusManager

logger = logging.getLogger(__name__) # Added

class AbilityManager:
    """
    Manages character abilities, including loading templates, learning, activation,
    and interaction with the RuleEngine for effects.
    """
    required_args_for_load = ["guild_id", "campaign_data"]
    required_args_for_save = ["guild_id"] 
    required_args_for_rebuild = ["guild_id", "campaign_data"]

    def __init__(self,
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional[CharacterManager] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 status_manager: Optional[StatusManager] = None,
                 **kwargs: Any):
        self._settings = settings if settings is not None else {}
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        
        self._ability_templates: Dict[str, Dict[str, Ability]] = {}
        logger.info("AbilityManager initialized.") # Changed

    async def load_ability_templates(self, guild_id: str, campaign_data: Dict[str, Any]) -> None:
        """Loads ability templates from campaign data for a specific guild."""
        guild_id_str = str(guild_id)
        self._ability_templates.setdefault(guild_id_str, {})
        
        ability_templates_data = campaign_data.get("ability_templates", [])
        if not ability_templates_data:
            logger.info("AbilityManager: No ability templates found in campaign_data for guild %s.", guild_id_str) # Changed
            return

        loaded_count = 0
        for ability_data in ability_templates_data:
            try:
                ability = Ability.from_dict(ability_data)
                self._ability_templates[guild_id_str][ability.id] = ability
                loaded_count += 1
            except Exception as e:
                logger.error("AbilityManager: Error loading ability template '%s' for guild %s: %s", ability_data.get('id', 'UnknownID'), guild_id_str, e, exc_info=True) # Changed
        
        logger.info("AbilityManager: Successfully loaded %s ability templates for guild %s.", loaded_count, guild_id_str) # Changed
        if loaded_count > 0 and logger.isEnabledFor(logging.DEBUG): # Changed to DEBUG for verbose output
            logger.debug("AbilityManager: Example ability templates for guild %s:", guild_id_str) # Changed
            count = 0
            for ability_id, ability_obj in self._ability_templates[guild_id_str].items():
                if count < 3:
                    ability_display_name = getattr(ability_obj, 'name', ability_obj.id)
                    logger.debug("  - ID: %s, Name: %s, Type: %s", ability_obj.id, ability_display_name, ability_obj.type) # Changed
                    count += 1
                else:
                    break
            if loaded_count > 3:
                logger.debug("  ... and %s more.", loaded_count - 3) # Changed

    async def get_ability(self, guild_id: str, ability_id: str) -> Optional[Ability]:
        """Retrieves a specific ability object from the cache for a guild."""
        guild_id_str = str(guild_id)
        ability_id_str = str(ability_id)
        return self._ability_templates.get(guild_id_str, {}).get(ability_id_str)

    async def learn_ability(self, guild_id: str, character_id: str, ability_id: str, source: str = "learned", **kwargs: Any) -> bool:
        """Allows a character to learn an ability."""
        guild_id_str = str(guild_id)
        
        if not self._character_manager or not self._rule_engine:
            logger.error("AbilityManager: CharacterManager or RuleEngine not available for learn_ability in guild %s.", guild_id_str) # Changed
            return False

        ability = await self.get_ability(guild_id_str, ability_id)
        if not ability:
            logger.warning("AbilityManager: Ability '%s' not found for guild %s.", ability_id, guild_id_str) # Changed
            return False

        character = self._character_manager.get_character(guild_id_str, character_id)
        if not character:
            logger.warning("AbilityManager: Character '%s' not found for guild %s.", character_id, guild_id_str) # Changed
            return False

        can_learn, reasons = await self._rule_engine.check_ability_learning_requirements(character, ability, **kwargs)
        if not can_learn:
            logger.info("AbilityManager: Character '%s' cannot learn ability '%s' in guild %s. Reasons: %s", character_id, ability_id, guild_id_str, reasons) # Changed
            return False

        if not hasattr(character, 'known_abilities') or character.known_abilities is None:
            logger.debug("AbilityManager: Character model for '%s' in guild %s missing 'known_abilities' attribute. Initializing.", character_id, guild_id_str) # Changed
            character.known_abilities = []
            
        if ability_id not in character.known_abilities:
            character.known_abilities.append(ability_id)
            
            if ability.type == "passive_stat_modifier":
                ability_display_name = getattr(ability, 'name', ability.id)
                logger.info("AbilityManager: Passive ability '%s' learned by char %s in guild %s. Stat mods would be applied by RuleEngine or Character model updates.", ability_display_name, character_id, guild_id_str) # Changed

            await self._character_manager.mark_character_dirty(guild_id_str, character_id)
            logger.info("AbilityManager: Character '%s' in guild %s learned ability '%s' (Source: %s).", character_id, guild_id_str, ability_id, source) # Changed
            return True
        else:
            logger.info("AbilityManager: Character '%s' in guild %s already knows ability '%s'.", character_id, guild_id_str, ability_id) # Changed
            return True

    async def activate_ability(self, guild_id: str, character_id: str, ability_id: str, target_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        """Activates an ability for a character."""
        guild_id_str = str(guild_id)

        if not self._character_manager or not self._rule_engine:
            logger.error("AbilityManager: CharacterManager or RuleEngine not available for activate_ability in guild %s.", guild_id_str) # Changed
            return {"success": False, "message": "Internal server error: Manager not available."}

        ability = await self.get_ability(guild_id_str, ability_id)
        if not ability:
            logger.warning("AbilityManager: Ability '%s' not found for activation in guild %s.", ability_id, guild_id_str) # Added
            return {"success": False, "message": f"Ability '{ability_id}' not found."}
        ability_display_name = getattr(ability, 'name', ability.id)

        if not ability.type.startswith("activated_"):
            logger.warning("AbilityManager: Ability '%s' is not an activatable ability in guild %s.", ability_display_name, guild_id_str) # Added
            return {"success": False, "message": f"Ability '{ability_display_name}' is not an activatable ability."}

        caster = self._character_manager.get_character(guild_id_str, character_id)
        if not caster:
            logger.warning("AbilityManager: Caster '%s' not found for ability activation in guild %s.", character_id, guild_id_str) # Added
            return {"success": False, "message": f"Caster '{character_id}' not found."}
            
        if not hasattr(caster, 'known_abilities') or ability_id not in caster.known_abilities:
             logger.warning("AbilityManager: Caster %s does not know ability '%s' in guild %s.", character_id, ability_display_name, guild_id_str) # Added
             return {"success": False, "message": f"Caster does not know the ability '{ability_display_name}'."}

        if ability.resource_cost:
            for resource, cost in ability.resource_cost.items():
                if resource == "stamina":
                    if not hasattr(caster, 'stats') or resource not in caster.stats:
                        logger.warning("AbilityManager: Caster %s has no '%s' attribute in guild %s.", character_id, resource, guild_id_str) # Added
                        return {"success": False, "message": f"Caster has no '{resource}' attribute."}
                    current_resource_val = caster.stats[resource]
                    if current_resource_val < cost:
                        logger.info("AbilityManager: Not enough %s for %s to use %s in guild %s. Needs %s, has %s.", resource, character_id, ability_display_name, guild_id_str, cost, current_resource_val) # Added
                        return {"success": False, "message": f"Not enough {resource} to use {ability_display_name}. Needs {cost}, has {current_resource_val}."}
                    caster.stats[resource] -= cost
                    logger.info("AbilityManager: Deducted %s %s from %s for %s in guild %s.", cost, resource, character_id, ability_display_name, guild_id_str) # Changed
                else:
                    logger.warning("AbilityManager: Unknown resource cost type '%s' for ability '%s' in guild %s.", resource, ability_display_name, guild_id_str) # Changed
            await self._character_manager.mark_character_dirty(guild_id_str, character_id)

        if ability.cooldown and ability.cooldown > 0:
            if not hasattr(caster, 'ability_cooldowns') or caster.ability_cooldowns is None:
                logger.debug("AbilityManager: Character model for '%s' in guild %s missing 'ability_cooldowns' attribute. Initializing.", character_id, guild_id_str) # Changed
                caster.ability_cooldowns = {}
            
            current_time = time.time()
            if ability_id in caster.ability_cooldowns and caster.ability_cooldowns[ability_id] > current_time:
                remaining_cooldown = caster.ability_cooldowns[ability_id] - current_time
                logger.info("AbilityManager: Ability %s for char %s in guild %s is on cooldown for %.1f more seconds.", ability_display_name, character_id, guild_id_str, remaining_cooldown) # Added
                return {"success": False, "message": f"{ability_display_name} is on cooldown for {remaining_cooldown:.1f} more seconds."}
            
            caster.ability_cooldowns[ability_id] = current_time + ability.cooldown
            await self._character_manager.mark_character_dirty(guild_id_str, character_id)
            logger.info("AbilityManager: Ability '%s' cooldown set for %s in guild %s for %ss.", ability_display_name, character_id, guild_id_str, ability.cooldown) # Changed

        try:
            target_entity = None
            if target_id:
                target_entity = self._character_manager.get_character(guild_id_str, target_id)
                if not target_entity:
                    if hasattr(self._character_manager, '_npc_manager') and self._character_manager._npc_manager:
                        target_entity = self._character_manager._npc_manager.get_npc(guild_id_str, target_id)
                    else:
                        logger.debug("AbilityManager: NPCManager not available via CharacterManager for target resolution in guild %s.", guild_id_str) # Changed

            outcomes = await self._rule_engine.process_ability_effects(
                caster=caster, ability=ability, target_entity=target_entity,
                guild_id=guild_id_str, **kwargs
            )
            logger.info("AbilityManager: Ability '%s' activated by '%s' in guild %s. Outcomes: %s", ability_display_name, character_id, guild_id_str, outcomes) # Changed
            return {"success": True, "message": f"{ability_display_name} activated successfully!", "outcomes": outcomes}
        except Exception as e:
            logger.error("AbilityManager: Error during ability effect processing for '%s' in guild %s: %s", ability_display_name, guild_id_str, e, exc_info=True) # Changed
            return {"success": False, "message": f"Error processing effects for {ability_display_name}."}

    async def process_passive_abilities(self, guild_id: str, character_id: str, event_type: str, event_data: Dict[str, Any], **kwargs: Any) -> None:
        logger.debug("AbilityManager (Conceptual): process_passive_abilities called for char %s, event %s in guild %s.", character_id, event_type, guild_id) # Changed
        pass

    async def load_state(self, guild_id: str, campaign_data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("AbilityManager: load_state for guild %s.", guild_id_str) # Changed
        
        if campaign_data:
            await self.load_ability_templates(guild_id_str, campaign_data)
        else:
            logger.warning("AbilityManager: No campaign_data provided to load_state for guild %s, cannot load ability templates.", guild_id_str) # Changed

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("AbilityManager: save_state for guild %s (No specific state to save for AbilityManager itself).", str(guild_id)) # Changed

    async def rebuild_runtime_caches(self, guild_id: str, campaign_data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("AbilityManager: Rebuilding runtime caches for guild %s.", guild_id_str) # Changed
        if campaign_data:
            await self.load_ability_templates(guild_id_str, campaign_data)
        else:
            logger.warning("AbilityManager: campaign_data not provided for rebuild_runtime_caches in guild %s. Template cache might be stale if not loaded via load_state.", guild_id_str) # Changed
