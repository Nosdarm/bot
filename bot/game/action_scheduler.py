import time
from typing import Dict, List, Optional, DefaultDict, Any # Added Any here
from collections import defaultdict
import heapq

from bot.game.models.action_request import ActionRequest

class GuildActionScheduler:
    def __init__(self):
        # Stores a list of ActionRequest objects for each guild_id
        # Using a heapq (min-heap) for each guild's queue to efficiently get the next action
        self._action_queues: DefaultDict[str, List[ActionRequest]] = defaultdict(list)
        # For quick lookup of actions by ID, also per guild
        self._action_map: DefaultDict[str, Dict[str, ActionRequest]] = defaultdict(dict)

    def add_action(self, action: ActionRequest) -> None:
        """Adds an action to the appropriate guild's queue and sorts it."""
        if not action.guild_id:
            # Or raise an error, depending on how strict we want to be
            print(f"Error: ActionRequest {action.action_id} is missing guild_id.")
            return

        guild_id = action.guild_id
        heapq.heappush(self._action_queues[guild_id], action)
        self._action_map[guild_id][action.action_id] = action
        # print(f"Scheduler: Added action {action.action_id} for guild {guild_id}. Queue size: {len(self._action_queues[guild_id])}")

    def get_ready_actions(self, guild_id: str) -> List[ActionRequest]:
        """
        Returns a list of actions from the guild's queue whose execute_at time has passed
        and whose dependencies (if any) are met (status="completed").
        Actions are returned sorted by execute_at then priority.
        """
        ready_actions: List[ActionRequest] = []
        pending_actions: List[ActionRequest] = [] # Actions not yet ready or dependencies not met

        if guild_id not in self._action_queues:
            return []

        current_time = time.time()

        # Process the heap for the specific guild
        guild_queue = self._action_queues[guild_id]

        while guild_queue:
            # Peek at the action with the earliest execute_at time
            action = guild_queue[0] # Peek

            if action.execute_at > current_time:
                # If the earliest action is not yet due, none of the subsequent ones will be either (as it's a min-heap)
                # However, we must iterate through all to check for dependencies if some actions could have execute_at in the past
                # but are blocked by dependencies.
                # For strict execute_at ordering, we could break here.
                # Let's assume for now that we check all actions that *could* be ready if not for dependencies.
                # If an action's execute_at is in the future, it's definitely not ready.
                heapq.heappush(pending_actions, heapq.heappop(guild_queue)) # Move to temp list and re-add later
                continue

            # Check dependencies
            dependencies_met = True
            if action.dependencies:
                for dep_action_id in action.dependencies:
                    dependency_action = self._action_map[guild_id].get(dep_action_id)
                    if not dependency_action or dependency_action.status != "completed":
                        dependencies_met = False
                        break

            if dependencies_met:
                # Action is ready, remove from main heap and add to ready_actions
                ready_actions.append(heapq.heappop(guild_queue))
            else:
                # Dependencies not met, or execute_at is in the future. Keep it in a temporary list.
                heapq.heappush(pending_actions, heapq.heappop(guild_queue))

        # Re-add all pending actions back to the main guild queue
        for pa in pending_actions:
            heapq.heappush(guild_queue, pa)

        # Sort ready_actions just in case (though heap processing should largely handle it)
        # The primary sort is already handled by heapq. Here, we ensure that if multiple actions
        # become ready at the same time due to dependency completion, they are still ordered.
        ready_actions.sort()
        return ready_actions

    def update_action_status(self, guild_id: str, action_id: str, status: str, result: Optional[Dict[str, Any]] = None) -> bool:
        """Updates the status and result of an action. Returns True if found and updated, False otherwise."""
        if guild_id in self._action_map and action_id in self._action_map[guild_id]:
            action = self._action_map[guild_id][action_id]
            action.status = status
            if result is not None:
                action.result = result
            # print(f"Scheduler: Updated action {action_id} in guild {guild_id} to status {status}.")

            # If an action is completed or failed/cancelled, it might unblock dependencies.
            # The current get_ready_actions will pick this up on its next call.
            # No need to re-sort the heap here as status change doesn't affect sort order.
            return True
        # print(f"Scheduler: Action {action_id} not found in guild {guild_id} for status update.")
        return False

    def get_action(self, guild_id: str, action_id: str) -> Optional[ActionRequest]:
        """Retrieves a specific action by its ID for a given guild."""
        return self._action_map[guild_id].get(action_id)

    def remove_action(self, guild_id: str, action_id: str) -> bool:
        """Removes an action from the scheduler. Useful for cancellation or after processing non-repeatable actions."""
        action_to_remove = self._action_map[guild_id].pop(action_id, None)
        if action_to_remove:
            try:
                # Removing from a list used as a heap is tricky.
                # The most straightforward way is to rebuild the heap for that guild without the item,
                # or mark the item as "removed" and ignore it in get_ready_actions.
                # For simplicity here, we'll rebuild. This can be optimized if it becomes a bottleneck.
                guild_queue = self._action_queues[guild_id]
                new_queue = [action for action in guild_queue if action.action_id != action_id]
                heapq.heapify(new_queue)
                self._action_queues[guild_id] = new_queue
                # print(f"Scheduler: Removed action {action_id} from guild {guild_id}.")
                return True
            except Exception as e:
                # print(f"Error removing action {action_id} from heap for guild {guild_id}: {e}")
                # Re-add to map if heap removal failed to maintain consistency
                self._action_map[guild_id][action_id] = action_to_remove
                return False
        return False

    def get_all_actions_for_guild(self, guild_id: str) -> List[ActionRequest]:
        """Returns a list of all actions currently in the queue for a specific guild, sorted."""
        if guild_id not in self._action_queues:
            return []

        # The internal queue is a heap, so convert to sorted list for consistent output
        # This is mainly for inspection/debugging.
        sorted_actions = sorted(list(self._action_queues[guild_id]))
        return sorted_actions
