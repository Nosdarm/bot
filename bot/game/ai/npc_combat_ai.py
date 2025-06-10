import random # Added for probabilistic choices
from typing import Any, Dict, List, Optional, Union

# Moved Character and NPC imports outside of TYPE_CHECKING for runtime use
from bot.game.models.character import Character
from bot.game.models.npc import NPC


class NpcCombatAI:
    def __init__(self, npc: NPC): # Type hint NPC directly
        self.npc = npc

    def select_target(
        self,
        potential_targets: List[Union[Character, NPC]],
        combat_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Union[Character, NPC]]:
        """
        Selects a target from the list of potential targets.
        Filters out self, dead targets.
        Prioritizes based on lowest HP, with potential difficulty scaling.
        """
        if combat_context is None:
            combat_context = {}

        difficulty_level = combat_context.get('difficulty_level', 1)

        valid_targets: List[Union[Character, NPC]] = []
        for target in potential_targets:
            # 1. Filter out self
            if target is self.npc:
                continue

            # 2. Filter out dead targets
            # Assuming Character has 'hp' and 'is_alive' attribute/method
            # Assuming NPC has 'health' and 'is_alive' attribute/method
            # For now, we'll directly check health/hp.
            # A more robust way would be target.is_alive() if available.
            target_hp = float('-inf') # Default for sorting if hp attribute is missing
            is_alive = False
            if isinstance(target, Character):
                target_hp = getattr(target, 'hp', 0)
                is_alive = getattr(target, 'is_alive', target_hp > 0)
                if callable(is_alive): # if is_alive is a method
                    is_alive = is_alive()
            elif isinstance(target, NPC):
                target_hp = getattr(target, 'health', 0)
                is_alive = getattr(target, 'is_alive', target_hp > 0)
                if callable(is_alive): # if is_alive is a method
                    is_alive = is_alive()

            if not is_alive:
                continue

            # 3. Filter out non-hostile targets (placeholder for future relationship checks)
            # For now, all remaining targets are considered hostile.
            # if combat_context and "relationships":
            #    if not self.npc.is_hostile_towards(target, combat_context["relationships"]):
            #        continue

            valid_targets.append(target)

        if not valid_targets:
            return None

        # Prioritize targets:
        # Simple heuristic: lowest current HP.
        # NPCs might have 'health', Characters might have 'hp'.
        # We'll try to access both, preferring 'hp' then 'health'.
        # Default sort key:
        sort_key = lambda t: getattr(t, 'hp', getattr(t, 'health', float('inf')))

        if difficulty_level >= 3:
            # Higher difficulty logic
            priority_targets: List[Union[Character, NPC]] = []
            character_targets: List[Character] = []
            npc_targets: List[NPC] = []

            for t in valid_targets:
                if isinstance(t, Character):
                    character_targets.append(t)
                elif isinstance(t, NPC):
                    npc_targets.append(t)

            # Conceptual: Prioritize 'healer' or 'mage' roles among Characters if HP not full
            # This requires Character model to have 'role' and 'max_hp' attributes.
            # For now, this is highly conceptual.
            for char_target in character_targets:
                # target_role = getattr(char_target, 'role', None) # Character.role doesn't exist yet
                # For demonstration, let's assume role might be in state_variables
                target_role = getattr(char_target, 'state_variables', {}).get('role')
                target_max_hp = getattr(char_target, 'max_hp', float('inf'))
                current_hp = getattr(char_target, 'hp', 0)

                if target_role in ['healer', 'mage'] and current_hp < target_max_hp : # and current_hp > 0
                    # Comment: Full implementation needs clear role definition and access on Character model
                    # Also, consider if NPC knows target is a healer/mage (e.g. via perception check)
                    priority_targets.append(char_target)

            if priority_targets:
                # Sort priority targets by lowest HP
                priority_targets.sort(key=lambda t: getattr(t, 'hp', getattr(t, 'health', float('inf'))))
                return priority_targets[0]

            # If no specific priority role targets, prefer any Character then NPCs, then by HP
            if character_targets:
                character_targets.sort(key=lambda t: getattr(t, 'hp', float('inf')))
                return character_targets[0]
            elif npc_targets:
                npc_targets.sort(key=lambda t: getattr(t, 'health', float('inf')))
                return npc_targets[0]
            # Fallback if lists were somehow empty despite valid_targets having content initially
            # This shouldn't be reached if valid_targets was not empty.

        # Default or low difficulty: sort all valid_targets by HP
        valid_targets.sort(key=sort_key)
        return valid_targets[0]

    def select_action(
        self,
        target: Optional[Union[Character, NPC]], # Target chosen by select_target
        combat_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Selects an action based on the target and combat context, with difficulty scaling.
        """
        if combat_context is None:
            combat_context = {}
        difficulty_level = combat_context.get('difficulty_level', 1)

        if target is None:
            # TODO: Consider self-heal or buff if difficulty is high and NPC needs it.
            return {"type": "wait", "actor_id": self.npc.id, "reason": "no_target"}

        # High difficulty: chance to use spells/abilities
        if difficulty_level >= 3:
            available_actions = []
            if hasattr(self.npc, 'known_spells') and self.npc.known_spells:
                for spell_id in self.npc.known_spells: # Assuming known_spells is List[str]
                    # TODO: Check spell usability (mana, cooldowns, range, target requirements)
                    # For now, just add them as potential actions
                    available_actions.append({"type": "spell", "id": spell_id})

            if hasattr(self.npc, 'known_abilities') and self.npc.known_abilities:
                for ability_id in self.npc.known_abilities: # Assuming known_abilities is List[str]
                    # TODO: Check ability usability (resources, cooldowns, range, target requirements)
                    available_actions.append({"type": "ability", "id": ability_id})

            if available_actions and random.random() < 0.5: # 50% chance to use a special action
                chosen_special_action_info = random.choice(available_actions)
                action_type = chosen_special_action_info["type"]
                action_id_key = "spell_id" if action_type == "spell" else "ability_id"

                # Comment: Full implementation needs detailed spell/ability objects, not just IDs,
                # to check targeting, effects, and resource costs.
                # Example: spell = self.npc.get_spell_details(chosen_special_action_info["id"])
                # if spell.is_usable_on(target) and self.npc.has_mana(spell.cost): ...

                return {
                    "type": action_type,
                    action_id_key: chosen_special_action_info["id"],
                    "actor_id": self.npc.id,
                    "target_id": target.id, # Assuming all spells/abilities are targeted for now
                    "comment": "Resource/cooldown checks not implemented yet"
                }

        # Default action: basic attack
        # TODO: Future: Check if NPC has multiple weapons or attack types
        return {
            "type": "attack",
            "actor_id": self.npc.id,
            "target_id": target.id,
            "weapon_id": "default_weapon",
        }

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
