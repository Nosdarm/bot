from __future__ import annotations
import json
import traceback
import asyncio # Added for asyncio.sleep
import uuid # Added for action_id_log fallback
import time # Added for ActionRequest execute_at
from typing import TYPE_CHECKING, List, Dict, Any, Optional
from collections import defaultdict # Added for process_guild_turn

from bot.game.action_scheduler import GuildActionScheduler
from bot.game.ai.npc_action_planner import NPCActionPlanner
from bot.game.npc_action_processor import NPCActionProcessor
from bot.game.models.action_request import ActionRequest
from bot.game.managers.npc_manager import NpcManager


if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.models.character import Character
    # from bot.game.conflict_resolver import ConflictResolver # Removed
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.services.location_interaction_service import LocationInteractionService
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.equipment_manager import EquipmentManager
    from bot.game.managers.item_manager import ItemManager
    # NpcManager already imported above, ensure it's here if TYPE_CHECKING is used strictly by mypy

# from bot.database.models import PendingConflict # Removed, related to ConflictResolver
from bot.ai.rules_schema import CoreGameRulesConfig

class TurnProcessingService:
    def __init__(self,
                 character_manager: CharacterManager,
                 # conflict_resolver: ConflictResolver, # Removed
                 rule_engine: RuleEngine,
                 game_manager: GameManager,
                 game_log_manager: GameLogManager,
                 character_action_processor: CharacterActionProcessor,
                 combat_manager: CombatManager,
                 location_manager: LocationManager,
                 location_interaction_service: LocationInteractionService,
                 dialogue_manager: DialogueManager,
                 inventory_manager: InventoryManager,
                 equipment_manager: EquipmentManager,
                 item_manager: ItemManager,
                 action_scheduler: GuildActionScheduler, # Added
                 npc_action_planner: NPCActionPlanner,   # Added
                 npc_action_processor: NPCActionProcessor, # Added
                 npc_manager: NpcManager,                # Added
                 settings: Dict[str, Any]):
        self.character_manager = character_manager
        # self.conflict_resolver = conflict_resolver # Removed
        self.rule_engine = rule_engine
        self.game_manager = game_manager
        self.game_log_manager = game_log_manager
        self.character_action_processor = character_action_processor
        self.combat_manager = combat_manager
        self.location_manager = location_manager
        self.location_interaction_service = location_interaction_service
        self.dialogue_manager = dialogue_manager
        self.inventory_manager = inventory_manager
        self.equipment_manager = equipment_manager
        self.item_manager = item_manager
        self.action_scheduler = action_scheduler     # Added
        self.npc_action_planner = npc_action_planner # Added
        self.npc_action_processor = npc_action_processor # Added
        self.npc_manager = npc_manager               # Added
        self.settings = settings
        print("TurnProcessingService initialized with new action scheduling components.")

    async def run_turn_cycle_check(self, guild_id: str) -> None:
        print(f"TurnProcessingService: Starting turn cycle check for guild {guild_id}.")
        details_log1 = {"guild_id": guild_id, "log_message": f"Turn cycle check started for guild {guild_id}."}
        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type="turn_cycle_check_start",
            details=details_log1
        )

        # Process player turns (collects actions and queues them)
        await self.process_player_turns(guild_id)

        # Process the entire guild turn (player and NPC actions from scheduler)
        # Context might be expanded in the future
        context: Dict[str, Any] = {
            'guild_id': guild_id,
            'rule_engine': self.rule_engine, # Pass rule engine for decision making
            'managers': { # Pass relevant managers
                'character_manager': self.character_manager,
                'npc_manager': self.npc_manager,
                'combat_manager': self.combat_manager,
                'location_manager': self.location_manager,
                'item_manager': self.item_manager,
                'inventory_manager': self.inventory_manager,
                'dialogue_manager': self.dialogue_manager,
                'game_log_manager': self.game_log_manager,
                # Add other managers as needed by action processors or planners
            },
            'rules_config': self.rule_engine._rules_data if self.rule_engine else None, # MODIFIED: _rules_data
        }
        await self.process_guild_turn(guild_id, context)

        details_log2 = {"guild_id": guild_id, "log_message": f"Turn cycle check completed for guild {guild_id}."}
        await self.game_log_manager.log_event(
            guild_id=guild_id, event_type="turn_cycle_check_end",
            details=details_log2
        )


    async def process_player_turns(self, guild_id: str) -> Dict[str, Any]:
        print(f"TurnProcessingService: Processing player actions for guild {guild_id} and adding to scheduler.")
        actions_submitted_count = 0

        all_characters_in_guild = self.character_manager.get_all_characters(guild_id) # MODIFIED: Removed await
        if not all_characters_in_guild:
            print(f"TurnProcessingService: No characters found in guild {guild_id} for player turn processing.")
            return {"status": "no_characters", "count": 0}

        for char in all_characters_in_guild:
            # Only process characters who might have actions (e.g., based on status or if they always can submit)
            # For now, let's assume any character might have actions in collected_actions_json
            # or a specific status like 'ожидание_обработки' could be checked here if needed.

            raw_actions_json = getattr(char, 'collected_actions_json', None)
            if raw_actions_json:
                try:
                    player_submitted_actions = json.loads(raw_actions_json)
                    if not isinstance(player_submitted_actions, list):
                        player_submitted_actions = [player_submitted_actions] # Handle single dict case

                    for p_action_data in player_submitted_actions:
                        if not isinstance(p_action_data, dict):
                            print(f"Warning: Invalid action data format for character {char.id}. Expected dict, got {type(p_action_data)}")
                            continue

                        action_id = p_action_data.get("action_id", str(uuid.uuid4()))
                        # Normalize intent_type, ensure it's prefixed for clarity if needed
                        intent_type = p_action_data.get('intent_type', p_action_data.get('intent', 'UNKNOWN')).upper()
                        action_type = f"PLAYER_{intent_type}" # Prefix to distinguish player actions

                        action_request = ActionRequest(
                            action_id=action_id,
                            guild_id=str(guild_id),
                            actor_id=str(char.id),
                            action_type=action_type,
                            action_data=p_action_data, # Store original player submission here
                            priority=p_action_data.get("priority", 10), # Player actions high priority
                            requested_at=time.time(),
                            execute_at=p_action_data.get("execute_at", time.time()), # Allow players to specify future execution
                            dependencies=p_action_data.get("dependencies", [])
                        )
                        self.action_scheduler.add_action(action_request)
                        actions_submitted_count += 1

                    # Clear actions and update status after processing all actions for this char
                    setattr(char, 'collected_actions_json', None) # Clear the raw actions
                    setattr(char, 'current_game_status', 'actions_queued') # New status
                    self.character_manager.mark_character_dirty(guild_id, char.id)

                except json.JSONDecodeError:
                    print(f"Error: Could not parse collected_actions_json for character {char.id} in guild {guild_id}.")
                    # Potentially log this error to player's feedback or game log
                    setattr(char, 'current_game_status', 'action_submission_error')
                    self.character_manager.mark_character_dirty(guild_id, char.id)
                except Exception as e:
                    print(f"Error processing actions for char {char.id}: {e}")
                    traceback.print_exc()
                    setattr(char, 'current_game_status', 'action_processing_error')
                    self.character_manager.mark_character_dirty(guild_id, char.id)

        if actions_submitted_count > 0:
            await self.game_manager.save_game_state_after_action(guild_id) # MODIFIED: reason argument removed
            details_log3 = {"count": actions_submitted_count, "log_message": f"{actions_submitted_count} player actions queued for guild {guild_id}."}
            await self.game_log_manager.log_event(
                guild_id=guild_id,
                event_type="player_actions_queued",
                details=details_log3
            )

        return {"status": "player_actions_submitted", "count": actions_submitted_count}

    async def process_guild_turn(self, guild_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        print(f"TurnProcessingService: Processing full guild turn for {guild_id}")
        turn_results: Dict[str, Any] = {
            "player_actions_processed": 0,
            "npc_actions_planned": 0,
            "npc_actions_processed": 0,
            "errors": []
        }

        # 1. Get and Process Ready Player Actions
        ready_player_actions = self.action_scheduler.get_ready_actions(guild_id)

        # Filter for player actions (actor_id is a player character)
        all_player_character_ids = [c.id for c in self.character_manager.get_all_characters(guild_id)] # MODIFIED: Removed await
        player_actions_to_process = [act for act in ready_player_actions if act.actor_id in all_player_character_ids]

        for action_request in player_actions_to_process:
            self.action_scheduler.update_action_status(guild_id, action_request.action_id, "processing")
            player_char = self.character_manager.get_character(guild_id, action_request.actor_id) # Removed await
            if not player_char:
                err_msg = f"Player character {action_request.actor_id} not found for action {action_request.action_id}."
                print(f"TPS Error: {err_msg}")
                turn_results["errors"].append(err_msg)
                self.action_scheduler.update_action_status(guild_id, action_request.action_id, "failed", {"error": err_msg})
                continue

            try:
                # PlayerActionProcessor is self.character_action_processor
                # Build the context for the CharacterActionProcessor if it needs specific things from the broader guild turn context
                player_action_context = {
                    'rules_config': context.get('rules_config'), # Pass rules_config if available in guild_context
                    'guild_id': guild_id,
                    # Add any other specific context CharacterActionProcessor might expect from context dict
                    'channel_id': action_request.action_data.get('channel_id') # Pass original channel_id if available in action_data
                }
                result = await self.character_action_processor.process_action_from_request(
                    action_request=action_request,
                    character=player_char,
                    context=player_action_context
                )

                self.action_scheduler.update_action_status(guild_id, action_request.action_id, "completed", result)
                turn_results["player_actions_processed"] += 1
                if result.get("state_changed", False):
                     await self.game_manager.save_game_state_after_action(guild_id, reason=f"Player action {action_request.action_type}")

                # Update player status (example)
                setattr(player_char, 'current_game_status', 'turn_action_processed') # Example status
                self.character_manager.mark_character_dirty(guild_id, player_char.id)

            except Exception as e:
                err_msg = f"Error processing player action {action_request.action_id} for {player_char.id}: {e}"
                print(f"TPS Error: {err_msg}")
                traceback.print_exc()
                turn_results["errors"].append(err_msg)
                self.action_scheduler.update_action_status(guild_id, action_request.action_id, "failed", {"error": str(e)})

        # 2. Plan NPC Actions for all NPCs in the guild
        all_npcs_in_guild = self.npc_manager.get_all_npcs(guild_id) # MODIFIED: Removed await
        for npc in all_npcs_in_guild:
            # Update context for this specific NPC if needed (e.g., NPC-specific stats)
            # context['current_npc_data'] = npc.some_relevant_attribute
            try:
                # The NPCActionPlanner might need more specific parts of the context.
                # Ensure `context` passed to plan_action has what NPCActionPlanner needs.
                npc_action_request = await self.npc_action_planner.plan_action(npc, guild_id, context)
                if npc_action_request:
                    self.action_scheduler.add_action(npc_action_request)
                    turn_results["npc_actions_planned"] += 1
            except Exception as e:
                err_msg = f"Error planning action for NPC {npc.id}: {e}"
                print(f"TPS Error: {err_msg}")
                traceback.print_exc()
                turn_results["errors"].append(err_msg)

        # 3. Get and Process Ready NPC Actions
        # Potentially re-fetch ready actions if player actions could have unblocked NPC actions immediately
        # Or, if NPC actions planned now are for the *next* processing cycle, this might be separate.
        # For simplicity, let's assume we process NPC actions planned in this same turn.
        ready_npc_actions = self.action_scheduler.get_ready_actions(guild_id)

        # Filter for NPC actions (actor_id is an NPC)
        all_npc_ids = [n.id for n in all_npcs_in_guild] # Re-use from above or re-fetch if necessary
        npc_actions_to_process = [act for act in ready_npc_actions if act.actor_id in all_npc_ids]

        for action_request in npc_actions_to_process:
            self.action_scheduler.update_action_status(guild_id, action_request.action_id, "processing")
            npc_actor = self.npc_manager.get_npc(guild_id, action_request.actor_id) # Removed await
            if not npc_actor:
                err_msg = f"NPC {action_request.actor_id} not found for action {action_request.action_id}."
                print(f"TPS Error: {err_msg}")
                turn_results["errors"].append(err_msg)
                self.action_scheduler.update_action_status(guild_id, action_request.action_id, "failed", {"error": err_msg})
                continue

            try:
                # The NPCActionProcessor needs the NPC object and the full context (or relevant parts)
                # Ensure self.npc_action_processor.managers is correctly populated at initialization.
                action_result = await self.npc_action_processor.process_action(action_request, npc_actor) # Pass full context

                self.action_scheduler.update_action_status(guild_id, action_request.action_id, "completed", action_result)
                turn_results["npc_actions_processed"] += 1
                if action_result.get("state_changed", False):
                    await self.game_manager.save_game_state_after_action(guild_id, reason=f"NPC action {action_request.action_type}")

                # Update NPC state if needed (e.g., npc_manager.mark_npc_dirty)
                self.npc_manager.mark_npc_dirty(guild_id, npc_actor.id)

            except Exception as e:
                err_msg = f"Error processing NPC action {action_request.action_id} for {npc_actor.id}: {e}"
                print(f"TPS Error: {err_msg}")
                traceback.print_exc()
                turn_results["errors"].append(err_msg)
                self.action_scheduler.update_action_status(guild_id, action_request.action_id, "failed", {"error": str(e)})

        # 4. Cleanup and Finalization for the turn
        # E.g., remove completed/failed actions from scheduler if they are not meant to persist
        # For now, assume they stay for logging/history until explicitly removed or TTL.

        # Update status for all characters after all actions are processed
        for char_id in all_player_character_ids:
            char_to_update = self.character_manager.get_character(guild_id, char_id) # Removed await
            if char_to_update:
                 # If no specific error status, mark as turn processed.
                if getattr(char_to_update, 'current_game_status', '') not in ['action_submission_error', 'action_processing_error']:
                    setattr(char_to_update, 'current_game_status', 'turn_cycle_complete')
                    self.character_manager.mark_character_dirty(guild_id, char_id)

        await self.game_manager.save_game_state_after_action(guild_id) # MODIFIED: reason argument removed

        details_log4 = turn_results.copy()
        details_log4["log_message"] = f"Guild turn processed for {guild_id}. Results: {json.dumps(turn_results)}"
        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type="guild_turn_processed",
            details=details_log4
        )
        print(f"TurnProcessingService: Guild turn processed for {guild_id}. Results: {turn_results}")
        return turn_results
