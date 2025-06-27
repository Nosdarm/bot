# bot/game/managers/spell_manager.py
from __future__ import annotations
import time
import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession
import json

from ..models.spell import Spell # Ensure Spell model is correctly defined with all expected fields

if TYPE_CHECKING:
    from bot.database.postgres_adapter import PostgresAdapter # Assuming this is the correct adapter type
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.status_manager import StatusManager
    from ..models.character import Character as GameCharacter
    from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__)

class SpellManager:
    def __init__(self, 
                 db_adapter: Optional['PostgresAdapter'] = None, # Corrected type hint
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional['CharacterManager'] = None,
                 rule_engine: Optional['RuleEngine'] = None,
                 status_manager: Optional['StatusManager'] = None,
                 game_manager: Optional['GameManager'] = None,
                 **kwargs: Any):
        self._db_adapter = db_adapter
        self._settings = settings if settings is not None else {}
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._game_manager = game_manager
        self._spell_templates: Dict[str, Dict[str, Spell]] = {}
        logger.info("SpellManager initialized.")

    async def load_spell_templates(self, guild_id: str, campaign_data: Dict[str, Any]) -> None:
        guild_id_str = str(guild_id)
        logger.info("SpellManager: Loading spell templates for guild %s...", guild_id_str)
        self._spell_templates.setdefault(guild_id_str, {})
        
        spell_templates_data = campaign_data.get("spell_templates", [])
        if not spell_templates_data:
            logger.info("SpellManager: No spell templates found in campaign_data for guild %s.", guild_id_str)
            return

        loaded_count = 0
        for spell_data_item in spell_templates_data: # Renamed to avoid conflict
            try:
                if isinstance(spell_data_item, dict):
                    spell = Spell.model_validate(spell_data_item)
                    self._spell_templates[guild_id_str][spell.id] = spell
                    loaded_count += 1
                else:
                    logger.error("SpellManager: Spell template data is not a dictionary for guild %s: %s", guild_id_str, spell_data_item)
            except Exception as e:
                spell_id_for_log = spell_data_item.get('id', 'UnknownID') if isinstance(spell_data_item, dict) else 'UnknownDataStructure'
                logger.error("SpellManager: Error loading spell template '%s' for guild %s: %s", spell_id_for_log, guild_id_str, e, exc_info=True)
        
        logger.info("SpellManager: Successfully loaded %s spell templates for guild %s.", loaded_count, guild_id_str)
        if loaded_count > 0 and logger.isEnabledFor(logging.DEBUG):
            logger.debug("SpellManager: Example spell templates for guild %s:", guild_id_str)
            count = 0
            for spell_id, spell_obj in self._spell_templates[guild_id_str].items():
                if count < 3:
                    spell_name = getattr(spell_obj, 'name_i18n', {}).get('en', 'Unknown Name') # Safer access
                    mana_cost = getattr(spell_obj, 'mana_cost', 'N/A')
                    logger.debug("  - ID: %s, Name: %s, Mana Cost: %s", spell_obj.id, spell_name, mana_cost)
                    count += 1
                else:
                    break
            if loaded_count > 3:
                logger.debug("  ... and %s more.", loaded_count - 3)

    async def get_spell(self, guild_id: str, spell_id: str) -> Optional[Spell]:
        guild_id_str, spell_id_str = str(guild_id), str(spell_id)
        return self._spell_templates.get(guild_id_str, {}).get(spell_id_str)

    async def get_all_spell_definitions_for_guild(self, guild_id: str, session: Optional[AsyncSession] = None) -> List[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        logger.debug(f"SpellManager: Fetching all spell definitions for guild {guild_id_str}.")

        definitions_from_rules: List[Dict[str, Any]] = []
        if self._game_manager and hasattr(self._game_manager, 'get_rule') and callable(getattr(self._game_manager, 'get_rule')):
            get_rule_method = getattr(self._game_manager, 'get_rule')
            spell_defs_raw = await get_rule_method(guild_id_str, "guild_spell_definitions", default=[])
            spell_defs_list: List[Any] = []

            if isinstance(spell_defs_raw, str):
                try:
                    loaded_json = json.loads(spell_defs_raw)
                    if isinstance(loaded_json, list): spell_defs_list = loaded_json
                    else: logger.error(f"SpellManager: Decoded JSON for 'guild_spell_definitions' is not a list for guild {guild_id_str}.")
                except json.JSONDecodeError: logger.error(f"SpellManager: Failed to decode 'guild_spell_definitions' JSON for guild {guild_id_str}: {spell_defs_raw[:100]}")
            elif isinstance(spell_defs_raw, list): spell_defs_list = spell_defs_raw
            else: logger.warning(f"SpellManager: 'guild_spell_definitions' for guild {guild_id_str} is not list/JSON string, but {type(spell_defs_raw)}. Skipping.")

            for spell_data in spell_defs_list:
                if isinstance(spell_data, dict) and "id" in spell_data and "name_i18n" in spell_data:
                    definitions_from_rules.append({
                        "id": str(spell_data.get("id")), "name_i18n": spell_data.get("name_i18n"), "term_type": "spell",
                        "description_i18n": spell_data.get("description_i18n", {"en": "No description.", "ru": "Нет описания."}),
                        "details": {
                            "cost": spell_data.get("cost", {}), "effect_i18n": spell_data.get("effect_i18n", {}),
                            "type": spell_data.get("type", "general"), "target_type": spell_data.get("target_type", "any"),
                            "range": spell_data.get("range_str", "self"), "duration": spell_data.get("duration_str", "instant"),
                            "casting_time": spell_data.get("casting_time_str", "1 action"), "components": spell_data.get("components", ["V", "S"])
                        }})
            if definitions_from_rules:
                logger.info(f"SpellManager: Fetched {len(definitions_from_rules)} spells from RulesConfig for guild {guild_id_str}.")
                return definitions_from_rules
        else: logger.warning(f"SpellManager: GameManager or get_rule method not available for guild {guild_id_str}.")

        cached_spell_templates = self._spell_templates.get(guild_id_str, {})
        if cached_spell_templates:
            definitions_from_cache: List[Dict[str, Any]] = []
            for spell_id, spell_obj in cached_spell_templates.items():
                definitions_from_cache.append({
                    "id": spell_obj.id, "name_i18n": getattr(spell_obj, 'name_i18n', {}), "term_type": "spell",
                    "description_i18n": getattr(spell_obj, 'description_i18n', {}),
                    "details": {
                        "cost": {"mana": getattr(spell_obj, 'mana_cost', 0)}, "effect_i18n": getattr(spell_obj, 'effect_i18n', {}),
                        "type": getattr(spell_obj, 'type', "general"), "target_type": getattr(spell_obj, 'target_type', "any"),
                        "range": getattr(spell_obj, 'range_str', "self"), "duration": getattr(spell_obj, 'duration_str', "instant"),
                        "casting_time": getattr(spell_obj, 'casting_time_str', "1 action"), "components": getattr(spell_obj, 'components', ["V","S"])
                    }})
            if definitions_from_cache:
                 logger.info(f"SpellManager: Fetched {len(definitions_from_cache)} spells from cache for guild {guild_id_str} as fallback.")
                 return definitions_from_cache
        logger.warning(f"SpellManager: No spell definitions found for guild {guild_id_str}.")
        return []

    async def learn_spell(self, guild_id: str, character_id: str, spell_id: str, **kwargs: Any) -> bool:
        guild_id_str, character_id_str, spell_id_str = str(guild_id), str(character_id), str(spell_id)
        log_prefix = f"SpellManager.learn_spell(guild='{guild_id_str}', char='{character_id_str}', spell='{spell_id_str}'):"

        if not self._character_manager or not self._rule_engine:
            logger.error("%s CharacterManager or RuleEngine not available.", log_prefix); return False

        spell = await self.get_spell(guild_id_str, spell_id_str)
        if not spell: logger.warning("%s Spell not found.", log_prefix); return False

        character = await self._character_manager.get_character(guild_id_str, character_id_str)
        if not character: logger.warning("%s Character not found.", log_prefix); return False

        check_req_method = getattr(self._rule_engine, 'check_spell_learning_requirements', None)
        if not callable(check_req_method):
            logger.error("%s RuleEngine.check_spell_learning_requirements not available/callable.", log_prefix); return False

        can_learn, reasons = await check_req_method(character, spell)
        if not can_learn: logger.info("%s Character cannot learn spell. Reasons: %s", log_prefix, reasons); return False

        known_spells_list = getattr(character, 'known_spells', None)
        if not isinstance(known_spells_list, list):
            logger.warning("%s Character.known_spells is not a list (type: %s). Initializing.", log_prefix, type(known_spells_list))
            setattr(character, 'known_spells', [])
            known_spells_list = getattr(character, 'known_spells') # Re-fetch after setting
            if not isinstance(known_spells_list, list): # Should not happen if setattr worked
                 logger.error("%s Failed to initialize character.known_spells as list.", log_prefix); return False

        if spell_id_str not in known_spells_list:
            known_spells_list.append(spell_id_str)
            await self._character_manager.mark_character_dirty(guild_id_str, character_id_str)
            logger.info("%s Character learned spell.", log_prefix); return True
        else:
            logger.info("%s Character already knows spell.", log_prefix); return True

    async def cast_spell(self, guild_id: str, caster_id: str, spell_id: str, target_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        guild_id_str, caster_id_str, spell_id_str = str(guild_id), str(caster_id), str(spell_id)
        log_prefix = f"SpellManager.cast_spell(guild='{guild_id_str}', caster='{caster_id_str}', spell='{spell_id_str}', target='{target_id}'):"

        if not self._character_manager or not self._rule_engine or not self._status_manager:
            logger.error("%s Core managers not available.", log_prefix); return {"success": False, "message": "Internal server error."}

        spell = await self.get_spell(guild_id_str, spell_id_str)
        if not spell: logger.warning("%s Spell not found.", log_prefix); return {"success": False, "message": f"Spell '{spell_id_str}' not found."}

        caster = await self._character_manager.get_character(guild_id_str, caster_id_str)
        if not caster: logger.warning("%s Caster not found.", log_prefix); return {"success": False, "message": f"Caster '{caster_id_str}' not found."}

        caster_known_spells = getattr(caster, 'known_spells', [])
        spell_name_for_msg = getattr(spell, 'name_i18n', {}).get('en', spell_id_str) # Safe name access
        if not isinstance(caster_known_spells, list) or spell_id_str not in caster_known_spells:
             logger.info("%s Caster does not know '%s'.", log_prefix, spell_name_for_msg); return {"success": False, "message": f"Caster does not know '{spell_name_for_msg}'."}

        caster_stats = getattr(caster, 'stats', None)
        if not isinstance(caster_stats, dict) or 'mana' not in caster_stats:
            logger.warning("%s Caster stats/mana missing.", log_prefix); return {"success": False, "message": "Caster stats/mana missing."}
        
        current_mana = caster_stats.get('mana', 0.0) # Default to 0 if mana key exists but is None or invalid
        if not isinstance(current_mana, (int, float)): current_mana = 0.0

        spell_mana_cost = getattr(spell, 'mana_cost', 0.0) # Default to 0 if missing
        if current_mana < spell_mana_cost:
            logger.info("%s Not enough mana for %s. Needs %s, has %s.", log_prefix, spell_name_for_msg, spell_mana_cost, current_mana)
            return {"success": False, "message": f"Not enough mana for {spell_name_for_msg}. Needs {spell_mana_cost}, has {current_mana}."}
        
        caster_stats['mana'] = current_mana - spell_mana_cost
        await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
        logger.info("%s Mana: %s -> %s.", log_prefix, current_mana, caster_stats['mana'])

        caster_spell_cooldowns = getattr(caster, 'spell_cooldowns', None)
        if not isinstance(caster_spell_cooldowns, dict):
            logger.warning("%s Character.spell_cooldowns is not a dict (type: %s). Initializing.", log_prefix, type(caster_spell_cooldowns))
            setattr(caster, 'spell_cooldowns', {})
            caster_spell_cooldowns = getattr(caster, 'spell_cooldowns')
            if not isinstance(caster_spell_cooldowns, dict): # Should not happen
                 logger.error("%s Failed to initialize character.spell_cooldowns as dict.", log_prefix); return {"success": False, "message": "Internal error with cooldowns."}


        current_time = time.time()
        cooldown_end_time = caster_spell_cooldowns.get(spell_id_str)
        if isinstance(cooldown_end_time, (int, float)) and cooldown_end_time > current_time: # Check type too
            remaining = cooldown_end_time - current_time
            logger.info("%s '%s' on cooldown for %.1fs.", log_prefix, spell_name_for_msg, remaining)
            return {"success": False, "message": f"'{spell_name_for_msg}' on cooldown for {remaining:.1f}s."}
        
        spell_cooldown_val = getattr(spell, 'cooldown', 0.0)
        if spell_cooldown_val > 0:
            caster_spell_cooldowns[spell_id_str] = current_time + spell_cooldown_val
            await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
            logger.info("%s '%s' cooldown set for %ss.", log_prefix, spell_name_for_msg, spell_cooldown_val)

        process_effects_method = getattr(self._rule_engine, 'process_spell_effects', None)
        if not callable(process_effects_method):
             logger.error("%s RuleEngine.process_spell_effects not available/callable.", log_prefix); return {"success": False, "message": "Internal error: RuleEngine issue."}

        try:
            outcomes = await process_effects_method(caster=caster, spell=spell, target_id=target_id, guild_id=guild_id_str, **kwargs)
            logger.info("%s Spell '%s' cast. Outcomes: %s", log_prefix, spell_name_for_msg, outcomes)
            return {"success": True, "message": f"'{spell_name_for_msg}' cast successfully!", "outcomes": outcomes}
        except Exception as e:
            logger.error("%s Error processing spell effects for '%s': %s", log_prefix, spell_name_for_msg, e, exc_info=True)
            return {"success": False, "message": f"Error processing spell effects for {spell_name_for_msg}."}

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("SpellManager: load_state for guild %s.", guild_id_str)
        campaign_data = kwargs.get('campaign_data')
        if campaign_data and isinstance(campaign_data, dict): # Ensure campaign_data is dict
            await self.load_spell_templates(guild_id_str, campaign_data)
        else:
            logger.warning("SpellManager: No campaign_data or invalid type provided to load_state for guild %s.", guild_id_str)

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("SpellManager: save_state for guild %s (No specific state to save for SpellManager itself).", str(guild_id))

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("SpellManager: Rebuilding runtime caches for guild %s.", str(guild_id))
        await self.load_state(guild_id, **kwargs)

[end of bot/game/managers/spell_manager.py]
