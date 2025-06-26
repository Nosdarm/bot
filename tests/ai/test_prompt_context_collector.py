import unittest
import json
from unittest.mock import MagicMock, patch, mock_open, AsyncMock

from bot.ai.prompt_context_collector import PromptContextCollector
from bot.ai.ai_data_models import GenerationContext, GameTerm, ScalingParameter

# Mocking the actual game models
MockCharacter = MagicMock
MockNpc = MagicMock
MockQuest = MagicMock
MockRelationship = MagicMock
MockItem = MagicMock
MockLocation = MagicMock
MockAbility = MagicMock
MockSpell = MagicMock
MockEvent = MagicMock
MockParty = MagicMock
MockTimeManager = MagicMock
MockDBService = MagicMock
MockLoreManager = MagicMock
MockGameManager = MagicMock


class TestPromptContextCollector(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_settings = {
            "main_language_code": "en",
            "target_languages": ["en", "ru"],
            "game_rules": {
                "character_stats_rules": {
                    "attributes": {
                        "strength": {"name_i18n": {"en": "Strength", "ru": "Сила"}, "description_i18n": {"en": "Physical power", "ru": "Физическая мощь"}},
                        "dexterity": {"name_i18n": {"en": "Dexterity", "ru": "Ловкость"}, "description_i18n": {"en": "Agility and reflexes", "ru": "Проворство и рефлексы"}}
                    },
                    "stat_ranges_by_role": {
                        "warrior": {"stats": {"strength": {"min": 10, "max": 20}, "dexterity": {"min": 8, "max": 16}}},
                        "mage": {"stats": {"intelligence": {"min": 12, "max": 20}}}
                    },
                    "valid_stats": ["strength", "dexterity", "intelligence"]
                },
                "skill_rules": {
                    "skills": {
                        "mining": {"name_i18n": {"en": "Mining", "ru": "Добыча руды"}, "description_i18n": {"en": "Ability to mine ores", "ru": "Способность добывать руду"}},
                        "herbalism": {"name_i18n": {"en": "Herbalism", "ru": "Травничество"}, "description_i18n": {"en": "Ability to gather herbs", "ru": "Способность собирать травы"}}
                    },
                    "skill_stat_map": {"mining": "strength", "herbalism": "intelligence"},
                    "valid_skills": ["mining", "herbalism"]
                },
                "factions_definition": {
                    "empire": {"name_i18n": {"en": "The Empire", "ru": "Империя"}, "description_i18n": {"en": "A lawful empire.", "ru": "Законная империя."}},
                    "rebels": {"name_i18n": {"en": "Rebel Alliance", "ru": "Альянс Повстанцев"}, "description_i18n": {"en": "Freedom fighters.", "ru": "Борцы за свободу."}}
                },
                "faction_rules": {"valid_faction_ids": ["empire", "rebels", "neutral_guild"]},
                "quest_rules": {"reward_rules": {"xp_reward_range": {"min": 50, "max": 1000}}},
                "item_rules": {"price_ranges_by_type": {"weapon": {"common": {"min": 10, "max": 100}, "rare": {"min": 101, "max": 500}}, "potion": {"common": {"min": 5, "max": 25}}}},
                "xp_rules": {"level_difference_modifier": {"-2": 0.5, "0": 1.0, "+2": 1.5}},
                "item_definitions": {
                    "sword_common": {"name_i18n": {"en":"Sword"}, "type": "weapon"},
                    "health_potion_sml": {"name_i18n": {"en":"Potion"}, "type": "potion"}
                }
            },
            "item_templates": {
                "itm001": {"name_i18n": {"en": "Healing Potion", "ru": "Зелье лечения"}, "description_i18n": {"en": "Restores health.", "ru": "Восстанавливает здоровье."}}
            },
        }

        self.mock_db_service = MockDBService()
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = MagicMock()
        self.mock_quest_manager = MagicMock()
        self.mock_relationship_manager = AsyncMock()
        self.mock_item_manager = MagicMock()
        self.mock_location_manager = AsyncMock()
        self.mock_ability_manager = AsyncMock()
        self.mock_spell_manager = AsyncMock()
        self.mock_event_manager = MagicMock()
        self.mock_party_manager = AsyncMock()
        self.mock_lore_manager = AsyncMock()
        self.mock_game_manager = AsyncMock(spec=MockGameManager)
        self.mock_game_manager.get_rule = AsyncMock(return_value="en")
        self.mock_game_manager._active_guild_ids = ["test_guild"]
        self.mock_game_manager.get_default_bot_language = MagicMock(return_value="en")
        self.mock_time_manager_instance = MockTimeManager()
        self.mock_game_manager.time_manager = self.mock_time_manager_instance

        self.collector = PromptContextCollector(
            settings=self.mock_settings,
            db_service=self.mock_db_service,
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            quest_manager=self.mock_quest_manager,
            relationship_manager=self.mock_relationship_manager,
            item_manager=self.mock_item_manager,
            location_manager=self.mock_location_manager,
            event_manager=self.mock_event_manager,
            ability_manager=self.mock_ability_manager,
            spell_manager=self.mock_spell_manager,
            party_manager=self.mock_party_manager,
            lore_manager=self.mock_lore_manager,
            game_manager=self.mock_game_manager
        )
        self.guild_id = "test_guild"
        self.character_id = "char_test_id"
        self.main_lang = self.mock_settings["main_language_code"]

    def test_get_main_language_code(self):
        self.assertEqual(self.collector.get_main_language_code(), "en")
        self.mock_game_manager.get_default_bot_language.assert_called_with(self.guild_id)
        original_gm = self.collector._game_manager
        self.collector._game_manager = None # type: ignore
        self.assertEqual(self.collector.get_main_language_code(), "en")
        self.collector._game_manager = original_gm

    def test_get_faction_data_context(self):
        game_rules_data_mock = self.mock_settings["game_rules"]
        faction_data = self.collector.get_faction_data_context(self.guild_id, game_rules_data=game_rules_data_mock)
        self.assertEqual(len(faction_data), 2)
        self.assertIn("empire", [f.get("id") for f in faction_data])
        self.assertEqual(faction_data[0].get("name_i18n", {}).get("en"), "The Empire")

        original_factions_def = game_rules_data_mock["factions_definition"]
        game_rules_data_mock["factions_definition"] = {}
        faction_data_fallback = self.collector.get_faction_data_context(self.guild_id, game_rules_data=game_rules_data_mock)
        self.assertEqual(len(faction_data_fallback), 3)
        self.assertIn("neutral_guild", [f.get("id") for f in faction_data_fallback])
        game_rules_data_mock["factions_definition"] = original_factions_def

        original_faction_rules = game_rules_data_mock["faction_rules"]
        game_rules_data_mock["factions_definition"] = {}
        game_rules_data_mock["faction_rules"] = {}
        faction_data_none = self.collector.get_faction_data_context(self.guild_id, game_rules_data=game_rules_data_mock)
        self.assertEqual(len(faction_data_none), 0)
        game_rules_data_mock["factions_definition"] = original_factions_def
        game_rules_data_mock["faction_rules"] = original_faction_rules

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_get_lore_context(self, mock_json_load, mock_file_open):
        mock_json_load.return_value = {"lore_entries": [{"id": "lore1", "text": "Ancient tale"}]}
        context = self.collector.get_lore_context()
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0].get("id"), "lore1")
        mock_file_open.assert_called_once_with("game_data/lore_i18n.json", 'r', encoding='utf-8')

        mock_file_open.side_effect = FileNotFoundError
        self.assertEqual(self.collector.get_lore_context(), [])
        mock_file_open.side_effect = None
        mock_json_load.side_effect = json.JSONDecodeError("Error decoding", "doc", 0)
        self.assertEqual(self.collector.get_lore_context(), [])

    def test_get_world_state_context(self):
        mock_event1 = MagicMock(); mock_event1.id = "event001"; mock_event1.name = "Festival"; mock_event1.current_stage_id = "stage2"; mock_event1.template_id = "fest_tpl"; mock_event1.is_active = True
        self.mock_event_manager.get_active_events.return_value = [mock_event1]
        mock_loc1_obj = MagicMock(); mock_loc1_obj.id = "loc001"; mock_loc1_obj.name_i18n = {"en": "Tower"}; mock_loc1_obj.state = {"is_destroyed": True}
        self.mock_location_manager.get_location_instance.return_value = mock_loc1_obj
        self.mock_location_manager._location_instances = {self.guild_id: {"loc001": {"id": "loc001"}}}
        mock_npc1 = MagicMock(); mock_npc1.id = "npc001"; mock_npc1.name = "Guard"; mock_npc1.health = 20.0; mock_npc1.max_health = 100.0; mock_npc1.current_action = None; mock_npc1.location_id = "loc001"
        self.mock_npc_manager.get_all_npcs.return_value = [mock_npc1]
        self.mock_time_manager_instance.get_current_game_time.return_value = 90061.0

        world_state = self.collector.get_world_state_context(self.guild_id)
        self.assertEqual(len(world_state.get("active_global_events", [])), 1)
        self.assertEqual(len(world_state.get("key_location_statuses", [])), 1)
        self.assertEqual(len(world_state.get("significant_npc_states", [])), 1)
        self.assertEqual(world_state.get("current_time", {}).get("game_time_string"), "Day 2, 01:01:01")

    async def test_get_relationship_context(self):
        mock_rel1_dict = {"entity1_id": self.character_id, "entity2_id": "npc001", "relationship_type": "friendly", "strength": 75.0, "details_i18n": {"en": "Good friends"}}
        mock_rel1_obj = MagicMock(); mock_rel1_obj.to_dict.return_value = mock_rel1_dict
        self.mock_relationship_manager.get_relationships_for_entity = AsyncMock(return_value=[mock_rel1_obj])
        context = await self.collector.get_relationship_context(self.guild_id, self.character_id, "character")
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0].get("strength"), 75.0)

    def test_get_quest_context(self):
        active_quest_dict1 = {"id": "q001", "name_i18n": {"en": "Slay Dragon"}, "status": "active", "current_stage_id": "s1", "stages": {"s1": {"description_i18n": {"en": "Find lair"}}}}
        self.mock_quest_manager.list_quests_for_character.return_value = [active_quest_dict1]
        context = self.collector.get_quest_context(self.guild_id, self.character_id)
        self.assertEqual(len(context.get("active_quests", [])), 1)

    @patch('bot.services.db_service.DBService.get_rules_config', new_callable=AsyncMock)
    async def test_get_game_rules_summary(self, mock_get_rules_config_db: AsyncMock):
        mock_get_rules_config_db.return_value = self.mock_settings["game_rules"]
        summary = await self.collector.get_game_rules_summary(self.guild_id)
        self.assertIn("strength", summary.get("attributes", {}))
        self.assertIn("mining", summary.get("skills", {}))
        self.assertIn("sword_common", summary.get("item_rules_summary", {}))

    def test_get_game_terms_dictionary(self):
        game_rules_data_mock = self.mock_settings["game_rules"]
        # Ensure ability and spell managers are set for this test if they are accessed
        self.collector.ability_manager = self.mock_ability_manager
        self.collector.spell_manager = self.mock_spell_manager
        self.mock_ability_manager.get_all_ability_definitions_for_guild = AsyncMock(return_value=[])
        self.mock_spell_manager.get_all_spell_definitions_for_guild = AsyncMock(return_value=[])


        terms = self.collector.get_game_terms_dictionary(self.guild_id, game_rules_data=game_rules_data_mock, _fetched_abilities=True, _fetched_spells=True)
        term_types_collected = [t.get("term_type") for t in terms]
        self.assertIn("stat", term_types_collected)
        self.assertIn("skill", term_types_collected)

    def test_get_scaling_parameters(self):
        game_rules_data_mock = self.mock_settings["game_rules"]
        params = self.collector.get_scaling_parameters(self.guild_id, game_rules_data=game_rules_data_mock)
        self.assertEqual(len(params), 17) # Original count
        param_names = [p.get("parameter_name") for p in params]
        self.assertIn("npc_stat_strength_warrior_min", param_names)

    async def test_get_full_context(self):
        # Simplified mocks for get_full_context sub-calls
        self.collector.get_main_language_code = MagicMock(return_value="en") # type: ignore
        self.mock_settings["target_languages"] = ["en", "ru"]
        self.collector.get_game_rules_summary = AsyncMock(return_value={}) # type: ignore
        self.collector.get_lore_context = MagicMock(return_value=[]) # type: ignore
        self.collector.get_world_state_context = MagicMock(return_value={}) # type: ignore
        self.collector.get_game_terms_dictionary = MagicMock(return_value=[]) # type: ignore
        self.collector.get_scaling_parameters = MagicMock(return_value=[]) # type: ignore
        self.collector.get_faction_data_context = MagicMock(return_value=[]) # type: ignore
        self.mock_character_manager.get_character_details_context = AsyncMock(return_value={"player_id": self.character_id})
        self.collector.get_quest_context = MagicMock(return_value={"active_quests": []}) # type: ignore
        self.collector.get_relationship_context = AsyncMock(return_value=[]) # type: ignore
        self.mock_location_manager.get_location_instance = AsyncMock(return_value=None)
        self.mock_party_manager.get_party = AsyncMock(return_value=None)
        self.mock_ability_manager.get_all_ability_definitions_for_guild = AsyncMock(return_value=[])
        self.mock_spell_manager.get_all_spell_definitions_for_guild = AsyncMock(return_value=[])
        self.mock_lore_manager.get_contextual_lore = AsyncMock(return_value=[])

        full_context_char = await self.collector.get_full_context(
            self.guild_id, "test_req", {}, target_entity_id=self.character_id, target_entity_type="character"
        )
        self.assertIsInstance(full_context_char, GenerationContext)
        self.assertEqual(full_context_char.guild_id, self.guild_id)
        self.assertIsNotNone(full_context_char.player_context)
        if full_context_char.player_context:
            self.assertEqual(full_context_char.player_context.get("player_id"), self.character_id)

if __name__ == '__main__':
    unittest.main()
