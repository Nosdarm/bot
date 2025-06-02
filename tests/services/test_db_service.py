import unittest
from unittest.mock import AsyncMock, patch
import json
import uuid

# Assuming aiosqlite.Row can be reasonably mocked or we use dicts directly for _row_to_dict
# If aiosqlite.Row is complex, we might need a more sophisticated mock.
# For now, let's assume _row_to_dict works with dictionary-like objects.

from bot.services.db_service import DBService
# from bot.database.sqlite_adapter import SqliteAdapter # Not strictly needed if only mocking

# Helper to simulate aiosqlite.Row behavior for _row_to_dict if it expects dict(row)
class MockRow(dict):
    def __init__(self, data):
        super().__init__(data)
        # To make dict(row) work as it does with aiosqlite.Row
        # aiosqlite.Row objects can be iterated over yielding column names,
        # and accessed by index or by column name.
        # Our _row_to_dict simply does dict(row), which works if row is already a dict
        # or a mapping.
        pass

class TestDBService(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Set up for each test."""
        # Mock the SqliteAdapter instance within DBService
        self.mock_adapter = AsyncMock() 
        
        # Patch the SqliteAdapter class to return our mock_adapter instance
        # when DBService tries to create it.
        # This requires knowing where SqliteAdapter is imported and used by DBService.
        # Assuming DBService instantiates SqliteAdapter like: self.adapter = SqliteAdapter(db_path)
        # The patch target should be 'bot.services.db_service.SqliteAdapter'
        self.sqlite_adapter_patch = patch('bot.services.db_service.SqliteAdapter')
        self.MockSqliteAdapterClass = self.sqlite_adapter_patch.start()
        self.MockSqliteAdapterClass.return_value = self.mock_adapter

        self.db_service = DBService(db_path=":memory:")
        # Ensure the mock adapter is indeed used
        self.assertIs(self.db_service.adapter, self.mock_adapter)


    async def asyncTearDown(self):
        self.sqlite_adapter_patch.stop()

    async def test_create_entity_without_id_provided(self):
        """Test create_entity when ID is not in data (should generate UUID)."""
        test_data = {"name": "Test Item", "value": 100, "details": {"color": "red", "size": "M"}}
        expected_id = str(uuid.uuid4()) # We'll have to mock uuid.uuid4 if we want to assert this exact ID

        with patch('uuid.uuid4', return_value=uuid.UUID(expected_id)) as mock_uuid:
            returned_id = await self.db_service.create_entity(
                table_name="items",
                data=test_data.copy(), # Pass a copy as the method might modify it
                id_field="id"
            )

        self.assertEqual(returned_id, expected_id)
        mock_uuid.assert_called_once()

        # Check how data was processed for SQL
        # The original test_data should not have 'id' before the call if id_field is 'id'
        # The data passed to execute should include the generated id and serialized JSON
        
        # Expected SQL call construction
        # Columns should be id, name, value, details
        # Values should include the generated ID and json.dumps(test_data['details'])
        
        self.mock_adapter.execute.assert_called_once()
        args, _ = self.mock_adapter.execute.call_args
        
        # args[0] is the SQL string, args[1] is the tuple of parameters
        sql_query = args[0]
        sql_params = args[1]

        self.assertTrue(sql_query.startswith("INSERT INTO items (id, name, value, details) VALUES (?, ?, ?, ?)")) # Order might vary, better check keys
        
        # To make the check robust against column order, we can parse the query or check params carefully
        # For now, let's assume a consistent order or check parameters by content
        self.assertIn(expected_id, sql_params)
        self.assertIn("Test Item", sql_params)
        self.assertIn(100, sql_params)
        self.assertIn(json.dumps({"color": "red", "size": "M"}), sql_params)


    async def test_create_entity_with_id_provided(self):
        """Test create_entity when ID is provided in data."""
        provided_id = "custom_id_123"
        test_data = {"id": provided_id, "name": "Test Product", "price": 25.50}
        
        returned_id = await self.db_service.create_entity(
            table_name="products",
            data=test_data.copy(),
            id_field="id"
        )
        self.assertEqual(returned_id, provided_id)
        
        self.mock_adapter.execute.assert_called_once()
        args, _ = self.mock_adapter.execute.call_args
        sql_query = args[0]
        sql_params = args[1]

        self.assertTrue(sql_query.startswith("INSERT INTO products (id, name, price) VALUES (?, ?, ?)"))
        self.assertIn(provided_id, sql_params)
        self.assertIn("Test Product", sql_params)
        self.assertIn(25.50, sql_params)

    async def test_get_entity_found_with_json_deserialization(self):
        """Test get_entity when entity is found and needs JSON deserialization."""
        entity_id = "entity_abc"
        db_row_data = {
            "id": entity_id,
            "name": "Configured Item",
            "settings": '{"theme": "dark", "features": ["A", "B"]}', # JSON string
            "status": "active"
        }
        # Simulate aiosqlite.Row by wrapping the dict in MockRow or just using the dict
        # if _row_to_dict handles plain dicts from fetchone mock.
        # DBService._row_to_dict will convert a Row to dict. If fetchone returns a dict, it's fine.
        self.mock_adapter.fetchone.return_value = MockRow(db_row_data)

        expected_result = {
            "id": entity_id,
            "name": "Configured Item",
            "settings": {"theme": "dark", "features": ["A", "B"]}, # Deserialized
            "status": "active"
        }

        result = await self.db_service.get_entity(
            table_name="configurations",
            entity_id=entity_id,
            id_field="id"
        )

        self.mock_adapter.fetchone.assert_called_once_with(
            "SELECT * FROM configurations WHERE id = ?", (entity_id,)
        )
        self.assertEqual(result, expected_result)

    async def test_get_entity_with_guild_id(self):
        """Test get_entity with guild_id constraint."""
        entity_id = "entity_xyz"
        guild_id = "guild_123"
        db_row_data = {"id": entity_id, "guild_id": guild_id, "data": "some_value"}
        self.mock_adapter.fetchone.return_value = MockRow(db_row_data)

        result = await self.db_service.get_entity(
            table_name="guild_items",
            entity_id=entity_id,
            guild_id=guild_id,
            id_field="id"
        )
        
        self.mock_adapter.fetchone.assert_called_once_with(
            "SELECT * FROM guild_items WHERE id = ? AND guild_id = ?", (entity_id, guild_id)
        )
        self.assertEqual(result, db_row_data) # Assuming no JSON fields for this test

    async def test_get_entity_not_found(self):
        """Test get_entity when entity is not found."""
        self.mock_adapter.fetchone.return_value = None
        
        result = await self.db_service.get_entity("items", "non_existent_id")
        
        self.assertIsNone(result)
        self.mock_adapter.fetchone.assert_called_once()

    async def test_update_entity_success(self):
        """Test update_entity successfully updates an entity."""
        entity_id = "item_to_update"
        update_data = {
            "status": "inactive",
            "inventory_count": 0,
            "config": {"mode": "manual", "options": [1, 2, 4]}
        }
        
        # Assume execute for UPDATE doesn't return a specific value, but success is no error
        # and potentially rowcount > 0 (though our mock adapter doesn't provide rowcount easily here)
        self.mock_adapter.execute.return_value = None # Or some mock cursor if needed

        success = await self.db_service.update_entity(
            table_name="assets",
            entity_id=entity_id,
            data=update_data.copy() # Pass a copy
        )

        self.assertTrue(success)
        self.mock_adapter.execute.assert_called_once()
        args, _ = self.mock_adapter.execute.call_args
        sql_query = args[0]
        sql_params = args[1]

        # Check query construction (order of SET items might vary)
        self.assertTrue(sql_query.startswith("UPDATE assets SET"))
        self.assertIn("status = ?", sql_query)
        self.assertIn("inventory_count = ?", sql_query)
        self.assertIn("config = ?", sql_query)
        self.assertTrue(sql_query.endswith("WHERE id = ?"))

        # Check params
        self.assertIn("inactive", sql_params)
        self.assertIn(0, sql_params)
        self.assertIn(json.dumps({"mode": "manual", "options": [1, 2, 4]}), sql_params)
        self.assertIn(entity_id, sql_params) # For the WHERE clause

    async def test_update_entity_with_guild_id(self):
        """Test update_entity with guild_id constraint."""
        entity_id = "guild_asset_abc"
        guild_id = "finance_guild"
        update_data = {"value": 5000}

        success = await self.db_service.update_entity(
            table_name="guild_finances",
            entity_id=entity_id,
            data=update_data,
            guild_id=guild_id
        )
        self.assertTrue(success)
        self.mock_adapter.execute.assert_called_once()
        args, _ = self.mock_adapter.execute.call_args
        sql_query = args[0]
        sql_params = args[1]

        self.assertTrue(sql_query.startswith("UPDATE guild_finances SET value = ? WHERE id = ? AND guild_id = ?"))
        self.assertEqual(sql_params, (5000, entity_id, guild_id))


    async def test_delete_entity_success(self):
        """Test delete_entity successfully deletes an entity."""
        entity_id = "entity_to_delete"
        self.mock_adapter.execute.return_value = None # Assume success if no error

        success = await self.db_service.delete_entity(
            table_name="records",
            entity_id=entity_id
        )

        self.assertTrue(success)
        self.mock_adapter.execute.assert_called_once_with(
            "DELETE FROM records WHERE id = ?", (entity_id,)
        )

    async def test_delete_entity_with_guild_id(self):
        """Test delete_entity with guild_id constraint."""
        entity_id = "record_xyz"
        guild_id = "archive_guild"

        success = await self.db_service.delete_entity(
            table_name="guild_archives",
            entity_id=entity_id,
            guild_id=guild_id
        )
        self.assertTrue(success)
        self.mock_adapter.execute.assert_called_once_with(
            "DELETE FROM guild_archives WHERE id = ? AND guild_id = ?", (entity_id, guild_id)
        )
        
    async def test_create_entity_handles_db_error(self):
        """Test create_entity handles database execution errors."""
        self.mock_adapter.execute.side_effect = Exception("DB write error")
        test_data = {"name": "Error Case"}
        
        with patch('builtins.print') as mock_print: # Suppress print
            returned_id = await self.db_service.create_entity("error_table", test_data)
        
        self.assertIsNone(returned_id)
        mock_print.assert_called_with("Error creating entity in error_table: DB write error")

    async def test_update_entity_handles_db_error(self):
        """Test update_entity handles database execution errors."""
        self.mock_adapter.execute.side_effect = Exception("DB update error")
        
        with patch('builtins.print') as mock_print: # Suppress print
            success = await self.db_service.update_entity("error_table", "id1", {"name": "Error Update"})

        self.assertFalse(success)
        mock_print.assert_called_with("Error updating entity id1 in error_table: DB update error")

    async def test_delete_entity_handles_db_error(self):
        """Test delete_entity handles database execution errors."""
        self.mock_adapter.execute.side_effect = Exception("DB delete error")

        with patch('builtins.print') as mock_print: # Suppress print
            success = await self.db_service.delete_entity("error_table", "id1")

        self.assertFalse(success)
        mock_print.assert_called_with("Error deleting entity id1 from error_table: DB delete error")


if __name__ == '__main__':
    unittest.main()
