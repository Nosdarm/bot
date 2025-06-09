import unittest
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game.managers.game_log_manager import GameLogManager
# Assuming DBService and its adapter structure for mocking
# If these are actual classes, they might need to be imported for isinstance checks or type hinting,
# but for pure mocking, string paths or MagicMock can suffice.

class MockPostgresAdapter:
    def __init__(self):
        self.execute = AsyncMock()
        self.fetchall = AsyncMock()

class MockDBService:
    def __init__(self):
        self.adapter = MockPostgresAdapter()

class TestGameLogManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = MockDBService()
        self.game_log_manager = GameLogManager(db_service=self.mock_db_service)

    async def test_log_event_inserts_correct_data(self):
        guild_id = "test_guild_123"
        event_type = "TEST_EVENT"
        details = {"key": "value", "nested": {"data": [1, 2]}}
        player_id = "player_789"
        party_id = "party_abc"
        location_id = "loc_def"
        channel_id = "channel_xyz"
        message_key = "log.test.event"
        message_params = {"param1": "foo", "count": 5}
        involved_entities_ids = ["entity_1", "entity_2"]

        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type=event_type,
            details=details,
            player_id=player_id,
            party_id=party_id,
            location_id=location_id,
            channel_id=channel_id,
            message_key=message_key,
            message_params=message_params,
            involved_entities_ids=involved_entities_ids
        )

        self.mock_db_service.adapter.execute.assert_called_once()
        call_args = self.mock_db_service.adapter.execute.call_args

        sql_statement = call_args[0][0]
        params = call_args[0][1]

        # Check SQL statement structure (basic check)
        self.assertIn("INSERT INTO game_logs", sql_statement)
        self.assertIn("VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)", sql_statement)
        self.assertIn("(id, timestamp, guild_id, player_id, party_id, event_type, message_key, message_params, location_id, involved_entities_ids, details, channel_id)", sql_statement)

        # Check parameters
        self.assertEqual(len(params), 11) # 11 placeholders

        # Param 0: id (should be a UUID string)
        try:
            uuid.UUID(params[0], version=4)
        except ValueError:
            self.fail("First parameter (id) is not a valid UUID4 string.")

        # Param 1: guild_id
        self.assertEqual(params[1], guild_id)
        # Param 2: player_id
        self.assertEqual(params[2], player_id)
        # Param 3: party_id
        self.assertEqual(params[3], party_id)
        # Param 4: event_type
        self.assertEqual(params[4], event_type)
        # Param 5: message_key
        self.assertEqual(params[5], message_key)
        # Param 6: message_params (JSON string)
        self.assertEqual(params[6], json.dumps(message_params))
        # Param 7: location_id
        self.assertEqual(params[7], location_id)
        # Param 8: involved_entities_ids (JSON string)
        self.assertEqual(params[8], json.dumps(involved_entities_ids))
        # Param 9: details (JSON string)
        self.assertEqual(params[9], json.dumps(details))
        # Param 10: channel_id
        self.assertEqual(params[10], channel_id)

    async def test_get_logs_by_guild_fetches_and_returns_data(self):
        guild_id = "test_guild_456"
        limit = 50
        offset = 10

        mock_row_data = [
            {"id": str(uuid.uuid4()), "guild_id": guild_id, "event_type": "EVENT_A", "details": json.dumps({"info": "aaa"}), "timestamp": "2023-01-01T12:00:00Z"},
            {"id": str(uuid.uuid4()), "guild_id": guild_id, "event_type": "EVENT_B", "details": json.dumps({"info": "bbb"}), "timestamp": "2023-01-01T13:00:00Z"},
        ]
        self.mock_db_service.adapter.fetchall.return_value = mock_row_data

        result = await self.game_log_manager.get_logs_by_guild(guild_id=guild_id, limit=limit, offset=offset)

        self.mock_db_service.adapter.fetchall.assert_called_once()
        call_args = self.mock_db_service.adapter.fetchall.call_args
        sql_statement = call_args[0][0]
        params = call_args[0][1]

        expected_sql_start = """
            SELECT id, timestamp, guild_id, player_id, party_id, event_type,
                   message_key, message_params, location_id, involved_entities_ids,
                   details, channel_id
            FROM game_logs
            WHERE guild_id = $1
        """.strip()
        self.assertTrue(sql_statement.strip().startswith(expected_sql_start))
        self.assertIn("ORDER BY timestamp DESC LIMIT $2 OFFSET $3", sql_statement)

        self.assertEqual(params, (guild_id, limit, offset))
        self.assertEqual(result, mock_row_data)

    async def test_get_logs_by_guild_with_event_type_filter(self):
        guild_id = "test_guild_789"
        event_type = "SPECIFIC_EVENT"
        limit = 20
        offset = 0

        self.mock_db_service.adapter.fetchall.return_value = [] # Actual return value not critical for this SQL check

        await self.game_log_manager.get_logs_by_guild(guild_id=guild_id, limit=limit, offset=offset, event_type_filter=event_type)

        self.mock_db_service.adapter.fetchall.assert_called_once()
        call_args = self.mock_db_service.adapter.fetchall.call_args
        sql_statement = call_args[0][0]
        params = call_args[0][1]

        self.assertIn(f"AND event_type = $2", sql_statement)
        self.assertIn(f"ORDER BY timestamp DESC LIMIT $3 OFFSET $4", sql_statement)
        self.assertEqual(params, (guild_id, event_type, limit, offset))

if __name__ == '__main__':
    unittest.main()
