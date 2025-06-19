# bot/game/rules/resolvers/combat_ai_resolver.py
import random
import re # Keep re if eval uses it, though direct use is safer
from typing import TYPE_CHECKING, Any, Dict, Optional, List

if TYPE_CHECKING:
    from bot.game.models.npc import NPC
    from bot.game.models.character import Character # For choose_peaceful_action_for_npc
    from bot.game.models.combat import Combat, CombatParticipant
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.location_manager import LocationManager # For choose_peaceful_action_for_npc
    from bot.game.managers.dialogue_manager import DialogueManager # For choose_peaceful_action_for_npc


async def choose_combat_action_for_npc(
    rules_data: Dict[str, Any],
    npc: "NPC",
    combat: "Combat",
    # Managers that might be needed by internal logic or passed context
    character_manager: Optional["CharacterManager"],
    npc_manager: Optional["NpcManager"],
    combat_manager: Optional["CombatManager"], # Though 'combat' object is passed, manager might have other utils
    relationship_manager: Optional["RelationshipManager"],
    context: Dict[str, Any] # Full context for flexibility
) -> Optional[Dict[str, Any]]:
    guild_id = context.get('guild_id', getattr(npc, 'guild_id', None))

    if not combat_manager or not guild_id: # combat_manager might be self._combat_manager in original
        print(f"CombatAIResolver: CombatManager or guild_id missing for NPC {npc.id}. Choosing idle.")
        return {'type': 'idle', 'total_duration': None}

    living_participants_in_combat = [
        p for p in combat.participants
        if isinstance(p, CombatParticipant) and p.hp > 0 and p.entity_id != npc.id
    ]

    if not living_participants_in_combat:
        return {'type': 'idle', 'total_duration': None}

    best_target = None
    highest_threat_score = -float('inf')
    base_threat = 10.0

    safe_builtins = {"True": True, "False": False, "None": None, "abs": abs, "min": min, "max": max, "float": float, "int": int}
    eval_globals = {"__builtins__": safe_builtins}

    influence_rules = rules_data.get("relationship_influence_rules", [])
    targeting_rules = [rule for rule in influence_rules if rule.get("influence_type") == "npc_targeting"]

    for p_target_obj in living_participants_in_combat:
        current_target_threat_adjustment = 0.0
        relationship_strength = 0.0
        if relationship_manager:
            relationship_strength = await relationship_manager.get_relationship_strength(
                guild_id, npc.id, "NPC", p_target_obj.entity_id, p_target_obj.entity_type
            )

        for rule in targeting_rules:
            rule_condition_str = rule.get("condition")
            condition_eval_locals = {
                "npc": npc.to_dict() if npc else {},
                "target_entity": p_target_obj.to_dict(),
                "current_strength": relationship_strength,
                "combat_context": combat.to_dict()
            }
            try:
                condition_met = eval(rule_condition_str, eval_globals, condition_eval_locals) if rule_condition_str else True
            except Exception as e:
                print(f"CombatAIResolver: Error evaluating condition for targeting rule '{rule.get('name')}': {e}")
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

                if threshold_met:
                    bonus_malus_formula = rule.get("bonus_malus_formula")
                    if bonus_malus_formula:
                        formula_eval_locals = {
                            "current_strength": relationship_strength,
                            "base_threat": base_threat,
                            "npc_stats": getattr(npc, 'stats', {}),
                            "target_stats": getattr(p_target_obj, 'stats', {})
                        }
                        try:
                            adjustment = float(eval(bonus_malus_formula, eval_globals, formula_eval_locals))
                            current_target_threat_adjustment += adjustment
                        except Exception as e:
                            print(f"CombatAIResolver: Error evaluating bonus_malus_formula for rule '{rule.get('name')}': {e}")

        final_threat_for_target = base_threat + current_target_threat_adjustment
        if final_threat_for_target > highest_threat_score:
            highest_threat_score = final_threat_for_target
            best_target = p_target_obj

    if best_target:
        return {'type': 'combat_attack', 'target_id': best_target.entity_id, 'target_type': best_target.entity_type, 'attack_type': 'basic_attack'}

    return {'type': 'idle', 'total_duration': None}


async def choose_peaceful_action_for_npc(
    rules_data: Dict[str, Any],
    npc: "NPC",
    location_manager: "LocationManager",
    character_manager: "CharacterManager",
    dialogue_manager: Optional["DialogueManager"], # Can be None
    relationship_manager: "RelationshipManager",
    context: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    guild_id = context.get('guild_id', getattr(npc, 'guild_id', None))
    if not guild_id:
        print(f"CombatAIResolver: guild_id missing for NPC {npc.id}. Cannot choose action.")
        return {'type': 'idle', 'total_duration': None}

    safe_builtins = {"True": True, "False": False, "None": None, "abs": abs, "min": min, "max": max, "float": float, "int": int}
    eval_globals = {"__builtins__": safe_builtins}
    influence_rules = rules_data.get("relationship_influence_rules", [])
    curr_loc = getattr(npc, 'location_id', None)

    if character_manager and location_manager and curr_loc and relationship_manager:
        # Assuming Character model is imported if TYPE_CHECKING is properly handled where Character is defined
        from bot.game.models.character import Character

        chars_in_loc = character_manager.get_characters_in_location(str(curr_loc), context=context)
        for ch_candidate in chars_in_loc:
            if not (isinstance(ch_candidate, Character) and ch_candidate.id != npc.id):
                continue

            relationship_strength = await relationship_manager.get_relationship_strength(
                guild_id, npc.id, "NPC", ch_candidate.id, "Character"
            )

            hostility_rules = [r for r in influence_rules if r.get("influence_type") == "npc_behavior_hostility"]
            for rule in hostility_rules:
                condition_eval_locals = {"npc": npc.to_dict(), "target_entity": ch_candidate.to_dict(), "current_strength": relationship_strength}
                try: condition_met = eval(rule.get("condition", "True"), eval_globals, condition_eval_locals)
                except Exception as e: print(f"CombatAIResolver: Error evaluating hostility condition '{rule.get('name')}': {e}"); condition_met = False
                if condition_met:
                    threshold_type = rule.get("threshold_type"); threshold_value = rule.get("threshold_value")
                    if threshold_type == "max_strength" and relationship_strength < threshold_value:
                        return {'type': 'initiate_combat', 'target_id': ch_candidate.id, 'target_type': 'Character'}

            if dialogue_manager:
                dialogue_rules = [r for r in influence_rules if r.get("influence_type") == "npc_behavior_dialogue_initiation"]
                for rule in dialogue_rules:
                    condition_eval_locals = {"npc": npc.to_dict(), "target_entity": ch_candidate.to_dict(), "current_strength": relationship_strength}
                    try: condition_met = eval(rule.get("condition", "True"), eval_globals, condition_eval_locals)
                    except Exception as e: print(f"CombatAIResolver: Error evaluating dialogue condition '{rule.get('name')}': {e}"); condition_met = False
                    if condition_met:
                        threshold_type = rule.get("threshold_type"); threshold_value = rule.get("threshold_value")
                        if threshold_type == "min_strength" and relationship_strength >= threshold_value:
                            if hasattr(dialogue_manager, 'can_start_dialogue') and dialogue_manager.can_start_dialogue(npc, ch_candidate, context=context):
                                return {'type': 'ai_dialogue', 'target_id': ch_candidate.id, 'target_type': 'Character'}

    if curr_loc and location_manager:
        exits = location_manager.get_connected_locations(str(curr_loc))
        dest_location_id = None
        if exits:
            if isinstance(exits, dict) and exits: dest_location_id = random.choice(list(exits.values()))
            elif isinstance(exits, list) and exits: dest_location_id = random.choice(exits)
            if dest_location_id:
                return {'type': 'move', 'target_location_id': dest_location_id}

    return {'type': 'idle', 'total_duration': None}


async def can_rest(
    npc: "NPC", # Pass NPC object directly
    combat_manager: Optional["CombatManager"], # Pass combat_manager
    context: Dict[str, Any]
) -> bool:
    if combat_manager and hasattr(combat_manager, 'get_combat_by_participant_id'):
        # Assuming get_combat_by_participant_id needs the full context if it uses other managers
        if combat_manager.get_combat_by_participant_id(npc.id, context=context):
            return False
    return True
