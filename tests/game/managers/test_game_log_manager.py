import unittest
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game.managers.game_log_manager import GameLogManager
from bot.game.ai.narrative_generator import AINarrativeGenerator # Added
# Assuming DBService and its adapter structure for mocking
# If these are actual classes, they might need to be imported for isinstance checks or type hinting,
# but for pure mocking, string paths or MagicMock can suffice.

class MockPostgresAdapter:
    def __init__(self):
        self.execute = AsyncMock()
        self.fetchall = AsyncMock()
        self.fetchone = AsyncMock() # Added for get_log_by_id tests

class MockDBService:
    def __init__(self):
        self.adapter = MockPostgresAdapter()

class TestGameLogManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = MockDBService()
        self.mock_relationship_processor = AsyncMock() # Assuming it's used or optional
        self.mock_narrative_generator = AsyncMock(spec=AINarrativeGenerator)
        self.settings = {
            "guilds": {
                "test_guild_123": { # For specific guild tests
                    "narrative_langs": ["en", "ru"],
                    "world_setting": "Test World",
                    "narrative_tone": "Serious"
                },
                 "test_guild_456": {}, # For other tests
                 "test_guild_789": {}
            }
        }
        self.game_log_manager = GameLogManager(
            db_service=self.mock_db_service,
            settings=self.settings,
            relationship_event_processor=self.mock_relationship_processor,
            narrative_generator=self.mock_narrative_generator
        )

    async def test_log_event_inserts_correct_data(self):
        guild_id = "test_guild_123"
        event_type = "TEST_EVENT"
        details = {"key": "value", "nested": {"data": [1, 2]}}
        player_id = "player_789"
        party_id = "party_abc"
        location_id = "loc_def"
        channel_id = "channel_xyz"
        description_key_val = "log.test.event" # Renamed
        description_params_val = {"param1": "foo", "count": 5} # Renamed
        involved_entities_ids = ["entity_1", "entity_2"]
        source_entity_id_val = "source_player_1"
        source_entity_type_val = "PLAYER"
        target_entity_id_val = "target_npc_1"
        target_entity_type_val = "NPC"


        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type=event_type,
            details=details,
            player_id=player_id,
            party_id=party_id,
            location_id=location_id,
            channel_id=channel_id,
            description_key=description_key_val, # Renamed
            description_params=description_params_val, # Renamed
            involved_entities_ids=involved_entities_ids,
            source_entity_id=source_entity_id_val,
            source_entity_type=source_entity_type_val,
            target_entity_id=target_entity_id_val,
            target_entity_type=target_entity_type_val,
            generate_narrative=False # Explicitly disable for this test
        )

        self.mock_db_service.adapter.execute.assert_called_once()
        call_args = self.mock_db_service.adapter.execute.call_args

        sql_statement = call_args[0][0]
        params = call_args[0][1]

        # Check SQL statement structure (basic check)
        self.assertIn("INSERT INTO game_logs", sql_statement)
        self.assertIn("VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)", sql_statement)
        self.assertIn("(id, timestamp, guild_id, player_id, party_id, event_type, description_key, description_params_json, location_id, involved_entities_ids, details, channel_id, source_entity_id, source_entity_type, target_entity_id, target_entity_type)", sql_statement)

        # Check parameters
        self.assertEqual(len(params), 15) # Now 15 placeholders

        # Param 0: id (should be a UUID string)
        try:
            uuid.UUID(params[0], version=4)
        except ValueError:
            self.fail("First parameter (id) is not a valid UUID4 string.")

        self.assertEqual(params[1], guild_id)
        self.assertEqual(params[2], player_id)
        self.assertEqual(params[3], party_id)
        self.assertEqual(params[4], event_type)
        self.assertEqual(params[5], description_key_val) # description_key
        self.assertEqual(params[6], json.dumps(description_params_val)) # description_params_json
        self.assertEqual(params[7], location_id)
        self.assertEqual(params[8], json.dumps(involved_entities_ids)) # involved_entities_ids_json
        self.assertEqual(params[9], json.dumps(details)) # details_json
        self.assertEqual(params[10], channel_id)
        self.assertEqual(params[11], source_entity_id_val) # source_entity_id
        self.assertEqual(params[12], source_entity_type_val) # source_entity_type
        self.assertEqual(params[13], target_entity_id_val) # target_entity_id
        self.assertEqual(params[14], target_entity_type_val) # target_entity_type

    async def test_get_logs_by_guild_fetches_and_returns_data(self):
        guild_id = "test_guild_456"
        limit = 50
        offset = 10

        mock_row_data = [
            {
                "id": str(uuid.uuid4()), "guild_id": guild_id, "event_type": "EVENT_A",
                "details": json.dumps({"info": "aaa"}), "timestamp": "2023-01-01T12:00:00Z",
                "description_key": "key.a", "description_params_json": json.dumps({"p":1}),
                "source_entity_id": "s1", "source_entity_type": "PLAYER",
                "target_entity_id": "t1", "target_entity_type": "NPC"
            },
            {
                "id": str(uuid.uuid4()), "guild_id": guild_id, "event_type": "EVENT_B",
                "details": json.dumps({"info": "bbb"}), "timestamp": "2023-01-01T13:00:00Z",
                "description_key": "key.b", "description_params_json": json.dumps({"p":2}),
                "source_entity_id": "s2", "source_entity_type": "ITEM",
                "target_entity_id": None, "target_entity_type": None
            },
        ]
        self.mock_db_service.adapter.fetchall.return_value = mock_row_data

        result = await self.game_log_manager.get_logs_by_guild(guild_id=guild_id, limit=limit, offset=offset)

        self.mock_db_service.adapter.fetchall.assert_called_once()
        call_args = self.mock_db_service.adapter.fetchall.call_args
        sql_statement = call_args[0][0]
        params_tuple = call_args[0][1] # Renamed to params_tuple to avoid conflict

        expected_sql_start = """SELECT id, timestamp, guild_id, player_id, party_id, event_type,
                      description_key, description_params_json, location_id,
                      involved_entities_ids, details, channel_id,
                      source_entity_id, source_entity_type, target_entity_id, target_entity_type
               FROM game_logs WHERE guild_id = $1""".strip() # Updated SQL
        self.assertTrue(sql_statement.strip().startswith(expected_sql_start))
        self.assertIn(f"ORDER BY timestamp DESC LIMIT ${len(params_tuple)-1} OFFSET ${len(params_tuple)}", sql_statement) # Adjusted placeholder indices

        self.assertEqual(params_tuple, (guild_id, limit, offset))
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

    async def test_get_log_by_id_fetches_and_returns_data(self):
        guild_id = "test_guild_log_by_id"
        log_id = str(uuid.uuid4())

        mock_row = {
            "id": log_id, "guild_id": guild_id, "event_type": "SINGLE_EVENT",
            "details": json.dumps({"detail": "single_event_info"}), "timestamp": "2023-02-01T10:00:00Z",
            "description_key": "key.single", "description_params_json": json.dumps({"s_param":1}),
            "source_entity_id": "s_single", "source_entity_type": "SYSTEM",
            "target_entity_id": "t_single", "target_entity_type": "GAME_WORLD"
        }
        self.mock_db_service.adapter.fetchone.return_value = mock_row

        result = await self.game_log_manager.get_log_by_id(log_id=log_id, guild_id=guild_id)

        self.mock_db_service.adapter.fetchone.assert_called_once()
        call_args = self.mock_db_service.adapter.fetchone.call_args
        sql_statement = call_args[0][0]
        params_tuple = call_args[0][1]

        expected_sql_start = """SELECT id, timestamp, guild_id, player_id, party_id, event_type,
                      description_key, description_params_json, location_id,
                      involved_entities_ids, details, channel_id,
                      source_entity_id, source_entity_type, target_entity_id, target_entity_type
               FROM game_logs WHERE id = $1 AND guild_id = $2""".strip()
        self.assertEqual(sql_statement.strip(), expected_sql_start) # Exact match for this query
        self.assertEqual(params_tuple, (log_id, guild_id))
        self.assertEqual(result, mock_row)

    async def test_log_event_with_narrative_generation_enabled(self):
        guild_id = "test_guild_123" # Matches settings in setUp
        event_type = "NARRATIVE_EVENT"
        details = {"story_point": "A great discovery"}

        async def narrative_side_effect(event_data, guild_context, lang):
            return f"Narrative in {lang} for {event_data.get('source_name')}"

        self.mock_narrative_generator.generate_narrative_for_event.side_effect = narrative_side_effect

        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type=event_type,
            details=details,
            player_id="narrator_player", # Used as source_name if details["source_name"] is missing
            generate_narrative=True
        )

        self.mock_db_service.adapter.execute.assert_called_once()
        sql_params = self.mock_db_service.adapter.execute.call_args[0][1]
        details_json_param = sql_params[9] # details is param index 9

        logged_details = json.loads(details_json_param)
        self.assertEqual(logged_details["story_point"], "A great discovery")
        self.assertEqual(logged_details["ai_narrative_en"], "Narrative in en for narrator_player")
        self.assertEqual(logged_details["ai_narrative_ru"], "Narrative in ru for narrator_player")

        self.assertEqual(self.mock_narrative_generator.generate_narrative_for_event.call_count, 2)
        # Check one of the calls more thoroughly
        self.mock_narrative_generator.generate_narrative_for_event.assert_any_call(
            event_data={
                "event_type": event_type,
                "source_name": "narrator_player", # from player_id as fallback
                "target_name": None,
                "key_details_str": "{'story_point': 'A great discovery'}" # Fallback details stringification
            },
            guild_context={
                "world_setting": "Test World", # From self.settings
                "tone": "Serious"             # From self.settings
            },
            lang="en" # or "ru"
        )

    async def test_log_event_with_narrative_generation_disabled(self):
        guild_id = "test_guild_123"
        event_type = "NON_NARRATIVE_EVENT"
        details = {"data": "simple_data"}

        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type=event_type,
            details=details,
            generate_narrative=False # Explicitly false
        )

        self.mock_narrative_generator.generate_narrative_for_event.assert_not_called()

        self.mock_db_service.adapter.execute.assert_called_once()
        sql_params = self.mock_db_service.adapter.execute.call_args[0][1]
        details_json_param = sql_params[9]
        logged_details = json.loads(details_json_param)
        self.assertEqual(logged_details["data"], "simple_data")
        self.assertNotIn("ai_narrative_en", logged_details)
        self.assertNotIn("ai_narrative_ru", logged_details)

    async def test_log_event_narrative_generation_fails(self):
        guild_id = "test_guild_123"
        event_type = "FAIL_NARRATIVE_EVENT"
        details = {"error_test": True}

        self.mock_narrative_generator.generate_narrative_for_event.side_effect = Exception("AI boom!")

        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type=event_type,
            details=details,
            generate_narrative=True
        )

        self.mock_db_service.adapter.execute.assert_called_once()
        sql_params = self.mock_db_service.adapter.execute.call_args[0][1]
        details_json_param = sql_params[9]
        logged_details = json.loads(details_json_param)

        self.assertEqual(logged_details["error_test"], True)
        self.assertIn("ai_narrative_en_error", logged_details)
        self.assertIn("Failed to generate narrative for en: AI boom!", logged_details["ai_narrative_en_error"])
        self.assertIn("ai_narrative_ru_error", logged_details) # Should attempt for all configured langs
        self.assertIn("Failed to generate narrative for ru: AI boom!", logged_details["ai_narrative_ru_error"])


if __name__ == '__main__':
    unittest.main()
