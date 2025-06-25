# tests/game/models/test_party_model.py
import unittest
import json
from bot.game.models.party import Party

class TestPartyPydanticModel(unittest.TestCase):

    def test_party_serialization_deserialization_full(self):
        """Test full serialization and deserialization of Pydantic Party model."""
        original_data = {
            "id": "party_123",
            "name_i18n": {"en": "The Valiant Few", "ru": "Отважная Горстка"},
            "leader_id": "char_hero_1",
            "player_ids_list": ["char_hero_1", "char_sidekick_2", "npc_wise_old_man"],
            "current_location_id": "loc_dungeon_entrance",
            "turn_status": "awaiting_actions",
            "current_action": {"type": "explore", "target": "mysterious_cave"},
            "action_queue": [{"type": "rest", "duration": 8}],
            "state_variables": {"food_rations": 10, "torch_lit": True},
            # player_ids (JSON string) will be derived by to_dict, and parsed by from_dict
        }

        # Test from_dict
        # from_dict expects 'player_ids' (JSON string) rather than 'player_ids_list' directly
        data_for_from_dict = original_data.copy()
        data_for_from_dict["player_ids"] = json.dumps(original_data["player_ids_list"])
        del data_for_from_dict["player_ids_list"] # Remove list version for from_dict input

        party = Party.from_dict(data_for_from_dict)

        self.assertEqual(party.id, original_data["id"])
        self.assertEqual(party.name_i18n, original_data["name_i18n"])
        self.assertEqual(party.leader_id, original_data["leader_id"])
        self.assertEqual(party.player_ids_list, original_data["player_ids_list"])
        self.assertEqual(party.current_location_id, original_data["current_location_id"])
        self.assertEqual(party.turn_status, original_data["turn_status"])
        self.assertEqual(party.current_action, original_data["current_action"])
        self.assertEqual(party.action_queue, original_data["action_queue"])
        self.assertEqual(party.state_variables, original_data["state_variables"])

        # Test to_dict
        party_dict = party.to_dict()

        # Compare all keys from original_data (player_ids_list will be converted to player_ids json string)
        for key, value in original_data.items():
            if key == "player_ids_list":
                self.assertEqual(json.loads(party_dict["player_ids"]), value, f"Mismatch for player_ids content")
            else:
                self.assertEqual(party_dict[key], value, f"Mismatch for key: {key}")

        # Ensure player_ids_list is not in the output dict, but player_ids (JSON string) is
        self.assertNotIn("player_ids_list", party_dict)
        self.assertIn("player_ids", party_dict)


    def test_party_minimal_data(self):
        """Test with minimal data, relying on defaults."""
        minimal_data = {
            "id": "party_min",
            "name_i18n": {"en": "Solo Adventurer"}
            # guild_id is not part of Pydantic model directly, assumed to be context
        }
        party = Party.from_dict(minimal_data)

        self.assertEqual(party.id, "party_min")
        self.assertEqual(party.name_i18n, {"en": "Solo Adventurer"})
        self.assertIsNone(party.leader_id)
        self.assertEqual(party.player_ids_list, [])
        self.assertIsNone(party.current_location_id)
        self.assertIsNone(party.turn_status)
        self.assertIsNone(party.current_action)
        self.assertEqual(party.action_queue, [])
        self.assertEqual(party.state_variables, {})

        party_dict = party.to_dict()
        self.assertEqual(party_dict["name_i18n"], {"en": "Solo Adventurer"})
        self.assertEqual(json.loads(party_dict["player_ids"]), [])


    def test_player_ids_json_handling(self):
        """Test how player_ids (JSON string) and player_ids_list are handled."""
        # Input with JSON string for player_ids
        player_ids_list = ["p1", "p2"]
        player_ids_json_str = json.dumps(player_ids_list)
        data_with_json_str = {
            "id": "party_json",
            "name_i18n": {"en": "JSON String Test"},
            "player_ids": player_ids_json_str
        }
        party1 = Party.from_dict(data_with_json_str)
        self.assertEqual(party1.player_ids_list, player_ids_list)
        self.assertEqual(json.loads(party1.to_dict()["player_ids"]), player_ids_list)

        # Input with old 'member_ids' key (should also be a JSON string)
        data_with_member_ids = {
            "id": "party_member_ids",
            "name_i18n": {"en": "Member IDs Test"},
            "member_ids": player_ids_json_str # Using old key
        }
        party2 = Party.from_dict(data_with_member_ids)
        self.assertEqual(party2.player_ids_list, player_ids_list)

        # Input with player_ids being None
        data_with_none_ids = {
            "id": "party_none_ids",
            "name_i18n": {"en": "None IDs Test"},
            "player_ids": None
        }
        party3 = Party.from_dict(data_with_none_ids)
        self.assertEqual(party3.player_ids_list, [])

        # Input with player_ids being an empty JSON array string
        data_with_empty_json_array = {
            "id": "party_empty_json_array",
            "name_i18n": {"en": "Empty JSON Array Test"},
            "player_ids": "[]"
        }
        party4 = Party.from_dict(data_with_empty_json_array)
        self.assertEqual(party4.player_ids_list, [])

        # Input with malformed JSON string for player_ids
        data_with_malformed_json = {
            "id": "party_malformed_json",
            "name_i18n": {"en": "Malformed JSON Test"},
            "player_ids": "[p1, p2" # Malformed
        }
        party5 = Party.from_dict(data_with_malformed_json)
        self.assertEqual(party5.player_ids_list, []) # Should default to empty list

    def test_name_backward_compatibility(self):
        """Test if 'name' (string) is correctly converted to 'name_i18n'."""
        data = {
            "id": "party_old_name",
            "name": "Old Name Party" # No name_i18n
        }
        party = Party.from_dict(data)
        self.assertEqual(party.name_i18n, {"en": "Old Name Party"})

        # If both name and name_i18n are present, name_i18n should take precedence
        data_both = {
            "id": "party_both_names",
            "name": "This should be ignored",
            "name_i18n": {"en": "Priority Name"}
        }
        party_both = Party.from_dict(data_both)
        self.assertEqual(party_both.name_i18n, {"en": "Priority Name"})

if __name__ == '__main__':
    unittest.main()
