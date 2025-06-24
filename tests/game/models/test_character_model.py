import unittest
import json
from bot.game.models.character import Character

class TestCharacterModel(unittest.TestCase):

    def test_character_serialization_deserialization_full(self):
        """Test full serialization and deserialization of Character model."""
        original_data = {
            "id": "char_1",
            "discord_user_id": 1234567890,
            "name_i18n": {"en": "Test Hero", "ru": "Тестовый Герой"},
            "guild_id": "guild_1",
            "location_id": "loc_start",
            "stats": {"strength": 15, "agility": 12, "hp": 100, "max_health": 100},
            "inventory": [{"item_id": "sword1", "quantity": 1}],
            "current_action": {"type": "idle"},
            "action_queue": [{"type": "move", "target": "loc_forest"}],
            "party_id": "party_alpha",
            "state_variables": {"quest_progress": {"q1": 2}},
            "hp": 100.0, # Made consistent with stats.hp for __post_init__ behavior
            "max_health": 100.0,
            "is_alive": True,
            "status_effects": [{"effect_id": "poison", "duration": 5}],
            "level": 5,
            "experience": 5500,
            "unspent_xp": 500,
            "active_quests": ["q1", "q2"],
            "known_spells": ["fireball_id"],
            "spell_cooldowns": {"fireball_id": 1678886400.0},

            # New/Updated fields
            "skills_data": [{"skill_id": "mining", "level": 10, "xp_to_next": 50}],
            "abilities_data": [{"ability_id": "power_attack", "unlocked": True}],
            "spells_data": [{"spell_id": "ice_bolt", "learned_at_level": 3}],
            "character_class": "Warrior",
            "flags": {"is_stealthy": True, "has_guild_key": False},

            "selected_language": "en",
            "current_game_status": "active",
            "collected_actions_json": json.dumps([{"action": "gather", "resource": "herb"}]), # Stored as JSON string
            "current_party_id": "party_alpha"
        }

        # Test from_dict
        char = Character.from_dict(original_data)

        self.assertEqual(char.id, original_data["id"])
        self.assertEqual(char.discord_user_id, original_data["discord_user_id"])
        self.assertEqual(char.name_i18n, original_data["name_i18n"])
        # Name is derived, check based on selected_language
        self.assertEqual(char.name, original_data["name_i18n"].get(original_data["selected_language"], char.id))
        self.assertEqual(char.guild_id, original_data["guild_id"])

        self.assertEqual(char.skills_data, original_data["skills_data"])
        self.assertEqual(char.abilities_data, original_data["abilities_data"])
        self.assertEqual(char.spells_data, original_data["spells_data"])
        self.assertEqual(char.character_class, original_data["character_class"])
        self.assertEqual(char.flags, original_data["flags"])
        self.assertEqual(char.collected_actions_json, original_data["collected_actions_json"])
        self.assertEqual(char.stats["hp"], original_data["hp"]) # Check __post_init__ effect on stats

        # Test to_dict
        char_dict = char.to_dict()

        # Compare all keys, ensuring JSON string for collected_actions is preserved
        for key, value in original_data.items():
            if key == "stats": # Stats might be modified by __post_init__
                self.assertEqual(char_dict[key]["strength"], value["strength"])
                self.assertEqual(char_dict[key]["hp"], original_data["hp"]) # Check HP in stats
            elif key == "name": # Name is derived in from_dict
                 self.assertEqual(char_dict[key], original_data["name_i18n"].get(original_data["selected_language"], original_data["id"]))
            else:
                self.assertEqual(char_dict[key], value, f"Mismatch for key: {key}")

        # Ensure all original keys were produced by to_dict
        self.assertEqual(set(char_dict.keys()), set(original_data.keys()))


    def test_character_minimal_data(self):
        """Test serialization/deserialization with minimal required data."""
        minimal_data = {
            "id": "char_2",
            "discord_user_id": 987654321,
            "name_i18n": {"en": "Minimus"},
            "guild_id": "guild_2",
            # selected_language will default in from_dict for name derivation if name not present
        }

        char = Character.from_dict(minimal_data)
        self.assertEqual(char.name, "Minimus") # Derived name
        self.assertEqual(char.level, 1)
        self.assertEqual(char.skills_data, [])
        self.assertEqual(char.abilities_data, [])
        self.assertEqual(char.spells_data, [])
        self.assertIsNone(char.character_class)
        self.assertEqual(char.flags, {})
        self.assertIsNone(char.collected_actions_json)

        char_dict = char.to_dict()
        self.assertEqual(char_dict["name_i18n"], minimal_data["name_i18n"])
        self.assertEqual(char_dict["level"], 1)
        self.assertEqual(char_dict["skills_data"], [])

    def test_collected_actions_handling(self):
        """Test specifically the collected_actions_json field."""
        # Case 1: Valid JSON string
        actions_list = [{"action": "test"}]
        actions_json_str = json.dumps(actions_list)
        char1_data = {"id": "c1", "discord_user_id": 1, "name_i18n": {"en":"c1"}, "guild_id": "g1", "collected_actions_json": actions_json_str}
        char1 = Character.from_dict(char1_data)
        self.assertEqual(char1.collected_actions_json, actions_json_str)
        self.assertEqual(char1.to_dict()["collected_actions_json"], actions_json_str)

        # Case 2: None (should remain None)
        char2_data = {"id": "c2", "discord_user_id": 2, "name_i18n": {"en":"c2"}, "guild_id": "g1", "collected_actions_json": None}
        char2 = Character.from_dict(char2_data)
        self.assertIsNone(char2.collected_actions_json)
        self.assertIsNone(char2.to_dict()["collected_actions_json"])

        # Case 3: Empty string (should probably be treated as None or empty JSON by model/manager)
        # The current model stores it as is.
        char3_data = {"id": "c3", "discord_user_id": 3, "name_i18n": {"en":"c3"}, "guild_id": "g1", "collected_actions_json": ""}
        char3 = Character.from_dict(char3_data)
        self.assertEqual(char3.collected_actions_json, "")
        self.assertEqual(char3.to_dict()["collected_actions_json"], "")

    def test_name_derivation_from_name_i18n(self):
        data = {
            "id": "char_name_test",
            "discord_user_id": 123,
            "name_i18n": {"en": "Hero", "ru": "Герой"},
            "guild_id": "g",
            "selected_language": "ru"
        }
        char_ru = Character.from_dict(data)
        self.assertEqual(char_ru.name, "Герой")

        data["selected_language"] = "fr" # Language not in name_i18n
        char_fr = Character.from_dict(data)
        # Falls back to the first value in name_i18n if selected lang not present
        self.assertEqual(char_fr.name, "Hero")

        data_no_selection = {
            "id": "char_name_test_2",
            "discord_user_id": 124,
            "name_i18n": {"de": "Held"},
            "guild_id": "g",
        }
        char_no_sel = Character.from_dict(data_no_selection)
        # Falls back to 'en' (default in from_dict if selected_language missing), then first value
        self.assertEqual(char_no_sel.name, "Held")


if __name__ == '__main__':
    unittest.main()
