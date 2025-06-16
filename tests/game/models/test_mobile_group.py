import unittest
import uuid
from typing import Dict, Any, List

from bot.game.models.mobile_group import MobileGroup

class TestMobileGroupModel(unittest.TestCase):

    def test_mobile_group_instantiation_required(self):
        """Test MobileGroup instantiation with only required fields."""
        guild_id = str(uuid.uuid4())
        name_i18n = {"en": "The Wanderers"}

        group = MobileGroup(guild_id=guild_id, name_i18n=name_i18n)

        self.assertIsNotNone(group.id)
        self.assertEqual(group.guild_id, guild_id)
        self.assertEqual(group.name_i18n, name_i18n)
        self.assertEqual(group.description_i18n, {}) # Default
        self.assertIsNone(group.current_location_id)
        self.assertEqual(group.member_ids, []) # Default
        self.assertIsNone(group.destination_location_id)
        self.assertEqual(group.state_variables, {}) # Default
        self.assertTrue(group.is_active) # Default

    def test_mobile_group_instantiation_all_fields(self):
        """Test MobileGroup instantiation with all fields provided."""
        data: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "guild_id": str(uuid.uuid4()),
            "name_i18n": {"en": "Merchant Caravan", "ru": "Торговый караван"},
            "description_i18n": {"en": "A large caravan carrying goods.", "ru": "Большой караван с товарами."},
            "current_location_id": "loc_city_gates",
            "member_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
            "destination_location_id": "loc_far_town",
            "state_variables": {"cargo_type": "spices", "speed": "normal"},
            "is_active": False
        }
        group = MobileGroup(**data)

        self.assertEqual(group.id, data["id"])
        self.assertEqual(group.guild_id, data["guild_id"])
        self.assertEqual(group.name_i18n, data["name_i18n"])
        self.assertEqual(group.description_i18n, data["description_i18n"])
        self.assertEqual(group.current_location_id, data["current_location_id"])
        self.assertEqual(group.member_ids, data["member_ids"])
        self.assertEqual(group.destination_location_id, data["destination_location_id"])
        self.assertEqual(group.state_variables, data["state_variables"])
        self.assertEqual(group.is_active, data["is_active"])

    def test_name_i18n_not_nullable_init(self):
        """Test that MobileGroup __init__ enforces name_i18n or provides default."""
        guild_id = str(uuid.uuid4())

        # Test with name_i18n missing (should use default from __init__)
        group_missing_name = MobileGroup(guild_id=guild_id)
        self.assertEqual(group_missing_name.name_i18n, {"en": "Default Mobile Group Name"})

        # Test with name_i18n provided as empty dict (should use default from __init__)
        group_empty_name = MobileGroup(guild_id=guild_id, name_i18n={})
        self.assertEqual(group_empty_name.name_i18n, {"en": "Default Mobile Group Name"})


    def test_to_dict(self):
        """Test the to_dict method."""
        group_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())
        member_ids = [str(uuid.uuid4())]
        group = MobileGroup(
            id=group_id,
            guild_id=guild_id,
            name_i18n={"en": "Scouts"},
            description_i18n={"en": "A small scouting party."},
            current_location_id="loc_forest_edge",
            member_ids=member_ids,
            destination_location_id="loc_mountain_pass",
            state_variables={"mission": "recon"}
        )

        group_dict = group.to_dict()

        expected_dict = {
            "id": group_id,
            "guild_id": guild_id,
            "name_i18n": {"en": "Scouts"},
            "description_i18n": {"en": "A small scouting party."},
            "current_location_id": "loc_forest_edge",
            "member_ids": member_ids,
            "destination_location_id": "loc_mountain_pass",
            "state_variables": {"mission": "recon"},
            "is_active": True,
        }
        self.assertEqual(group_dict, expected_dict)

    def test_from_dict(self):
        """Test the from_dict class method."""
        data: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "guild_id": str(uuid.uuid4()),
            "name_i18n": {"en": "Refugees"},
            "description_i18n": {"en": "A group of displaced people."},
            "current_location_id": "loc_ruins",
            "member_ids": [str(uuid.uuid4()) for _ in range(5)],
            "destination_location_id": "loc_safe_haven",
            "state_variables": {"food_days": 2, "morale": "low"},
            "is_active": True
        }
        group = MobileGroup.from_dict(data)

        self.assertEqual(group.id, data["id"])
        self.assertEqual(group.guild_id, data["guild_id"])
        self.assertEqual(group.name_i18n, data["name_i18n"])
        self.assertEqual(group.description_i18n, data["description_i18n"])
        self.assertEqual(group.current_location_id, data["current_location_id"])
        self.assertEqual(group.member_ids, data["member_ids"])
        self.assertEqual(group.destination_location_id, data["destination_location_id"])
        self.assertEqual(group.state_variables, data["state_variables"])
        self.assertTrue(group.is_active)

    def test_from_dict_defaults_and_required(self):
        """Test from_dict with minimal data, checking defaults and required fields."""
        guild_id = str(uuid.uuid4())

        # name_i18n is required by from_dict's default logic if not provided
        group_min_data = MobileGroup.from_dict({
            "guild_id": guild_id,
            # name_i18n will use its default from from_dict
        })
        self.assertIsNotNone(group_min_data.id)
        self.assertEqual(group_min_data.guild_id, guild_id)
        self.assertEqual(group_min_data.name_i18n, {"en": "Default Mobile Group Name"}) # Default from from_dict
        self.assertEqual(group_min_data.description_i18n, {}) # Default
        self.assertEqual(group_min_data.member_ids, []) # Default
        self.assertTrue(group_min_data.is_active) # Default

    def test_from_dict_missing_guild_id_raises_error(self):
        """Test that from_dict raises ValueError if guild_id is missing."""
        with self.assertRaisesRegex(ValueError, "guild_id is required for MobileGroup"):
            MobileGroup.from_dict({"name_i18n": {"en": "Test"}})


if __name__ == '__main__':
    unittest.main()
