import unittest
import uuid
from typing import Dict, Any

from bot.game.models.global_npc import GlobalNpc

class TestGlobalNpcModel(unittest.TestCase):

    def test_global_npc_instantiation_defaults(self):
        """Test GlobalNpc instantiation with minimal required fields and default values."""
        guild_id = str(uuid.uuid4())
        name_i18n = {"en": "Test NPC"}

        npc = GlobalNpc(guild_id=guild_id, name_i18n=name_i18n)

        self.assertIsNotNone(npc.id)
        self.assertEqual(npc.guild_id, guild_id)
        self.assertEqual(npc.name_i18n, name_i18n)
        self.assertEqual(npc.description_i18n, {}) # Default
        self.assertIsNone(npc.current_location_id)
        self.assertIsNone(npc.npc_template_id)
        self.assertEqual(npc.state_variables, {}) # Default
        self.assertIsNone(npc.faction_id)
        self.assertTrue(npc.is_active) # Default

    def test_global_npc_instantiation_all_fields(self):
        """Test GlobalNpc instantiation with all fields provided."""
        data: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "guild_id": str(uuid.uuid4()),
            "name_i18n": {"en": "Valerius", "ru": "Валериус"},
            "description_i18n": {"en": "A mighty warrior.", "ru": "Могучий воин."},
            "current_location_id": "loc_castle_throne_room",
            "npc_template_id": "template_warrior_captain",
            "state_variables": {"mood": "angry", "quest_stage": 5},
            "faction_id": "faction_knights_of_valor",
            "is_active": False
        }
        npc = GlobalNpc(**data)

        self.assertEqual(npc.id, data["id"])
        self.assertEqual(npc.guild_id, data["guild_id"])
        self.assertEqual(npc.name_i18n, data["name_i18n"])
        self.assertEqual(npc.description_i18n, data["description_i18n"])
        self.assertEqual(npc.current_location_id, data["current_location_id"])
        self.assertEqual(npc.npc_template_id, data["npc_template_id"])
        self.assertEqual(npc.state_variables, data["state_variables"])
        self.assertEqual(npc.faction_id, data["faction_id"])
        self.assertEqual(npc.is_active, data["is_active"])

    def test_to_dict(self):
        """Test the to_dict method."""
        npc_id = str(uuid.uuid4())
        guild_id = str(uuid.uuid4())
        npc = GlobalNpc(
            id=npc_id,
            guild_id=guild_id,
            name_i18n={"en": "Guard"},
            description_i18n={"en": "A city guard."},
            current_location_id="loc_gate",
            state_variables={"on_duty": True}
        )

        npc_dict = npc.to_dict()

        expected_dict = {
            "id": npc_id,
            "guild_id": guild_id,
            "name_i18n": {"en": "Guard"},
            "description_i18n": {"en": "A city guard."},
            "current_location_id": "loc_gate",
            "npc_template_id": None,
            "state_variables": {"on_duty": True},
            "faction_id": None,
            "is_active": True,
        }
        self.assertEqual(npc_dict, expected_dict)

    def test_from_dict(self):
        """Test the from_dict class method."""
        data: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "guild_id": str(uuid.uuid4()),
            "name_i18n": {"en": "Merchant"},
            "description_i18n": {"en": "A traveling merchant."},
            "current_location_id": "loc_market",
            "npc_template_id": "tpl_merchant_generic",
            "state_variables": {"gold": 1000, "inventory_stocked": True},
            "faction_id": "faction_merchants_guild",
            "is_active": True
        }
        npc = GlobalNpc.from_dict(data)

        self.assertEqual(npc.id, data["id"])
        self.assertEqual(npc.guild_id, data["guild_id"])
        self.assertEqual(npc.name_i18n, data["name_i18n"])
        self.assertEqual(npc.description_i18n, data["description_i18n"])
        self.assertEqual(npc.current_location_id, data["current_location_id"])
        self.assertEqual(npc.npc_template_id, data["npc_template_id"])
        self.assertEqual(npc.state_variables, data["state_variables"])
        self.assertEqual(npc.faction_id, data["faction_id"])
        self.assertTrue(npc.is_active)

    def test_from_dict_defaults(self):
        """Test from_dict with minimal data, relying on defaults."""
        guild_id = str(uuid.uuid4())
        npc = GlobalNpc.from_dict({
            "guild_id": guild_id,
            # name_i18n will use its default from from_dict
        })
        self.assertIsNotNone(npc.id)
        self.assertEqual(npc.guild_id, guild_id)
        self.assertEqual(npc.name_i18n, {"en": "Default Global NPC Name"}) # Default from from_dict
        self.assertEqual(npc.description_i18n, {}) # Default from from_dict
        self.assertTrue(npc.is_active) # Default from from_dict
        self.assertEqual(npc.state_variables, {}) # Default from from_dict

    def test_name_i18n_default_in_init(self):
        """Test that name_i18n defaults correctly in __init__ if not provided or empty."""
        guild_id = str(uuid.uuid4())

        # Test with name_i18n missing
        npc_missing_name = GlobalNpc(guild_id=guild_id)
        self.assertEqual(npc_missing_name.name_i18n, {"en": "Default Global NPC Name"})

        # Test with name_i18n provided as empty dict
        npc_empty_name = GlobalNpc(guild_id=guild_id, name_i18n={})
        self.assertEqual(npc_empty_name.name_i18n, {"en": "Default Global NPC Name"})


if __name__ == '__main__':
    unittest.main()
