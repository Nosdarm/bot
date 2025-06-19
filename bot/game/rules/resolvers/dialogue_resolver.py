# bot/game/rules/resolvers/dialogue_resolver.py
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Callable, Awaitable, Tuple

if TYPE_CHECKING:
    from bot.game.models.character import Character
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.relationship_manager import RelationshipManager
    # Removed: from ..rule_engine import RuleEngine as it would create circular dependency

async def process_dialogue_action(
    rules_data: Dict[str, Any],
    dialogue_manager: "DialogueManager",
    character_manager: "CharacterManager",
    npc_manager: "NpcManager",
    relationship_manager: "RelationshipManager",
    resolve_skill_check_func: Callable[..., Awaitable[Tuple[bool, int, int, Optional[str]]]], # Type for resolve_skill_check_wrapper
    dialogue_data: Dict[str, Any],
    character_id: str,
    p_action_data: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    result = {
        "new_stage_id": None, "is_dialogue_ending": False, "skill_check_result": None,
        "immediate_actions_to_trigger": [], "direct_relationship_changes": [], "messages_to_send": []
    }
    guild_id = str(context.get('guild_id'))
    if not guild_id:
        result["error"] = "Guild ID missing from context."
        return result

    current_stage_id = dialogue_data.get('current_stage_id')
    template_id = dialogue_data.get('template_id')
    dialogue_template = dialogue_manager.get_dialogue_template(guild_id, template_id)

    if not dialogue_template or not current_stage_id:
        result["error"] = f"Dialogue template '{template_id}' or current stage '{current_stage_id}' not found."
        return result

    current_stage_definition = dialogue_template.get('stages', {}).get(current_stage_id)
    if not current_stage_definition:
        result["error"] = f"Current stage definition '{current_stage_id}' not found in template '{template_id}'."
        return result

    response_id = p_action_data.get('response_id')
    chosen_response_definition = next((resp for resp in current_stage_definition.get('player_responses', []) if resp.get('id') == response_id), None)

    if not chosen_response_definition:
        result["error"] = f"Response ID '{response_id}' not found in current stage '{current_stage_id}'."
        return result

    next_node_id = chosen_response_definition.get('next_node_id', 'end')

    skill_check_def = chosen_response_definition.get('skill_check')
    if skill_check_def:
        character_obj = await character_manager.get_character(guild_id, character_id)
        if not character_obj:
            result["error"] = f"Character {character_id} not found for skill check."
            return result

        npc_id = next((p.get('entity_id') for p in dialogue_data.get('participants', []) if isinstance(p, dict) and p.get('entity_id') != character_id and p.get('entity_type') == "NPC"), None)
        npc_obj = await npc_manager.get_npc(guild_id, npc_id) if npc_id else None
        if not npc_obj:
            result["error"] = f"NPC partner in dialogue (ID: {npc_id}) not found for skill check."
            return result

        skill_type = skill_check_def.get('type')
        dc_formula_str = str(skill_check_def.get('dc_formula', '15'))
        base_dc = 15
        try: base_dc = int(dc_formula_str)
        except ValueError:
            if "npc_stats." in dc_formula_str:
                stat_name_match = re.search(r"npc_stats\.(\w+)", dc_formula_str)
                if stat_name_match and npc_obj:
                    stat_name = stat_name_match.group(1)
                    npc_stat_val = getattr(npc_obj, 'stats', {}).get(stat_name, 10)
                    offset_match = re.search(r"([+\-])\s*(\d+)", dc_formula_str)
                    offset = 0
                    if offset_match:
                        op, val_str_offset = offset_match.group(1), offset_match.group(2)
                        val_offset = int(val_str_offset)
                        offset = val_offset if op == '+' else -val_offset
                    base_dc = npc_stat_val + offset

        relationship_bonus = 0.0
        feedback_key_skill_check = None
        feedback_params_skill_check = {}
        safe_builtins = {"True": True, "False": False, "None": None, "abs": abs, "min": min, "max": max, "float": float, "int": int}
        eval_globals = {"__builtins__": safe_builtins}
        rules_ref_name = skill_check_def.get('relationship_bonus_rules_ref')

        if rules_ref_name and relationship_manager and rules_data and npc_obj:
            rel_strength = await relationship_manager.get_relationship_strength(guild_id, character_id, "Character", npc_obj.id, "NPC")
            all_influence_rules = rules_data.get("relationship_influence_rules", [])
            found_rule = next((r_rule for r_rule in all_influence_rules if r_rule.get("name") == rules_ref_name and r_rule.get("influence_type") == "dialogue_skill_check"), None)
            if found_rule:
                rule_condition_str = found_rule.get("condition")
                condition_eval_locals = {"character": character_obj.to_dict(), "npc": npc_obj.to_dict(), "current_strength": rel_strength, "dialogue_data": dialogue_data}
                try: condition_met = eval(rule_condition_str, eval_globals, condition_eval_locals) if rule_condition_str else True
                except Exception as e: print(f"DialogueResolver: Error evaluating condition for skill check rule '{found_rule.get('name')}': {e}"); condition_met = False
                if condition_met:
                    threshold_type = found_rule.get("threshold_type"); threshold_value = found_rule.get("threshold_value"); threshold_met = True
                    if threshold_type and threshold_value is not None:
                        if threshold_type == "min_strength" and rel_strength < threshold_value: threshold_met = False
                        elif threshold_type == "max_strength" and rel_strength > threshold_value: threshold_met = False
                    if threshold_met:
                        bonus_malus_formula = found_rule.get("bonus_malus_formula")
                        if bonus_malus_formula:
                            formula_eval_locals = {"current_strength": rel_strength, "character_stats": character_obj.stats_json, "npc_stats": npc_obj.stats}
                            try: relationship_bonus = float(eval(bonus_malus_formula, eval_globals, formula_eval_locals))
                            except Exception as e: print(f"DialogueResolver: Error evaluating bonus_malus for rule '{found_rule.get('name')}': {e}")
                        feedback_key_skill_check = found_rule.get("effect_description_i18n_key")
                        raw_params_map = found_rule.get("effect_params_mapping", {})
                        for param_key, context_path_str in raw_params_map.items():
                            if context_path_str == "npc.name": feedback_params_skill_check[param_key] = getattr(npc_obj, 'name_i18n', {}).get('en', npc_obj.id)
                            elif context_path_str == "character.name": feedback_params_skill_check[param_key] = getattr(character_obj, 'name_i18n', {}).get('en', character_obj.id)
                            elif context_path_str == "calculated_bonus": feedback_params_skill_check[param_key] = f"{'+' if relationship_bonus >= 0 else ''}{relationship_bonus:.0f}"

        final_dc = int(base_dc - relationship_bonus)
        check_success, total_roll, d20_roll, crit_status = await resolve_skill_check_func(character_obj, skill_type, final_dc, context=context)

        result['skill_check_result'] = {"type": skill_type, "dc": final_dc, "roll": d20_roll, "total": total_roll, "success": check_success, "crit_status": crit_status, "relationship_bonus_applied": relationship_bonus, "feedback_key": feedback_key_skill_check, "feedback_params": feedback_params_skill_check}
        next_node_id = skill_check_def['success_node_id'] if check_success else skill_check_def['failure_node_id']

    result['new_stage_id'] = next_node_id
    result['is_dialogue_ending'] = (next_node_id == "end" or next_node_id in dialogue_template.get('end_stages', ['end']))
    if chosen_response_definition.get('action'): result['immediate_actions_to_trigger'].append(chosen_response_definition['action'])
    rel_effects = chosen_response_definition.get('relationship_effects')
    if isinstance(rel_effects, list): result['direct_relationship_changes'].extend(rel_effects)
    elif isinstance(rel_effects, dict): result['direct_relationship_changes'].append(rel_effects)
    return result

async def get_filtered_dialogue_options(
    rules_data: Dict[str, Any],
    character_manager: "CharacterManager",
    npc_manager: "NpcManager",
    relationship_manager: "RelationshipManager",
    dialogue_data: Dict[str, Any],
    character_id: str,
    stage_definition: Dict[str, Any],
    context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    guild_id = str(context.get('guild_id'))
    if not guild_id: return stage_definition.get('player_responses', [])

    available_options = []
    all_responses = stage_definition.get('player_responses', [])
    safe_builtins = {"True": True, "False": False, "None": None, "abs": abs, "min": min, "max": max, "float": float, "int": int, "str": str}
    eval_globals = {"__builtins__": safe_builtins}

    npc_id = None; npc_type = "NPC"; npc_obj_dict = {}
    character_obj = await character_manager.get_character(guild_id, character_id)
    char_obj_dict = character_obj.to_dict() if character_obj else {}

    participants = dialogue_data.get('participants', [])
    for p_data_entry in participants:
        p_entity_id = p_data_entry.get('entity_id') if isinstance(p_data_entry, dict) else str(p_data_entry)
        if p_entity_id != character_id:
            npc_id = p_entity_id
            npc_type = p_data_entry.get('entity_type', "NPC") if isinstance(p_data_entry, dict) else "NPC"
            if npc_id:
                npc_instance = await npc_manager.get_npc(guild_id, npc_id)
                npc_obj_dict = npc_instance.to_dict() if npc_instance else {}
            break

    current_strength_with_npc = 0.0
    if npc_id:
        current_strength_with_npc = await relationship_manager.get_relationship_strength(guild_id, character_id, "Character", npc_id, npc_type)

    influence_rules = rules_data.get("relationship_influence_rules", [])
    dialogue_availability_rules = [rule for rule in influence_rules if rule.get("influence_type") == "dialogue_option_availability"]

    for option_def in all_responses:
        option_copy = option_def.copy(); option_copy['is_available'] = True; option_copy['failure_feedback_key'] = None; option_copy['failure_feedback_params'] = {}
        for rule in dialogue_availability_rules:
            rule_condition_str = rule.get("condition")
            condition_eval_locals = {"character": char_obj_dict, "npc": npc_obj_dict, "current_strength": current_strength_with_npc, "dialogue_data": dialogue_data, "option_data": option_copy}
            try: rule_applies = eval(rule_condition_str, eval_globals, condition_eval_locals) if rule_condition_str else True
            except Exception as e: print(f"DialogueResolver: Error evaluating condition for avail rule '{rule.get('name')}': {e}"); rule_applies = False

            if rule_applies:
                threshold_type = rule.get("threshold_type"); threshold_value = rule.get("threshold_value"); threshold_met = True
                threshold_condition_present = threshold_type and threshold_value is not None
                if threshold_condition_present:
                    if threshold_type == "min_strength" and current_strength_with_npc < threshold_value: threshold_met = False
                    elif threshold_type == "max_strength" and current_strength_with_npc > threshold_value: threshold_met = False

                if rule.get("availability_flag") is True:
                    if threshold_condition_present and not threshold_met:
                        option_copy['is_available'] = False; option_copy['failure_feedback_key'] = rule.get("failure_feedback_key"); raw_params_map = rule.get("failure_feedback_params_mapping", {})
                        for param_key, context_path_str in raw_params_map.items():
                            if context_path_str == "npc.name": option_copy['failure_feedback_params'][param_key] = npc_obj_dict.get('name_i18n', {}).get('en', npc_id)
                            elif context_path_str == "character.name": option_copy['failure_feedback_params'][param_key] = char_obj_dict.get('name_i18n', {}).get('en', character_id)
                            elif context_path_str == "threshold_value": option_copy['failure_feedback_params'][param_key] = str(threshold_value)
                            elif context_path_str == "current_strength": option_copy['failure_feedback_params'][param_key] = f"{current_strength_with_npc:.1f}"
                        break
                elif rule.get("availability_flag") is False:
                    if threshold_met:
                        option_copy['is_available'] = False; option_copy['failure_feedback_key'] = rule.get("failure_feedback_key"); raw_params_map = rule.get("failure_feedback_params_mapping", {})
                        for param_key, context_path_str in raw_params_map.items():
                            if context_path_str == "npc.name": option_copy['failure_feedback_params'][param_key] = npc_obj_dict.get('name_i18n', {}).get('en', npc_id)
                            elif context_path_str == "character.name": option_copy['failure_feedback_params'][param_key] = char_obj_dict.get('name_i18n', {}).get('en', character_id)
                            elif context_path_str == "threshold_value": option_copy['failure_feedback_params'][param_key] = str(threshold_value)
                            elif context_path_str == "current_strength": option_copy['failure_feedback_params'][param_key] = f"{current_strength_with_npc:.1f}"
                        break
        available_options.append(option_copy)
    return available_options
