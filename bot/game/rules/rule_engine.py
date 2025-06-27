# bot/game/rules/rule_engine.py

from __future__ import annotations
import random
import re
import logging # Added
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable, TYPE_CHECKING, Union # Removed Set, asyncio, json, traceback

from bot.game.models.check_models import CheckResult
# from bot.game.models.status_effect import StatusEffect # Removed unused import

if TYPE_CHECKING:
    from bot.game.models.npc import NPC
    from bot.game.models.party import Party
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.game_manager import GameManager

from bot.game.models.character import Character
# from bot.game.models.combat import Combat, CombatParticipant # Combat model not directly used here
from bot.game.managers.time_manager import TimeManager


# Import the resolvers
from .resolvers import skill_check_resolver, economic_resolver, dialogue_resolver, combat_ai_resolver

logger = logging.getLogger(__name__)
logger.debug("RuleEngine: Module loaded.")

class RuleEngine:
    def __init__(self,
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional["CharacterManager"] = None,
                 npc_manager: Optional["NpcManager"] = None,
                 status_manager: Optional["StatusManager"] = None,
                 item_manager: Optional["ItemManager"] = None,
                 location_manager: Optional["LocationManager"] = None,
                 party_manager: Optional["PartyManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 dialogue_manager: Optional["DialogueManager"] = None,
                 time_manager: Optional["TimeManager"] = None,
                 rules_data: Optional[Dict[str, Any]] = None,
                 game_log_manager: Optional["GameLogManager"] = None,
                 relationship_manager: Optional["RelationshipManager"] = None,
                 economy_manager: Optional["EconomyManager"] = None,
                 game_manager: Optional["GameManager"] = None # Added game_manager
                 ):
        logger.info("Initializing RuleEngine...")
        self._settings = settings or {}
        self._game_log_manager: Optional["GameLogManager"] = game_log_manager
        self._character_manager: Optional["CharacterManager"] = character_manager
        self._npc_manager: Optional["NpcManager"] = npc_manager
        self._status_manager: Optional["StatusManager"] = status_manager
        self._item_manager: Optional["ItemManager"] = item_manager
        self._location_manager: Optional["LocationManager"] = location_manager
        self._party_manager: Optional["PartyManager"] = party_manager
        self._combat_manager: Optional["CombatManager"] = combat_manager
        self._dialogue_manager: Optional["DialogueManager"] = dialogue_manager
        self._time_manager: Optional["TimeManager"] = time_manager
        self._relationship_manager: Optional["RelationshipManager"] = relationship_manager
        self._economy_manager: Optional["EconomyManager"] = economy_manager
        self._game_manager: Optional["GameManager"] = game_manager
        
        self._rules_data: Dict[str, Any] = rules_data if rules_data is not None else (self._settings.get('game_rules', {}) if self._settings else {})
        
        logger.info("RuleEngine initialized.")

    async def load_rules_data(self) -> None:
        logger.info("RuleEngine: Loading rules data...")
        self._rules_data = self._settings.get('game_rules', {}) if self._settings else {}
        logger.info(f"RuleEngine: Loaded {len(self._rules_data)} rules entries.")

    async def load_state(self, **kwargs: Any) -> None:
         await self.load_rules_data()

    async def save_state(self, **kwargs: Any) -> None:
         logger.info("RuleEngine: Save state method called. (Placeholder - does RuleEngine have state to save?)")
         pass

    def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info(f"RuleEngine: Rebuilding runtime caches for guild {guild_id}. (Placeholder)")
        pass

    async def execute_triggers(self, triggers: List[Dict[str, Any]], context: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        logger.info(f"RuleEngine: execute_triggers called with {len(triggers)} triggers. Context keys: {list(context.keys())}")
        return {}, True

    async def calculate_action_duration(
        self,
        action_type: str,
        action_context: Dict[str, Any],
        character: Optional["Character"] = None,
        npc: Optional["NPC"] = None,
        party: Optional["Party"] = None,
        **context: Dict[str, Any],
    ) -> float:
        lm: Optional["LocationManager"] = context.get('location_manager') or self._location_manager # Type "Dict[str, Any] | LocationManager | None" is not assignable to declared type "LocationManager | None" (Pyright error)
        curr = getattr(character or npc, 'location_id', None)
        target = action_context.get('target_location_id')

        rules_data_val = self._rules_data if self._rules_data else {}

        if action_type == 'move':
            if curr is not None and target is not None and lm:
                base = float(rules_data_val.get('base_move_duration_per_location', 5.0))
                return base
            logger.warning(f"RuleEngine: Cannot calculate duration for move from {curr} to {target} (lm: {lm is not None}). Returning 0.0.")
            return 0.0

        action_durations: Dict[str, float] = {
            'combat_attack': float(rules_data_val.get('base_attack_duration', 1.0)),
            'rest': float(action_context.get('duration', rules_data_val.get('default_rest_duration', 10.0))),
            'search': float(rules_data_val.get('base_search_duration', 5.0)),
            'craft': float(rules_data_val.get('base_craft_duration', 30.0)),
            'use_item': float(rules_data_val.get('base_use_item_duration', 1.0)),
            'ai_dialogue': float(rules_data_val.get('base_dialogue_step_duration', 0.1)),
            'idle': float(rules_data_val.get('default_idle_duration', 60.0)),
        }
        duration = action_durations.get(action_type)
        if duration is not None:
            return duration

        logger.warning(f"RuleEngine: Unknown action type '{action_type}' for duration calculation. Returning 0.0.")
        return 0.0

    async def check_conditions(self, conditions: List[Dict[str, Any]], context: Dict[str, Any]) -> bool:
        if not conditions: return True

        cm: Optional[CharacterManager] = context.get('character_manager') or self._character_manager
        nm: Optional[NpcManager] = context.get('npc_manager') or self._npc_manager
        lm: Optional[LocationManager] = context.get('location_manager') or self._location_manager
        im: Optional[ItemManager] = context.get('item_manager') or self._item_manager
        pm: Optional[PartyManager] = context.get('party_manager') or self._party_manager
        sm: Optional[StatusManager] = context.get('status_manager') or self._status_manager
        combat_mgr: Optional[CombatManager] = context.get('combat_manager') or self._combat_manager

        for cond in conditions:
            ctype = cond.get('type')
            data = cond.get('data', {})
            met = False

            entity = context.get('character') or context.get('npc') or context.get('party')
            entity_id_any = data.get('entity_id') or getattr(entity, 'id', None)
            entity_id: Optional[str] = str(entity_id_any) if entity_id_any is not None else None
            entity_type: Optional[str] = data.get('entity_type') or (type(entity).__name__ if entity else None)

            if ctype == 'has_item' and im:
                item_template_id_condition = data.get('item_template_id')
                item_id_condition = data.get('item_id')
                quantity_condition = float(data.get('quantity', 1.0))

                if entity_id and entity_type and (item_template_id_condition or item_id_condition):
                    guild_id_from_context = str(context.get('guild_id'))
                    if guild_id_from_context:
                        owned_items_raw = await im.get_items_by_owner(guild_id_from_context, entity_id) # "CoroutineType[Any, Any, List[Item]]" is not iterable (Pyright error)
                        owned_items: List[Dict[str, Any]] = owned_items_raw if isinstance(owned_items_raw, list) else []

                        found_item_count = 0.0
                        for item_instance_dict in owned_items:
                            if not isinstance(item_instance_dict, dict): continue
                            matches_template = (item_template_id_condition and
                                                str(item_instance_dict.get('template_id')) == str(item_template_id_condition))
                            matches_instance_id = (item_id_condition and
                                                   str(item_instance_dict.get('id')) == str(item_id_condition))

                            item_qty = item_instance_dict.get('quantity', 0.0)
                            current_item_qty = float(item_qty) if isinstance(item_qty, (int, float)) else 0.0

                            if item_id_condition:
                                if matches_instance_id:
                                    found_item_count += current_item_qty
                                    break
                            elif matches_template:
                                found_item_count += current_item_qty

                        if found_item_count >= quantity_condition:
                            met = True
            elif ctype == 'in_location' and lm:
                loc_id_in_cond = data.get('location_id')
                if entity and loc_id_in_cond:
                     entity_location_id = getattr(entity, 'current_location_id', getattr(entity, 'location_id', None))
                     if entity_location_id is not None and str(entity_location_id) == str(loc_id_in_cond):
                         met = True
            elif ctype == 'has_status' and sm:
                status_type_cond = data.get('status_type')
                if entity_id and entity_type and status_type_cond:
                    guild_id_from_context = str(context.get('guild_id'))
                    if guild_id_from_context and hasattr(sm, '_status_effects') and isinstance(sm._status_effects, dict): # Check type of _status_effects
                        guild_statuses_cache: Dict[str, Any] = sm._status_effects.get(guild_id_from_context, {})
                        for effect_instance in guild_statuses_cache.values():
                            if (str(getattr(effect_instance, 'target_id', None)) == entity_id and
                                str(getattr(effect_instance, 'target_type', None)) == entity_type and
                                str(getattr(effect_instance, 'status_type', None)) == str(status_type_cond)):
                                met = True
                                break
            elif ctype == 'stat_check':
                met = await self.perform_stat_check(entity, str(data.get('stat')), data.get('threshold'), str(data.get('operator', '>=')))
            elif ctype == 'is_in_combat' and combat_mgr and entity_id:
                 guild_id = str(context.get('guild_id'))
                 if guild_id: # Argument missing for parameter "entity_id" (Pyright error)
                    met = bool(await combat_mgr.get_combat_by_participant_id(entity_id, guild_id=guild_id)) # Pass entity_id
            elif ctype == 'is_leader_of_party' and pm and entity_id and entity_type == 'Character':
                 guild_id_str = str(context.get('guild_id'))
                 if guild_id_str and hasattr(pm, 'get_party_by_member_id') and callable(getattr(pm, 'get_party_by_member_id')):
                     party_instance = await pm.get_party_by_member_id(guild_id_str, entity_id) # No parameter named "context" (Pyright error)
                     if party_instance and getattr(party_instance, 'leader_id', None) == entity_id:
                         met = True
            else:
                logger.warning(f"RuleEngine: Unknown or unhandled condition type '{ctype}' or missing manager for guild {context.get('guild_id')}.")
                return False

            if not met:
                return False
        return True

    async def perform_stat_check(self, entity: Any, stat_name: str, threshold: Any, operator: str = '>=' ) -> bool:
        entity_stats = getattr(entity, 'stats_json', {}) if isinstance(entity, Character) else getattr(entity, 'stats', {})
        if not isinstance(entity_stats, dict): entity_stats = {}
        stat_value_any = entity_stats.get(stat_name)
        if stat_value_any is None: return False
        try:
            stat_value_numeric = float(stat_value_any)
            threshold_numeric = float(threshold)
            if operator == '>=': return stat_value_numeric >= threshold_numeric
            elif operator == '>': return stat_value_numeric > threshold_numeric
            elif operator == '<=': return stat_value_numeric <= threshold_numeric
            elif operator == '<': return stat_value_numeric < threshold_numeric
            elif operator == '==': return stat_value_numeric == threshold_numeric
            elif operator == '!=': return stat_value_numeric != threshold_numeric
            else: logger.warning(f"Unknown operator '{operator}' in perform_stat_check."); return False
        except (ValueError, TypeError):
            logger.warning(f"Could not convert stat '{stat_name}' value '{stat_value_any}' or threshold '{threshold}' to float.")
            return False
        except Exception as e:
            logger.error(f"Error in perform_stat_check: {e}", exc_info=True)
            return False

    def generate_initial_character_stats(self) -> Dict[str, Any]:
        char_stats_rules = self._rules_data.get("character_stats_rules", {}) if self._rules_data else {}
        default_stats = char_stats_rules.get("default_initial_stats",
                                             {'strength': 10, 'dexterity': 10, 'constitution': 10,
                                              'intelligence': 10, 'wisdom': 10, 'charisma': 10})
        return default_stats.copy()

    def _calculate_attribute_modifier(self, attribute_value: int) -> int:
        char_stats_rules = self._rules_data.get("character_stats_rules", {}) if self._rules_data else {}
        formula_str: str = char_stats_rules.get("attribute_modifier_formula", "(attribute_value - 10) // 2")

        allowed_chars = "attribute_value()+-*/0123456789 "
        if not all(char in allowed_chars for char in formula_str):
            logger.warning(f"Potentially unsafe formula detected: {formula_str}. Using default.")
            formula_str = "(attribute_value - 10) // 2"

        try:
            modifier = eval(formula_str, {"__builtins__": {}}, {"attribute_value": int(attribute_value)})
            return int(modifier)
        except Exception as e:
            logger.error(f"Error evaluating attribute_modifier_formula '{formula_str}': {e}", exc_info=True)
            return (int(attribute_value) - 10) // 2

    def get_base_dc(self, relevant_stat_value: int, difficulty_modifier: Optional[str] = None) -> int:
        check_rules = self._rules_data.get("check_rules", {}) if self._rules_data else {}
        base_dc_config = check_rules.get("base_dc_calculation", {}) if isinstance(check_rules, dict) else {}
        difficulty_modifiers_config = check_rules.get("difficulty_modifiers", {}) if isinstance(check_rules, dict) else {}

        base_dc_value = int(base_dc_config.get("base_value", 10))
        stat_contribution_formula: str = base_dc_config.get("stat_contribution_formula", "(relevant_stat_value - 10) // 2")

        stat_contribution = 0
        try:
            stat_contribution = eval(stat_contribution_formula, {"__builtins__": {}}, {"relevant_stat_value": int(relevant_stat_value)})
        except Exception as e:
            logger.error(f"Error evaluating stat_contribution_formula '{stat_contribution_formula}': {e}", exc_info=True)
            stat_contribution = (int(relevant_stat_value) - 10) // 2

        difficulty_mod_value = 0
        if difficulty_modifier:
            difficulty_mod_value = int(difficulty_modifiers_config.get(difficulty_modifier.lower(), 0))

        final_dc = base_dc_value + int(stat_contribution) + difficulty_mod_value
        return int(final_dc)

    # --- Skill Check Wrappers ---
    async def resolve_stealth_check(self, character_id: str, guild_id: str, location_id: str, **kwargs: Any) -> CheckResult:
        if not self._character_manager: raise ValueError("CharacterManager not available for resolve_stealth_check") # Argument of type "CharacterManager | None" cannot be assigned to parameter "character_manager" of type "CharacterManager" (Pyright error)
        return await skill_check_resolver.resolve_stealth_check(
            character_manager=self._character_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id,
            guild_id=guild_id, location_id=location_id, **kwargs)

    async def resolve_pickpocket_attempt(self, character_id: str, guild_id: str, target_npc_id: str, **kwargs: Any) -> CheckResult:
        if not self._character_manager: raise ValueError("CharacterManager not available for resolve_pickpocket_attempt")
        if not self._npc_manager: raise ValueError("NpcManager not available for resolve_pickpocket_attempt") # Argument of type "NpcManager | None" cannot be assigned to parameter "npc_manager" of type "NpcManager" (Pyright error)
        return await skill_check_resolver.resolve_pickpocket_attempt(
            character_manager=self._character_manager, npc_manager=self._npc_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id, guild_id=guild_id,
            target_npc_id=target_npc_id, **kwargs)

    async def resolve_gathering_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any], **kwargs: Any) -> CheckResult:
        if not self._character_manager: raise ValueError("CharacterManager not available for resolve_gathering_attempt")
        return await skill_check_resolver.resolve_gathering_attempt(
            character_manager=self._character_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id, guild_id=guild_id,
            poi_data=poi_data, **kwargs)

    async def resolve_crafting_attempt(self, character_id: str, guild_id: str, recipe_data: Dict[str, Any],
                                       current_location_data: Dict[str, Any], **kwargs: Any) -> CheckResult:
        if not self._character_manager: raise ValueError("CharacterManager not available for resolve_crafting_attempt")
        return await skill_check_resolver.resolve_crafting_attempt(
            character_manager=self._character_manager, rules_data=self._rules_data,
            character_id=character_id, guild_id=guild_id, recipe_data=recipe_data,
            current_location_data=current_location_data, **kwargs)

    async def resolve_lockpick_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any], **kwargs: Any) -> CheckResult:
        if not self._character_manager: raise ValueError("CharacterManager not available for resolve_lockpick_attempt")
        return await skill_check_resolver.resolve_lockpick_attempt(
            character_manager=self._character_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id, guild_id=guild_id,
            poi_data=poi_data, **kwargs)

    async def resolve_disarm_trap_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any], **kwargs: Any) -> CheckResult:
        if not self._character_manager: raise ValueError("CharacterManager not available for resolve_disarm_trap_attempt")
        return await skill_check_resolver.resolve_disarm_trap_attempt(
            character_manager=self._character_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id, guild_id=guild_id,
            poi_data=poi_data, **kwargs)

    async def resolve_skill_check_wrapper(self, character: "Character", skill_type: str, dc: int, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, int, int, Optional[str]]:
        return await skill_check_resolver.resolve_skill_check(
            character=character, skill_type=skill_type, dc=dc, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, context=context)

    # --- Economic Method Wrappers ---
    async def calculate_market_price(self, guild_id: str, location_id: str, item_template_id: str, quantity: float,
                                     is_selling_to_market: bool, actor_entity_id: str, actor_entity_type: str,
                                     **kwargs: Any) -> Optional[float]:
        if not self._economy_manager: return None
        return await economic_resolver.calculate_market_price(
            rules_data=self._rules_data, guild_id=guild_id, location_id=location_id,
            item_template_id=item_template_id, quantity=quantity, is_selling_to_market=is_selling_to_market,
            actor_entity_id=actor_entity_id, actor_entity_type=actor_entity_type,
            economy_manager=self._economy_manager, character_manager=self._character_manager,
            location_manager=self._location_manager, relationship_manager=self._relationship_manager,
            npc_manager=self._npc_manager, **kwargs)

    async def process_economy_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        if not self._economy_manager: return
        await economic_resolver.process_economy_tick(
            rules_data=self._rules_data, guild_id=guild_id, game_time_delta=game_time_delta,
            economy_manager=self._economy_manager, **kwargs)

    # --- Dialogue Method Wrappers ---
    async def process_dialogue_action(self, dialogue_data: Dict[str, Any], character_id: str, p_action_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        if not self._dialogue_manager: return {"error": "DialogueManager not available"} # Argument of type "DialogueManager | None" cannot be assigned to parameter "dialogue_manager" of type "DialogueManager" (Pyright error)
        return await dialogue_resolver.process_dialogue_action(
            rules_data=self._rules_data, dialogue_manager=self._dialogue_manager,
            character_manager=self._character_manager, npc_manager=self._npc_manager,
            relationship_manager=self._relationship_manager,
            resolve_skill_check_func=self.resolve_skill_check_wrapper,
            dialogue_data=dialogue_data, character_id=character_id,
            p_action_data=p_action_data, context=context)

    async def get_filtered_dialogue_options(self, dialogue_data: Dict[str, Any], character_id: str, stage_definition: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
        return await dialogue_resolver.get_filtered_dialogue_options(
            rules_data=self._rules_data, character_manager=self._character_manager,
            npc_manager=self._npc_manager, relationship_manager=self._relationship_manager,
            dialogue_data=dialogue_data, character_id=character_id,
            stage_definition=stage_definition, context=context)

    # --- Combat AI / NPC Behavior Wrappers ---
    async def choose_combat_action_for_npc(self, npc: "NPC", combat: Any, **context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await combat_ai_resolver.choose_combat_action_for_npc(
            rules_data=self._rules_data, npc=npc, combat=combat, # "Combat" is not defined (Pyright error)
            character_manager=self._character_manager, npc_manager=self._npc_manager,
            combat_manager=self._combat_manager, relationship_manager=self._relationship_manager,
            context=context)

    async def choose_peaceful_action_for_npc(self, npc: "NPC", **context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await combat_ai_resolver.choose_peaceful_action_for_npc(
            rules_data=self._rules_data, npc=npc,
            location_manager=self._location_manager, character_manager=self._character_manager,
            dialogue_manager=self._dialogue_manager, relationship_manager=self._relationship_manager,
            context=context)

    async def can_rest(self, npc: "NPC", **context: Dict[str, Any]) -> bool:
        return await combat_ai_resolver.can_rest(
            npc=npc, combat_manager=self._combat_manager, context=context)

    # --- Methods to be kept in RuleEngine (or moved to a general_rules_resolver) ---
    async def handle_stage(self, stage: Any, **context: Dict[str, Any]) -> None:
        proc: Optional["EventStageProcessor"] = context.get('event_stage_processor')
        event: Any = context.get('event')
        send_message_callback: Optional[Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]] = context.get('send_message_callback')

        if proc and event and send_message_callback: # Type "Dict[str, Any] | None" is not assignable to declared type "((str, Dict[str, Any] | None) -> Awaitable[Any]) | None" (Pyright error)
            target_stage_id_any = getattr(stage, 'next_stage_id', None) or stage.get('next_stage_id')
            target_stage_id = str(target_stage_id_any) if target_stage_id_any is not None else None
            if target_stage_id: # Many argument type errors for advance_stage (Pyright errors)
                 await proc.advance_stage(event=event, target_stage_id=target_stage_id, send_message_callback=send_message_callback, **context)

    def _compare_values(self, value1: Any, value2: Any, operator: str) -> bool:
        try:
            num1 = float(value1)
            num2 = float(value2)
            
            if operator == '>=':
                return num1 >= num2
            elif operator == '>':
                return num1 > num2
            elif operator == '<=':
                return num1 <= num2
            elif operator == '<':
                return num1 < num2
            elif operator == '==':
                return num1 == num2
            elif operator == '!=':
                return num1 != num2
            else:
                logger.warning(f"Unknown operator '{operator}' for numeric comparison in _compare_values.")
                return False
        except (ValueError, TypeError):
            if operator == '==':
                return str(value1) == str(value2)
            elif operator == '!=':
                return str(value1) != str(value2)
            logger.debug(f"Could not compare '{value1}' and '{value2}' numerically with operator '{operator}'. Falling back to string comparison or False.")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in _compare_values with values '{value1}', '{value2}', operator '{operator}': {e}", exc_info=True)
            return False

    async def resolve_dice_roll(self, dice_string: str, pre_rolled_result: Optional[int] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        dice_string_cleaned = str(dice_string).lower().strip()
        match = re.fullmatch(r"(\d*)d(\d+)(\s*[+-]\s*\d+)?", dice_string_cleaned)

        num_dice_str: Optional[str]
        sides_str: Optional[str]
        modifier_str: Optional[str]

        if not match:
            match_simple = re.fullmatch(r"d(\d+)(\s*[+-]\s*\d+)?", dice_string_cleaned)
            if match_simple:
                num_dice_str, sides_str, modifier_str = "1", match_simple.group(1), match_simple.group(2)
            else:
                logger.error(f"Invalid dice string format: {dice_string}")
                raise ValueError(f"Invalid dice string format: {dice_string}")
        else:
            num_dice_str, sides_str, modifier_str = match.group(1), match.group(2), match.group(3)

        num_dice = int(num_dice_str) if num_dice_str else 1
        sides = int(sides_str) if sides_str else 0
        modifier_val = 0
        if modifier_str:
            try:
                modifier_val = int(modifier_str.replace(" ", ""))
            except ValueError:
                logger.error(f"Invalid modifier format in dice string: {dice_string}")
                raise ValueError(f"Invalid modifier format in dice string: {dice_string}")

        if sides <= 0:
            logger.error(f"Dice sides must be positive, got: {sides} from string '{dice_string}'")
            raise ValueError("Dice sides must be positive.")
        if num_dice <= 0:
            logger.error(f"Number of dice must be positive, got: {num_dice} from string '{dice_string}'")
            raise ValueError("Number of dice must be positive.")

        rolls: List[int] = []
        roll_total: int = 0

        for i in range(num_dice):
            roll: int
            if i == 0 and pre_rolled_result is not None:
                if not (1 <= pre_rolled_result <= sides):
                    logger.error(f"pre_rolled_result {pre_rolled_result} is not valid for a d{sides}.")
                    raise ValueError(f"pre_rolled_result {pre_rolled_result} is not valid for a d{sides}.")
                roll = pre_rolled_result
            else:
                roll = random.randint(1, sides)
            rolls.append(roll)
            roll_total += roll

        total_with_modifier: int = roll_total + modifier_val

        return {
            "dice_string": dice_string, "num_dice": num_dice, "sides": sides,
            "modifier": modifier_val, "rolls": rolls, "roll_total_raw": roll_total,
            "total": total_with_modifier, "pre_rolled_input": pre_rolled_result
        }

logger.debug("RuleEngine: Module defined.")
