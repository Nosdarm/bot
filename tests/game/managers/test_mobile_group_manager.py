import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import uuid

from bot.game.models.mobile_group import MobileGroup as PydanticMobileGroup
from bot.database.models import MobileGroup as DBMobileGroup
from bot.game.managers.mobile_group_manager import MobileGroupManager
from bot.game.models.global_npc import GlobalNpc as PydanticGlobalNpc # For member updates
# Assuming Location Pydantic model exists for LocationManager mock
from bot.game.models.location import Location as PydanticLocation


class TestMobileGroupManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = MagicMock()
        self.mock_persistence_manager = MagicMock()
        self.mock_config_service = MagicMock()
        self.mock_location_manager = MagicMock()
        self.mock_global_npc_manager = MagicMock() # AsyncMock for its methods

        self.manager = MobileGroupManager(
            db_service=self.mock_db_service,
            persistence_manager=self.mock_persistence_manager,
            config_service=self.mock_config_service,
            location_manager=self.mock_location_manager,
            global_npc_manager=self.mock_global_npc_manager
        )
        self.mock_session = MagicMock()
        self.mock_db_service.get_session.return_value.__enter__.return_value = self.mock_session

    def _create_sample_db_group(self, group_id=None, guild_id=None, **kwargs):
        data = {
            "id": group_id or str(uuid.uuid4()),
            "guild_id": guild_id or str(uuid.uuid4()),
            "name_i18n": {"en": "Test DB Group"},
            "description_i18n": {},
            "current_location_id": "loc_start",
            "member_ids": [],
            "destination_location_id": None,
            "state_variables": {},
            "is_active": True,
            **kwargs
        }
        # DBMobileGroup does not take arbitrary kwargs in its constructor typically
        db_group = DBMobileGroup(id=data['id'], guild_id=data['guild_id'], name_i18n=data['name_i18n'])
        for key, value in data.items():
            if hasattr(db_group, key):
                setattr(db_group, key, value)
        return db_group


    def _create_sample_pydantic_group(self, group_id=None, guild_id=None, **kwargs):
        data = {
            "id": group_id or str(uuid.uuid4()),
            "guild_id": guild_id or str(uuid.uuid4()),
            "name_i18n": {"en": "Test Pydantic Group"},
            **kwargs
        }
        return PydanticMobileGroup(**data)

    def test_create_mobile_group(self):
        pydantic_group = self._create_sample_pydantic_group()

        created_group = self.manager.create_mobile_group(pydantic_group)

        self.mock_session.add.assert_called_once()
        self.mock_session.commit.assert_called_once()
        self.mock_session.refresh.assert_called_once()
        self.assertIsNotNone(created_group)
        self.assertEqual(created_group.id, pydantic_group.id)

    def test_get_mobile_group(self):
        group_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())
        db_group = self._create_sample_db_group(id=group_id, guild_id=guild_id)

        self.mock_session.get.return_value = db_group

        retrieved_group = self.manager.get_mobile_group(guild_id, group_id)

        self.mock_session.get.assert_called_once_with(DBMobileGroup, group_id)
        self.assertIsNotNone(retrieved_group)
        self.assertEqual(retrieved_group.id, group_id)

    def test_get_mobile_groups_by_guild(self):
        guild_id = str(uuid.uuid4())
        db_group1 = self._create_sample_db_group(guild_id=guild_id)
        db_group2 = self._create_sample_db_group(guild_id=guild_id)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [db_group1, db_group2]
        self.mock_session.execute.return_value = mock_result

        groups_list = self.manager.get_mobile_groups_by_guild(guild_id)

        self.mock_session.execute.assert_called_once()
        self.assertEqual(len(groups_list), 2)

    def test_update_mobile_group(self):
        group_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())

        existing_db_group = self._create_sample_db_group(id=group_id, guild_id=guild_id, name_i18n={"en": "Old Name"})
        self.mock_session.get.return_value = existing_db_group

        pydantic_update_data = self._create_sample_pydantic_group(
            id=group_id,
            guild_id=guild_id,
            name_i18n={"en": "New Name"},
            current_location_id="new_loc_updated"
        )

        updated_group = self.manager.update_mobile_group(group_id, pydantic_update_data)

        self.mock_session.commit.assert_called_once()
        self.mock_session.refresh.assert_called_once_with(existing_db_group)
        self.assertIsNotNone(updated_group)
        self.assertEqual(updated_group.name_i18n["en"], "New Name")
        self.assertEqual(updated_group.current_location_id, "new_loc_updated")
        self.assertEqual(existing_db_group.name_i18n["en"], "New Name")
        self.assertEqual(existing_db_group.current_location_id, "new_loc_updated")


    def test_delete_mobile_group(self):
        group_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())
        db_group = self._create_sample_db_group(id=group_id, guild_id=guild_id, is_active=True)

        self.mock_session.get.return_value = db_group

        result = self.manager.delete_mobile_group(guild_id, group_id)

        self.assertTrue(result)
        self.mock_session.commit.assert_called_once()
        self.assertFalse(db_group.is_active)

    async def test_process_tick_movement_and_member_update(self):
        guild_id = str(uuid.uuid4())
        group_id = str(uuid.uuid4())
        member_npc_id = str(uuid.uuid4())

        start_loc = "loc_A"
        dest_loc = "loc_B"

        pydantic_group = self._create_sample_pydantic_group(
            id=group_id,
            guild_id=guild_id,
            current_location_id=start_loc,
            destination_location_id=dest_loc,
            member_ids=[member_npc_id]
        )

        mock_member_npc = PydanticGlobalNpc(id=member_npc_id, guild_id=guild_id, name_i18n={"en": "Member"}, current_location_id=start_loc)

        self.manager.get_mobile_groups_by_guild = MagicMock(return_value=[pydantic_group])
        self.manager.update_mobile_group = MagicMock(return_value=pydantic_group)

        # Mock GlobalNpcManager calls (assuming they are async as per previous GlobalNpcManager tests)
        self.mock_global_npc_manager.get_global_npc = AsyncMock(return_value=mock_member_npc)
        self.mock_global_npc_manager.update_global_npc = AsyncMock(return_value=mock_member_npc)

        await self.manager.process_tick(
            guild_id=guild_id,
            game_time_delta=1.0,
            location_manager=self.mock_location_manager, # Passed in kwargs
            global_npc_manager=self.mock_global_npc_manager # Passed in kwargs, though self.global_npc_manager is also used
        )

        # Verify group moved
        self.manager.update_mobile_group.assert_called_once()
        called_group_arg = self.manager.update_mobile_group.call_args[0][1]
        self.assertEqual(called_group_arg.current_location_id, dest_loc)

        # Verify member NPC was fetched and updated
        self.mock_global_npc_manager.get_global_npc.assert_called_once_with(guild_id, member_npc_id)
        self.mock_global_npc_manager.update_global_npc.assert_called_once()
        updated_member_npc_arg = self.mock_global_npc_manager.update_global_npc.call_args[0][1]
        self.assertEqual(updated_member_npc_arg.current_location_id, dest_loc)

    async def test_process_tick_random_destination_setting(self):
        guild_id = str(uuid.uuid4())
        group_id = str(uuid.uuid4())
        start_loc = "loc_current"
        possible_dest_loc = "loc_possible_random_dest"

        pydantic_group = self._create_sample_pydantic_group(
            id=group_id,
            guild_id=guild_id,
            current_location_id=start_loc,
            destination_location_id=None, # No current destination
            state_variables={"allow_random_patrol": True}
        )
        self.manager.get_mobile_groups_by_guild = MagicMock(return_value=[pydantic_group])
        self.manager.update_mobile_group = MagicMock(return_value=pydantic_group)

        # Mock LocationManager's get_all_locations
        mock_loc_current = PydanticLocation(id=start_loc, guild_id=guild_id, name_i18n={"en":"Current"}, descriptions_i18n={})
        mock_loc_dest = PydanticLocation(id=possible_dest_loc, guild_id=guild_id, name_i18n={"en":"Possible Dest"}, descriptions_i18n={})
        self.mock_location_manager.get_all_locations = AsyncMock(return_value=[mock_loc_current, mock_loc_dest])

        await self.manager.process_tick(
            guild_id=guild_id,
            game_time_delta=1.0,
            location_manager=self.mock_location_manager,
            global_npc_manager=self.mock_global_npc_manager
        )

        self.manager.update_mobile_group.assert_called_once()
        called_group_arg = self.manager.update_mobile_group.call_args[0][1]
        self.assertEqual(called_group_arg.destination_location_id, possible_dest_loc)


if __name__ == '__main__':
    unittest.main()
