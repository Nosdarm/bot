# bot/game/rules/rule_engine.py

from __future__ import annotations
import json
import random
import re
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, Tuple, Callable, Awaitable, TYPE_CHECKING, Union

from bot.game.models.check_models import CheckOutcome, DetailedCheckResult
from bot.game.models.status_effect import StatusEffect

if TYPE_CHECKING:
    from bot.game.models.npc import NPC
    from bot.game.models.party import Party
    from bot.game.models.ability import Ability
    from bot.game.models.item import Item
    from bot.game.models.spell import Spell
    from bot.game.models.skill import Skill
    from bot.game.models.rules_config import RulesConfig
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.services.openai_service import OpenAIService
    from bot.game.managers.spell_manager import SpellManager
    from bot.game.managers.skill_manager import SkillManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.models.check_models import DetailedCheckResult as DetailedCheckResultHint

from bot.game.models.character import Character
from bot.game.models.combat import Combat, CombatParticipant
from bot.game.managers.time_manager import TimeManager
import bot.game.rules.combat_rules as combat_rules

print("DEBUG: rule_engine.py module loaded.")

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
                 relationship_manager: Optional["RelationshipManager"] = None
                 ):
        print("Initializing RuleEngine...")
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
        
        if rules_data is not None:
            self._rules_data = rules_data
        else:
            self._rules_data = self._settings.get('game_rules', {})
        
        print("RuleEngine initialized.")

    async def load_rules_data(self) -> None:
        print("RuleEngine: Loading rules data...")
        self._rules_data = self._settings.get('game_rules', {})
        print(f"RuleEngine: Loaded {len(self._rules_data)} rules entries.")

    async def load_state(self, **kwargs: Any) -> None:
         await self.load_rules_data()

    async def save_state(self, **kwargs: Any) -> None:
         print("RuleEngine: Save state method called. (Placeholder - does RuleEngine have state to save?)")
         pass

    def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        print(f"RuleEngine: Rebuilding runtime caches for guild {guild_id}. (Placeholder)")
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
        lm: Optional["LocationManager"] = context.get('location_manager')
        curr = getattr(character or npc, 'location_id', None)
        target = action_context.get('target_location_id')

        if action_type == 'move':
            if curr is not None and target is not None and lm:
                base = float(self._rules_data.get('base_move_duration_per_location', 5.0))
                return base
            print(f"RuleEngine: Warning: Cannot calculate duration for move from {curr} to {target} (lm: {lm is not None}). Returning 0.0.")
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

        print(f"RuleEngine: Warning: Unknown action type '{action_type}' for duration calculation. Returning 0.0.")
        return 0.0

    async def check_conditions(
        self,
        conditions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> bool:
        if not conditions:
            return True
        cm: Optional["CharacterManager"] = context.get('character_manager')
        nm: Optional["NpcManager"] = context.get('npc_manager')
        lm: Optional["LocationManager"] = context.get('location_manager')
        im: Optional["ItemManager"] = context.get('item_manager')
        pm: Optional["PartyManager"] = context.get('party_manager')
        sm: Optional["StatusManager"] = context.get('status_manager')
        combat_mgr: Optional["CombatManager"] = context.get('combat_manager')

        for cond in conditions:
            ctype = cond.get('type')
            data = cond.get('data', {})
            met = False

            entity = context.get('character') or context.get('npc') or context.get('party')
            entity_id = data.get('entity_id') or getattr(entity, 'id', None)
            entity_type = data.get('entity_type') or (type(entity).__name__ if entity else None)

            # print(f"RuleEngine: Checking condition type '{ctype}' for entity '{entity_id}' ({entity_type}) with data: {data}")

            if ctype == 'has_item' and im:
                item_template_id_condition = data.get('item_template_id')
                item_id_condition = data.get('item_id')
                quantity_condition = data.get('quantity', 1)
                if entity_id and entity_type and (item_template_id_condition or item_id_condition):
                    guild_id_from_context = context.get('guild_id')
                    if guild_id_from_context:
                        owned_items = im.get_items_by_owner(guild_id_from_context, entity_id)
                        found_item_count = 0
                        for item_instance_dict in owned_items:
                            matches_template = (item_template_id_condition and
                                                item_instance_dict.get('template_id') == item_template_id_condition)
                            matches_instance_id = (item_id_condition and
                                                   item_instance_dict.get('id') == item_id_condition)
                            if item_id_condition:
                                if matches_instance_id:
                                    found_item_count += item_instance_dict.get('quantity', 0)
                                    break
                            elif matches_template:
                                found_item_count += item_instance_dict.get('quantity', 0)
                        if found_item_count >= quantity_condition:
                            met = True
            elif ctype == 'in_location' and lm:
                loc_id_in_cond = data.get('location_id')
                if entity and loc_id_in_cond:
                     entity_location_id = getattr(entity, 'location_id', None)
                     if entity_location_id is not None and str(entity_location_id) == str(loc_id_in_cond):
                        met = True
            elif ctype == 'has_status' and sm:
                status_type = data.get('status_type')
                if entity_id and entity_type and status_type:
                    guild_id_from_context = context.get('guild_id')
                    if guild_id_from_context:
                        guild_statuses_cache = sm._status_effects.get(guild_id_from_context, {})
                        for effect_instance in guild_statuses_cache.values():
                            if (effect_instance.target_id == entity_id and
                                effect_instance.target_type == entity_type and
                                effect_instance.status_type == status_type):
                                met = True
                                break
            elif ctype == 'stat_check':
                stat_name = data.get('stat')
                threshold = data.get('threshold')
                operator = data.get('operator', '>=')
                if entity and stat_name and threshold is not None and operator:
                    if hasattr(self, 'perform_stat_check'):
                         met = await self.perform_stat_check(entity, stat_name, threshold, operator, context=context)
                    else:
                        return False
            elif ctype == 'is_in_combat' and combat_mgr:
                if entity_id and entity_type:
                    combat_instance = combat_mgr.get_combat_by_participant_id(entity_id, context=context)
                    met = bool(combat_instance)
            elif ctype == 'is_leader_of_party' and pm:
                if entity_id and entity_type == 'Character':
                     party_instance = pm.get_party_by_member_id(entity_id, context=context)
                     if party_instance and getattr(party_instance, 'leader_id', None) == entity_id:
                         met = True
            else:
                print(f"RuleEngine: Warning: Unknown or unhandled condition type '{ctype}'.")
                return False
            if not met:
                # print(f"RuleEngine: Condition '{ctype}' not met for entity '{entity_id}' ({entity_type}).")
                return False
        # print(f"RuleEngine: All conditions met.")
        return True

    async def perform_stat_check(self, entity: Any, stat_name: str, threshold: Any, operator: str = '>=', **context: Any) -> bool:
        entity_stats = getattr(entity, 'stats', {})
        stat_value = entity_stats.get(stat_name)
        if stat_value is None:
            return False
        try:
            stat_value_numeric = float(stat_value)
            threshold_numeric = float(threshold)
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
        if not all(char in allowed_chars for char in formula_str):
            formula_str = "(attribute_value - 10) // 2"
        try:
            modifier = eval(formula_str, {"__builtins__": {}}, {"attribute_value": attribute_value})
            return int(modifier)
        except Exception:
            return (attribute_value - 10) // 2

    def get_base_dc(self, relevant_stat_value: int, difficulty_modifier: Optional[str] = None) -> int:
        check_rules = self._rules_data.get("check_rules", {})
        base_dc_config = check_rules.get("base_dc_calculation", {})
        difficulty_modifiers_config = check_rules.get("difficulty_modifiers", {})
        base_dc_value = base_dc_config.get("base_value", 10)
        stat_contribution_formula = base_dc_config.get("stat_contribution_formula", "(relevant_stat_value - 10) // 2")
        stat_contribution = 0
        try:
            stat_contribution = eval(stat_contribution_formula, {"__builtins__": {}}, {"relevant_stat_value": relevant_stat_value})
        except Exception:
            stat_contribution = (relevant_stat_value - 10) // 2
        difficulty_mod_value = 0
        if difficulty_modifier:
            difficulty_mod_value = difficulty_modifiers_config.get(difficulty_modifier.lower(), 0)
        final_dc = base_dc_value + stat_contribution + difficulty_mod_value
        return int(final_dc)

    async def choose_combat_action_for_npc(
        self, npc: "NPC", combat: "Combat", **context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        cm: Optional["CharacterManager"] = context.get('character_manager')
        nm: Optional["NpcManager"] = context.get('npc_manager')
        cman: Optional["CombatManager"] = context.get('combat_manager')
        guild_id = context.get('guild_id', getattr(npc, 'guild_id', None))

        if not cman or not guild_id:
            print(f"RuleEngine: CombatManager or guild_id missing in context for NPC {npc.id}. Choosing idle.")
            return {'type': 'idle', 'total_duration': None}

        living_participants_in_combat = [
            p for p in combat.participants
            if isinstance(p, CombatParticipant) and p.hp > 0 and p.entity_id != npc.id
        ]

        if not living_participants_in_combat:
            return {'type': 'idle', 'total_duration': None}

        best_target = None
        highest_threat_score = -float('inf')
        base_threat = 10.0 # Default threat

        # Safe builtins for eval
        safe_builtins = {"True": True, "False": False, "None": None, "abs": abs, "min": min, "max": max, "float": float, "int": int}
        eval_globals = {"__builtins__": safe_builtins}

        influence_rules = self._rules_data.get("relationship_influence_rules", [])
        targeting_rules = [rule for rule in influence_rules if rule.get("influence_type") == "npc_targeting"]

        for p_target_obj in living_participants_in_combat:
            current_target_threat_adjustment = 0.0
            relationship_strength = 0.0
            if self._relationship_manager:
                relationship_strength = await self._relationship_manager.get_relationship_strength(
                    guild_id, npc.id, "NPC", p_target_obj.entity_id, p_target_obj.entity_type
                )

            for rule in targeting_rules:
                rule_condition_str = rule.get("condition")
                # Eval context for rule condition
                condition_eval_locals = {
                    "npc": npc.to_dict() if npc else {}, # Provide NPC data
                    "target_entity": p_target_obj.to_dict(), # Provide target data
                    "current_strength": relationship_strength,
                    "combat_context": combat.to_dict() # Provide combat context if needed
                }
                try:
                    condition_met = eval(rule_condition_str, eval_globals, condition_eval_locals) if rule_condition_str else True
                except Exception as e:
                    print(f"RuleEngine: Error evaluating condition for targeting rule '{rule.get('name')}': {e}")
                    condition_met = False

                if condition_met:
                    threshold_type = rule.get("threshold_type")
                    threshold_value = rule.get("threshold_value")
                    threshold_met = True
                    if threshold_type and threshold_value is not None:
                        if threshold_type == "min_strength" and relationship_strength < threshold_value:
                            threshold_met = False
                        elif threshold_type == "max_strength" and relationship_strength > threshold_value:
                            threshold_met = False
                        # Add other threshold types if necessary

                    if threshold_met:
                        bonus_malus_formula = rule.get("bonus_malus_formula")
                        if bonus_malus_formula:
                            # Eval context for bonus/malus formula
                            formula_eval_locals = {
                                "current_strength": relationship_strength,
                                "base_threat": base_threat, # Can be used in formula
                                # Add other relevant data like npc.stats.X, target.level etc.
                                "npc_stats": getattr(npc, 'stats', {}),
                                "target_stats": getattr(p_target_obj, 'stats', {}) # Assuming target might have stats
                            }
                            try:
                                adjustment = float(eval(bonus_malus_formula, eval_globals, formula_eval_locals))
                                current_target_threat_adjustment += adjustment
                            except Exception as e:
                                print(f"RuleEngine: Error evaluating bonus_malus_formula for targeting rule '{rule.get('name')}': {e}")

            final_threat_for_target = base_threat + current_target_threat_adjustment
            if final_threat_for_target > highest_threat_score:
                highest_threat_score = final_threat_for_target
                best_target = p_target_obj

        if best_target:
            return {'type': 'combat_attack', 'target_id': best_target.entity_id, 'target_type': best_target.entity_type, 'attack_type': 'basic_attack'}

        return {'type': 'idle', 'total_duration': None} # Fallback if no suitable target or rule applies

    async def can_rest(self, npc: "NPC", **context: Dict[str, Any]) -> bool:
        cman: Optional["CombatManager"] = context.get('combat_manager')
        if cman and hasattr(cman, 'get_combat_by_participant_id') and cman.get_combat_by_participant_id(npc.id, context=context):
            return False
        return True

    async def handle_stage(self, stage: Any, **context: Dict[str, Any]) -> None:
        proc: Optional["EventStageProcessor"] = context.get('event_stage_processor')
        event = context.get('event')
        send_message_callback: Optional[Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]] = context.get('send_message_callback')
        if proc and event and send_message_callback:
            target_stage_id = getattr(stage, 'next_stage_id', None) or stage.get('next_stage_id')
            if target_stage_id:
                 await proc.advance_stage(
                     event=event, target_stage_id=str(target_stage_id),
                     send_message_callback=send_message_callback, **context
                 )

    def _compare_values(self, value1: Any, value2: Any, operator: str) -> bool:
        try:
            num1 = float(value1); num2 = float(value2)
            if operator == '>=': return num1 >= num2
            elif operator == '>': return num1 > num2
            elif operator == '<=': return num1 <= num2
            elif operator == '<': return num1 < num2
            elif operator == '==': return num1 == num2
            elif operator == '!=': return num1 != num2
            else: return False
        except (ValueError, TypeError):
            if operator == '==' : return str(value1) == str(value2)
            elif operator == '!=': return str(value1) != str(value2)
            return False
        except Exception: return False

    async def choose_peaceful_action_for_npc(
        self, npc: "NPC", **context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        lm: Optional["LocationManager"] = context.get('location_manager')
        cm: Optional["CharacterManager"] = context.get('character_manager')
        dm: Optional["DialogueManager"] = context.get('dialogue_manager')
        guild_id = context.get('guild_id', getattr(npc, 'guild_id', None))

        if not guild_id:
            print(f"RuleEngine: guild_id missing for NPC {npc.id}. Cannot choose action.")
            return {'type': 'idle', 'total_duration': None}

        # Safe builtins for eval
        safe_builtins = {"True": True, "False": False, "None": None, "abs": abs, "min": min, "max": max, "float": float, "int": int}
        eval_globals = {"__builtins__": safe_builtins}

        influence_rules = self._rules_data.get("relationship_influence_rules", [])

        curr_loc = getattr(npc, 'location_id', None)
        if cm and lm and curr_loc and self._relationship_manager:
            chars_in_loc = cm.get_characters_in_location(str(curr_loc), context=context)

            # Sort characters by some priority if multiple are present (e.g. proximity, history - not implemented here)
            # For now, iterate and act on the first character that triggers a rule.

            for ch_candidate in chars_in_loc:
                if not (isinstance(ch_candidate, Character) and ch_candidate.id != npc.id):
                    continue

                relationship_strength = await self._relationship_manager.get_relationship_strength(
                    guild_id, npc.id, "NPC", ch_candidate.id, "Character"
                )

                # Check for hostility rules first
                hostility_rules = [r for r in influence_rules if r.get("influence_type") == "npc_behavior_hostility"]
                for rule in hostility_rules:
                    condition_eval_locals = {"npc": npc.to_dict(), "target_entity": ch_candidate.to_dict(), "current_strength": relationship_strength}
                    try:
                        condition_met = eval(rule.get("condition", "True"), eval_globals, condition_eval_locals)
                    except Exception as e:
                        print(f"RuleEngine: Error evaluating condition for hostility rule '{rule.get('name')}': {e}"); condition_met = False

                    if condition_met:
                        threshold_type = rule.get("threshold_type") # e.g. "max_strength" (becomes hostile if strength IS BELOW this)
                        threshold_value = rule.get("threshold_value")
                        if threshold_type == "max_strength" and relationship_strength < threshold_value:
                            print(f"RuleEngine: NPC {npc.id} relationship with Character {ch_candidate.id} is {relationship_strength:.2f} (below hostile threshold {threshold_value} from rule '{rule.get('name')}'). Initiating combat.")
                            return {'type': 'initiate_combat', 'target_id': ch_candidate.id, 'target_type': 'Character'}
                        # Add other threshold types like "min_strength" if a rule makes NPC hostile above a certain positive value (less common)


                # Check for dialogue initiation rules if not hostile
                if dm: # Ensure DialogueManager is available
                    dialogue_rules = [r for r in influence_rules if r.get("influence_type") == "npc_behavior_dialogue_initiation"]
                    for rule in dialogue_rules:
                        condition_eval_locals = {"npc": npc.to_dict(), "target_entity": ch_candidate.to_dict(), "current_strength": relationship_strength}
                        try:
                            condition_met = eval(rule.get("condition", "True"), eval_globals, condition_eval_locals)
                        except Exception as e:
                            print(f"RuleEngine: Error evaluating condition for dialogue rule '{rule.get('name')}': {e}"); condition_met = False

                        if condition_met:
                            threshold_type = rule.get("threshold_type") # e.g. "min_strength"
                            threshold_value = rule.get("threshold_value")
                            if threshold_type == "min_strength" and relationship_strength >= threshold_value:
                                if hasattr(dm, 'can_start_dialogue') and dm.can_start_dialogue(npc, ch_candidate, context=context):
                                    print(f"RuleEngine: NPC {npc.id} relationship with Character {ch_candidate.id} is {relationship_strength:.2f} (above dialogue threshold {threshold_value} from rule '{rule.get('name')}'). Initiating dialogue.")
                                    return {'type': 'ai_dialogue', 'target_id': ch_candidate.id, 'target_type': 'Character'}
                                # Add other threshold types as needed

        if curr_loc and lm: # Wandering behavior if no interaction occurs
            exits = lm.get_connected_locations(str(curr_loc))
            if exits:
                dest_location_id = None
                if isinstance(exits, dict):
                    if exits: dest_location_id = random.choice(list(exits.values()))
                elif isinstance(exits, list):
                    if exits: dest_location_id = random.choice(exits)
                if dest_location_id:
                    return {'type': 'move', 'target_location_id': dest_location_id}

        return {'type': 'idle', 'total_duration': None}

    async def process_dialogue_action(self, dialogue_data: Dict[str, Any], character_id: str, p_action_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "new_stage_id": None, "is_dialogue_ending": False, "skill_check_result": None,
            "immediate_actions_to_trigger": [], "direct_relationship_changes": [], "messages_to_send": []
        }
        guild_id = str(context.get('guild_id'))
        if not guild_id:
            result["error"] = "Guild ID missing from context."
            return result

        if not (self._dialogue_manager and self._character_manager and self._npc_manager and self._relationship_manager):
            result["error"] = "One or more required managers are not available in RuleEngine."
            return result

        current_stage_id = dialogue_data.get('current_stage_id')
        template_id = dialogue_data.get('template_id')
        dialogue_template = self._dialogue_manager.get_dialogue_template(guild_id, template_id)

        if not dialogue_template or not current_stage_id:
            result["error"] = f"Dialogue template '{template_id}' or current stage '{current_stage_id}' not found."
            return result
        
        current_stage_definition = dialogue_template.get('stages', {}).get(current_stage_id)
        if not current_stage_definition:
            result["error"] = f"Current stage definition '{current_stage_id}' not found in template '{template_id}'."
            return result

        response_id = p_action_data.get('response_id')
        chosen_response_definition = None
        for resp in current_stage_definition.get('player_responses', []):
            if resp.get('id') == response_id:
                chosen_response_definition = resp
                break
        
        if not chosen_response_definition:
            result["error"] = f"Response ID '{response_id}' not found in current stage '{current_stage_id}'."
            return result

        next_node_id = chosen_response_definition.get('next_node_id', 'end') # Default to 'end'

        # Process Skill Check
        skill_check_def = chosen_response_definition.get('skill_check')
        if skill_check_def:
            character_obj = await self._character_manager.get_character(guild_id, character_id)
            if not character_obj:
                result["error"] = f"Character {character_id} not found for skill check."
                return result

            npc_id = None
            # Correctly extract npc_id from participants list of dicts
            for p_data_entry in dialogue_data.get('participants', []):
                if isinstance(p_data_entry, dict) and p_data_entry.get('entity_id') != character_id and p_data_entry.get('entity_type') == "NPC":
                    npc_id = p_data_entry.get('entity_id')
                    break
                elif isinstance(p_data_entry, str) and p_data_entry != character_id: # Legacy: list of IDs, assume other is NPC
                    # This path is less robust as it assumes the other is an NPC
                    pass # npc_id = p_data_entry # This was commented out, if participants are just IDs, this might be needed.
            
            npc_obj = await self._npc_manager.get_npc(guild_id, npc_id) if npc_id else None
            if not npc_obj: # NPC is crucial for DC calculation if formula involves npc_stats or relationship bonus
                result["error"] = f"NPC partner in dialogue (ID: {npc_id}) not found for skill check."
                # If no NPC, can't calculate relationship-based DC or NPC stat based DC.
                # Fallback to a default DC or fail the check? For now, let's make DC very high or return error.
                # This depends on how skill checks against non-NPCs or environment are handled.
                # For this subtask, skill checks are against an NPC in dialogue.
                return result


            skill_type = skill_check_def.get('type')
            dc_formula_str = str(skill_check_def.get('dc_formula', '15'))
            
            base_dc = 15 # Default
            try: base_dc = int(dc_formula_str)
            except ValueError:
                if "npc_stats." in dc_formula_str:
                    stat_name_match = re.search(r"npc_stats\.(\w+)", dc_formula_str)
                    if stat_name_match and npc_obj: # Check npc_obj here
                        stat_name = stat_name_match.group(1)
                        npc_stat_val = getattr(npc_obj, 'stats', {}).get(stat_name, 10)
                        offset_match = re.search(r"([+\-])\s*(\d+)", dc_formula_str)
                        offset = 0
                        if offset_match:
                            op, val_str_offset = offset_match.group(1), offset_match.group(2)
                            val_offset = int(val_str_offset)
                            if op == '+': offset = val_offset
                            elif op == '-': offset = -val_offset
                        base_dc = npc_stat_val + offset
            
            relationship_bonus = 0.0
            feedback_key_skill_check = None
            feedback_params_skill_check = {}

            # Safe builtins for eval
            safe_builtins = {"True": True, "False": False, "None": None, "abs": abs, "min": min, "max": max, "float": float, "int": int}
            eval_globals = {"__builtins__": safe_builtins}

            rules_ref_name = skill_check_def.get('relationship_bonus_rules_ref') # This is the name of the RelationshipInfluenceRule
            if rules_ref_name and self._relationship_manager and self._rules_data and npc_obj:
                rel_strength = await self._relationship_manager.get_relationship_strength(guild_id, character_id, "Character", npc_obj.id, "NPC")

                all_influence_rules = self._rules_data.get("relationship_influence_rules", [])
                found_rule = None
                for r_rule in all_influence_rules:
                    if r_rule.get("name") == rules_ref_name and r_rule.get("influence_type") == "dialogue_skill_check": # Ensure correct type
                        found_rule = r_rule
                        break

                if found_rule:
                    # Evaluate condition of the found rule
                    rule_condition_str = found_rule.get("condition")
                    condition_eval_locals = {
                        "character": character_obj.to_dict(),
                        "npc": npc_obj.to_dict(),
                        "current_strength": rel_strength,
                        "dialogue_data": dialogue_data # Make current dialogue state available
                    }
                    try:
                        condition_met = eval(rule_condition_str, eval_globals, condition_eval_locals) if rule_condition_str else True
                    except Exception as e:
                        print(f"RuleEngine: Error evaluating condition for dialogue skill check rule '{found_rule.get('name')}': {e}"); condition_met = False

                    if condition_met:
                        threshold_type = found_rule.get("threshold_type")
                        threshold_value = found_rule.get("threshold_value")
                        threshold_met = True
                        if threshold_type and threshold_value is not None:
                            if threshold_type == "min_strength" and rel_strength < threshold_value: threshold_met = False
                            elif threshold_type == "max_strength" and rel_strength > threshold_value: threshold_met = False
                            # Add other threshold checks as needed

                        if threshold_met:
                            bonus_malus_formula = found_rule.get("bonus_malus_formula")
                            if bonus_malus_formula:
                                formula_eval_locals = {"current_strength": rel_strength, "character_stats": character_obj.stats, "npc_stats": npc_obj.stats}
                                try:
                                    relationship_bonus = float(eval(bonus_malus_formula, eval_globals, formula_eval_locals))
                                except Exception as e:
                                    print(f"RuleEngine: Error evaluating bonus_malus_formula for rule '{found_rule.get('name')}': {e}")

                            feedback_key_skill_check = found_rule.get("effect_description_i18n_key")
                            # Prepare params for i18n
                            raw_params_map = found_rule.get("effect_params_mapping", {})
                            for param_key, context_path_str in raw_params_map.items():
                                # Resolve context_path_str against available data (char, npc, calculated bonus etc.)
                                # Example: "npc.name" -> npc_obj.name, "calculated_bonus" -> relationship_bonus
                                if context_path_str == "npc.name": feedback_params_skill_check[param_key] = getattr(npc_obj, 'name', npc_obj.id)
                                elif context_path_str == "character.name": feedback_params_skill_check[param_key] = getattr(character_obj, 'name', character_obj.id)
                                elif context_path_str == "calculated_bonus": feedback_params_skill_check[param_key] = f"{'+' if relationship_bonus >= 0 else ''}{relationship_bonus:.0f}" # Format as needed
                                # Add more complex path resolution if needed, e.g. eval(context_path_str, globals, locals)
            
            final_dc = int(base_dc - relationship_bonus) # Bonus reduces DC, penalty increases it

            check_success, total_roll, d20_roll, crit_status = await self.resolve_skill_check(
                character_obj, skill_type, final_dc, context=context
            )
            result['skill_check_result'] = {
                "type": skill_type, "dc": final_dc, "roll": d20_roll,
                "total": total_roll, "success": check_success, "crit_status": crit_status,
                "relationship_bonus_applied": relationship_bonus,
                "feedback_key": feedback_key_skill_check,
                "feedback_params": feedback_params_skill_check
            }
            next_node_id = skill_check_def['success_node_id'] if check_success else skill_check_def['failure_node_id']
        
        result['new_stage_id'] = next_node_id
        result['is_dialogue_ending'] = (next_node_id == "end" or next_node_id in dialogue_template.get('end_stages', ['end']))

        if chosen_response_definition.get('action'):
            result['immediate_actions_to_trigger'].append(chosen_response_definition['action'])
        
        rel_effects = chosen_response_definition.get('relationship_effects')
        if isinstance(rel_effects, list):
            result['direct_relationship_changes'].extend(rel_effects)
        elif isinstance(rel_effects, dict):
             result['direct_relationship_changes'].append(rel_effects)

        return result

    async def get_filtered_dialogue_options(
        self, 
        dialogue_data: Dict[str, Any],
        character_id: str,
        stage_definition: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Filters dialogue options based on relationship prerequisites.
        Marks options as unavailable if prerequisites are not met.
        """
        guild_id = str(context.get('guild_id'))
        if not guild_id:
            # print("RuleEngine.get_filtered_dialogue_options: Guild ID missing from context. Returning all options.")
            return stage_definition.get('player_responses', [])

        if not self._relationship_manager:
            # print("RuleEngine.get_filtered_dialogue_options: RelationshipManager not available. Returning all options.")
            return stage_definition.get('player_responses', [])

        available_options = []
        all_responses = stage_definition.get('player_responses', [])

        # Safe builtins for eval
        safe_builtins = {"True": True, "False": False, "None": None, "abs": abs, "min": min, "max": max, "float": float, "int": int, "str": str}
        eval_globals = {"__builtins__": safe_builtins}

        npc_id = None
        npc_type = "NPC"
        npc_obj_dict = {} # For eval context
        character_obj = await self._character_manager.get_character(guild_id, character_id) if self._character_manager else None
        char_obj_dict = character_obj.to_dict() if character_obj else {}

        participants = dialogue_data.get('participants', [])
        for p_data_entry in participants:
            p_entity_id = p_data_entry.get('entity_id') if isinstance(p_data_entry, dict) else str(p_data_entry)
            if p_entity_id != character_id:
                npc_id = p_entity_id
                if isinstance(p_data_entry, dict): npc_type = p_data_entry.get('entity_type', "NPC")
                if self._npc_manager and npc_id:
                    npc_instance = await self._npc_manager.get_npc(guild_id, npc_id)
                    if npc_instance: npc_obj_dict = npc_instance.to_dict()
                break
        
        current_strength_with_npc = 0.0
        if npc_id:
            current_strength_with_npc = await self._relationship_manager.get_relationship_strength(
                guild_id, character_id, "Character", npc_id, npc_type
            )

        influence_rules = self._rules_data.get("relationship_influence_rules", [])
        dialogue_availability_rules = [
            rule for rule in influence_rules if rule.get("influence_type") == "dialogue_option_availability"
        ]

        for option_def in all_responses:
            option_copy = option_def.copy()
            option_copy['is_available'] = True # Default to available
            option_copy['failure_feedback_key'] = None
            option_copy['failure_feedback_params'] = {}

            # An option might need to reference which rule(s) specifically control its availability,
            # if not all "dialogue_option_availability" rules apply to all options.
            # For now, assume rules are general or use their own 'condition' field to target options.
            # Example: rule.condition could be "option_data.get('id') == 'specific_option_id'"
            # This requires passing option_copy into rule condition evaluation context.

            for rule in dialogue_availability_rules:
                rule_condition_str = rule.get("condition")
                condition_eval_locals = {
                    "character": char_obj_dict,
                    "npc": npc_obj_dict,
                    "current_strength": current_strength_with_npc, # Strength with the main NPC in dialogue
                    "dialogue_data": dialogue_data,
                    "option_data": option_copy # Make the current option being evaluated available
                }
                try:
                    rule_applies = eval(rule_condition_str, eval_globals, condition_eval_locals) if rule_condition_str else True
                except Exception as e:
                    print(f"RuleEngine: Error evaluating condition for dialogue availability rule '{rule.get('name')}': {e}"); rule_applies = False

                if rule_applies:
                    threshold_type = rule.get("threshold_type")
                    threshold_value = rule.get("threshold_value")
                    threshold_met = True # Assume met if no threshold defined in rule

                    threshold_condition_present = threshold_type and threshold_value is not None

                    threshold_met = True # Default if no threshold defined in rule for it to apply
                    if threshold_condition_present:
                        # Evaluate actual threshold
                        if threshold_type == "min_strength" and current_strength_with_npc < threshold_value: threshold_met = False
                        elif threshold_type == "max_strength" and current_strength_with_npc > threshold_value: threshold_met = False
                        # Add other types like "equal_to", "not_equal_to" if needed

                    # Logic based on availability_flag and whether threshold was met
                    if rule.get("availability_flag") is True:
                        # This rule is meant to make an option AVAILABLE if conditions/thresholds are met.
                        # If it has a threshold that is NOT met, then the option becomes UNAVAILABLE.
                        if threshold_condition_present and not threshold_met:
                            option_copy['is_available'] = False
                            option_copy['failure_feedback_key'] = rule.get("failure_feedback_key")
                            raw_params_map = rule.get("failure_feedback_params_mapping", {})
                            for param_key, context_path_str in raw_params_map.items():
                                if context_path_str == "npc.name": option_copy['failure_feedback_params'][param_key] = npc_obj_dict.get('name', npc_id)
                                elif context_path_str == "character.name": option_copy['failure_feedback_params'][param_key] = char_obj_dict.get('name', character_id)
                                elif context_path_str == "threshold_value": option_copy['failure_feedback_params'][param_key] = str(threshold_value)
                                elif context_path_str == "current_strength": option_copy['failure_feedback_params'][param_key] = f"{current_strength_with_npc:.1f}"
                            break # This rule (an enabling one with unmet threshold) blocks it.
                        # If threshold_condition_present AND threshold_met, or if no threshold_condition_present,
                        # this enabling rule doesn't make it unavailable. It remains available (its default state).

                    elif rule.get("availability_flag") is False:
                        # This rule is meant to make an option UNAVAILABLE if conditions/thresholds are met.
                        if threshold_met: # If condition/threshold for *disabling* is met
                            option_copy['is_available'] = False
                            option_copy['failure_feedback_key'] = rule.get("failure_feedback_key")
                            raw_params_map = rule.get("failure_feedback_params_mapping", {})
                            for param_key, context_path_str in raw_params_map.items():
                                if context_path_str == "npc.name": option_copy['failure_feedback_params'][param_key] = npc_obj_dict.get('name', npc_id)
                                elif context_path_str == "character.name": option_copy['failure_feedback_params'][param_key] = char_obj_dict.get('name', character_id)
                                elif context_path_str == "threshold_value": option_copy['failure_feedback_params'][param_key] = str(threshold_value)
                                elif context_path_str == "current_strength": option_copy['failure_feedback_params'][param_key] = f"{current_strength_with_npc:.1f}"
                            break # This rule (a disabling one with met threshold) blocks it.

            available_options.append(option_copy)
        
        return available_options


    # --- Existing methods below this line are assumed to be complete as per previous tasks ---
    # (resolve_dice_roll, resolve_steal_attempt, resolve_hide_attempt, resolve_item_use,
    #  check_spell_learning_requirements, _resolve_dice_roll (internal), process_spell_effects,
    #  check_ability_learning_requirements, process_ability_effects, resolve_skill_check,
    #  resolve_attack_roll, calculate_damage, process_entity_death, check_combat_end_conditions,
    #  get_game_time, award_experience, check_for_level_up, apply_combat_action_effects,
    #  calculate_initiative, apply_equipment_effects, resolve_saving_throw, _get_entity_data_for_check,
    #  _resolve_single_entity_check_roll)

print("DEBUG: rule_engine.py module defined.")


