import unittest
import json # Not strictly needed if model handles objects, but good for example data
from bot.game.models.npc import NPC

class TestNpcModel(unittest.TestCase):

    def test_npc_serialization_deserialization_standard(self):
        """Test NPC model for a standard NPC (like from 'npcs' table)."""
        original_data = {
            "id": "npc_std_1",
            "template_id": "template_guard",
            "name_i18n": {"en": "Guard", "ru": "Страж"},
            "description_i18n": {"en": "A city guard.", "ru": "Городской страж."},
            "persona_i18n": {"en": "Stern and watchful.", "ru": "Суровый и бдительный."},
            "backstory_i18n": {"en": "Served for 10 years.", "ru": "Служил 10 лет."},
            "location_id": "loc_gate",
            "guild_id": "guild_1",
            "stats": {"hp": 50, "atk": 5, "max_health": 50},
            "inventory": ["sword_id", "shield_id"],
            "archetype": "guard",
            "is_ai_generated": False,
            # Fill other relevant fields from NPC model with defaults or simple values
            "owner_id": None,
            "is_temporary": False,
            "current_action": None,
            "action_queue": [],
            "party_id": None,
            "state_variables": {},
            "health": 50.0,
            "max_health": 50.0,
            "is_alive": True,
            "status_effects": [],
            "traits": ["vigilant"],
            "desires": ["peace"],
            "motives": ["duty"],
            "role_i18n": {}, # Empty for standard NPC
            "personality_i18n": {}, # Empty for standard NPC (or could reuse persona)
            "motivation_i18n": {}, # Empty
            "dialogue_hints_i18n": {}, # Empty
            "stats_data": {}, # Empty
            "skills_data": [], # Empty
            "abilities_data": [], # Empty
            "spells_data": [], # Empty
            "inventory_data": [], # Empty
            "faction_affiliations_data": [], # Empty
            "relationships_data": {}, # Empty
            "ai_prompt_context_data": {}, # Empty
            "known_abilities": [],
            "known_spells": [],
            "skills": {},
            "faction_affiliations": [],
            "visual_description_i18n": {},
            "relationships": {}
        }

        npc = NPC.from_dict(original_data)

        self.assertEqual(npc.id, original_data["id"])
        self.assertEqual(npc.name_i18n, original_data["name_i18n"])
        self.assertEqual(npc.name, original_data["name_i18n"]["en"]) # Assuming 'en' default derivation
        self.assertEqual(npc.description_i18n, original_data["description_i18n"])
        self.assertEqual(npc.persona_i18n, original_data["persona_i18n"])
        self.assertEqual(npc.backstory_i18n, original_data["backstory_i18n"])
        self.assertEqual(npc.stats, original_data["stats"])
        self.assertEqual(npc.inventory, original_data["inventory"])
        self.assertEqual(npc.is_ai_generated, False)

        npc_dict = npc.to_dict()
        # Check all keys
        for key, value in original_data.items():
            if key == "name": # name is derived by from_dict
                 self.assertEqual(npc_dict[key], original_data["name_i18n"]["en"])
            else:
                self.assertEqual(npc_dict[key], value, f"Mismatch for key: {key}")
        self.assertEqual(set(npc_dict.keys()), set(original_data.keys()))


    def test_npc_serialization_deserialization_ai_generated(self):
        """Test NPC model for an AI-generated NPC (like from 'generated_npcs' table)."""
        original_data = {
            "id": "npc_ai_1",
            "template_id": "ai_generated_template", # Or could be None/specific
            "name_i18n": {"en": "Mystic Sage", "ru": "Мистический Мудрец"},
            "description_i18n": {"en": "An ancient sage with arcane knowledge.", "ru": "Древний мудрец с тайными знаниями."},
            "role_i18n": {"en": "Quest Giver", "ru": "Выдающий задания"},
            "personality_i18n": {"en": "Enigmatic and wise.", "ru": "Загадочный и мудрый."},
            "motivation_i18n": {"en": "To preserve balance.", "ru": "Сохранять баланс."},
            "dialogue_hints_i18n": {"en": "Speaks in riddles.", "ru": "Говорит загадками."},
            "backstory_i18n": {"en": "Lived for centuries.", "ru": "Живет веками."},
            "location_id": "loc_ruins",
            "guild_id": "guild_1",
            "stats_data": {"hp": 30, "mana": 100, "max_health": 30, "max_mana": 100},
            "skills_data": [{"skill_id": "arcana", "value": 15}],
            "abilities_data": [{"ability_id": "arcane_blast"}],
            "spells_data": [{"spell_id": "teleport", "level": 5}],
            "inventory_data": [{"item_template_id": "scroll_wisdom", "quantity": 1}],
            "faction_affiliations_data": [{"faction_id": "keepers_of_lore", "rank": "elder"}],
            "relationships_data": {"char_hero_1": "ally"},
            "ai_prompt_context_data": {"source_prompt": "Create a wise old sage..."},
            "is_ai_generated": True,
            # Fill other relevant fields from NPC model with defaults or simple values
            "owner_id": None, "is_temporary": False, "current_action": None, "action_queue": [],
            "party_id": None, "state_variables": {}, "health": 30.0, "max_health": 30.0,
            "is_alive": True, "status_effects": [], "archetype": "sage", "traits": ["wise"],
            "desires": ["knowledge"], "motives": ["balance"],
            "stats": {"hp": 30, "mana": 100, "max_health": 30, "max_mana": 100}, # stats often mirrors stats_data for AI NPCs
            "inventory": [], # inventory_data is primary for AI NPCs
            "persona_i18n": {}, # Could reuse personality_i18n
            "known_abilities": [], "known_spells": [], "skills": {}, "faction_affiliations": [],
            "visual_description_i18n": {}, "relationships": {}
        }

        npc = NPC.from_dict(original_data)

        self.assertEqual(npc.id, original_data["id"])
        self.assertEqual(npc.name_i18n, original_data["name_i18n"])
        self.assertEqual(npc.role_i18n, original_data["role_i18n"])
        self.assertEqual(npc.personality_i18n, original_data["personality_i18n"])
        self.assertEqual(npc.stats_data, original_data["stats_data"])
        self.assertEqual(npc.skills_data, original_data["skills_data"])
        self.assertEqual(npc.abilities_data, original_data["abilities_data"])
        self.assertEqual(npc.spells_data, original_data["spells_data"])
        self.assertEqual(npc.inventory_data, original_data["inventory_data"])
        self.assertEqual(npc.faction_affiliations_data, original_data["faction_affiliations_data"])
        self.assertEqual(npc.relationships_data, original_data["relationships_data"])
        self.assertEqual(npc.ai_prompt_context_data, original_data["ai_prompt_context_data"])
        self.assertEqual(npc.is_ai_generated, True)
        # Check if simple 'stats' gets populated from 'stats_data' if logic exists for it
        # The NPC model from_dict does not explicitly copy stats_data to stats.
        # NpcManager load_state does this: model_data_gen['stats'] = model_data_gen.get('stats_data', {})
        # So original_data for testing from_dict should have 'stats' populated if that's expected.
        self.assertEqual(npc.stats, original_data["stats_data"])


        npc_dict = npc.to_dict()
        for key, value in original_data.items():
            if key == "name": # name is derived
                 self.assertEqual(npc_dict[key], original_data["name_i18n"]["en"])
            else:
                self.assertEqual(npc_dict[key], value, f"Mismatch for key: {key}")
        self.assertEqual(set(npc_dict.keys()), set(original_data.keys()))

    def test_npc_name_derivation(self):
        """Test plain name derivation in NPC model."""
        data = {"id": "npc1", "template_id": "t1", "name_i18n": {"en": "John", "ru": "Иван"}}
        npc_en = NPC.from_dict({**data, "selected_language": "en"}) # Assume selected_language hint
        self.assertEqual(npc_en.name, "John")

        npc_ru = NPC.from_dict({**data, "selected_language": "ru"})
        self.assertEqual(npc_ru.name, "Иван")

        npc_default = NPC.from_dict(data) # No selected_language, defaults to 'en' or first
        self.assertEqual(npc_default.name, "John")

        # Test fallback if name_i18n is empty
        data_no_name = {"id": "npc_no_name", "template_id": "t2", "name_i18n": {}}
        npc_no_name = NPC.from_dict(data_no_name)
        self.assertEqual(npc_no_name.name, "npc_no_name") # Falls back to ID

if __name__ == '__main__':
    unittest.main()
