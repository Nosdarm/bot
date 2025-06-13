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
            p_obj for p_obj in combat.participants
            if isinstance(p_obj, CombatParticipant) and p_obj.hp > 0 and p_obj.entity_id != npc.id
        ]

        if not living_participants_in_combat:
            return {'type': 'idle', 'total_duration': None}

        best_target = None
        highest_threat_score = -float('inf')
        npc_combat_rules = self._rules_data.get("relationship_influence_rules", {}).get("npc_combat", {})
        priority_factor_negative_rel = npc_combat_rules.get("target_priority", {}).get("prioritize_strong_negative_relationship_factor", 1.0)
        depriority_factor_positive_rel = npc_combat_rules.get("target_priority", {}).get("deprioritize_strong_positive_relationship_factor", 1.0)
        base_threat = 10

        for p_target_obj in living_participants_in_combat:
            current_threat = float(base_threat)
            relationship_strength = 0.0
            if self._relationship_manager: # Check if RelationshipManager is available
                relationship_strength = await self._relationship_manager.get_relationship_strength(
                    guild_id, npc.id, "NPC", p_target_obj.entity_id, p_target_obj.entity_type
                )
            if relationship_strength < 0:
                current_threat *= (1 + (abs(relationship_strength) / 100.0) * (priority_factor_negative_rel -1))
            elif relationship_strength > 0:
                current_threat *= (1 - (relationship_strength / 100.0) * (1 - depriority_factor_positive_rel))

            if current_threat > highest_threat_score:
                highest_threat_score = current_threat
                best_target = p_target_obj

        if best_target:
            return {'type': 'combat_attack', 'target_id': best_target.entity_id, 'target_type': best_target.entity_type, 'attack_type': 'basic_attack'}
        return {'type': 'idle', 'total_duration': None}

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

        behavior_rules = self._rules_data.get("relationship_influence_rules", {}).get("npc_behavior", {})
        dialogue_init_threshold = behavior_rules.get("dialogue_initiation_threshold", -25.0)
        become_hostile_threshold = behavior_rules.get("become_hostile_threshold", -50.0)

        curr_loc = getattr(npc, 'location_id', None)
        if cm and lm and curr_loc and self._relationship_manager: # Ensure RelationshipManager is available
            chars_in_loc = cm.get_characters_in_location(str(curr_loc), context=context)

            potential_targets_by_relationship: List[Tuple[Character, float]] = []
            for ch_candidate in chars_in_loc:
                if isinstance(ch_candidate, Character) and ch_candidate.id != npc.id :
                    strength = await self._relationship_manager.get_relationship_strength(
                        guild_id, npc.id, "NPC", ch_candidate.id, "Character"
                    )
                    potential_targets_by_relationship.append((ch_candidate, strength))

            for ch, strength in potential_targets_by_relationship:
                if strength < become_hostile_threshold:
                    print(f"RuleEngine: NPC {npc.id} relationship with Character {ch.id} is {strength:.2f} (below hostile threshold {become_hostile_threshold}). Initiating combat.")
                    return {'type': 'initiate_combat', 'target_id': ch.id, 'target_type': 'Character'}

            if dm:
                sorted_dialogue_targets = sorted(potential_targets_by_relationship, key=lambda x: x[1], reverse=True)
                for ch, strength in sorted_dialogue_targets:
                    if strength >= dialogue_init_threshold:
                        if hasattr(dm, 'can_start_dialogue') and dm.can_start_dialogue(npc, ch, context=context):
                            return {'type': 'ai_dialogue', 'target_id': ch.id, 'target_type': 'Character'}

        if curr_loc and lm: # Wandering
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

            rules_ref = skill_check_def.get('relationship_bonus_rules_ref')
            if rules_ref and self._relationship_manager and self._rules_data and npc_obj: # Check npc_obj
                rel_strength = await self._relationship_manager.get_relationship_strength(guild_id, character_id, "Character", npc_obj.id, "NPC")
                bonus_rules = self._rules_data.get("relationship_influence_rules", {}).get(rules_ref, [])
                for rule in sorted(bonus_rules, key=lambda x: x.get("threshold", 0.0), reverse=True):
                    if rel_strength >= rule.get("threshold", float('inf')):
                        relationship_bonus = float(rule.get("bonus", 0.0))
                        if relationship_bonus > 0: feedback_key_skill_check = "feedback.relationship.dialogue_check_bonus"
                        elif relationship_bonus < 0: feedback_key_skill_check = "feedback.relationship.dialogue_check_penalty"
                        if feedback_key_skill_check:
                             feedback_params_skill_check = {"npc_name": getattr(npc_obj, 'name', npc_obj.id), "bonus_amount_str": f"{'+' if relationship_bonus > 0 else ''}{relationship_bonus}"}
                        break
            
            final_dc = int(base_dc - relationship_bonus)

            check_success, total_roll, d20_roll, crit_status = await self.resolve_skill_check(
                character_obj, skill_type, final_dc, context=context # Pass context for resolve_skill_check's logging
            )
            result['skill_check_result'] = {
                "type": skill_type, "dc": final_dc, "roll": d20_roll,
                "total": total_roll, "success": check_success, "crit_status": crit_status,
                "relationship_bonus_applied": relationship_bonus,
                "feedback_key": feedback_key_skill_check, # Added
                "feedback_params": feedback_params_skill_check # Added
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

        npc_id = None
        npc_type = "NPC" # Assume other participant is NPC for dialogue context
        participants = dialogue_data.get('participants', [])
        for p_data_entry in participants:
            p_entity_id = p_data_entry.get('entity_id') if isinstance(p_data_entry, dict) else str(p_data_entry)
            if p_entity_id != character_id:
                npc_id = p_entity_id
                if isinstance(p_data_entry, dict):
                    npc_type = p_data_entry.get('entity_type', "NPC")
                break
        
        npc_name = npc_id # Fallback
        if npc_id and self._npc_manager:
            npc_obj = await self._npc_manager.get_npc(guild_id, npc_id)
            if npc_obj:
                npc_name = getattr(npc_obj, 'name', npc_id)


        for option in all_responses:
            option_copy = option.copy() # Work with a copy
            option_copy['is_available'] = True # Default to available

            req_rel = option_copy.get('requires_relationship')
            if req_rel and isinstance(req_rel, dict):
                target_entity_ref = req_rel.get('target_entity_ref')
                target_entity_type = req_rel.get('target_entity_type') # Should be "NPC" or "Faction"
                
                actual_target_id = None
                if target_entity_ref == "npc_id" and npc_id: # Special ref for "the NPC I'm talking to"
                    actual_target_id = npc_id
                elif target_entity_ref:
                    # For other refs, e.g. a faction ID stored in dialogue_data or template
                    # This part would need more robust resolution if refs can be complex
                    actual_target_id = dialogue_data.get('state_variables', {}).get(target_entity_ref)
                    if not actual_target_id: # Check dialogue_data itself
                        actual_target_id = dialogue_data.get(target_entity_ref)

                if actual_target_id and target_entity_type:
                    current_strength = await self._relationship_manager.get_relationship_strength(
                        guild_id, character_id, "Character", str(actual_target_id), target_entity_type
                    )

                    min_strength = req_rel.get("min_strength")
                    max_strength = req_rel.get("max_strength")
                    prereq_met = True
                    if min_strength is not None and current_strength < float(min_strength):
                        prereq_met = False
                    if max_strength is not None and current_strength > float(max_strength):
                        prereq_met = False

                    if not prereq_met:
                        option_copy['is_available'] = False
                        # Store failure text or key for NotificationService
                        option_copy['failure_feedback_key'] = req_rel.get('failure_text_i18n_key', "feedback.relationship.dialogue_option_unavailable_poor")
                        option_copy['failure_feedback_params'] = {"npc_name": npc_name or "this person"}
                        # The actual failure_text_i18n from template could also be passed along if DialogueManager is to format it
                        option_copy['failure_text_i18n_direct'] = req_rel.get('failure_text_i18n')


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

[end of bot/game/rules/rule_engine.py]
