import random # Added for probabilistic choices
from typing import Any, Dict, List, Optional, Union

# Moved Character and NPC imports outside of TYPE_CHECKING for runtime use
from bot.game.models.character import Character
from bot.game.models.npc import NPC


class NpcCombatAI:
    def __init__(self, npc: NPC): # Type hint NPC directly
        self.npc = npc

    def get_npc_combat_action(
        self,
        combat_instance: Any, # Combat model
        potential_targets: List[Union[Character, NPC]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Determines the NPC's combat action using RuleEngine principles.
        """
        # Extract necessary components from context
        # rule_engine = context.get('rule_engine') # RuleEngine instance
        rules_config = context.get('rules_config') # CoreGameRulesConfig object or dict
        # character_manager = context.get('character_manager')
        # npc_manager = context.get('npc_manager')
        # party_manager = context.get('party_manager')
        relationship_manager = context.get('relationship_manager')
        # guild_id = context.get('guild_id')
        actor_effective_stats = context.get('actor_effective_stats', {})
        targets_effective_stats = context.get('targets_effective_stats', {})

        # --- 1. Target Selection ---
        valid_targets: List[Union[Character, NPC]] = []
        for target_entity_obj in potential_targets:
            if target_entity_obj.id == self.npc.id: # Filter out self
                continue

            target_id = target_entity_obj.id
            target_stats = targets_effective_stats.get(target_id, {})

            # Check if target is alive using effective stats (assuming HP is there)
            # Or use participant data from combat_instance if more reliable for current HP
            target_participant_data = combat_instance.get_participant_data(target_id)
            if not target_participant_data or target_participant_data.hp <= 0:
                print(f"NPC AI: Target {target_id} is incapacitated or not in combat instance.")
                continue

            # Hostility check
            is_hostile = True # Default to hostile
            if relationship_manager:
                # Assuming a method like: relationship_manager.is_hostile(self.npc.id, target_id, guild_id)
                # For now, simplified:
                # if not relationship_manager.are_hostile(self.npc, target_entity_obj):
                #     is_hostile = False
                pass # Placeholder for actual relationship check

            if not is_hostile:
                # print(f"NPC AI: Target {target_id} is not hostile. Skipping.")
                continue

            valid_targets.append(target_entity_obj)

        # Apply targeting rules from rules_config
        chosen_target: Optional[Union[Character, NPC]] = None
        if valid_targets:
            # Placeholder for npc_behavior_rules.targeting_rules
            # Example: target_lowest_hp_percent
            # This would involve iterating through valid_targets and using their effective_stats
            # and current HP from combat_instance.participants

            # Simple default: target first valid target (effectively random if not sorted)
            # or sort by HP like old select_target
            valid_targets.sort(key=lambda t: combat_instance.get_participant_data(t.id).hp if combat_instance.get_participant_data(t.id) else float('inf'))
            chosen_target = valid_targets[0]
            print(f"NPC AI: Chosen target {chosen_target.id} with HP {combat_instance.get_participant_data(chosen_target.id).hp if chosen_target else 'N/A'}")

        # --- 2. Action Selection ---
        if not chosen_target:
            # No valid target found, decide to wait or perform a self-action
            # Placeholder for npc_behavior_rules.action_selection_rules (e.g., heal self)
            print(f"NPC AI: No target found for {self.npc.id}. Action: wait.")
            return {"type": "wait", "actor_id": self.npc.id, "reason": "no_valid_target"}

        # Retrieve NPC's available actions
        # This is a CRITICAL assumption. NPC model needs 'available_actions'
        # Format: [{"action_type": "attack", "weapon_id": "claws", ...}, {"action_type": "spell", "spell_id": "fireball", ...}]
        npc_available_actions = getattr(self.npc, 'available_actions', [])
        if not npc_available_actions:
            # Default to a basic attack if no actions are defined
            print(f"NPC AI: NPC {self.npc.id} has no available_actions defined. Defaulting to basic attack.")
            npc_available_actions = [{"action_type": "attack", "name": "Basic Attack", "weapon_id": "default_npc_weapon"}]

        # Filter actions based on usability (resources, cooldowns, range - using RuleEngine helpers if available)
        # Placeholder for npc_behavior_rules.action_selection_rules
        # Example: use_strongest_attack_if_available, heal_self_if_below_x_hp

        # Consider NPC's own state (e.g., low HP from actor_effective_stats or combat_instance)
        npc_current_hp = combat_instance.get_participant_data(self.npc.id).hp
        npc_max_hp = combat_instance.get_participant_data(self.npc.id).max_hp # Assuming max_hp is on participant data

        # Simplistic action choice: first available action that's not self-healing if HP is high,
        # or a healing action if available and HP is low.
        # This needs to be driven by rules_config.npc_behavior_rules.action_selection_rules

        selected_action_dict = None

        # Placeholder for healing logic
        # if npc_current_hp < (npc_max_hp * 0.3): # Example: heal if below 30% HP
        #    for action in npc_available_actions:
        #        if action.get("effect") == "heal_self": # Hypothetical action property
        #            selected_action_dict = action
        #            break
        # if selected_action_dict:
        #     return {
        #         "type": selected_action_dict["action_type"],
        #         "spell_id": selected_action_dict.get("spell_id"), # Or ability_id
        #         "actor_id": self.npc.id,
        #         "target_id": self.npc.id, # Target self for healing
        #         "comment": "AI Heal Self"
        #     }

        # Default to first attack-like action on the chosen target
        for action in npc_available_actions:
            if action.get("action_type") == "attack": # Simplistic: take the first attack action
                selected_action_dict = {
                    "type": "attack",
                    "actor_id": self.npc.id,
                    "target_id": chosen_target.id,
                    "weapon_id": action.get("weapon_id", "default_npc_weapon"), # Ensure weapon_id is included
                    "action_name": action.get("name", "Attack")
                }
                break
            elif action.get("action_type") == "spell": # Or first spell
                 selected_action_dict = {
                    "type": "cast_spell", # Use "cast_spell" for consistency if that's what CombatManager expects
                    "actor_id": self.npc.id,
                    "target_id": chosen_target.id, # Assuming offensive spell
                    "spell_id": action.get("spell_id"),
                    "action_name": action.get("name", "Spell")
                }
                 break

        if not selected_action_dict and npc_available_actions: # Fallback to first action if no attack/spell found
            first_action = npc_available_actions[0]
            action_type = first_action.get("action_type", "unknown_action")
            base_return = {
                "type": action_type,
                "actor_id": self.npc.id,
                "target_id": chosen_target.id, # Default to chosen target
                "action_name": first_action.get("name", "Unknown Action")
            }
            if action_type == "attack": base_return["weapon_id"] = first_action.get("weapon_id")
            elif action_type == "cast_spell": base_return["spell_id"] = first_action.get("spell_id")
            elif action_type == "ability": base_return["ability_id"] = first_action.get("ability_id")
            selected_action_dict = base_return

        if not selected_action_dict:
            # If absolutely no action could be formed (e.g. npc_available_actions was empty initially and not defaulted)
            print(f"NPC AI: Could not determine an action for {self.npc.id}. Action: wait.")
            return {"type": "wait", "actor_id": self.npc.id, "reason": "no_action_available"}

        # --- 3. Stat/Behavior Scaling ---
        # Placeholder for rules_config.npc_behavior_rules.scaling_rules
        # This might adjust the chosen_action (e.g., use a stronger version) or NPC stats temporarily.
        # Example: Check party_level from context if available.
        # party_level = context.get('party_average_level')
        # if party_level and party_level > getattr(self.npc, 'level', 10):
        #     selected_action_dict["comment"] = "Scaled up due to high party level (not implemented)"

        print(f"NPC AI: Action for {self.npc.id}: {selected_action_dict}")
        return selected_action_dict

    # select_target and select_action methods are now effectively replaced by get_npc_combat_action.
    # They can be removed or kept as private helpers if parts of their logic are complex
    # and deemed reusable by get_npc_combat_action in a more refined implementation.
    # For this pass, we'll remove them to avoid confusion.

    def select_movement(
        self,
        target: Optional[Union[Character, NPC]], # Current target
        combat_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Selects a movement action for the NPC.
        For this initial version, NPC will stand still.
        """
        # TODO: Future enhancements:
        # - Check range to target:
        #   - If melee NPC and target is out of range, move towards target.
        #   - If ranged NPC and target is too close, move away (kiting).
        #   - If ranged NPC and target is out of optimal range, adjust position.
        # - Pathfinding:
        #   - Requires map/grid data within combat_context or accessible by NPC.
        #   - Find a path if obstacles block line of sight or direct movement.
        # - Advantageous positioning:
        #   - Move to flank the target.
        #   - Seek cover if available and low on health/threatened.
        #   - Consider environmental hazards or buffs.
        # - Consider NPC role (e.g., sniper stays far, tank engages).

        # Placeholder: NPC does not move or performs a default "stand still" action.
        return {"type": "stand_still", "actor_id": self.npc.id, "reason": "not_implemented"}


print("DEBUG: npc_combat_ai.py module loaded.")
