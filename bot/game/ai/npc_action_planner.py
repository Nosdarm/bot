import time
import random
from typing import Dict, Any, Optional, List, Union

# Assuming NPC and Character models are accessible for type hinting
# from bot.game.models.npc import NPC # Actual import if NPC class is defined
# from bot.game.models.character import Character # Actual import for Character
# For now, using placeholder type hints if direct import causes issues with subtask runner
NPC = Any
Character = Any

from bot.game.models.action_request import ActionRequest
# Assuming NpcCombatAI is in a path like this, adjust if necessary
from bot.game.ai.npc_combat_ai import NpcCombatAI

class NPCActionPlanner:
    def __init__(self, context_providing_services: Optional[Dict[str, Any]] = None):
        """
        Initializes the NPCActionPlanner.
        context_providing_services: A dictionary of services/managers the planner might need
                                   to make decisions (e.g., rule_engine, relationship_manager).
        """
        self.services = context_providing_services if context_providing_services else {}
        # Example: self.rule_engine = self.services.get('rule_engine')

    async def plan_action(self, npc: NPC, guild_id: str, context: Dict[str, Any]) -> Optional[ActionRequest]:
        """
        Decides the next action for an NPC.

        Args:
            npc: The NPC instance for which to plan an action.
            guild_id: The ID of the guild the NPC belongs to.
            context: Current game context relevant to decision making. This might include:
                - 'combat_instance': If NPC is in combat.
                - 'potential_targets': List of characters/NPCs in combat.
                - 'world_state': Broader information about the game world.
                - 'rules_config': Game rules configuration.
                - 'managers': Access to various game managers.

        Returns:
            An ActionRequest object if an action is decided, otherwise None.
        """
        action_type = "NPC_IDLE" # Default action if nothing else is decided
        action_data = {}
        priority = 50 # Default priority for NPC actions
        delay_seconds = random.uniform(1.0, 5.0) # Default random delay for non-urgent actions

        # --- Combat Action Planning ---
        combat_instance = context.get('combat_instance')
        if combat_instance and combat_instance.is_participant(npc.id):
            potential_targets = context.get('potential_targets', [])

            # Use a simplified version of NpcCombatAI or integrate its logic
            # The NpcCombatAI class itself might need access to similar context.
            # For this integration, we pass the necessary parts of the context to NpcCombatAI.
            npc_combat_ai = NpcCombatAI(npc=npc) # NpcCombatAI expects the NPC object

            # The context for NpcCombatAI needs to be built from the broader context
            # passed to plan_action.
            combat_ai_context = {
                'rules_config': context.get('rules_config'),
                'relationship_manager': self.services.get('relationship_manager'), # Example service
                # Add other managers/data NpcCombatAI expects based on its implementation
                'actor_effective_stats': context.get('npc_effective_stats', {}).get(npc.id),
                'targets_effective_stats': context.get('targets_effective_stats', {}),
                'guild_id': guild_id,
                # Potentially pass character_manager, npc_manager, party_manager if NpcCombatAI uses them directly
            }

            combat_action_choice = npc_combat_ai.get_npc_combat_action(
                combat_instance=combat_instance,
                potential_targets=potential_targets,
                context=combat_ai_context
            )

            if combat_action_choice and combat_action_choice.get("type") != "wait":
                action_type = combat_action_choice.get("type", "NPC_ATTACK").upper() # e.g. ATTACK, CAST_SPELL
                action_data = combat_action_choice # Pass the whole dict as data
                priority = 20 # Combat actions are higher priority
                delay_seconds = random.uniform(0.5, 1.5) # Combat actions are quicker

                # Ensure actor_id is set to the current NPC
                action_data['actor_id'] = npc.id
                if 'target_id' not in action_data and combat_action_choice.get('target'):
                    action_data['target_id'] = combat_action_choice['target'].id

                # Map NpcCombatAI action type to a more generic ActionRequest.action_type if needed
                # For example, NpcCombatAI might return "attack", "cast_spell", "use_ability"
                # These can often be used directly.
                if action_type == "ATTACK":
                    action_type = "NPC_ATTACK" # Example mapping if needed
                elif action_type == "CAST_SPELL":
                    action_type = "NPC_CAST_SPELL"
                # Add more mappings as necessary

                # print(f"NPCActionPlanner: NPC {npc.id} combat action planned: {action_type} with data {action_data}")

            else:
                action_type = "NPC_COMBAT_IDLE" # NPC is in combat but chose to wait or couldn't act
                delay_seconds = random.uniform(1.0, 2.0)
                # print(f"NPCActionPlanner: NPC {npc.id} is in combat but chose to idle/wait.")

        # --- Non-Combat Action Planning (Basic Placeholder) ---
        else:
            # This is where more sophisticated non-combat AI would go.
            # For now, a very simple placeholder:
            # - 20% chance to "wander" (NPC_MOVE to a nearby location)
            # - 80% chance to "idle" (NPC_IDLE)

            # To implement "wander", we'd need access to LocationManager to find adjacent locations.
            # location_manager = self.services.get('location_manager')
            # if location_manager and hasattr(npc, 'current_location_id'):
            #    pass # Wander logic here

            if random.random() < 0.1: # 10% chance to "think" or do something minor
                action_type = "NPC_THINK" # A conceptual action, processor might just log or do nothing
                action_data = {"thought": "Hmm, what to do next?"}
                priority = 90 # Very low priority
                delay_seconds = random.uniform(5.0, 15.0)
                # print(f"NPCActionPlanner: NPC {npc.id} non-combat action: THINK")
            else:
                action_type = "NPC_IDLE"
                action_data = {"reason": "routine_idle"}
                priority = 100 # Lowest priority
                delay_seconds = random.uniform(10.0, 30.0)
                # print(f"NPCActionPlanner: NPC {npc.id} non-combat action: IDLE")

        # Construct the ActionRequest
        execute_at = time.time() + delay_seconds

        # Ensure npc.id is a string if it's not already
        actor_id_str = str(npc.id) if npc and hasattr(npc, 'id') else "unknown_npc"

        return ActionRequest(
            guild_id=str(guild_id), # Ensure guild_id is string
            actor_id=actor_id_str,
            action_type=action_type,
            action_data=action_data,
            priority=priority,
            execute_at=execute_at
            # dependencies, status, result will be handled by scheduler/processor
        )
