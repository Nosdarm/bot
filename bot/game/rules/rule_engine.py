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

from bot.game.models.character import Character
from bot.game.models.combat import Combat, CombatParticipant
from bot.game.managers.time_manager import TimeManager

# Import the resolvers
from .resolvers import skill_check_resolver, economic_resolver, dialogue_resolver, combat_ai_resolver

logger = logging.getLogger(__name__) # Added
logger.debug("RuleEngine: Module loaded.") # Changed print to logger

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
                 economy_manager: Optional["EconomyManager"] = None
                 ):
        logger.info("Initializing RuleEngine...") # Changed print to logger
        self._settings = settings or {}
        self._game_log_manager = game_log_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._status_manager = status_manager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager
        self._time_manager = time_manager
        self._relationship_manager = relationship_manager
        self._economy_manager = economy_manager
        
        if rules_data is not None:
            self._rules_data = rules_data
        else:
            self._rules_data = self._settings.get('game_rules', {})
        
        logger.info("RuleEngine initialized.") # Changed print to logger

    async def load_rules_data(self) -> None:
        logger.info("RuleEngine: Loading rules data...") # Changed print to logger
        self._rules_data = self._settings.get('game_rules', {})
        logger.info(f"RuleEngine: Loaded {len(self._rules_data)} rules entries.") # Changed print to logger

    async def load_state(self, **kwargs: Any) -> None:
         await self.load_rules_data()

    async def save_state(self, **kwargs: Any) -> None:
         logger.info("RuleEngine: Save state method called. (Placeholder - does RuleEngine have state to save?)") # Changed print to logger
         pass

    def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info(f"RuleEngine: Rebuilding runtime caches for guild {guild_id}. (Placeholder)") # Changed print to logger
        pass

    async def calculate_action_duration(
        self,
        action_type: str,
        action_context: Dict[str, Any],
        character: Optional["Character"] = None,
        npc: Optional["NPC"] = None,
        party: Optional["Party"] = None,
        **context: Dict[str, Any],
    ) -> float:
        lm: Optional["LocationManager"] = context.get('location_manager') or self._location_manager
        curr = getattr(character or npc, 'location_id', None)
        target = action_context.get('target_location_id')

        if action_type == 'move':
            if curr is not None and target is not None and lm:
                base = float(self._rules_data.get('base_move_duration_per_location', 5.0))
                return base
            logger.warning(f"RuleEngine: Cannot calculate duration for move from {curr} to {target} (lm: {lm is not None}). Returning 0.0.") # Changed print
            return 0.0
        if action_type == 'combat_attack':
            return float(self._rules_data.get('base_attack_duration', 1.0))
        if action_type == 'rest':
            return float(action_context.get('duration', self._rules_data.get('default_rest_duration', 10.0)))
        if action_type == 'search':
            return float(self._rules_data.get('base_search_duration', 5.0))
        if action_type == 'craft':
            return float(self._rules_data.get('base_craft_duration', 30.0))
        if action_type == 'use_item':
            return float(self._rules_data.get('base_use_item_duration', 1.0))
        if action_type == 'ai_dialogue':
            return float(self._rules_data.get('base_dialogue_step_duration', 0.1))
        if action_type == 'idle':
            return float(self._rules_data.get('default_idle_duration', 60.0))
        logger.warning(f"RuleEngine: Unknown action type '{action_type}' for duration calculation. Returning 0.0.") # Changed print
        return 0.0


    async def check_conditions(
        self,
        conditions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> bool:
        if not conditions: return True
        cm = context.get('character_manager') or self._character_manager
        nm = context.get('npc_manager') or self._npc_manager
        lm = context.get('location_manager') or self._location_manager
        im = context.get('item_manager') or self._item_manager
        pm = context.get('party_manager') or self._party_manager
        sm = context.get('status_manager') or self._status_manager
        combat_mgr = context.get('combat_manager') or self._combat_manager
        for cond in conditions:
            ctype = cond.get('type'); data = cond.get('data', {}); met = False
            entity = context.get('character') or context.get('npc') or context.get('party')
            entity_id = data.get('entity_id') or getattr(entity, 'id', None)
            entity_type = data.get('entity_type') or (type(entity).__name__ if entity else None)
            if ctype == 'has_item' and im:
                item_template_id_condition = data.get('item_template_id'); item_id_condition = data.get('item_id'); quantity_condition = data.get('quantity', 1)
                if entity_id and entity_type and (item_template_id_condition or item_id_condition):
                    guild_id_from_context = context.get('guild_id')
                    if guild_id_from_context:
                        owned_items = im.get_items_by_owner(guild_id_from_context, entity_id)
                        found_item_count = 0
                        for item_instance_dict in owned_items:
                            matches_template = (item_template_id_condition and item_instance_dict.get('template_id') == item_template_id_condition)
                            matches_instance_id = (item_id_condition and item_instance_dict.get('id') == item_id_condition)
                            if item_id_condition:
                                if matches_instance_id: found_item_count += item_instance_dict.get('quantity', 0); break
                            elif matches_template: found_item_count += item_instance_dict.get('quantity', 0)
                        if found_item_count >= quantity_condition: met = True
            elif ctype == 'in_location' and lm:
                loc_id_in_cond = data.get('location_id')
                if entity and loc_id_in_cond:
                     entity_location_id = getattr(entity, 'location_id', None)
                     if entity_location_id is not None and str(entity_location_id) == str(loc_id_in_cond): met = True
            elif ctype == 'has_status' and sm:
                status_type_cond = data.get('status_type')
                if entity_id and entity_type and status_type_cond:
                    guild_id_from_context = context.get('guild_id')
                    if guild_id_from_context:
                        guild_statuses_cache = sm._status_effects.get(guild_id_from_context, {})
                        for effect_instance in guild_statuses_cache.values():
                            if (effect_instance.target_id == entity_id and effect_instance.target_type == entity_type and effect_instance.status_type == status_type_cond):
                                met = True; break
            elif ctype == 'stat_check': met = await self.perform_stat_check(entity, data.get('stat'), data.get('threshold'), data.get('operator', '>='), context=context)
            elif ctype == 'is_in_combat' and combat_mgr: met = bool(combat_mgr.get_combat_by_participant_id(entity_id, context=context))
            elif ctype == 'is_leader_of_party' and pm:
                if entity_id and entity_type == 'Character':
                     party_instance = pm.get_party_by_member_id(entity_id, context=context)
                     if party_instance and getattr(party_instance, 'leader_id', None) == entity_id: met = True
            else: logger.warning(f"RuleEngine: Unknown or unhandled condition type '{ctype}'."); return False # Changed print
            if not met: return False
        return True

    async def perform_stat_check(self, entity: Any, stat_name: str, threshold: Any, operator: str = '>=', **context: Any) -> bool:
        entity_stats = getattr(entity, 'stats_json', {}) if isinstance(entity, Character) else getattr(entity, 'stats', {})
        if not isinstance(entity_stats, dict): entity_stats = {}
        stat_value = entity_stats.get(stat_name)
        if stat_value is None: return False
        try:
            stat_value_numeric = float(stat_value); threshold_numeric = float(threshold)
            if operator == '>=': return stat_value_numeric >= threshold_numeric
            elif operator == '>': return stat_value_numeric > threshold_numeric
            elif operator == '<=': return stat_value_numeric <= threshold_numeric
            elif operator == '<': return stat_value_numeric < threshold_numeric
            elif operator == '==': return stat_value_numeric == threshold_numeric
            elif operator == '!=': return stat_value_numeric != threshold_numeric
            else: return False
        except (ValueError, TypeError): return False
        except Exception: return False

    def generate_initial_character_stats(self) -> Dict[str, Any]:
        default_stats = self._rules_data.get("character_stats_rules", {}).get("default_initial_stats", {'strength': 10, 'dexterity': 10, 'constitution': 10, 'intelligence': 10, 'wisdom': 10, 'charisma': 10})
        return default_stats.copy()

    def _calculate_attribute_modifier(self, attribute_value: int) -> int:
        char_stats_rules = self._rules_data.get("character_stats_rules", {})
        formula_str = char_stats_rules.get("attribute_modifier_formula", "(attribute_value - 10) // 2")
        allowed_chars = "attribute_value()+-*/0123456789 "
        if not all(char in allowed_chars for char in formula_str): formula_str = "(attribute_value - 10) // 2"
        try: modifier = eval(formula_str, {"__builtins__": {}}, {"attribute_value": attribute_value}); return int(modifier)
        except Exception: return (attribute_value - 10) // 2

    def get_base_dc(self, relevant_stat_value: int, difficulty_modifier: Optional[str] = None) -> int:
        check_rules = self._rules_data.get("check_rules", {})
        base_dc_config = check_rules.get("base_dc_calculation", {})
        difficulty_modifiers_config = check_rules.get("difficulty_modifiers", {})
        base_dc_value = base_dc_config.get("base_value", 10)
        stat_contribution_formula = base_dc_config.get("stat_contribution_formula", "(relevant_stat_value - 10) // 2")
        stat_contribution = 0
        try: stat_contribution = eval(stat_contribution_formula, {"__builtins__": {}}, {"relevant_stat_value": relevant_stat_value})
        except Exception: stat_contribution = (relevant_stat_value - 10) // 2
        difficulty_mod_value = 0
        if difficulty_modifier: difficulty_mod_value = difficulty_modifiers_config.get(difficulty_modifier.lower(), 0)
        final_dc = base_dc_value + stat_contribution + difficulty_mod_value
        return int(final_dc)

    # --- Skill Check Wrappers ---
    async def resolve_stealth_check(self, character_id: str, guild_id: str, location_id: str, **kwargs: Any) -> CheckResult:
        return await skill_check_resolver.resolve_stealth_check(
            character_manager=self._character_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id,
            guild_id=guild_id, location_id=location_id, **kwargs)

    async def resolve_pickpocket_attempt(self, character_id: str, guild_id: str, target_npc_id: str, **kwargs: Any) -> CheckResult:
        return await skill_check_resolver.resolve_pickpocket_attempt(
            character_manager=self._character_manager, npc_manager=self._npc_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id, guild_id=guild_id,
            target_npc_id=target_npc_id, **kwargs)

    async def resolve_gathering_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any],
                                      character_skills: Dict[str, int], character_inventory: List[Dict[str, Any]],
                                      **kwargs: Any) -> CheckResult:
        return await skill_check_resolver.resolve_gathering_attempt(
            character_manager=self._character_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id, guild_id=guild_id,
            poi_data=poi_data, **kwargs)

    async def resolve_crafting_attempt(self, character_id: str, guild_id: str, recipe_data: Dict[str, Any],
                                       character_skills: Dict[str, int], character_inventory: List[Dict[str, Any]],
                                       current_location_data: Dict[str, Any], **kwargs: Any) -> CheckResult:
        return await skill_check_resolver.resolve_crafting_attempt(
            character_manager=self._character_manager, rules_data=self._rules_data,
            character_id=character_id, guild_id=guild_id, recipe_data=recipe_data,
            current_location_data=current_location_data, **kwargs)

    async def resolve_lockpick_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any], **kwargs: Any) -> CheckResult:
        return await skill_check_resolver.resolve_lockpick_attempt(
            character_manager=self._character_manager, rules_data=self._rules_data,
            resolve_dice_roll_func=self.resolve_dice_roll, character_id=character_id, guild_id=guild_id,
            poi_data=poi_data, **kwargs)

    async def resolve_disarm_trap_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any], **kwargs: Any) -> CheckResult:
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
        return await economic_resolver.calculate_market_price(
            rules_data=self._rules_data, guild_id=guild_id, location_id=location_id,
            item_template_id=item_template_id, quantity=quantity, is_selling_to_market=is_selling_to_market,
            actor_entity_id=actor_entity_id, actor_entity_type=actor_entity_type,
            economy_manager=self._economy_manager, character_manager=self._character_manager,
            location_manager=self._location_manager, relationship_manager=self._relationship_manager,
            npc_manager=self._npc_manager, **kwargs)

    async def process_economy_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        await economic_resolver.process_economy_tick(
            rules_data=self._rules_data, guild_id=guild_id, game_time_delta=game_time_delta,
            economy_manager=self._economy_manager, **kwargs)

    # --- Dialogue Method Wrappers ---
    async def process_dialogue_action(self, dialogue_data: Dict[str, Any], character_id: str, p_action_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
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
    async def choose_combat_action_for_npc(self, npc: "NPC", combat: "Combat", **context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await combat_ai_resolver.choose_combat_action_for_npc(
            rules_data=self._rules_data, npc=npc, combat=combat,
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
        event = context.get('event')
        send_message_callback: Optional[Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]] = context.get('send_message_callback')
        if proc and event and send_message_callback:
            target_stage_id = getattr(stage, 'next_stage_id', None) or stage.get('next_stage_id')
            if target_stage_id:
                 await proc.advance_stage(event=event, target_stage_id=str(target_stage_id), send_message_callback=send_message_callback, **context)

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
                # Operator not recognized for numeric comparison
                return False
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
                # Operator not recognized for numeric comparison
                return False
        except (ValueError, TypeError):
            # Fallback to string comparison for '==' and '!=' if numeric conversion fails
            if operator == '==':
                return str(value1) == str(value2)
            elif operator == '!=':
                return str(value1) != str(value2)
            return False
        except Exception:
            # Consider logging here: logger.error(f"Unexpected error in _compare_values", exc_info=True)
            return False

    async def resolve_dice_roll(self, dice_string: str, pre_rolled_result: Optional[int] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # This method is general and used by many resolvers, so it stays in RuleEngine for now.
        # It will be passed as a function to resolvers that need it.
        dice_string_cleaned = dice_string.lower().strip()
        match = re.fullmatch(r"(\d*)d(\d+)(\s*[+-]\s*\d+)?", dice_string_cleaned)
        if not match:
            match_simple = re.fullmatch(r"d(\d+)(\s*[+-]\s*\d+)?", dice_string_cleaned)
            if match_simple: num_dice_str, sides_str, modifier_str = "1", match_simple.group(1), match_simple.group(2)
            else: raise ValueError(f"Invalid dice string format: {dice_string}")
        else: num_dice_str, sides_str, modifier_str = match.group(1), match.group(2), match.group(3)
        num_dice = int(num_dice_str) if num_dice_str else 1; sides = int(sides_str); modifier = int(modifier_str.replace(" ", "")) if modifier_str else 0
        if sides <= 0: raise ValueError("Dice sides must be positive.")
        if num_dice <= 0: raise ValueError("Number of dice must be positive.")
        rolls = []; roll_total = 0
        for i in range(num_dice):
            if i == 0 and pre_rolled_result is not None:
                if not (1 <= pre_rolled_result <= sides): raise ValueError(f"pre_rolled_result {pre_rolled_result} is not valid for a d{sides}.")
                roll = pre_rolled_result
            else: roll = random.randint(1, sides)
            rolls.append(roll); roll_total += roll
        total_with_modifier = roll_total + modifier
        return {"dice_string": dice_string, "num_dice": num_dice, "sides": sides, "modifier": modifier, "rolls": rolls, "roll_total_raw": roll_total, "total": total_with_modifier, "pre_rolled_input": pre_rolled_result}

logger.debug("RuleEngine: Module defined.") # Changed print to logger
