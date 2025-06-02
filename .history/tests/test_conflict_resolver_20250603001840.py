# tests/test_conflict_resolver.py (или similar)
# (Этот код должен быть в ОТДЕЛЬНОМ ФАЙЛЕ)

import asyncio
import json
import traceback
from typing import Any, Dict, List, Optional, Tuple, Union # Imports needed for mocks and test logic

# Import the actual ConflictResolver class
# from bot.game.conflict_resolver import ConflictResolver # Adjust path as needed

# --- Helper mock classes for testing ---
# Define all mock classes needed for the test block

class MockCursor:
    # Simple mock cursor that returns predefined data or None
    def __init__(self, data, keys=None):
        self._data = data
        self._keys = keys if keys is not None else list(range(len(data[0]))) if data else []
        self._index = 0

    async def fetchone(self):
        await asyncio.sleep(0.001) # Simulate async
        if self._index < len(self._data):
            row = self._data[self._index]
            self._index += 1
            return MockRow(dict(zip(self._keys, row))) if self._keys else MockRow(row)
        return None

    async def fetchall(self):
        await asyncio.sleep(0.001) # Simulate async
        if self._data:
            rows = [MockRow(dict(zip(self._keys, row))) if self._keys else MockRow(row) for row in self._data[self._index:]]
            self._index = len(self._data)
            return rows
        return []

    async def execute(self, sql, params=None):
         # Basic execute mock - doesn't need to return anything usually
         print(f"MockCursor Execute: {sql}")
         await asyncio.sleep(0.001)
         return self # Allows chaining like await cursor.execute().fetchone() if needed

    async def close(self):
        await asyncio.sleep(0.001)
        pass

class MockRow:
    # Simple mock for aiosqlite.Row
    def __init__(self, data):
        self._data = data
        if isinstance(data, dict):
            self._keys = list(data.keys())
        elif isinstance(data, (list, tuple)):
             self._keys = list(range(len(data)))
        else:
             self._keys = []


    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        if isinstance(self._data, dict):
            return self._data.get(key, default)
        # Basic handling for list/tuple access by index
        try:
             if isinstance(key, int) and key >= 0 and key < len(self._data):
                  return self._data[key]
             return default
        except (TypeError, IndexError):
             return default


    def keys(self):
        return self._keys

    def __repr__(self):
        return f"MockRow({self._data})"


# Mock the SqliteAdapter with the new methods for testing
class MockSqliteAdapter:
    def __init__(self):
        self._db_pending_conflicts = {} # In-memory dict to simulate pending_conflicts table
        self._db_players = {} # In-memory dict for players (if needed for RuleEngine mock)
        print("MockSqliteAdapter initialized (in-memory).")
        # Add placeholder methods from the SqliteAdapter block
        self.save_pending_conflict = self._mock_save_pending_conflict
        self.get_pending_conflict = self._mock_get_pending_conflict
        self.delete_pending_conflict = self._mock_delete_pending_conflict
        self.get_pending_conflicts_by_guild = self._mock_get_pending_conflicts_by_guild
        # Add base adapter methods needed by the mock methods (or other mocks)
        self.execute = self._mock_execute
        self.fetchone = self._mock_fetchone
        self.fetchall = self._mock_fetchall


    async def _mock_execute(self, sql: str, params: Optional[Union[Tuple, List]] = None):
        # print(f"MockSqliteAdapter: Execute | SQL: {sql} | Params: {params}")
        await asyncio.sleep(0.001)
        # This mock doesn't need to do complex SQL parsing, the mock methods handle the data
        return MockCursor([], []) # Simulate cursor return

    async def _mock_fetchone(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Optional[MockRow]:
        # print(f"MockSqliteAdapter: FetchOne | SQL: {sql} | Params: {params}")
        await asyncio.sleep(0.001)
        # This mock doesn't do SQL parsing, the mock methods handle the data logic before calling this
        # However, if a mock method *uses* fetchone internally, this would need more logic.
        # For now, let's assume the mock methods directly access the internal dicts.
        print("MockSqliteAdapter: Warning: _mock_fetchone called directly, not via a mock method.")
        return None

    async def _mock_fetchall(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> List[MockRow]:
        # print(f"MockSqliteAdapter: FetchAll | SQL: {sql} | Params: {params}")
        await asyncio.sleep(0.001)
        print("MockSqliteAdapter: Warning: _mock_fetchall called directly, not via a mock method.")
        return []


    # Mock implementations of the new SqliteAdapter methods
    async def _mock_save_pending_conflict(self, conflict_id: str, guild_id: str, conflict_data: str) -> None:
         # print(f"MockSqliteAdapter: Mock save_pending_conflict('{conflict_id}', '{guild_id}', data_length={len(conflict_data)})")
         # Simulate upsert
         self._db_pending_conflicts[conflict_id] = {'id': conflict_id, 'guild_id': guild_id, 'conflict_data': conflict_data}
         # print(f"MockSqliteAdapter: Saved/Updated pending conflict {conflict_id} in mock DB.")

    async def _mock_get_pending_conflict(self, conflict_id: str) -> Optional[MockRow]:
         # print(f"MockSqliteAdapter: Mock get_pending_conflict('{conflict_id}')")
         await asyncio.sleep(0.001)
         row_data = self._db_pending_conflicts.get(conflict_id)
         if row_data:
              # print(f"MockSqliteAdapter: Found pending conflict {conflict_id} in mock DB.")
              return MockRow(row_data) # Return a MockRow object
         else:
              # print(f"MockSqliteAdapter: Pending conflict {conflict_id} not found in mock DB.")
              return None

    async def _mock_delete_pending_conflict(self, conflict_id: str) -> None:
         # print(f"MockSqliteAdapter: Mock delete_pending_conflict('{conflict_id}')")
         await asyncio.sleep(0.001)
         if conflict_id in self._db_pending_conflicts:
              del self._db_pending_conflicts[conflict_id]
              # print(f"MockSqliteAdapter: Deleted pending conflict {conflict_id} from mock DB.")
         # else:
              # print(f"MockSqliteAdapter: Delete called for non-existent pending conflict {conflict_id} in mock DB.")

    async def _mock_get_pending_conflicts_by_guild(self, guild_id: str) -> List[MockRow]:
         # print(f"MockSqliteAdapter: Mock get_pending_conflicts_by_guild('{guild_id}')")
         await asyncio.sleep(0.001)
         rows = [MockRow(c) for c in self._db_pending_conflicts.values() if c.get('guild_id') == guild_id]
         # print(f"MockSqliteAdapter: Found {len(rows)} pending conflicts for guild {guild_id}.")
         return rows


# Helper mock class for RuleEngine (assuming async methods)
class MockRuleEngine:
    def __init__(self):
        print("MockRuleEngine initialized.")

    async def resolve_check(self, entity_id: str, entity_type: str, check_type: str, context: Dict[str, Any], target_id: Optional[str] = None, target_type: Optional[str] = None, conflict_details: Dict[str, Any] = None) -> Dict[str, Any]:
        # print(f"MockRuleEngine: Simulating async resolve_check for {entity_type} '{entity_id}', type '{check_type}'...")
        await asyncio.sleep(0.01) # Simulate async delay

        # Simple mock logic: Actor roll is 15, Target roll is 12
        mock_roll = 15 if entity_id.startswith('player1') or entity_id.startswith('player3') else 12 # Bias player1/player3
        outcome = "SUCCESS" if mock_roll >= 10 else "FAILURE"

        return {
            "total_roll_value": mock_roll,
            "is_success": outcome == "SUCCESS",
            "outcome": outcome,
            "description": f"Mock {check_type} for {entity_id}",
            "rolls": [mock_roll - 5],
            "modifier_applied": 5
        }

    async def resolve_dice_roll(self, dice_notation: str) -> Dict[str, Any]:
        # print(f"MockRuleEngine: Simulating async resolve_dice_roll('{dice_notation}')")
        await asyncio.sleep(0.01)
        if dice_notation == "1d2":
             return {"total": 1, "rolls": [1], "modifier_applied": 0} # Always return 1 (actor wins tie)
        return {"total": 1, "rolls": [1], "modifier_applied": 0}

    async def get_game_time(self) -> float:
        """Simulate getting current game time."""
        return asyncio.get_event_loop().time()


# Helper mock class for NotificationService (assuming async methods)
class MockNotificationService:
    def __init__(self):
        print("MockNotificationService initialized.")

    async def send_master_alert(self, conflict_id: str, guild_id: str, message: str, conflict_details: Dict[str, Any]):
        print(f"--- MOCK MASTER NOTIFICATION ({conflict_id} in {guild_id}) ---")
        print(f"Message: {message}")
        # print(f"Conflict Details (partial): Type={conflict_details.get('type')}, Entities={[e['id'] for e in conflict_details.get('involved_entities',[])]}")
        print("--- END MOCK NOTIFICATION ---")
        await asyncio.sleep(0.01)


# --- Test Main Function ---
async def main():
    print("--- Async ConflictResolver Example Usage (Mocked) ---")

    # Mock services and data
    mock_rule_engine = MockRuleEngine()
    mock_db_adapter = MockSqliteAdapter()
    mock_notification_service = MockNotificationService()

    # Simplified rules_config for example (same as before)
    sample_rules_config = {
        "simultaneous_move_to_limited_space": {
            "description": "Two entities attempt to move into the same space that can only occupy one.",
            "manual_resolution_required": False,
            "automatic_resolution": {
                "check_type": "opposed_skill_check",
                "actor_check_details": {"skill_to_use": "agility"},
                "target_check_details": {"skill_to_use": "agility"},
                "outcome_rules": {
                    "higher_wins": True,
                    "tie_breaker_rule": "random",
                    "outcomes": {
                        "actor_wins": {"description": "Actor gets space.", "effects": [{"type": "move_entity", "target": "actor", "location_id": "{space_id}"}, {"type": "fail_action", "target": "target"}]},
                        "target_wins": {"description": "Target gets space.", "effects": [{"type": "move_entity", "target": "target", "location_id": "{space_id}"}, {"type": "fail_action", "target": "actor"}]},
                        "tie": {"description": "Tie breaker applied.", "effects": []}
                    }
                }
            },
             "notification_format": {
                 "message": "Conflict: {actor_id} vs {target_id} for space {space_id}. Result: Auto resolved.",
                 "placeholders": ["actor_id", "target_id", "space_id"]
             }
        },
        "item_dispute": {
            "description": "Two players claim the same item.",
            "manual_resolution_required": True,
             "manual_resolution": {
                "outcomes": {
                    "player1_wins": {"description": "{actor_id} gets the item.", "effects": [{"type": "give_item", "target": "{actor_id}", "item_id": "{item_id}"}, {"type": "notify_player", "target": "{target_id}", "message": "You lost the item dispute."}]},
                    "player2_wins": {"description": "{target_id} gets the item.", "effects": [{"type": "give_item", "target": "{target_id}", "item_id": "{item_id}"}, {"type": "notify_player", "target": "{actor_id}", "message": "You lost the item dispute."}]},
                    "split_item": {"description": "Master split the item.", "effects": [{"type": "give_item", "target": "{actor_id}", "item_id": "{item_id}_half"}, {"type": "give_item", "target": "{target_id}", "item_id": "{item_id}_half"}]}
                }
             },
            "notification_format": {
                "message": "Manual resolution needed (ID: {conflict_id}): Player {actor_id} and Player {target_id} dispute item {item_id} in {location}.",
                "placeholders": ["conflict_id", "actor_id", "target_id", "item_id", "location"]
            }
        }
    }

    # Instantiate the ConflictResolver with mocks
    resolver = ConflictResolver(mock_rule_engine, sample_rules_config, mock_notification_service, mock_db_adapter)

    print("\n--- Testing analyze_actions_for_conflicts (Automatic) ---")
    guild_id_1 = "guild_abc"
    player_actions_auto = {
        "player1": [{"type": "MOVE", "target_space": "X1Y1", "speed": 10}], # Actor in conflict
        "player2": [{"type": "MOVE", "target_space": "X1Y1", "speed": 12}], # Target in conflict
        "player_solo": [{"type": "GATHER", "resource": "wood"}] # Not in conflict
    }
    conflicts_auto = await resolver.analyze_actions_for_conflicts(player_actions_auto, guild_id_1)

    print("\nIdentified/Processed Automatic Conflicts:")
    for c in conflicts_auto:
         print(f"- ID: {c.get('conflict_id')}, Type: {c.get('type')}, Status: {c.get('status')}, Outcome: {c.get('outcome', {}).get('outcome_key')}, Winner: {c.get('outcome', {}).get('winner_id')}")
         # In real code, you'd now queue the effects from c['outcome']['effects'] for application

    print("\n--- Testing analyze_actions_for_conflicts (Manual - simulated) ---")
    guild_id_2 = "guild_xyz"
    # Simulate that an analyzer function (which is not part of ConflictResolver itself)
    # detected an item dispute and created the conflict object.
    
    print("Simulating creation of a manual conflict by a more complete analyzer...")
    manual_conflict_simulated = {
        "guild_id": guild_id_2,
        "type": "item_dispute", # This type is set to manual_resolution_required = True in sample_rules_config
        "involved_entities": [{"id": "player3", "type": "Character"}, {"id": "player4", "type": "Character"}],
        "details": {"item_id": "gold_idol", "location": "altar_room"},
        "status": "identified"
    }
    
    # Pass this simulated conflict object directly to prepare_for_manual_resolution
    prepared_manual_conflict_result = await resolver.prepare_for_manual_resolution(manual_conflict_simulated)
    print("\nPrepared Manual Conflict:")
    print(f"- ID: {prepared_manual_conflict_result.get('conflict_id')}, Status: {prepared_manual_conflict_result.get('status')}")
    print(f"  Message for Master: {prepared_manual_conflict_result.get('details_for_master')}")

    conflict_id_manual = prepared_manual_conflict_result.get('conflict_id')

    print("\n--- Simulating Master Resolution ---")
    if prepared_manual_conflict_result.get('status') == 'awaiting_manual_resolution':
        print(f"Master deciding outcome for conflict {conflict_id_manual}...")
        # Master chooses an outcome defined in rules_config -> item_dispute -> manual_resolution -> outcomes
        master_outcome_type = "player1_wins" # In the context of the conflict, player3 is entity1 ("actor")
        master_resolution_params = {"reason": "Master decided player3 spoke louder"} # Optional params

        final_manual_outcome = await resolver.process_master_resolution(
            conflict_id=conflict_id_manual,
            outcome_type=master_outcome_type,
            params=master_resolution_params
        )
        print("\nFinal Manual Resolution Outcome:")
        print(f"- Success: {final_manual_outcome.get('success')}")
        print(f"- Message: {final_manual_outcome.get('message')}")
        resolution_details = final_manual_outcome.get('resolution_details', {})
        print(f"- Conflict Status: {resolution_details.get('status')}")
        print(f"- Chosen Outcome Key: {resolution_details.get('outcome', {}).get('outcome_key')}")
        print(f"- Effects to Apply: {resolution_details.get('outcome', {}).get('effects')}")

        # Test getting the conflict again (should be gone)
        print(f"\nAttempting to retrieve conflict {conflict_id_manual} from mock DB after resolution...")
        should_be_none = await mock_db_adapter.get_pending_conflict(conflict_id_manual)
        print(f"Result: {should_be_none}")

    print("\n--- End of Async Example Usage ---")


if __name__ == '__main__':
    # This block runs the async example
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"An error occurred during example execution: {e}")
        traceback.print_exc()