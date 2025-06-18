# NPC Schedule Processing Logic

This document outlines the logic for the `WorldSimulationProcessor` (specifically its `process_world_tick` method or a dedicated sub-processor) to handle NPC schedules defined in `NPC.schedule_json`.

## 1. Prerequisites and Context

*   **`NPC.schedule_json`**: Assumes the structure defined in `documentation/json_structures.md` is available for each NPC.
*   **`TimeManager`**: Must provide the current game time for a specific guild, including:
    *   Day of the week (e.g., "Monday", "Tuesday", or game-specific names).
    *   Current hour (0-23).
    *   Current minute (0-59).
*   **`NpcManager`**:
    *   Provides access to NPCs that have schedules.
    *   Exposes methods to command NPCs (e.g., move to a location, start an activity).
*   **`WorldStateManager` (or `GameManager.get_rule("world_state_flags")`)**: To check conditions for `special_event_overrides`.
*   **`CombatManager`**: To check if an NPC is currently in combat and thus might ignore schedule changes.
*   **`NpcActionProcessor` (or similar logic within `NpcManager`)**: To handle the execution of "activities" (e.g., "work_at_forge" might translate to a sequence of animations, sound effects, or even resource consumption/production over time).

## 2. Logic within `WorldSimulationProcessor.process_world_tick`

This logic should execute for each active guild after the `TimeManager` has updated the game time for that guild.

```python
# Conceptual placement within WorldSimulationProcessor.process_world_tick
# async def process_world_tick(self, guild_id: str, current_time_utc: datetime, game_time_delta: float):
#     # ... other tick processing (weather, economy, event triggers) ...
#
#     await self.process_npc_schedules(guild_id, game_time_delta)
#
# # New method in WorldSimulationProcessor (or called by it)
# async def process_npc_schedules(self, guild_id: str, game_time_delta: float):
#     current_game_time = self.time_manager.get_current_game_time(guild_id) # Needs to return day_of_week, hour, minute
#
#     # Get NPCs that have a schedule defined and are suitable for schedule processing
#     # (e.g., not player-controlled, not in a cutscene, etc.)
#     scheduled_npcs = self.npc_manager.get_npcs_with_schedules(guild_id) # New NpcManager method
#
#     for npc in scheduled_npcs:
#         if not npc.schedule_json:
#             continue
#
#         # Determine the highest priority scheduled entry
#         scheduled_entry = self.determine_current_schedule_entry(
#             npc.schedule_json,
#             current_game_time,
#             guild_id # For checking world state flags
#         )
#
#         if not scheduled_entry: # Should ideally fall back to default if defined
#             continue
#
#         target_location_id = scheduled_entry.get("location_id")
#         target_activity_key = scheduled_entry.get("activity_key")
#
#         # Check if NPC is busy with something critical
#         if self.combat_manager.is_entity_in_combat(npc.id, npc.entity_type, guild_id):
#             # Potentially log: NPC {npc.id} is in combat, skipping scheduled action {target_activity_key}
#             continue
#
#         # Add more checks for other critical actions if NPC.current_action needs evaluation
#         # e.g., if npc.current_action.is_interruptible == False and schedule_priority < action_priority
#
#         # 1. Handle Location Change
#         if target_location_id and npc.location_id != target_location_id:
#             # Instruct NPC to move. The NpcActionProcessor would handle the actual movement.
#             # The target_activity_key can be passed as a goal to pursue upon arrival.
#             await self.npc_manager.initiate_move_to_location(
#                 guild_id, npc.id, target_location_id,
#                 goal_activity_on_arrival=target_activity_key
#             )
#             # Log: NPC {npc.id} moving to {target_location_id} for activity {target_activity_key}
#
#         # 2. Handle Activity Change (if at the target location or no location change needed)
#         elif target_activity_key:
#             # Check if current activity is already the target activity.
#             # This requires NPC model to have a field like `current_activity_key` or for it to be derivable
#             # from `npc.current_action_json`.
#             current_npc_activity = npc.current_activity_key # Assume this field exists or is gettable
#
#             if current_npc_activity != target_activity_key:
#                 await self.npc_manager.initiate_activity(
#                     guild_id, npc.id, target_activity_key, scheduled_entry # Pass full entry for context
#                 )
#                 # Log: NPC {npc.id} at {npc.location_id} starting activity {target_activity_key}
```

## 3. `determine_current_schedule_entry` Logic

This helper method (likely within `WorldSimulationProcessor` or a dedicated `ScheduleService`) would implement the priority logic:

```python
# def determine_current_schedule_entry(self, schedule_json: Dict, current_game_time: GameTime, guild_id: str) -> Optional[Dict]:
#     # 1. Check Special Event Overrides
#     for override in schedule_json.get("special_event_overrides", []):
#         flag_name = override.get("condition_world_flag")
#         expected_value = override.get("expected_value", True)
#         # world_state_active = self.world_state_manager.get_flag_value(guild_id, flag_name)
#         # For MVP, assume direct access or via GameManager.get_rule("world_state_flags")
#         world_state_flags = self.game_manager.get_rule(guild_id, "world_state_flags") # Conceptual
#         current_flag_value = world_state_flags.get(flag_name)
#
#         if current_flag_value == expected_value:
#             # Consider priority field if multiple special events match
#             return override # Assuming highest priority listed first or handled by sorting
#
#     # 2. Check Weekly Schedule for current day
#     day_name = current_game_time.day_of_week_name # e.g., "Monday"
#     if day_name in schedule_json.get("weekly_schedule", {}):
#         day_schedule = schedule_json["weekly_schedule"][day_name]
#         # Find the latest entry whose time is <= current_game_time.time_of_day
#         # This needs careful time comparison (HH:MM strings vs. current hour/minute)
#         # Example: Convert HH:MM to total minutes from midnight for comparison.
#         # current_minutes_past_midnight = current_game_time.hour * 60 + current_game_time.minute
#         # matching_entry = find_latest_time_match(day_schedule, current_minutes_past_midnight)
#         # if matching_entry:
#         #     return matching_entry
#         # Simplified: find first entry for now, assuming exact time match or system implies duration
#         for entry in day_schedule:
#             if self.is_time_match(entry.get("time"), current_game_time): # is_time_match needs to handle HH:MM
                 # More robust: find entry that *starts* at/before current time and is either ongoing
                 # due to duration or is the latest one that started.
#                return entry
#
#     # 3. Check Daily Schedule
#     daily_schedule = schedule_json.get("daily_schedule", [])
#     # matching_entry = find_latest_time_match(daily_schedule, current_minutes_past_midnight)
#     # if matching_entry:
#     #     return matching_entry
#     for entry in daily_schedule:
#         if self.is_time_match(entry.get("time"), current_game_time):
#             return entry
#
#     # 4. Fallback to Default
#     if schedule_json.get("default_activity") and schedule_json.get("default_location_id"):
#         return {
#             "location_id": schedule_json.get("default_location_id"),
#             "activity_key": schedule_json.get("default_activity")
#         }
#     return None # No matching schedule or default
#
# def is_time_match(self, scheduled_time_str: str, current_game_time: GameTime) -> bool:
#    if not scheduled_time_str: return False
#    try:
#        scheduled_hour, scheduled_minute = map(int, scheduled_time_str.split(':'))
#        # This basic match is for the *start* of an activity.
#        # A more complex system would consider durations to see if an activity is ongoing.
#        return scheduled_hour == current_game_time.hour # and scheduled_minute == current_game_time.minute (too granular for simple match)
#    except ValueError:
#        return False # Invalid time format
```
**Note on Time Matching:** The `is_time_match` and overall logic for finding the "current" schedule entry needs to be robust. A common approach is to sort schedule entries by time and find the latest one whose start time is less than or equal to the current time. If entries have durations, the logic would also need to check if the NPC is still within that activity's duration. For MVP, matching the hour might be sufficient if schedules are not too dense.

## 4. Required Manager Modifications/Helpers

*   **`TimeManager`:**
    *   `get_current_game_time(guild_id) -> GameTimeObject`: This object should provide easy access to `day_of_week_name` (string), `hour` (int 0-23), `minute` (int 0-59).
*   **`NpcManager`:**
    *   `get_npcs_with_schedules(guild_id) -> List[NPC]`: Returns a list of NPC objects that have a non-null `schedule_json`.
    *   `initiate_move_to_location(guild_id: str, npc_id: str, target_location_id: str, goal_activity_on_arrival: Optional[str] = None)`: Creates and queues a move action for the NPC. The `NpcActionProcessor` would handle the pathfinding and actual movement. The `goal_activity_on_arrival` tells the NPC what to do once it reaches the destination.
    *   `initiate_activity(guild_id: str, npc_id: str, activity_key: str, schedule_entry_data: Dict)`: Instructs the NPC to begin a new activity. This might involve setting `NPC.current_action_json` to an action like `{"type": "perform_activity", "activity_key": "...", ...}` which `NpcActionProcessor` then interprets. The `schedule_entry_data` can provide full context for the activity.
*   **`NPC` Model (Conceptual Field):**
    *   Consider adding `current_activity_key: Optional[str]` to the NPC model or making it derivable from `current_action_json` to easily check if the NPC is already performing the scheduled activity.
*   **`WorldStateManager` / `GameManager`:**
    *   Easy access to world state flags for checking `special_event_overrides`.

## 5. Considerations

*   **Activity Interruption:** Define clear rules for when a scheduled action can interrupt an NPC's current action (e.g., based on priority of the current action vs. priority of the scheduled activity, or if the NPC is in combat).
*   **Pathfinding:** Movement initiated by schedules relies on the `NpcActionProcessor`'s ability to pathfind and move NPCs between locations.
*   **Activity Definitions:** The `activity_key` values (e.g., "work_at_forge", "patrol_market_district") need to be understood and translated into concrete behaviors by the `NpcActionProcessor`. This might involve a registry or a set of rules for each activity key.
*   **Performance:** Processing schedules for many NPCs every tick could be intensive. Consider optimizations like only processing schedules for NPCs in loaded/active regions or staggering checks.
*   **Durations:** If `duration_minutes` is used, the system needs to track when an activity started to know when it should end, potentially allowing the NPC to revert to `default_activity` or the next scheduled item if the duration expires before a new scheduled time.

This outline provides a foundation for implementing NPC scheduling within the game world.
