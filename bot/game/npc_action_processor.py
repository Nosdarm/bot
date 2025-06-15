from typing import Dict, Any, Optional

# Assuming ActionRequest and NPC models are accessible
from bot.game.models.action_request import ActionRequest
# from bot.game.models.npc import NPC # Actual import
NPC = Any # Placeholder type hint

# Managers that might be needed - these would be injected
# from bot.game.managers.game_log_manager import GameLogManager
# from bot.game.managers.location_manager import LocationManager
# from bot.game.managers.combat_manager import CombatManager
# from bot.game.managers.character_manager import CharacterManager # For target characters
# from bot.game.managers.npc_manager import NpcManager # For target NPCs or self updates
# from bot.game.managers.item_manager import ItemManager
# from bot.game.managers.status_manager import StatusManager

class NPCActionProcessor:
    def __init__(self, managers: Dict[str, Any]):
        """
        Initializes the NPCActionProcessor.

        Args:
            managers: A dictionary containing instances of various game managers
                      (e.g., 'game_log_manager', 'location_manager', 'combat_manager').
        """
        self.managers = managers
        self.game_log_manager = managers.get('game_log_manager')
        self.location_manager = managers.get('location_manager')
        self.combat_manager = managers.get('combat_manager')
        self.character_manager = managers.get('character_manager')
        self.npc_manager = managers.get('npc_manager')
        # Add other managers as needed

    async def process_action(self, action: ActionRequest, npc: NPC) -> Dict[str, Any]:
        """
        Executes the NPC action defined in ActionRequest.action_data.

        Args:
            action: The ActionRequest to process.
            npc: The NPC instance performing the action.

        Returns:
            A result dictionary (e.g., {"success": True, "message": "NPC moved", "state_changed": True}).
        """
        action_type = action.action_type.upper() # Normalize action type
        action_data = action.action_data
        guild_id = action.guild_id
        actor_id = action.actor_id # Should be npc.id

        # Default result
        result = {"success": False, "message": f"Action type '{action_type}' not yet implemented for NPCs.", "state_changed": False}

        try:
            if action_type == "NPC_IDLE":
                result = {"success": True, "message": f"{npc.name} idles.", "state_changed": False}
                if self.game_log_manager:
                    await self.game_log_manager.log_event(
                        guild_id=guild_id,
                        event_type="NPC_ACTION_IDLE",
                        message=f"NPC {npc.name} ({actor_id}) is idle.",
                        details={"actor_id": actor_id, "action_id": action.action_id},
                        # entity_ids, location_id etc. can be added if relevant
                    )

            elif action_type == "NPC_THINK":
                thought = action_data.get("thought", "thinking...")
                result = {"success": True, "message": f"{npc.name} thinks: '{thought}'.", "state_changed": False}
                if self.game_log_manager:
                     await self.game_log_manager.log_event(
                        guild_id=guild_id,
                        event_type="NPC_ACTION_THINK",
                        message=f"NPC {npc.name} ({actor_id}) thinks: {thought}.",
                        details={"actor_id": actor_id, "action_id": action.action_id, "thought": thought},
                    )

            elif action_type == "NPC_MOVE":
                # Simplified move logic, assumes action_data contains 'target_location_id'
                target_location_id = action_data.get('target_location_id')
                if self.location_manager and target_location_id:
                    # In a real scenario, LocationManager.move_npc would handle this
                    # For now, just update npc.current_location_id (if such a field exists)
                    # and log. This is a placeholder for actual movement logic.
                    # old_location_id = npc.current_location_id
                    # npc.current_location_id = target_location_id
                    # if self.npc_manager: self.npc_manager.mark_npc_dirty(guild_id, npc.id)

                    # This part needs actual implementation via LocationManager methods
                    # move_success = await self.location_manager.move_entity_to_location(
                    #    guild_id=guild_id, entity_id=npc.id, entity_type="NPC",
                    #    target_location_id=target_location_id
                    # )
                    # For now, let's assume success for placeholder
                    move_success = True
                    if move_success:
                        result = {"success": True, "message": f"{npc.name} moves to {target_location_id}.", "state_changed": True}
                        if self.game_log_manager:
                            await self.game_log_manager.log_event(
                                guild_id=guild_id, event_type="NPC_ACTION_MOVE",
                                message=f"NPC {npc.name} ({actor_id}) moved to location {target_location_id}.",
                                details={"actor_id": actor_id, "action_id": action.action_id, "target_location_id": target_location_id}
                            )
                    else:
                        result = {"success": False, "message": f"{npc.name} failed to move to {target_location_id}.", "state_changed": False}
                else:
                    result = {"success": False, "message": "NPC_MOVE: Missing target_location_id or location_manager.", "state_changed": False}

            elif action_type in ["NPC_ATTACK", "NPC_CAST_SPELL"]: # Combat actions
                if self.combat_manager:
                    # CombatManager would have a method like handle_combat_action
                    # It would take the actor (NPC), target_id, action_type, specific details (weapon_id, spell_id)
                    # This is a placeholder for a more complex interaction with CombatManager
                    # combat_result = await self.combat_manager.process_npc_action_in_combat(
                    #    guild_id=guild_id,
                    #    npc_actor=npc,
                    #    action_request_data=action_data # Contains target_id, weapon_id/spell_id etc.
                    # )
                    # result = combat_result # combat_result should match the standard result format

                    # Placeholder until CombatManager method is defined:
                    target_id = action_data.get('target_id')
                    weapon_id = action_data.get('weapon_id')
                    spell_id = action_data.get('spell_id')
                    action_name = action_data.get('action_name', action_type)

                    # Simulate finding target (could be Character or another NPC)
                    target_name = f"target {target_id}" # Placeholder
                    # if self.character_manager and await self.character_manager.get_character(guild_id, target_id):
                    #    target_name = (await self.character_manager.get_character(guild_id, target_id)).name
                    # elif self.npc_manager and await self.npc_manager.get_npc(guild_id, target_id):
                    #    target_name = (await self.npc_manager.get_npc(guild_id, target_id)).name

                    log_message = f"NPC {npc.name} ({actor_id}) performs {action_name} on {target_name}."
                    if weapon_id: log_message += f" (Weapon: {weapon_id})"
                    if spell_id: log_message += f" (Spell: {spell_id})"

                    result = {"success": True, "message": log_message, "state_changed": True} # Assume combat always changes state

                    if self.game_log_manager:
                        await self.game_log_manager.log_event(
                            guild_id=guild_id, event_type=f"NPC_ACTION_{action_type}",
                            message=log_message,
                            details={**action_data, "actor_id": actor_id, "action_id": action.action_id}
                        )
                else:
                    result = {"success": False, "message": f"{action_type}: Missing combat_manager.", "state_changed": False}

            # Add more action types as they are defined in NPCActionPlanner:
            # elif action_type == "NPC_INTERACT_OBJECT":
            #    ...
            # elif action_type == "NPC_USE_ITEM":
            #    ...

            else:
                # Log that an unhandled action type was received if game_log_manager is available
                if self.game_log_manager:
                    await self.game_log_manager.log_event(
                        guild_id=guild_id,
                        event_type="NPC_ACTION_UNKNOWN",
                        message=f"NPC {npc.name} ({actor_id}) attempted unknown action type '{action_type}'.",
                        details={"actor_id": actor_id, "action_id": action.action_id, "action_type": action_type, "action_data": action_data}
                    )

        except Exception as e:
            # print(f"Error processing NPC action {action.action_id} ({action_type}) for NPC {npc.id}: {e}")
            # traceback.print_exc() # For debugging
            error_message = f"Exception processing action {action_type} for NPC {npc.id}: {str(e)}"
            result = {"success": False, "message": error_message, "state_changed": False, "error": True}
            if self.game_log_manager:
                await self.game_log_manager.log_event(
                    guild_id=guild_id,
                    event_type="NPC_ACTION_ERROR",
                    message=error_message,
                    details={"actor_id": actor_id, "action_id": action.action_id, "action_type": action_type, "exception": str(e)}
                )

        return result
