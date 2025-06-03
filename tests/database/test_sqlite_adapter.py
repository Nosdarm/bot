import unittest
import asyncio
import json
import uuid
import time # For checking timestamp differences
from bot.database.sqlite_adapter import SqliteAdapter

class TestSqliteAdapterModerationTables(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Set up an in-memory SQLite database for each test."""
        self.adapter = SqliteAdapter(db_path=":memory:")
        await self.adapter.connect()
        # Ensure all migrations are run (up to LATEST_SCHEMA_VERSION which should be 15)
        await self.adapter.initialize_database()

    async def asyncTearDown(self):
        """Close the database connection after each test."""
        await self.adapter.close()

    async def test_save_and_get_pending_moderation_request(self):
        """Test saving and retrieving a pending moderation request."""
        request_id = str(uuid.uuid4())
        guild_id = "test_guild_1"
        user_id = "test_user_1"
        content_type = "npc"
        data_dict = {"name": "Test NPC", "archetype": "Warrior"}
        data_json = json.dumps(data_dict)

        await self.adapter.save_pending_moderation_request(request_id, guild_id, user_id, content_type, data_json)

        retrieved_request_row = await self.adapter.get_pending_moderation_request(request_id)

        self.assertIsNotNone(retrieved_request_row)
        retrieved_request = dict(retrieved_request_row) # Convert aiosqlite.Row to dict

        self.assertEqual(retrieved_request['id'], request_id)
        self.assertEqual(retrieved_request['guild_id'], guild_id)
        self.assertEqual(retrieved_request['user_id'], user_id)
        self.assertEqual(retrieved_request['content_type'], content_type)
        self.assertEqual(json.loads(retrieved_request['data']), data_dict)
        self.assertEqual(retrieved_request['status'], 'pending')
        self.assertIsNotNone(retrieved_request['created_at'])
        self.assertIsNone(retrieved_request['moderator_id'])
        self.assertIsNone(retrieved_request['moderated_at'])

        # Test getting a non-existent request
        non_existent_request = await self.adapter.get_pending_moderation_request(str(uuid.uuid4()))
        self.assertIsNone(non_existent_request)

    async def test_update_pending_moderation_request(self):
        """Test updating a pending moderation request."""
        request_id = str(uuid.uuid4())
        guild_id = "test_guild_2"
        user_id = "test_user_2"
        content_type = "location"
        data_dict_initial = {"name": "Old Tavern", "description": "A dusty old place."}
        data_json_initial = json.dumps(data_dict_initial)

        await self.adapter.save_pending_moderation_request(request_id, guild_id, user_id, content_type, data_json_initial)

        # 1. Update status and moderator_id
        moderator_id = "moderator_1"
        time_before_update = time.time()
        success_status_update = await self.adapter.update_pending_moderation_request(request_id, 'approved', moderator_id)
        self.assertTrue(success_status_update)

        updated_request_row_1 = await self.adapter.get_pending_moderation_request(request_id)
        self.assertIsNotNone(updated_request_row_1)
        updated_request_1 = dict(updated_request_row_1)
        self.assertEqual(updated_request_1['status'], 'approved')
        self.assertEqual(updated_request_1['moderator_id'], moderator_id)
        self.assertIsNotNone(updated_request_1['moderated_at'])
        self.assertGreaterEqual(updated_request_1['moderated_at'], time_before_update)
        self.assertEqual(json.loads(updated_request_1['data']), data_dict_initial) # Data should be unchanged

        # 2. Update status, moderator_id, and data_json
        data_dict_edited = {"name": "Renovated Tavern", "description": "Sparkling clean!", "new_feature": True}
        data_json_edited = json.dumps(data_dict_edited)
        moderator_id_2 = "moderator_2"
        time_before_edit_update = time.time()

        success_data_update = await self.adapter.update_pending_moderation_request(request_id, 'edited_approved', moderator_id_2, data_json=data_json_edited)
        self.assertTrue(success_data_update)

        updated_request_row_2 = await self.adapter.get_pending_moderation_request(request_id)
        self.assertIsNotNone(updated_request_row_2)
        updated_request_2 = dict(updated_request_row_2)
        self.assertEqual(updated_request_2['status'], 'edited_approved')
        self.assertEqual(updated_request_2['moderator_id'], moderator_id_2)
        self.assertEqual(json.loads(updated_request_2['data']), data_dict_edited)
        self.assertIsNotNone(updated_request_2['moderated_at'])
        self.assertGreaterEqual(updated_request_2['moderated_at'], time_before_edit_update)

        # Test updating a non-existent request
        success_non_existent = await self.adapter.update_pending_moderation_request(str(uuid.uuid4()), 'approved', 'mod_test')
        self.assertFalse(success_non_existent)

    async def test_delete_pending_moderation_request(self):
        """Test deleting a pending moderation request."""
        request_id = str(uuid.uuid4())
        guild_id = "test_guild_3"
        user_id = "test_user_3"
        await self.adapter.save_pending_moderation_request(request_id, guild_id, user_id, "quest", "{}")

        success_delete = await self.adapter.delete_pending_moderation_request(request_id)
        self.assertTrue(success_delete)

        self.assertIsNone(await self.adapter.get_pending_moderation_request(request_id))

        # Test deleting a non-existent request
        success_delete_non_existent = await self.adapter.delete_pending_moderation_request(str(uuid.uuid4()))
        self.assertFalse(success_delete_non_existent)

    async def test_get_pending_requests_by_guild(self):
        """Test retrieving pending requests by guild and status."""
        guild1 = "guild_pending_1"
        guild2 = "guild_pending_2"
        user = "user_multi_guild"

        # Requests for guild1
        req1_g1 = str(uuid.uuid4())
        await self.adapter.save_pending_moderation_request(req1_g1, guild1, user, "npc", "{}", status="pending")
        await asyncio.sleep(0.01) # Ensure different created_at
        req2_g1 = str(uuid.uuid4())
        await self.adapter.save_pending_moderation_request(req2_g1, guild1, user, "location", "{}", status="pending")
        req3_g1 = str(uuid.uuid4()) # approved
        await self.adapter.save_pending_moderation_request(req3_g1, guild1, user, "quest", "{}", status="approved")

        # Requests for guild2
        req1_g2 = str(uuid.uuid4())
        await self.adapter.save_pending_moderation_request(req1_g2, guild2, user, "npc", "{}", status="pending")

        # Get pending for guild1
        pending_g1_rows = await self.adapter.get_pending_requests_by_guild(guild1, status="pending")
        pending_g1 = [dict(r) for r in pending_g1_rows]
        self.assertEqual(len(pending_g1), 2)
        self.assertEqual(pending_g1[0]['id'], req1_g1) # Ordered by created_at ASC
        self.assertEqual(pending_g1[1]['id'], req2_g1)

        # Get approved for guild1
        approved_g1_rows = await self.adapter.get_pending_requests_by_guild(guild1, status="approved")
        approved_g1 = [dict(r) for r in approved_g1_rows]
        self.assertEqual(len(approved_g1), 1)
        self.assertEqual(approved_g1[0]['id'], req3_g1)

        # Get pending for guild2
        pending_g2_rows = await self.adapter.get_pending_requests_by_guild(guild2, status="pending")
        pending_g2 = [dict(r) for r in pending_g2_rows]
        self.assertEqual(len(pending_g2), 1)
        self.assertEqual(pending_g2[0]['id'], req1_g2)

        # Get for non-existent guild or status
        self.assertEqual(len(await self.adapter.get_pending_requests_by_guild("non_existent_guild")), 0)
        self.assertEqual(len(await self.adapter.get_pending_requests_by_guild(guild1, status="non_existent_status")), 0)

    async def test_add_generated_location(self):
        """Test adding a record to generated_locations."""
        # Need a valid location_id from 'locations' table due to FOREIGN KEY.
        # For simplicity, we'll insert a dummy location instance first.
        # This also implicitly tests that the locations table exists from migrations.
        location_id = str(uuid.uuid4())
        guild_id = "gen_loc_guild"
        user_id = "gen_loc_user"

        # Insert dummy location for FK constraint
        # Normally, LocationManager would handle this population.
        # Here, we do it directly for adapter testing.
        # Note: The 'locations' table has name, description etc. as TEXT which can store JSON strings
        # or plain text. The adapter methods for 'locations' are not part of this test suite.
        # We just need a valid FK reference.
        await self.adapter.execute(
            "INSERT INTO locations (id, template_id, name, guild_id, description, exits, state_variables, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (location_id, "dummy_template", "Dummy Location", guild_id, "{}", "{}", "{}", 1)
        )

        await self.adapter.add_generated_location(location_id, guild_id, user_id)

        # Verify by direct select
        row = await self.adapter.fetchone(
            "SELECT location_id, guild_id, user_id FROM generated_locations WHERE location_id = ?", (location_id,)
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["location_id"], location_id)
        self.assertEqual(row["guild_id"], guild_id)
        self.assertEqual(row["user_id"], user_id)

        # Test ON CONFLICT DO NOTHING
        await self.adapter.add_generated_location(location_id, guild_id, "another_user_id_should_not_update")
        row_after_conflict = await self.adapter.fetchone(
            "SELECT user_id FROM generated_locations WHERE location_id = ?", (location_id,)
        )
        self.assertEqual(row_after_conflict["user_id"], user_id) # Should remain the original user_id

if __name__ == '__main__':
    unittest.main()
