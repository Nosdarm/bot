import json
from typing import Dict, Optional, Any, List, Callable, Type # Standard types, changed callable to Callable

# Models
from bot.game.models.event import Event, EventStage
from bot.game.models.character import Character # For passive checks on characters


# Managers (needed for sim logic and OnEnter actions)
from bot.game.managers.character_manager import CharacterManager # For passive checks on characters
from bot.game.managers.location_manager import LocationManager # For passive check env context, and OnEnter
# OTHER MANAGERS needed for sim logic or OnEnter Actions (Add here)
from bot.game.managers.npc_manager import NpcManager # Needed for NPC sim or spawn_npcs
from bot.game.managers.combat_manager import CombatManager # Needed for combat sim or start_combat
from bot.game.managers.time_manager import TimeManager # Example: needed for advancing simulation time
from bot.game.managers.item_manager import ItemManager # ItemManager needed by OnEnter give_item


# Services
from bot.services.openai_service import OpenAIService # For AI descriptions

# Rules and Checkers/Processors (Processor instances owned by SimulationProcessor)
from bot.game.rules.rule_engine import RuleEngine # For passive checks
from bot.game.event_processors.event_condition_checker import EventConditionChecker
from bot.game.event_processors.event_stage_processor import EventStageProcessor


class EventSimulationProcessor:
     # Constructor receives checker and stage processor instances
     def __init__(self, condition_checker: EventConditionChecker, stage_processor: EventStageProcessor):
          self._condition_checker = condition_checker
          self._stage_processor = stage_processor


     # --- Main simulation method called by WorldSimulator ---
     # Needs event object and ALL necessary managers/services/callback passed by WorldSimulator.
     # All manager arguments (character_manager, loc_manager, npc_manager, etc.) are needed if used below.
     async def run_simulation(self,
                              event: Event, # The event object to modify (passed by reference)
                              send_message_callback: Callable, # Callback for messages from simulation, changed callable to Callable

                              # !!! PASS ALL MANAGERS/SERVICES NEEDED HERE !!!
                              character_manager: CharacterManager, # Needs CM
                              loc_manager: LocationManager, # Needs LM
                              rule_engine: RuleEngine, # Needs RE
                              openai_service: OpenAIService, # Needs OAI

                              # Other optional managers needed BY SIM LOGIC OR ONENTER ACTIONS
                              npc_manager: Optional[NpcManager] = None, # Example: For NPC sim or OnEnter spawn_npcs
                              combat_manager: Optional[CombatManager] = None, # Example: For Combat sim or OnEnter start_combat
                              time_manager: Optional[TimeManager] = None, # Example: For time tick
                              item_manager: Optional[ItemManager] = None, # Example: For OnEnter give_item

                             ) -> None:
          """
          Runs a single simulation tick for an active event.
          Updates state, performs passive checks, checks outcome conditions, advances stage.
          Modifies event state. Uses send_message_callback.
          """
          # Event object assumed valid and active. WorldSimulator handles 'event_end' check.

          current_stage = event.get_current_stage()
          if not current_stage: # Check for invalid stage
              event_name_for_log = getattr(event, 'name_i18n', {}).get('en', event.id) # Safe name access
              print(f"Error: Event {event_name_for_log} invalid stage {event.current_stage_id} during simulation.")
              # Error state -> let WorldSimulator/EventManager.end_event handle.
              return


          # --- Handle Improvised Event Simulation (Skip standard logic) ---
          if event.template_id == "improvised_premise_event":
              # Placeholder: Improvised simulation logic (ambient updates, nudges via AI).
              # Needs specific logic for improvised events, probably using time passed (time_manager?), openai_service, send_message_callback.
              event_name_for_log = getattr(event, 'name_i18n', {}).get('en', event.id) # Safe name access
              # print(f"Simulation tick processed (ambient/nudge logic only) for improvised event {event_name_for_log} ({event.id}).")
              return # Skip standard simulation for improvised events


          # --- Standard Template Event Simulation Logic ---
          event_name_for_log = getattr(event, 'name_i18n', {}).get('en', event.id) # Safe name access
          stage_name_for_log = getattr(current_stage, 'name_i18n', {}).get('en', getattr(current_stage, 'id', 'UnknownStage')) # Safe stage name access
          print(f"Simulating tick for template event {event_name_for_log} ({event.id}) stage {stage_name_for_log}...")

          # --- 1. Update State Variables for Simulation (e.g., Increment timer) ---
          state_variables_updated_in_this_tick = False

          if 'timer' in event.state_variables: # Check if timer exists
               event.state_variables['timer'] += 1 # Modify state
               state_variables_updated_in_this_tick = True

          # Add other template sim logic updating state variables (requires managers)


          # --- 2. Perform Passive RuleEngine Checks Triggered by Simulation Tick ---
          passive_check_results: Dict[str, Any] = {} # Results of checks in THIS tick

          # Check for passive simulation checks defined in the current stage template.
          if hasattr(current_stage, 'passive_sim_checks') and isinstance(current_stage.passive_sim_checks, dict):
              for check_def_id, check_definition in current_stage.passive_sim_checks.items():
                   target_param = check_definition.get('target') # 'player_in_focus'/'all_players_in_location'/ID
                   check_type = check_definition.get('check_type') # 'skill', 'attribute' etc.

                   if target_param and check_type:
                       # Resolve targets using managers (character_manager, npc_manager, loc_manager if needed)
                       targets_to_check_ids: List[str] = []
                       # ... resolution logic (as in previous versions of this code block) ...
                       # Example resolution for 'all_players_in_location':
                       if target_param == 'all_players_in_location' and character_manager:
                            # Assuming event.location_id is the instance ID
                            # CharacterManager.get_characters_in_location needs guild_id.
                            # Assuming event object has guild_id
                            if hasattr(event, 'guild_id') and event.guild_id:
                                players_in_location = character_manager.get_characters_in_location(guild_id=str(event.guild_id), location_id=event.location_id)
                                targets_to_check_ids = [p.id for p in players_in_location]
                       # ... other resolution logic ...


                       # Perform check for EACH identified target ID
                       for target_entity_id in targets_to_check_ids:
                           # Needs entity object for check (character_manager or npc_manager)
                           # check_definition includes check params (skill_name, complexity, modifiers)
                           # Need context modifiers (loc_manager for env, char/npc for status)

                           # ... Perform check using RuleEngine ...
                           # sim_check_result = await rule_engine.perform_check(...)
                           # ... Store results in passive_check_results (as list per check_def_id) ...
                           print(f"Template Sim: Placeholder: Performing passive check '{check_def_id}' for {target_entity_id}.")


          # --- 3. Check for Passive Outcome Triggers ---
          # Use condition checker. Context includes is_simulation, state vars, passive check results.
          context_for_condition_check: Dict[str, Any] = {
               'is_simulation': True,
               'state_variables': event.state_variables,
               'passive_check_results': passive_check_results, # Add collected results
               # Add other sim context if needed by conditions (location object etc)
               'event_object': event,
               'location_object': loc_manager.get_location_instance(str(event.guild_id), event.location_id) if loc_manager and hasattr(event, 'guild_id') and event.guild_id else None, # Use get_location_instance and check guild_id
           }

          triggered_outcome_id = self._condition_checker.check_outcome_conditions(
               event=event,
               stage=current_stage,
               **context_for_condition_check
           )


          # --- 4. If an outcome condition IS met -> ADVANCE STAGE ---
          if triggered_outcome_id and triggered_outcome_id in current_stage.outcomes:
               next_stage_event_outcome = current_stage.outcomes.get(triggered_outcome_id) # This is an EventOutcome object
               if next_stage_event_outcome and hasattr(next_stage_event_outcome, 'next_stage_id') and next_stage_event_outcome.next_stage_id:
                   next_stage_id = next_stage_event_outcome.next_stage_id
                   print(f"Template Sim triggered outcome '{triggered_outcome_id}' -> advance to stage '{next_stage_id}'.")

                   # --- Trigger stage advancement via StageProcessor instance. ---
                   # Pass ALL dependencies required BY StageProcessor and OnEnter actions.
                   # All managers passed TO THIS run_simulation method are needed here.
                   await self._stage_processor.advance_stage(
                       event=event, target_stage_id=next_stage_id,
                       character_manager=character_manager, loc_manager=loc_manager, rule_engine=rule_engine, openai_service=openai_service,
                       send_message_callback=send_message_callback, # Pass callback
                       npc_manager=npc_manager, combat_manager=combat_manager, item_manager=item_manager, time_manager=time_manager, # Optional managers
                       transition_context=context_for_condition_check # Context
                   )
                   state_variables_updated_in_this_tick = True # Advancement signals state change


          # If state variables changed or stage advanced, GameManager saves.


     # Helper method for WorldSimulator to check if simulation processor thinks event is ended.
     def check_if_ended(self, event: Event) -> bool:
        if not event: return False
        return event.current_stage_id == 'event_end'