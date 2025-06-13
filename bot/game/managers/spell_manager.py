# bot/game/managers/spell_manager.py
from __future__ import annotations
import time
import logging # Added
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from ..models.spell import Spell

if TYPE_CHECKING:
    from bot.database.postgres_adapter import PostgresAdapter
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.status_manager import StatusManager
    from ..models.character import Character

logger = logging.getLogger(__name__) # Added

class SpellManager:
    def __init__(self, 
                 db_adapter: Optional[PostgresAdapter] = None, # Note: db_adapter is PostgresAdapter, not DBService
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional[CharacterManager] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 status_manager: Optional[StatusManager] = None,
                 **kwargs: Any):
        self._db_adapter = db_adapter
        self._settings = settings if settings is not None else {}
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._spell_templates: Dict[str, Dict[str, Spell]] = {}
        logger.info("SpellManager initialized.") # Changed

    async def load_spell_templates(self, guild_id: str, campaign_data: Dict[str, Any]) -> None:
        guild_id_str = str(guild_id)
        logger.info("SpellManager: Loading spell templates for guild %s...", guild_id_str) # Added guild_id
        self._spell_templates.setdefault(guild_id_str, {})
        
        spell_templates_data = campaign_data.get("spell_templates", [])
        if not spell_templates_data:
            logger.info("SpellManager: No spell templates found in campaign_data for guild %s.", guild_id_str) # Changed
            return

        loaded_count = 0
        for spell_data in spell_templates_data:
            try:
                spell = Spell.from_dict(spell_data)
                self._spell_templates[guild_id_str][spell.id] = spell
                loaded_count += 1
            except Exception as e:
                logger.error("SpellManager: Error loading spell template '%s' for guild %s: %s", spell_data.get('id', 'UnknownID'), guild_id_str, e, exc_info=True) # Changed
        
        logger.info("SpellManager: Successfully loaded %s spell templates for guild %s.", loaded_count, guild_id_str) # Changed
        if loaded_count > 0 and logger.isEnabledFor(logging.DEBUG): # Changed to DEBUG
            logger.debug("SpellManager: Example spell templates for guild %s:", guild_id_str) # Changed
            count = 0
            for spell_id, spell_obj in self._spell_templates[guild_id_str].items():
                if count < 3:
                    logger.debug("  - ID: %s, Name: %s, Mana Cost: %s", spell_obj.id, spell_obj.name, spell_obj.mana_cost) # Changed
                    count += 1
                else:
                    break
            if loaded_count > 3:
                logger.debug("  ... and %s more.", loaded_count - 3) # Changed

    async def get_spell(self, guild_id: str, spell_id: str) -> Optional[Spell]:
        guild_id_str, spell_id_str = str(guild_id), str(spell_id)
        return self._spell_templates.get(guild_id_str, {}).get(spell_id_str)

    async def learn_spell(self, guild_id: str, character_id: str, spell_id: str, **kwargs: Any) -> bool:
        guild_id_str, character_id_str, spell_id_str = str(guild_id), str(character_id), str(spell_id)
        log_prefix = f"SpellManager.learn_spell(guild='{guild_id_str}', char='{character_id_str}', spell='{spell_id_str}'):" # Added

        if not self._character_manager or not self._rule_engine:
            logger.error("%s CharacterManager or RuleEngine not available.", log_prefix) # Changed
            return False

        spell = await self.get_spell(guild_id_str, spell_id_str)
        if not spell:
            logger.warning("%s Spell not found.", log_prefix) # Changed
            return False

        character = await self._character_manager.get_character(guild_id_str, character_id_str)
        if not character:
            logger.warning("%s Character not found.", log_prefix) # Changed
            return False

        can_learn, reasons = await self._rule_engine.check_spell_learning_requirements(character, spell)
        if not can_learn:
            logger.info("%s Character cannot learn spell. Reasons: %s", log_prefix, reasons) # Changed
            return False

        if not hasattr(character, 'known_spells') or character.known_spells is None:
            logger.debug("%s Character model missing 'known_spells' attribute. Initializing.", log_prefix) # Changed
            character.known_spells = []
            
        if spell_id_str not in character.known_spells:
            character.known_spells.append(spell_id_str)
            await self._character_manager.mark_character_dirty(guild_id_str, character_id_str)
            logger.info("%s Character learned spell.", log_prefix) # Changed
            return True
        else:
            logger.info("%s Character already knows spell.", log_prefix) # Changed
            return True

    async def cast_spell(self, guild_id: str, caster_id: str, spell_id: str, target_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        guild_id_str, caster_id_str, spell_id_str = str(guild_id), str(caster_id), str(spell_id)
        log_prefix = f"SpellManager.cast_spell(guild='{guild_id_str}', caster='{caster_id_str}', spell='{spell_id_str}', target='{target_id}'):" # Added

        if not self._character_manager or not self._rule_engine or not self._status_manager:
            logger.error("%s CharacterManager, RuleEngine, or StatusManager not available.", log_prefix) # Changed
            return {"success": False, "message": "Internal server error: Manager not available."}

        spell = await self.get_spell(guild_id_str, spell_id_str)
        if not spell:
            logger.warning("%s Spell not found.", log_prefix) # Added
            return {"success": False, "message": f"Spell '{spell_id_str}' not found."}

        caster = await self._character_manager.get_character(guild_id_str, caster_id_str)
        if not caster:
            logger.warning("%s Caster not found.", log_prefix) # Added
            return {"success": False, "message": f"Caster '{caster_id_str}' not found."}
            
        if hasattr(caster, 'known_spells') and spell_id_str not in caster.known_spells:
             logger.info("%s Caster does not know the spell '%s'.", log_prefix, spell.name) # Added
             return {"success": False, "message": f"Caster does not know the spell '{spell.name}'."}

        if not hasattr(caster, 'stats') or 'mana' not in caster.stats:
            logger.warning("%s Caster has no mana attribute.", log_prefix) # Added
            return {"success": False, "message": "Caster has no mana attribute."}
        
        current_mana = caster.stats['mana']
        if current_mana < spell.mana_cost:
            logger.info("%s Not enough mana to cast %s. Needs %s, has %s.", log_prefix, spell.name, spell.mana_cost, current_mana) # Added
            return {"success": False, "message": f"Not enough mana to cast {spell.name}. Needs {spell.mana_cost}, has {current_mana}."}
        
        caster.stats['mana'] -= spell.mana_cost
        await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
        logger.info("%s Deducted %s mana. Remaining: %s.", log_prefix, spell.mana_cost, caster.stats['mana']) # Changed

        if not hasattr(caster, 'spell_cooldowns') or caster.spell_cooldowns is None:
            logger.debug("%s Character model missing 'spell_cooldowns' attribute. Initializing.", log_prefix) # Changed
            caster.spell_cooldowns = {}
            
        current_time = time.time()
        if spell_id_str in caster.spell_cooldowns and caster.spell_cooldowns[spell_id_str] > current_time:
            remaining_cooldown = caster.spell_cooldowns[spell_id_str] - current_time
            logger.info("%s Spell on cooldown for %.1f more seconds.", log_prefix, remaining_cooldown) # Added
            return {"success": False, "message": f"{spell.name} is on cooldown for {remaining_cooldown:.1f} more seconds."}
        
        if spell.cooldown > 0:
            caster.spell_cooldowns[spell_id_str] = current_time + spell.cooldown
            await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
            logger.info("%s Spell cooldown set for %ss.", log_prefix, spell.cooldown) # Changed

        try:
            outcomes = await self._rule_engine.process_spell_effects(caster=caster, spell=spell, target_id=target_id, guild_id=guild_id_str, **kwargs)
            logger.info("%s Spell cast. Outcomes: %s", log_prefix, outcomes) # Changed
            return {"success": True, "message": f"{spell.name} cast successfully!", "outcomes": outcomes}
        except Exception as e:
            logger.error("%s Error during spell effect processing: %s", log_prefix, e, exc_info=True) # Changed
            return {"success": False, "message": f"Error processing spell effects for {spell.name}."}

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("SpellManager: load_state for guild %s.", guild_id_str) # Changed
        campaign_data = kwargs.get('campaign_data')
        if campaign_data:
            await self.load_spell_templates(guild_id_str, campaign_data)
        else:
            logger.warning("SpellManager: No campaign_data provided to load_state for guild %s, cannot load spell templates.", guild_id_str) # Changed

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("SpellManager: save_state for guild %s (No specific state to save for SpellManager itself).", str(guild_id)) # Changed

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("SpellManager: Rebuilding runtime caches for guild %s.", str(guild_id)) # Changed
        await self.load_state(guild_id, **kwargs)
