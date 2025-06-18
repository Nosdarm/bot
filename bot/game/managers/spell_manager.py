# bot/game/managers/spell_manager.py
from __future__ import annotations
import time
import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING

# New Imports
from sqlalchemy.ext.asyncio import AsyncSession # For type hinting
import json # For parsing JSON if spell definitions in RulesConfig are stored as strings

from ..models.spell import Spell # Pydantic model

if TYPE_CHECKING:
    from bot.database.postgres_adapter import PostgresAdapter
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.status_manager import StatusManager
    from ..models.character import Character
    from bot.game.managers.game_manager import GameManager # Added for type hinting

logger = logging.getLogger(__name__)

class SpellManager:
    def __init__(self, 
                 db_adapter: Optional[PostgresAdapter] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional[CharacterManager] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 status_manager: Optional[StatusManager] = None,
                 game_manager: Optional['GameManager'] = None, # Added game_manager
                 **kwargs: Any):
        self._db_adapter = db_adapter
        self._settings = settings if settings is not None else {}
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._game_manager = game_manager # Store game_manager
        self._spell_templates: Dict[str, Dict[str, Spell]] = {} # Stores Pydantic Spell models
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
        for spell_data in spell_templates_data:
            try:
                spell = Spell.from_dict(spell_data)
                self._spell_templates[guild_id_str][spell.id] = spell
                loaded_count += 1
            except Exception as e:
                logger.error("SpellManager: Error loading spell template '%s' for guild %s: %s", spell_data.get('id', 'UnknownID'), guild_id_str, e, exc_info=True)
        
        logger.info("SpellManager: Successfully loaded %s spell templates for guild %s.", loaded_count, guild_id_str)
        if loaded_count > 0 and logger.isEnabledFor(logging.DEBUG):
            logger.debug("SpellManager: Example spell templates for guild %s:", guild_id_str)
            count = 0
            for spell_id, spell_obj in self._spell_templates[guild_id_str].items():
                if count < 3:
                    logger.debug("  - ID: %s, Name: %s, Mana Cost: %s", spell_obj.id, spell_obj.name, spell_obj.mana_cost)
                    count += 1
                else:
                    break
            if loaded_count > 3:
                logger.debug("  ... and %s more.", loaded_count - 3)

    async def get_spell(self, guild_id: str, spell_id: str) -> Optional[Spell]: # Returns Pydantic model
        guild_id_str, spell_id_str = str(guild_id), str(spell_id)
        return self._spell_templates.get(guild_id_str, {}).get(spell_id_str)

    async def get_all_spell_definitions_for_guild(self, guild_id: str, session: Optional[AsyncSession] = None) -> List[Dict[str, Any]]:
        """
        Fetches all spell definitions for a specific guild.
        For MVP, attempts to load from RulesConfig, then falls back to loaded templates.
        'session' parameter is included for future DB table integration but not used for RulesConfig/cache access.
        """
        guild_id_str = str(guild_id)
        logger.debug(f"SpellManager: Fetching all spell definitions for guild {guild_id_str}.")

        definitions_from_rules = []
        if self._game_manager:
            spell_defs_raw = await self._game_manager.get_rule(guild_id_str, "guild_spell_definitions", default=[])

            # Handle if rule stores JSON string vs already parsed list/dict
            if isinstance(spell_defs_raw, str):
                try:
                    spell_defs_list = json.loads(spell_defs_raw)
                except json.JSONDecodeError:
                    logger.error(f"SpellManager: Failed to decode 'guild_spell_definitions' JSON string for guild {guild_id_str}: {spell_defs_raw[:100]}")
                    spell_defs_list = []
            elif isinstance(spell_defs_raw, list):
                spell_defs_list = spell_defs_raw
            else:
                logger.warning(f"SpellManager: 'guild_spell_definitions' for guild {guild_id_str} is not a list or JSON string, but type {type(spell_defs_raw)}. Skipping RulesConfig load.")
                spell_defs_list = []

            if isinstance(spell_defs_list, list):
                for spell_data in spell_defs_list:
                    if isinstance(spell_data, dict) and "id" in spell_data and "name_i18n" in spell_data:
                        definitions_from_rules.append({
                            "id": str(spell_data.get("id")),
                            "name_i18n": spell_data.get("name_i18n"),
                            "term_type": "spell",
                            "description_i18n": spell_data.get("description_i18n", {"en": "No description.", "ru": "Нет описания."}),
                            "details": {
                                "cost": spell_data.get("cost", {}),
                                "effect_i18n": spell_data.get("effect_i18n", {}),
                                "type": spell_data.get("type", "general"),
                                "target_type": spell_data.get("target_type", "any"),
                                "range": spell_data.get("range", "self"),
                                "duration": spell_data.get("duration", "instant"),
                                "casting_time": spell_data.get("casting_time", "1 action"),
                                "components": spell_data.get("components", ["V", "S"])
                            }
                        })
                if definitions_from_rules:
                    logger.info(f"SpellManager: Fetched {len(definitions_from_rules)} spells from RulesConfig for guild {guild_id_str}.")
                    return definitions_from_rules

        # Fallback to _spell_templates if no data from RulesConfig or no game_manager
        cached_spell_templates = self._spell_templates.get(guild_id_str, {})
        if cached_spell_templates:
            definitions_from_cache = []
            for spell_id, spell_obj in cached_spell_templates.items():
                definitions_from_cache.append({
                    "id": spell_obj.id,
                    "name_i18n": spell_obj.name_i18n,
                    "term_type": "spell",
                    "description_i18n": spell_obj.description_i18n,
                    "details": {
                        "cost": {"mana": spell_obj.mana_cost} if hasattr(spell_obj, 'mana_cost') else {},
                        "effect_i18n": spell_obj.effect_i18n if hasattr(spell_obj, 'effect_i18n') else {},
                        "type": spell_obj.type if hasattr(spell_obj, 'type') else "general",
                        "target_type": spell_obj.target_type if hasattr(spell_obj, 'target_type') else "any",
                        "range": spell_obj.range_str if hasattr(spell_obj, 'range_str') else "self",
                        "duration": spell_obj.duration_str if hasattr(spell_obj, 'duration_str') else "instant",
                        "casting_time": spell_obj.casting_time_str if hasattr(spell_obj, 'casting_time_str') else "1 action",
                        "components": spell_obj.components if hasattr(spell_obj, 'components') else ["V","S"]
                    }
                })
            if definitions_from_cache:
                 logger.info(f"SpellManager: Fetched {len(definitions_from_cache)} spells from cached templates for guild {guild_id_str} as fallback.")
                 return definitions_from_cache

        logger.warning(f"SpellManager: No spell definitions found for guild {guild_id_str} from RulesConfig or cache.")
        return []

    async def learn_spell(self, guild_id: str, character_id: str, spell_id: str, **kwargs: Any) -> bool:
        guild_id_str, character_id_str, spell_id_str = str(guild_id), str(character_id), str(spell_id)
        log_prefix = f"SpellManager.learn_spell(guild='{guild_id_str}', char='{character_id_str}', spell='{spell_id_str}'):"

        if not self._character_manager or not self._rule_engine:
            logger.error("%s CharacterManager or RuleEngine not available.", log_prefix)
            return False

        spell = await self.get_spell(guild_id_str, spell_id_str) # Pydantic model
        if not spell:
            logger.warning("%s Spell not found.", log_prefix)
            return False

        character = await self._character_manager.get_character(guild_id_str, character_id_str)
        if not character:
            logger.warning("%s Character not found.", log_prefix)
            return False

        can_learn, reasons = await self._rule_engine.check_spell_learning_requirements(character, spell)
        if not can_learn:
            logger.info("%s Character cannot learn spell. Reasons: %s", log_prefix, reasons)
            return False

        if not hasattr(character, 'known_spells') or character.known_spells is None:
            logger.debug("%s Character model missing 'known_spells' attribute. Initializing.", log_prefix)
            character.known_spells = [] # type: ignore
            
        if spell_id_str not in character.known_spells: # type: ignore
            character.known_spells.append(spell_id_str) # type: ignore
            await self._character_manager.mark_character_dirty(guild_id_str, character_id_str)
            logger.info("%s Character learned spell.", log_prefix)
            return True
        else:
            logger.info("%s Character already knows spell.", log_prefix)
            return True

    async def cast_spell(self, guild_id: str, caster_id: str, spell_id: str, target_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        guild_id_str, caster_id_str, spell_id_str = str(guild_id), str(caster_id), str(spell_id)
        log_prefix = f"SpellManager.cast_spell(guild='{guild_id_str}', caster='{caster_id_str}', spell='{spell_id_str}', target='{target_id}'):"

        if not self._character_manager or not self._rule_engine or not self._status_manager:
            logger.error("%s CharacterManager, RuleEngine, or StatusManager not available.", log_prefix)
            return {"success": False, "message": "Internal server error: Manager not available."}

        spell = await self.get_spell(guild_id_str, spell_id_str) # Pydantic model
        if not spell:
            logger.warning("%s Spell not found.", log_prefix)
            return {"success": False, "message": f"Spell '{spell_id_str}' not found."}

        caster = await self._character_manager.get_character(guild_id_str, caster_id_str)
        if not caster:
            logger.warning("%s Caster not found.", log_prefix)
            return {"success": False, "message": f"Caster '{caster_id_str}' not found."}
            
        if hasattr(caster, 'known_spells') and spell_id_str not in caster.known_spells: # type: ignore
             logger.info("%s Caster does not know the spell '%s'.", log_prefix, spell.name)
             return {"success": False, "message": f"Caster does not know the spell '{spell.name}'."}

        if not hasattr(caster, 'stats') or not isinstance(caster.stats, dict) or 'mana' not in caster.stats: # type: ignore
            logger.warning("%s Caster has no mana attribute in stats.", log_prefix)
            return {"success": False, "message": "Caster has no mana attribute in stats."}
        
        current_mana = caster.stats['mana'] # type: ignore
        if current_mana < spell.mana_cost:
            logger.info("%s Not enough mana to cast %s. Needs %s, has %s.", log_prefix, spell.name, spell.mana_cost, current_mana)
            return {"success": False, "message": f"Not enough mana to cast {spell.name}. Needs {spell.mana_cost}, has {current_mana}."}
        
        caster.stats['mana'] -= spell.mana_cost # type: ignore
        await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
        logger.info("%s Deducted %s mana. Remaining: %s.", log_prefix, spell.mana_cost, caster.stats['mana'])

        if not hasattr(caster, 'spell_cooldowns') or caster.spell_cooldowns is None: # type: ignore
            logger.debug("%s Character model missing 'spell_cooldowns' attribute. Initializing.", log_prefix)
            caster.spell_cooldowns = {} # type: ignore
            
        current_time = time.time()
        if spell_id_str in caster.spell_cooldowns and caster.spell_cooldowns[spell_id_str] > current_time: # type: ignore
            remaining_cooldown = caster.spell_cooldowns[spell_id_str] - current_time # type: ignore
            logger.info("%s Spell on cooldown for %.1f more seconds.", log_prefix, remaining_cooldown)
            return {"success": False, "message": f"{spell.name} is on cooldown for {remaining_cooldown:.1f} more seconds."}
        
        if spell.cooldown > 0:
            caster.spell_cooldowns[spell_id_str] = current_time + spell.cooldown # type: ignore
            await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
            logger.info("%s Spell cooldown set for %ss.", log_prefix, spell.cooldown)

        try:
            outcomes = await self._rule_engine.process_spell_effects(caster=caster, spell=spell, target_id=target_id, guild_id=guild_id_str, **kwargs) # type: ignore
            logger.info("%s Spell cast. Outcomes: %s", log_prefix, outcomes)
            return {"success": True, "message": f"{spell.name} cast successfully!", "outcomes": outcomes}
        except Exception as e:
            logger.error("%s Error during spell effect processing: %s", log_prefix, e, exc_info=True)
            return {"success": False, "message": f"Error processing spell effects for {spell.name}."}

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("SpellManager: load_state for guild %s.", guild_id_str)
        campaign_data = kwargs.get('campaign_data')
        if campaign_data:
            await self.load_spell_templates(guild_id_str, campaign_data)
        else:
            logger.warning("SpellManager: No campaign_data provided to load_state for guild %s, cannot load spell templates.", guild_id_str)

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("SpellManager: save_state for guild %s (No specific state to save for SpellManager itself).", str(guild_id))

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("SpellManager: Rebuilding runtime caches for guild %s.", str(guild_id))
        await self.load_state(guild_id, **kwargs)
