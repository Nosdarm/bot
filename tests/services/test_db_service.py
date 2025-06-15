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
        # Configure mock adapter properties to mimic SQLiteAdapter behavior for these tests
        self.mock_adapter.supports_returning_id_on_insert = False
        self.mock_adapter.json_column_type_cast = "" # SQLite stores JSON as TEXT, no cast needed
        
        # Patch the SqliteAdapter class to return our mock_adapter instance
        # when DBService tries to create it.
        # This requires knowing where SqliteAdapter is imported and used by DBService.
        # Assuming DBService instantiates SqliteAdapter like: self.adapter = SqliteAdapter(db_path)
        # The patch target should be 'bot.database.sqlite_adapter.SQLiteAdapter' as DBService imports it from there.
        self.sqlite_adapter_patch = patch('bot.database.sqlite_adapter.SQLiteAdapter')
        self.MockSqliteAdapterClass = self.sqlite_adapter_patch.start()
        self.MockSqliteAdapterClass.return_value = self.mock_adapter

        self.db_service = DBService(db_type="sqlite") # Changed db_path to db_type
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
        
        # Verify that execute_insert was called, and check its arguments
        self.mock_adapter.execute_insert.assert_called_once()
        call_args = self.mock_adapter.execute_insert.call_args
        sql_query_passed_to_mock = call_args[0][0]
        sql_params_passed_to_mock = call_args[0][1]

        # Example: check parts of the actual SQL passed to the mock, expecting $ placeholders
        # self.assertIn("INSERT INTO items (id, name, value, details) VALUES ($1, $2, $3, $4)", sql_query_passed_to_mock)
        self.assertTrue(sql_query_passed_to_mock.startswith("INSERT INTO items ("))
        self.assertIn(") VALUES ($1, $2, $3, $4)", sql_query_passed_to_mock) # Check for 4 placeholders
        # Check if all expected columns are mentioned in the SQL query (order agnostic)
        self.assertIn("id", sql_query_passed_to_mock)
        self.assertIn("name", sql_query_passed_to_mock)
        self.assertIn("value", sql_query_passed_to_mock)
        self.assertIn("details", sql_query_passed_to_mock)
        
        # Check that the parameters are correct (order might matter depending on how columns are processed in create_entity)
        # For robustness, ensure all expected values are present in the params tuple
        self.assertIn(expected_id, sql_params_passed_to_mock)
        self.assertIn("Test Item", sql_params_passed_to_mock)
        self.assertIn(100, sql_params_passed_to_mock)
        self.assertIn(json.dumps({"color": "red", "size": "M"}), sql_params_passed_to_mock)


    async def test_create_entity_with_id_provided(self):
        """Test create_entity when ID is provided in data."""
        provided_id = "custom_id_123"
        test_data = {"id": provided_id, "name": "Test Product", "price": 25.50}
        
        # This now calls execute_insert
        returned_id = await self.db_service.create_entity(
            table_name="products",
            data=test_data.copy(),
            id_field="id"
        )
        self.assertEqual(returned_id, provided_id)
        
        self.mock_adapter.execute_insert.assert_called_once() # Changed from execute
        args, _ = self.mock_adapter.execute_insert.call_args # Changed from execute
        sql_query = args[0]
        sql_params = args[1]

        self.assertTrue(sql_query.startswith("INSERT INTO products (id, name, price) VALUES ($1, $2, $3)")) # Changed ? to $N
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
            "SELECT * FROM configurations WHERE id = $1", (entity_id,) # Changed ? to $1
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
            "SELECT * FROM guild_items WHERE id = $1 AND guild_id = $2", (entity_id, guild_id) # Changed ? to $N
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
        # Assertions check for $N placeholders now
        self.assertIn("status = $1", sql_query)
        self.assertIn("inventory_count = $2", sql_query)
        # self.adapter.json_column_type_cast is "", so no ::jsonb
        self.assertIn("config = $3", sql_query)
        self.assertTrue(sql_query.endswith("WHERE id = $4")) # Adjust index based on actual number of SET params

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

        self.assertTrue(sql_query.startswith("UPDATE guild_finances SET value = $1 WHERE id = $2 AND guild_id = $3")) # Changed ? to $N
        self.assertEqual(sql_params, (5000, entity_id, guild_id))


    async def test_delete_entity_success(self):
        """Test delete_entity successfully deletes an entity."""
        entity_id = "entity_to_delete"
        self.mock_adapter.execute.return_value = "DELETE 1" # Simulate successful delete

        success = await self.db_service.delete_entity(
            table_name="records",
            entity_id=entity_id
        )

        self.assertTrue(success)
        self.mock_adapter.execute.assert_called_once_with(
            "DELETE FROM records WHERE id = $1", (entity_id,) # Changed ? to $1
        )

    async def test_delete_entity_with_guild_id(self):
        """Test delete_entity with guild_id constraint."""
        entity_id = "record_xyz"
        guild_id = "archive_guild"
        self.mock_adapter.execute.return_value = "DELETE 1" # Simulate successful delete

        success = await self.db_service.delete_entity(
            table_name="guild_archives",
            entity_id=entity_id,
            guild_id=guild_id
        )
        self.assertTrue(success)
        self.mock_adapter.execute.assert_called_once_with(
            "DELETE FROM guild_archives WHERE id = $1 AND guild_id = $2", (entity_id, guild_id) # Changed ? to $N
        )
        
    async def test_create_entity_handles_db_error(self):
        """Test create_entity handles database execution errors."""
        self.mock_adapter.execute_insert.side_effect = Exception("DB write error") # Changed from execute to execute_insert
        test_data = {"name": "Error Case"}
        # ID will be generated by create_entity. Use a valid UUID format for mocking.
        entity_id_placeholder = "12345678-1234-5678-1234-567812345678"
        # Import the module to patch its logger instance directly
        from bot.services import db_service as db_service_module
        with patch('uuid.uuid4', return_value=uuid.UUID(entity_id_placeholder)):
            with patch.object(db_service_module.logger, 'error') as mock_log_error_on_instance:
                returned_id = await self.db_service.create_entity("error_table", test_data.copy())
        
        self.assertIsNone(returned_id)
        # Check that the error was logged with relevant info
        mock_log_error_on_instance.assert_called_once()

        log_call_args, log_call_kwargs = mock_log_error_on_instance.call_args
        format_string = log_call_args[0]
        log_params = log_call_args[1:]

        self.assertIn("DBService: Error creating entity in table '%s' (ID: %s, Guild: %s): %s", format_string)
        self.assertEqual("error_table", log_params[0])
        self.assertEqual(entity_id_placeholder, log_params[1])
        # self.assertEqual("N/A", log_params[2]) # Guild ID
        self.assertIsInstance(log_params[3], Exception) # The exception instance
        self.assertEqual(str(log_params[3]), "DB write error")
        self.assertTrue(log_call_kwargs.get('exc_info', False))


    async def test_update_entity_handles_db_error(self):
        """Test update_entity handles database execution errors."""
        self.mock_adapter.execute.side_effect = Exception("DB update error")
        from bot.services import db_service as db_service_module
        with patch.object(db_service_module.logger, 'error') as mock_log_error_on_instance:
            success = await self.db_service.update_entity("error_table", "id1", {"name": "Error Update"})

        self.assertFalse(success)
        mock_log_error_on_instance.assert_called_once()
        log_call_args, log_call_kwargs = mock_log_error_on_instance.call_args
        format_string = log_call_args[0]
        log_params = log_call_args[1:]

        self.assertIn("DBService: Error updating entity '%s' in table '%s' (Guild: %s): %s", format_string)
        self.assertEqual("id1", log_params[0])
        self.assertEqual("error_table", log_params[1])
        # self.assertEqual("N/A (or not applicable)", log_params[2]) # Guild ID
        self.assertIsInstance(log_params[3], Exception)
        self.assertEqual(str(log_params[3]), "DB update error")
        self.assertTrue(log_call_kwargs.get('exc_info', False))

    async def test_delete_entity_handles_db_error(self):
        """Test delete_entity handles database execution errors."""
        self.mock_adapter.execute.side_effect = Exception("DB delete error")
        from bot.services import db_service as db_service_module
        with patch.object(db_service_module.logger, 'error') as mock_log_error_on_instance:
            success = await self.db_service.delete_entity("error_table", "id1")

        self.assertFalse(success)
        mock_log_error_on_instance.assert_called_once()
        log_call_args, log_call_kwargs = mock_log_error_on_instance.call_args
        format_string = log_call_args[0]
        log_params = log_call_args[1:]

        self.assertIn("DBService: Error deleting entity '%s' from table '%s' (Guild: %s): %s", format_string)
        self.assertEqual("id1", log_params[0])
        self.assertEqual("error_table", log_params[1])
        # self.assertEqual("N/A (or not applicable)", log_params[2]) # Guild ID
        self.assertIsInstance(log_params[3], Exception)
        self.assertEqual(str(log_params[3]), "DB delete error")
        self.assertTrue(log_call_kwargs.get('exc_info', False))


if __name__ == '__main__':
    unittest.main()
