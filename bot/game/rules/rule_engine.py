# bot/game/rules/rule_engine.py

from __future__ import annotations
import json
import random
import re
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, Tuple, Callable, Awaitable, TYPE_CHECKING, Union

from bot.game.models.check_models import CheckResult # MODIFIED
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
    # DetailedCheckResultHint REMOVED

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

    # --- New Stealth and Thievery Skill Check Methods ---

    async def resolve_stealth_check(
        self,
        character_id: str,
        guild_id: str,
        location_id: str,
        # npc_ids_in_location: List[str], # Future: for opposed checks
        **kwargs: Any
    ) -> CheckResult:
        """
        Resolves a stealth check for a character.
        Considers character's stealth skill and location-based factors.
        """
        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return CheckResult(succeeded=False, description="Character not found.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

        skills_data = character.skills_data_json or {}
        stealth_skill = skills_data.get("stealth", 0)

        # Get stealth rules from self._rules_data
        stealth_rules = self._rules_data.get("stealth_rules", {})
        base_dc = stealth_rules.get("base_detection_dc", 15) # Default DC if no NPCs or specific location awareness
        # Location awareness modifier (conceptual)
        # location = await self._location_manager.get_location(guild_id, location_id)
        # awareness_modifier = location.state_variables.get("awareness_level", 0) if location else 0
        # current_dc = base_dc + awareness_modifier
        current_dc = base_dc # Simplified for now

        # TODO: Opposed checks against NPCs perception
        # For now, simple check against location DC

        success, total_roll, d20_roll, crit_status = await self.resolve_skill_check(
            character, "stealth", current_dc, context=kwargs
        )

        # awareness_level_change = 0
        # consequences = []
        # if not success:
        #     awareness_level_change = stealth_rules.get("awareness_increase_on_fail", 1)
        #     consequences.append("Detected by someone or something.")

        return DetailedCheckResult(
            success=success,
            message=f"Stealth check {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}",
            roll_details={"skill": "stealth", "roll": d20_roll, "total_roll": total_roll, "dc": current_dc, "crit_status": crit_status},
            # custom_outcomes={
            #     "awareness_level_change": awareness_level_change,
            #     "consequences": consequences
            # }
            # Mapping to CheckResult:
            succeeded=success, # from original
            roll_value=d20_roll, # from roll_details.roll
            modifier_applied=total_roll - d20_roll, # Calculated, placeholder for actual sum of modifiers
            total_roll_value=total_roll, # from roll_details.total_roll
            dc_value=current_dc, # from roll_details.dc
            description=f"Stealth check {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}", # from original message
            details_log={"skill_type": "stealth", "crit_status": crit_status} # from roll_details, skill_type mapped from "skill"
        )

    async def resolve_pickpocket_attempt(
        self,
        character_id: str,
        guild_id: str,
        target_npc_id: str,
        # item_to_steal_id: Optional[str] = None, # Future: item difficulty
        **kwargs: Any
    ) -> CheckResult:
        """
        Resolves a pickpocket attempt by a character on an NPC.
        """
        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return CheckResult(succeeded=False, description="Character not found for pickpocket.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

        target_npc = await self._npc_manager.get_npc(guild_id, target_npc_id)
        if not target_npc:
            return CheckResult(succeeded=False, description="Target NPC not found for pickpocket.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Target NPC not found."})

        skills_data = character.skills_data_json or {}
        pickpocket_skill = skills_data.get("pickpocket", 0)

        pickpocket_rules = self._rules_data.get("pickpocket_rules", {})
        base_dc = pickpocket_rules.get("base_dc", 12)
        npc_perception_modifier = 0 # Simplified, could be based on target_npc.stats.perception or awareness

        # item_difficulty_modifier = 0 # Future
        # if item_to_steal_id:
        #     item = await self._item_manager.get_item_template(item_to_steal_id) # or get instance
        #     item_difficulty_modifier = item.difficulty_class if item else 0

        current_dc = base_dc + npc_perception_modifier # + item_difficulty_modifier

        success, total_roll, d20_roll, crit_status = await self.resolve_skill_check(
            character, "pickpocket", current_dc, context=kwargs
        )

        detected = False
        item_id_stolen = None

        if not success:
            detected = True # Simple assumption: failure means detection
            # Critical failure might have worse consequences (e.g. hostility)
            if crit_status == "critical_failure":
                detected = True # Already true, but could add more effects
                # consequences.append("NPC becomes hostile!")
        # else:
            # item_id_stolen = "some_item_id" # TODO: Logic to determine what item is stolen

        return DetailedCheckResult(
            success=success,
            message=f"Pickpocket attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}",
            roll_details={"skill": "pickpocket", "roll": d20_roll, "total_roll": total_roll, "dc": current_dc, "crit_status": crit_status},
            custom_outcomes={
                "detected": detected,
                "item_id_stolen": item_id_stolen if success else None
            }
            # Mapping to CheckResult:
            succeeded=success,
            roll_value=d20_roll, # from roll_details.roll
            modifier_applied=total_roll - d20_roll, # Calculated placeholder
            total_roll_value=total_roll, # from roll_details.total_roll
            dc_value=current_dc, # from roll_details.dc
            description=f"Pickpocket attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}", # from original message
            details_log={
                "skill_type": "pickpocket", # from roll_details.skill
                "crit_status": crit_status, # from roll_details.crit_status
                "detected": detected, # from custom_outcomes
                "item_id_stolen": item_id_stolen if success else None # from custom_outcomes
            }
        )

    # --- New Crafting and Gathering Skill Check Methods ---

    async def resolve_gathering_attempt(
        self,
        character_id: str,
        guild_id: str,
        poi_data: Dict[str, Any],
        character_skills: Dict[str, int],
        character_inventory: List[Dict[str, Any]], # List of item dicts
        **kwargs: Any
    ) -> CheckResult:
        """
        Resolves a gathering attempt from a resource node PoI.
        """
        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return CheckResult(succeeded=False, description="error_character_not_found", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "error_character_not_found"})

        resource_details = poi_data.get("resource_details")
        if not resource_details:
            return CheckResult(succeeded=False, description="gathering_fail_invalid_node_data", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "gathering_fail_invalid_node_data"})

        gathering_skill_id = resource_details.get("gathering_skill_id")
        gathering_dc = resource_details.get("gathering_dc", 15)
        required_tool_category = resource_details.get("required_tool_category")
        base_yield_formula = resource_details.get("base_yield_formula", "1")
        primary_resource_id = resource_details.get("resource_item_template_id")

        secondary_resource_id = resource_details.get("secondary_resource_item_template_id")
        secondary_yield_formula = resource_details.get("secondary_resource_yield_formula", "1")
        secondary_chance = resource_details.get("secondary_resource_chance", 0.0)

        if not primary_resource_id or not gathering_skill_id:
            return CheckResult(succeeded=False, description="gathering_fail_incomplete_node_data", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc if 'gathering_dc' in locals() else None, details_log={"reason": "gathering_fail_incomplete_node_data", "skill_type": gathering_skill_id if 'gathering_skill_id' in locals() else "unknown"})

        # 1. Tool Check
        if required_tool_category:
            has_required_tool = False
            # This assumes items in inventory have a "tags" list or a "category" field.
            # For MVP, let's assume a simple check for an item with a 'name' or 'id' that matches the category for simplicity,
            # or more realistically, that items have a `tool_category` property if they are tools.
            # The subtask says "The system will check if the player has any item of this category".
            # We need to define how item categories are stored on items.
            # Assuming item dicts in character_inventory have 'properties: {"tool_category": "pickaxe"}' or similar.
            for item_dict in character_inventory:
                item_properties = item_dict.get("properties", {})
                if isinstance(item_properties, dict) and item_properties.get("tool_category") == required_tool_category:
                    has_required_tool = True
                    break
            if not has_required_tool:
                return CheckResult(succeeded=False, description=f"gathering_fail_no_tool_{required_tool_category}", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc, details_log={"skill_type": gathering_skill_id, "required_tool_category": required_tool_category})

        # 2. Skill Check
        # We need the Character object for resolve_skill_check
        success, total_roll, d20_roll, crit_status = await self.resolve_skill_check(
            character, gathering_skill_id, gathering_dc, context=kwargs
        )

        if not success:
            return CheckResult(
                succeeded=False,
                description=f"gathering_fail_skill_check_{gathering_skill_id}", # Using message_key
                roll_value=d20_roll,
                modifier_applied=total_roll - d20_roll, # Placeholder
                total_roll_value=total_roll,
                dc_value=gathering_dc,
                details_log={"skill_type": gathering_skill_id, "crit_status": crit_status} # Mapped from roll_details
            )

        # 3. Calculate Yield
        yielded_items = []
        try:
            primary_yield_roll = await self.resolve_dice_roll(base_yield_formula)
            primary_quantity = primary_yield_roll.get("total", 0)
            if primary_quantity > 0:
                yielded_items.append({"item_template_id": primary_resource_id, "quantity": primary_quantity})

            if secondary_resource_id and random.random() < secondary_chance:
                secondary_yield_roll = await self.resolve_dice_roll(secondary_yield_formula)
                secondary_quantity = secondary_yield_roll.get("total", 0)
                if secondary_quantity > 0:
                    yielded_items.append({"item_template_id": secondary_resource_id, "quantity": secondary_quantity})

        except ValueError as e: # Invalid dice string
             # Log error, potentially yield 0 or a default amount
            print(f"Error resolving dice roll for gathering: {e}")
            return CheckResult(succeeded=False, description="gathering_fail_yield_calculation_error", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc, details_log={"reason": "gathering_fail_yield_calculation_error", "skill_type": gathering_skill_id, "error": str(e)})

        details_log_data = {
            "skill_type": gathering_skill_id, # from roll_details
            "crit_status": crit_status, # from roll_details
            "yielded_items": yielded_items # from custom_outcomes
        }
        return CheckResult(
            succeeded=True,
            roll_value=d20_roll,
            modifier_applied=total_roll - d20_roll, # Placeholder
            total_roll_value=total_roll,
            dc_value=gathering_dc,
            description=f"gathering_success_{gathering_skill_id}", # Using message_key
            details_log=details_log_data
        )

    async def resolve_crafting_attempt(
        self,
        character_id: str,
        guild_id: str,
        recipe_data: Dict[str, Any],
        character_skills: Dict[str, int],
        character_inventory: List[Dict[str, Any]], # List of item dicts, each with 'template_id' and 'quantity'
        current_location_data: Dict[str, Any], # Contains 'tags' list and 'properties' like 'station_type'
        **kwargs: Any
    ) -> CheckResult:
        """
        Resolves a crafting attempt based on a recipe. (MVP: Requirement checks only)
        """
        # Ensure managers are available if direct character object is needed
        if not self._character_manager: # Or any other required manager
            return CheckResult(succeeded=False, description="error_internal_server_error", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"details": "CharacterManager not available"})

        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return CheckResult(succeeded=False, description="error_character_not_found", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"reason": "error_character_not_found"})

        recipe_id = recipe_data.get("id", "unknown_recipe")
        ingredients = recipe_data.get("ingredients_json", []) # List of {"item_template_id": "x", "quantity": y}
        outputs = recipe_data.get("outputs_json", []) # List of {"item_template_id": "x", "quantity": y}
        required_skill_id = recipe_data.get("required_skill_id")
        required_skill_level = recipe_data.get("required_skill_level", 0)

        other_requirements = recipe_data.get("other_requirements_json", {})
        required_tools_specific = other_requirements.get("required_tools", []) # list of item_template_ids
        required_crafting_station = other_requirements.get("crafting_station_type")
        required_location_tags = other_requirements.get("required_location_tags", [])
        # requires_event_flag = other_requirements.get("requires_event_flag") # Not checked in MVP

        # 1. Skill Level Check
        if required_skill_id and character_skills.get(required_skill_id, 0) < required_skill_level:
            return CheckResult(succeeded=False, description="crafting_fail_skill_too_low", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_skill": required_skill_id, "required_level": required_skill_level})

        # 2. Ingredient Check
        consumed_items_for_outcome = []
        inventory_map = {item['template_id']: item['quantity'] for item in character_inventory}
        for ingredient in ingredients:
            ing_id = ingredient["item_template_id"]
            ing_qty = ingredient["quantity"]
            if inventory_map.get(ing_id, 0) < ing_qty:
                return CheckResult(succeeded=False, description="crafting_fail_missing_ingredients", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "missing_item_id": ing_id, "required_quantity": ing_qty})
            consumed_items_for_outcome.append({"item_template_id": ing_id, "quantity": ing_qty})

        # 3. Specific Tool Check (player must have specific items)
        if required_tools_specific:
            for tool_template_id in required_tools_specific:
                if not any(item['template_id'] == tool_template_id for item in character_inventory):
                    return CheckResult(succeeded=False, description="crafting_fail_missing_specific_tool", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "missing_tool_id": tool_template_id})

        # 4. Crafting Station Check
        if required_crafting_station:
            # Location data needs a way to specify its station type. Assume current_location_data has a "station_type" or similar.
            # For example, from a PoI that is a crafting station: current_location_data.get("active_poi_station_type")
            # Or, location itself has a station type: current_location_data.get("properties", {}).get("station_type")
            location_station_type = current_location_data.get("properties", {}).get("station_type") # Example access
            if location_station_type != required_crafting_station:
                 return CheckResult(succeeded=False, description="crafting_fail_wrong_station", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_station": required_crafting_station, "current_station": location_station_type or "none"})

        # 5. Location Tags Check
        if required_location_tags:
            location_tags = current_location_data.get("tags", []) # Assuming location has a 'tags' list
            if not all(tag in location_tags for tag in required_location_tags):
                return CheckResult(succeeded=False, description="crafting_fail_location_tags", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_tags": required_location_tags})

        # MVP: If all checks pass, crafting is successful.
        # Future: Add skill check roll against recipe DC for success chance/quality.

        # For MVP, assume first output is the primary.
        crafted_item_details = outputs[0] if outputs else None
        if not crafted_item_details:
            return CheckResult(succeeded=False, description="crafting_fail_no_output_defined", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id})

        details_log_data = {
            "recipe_id": recipe_id,
            "crafted_item": crafted_item_details,
            "consumed_items": consumed_items_for_outcome
            # "xp_gained": calculated_xp (future)
        }
        return CheckResult(
            succeeded=True,
            description="crafting_success", # Using message_key
            roll_value=0, # No dice roll in current crafting MVP
            modifier_applied=0, # No dice roll
            total_roll_value=0, # No dice roll
            details_log=details_log_data
            # dc_value can be omitted (it's Optional)
        )

    async def resolve_lockpick_attempt(
        self,
        character_id: str,
        guild_id: str,
        poi_data: Dict[str, Any], # Point of Interest data containing lock details
        **kwargs: Any
    ) -> CheckResult:
        """
        Resolves a lockpicking attempt by a character on a lock (part of a PoI).
        """
        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return CheckResult(succeeded=False, description="Character not found for lockpicking.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

        skills_data = character.skills_data_json or {}
        lockpicking_skill = skills_data.get("lockpicking", 0)

        lock_details = poi_data.get("lock_details", {}) # As per documentation plan
        lock_dc = lock_details.get("dc", 15) # Default if not specified in PoI

        # lockpicking_rules = self._rules_data.get("lockpicking_rules", {})
        # tool_quality_modifier = 0 # Future enhancement
        # multiple_attempts_penalty = 0 # Future

        current_dc = lock_dc # + tool_quality_modifier + multiple_attempts_penalty

        success, total_roll, d20_roll, crit_status = await self.resolve_skill_check(
            character, "lockpicking", current_dc, context=kwargs
        )

        # tool_broken = False # Future
        # if crit_status == "critical_failure" and lockpicking_rules.get("break_tools_on_crit_fail", False):
        #     tool_broken = True

        return DetailedCheckResult(
            success=success,
            message=f"Lockpicking attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}",
            roll_details={"skill": "lockpicking", "roll": d20_roll, "total_roll": total_roll, "dc": current_dc, "crit_status": crit_status},
            # custom_outcomes={
            #     "tool_broken": tool_broken,
            #     "attempts_used": 1 # Simplified
            # }
            # Mapping to CheckResult:
            succeeded=success,
            roll_value=d20_roll, # from roll_details.roll
            modifier_applied=total_roll - d20_roll, # Calculated placeholder
            total_roll_value=total_roll, # from roll_details.total_roll
            dc_value=current_dc, # from roll_details.dc
            description=f"Lockpicking attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}", # from original message
            details_log={
                "skill_type": "lockpicking", # from roll_details.skill
                "crit_status": crit_status # from roll_details.crit_status
                # custom_outcomes fields like tool_broken would go here if they were active
            }
        )

    async def resolve_disarm_trap_attempt(
        self,
        character_id: str,
        guild_id: str,
        poi_data: Dict[str, Any], # Point of Interest data containing trap details
        **kwargs: Any
    ) -> CheckResult:
        """
        Resolves a trap disarming attempt by a character.
        """
        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return CheckResult(succeeded=False, description="Character not found for disarming trap.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

        skills_data = character.skills_data_json or {}
        disarm_skill = skills_data.get("disarm_traps", 0)

        trap_details = poi_data.get("trap_details") # As per documentation plan
        if not trap_details:
            return CheckResult(succeeded=False, description="Trap details not found in PoI data.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Trap details not found."})

        disarm_dc = trap_details.get("disarm_dc", 15) # Default if not specified

        # disarm_rules = self._rules_data.get("disarm_trap_rules", {})

        success, total_roll, d20_roll, crit_status = await self.resolve_skill_check(
            character, "disarm_traps", disarm_dc, context=kwargs
        )

        trap_triggered_on_fail = False
        if not success:
            # Check for critical failure triggering the trap
            # if crit_status == "critical_failure" and disarm_rules.get("trigger_on_crit_fail", True):
            #     trap_triggered_on_fail = True
            # elif disarm_rules.get("trigger_on_any_fail", False): # Simpler rule: any failure triggers
            #     trap_triggered_on_fail = True
            trap_triggered_on_fail = True # Simplified: any failure triggers for now

        return DetailedCheckResult(
            success=success,
            message=f"Disarm trap attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {disarm_dc}",
            roll_details={"skill": "disarm_traps", "roll": d20_roll, "total_roll": total_roll, "dc": disarm_dc, "crit_status": crit_status},
            custom_outcomes={
                "trap_triggered_on_fail": trap_triggered_on_fail
            }
            # Mapping to CheckResult:
            succeeded=success,
            roll_value=d20_roll, # from roll_details.roll
            modifier_applied=total_roll - d20_roll, # Calculated placeholder
            total_roll_value=total_roll, # from roll_details.total_roll
            dc_value=disarm_dc, # from roll_details.dc
            description=f"Disarm trap attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {disarm_dc}", # from original message
            details_log={
                "skill_type": "disarm_traps", # from roll_details.skill
                "crit_status": crit_status, # from roll_details.crit_status
                "trap_triggered_on_fail": trap_triggered_on_fail # from custom_outcomes
            }
        )

    # --- Existing methods below this line are assumed to be complete as per previous tasks ---
    # (resolve_dice_roll, resolve_steal_attempt, resolve_hide_attempt, resolve_item_use,
    #  check_spell_learning_requirements, _resolve_dice_roll (internal), process_spell_effects,
    #  check_ability_learning_requirements, process_ability_effects, resolve_skill_check,
    #  resolve_attack_roll, calculate_damage, process_entity_death, check_combat_end_conditions,
    #  get_game_time, award_experience, check_for_level_up, apply_combat_action_effects,
    #  calculate_initiative, apply_equipment_effects, resolve_saving_throw, _get_entity_data_for_check,
    #  _resolve_single_entity_check_roll)

    async def calculate_market_price(
        self,
        guild_id: str,
        location_id: str,
        item_template_id: str,
        quantity: float,
        is_selling_to_market: bool, # Player is selling to NPC/market
        actor_entity_id: str,
        actor_entity_type: str, # e.g. "Character"
        **kwargs: Any
    ) -> Optional[float]:
        """
        Calculates the market price for an item considering various economic factors.
        """
        print(f"RuleEngine: calculate_market_price: Called for item '{item_template_id}' (qty: {quantity}) in loc '{location_id}', player selling: {is_selling_to_market}, actor: {actor_entity_id} ({actor_entity_type})")

        economy_rules = self._rules_data.get("economy_rules")
        if not economy_rules:
            print("RuleEngine: calculate_market_price: ERROR - 'economy_rules' not found in rules_data.")
            return None

        item_definitions = self._rules_data.get("item_definitions")
        if not item_definitions:
            print("RuleEngine: calculate_market_price: ERROR - 'item_definitions' not found in rules_data.")
            return None

        item_def = item_definitions.get(str(item_template_id))
        if not item_def:
            print(f"RuleEngine: calculate_market_price: ERROR - Item template '{item_template_id}' not found in item_definitions.")
            return None

        base_price = item_def.get("base_price")
        if base_price is None or not isinstance(base_price, (int, float)) or base_price < 0:
            print(f"RuleEngine: calculate_market_price: ERROR - Invalid or missing 'base_price' for item '{item_template_id}'. Found: {base_price}")
            return None

        current_price_per_unit = float(base_price)
        print(f"RuleEngine: calculate_market_price: Initial base_price_per_unit: {current_price_per_unit}")

        # 2. Apply Base Multipliers
        if is_selling_to_market:
            multiplier = economy_rules.get("base_sell_price_multiplier", 0.75)
            current_price_per_unit *= multiplier
            print(f"RuleEngine: calculate_market_price: Applied base_sell_price_multiplier ({multiplier}). Price_per_unit: {current_price_per_unit}")
        else: # Player is buying from market
            multiplier = economy_rules.get("base_buy_price_multiplier", 1.25)
            current_price_per_unit *= multiplier
            print(f"RuleEngine: calculate_market_price: Applied base_buy_price_multiplier ({multiplier}). Price_per_unit: {current_price_per_unit}")

        # 3. Apply Regional Modifiers
        regional_modifiers_all = economy_rules.get("regional_price_modifiers", {})
        regional_mod_for_location = regional_modifiers_all.get(str(location_id))

        if regional_mod_for_location:
            base_multiplier_for_direction = economy_rules.get("base_sell_price_multiplier", 0.75) if is_selling_to_market else economy_rules.get("base_buy_price_multiplier", 1.25)
            effective_multiplier = base_multiplier_for_direction

            if is_selling_to_market:
                sell_adj = regional_mod_for_location.get("sell_price_multiplier_adj", 0.0) # Additive adjustment to the multiplier itself
                effective_multiplier += sell_adj
                print(f"RuleEngine: calculate_market_price: Regional sell_price_multiplier_adj: {sell_adj}. Base mult: {base_multiplier_for_direction}, Effective mult: {effective_multiplier}")
            else: # Buying from market
                buy_adj = regional_mod_for_location.get("buy_price_multiplier_adj", 0.0)
                effective_multiplier += buy_adj
                print(f"RuleEngine: calculate_market_price: Regional buy_price_multiplier_adj: {buy_adj}. Base mult: {base_multiplier_for_direction}, Effective mult: {effective_multiplier}")

            # Re-calculate price using the adjusted effective multiplier based on the original base_price
            # (Original base_price * effective_multiplier) vs (current_price_per_unit * adjustment_factor)
            # The requirement says "E.g., if base buy multiplier is 1.25 and buy_factor_adj is -0.1, the effective multiplier becomes 1.15."
            # This implies the adjustment is to the multiplier, then applied to the original base price.
            current_price_per_unit = float(base_price) * effective_multiplier
            print(f"RuleEngine: calculate_market_price: After regional multiplier adjustment, price_per_unit: {current_price_per_unit}")

            # Category-specific regional modifiers
            item_category = item_def.get("category")
            if item_category:
                category_mods = regional_mod_for_location.get("item_category_multipliers", {}).get(str(item_category))
                if category_mods:
                    # These are defined as _adj as well, so they adjust the effective_multiplier further.
                    if is_selling_to_market:
                        sell_cat_adj = category_mods.get("sell_price_multiplier_adj", 0.0)
                        effective_multiplier += sell_cat_adj
                        print(f"RuleEngine: calculate_market_price: Regional category '{item_category}' sell_adj: {sell_cat_adj}. New Effective mult: {effective_multiplier}")
                    else:
                        buy_cat_adj = category_mods.get("buy_price_multiplier_adj", 0.0)
                        effective_multiplier += buy_cat_adj
                        print(f"RuleEngine: calculate_market_price: Regional category '{item_category}' buy_adj: {buy_cat_adj}. New Effective mult: {effective_multiplier}")

                    current_price_per_unit = float(base_price) * effective_multiplier # Recalculate with new effective_multiplier
                    print(f"RuleEngine: calculate_market_price: After category-specific regional adjustment, price_per_unit: {current_price_per_unit}")

        # 4. Apply Supply/Demand Modifiers
        economy_manager = kwargs.get("economy_manager")
        supply_demand_rules = economy_rules.get("supply_demand_rules")
        if economy_manager and supply_demand_rules and hasattr(economy_manager, 'get_market_inventory_level_ratio'):
            # Assuming get_market_inventory_level_ratio returns a value like 0.0 (empty) to 1.0 (ideal/target) to 2.0 (oversupplied)
            # This method needs to be implemented in EconomyManager. For now, let's assume it exists.
            # It might take (guild_id, location_id, item_template_id) and return this ratio.
            # A simpler version could be get_current_stock and then we calculate ratio here based on some target stock.
            # Let's assume get_market_inventory_level_ratio exists for simplicity here.

            # Placeholder: Ideal or target stock might be defined in item_def or globally in supply_demand_rules
            # For now, we rely on a conceptual 'inventory_level_ratio' from economy_manager.
            # This ratio would be (current_stock / target_stock).

            inventory_level_ratio = await economy_manager.get_market_inventory_level_ratio(guild_id, location_id, item_template_id)

            if inventory_level_ratio is not None:
                print(f"RuleEngine: calculate_market_price: Supply/Demand - Inventory level ratio: {inventory_level_ratio}")
                low_supply_thresh = supply_demand_rules.get("low_supply_threshold_percent", 0.2)
                high_supply_thresh = supply_demand_rules.get("high_supply_threshold_percent", 0.8)

                price_adjustment_factor = 1.0

                if inventory_level_ratio < low_supply_thresh: # Low supply -> price increases (player buying higher, selling higher)
                    markup_percent_range = supply_demand_rules.get("min_supply_markup_percent", 200.0) - 100.0 # e.g. 200% total price means 100% markup
                    # Simple linear interpolation for markup:
                    # Factor = 1.0 + ( (low_supply_thresh - inventory_level_ratio) / low_supply_thresh ) * (markup_percent_range / 100.0)
                    # Ensure inventory_level_ratio isn't zero to avoid division by zero if low_supply_thresh is used as denominator.
                    # If low_supply_thresh is 0.2, and ratio is 0.1: (0.1 / 0.2) * markup_range = 0.5 * markup_range
                    # Max markup when ratio is 0.
                    clamped_ratio = max(0.0, inventory_level_ratio)
                    markup_factor = ( (low_supply_thresh - clamped_ratio) / low_supply_thresh ) if low_supply_thresh > 0 else 1.0
                    price_adjustment_factor = 1.0 + (markup_factor * (markup_percent_range / 100.0))
                    print(f"RuleEngine: calculate_market_price: Supply/Demand - LOW supply. Markup factor: {price_adjustment_factor}")

                elif inventory_level_ratio > high_supply_thresh: # High supply -> price decreases
                    discount_percent_range = supply_demand_rules.get("max_supply_discount_percent", 50.0) # e.g. 50% discount means price is 0.5 of normal
                    # Simple linear interpolation for discount:
                    # Factor = 1.0 - ( (inventory_level_ratio - high_supply_thresh) / (SomeMaxPossibleRatio - high_supply_thresh) ) * (discount_percent_range / 100.0)
                    # Assume MaxPossibleRatio is e.g. 2.0 (twice the target stock) for full discount application range.
                    # Or, more simply, scale up to high_supply_thresh + (1-high_supply_thresh) = 1.0 as the point of max discount application.
                    # Max discount when ratio is very high (e.g., 1.0 or ideal_stock_multiplier_for_max_discount).
                    # Let's say max discount is applied when ratio is high_supply_thresh + (e.g. 0.5).
                    # (inventory_level_ratio - high_supply_thresh) / ( (high_supply_thresh + 0.5) - high_supply_thresh )
                    # (inventory_level_ratio - high_supply_thresh) / 0.5
                    # This needs a defined "max_ratio_for_full_discount" or similar in rules.
                    # For now, let's use a simpler scaling:
                    # If high_supply_thresh is 0.8, and ratio is 1.0 (meaning 100% of target stock):
                    # (1.0 - 0.8) / (1.0 - 0.8) - this is not good.
                    # Let's assume discount_percent_range is the reduction.
                    # If inventory_level_ratio is higher than high_supply_thresh, apply discount.
                    # Scaled effect: (inventory_level_ratio - high_supply_thresh) / ( (let's say 1.5 * high_supply_thresh) - high_supply_thresh )
                    # For now, a simpler linear scale from high_supply_threshold to a conceptual "max_relevant_supply_ratio" (e.g., 2.0)
                    max_relevant_supply_ratio = high_supply_thresh * 1.5 # Example: 50% above high threshold for full effect
                    if inventory_level_ratio > max_relevant_supply_ratio : inventory_level_ratio = max_relevant_supply_ratio # Cap effect

                    if max_relevant_supply_ratio > high_supply_thresh: # Avoid division by zero
                        discount_factor = (inventory_level_ratio - high_supply_thresh) / (max_relevant_supply_ratio - high_supply_thresh)
                        price_adjustment_factor = 1.0 - (discount_factor * (discount_percent_range / 100.0))
                        print(f"RuleEngine: calculate_market_price: Supply/Demand - HIGH supply. Discount factor: {price_adjustment_factor}")
                    else:
                        price_adjustment_factor = 1.0 - (discount_percent_range / 100.0) # Apply full discount if threshold is met and range is tiny/zero
                        print(f"RuleEngine: calculate_market_price: Supply/Demand - HIGH supply (max discount due to config). Discount factor: {price_adjustment_factor}")


                current_price_per_unit *= price_adjustment_factor
                print(f"RuleEngine: calculate_market_price: After Supply/Demand adjustment, price_per_unit: {current_price_per_unit}")

        # 5. Apply Relationship Modifiers
        relationship_manager = kwargs.get("relationship_manager")
        location_manager = kwargs.get("location_manager") # To find trader_entity

        trader_entity_id: Optional[str] = None
        trader_entity_type: Optional[str] = None

        if location_manager and hasattr(location_manager, 'get_location'):
            location_obj = await location_manager.get_location(guild_id, location_id)
            if location_obj:
                # Assuming Location object has owner_id and owner_type (e.g. FactionID, NPCID)
                if hasattr(location_obj, 'owner_id') and getattr(location_obj, 'owner_id'):
                    trader_entity_id = str(getattr(location_obj, 'owner_id'))
                    trader_entity_type = str(getattr(location_obj, 'owner_type', "Faction")) # Default to Faction if type not specified
                    print(f"RuleEngine: calculate_market_price: Trader identified from location owner: {trader_entity_id} ({trader_entity_type})")

        # Allow direct override from kwargs if specific NPC trader is involved not tied to location ownership
        trader_entity_id = kwargs.get('trader_entity_id', trader_entity_id)
        trader_entity_type = kwargs.get('trader_entity_type', trader_entity_type)

        if relationship_manager and trader_entity_id and trader_entity_type and hasattr(relationship_manager, 'get_relationship_strength'):
            relationship_strength = await relationship_manager.get_relationship_strength(
                guild_id, actor_entity_id, actor_entity_type, trader_entity_id, trader_entity_type
            )
            print(f"RuleEngine: calculate_market_price: Relationship strength with {trader_entity_id} ({trader_entity_type}): {relationship_strength}")

            rel_influence_rules = economy_rules.get("relationship_price_influence", {})
            tiers = rel_influence_rules.get("trading_discount_per_tier", [])

            best_tier_effect = None
            # Tiers should be sorted by threshold, or we find the best applicable one.
            # Assuming tiers are defined in a way that higher thresholds are more impactful.
            # Find the highest threshold tier that the current relationship_strength meets.
            applicable_tiers = [tier for tier in tiers if relationship_strength >= tier.get("relationship_threshold", float('-inf'))]
            if applicable_tiers:
                # Sort by threshold descending to get the "best" applicable tier
                applicable_tiers.sort(key=lambda t: t.get("relationship_threshold", float('-inf')), reverse=True)
                best_tier_effect = applicable_tiers[0]

            if best_tier_effect:
                print(f"RuleEngine: calculate_market_price: Applying relationship tier: {best_tier_effect.get('tier_name_i18n', {}).get('en_US', 'Unnamed Tier')}")
                price_adj_percentage = 0.0
                if is_selling_to_market: # Player selling, wants higher price from good relationship (sell_bonus_percent)
                    price_adj_percentage += best_tier_effect.get("sell_bonus_percent", 0.0)
                    price_adj_percentage -= best_tier_effect.get("sell_penalty_percent", 0.0) # if defined for negative rel
                else: # Player buying, wants lower price from good relationship (buy_discount_percent)
                    price_adj_percentage -= best_tier_effect.get("buy_discount_percent", 0.0)
                    price_adj_percentage += best_tier_effect.get("buy_markup_percent", 0.0) # if defined for negative rel

                current_price_per_unit *= (1 + (price_adj_percentage / 100.0))
                print(f"RuleEngine: calculate_market_price: After relationship adjustment ({price_adj_percentage}%), price_per_unit: {current_price_per_unit}")

        # 6. Apply Skill/Reputation Modifiers
        # This requires fetching the actor_entity (e.g. Character object) to get skills/reputations
        skill_rep_rules = economy_rules.get("skill_reputation_price_influence", {})

        # Actor might be a Character, potentially fetched via CharacterManager
        character_manager = kwargs.get("character_manager")
        actor_entity_obj = None
        if character_manager and actor_entity_type == "Character" and hasattr(character_manager, 'get_character'):
            actor_entity_obj = await character_manager.get_character(guild_id, actor_entity_id)

        if actor_entity_obj and skill_rep_rules:
            # Bartering Skill
            bartering_rules = skill_rep_rules.get("bartering_skill_influence")
            if bartering_rules and hasattr(actor_entity_obj, 'skills'): # Assuming actor_entity_obj has a 'skills' dict/attr
                skill_id = bartering_rules.get("skill_id", "bartering")
                actor_skills = getattr(actor_entity_obj, 'skills', {}) # e.g. {"bartering": 10, "stealth": 5}
                skill_level = actor_skills.get(skill_id, 0)

                if skill_level > 0:
                    total_skill_effect_percent = 0.0
                    if is_selling_to_market:
                        bonus_per_point = bartering_rules.get("sell_bonus_percent_per_skill_point", 0.0)
                        max_bonus = bartering_rules.get("max_total_sell_bonus_percent", float('inf'))
                        total_skill_effect_percent = min(skill_level * bonus_per_point, max_bonus)
                    else: # Buying from market
                        discount_per_point = bartering_rules.get("buy_discount_percent_per_skill_point", 0.0)
                        max_discount = bartering_rules.get("max_total_discount_percent", float('inf'))
                        total_skill_effect_percent = -min(skill_level * discount_per_point, max_discount) # Negative for discount

                    current_price_per_unit *= (1 + (total_skill_effect_percent / 100.0))
                    print(f"RuleEngine: calculate_market_price: After bartering skill '{skill_id}' (lvl {skill_level}, effect {total_skill_effect_percent}%), price_per_unit: {current_price_per_unit}")

            # Faction Reputation (assuming actor_entity_obj has faction reputations and trader has a faction)
            # This part requires knowing the trader's faction_id.
            # Let's assume trader_entity_id could be a faction_id if trader_entity_type was "Faction".
            # Or, if trader is an NPC, that NPC needs a faction_id attribute.
            # For now, this part will be simplified.

            # trader_faction_id = None
            # if trader_entity_type == "Faction": trader_faction_id = trader_entity_id
            # elif trader_entity_type == "NPC": # Need to get NPC's faction
            #    npc_manager = kwargs.get("npc_manager")
            #    if npc_manager and hasattr(npc_manager, 'get_npc'):
            #        npc_trader = await npc_manager.get_npc(guild_id, trader_entity_id)
            #        if npc_trader and hasattr(npc_trader, 'faction_id'):
            #            trader_faction_id = getattr(npc_trader, 'faction_id')

            # if trader_faction_id and hasattr(actor_entity_obj, 'reputations'):
            #    faction_rep_rules = skill_rep_rules.get("faction_reputation_tiers", [])
            #    actor_reputations = getattr(actor_entity_obj, 'reputations', {}) # e.g. {"merchants_guild": "member_plus"}
            #    actor_rep_tier_with_trader_faction = actor_reputations.get(trader_faction_id)

            #    if actor_rep_tier_with_trader_faction:
            #        for rep_tier_rule in faction_rep_rules:
            #            if rep_tier_rule.get("faction_id") == trader_faction_id and \
            #               rep_tier_rule.get("reputation_tier_name") == actor_rep_tier_with_trader_faction:
            #                rep_effect_percent = 0.0
            #                if is_selling_to_market:
            #                    rep_effect_percent += rep_tier_rule.get("sell_bonus_percent", 0.0)
            #                else:
            #                    rep_effect_percent -= rep_tier_rule.get("buy_discount_percent", 0.0)
            #                current_price_per_unit *= (1 + (rep_effect_percent / 100.0))
            #                print(f"RuleEngine: calculate_market_price: After faction reputation '{trader_faction_id}' tier '{actor_rep_tier_with_trader_faction}' effect ({rep_effect_percent}%), price_per_unit: {current_price_per_unit}")
            #                break # Applied one faction rep tier effect for the trader's faction

        # 7. Final Price
        final_total_price = current_price_per_unit * quantity
        final_total_price = max(0, final_total_price) # Ensure price is not negative

        print(f"RuleEngine: calculate_market_price: Final calculated total price for quantity {quantity}: {final_total_price} (per unit: {final_total_price/quantity if quantity else 0})")
        return float(final_total_price)

    async def process_economy_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        """
        Processes economic updates for a game tick, such as restocking markets,
        adjusting demand/supply effects, etc.
        This is a placeholder for more complex rule-driven economic simulation.
        """
        guild_id_str = str(guild_id)
        print(f"RuleEngine: process_economy_tick called for guild '{guild_id_str}', game_time_delta: {game_time_delta}s.")

        economy_rules = self._rules_data.get("economy_rules")
        if not economy_rules:
            print(f"RuleEngine: process_economy_tick: No 'economy_rules' found for guild '{guild_id_str}'. Skipping.")
            return

        economy_manager = kwargs.get("economy_manager")
        if not economy_manager:
            print(f"RuleEngine: process_economy_tick: 'economy_manager' not found in kwargs. Cannot process economy tick for guild '{guild_id_str}'.")
            return

        # Placeholder for actual tick processing logic
        print(f"RuleEngine: process_economy_tick: Placeholder for guild '{guild_id_str}'. Would access 'economy_rules.supply_demand_rules' for restocking intervals, amounts, etc.")
        print(f"RuleEngine: process_economy_tick: Would also check for rules on item consumption, demand shifts, or global price adjustments.")

        # Example of what detailed logic might involve (conceptual):
        # supply_demand_rules = economy_rules.get("supply_demand_rules", {})
        # restock_interval_hours = supply_demand_rules.get("restock_cycle_hours")
        #
        # if restock_interval_hours:
        #     # This would require EconomyManager to store market data with timestamps or for RuleEngine to maintain such state.
        #     # For each market in economy_manager for the guild:
        #     #   For each item_template_id in market:
        #     #     Fetch item_def for target_stock_level (needs to be added to item_def)
        #     #     current_stock = market_inventory.get(item_template_id)
        #     #     if time_since_last_restock > restock_interval_hours and current_stock < target_stock_level:
        #     #         restock_amount = calculate_restock_amount(...)
        #     #         await economy_manager.add_items_to_market(guild_id_str, location_id, {item_template_id: restock_amount}, **kwargs)
        #     #         Update last_restock_timestamp for this item/market
        #     pass

        # For now, no actual modifications are made.
        # This method should be expanded when specific economic simulation rules are defined.
        if not economy_rules.get("supply_demand_rules"):
            print(f"RuleEngine: process_economy_tick: No 'supply_demand_rules' found in 'economy_rules' for guild '{guild_id_str}'. No restocking or detailed simulation will occur.")

        print(f"RuleEngine: process_economy_tick completed for guild '{guild_id_str}'.")

    async def resolve_dice_roll(
        self,
        dice_string: str,
        pre_rolled_result: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Resolves a dice roll string, e.g., "2d6+3", "1d20", "d6-1".
        Optionally accepts a pre_rolled_result for one of the dice (typically the first d20).
        context is currently unused but included for future extensibility (e.g., character-specific modifiers).
        """
        # print(f"RuleEngine: resolve_dice_roll called with dice_string='{dice_string}', pre_rolled_result={pre_rolled_result}, context={context}")

        # Regex to parse dice string: (\d*)d(\d+)([+-]\d+)?
        # Group 1: Number of dice (optional, defaults to 1)
        # Group 2: Sides of dice
        # Group 3: Modifier (optional, e.g., +3, -1), allowing spaces like " + 3" or " - 2"
        # Regex to parse dice string: (\d*)d(\d+)(\s*[+-]\s*\d+)?
        dice_string_cleaned = dice_string.lower().strip()
        match = re.fullmatch(r"(\d*)d(\d+)(\s*[+-]\s*\d+)?", dice_string_cleaned)

        if not match:
            # Try matching simpler "d20" or "d6" forms (implies 1 die)
            match_simple = re.fullmatch(r"d(\d+)(\s*[+-]\s*\d+)?", dice_string_cleaned)
            if match_simple:
                num_dice_str = "1"
                sides_str = match_simple.group(1)
                modifier_str = match_simple.group(2)
            else:
                raise ValueError(f"Invalid dice string format: {dice_string}")
        else:
            num_dice_str = match.group(1)
            sides_str = match.group(2)
            modifier_str = match.group(3)

        num_dice = int(num_dice_str) if num_dice_str else 1
        sides = int(sides_str)
        # Process modifier string by removing spaces before converting to int
        modifier = int(modifier_str.replace(" ", "")) if modifier_str else 0

        if sides <= 0:
            raise ValueError("Dice sides must be positive.")
        if num_dice <= 0:
            raise ValueError("Number of dice must be positive.")

        rolls = []
        roll_total = 0

        for i in range(num_dice):
            if i == 0 and pre_rolled_result is not None:
                # Use pre_rolled_result for the first die if provided
                # Ensure it's within the valid range for the die
                if not (1 <= pre_rolled_result <= sides):
                    # This could be an error, or we could clamp it, or just use it.
                    # For now, let's use it but be aware it might be "out of bounds" for a natural roll.
                    # Or, more strictly, raise an error if it's impossible for the die type.
                    # Let's be strict for now.
                    raise ValueError(f"pre_rolled_result {pre_rolled_result} is not valid for a d{sides}.")
                roll = pre_rolled_result
            else:
                roll = random.randint(1, sides)
            rolls.append(roll)
            roll_total += roll

        total_with_modifier = roll_total + modifier

        result = {
            "dice_string": dice_string,
            "num_dice": num_dice,
            "sides": sides,
            "modifier": modifier,
            "rolls": rolls, # List of individual dice results
            "roll_total_raw": roll_total, # Sum of dice before modifier
            "total": total_with_modifier, # Final result after modifier
            "pre_rolled_input": pre_rolled_result # For logging/debugging
        }
        # print(f"RuleEngine: resolve_dice_roll result: {result}")
        return result

print("DEBUG: rule_engine.py module defined.")


