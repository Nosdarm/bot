import unittest
import json
from bot.game.models.location import Location

class TestLocationModel(unittest.TestCase):

    def test_location_serialization_deserialization_full(self):
        """Test full serialization and deserialization of Location model."""
        original_data = {
            "id": "loc_1",
            "name_i18n": {"en": "Old Library", "ru": "Старая Библиотека"},
            "description_template_i18n": {"en": "A dusty old library.", "ru": "Пыльная старая библиотека."},
            "descriptions_i18n": {"en": "You see cobwebs everywhere.", "ru": "Повсюду паутина."},
            "static_name": "library_main_hall",
            "static_connections": json.dumps({"north": "archive_room_static_id"}), # Assuming stored as JSON string
            "exits": [{"direction": "north", "to_location_id": "loc_archive"}],
            "guild_id": "guild_xyz",
            "template_id": "tpl_library",
            "is_active": True,
            "state": {"lights_on": False, "secret_passage_open": True},
            "custom_field": "custom_value" # Test arbitrary kwargs
        }

        # Test from_dict
        loc = Location.from_dict(original_data)

        self.assertEqual(loc.id, original_data["id"])
        self.assertEqual(loc.name_i18n, original_data["name_i18n"])
        self.assertEqual(loc.description_template_i18n, original_data["description_template_i18n"])
        self.assertEqual(loc.descriptions_i18n, original_data["descriptions_i18n"])
        self.assertEqual(loc.static_name, original_data["static_name"])
        self.assertEqual(loc.static_connections, original_data["static_connections"])
        self.assertEqual(loc.exits, original_data["exits"])
        self.assertEqual(loc.guild_id, original_data["guild_id"])
        self.assertEqual(loc.template_id, original_data["template_id"])
        self.assertEqual(loc.is_active, original_data["is_active"])
        self.assertEqual(loc.state, original_data["state"])
        self.assertEqual(loc.custom_field, original_data["custom_field"])

        # Test derived properties
        self.assertEqual(loc.name, "Old Library") # Assuming 'en' default
        # display_description should prioritize descriptions_i18n
        self.assertEqual(loc.display_description, "You see cobwebs everywhere.")

        # Test to_dict
        loc_dict = loc.to_dict()

        # Compare all keys
        for key, value in original_data.items():
            self.assertEqual(loc_dict[key], value, f"Mismatch for key: {key}")

        # Ensure all original keys were produced by to_dict (plus 'name' and 'display_description' if they were part of it)
        # to_dict() as implemented doesn't add properties, so direct comparison of original_data keys is fine.
        self.assertEqual(set(loc_dict.keys()), set(original_data.keys()))

    def test_location_minimal_data(self):
        """Test with minimal data, relying on defaults."""
        minimal_data = {
            "id": "loc_min",
            "name": "Minimal Room" # Test backward compatibility for name
        }
        # guild_id, template_id etc. are not strictly required by __init__ but might be by logic

        loc = Location.from_dict(minimal_data)
        self.assertEqual(loc.id, "loc_min")
        self.assertEqual(loc.name_i18n, {"en": "Minimal Room"})
        self.assertEqual(loc.name, "Minimal Room")
        self.assertEqual(loc.description_template_i18n, {"en": "This is a mysterious place with no clear description."})
        self.assertEqual(loc.descriptions_i18n, {})
        self.assertEqual(loc.display_description, "This is a mysterious place with no clear description.") # Falls back to template
        self.assertEqual(loc.exits, [])
        self.assertEqual(loc.state, {})
        self.assertTrue(loc.is_active)

        loc_dict = loc.to_dict()
        self.assertEqual(loc_dict["name_i18n"], {"en": "Minimal Room"})
        self.assertTrue(loc_dict["is_active"])

    def test_description_priority(self):
        """Test the display_description property logic."""
        # 1. Only template description
        data1 = {"id":"l1", "name_i18n": {"en":"L1"}, "description_template_i18n": {"en": "Template Desc"}}
        loc1 = Location.from_dict(data1)
        self.assertEqual(loc1.display_description, "Template Desc")

        # 2. Only instance-specific description
        data2 = {"id":"l2", "name_i18n": {"en":"L2"}, "descriptions_i18n": {"en": "Instance Desc"}}
        loc2 = Location.from_dict(data2)
        self.assertEqual(loc2.display_description, "Instance Desc")

        # 3. Both present: instance should take priority
        data3 = {
            "id":"l3", "name_i18n": {"en":"L3"},
            "description_template_i18n": {"en": "Template Desc 3"},
            "descriptions_i18n": {"en": "Instance Desc 3"}
        }
        loc3 = Location.from_dict(data3)
        self.assertEqual(loc3.display_description, "Instance Desc 3")

        # 4. Different languages
        data4 = {
            "id":"l4", "name_i18n": {"en":"L4"},
            "description_template_i18n": {"ru": "Шаблон Описание"},
            "descriptions_i18n": {"de": "Instanz Beschreibung"}
        }
        loc4_en_pref = Location.from_dict(data4) # Assuming 'en' default for property
        # Falls back to first available if 'en' is not in the prioritized dict
        self.assertEqual(loc4_en_pref.display_description, "Instanz Beschreibung")

    def test_descriptions_i18n_json_string_input(self):
        """Test if descriptions_i18n (instance-specific) is parsed from a JSON string."""
        desc_json_str = json.dumps({"en": "Instance JSON string desc", "ru": "Инстанс JSON строка описание"})
        data = {
            "id": "loc_json",
            "name_i18n": {"en": "JSON Test Loc"},
            "descriptions_i18n": desc_json_str
        }
        loc = Location.from_dict(data)
        self.assertEqual(loc.descriptions_i18n, json.loads(desc_json_str))
        self.assertEqual(loc.display_description, "Instance JSON string desc") # 'en' preference

        # Test with non-JSON string (should become {"en": string_value})
        plain_string_desc = "This is just a plain string."
        data_plain = {
             "id": "loc_plain",
             "name_i18n": {"en": "Plain Test Loc"},
             "descriptions_i18n": plain_string_desc
        }
        loc_plain = Location.from_dict(data_plain)
        self.assertEqual(loc_plain.descriptions_i18n, {"en": plain_string_desc})
        self.assertEqual(loc_plain.display_description, plain_string_desc)


if __name__ == '__main__':
    unittest.main()
