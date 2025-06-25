import unittest
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from bot.game.managers.game_log_manager import GameLogManager
from bot.game.ai.narrative_generator import AINarrativeGenerator # Added
from bot.database.models import GameLogEntry as GameLogEntryDB # Import the SQLAlchemy model
# Assuming DBService and its adapter structure for mocking
# If these are actual classes, they might need to be imported for isinstance checks or type hinting,
# but for pure mocking, string paths or MagicMock can suffice.

# Removed MockPostgresAdapter and MockDBService classes

class TestGameLogManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = AsyncMock() # Direct AsyncMock for DBService

        # Setup session mocking
        self.mock_session = AsyncMock(spec=AsyncSession) # This will be the session object yielded by the context manager
        self.mock_session.add = MagicMock()
        self.mock_session.execute = AsyncMock() # Ensure execute is an AsyncMock

        # Factory function to create a new async context manager mock each time get_session is called
        def create_async_session_context_manager(*args, **kwargs):
            context_manager = AsyncMock()
            context_manager.__aenter__ = AsyncMock(return_value=self.mock_session)
            context_manager.__aexit__ = AsyncMock(return_value=None)
            return context_manager

        self.mock_db_service.get_session.side_effect = create_async_session_context_manager

        # Mock session.begin() to also be an async context manager that can be called multiple times if needed
        def create_async_transaction_context_manager(*args, **kwargs):
            transaction_manager = AsyncMock()
            # When session.begin() is entered, it should yield the session (or a transaction object that has an execute method)
            transaction_manager.__aenter__ = AsyncMock(return_value=self.mock_session)
            transaction_manager.__aexit__ = AsyncMock(return_value=None)
            return transaction_manager

        self.mock_session.begin.side_effect = create_async_transaction_context_manager

        self.mock_relationship_processor = AsyncMock()
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

        self.mock_session.add.assert_called_once()
        added_log_entry_instance = self.mock_session.add.call_args[0][0]

        self.assertIsInstance(added_log_entry_instance, GameLogEntryDB)
        try:
            uuid.UUID(added_log_entry_instance.id, version=4)
        except ValueError:
            self.fail("Log entry ID is not a valid UUID4 string.")

        self.assertEqual(added_log_entry_instance.guild_id, guild_id)
        self.assertEqual(added_log_entry_instance.player_id, player_id)
        self.assertEqual(added_log_entry_instance.party_id, party_id)
        self.assertEqual(added_log_entry_instance.event_type, event_type)
        self.assertEqual(added_log_entry_instance.description_key, description_key_val)
        self.assertEqual(json.loads(added_log_entry_instance.description_params_json), description_params_val)
        self.assertEqual(added_log_entry_instance.location_id, location_id)
        self.assertEqual(json.loads(added_log_entry_instance.involved_entities_ids_json), involved_entities_ids)
        self.assertEqual(json.loads(added_log_entry_instance.details_json), details)
        self.assertEqual(added_log_entry_instance.channel_id, channel_id) # channel_id is int in DB model
        self.assertEqual(added_log_entry_instance.source_entity_id, source_entity_id_val)
        self.assertEqual(added_log_entry_instance.source_entity_type, source_entity_type_val)
        self.assertEqual(added_log_entry_instance.target_entity_id, target_entity_id_val)
        self.assertEqual(added_log_entry_instance.target_entity_type, target_entity_type_val)
        # self.assertIsNotNone(added_log_entry_instance.timestamp) # Timestamp is set by DB (NOW())

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

        self.mock_session.add.assert_called_once()
        added_log_entry_instance = self.mock_session.add.call_args[0][0]
        self.assertIsInstance(added_log_entry_instance, GameLogEntryDB)

        logged_details = json.loads(added_log_entry_instance.details_json)
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

        self.mock_session.add.assert_called_once()
        added_log_entry_instance = self.mock_session.add.call_args[0][0]
        self.assertIsInstance(added_log_entry_instance, GameLogEntryDB)

        logged_details = json.loads(added_log_entry_instance.details_json)
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

        self.mock_session.add.assert_called_once()
        added_log_entry_instance = self.mock_session.add.call_args[0][0]
        self.assertIsInstance(added_log_entry_instance, GameLogEntryDB)

        logged_details = json.loads(added_log_entry_instance.details_json)

        self.assertEqual(logged_details["error_test"], True)
        self.assertIn("ai_narrative_en_error", logged_details)
        self.assertIn("Failed to generate narrative for en: AI boom!", logged_details["ai_narrative_en_error"])
        self.assertIn("ai_narrative_ru_error", logged_details) # Should attempt for all configured langs
        self.assertIn("Failed to generate narrative for ru: AI boom!", logged_details["ai_narrative_ru_error"])


if __name__ == '__main__':
    unittest.main()
