import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import uuid

from bot.game.models.global_npc import GlobalNpc as PydanticGlobalNpc
from bot.database.models import GlobalNpc as DBGlobalNpc
from bot.game.managers.global_npc_manager import GlobalNpcManager
# Assuming Location Pydantic model exists for LocationManager mock if needed by tick
from bot.game.models.location import Location as PydanticLocation

class TestGlobalNpcManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = MagicMock()
        self.mock_persistence_manager = MagicMock()
        self.mock_config_service = MagicMock()
        self.mock_location_manager = MagicMock()

        self.manager = GlobalNpcManager(
            db_service=self.mock_db_service,
            persistence_manager=self.mock_persistence_manager,
            config_service=self.mock_config_service,
            location_manager=self.mock_location_manager
        )
        self.mock_session = MagicMock()
        self.mock_db_service.get_session.return_value.__enter__.return_value = self.mock_session

    def _create_sample_db_npc(self, npc_id=None, guild_id=None, **kwargs):
        data = {
            "id": npc_id or str(uuid.uuid4()),
            "guild_id": guild_id or str(uuid.uuid4()),
            "name_i18n": {"en": "Test DB NPC"},
            "description_i18n": {},
            "current_location_id": None,
            "npc_template_id": None,
            "state_variables": {},
            "faction_id": None,
            "is_active": True,
            **kwargs
        }
        return DBGlobalNpc(**data)

    def _create_sample_pydantic_npc(self, npc_id=None, guild_id=None, **kwargs):
        data = {
            "id": npc_id or str(uuid.uuid4()),
            "guild_id": guild_id or str(uuid.uuid4()),
            "name_i18n": {"en": "Test Pydantic NPC"},
            **kwargs  # is_active etc. will use defaults if not provided
        }
        return PydanticGlobalNpc(**data)

    def test_create_global_npc(self):
        pydantic_npc = self._create_sample_pydantic_npc()

        # _map_pydantic_to_db will be called internally
        # self.mock_session.add, self.mock_session.commit, self.mock_session.refresh are called

        created_npc = self.manager.create_global_npc(pydantic_npc)

        self.mock_session.add.assert_called_once()
        self.mock_session.commit.assert_called_once()
        self.mock_session.refresh.assert_called_once()
        self.assertIsNotNone(created_npc)
        self.assertEqual(created_npc.id, pydantic_npc.id)
        self.assertEqual(created_npc.name_i18n, pydantic_npc.name_i18n)

    def test_get_global_npc(self):
        npc_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())
        db_npc = self._create_sample_db_npc(id=npc_id, guild_id=guild_id)

        self.mock_session.get.return_value = db_npc

        retrieved_npc = self.manager.get_global_npc(guild_id, npc_id)

        self.mock_session.get.assert_called_once_with(DBGlobalNpc, npc_id)
        self.assertIsNotNone(retrieved_npc)
        self.assertEqual(retrieved_npc.id, npc_id)
        self.assertEqual(retrieved_npc.guild_id, guild_id)

    def test_get_global_npc_not_found_or_inactive(self):
        npc_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())

        self.mock_session.get.return_value = None
        self.assertIsNone(self.manager.get_global_npc(guild_id, npc_id))

        # Test inactive
        db_npc_inactive = self._create_sample_db_npc(id=npc_id, guild_id=guild_id, is_active=False)
        self.mock_session.get.return_value = db_npc_inactive
        self.assertIsNone(self.manager.get_global_npc(guild_id, npc_id))

        # Test guild mismatch
        db_npc_wrong_guild = self._create_sample_db_npc(id=npc_id, guild_id=str(uuid.uuid4()))
        self.mock_session.get.return_value = db_npc_wrong_guild
        self.assertIsNone(self.manager.get_global_npc(guild_id, npc_id))


    def test_get_global_npcs_by_guild(self):
        guild_id = str(uuid.uuid4())
        db_npc1 = self._create_sample_db_npc(guild_id=guild_id)
        db_npc2 = self._create_sample_db_npc(guild_id=guild_id)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [db_npc1, db_npc2]
        self.mock_session.execute.return_value = mock_result

        npcs_list = self.manager.get_global_npcs_by_guild(guild_id)

        self.mock_session.execute.assert_called_once()
        self.assertEqual(len(npcs_list), 2)
        self.assertEqual(npcs_list[0].id, db_npc1.id)

    async def test_update_global_npc(self): # Changed to async def
        npc_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())

        existing_db_npc = self._create_sample_db_npc(id=npc_id, guild_id=guild_id, name_i18n={"en": "Old Name"})
        self.mock_session.get.return_value = existing_db_npc

        pydantic_update_data = PydanticGlobalNpc(
            id=npc_id,
            guild_id=guild_id,
            name_i18n={"en": "New Name"},
            current_location_id="new_loc"
        )

        # Call the async method
        updated_npc = await self.manager.update_global_npc(npc_id, pydantic_update_data)

        self.mock_session.get.assert_called_with(DBGlobalNpc, npc_id)
        self.mock_session.commit.assert_called_once()
        self.mock_session.refresh.assert_called_once_with(existing_db_npc)

        self.assertIsNotNone(updated_npc)
        self.assertEqual(updated_npc.name_i18n["en"], "New Name")
        self.assertEqual(updated_npc.current_location_id, "new_loc")
        # Check if the actual DB object was modified as expected before commit
        self.assertEqual(existing_db_npc.name_i18n["en"], "New Name")
        self.assertEqual(existing_db_npc.current_location_id, "new_loc")


    def test_delete_global_npc(self):
        npc_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())
        db_npc = self._create_sample_db_npc(id=npc_id, guild_id=guild_id, is_active=True)

        self.mock_session.get.return_value = db_npc

        result = self.manager.delete_global_npc(guild_id, npc_id)

        self.assertTrue(result)
        self.mock_session.commit.assert_called_once()
        self.assertFalse(db_npc.is_active) # Check if is_active was set to False

    async def test_process_tick_patrol_movement(self):
        guild_id = str(uuid.uuid4())
        npc_id = str(uuid.uuid4())

        pydantic_npc = self._create_sample_pydantic_npc(
            id=npc_id,
            guild_id=guild_id,
            current_location_id="loc1",
            state_variables={
                "patrol_points": ["loc1", "loc2", "loc3"],
                "current_patrol_index": 0
            }
        )

        # Mock get_global_npcs_by_guild to return our test NPC
        self.manager.get_global_npcs_by_guild = MagicMock(return_value=[pydantic_npc])

        # Mock update_global_npc as an AsyncMock because it's awaited inside process_tick
        # It should return the npc object that was passed to it, or a new one if desired for the test.
        async def mock_update_npc_side_effect(nid, npc_data):
            return npc_data # Return the modified npc_data
        self.manager.update_global_npc = AsyncMock(side_effect=mock_update_npc_side_effect)


        # Call process_tick
        await self.manager.process_tick(guild_id=guild_id, game_time_delta=1.0, location_manager=self.mock_location_manager)

        # Assertions
        # 1. NPC should reach the current patrol point (loc1), then update index to 1
        # The log message indicates it reached loc1, then index becomes 1.
        # In the next tick, it would move to loc2.
        # For this tick, it arrived at loc1 (was already there), so index should update.
        self.manager.update_global_npc.assert_called_once()
        # Access keyword arguments: call_args is a tuple (pos_args_tuple, kw_args_dict)
        # The method is called as update_global_npc(npc.id, npc_data=npc_object)
        called_kwargs = self.manager.update_global_npc.call_args[1]
        called_npc_arg = called_kwargs['npc_data']


        self.assertEqual(called_npc_arg.state_variables["current_patrol_index"], 1)
        self.assertEqual(called_npc_arg.current_location_id, "loc1") # Still at loc1, but index updated

        # Simulate next tick: move from loc1 to loc2
        pydantic_npc.state_variables["current_patrol_index"] = 1 # Manually set for next phase
        pydantic_npc.current_location_id = "loc1" # Start at loc1, target is loc2
        # Ensure the mock is reset and side effect is reassigned if it matters for this specific call
        self.manager.get_global_npcs_by_guild.return_value = [pydantic_npc] # Re-assign if necessary, though it's the same object
        self.manager.update_global_npc.reset_mock() # Reset call count etc.
        self.manager.update_global_npc.side_effect = mock_update_npc_side_effect # Re-assign side effect

        await self.manager.process_tick(guild_id=guild_id, game_time_delta=1.0, location_manager=self.mock_location_manager)

        self.manager.update_global_npc.assert_called_once()
        called_kwargs_2 = self.manager.update_global_npc.call_args[1]
        called_npc_arg_2 = called_kwargs_2['npc_data']
        self.assertEqual(called_npc_arg_2.current_location_id, "loc2") # Moved to loc2
        self.assertEqual(called_npc_arg_2.state_variables["current_patrol_index"], 1) # Index remains 1 until arrival at loc2 in next tick

    async def test_process_tick_random_movement(self):
        guild_id = str(uuid.uuid4())
        npc_id = str(uuid.uuid4())
        start_loc_id = "start_loc"
        exit_loc_id = "exit_loc"

        pydantic_npc = self._create_sample_pydantic_npc(
            id=npc_id,
            guild_id=guild_id,
            current_location_id=start_loc_id,
            state_variables={"allow_random_move": True}
        )
        self.manager.get_global_npcs_by_guild = MagicMock(return_value=[pydantic_npc])

        async def mock_update_npc_side_effect_random(nid, npc_data):
            return npc_data
        self.manager.update_global_npc = AsyncMock(side_effect=mock_update_npc_side_effect_random)


        # Mock LocationManager's get_location to return a location with an exit
        mock_location_obj = PydanticLocation(id=start_loc_id, guild_id=guild_id, name_i18n={"en":"Start Loc"}, descriptions_i18n={}, exits={"north": {"target_location_id": exit_loc_id}})

        # LocationManager.get_location is async
        self.mock_location_manager.get_location = AsyncMock(return_value=mock_location_obj)

        await self.manager.process_tick(guild_id=guild_id, game_time_delta=1.0, location_manager=self.mock_location_manager)

        self.manager.update_global_npc.assert_called_once()
        called_kwargs_random = self.manager.update_global_npc.call_args[1]
        called_npc_arg_random = called_kwargs_random['npc_data']
        self.assertEqual(called_npc_arg_random.current_location_id, exit_loc_id)


if __name__ == '__main__':
    unittest.main()
