import unittest
from unittest.mock import MagicMock, AsyncMock
import json
import logging

from bot.ai.ai_response_validator import AIResponseValidator
from bot.ai.ai_data_models import GenerationContext, ValidationIssue
from bot.ai.ai_data_models import (
    GeneratedLocationContent, GeneratedNpcProfile, GeneratedQuestData, GeneratedItemProfile
)
from bot.ai.rules_schema import (
    GameRules, CharacterStatRules, SkillRules, ItemRules, QuestRules,
    FactionRules, RoleStatRules, StatRange, ItemPriceCategory, ItemPriceDetail,
    QuestRewardRules, CoreGameRulesConfig
)
from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__)

class TestAIResponseValidator(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.sample_rules_dict = {
            "character_stats_rules": {
                "valid_stats": ["strength", "dexterity", "intelligence", "health", "mana"],
                "stat_ranges_by_role": {
                    "warrior": {"stats": {"strength": {"min": 10, "max": 20}, "health": {"min": 50, "max": 150}}},
                    "mage": {"stats": {"intelligence": {"min": 12, "max": 22}, "mana": {"min": 70, "max": 180}}},
                    "commoner": {"stats": {"strength": {"min": 5, "max": 15}, "health": {"min": 20, "max": 80}}}
                }
            },
            "skill_rules": {
                "valid_skills": ["mining", "herbalism", "lockpicking"],
                "skill_stat_map": {"mining": "strength", "herbalism": "intelligence"},
                "skill_value_ranges": {"min": 0, "max": 100}
            },
            "item_rules": {
                "valid_item_types": ["weapon", "potion", "armor", "misc"],
                "price_ranges_by_type": {
                    "weapon": {"prices": {"common": {"min":10, "max":100}, "rare": {"min":101, "max":500}}},
                    "potion": {"prices": {"common": {"min":5, "max":50}}}
                },
                "valid_rarities": ["common", "uncommon", "rare"]
            },
            "faction_rules": {"valid_faction_ids": ["empire", "rebels", "neutral_guild"]},
            "quest_rules": {
                "reward_rules": {"xp_reward_range": {"min": 50, "max": 1000}},
                "valid_objective_types": ["kill", "collect", "goto", "interact_npc"]
            },
            "general_settings": {
                "min_quest_level": 1,
                "max_character_level": 60,
                "default_language": "en",
                "target_languages": ["en", "ru", "fr"]
            },
            "action_conflicts": []
        }
        self.mock_core_game_rules = CoreGameRulesConfig(**self.sample_rules_dict)

        self.mock_game_manager = AsyncMock(spec=GameManager)

        # Simplified get_rule mock logic
        async def get_rule_side_effect(guild_id, rule_key, default=None):
            # Direct access for top-level rule structures
            if hasattr(self.mock_core_game_rules, rule_key):
                return getattr(self.mock_core_game_rules, rule_key)
            # Access for nested general settings like default_language
            if hasattr(self.mock_core_game_rules.general_settings, rule_key):
                return getattr(self.mock_core_game_rules.general_settings, rule_key)

            # Specific mapped keys from validator's expectations
            if rule_key == "npc_stat_ranges":
                return self.mock_core_game_rules.character_stats_rules.stat_ranges_by_role
            if rule_key == "npc_global_stat_limits":
                return self.mock_core_game_rules.character_stats_rules.stat_ranges_by_role.get("commoner", {}).get("stats", {})
            if rule_key == "item_value_ranges":
                return self.mock_core_game_rules.item_rules.price_ranges_by_type

            logger.warning(f"Mock get_rule: Unhandled rule_key '{rule_key}', returning default: {default}")
            return default

        self.mock_game_manager.get_rule = AsyncMock(side_effect=get_rule_side_effect)

        # Ensure general_settings itself can be returned if requested by that key
        # This is implicitly handled by hasattr(self.mock_core_game_rules, rule_key) check above.

        self.mock_game_terms_list_data = [
            {"id": "strength", "name_i18n": {"en": "Strength"}, "term_type": "stat"},
            {"id": "mining", "name_i18n": {"en": "Mining"}, "term_type": "skill"},
            {"id": "ab001", "name_i18n": {"en": "Power Attack"}, "term_type": "ability"},
            {"id": "item_sword", "name_i18n": {"en": "Sword"}, "term_type": "item_template"},
            {"id": "empire", "name_i18n": {"en": "The Empire"}, "term_type": "faction"},
            {"id": "commoner", "name_i18n": {"en": "Commoner"}, "term_type": "npc_archetype"},
            {"id": "warrior", "name_i18n": {"en": "Warrior"}, "term_type": "npc_archetype"},
        ]

        # Setup mock_prompt_collector correctly
        mock_prompt_collector = AsyncMock() # Use AsyncMock for awaitable methods
        mock_prompt_collector.get_game_terms_dictionary = AsyncMock(return_value=self.mock_game_terms_list_data)
        # Ensure get_game_rules_summary is an AsyncMock and returns a dict
        mock_prompt_collector.get_game_rules_summary = AsyncMock(return_value=self.sample_rules_dict) # Or a more specific subset if needed

        self.mock_game_manager.prompt_context_collector = mock_prompt_collector

        self.validator = AIResponseValidator()
        self.guild_id = "test_guild_validator"
        # Validation context is now built inside parse_and_validate_ai_response based on game_manager
        # self.validation_context = {"target_languages": ["en", "ru", "fr"]} # No longer needed here

    async def test_validate_npc_profile_valid(self):
        npc_data = {
            "template_id": "npc001", "name_i18n": {"en": "Valid Guard", "ru": "Валидный стражник", "fr": "Garde Valide"},
            "role_i18n": {"en": "Guard", "ru": "Страж", "fr":"Garde"}, "archetype": "commoner",
            "backstory_i18n": {"en":"bs", "ru":"бс", "fr":"bs"}, "personality_i18n": {"en":"p", "ru":"п", "fr":"p"},
            "motivation_i18n": {"en":"m", "ru":"м", "fr":"m"}, "visual_description_i18n": {"en":"v", "ru":"в", "fr":"v"},
            "dialogue_hints_i18n": {"en":"d", "ru":"д", "fr":"d"},
            "stats": {"strength": 10, "health": 30}, "skills": {"mining": 5}
        }
        raw_json_input = json.dumps(npc_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "npc_profile_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNone(issues, f"Expected no issues, got: {issues}")
        self.assertEqual(validated_data['name_i18n']['en'], "Valid Guard")

    async def test_validate_npc_profile_issues(self):
        npc_data = {
            "template_id": "npc002", "name_i18n": {"en": "Problematic NPC"},
            "role_i18n": {"en":"commoner"},
            "archetype": "unknown_archetype",
            "stats": {"strength": 5000, "invalid_stat_id": 10 },
            "backstory_i18n": {"en":"bs"}, "personality_i18n": {"en":"p"},
            "motivation_i18n": {"en":"m"}, "visual_description_i18n": {"en":"v"},
            "dialogue_hints_i18n": {"en":"d"}, "skills":{}
        }
        raw_json_input = json.dumps(npc_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "npc_profile_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNotNone(issues)
        self.assertTrue(any(iss.loc == ['name_i18n'] and "missing required language(s): ru, fr" in iss.msg.lower() for iss in issues))
        self.assertTrue(any(iss.loc == ['archetype'] and "invalid id" in iss.msg.lower() and "unknown_archetype" in iss.msg.lower() for iss in issues), "Archetype issue not found or message mismatch")
        self.assertTrue(any(iss.loc == ['stats', 'strength'] and "above maximum 15" in iss.msg.lower() for iss in issues), "Strength out of range issue not found")
        self.assertTrue(any(iss.loc == ['stats', 'invalid_stat_id'] and "invalid id" in iss.msg.lower() for iss in issues), "Invalid stat ID issue not found")

    async def test_validate_quest_data_valid(self):
        quest_data = {
            "name_i18n": {"en": "Q", "ru": "К", "fr":"Q"},
            "description_i18n": {"en": "D", "ru": "О", "fr":"D"},
            "steps": [{"title_i18n": {"en":"S1","ru":"Э1","fr":"E1"}, "description_i18n":{"en":"SD1","ru":"ОЭ1","fr":"DE1"}, "required_mechanics_json":"{}", "abstract_goal_json":"{}", "step_order":0, "consequences_json":"{}"}],
            "consequences_json": "{}", "prerequisites_json": "{}"
        }
        raw_json_input = json.dumps(quest_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "quest_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNone(issues, f"Expected no issues for quest, got: {issues}")

    async def test_validate_item_profile_valid(self):
        item_data = {
            "template_id": "item001_valid_sword",
            "name_i18n": {"en": "Fine Sword", "ru": "Отличный меч", "fr": "Bonne Épée"},
            "description_i18n": {"en": "A well-crafted sword.", "ru": "Хорошо сделанный меч.", "fr": "Une épée bien conçue."},
            "item_type": "weapon",
            "base_value": 50,
            "properties_json": json.dumps({"damage_bonus": 5, "weight": 3.5}),
            "rarity_level": "common"
        }
        raw_json_input = json.dumps(item_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "item_profile_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNone(issues, f"Expected no issues for item, got: {issues}")

    async def test_validate_location_content_valid(self):
        loc_data = {
            "template_id": "loc_tpl_1",
            "name_i18n": {"en": "Valid Location", "ru": "Валидная Локация", "fr":"Lieu Valide"},
            "atmospheric_description_i18n": {"en": "Atmosphere", "ru": "Атмосфера", "fr":"Ambiance"},
            "location_type_key": "forest"
        }
        raw_json_input = json.dumps(loc_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "location_details", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNone(issues, f"Expected no issues for location, got: {issues}")

    async def test_validate_location_content_semantic_issues(self):
        loc_data = {
            "template_id": "loc_tpl_sem_issue",
            "name_i18n": {"en": "Semantic Issue Loc", "ru": "Локация с сем. ошибками", "fr": "Lieu Erreur Sem"},
            "atmospheric_description_i18n": {"en": "Desc", "ru": "Опис", "fr":"Desc"},
            "location_type_key": "cave",
            "points_of_interest": [{
                "poi_id": "poi1", "name_i18n": {"en":"POI", "ru":"ПОИ", "fr":"POI"}, "description_i18n": {"en":"D", "ru":"О", "fr":"D"},
                "contained_item_ids": ["item_sword", "item_unknown_one"] # item_sword is valid, item_unknown_one is not
            }],
            "connections": [{
                "to_location_id": "non_existent_loc_id", # Invalid
                "path_description_i18n": {"en":"Path", "ru":"Путь", "fr":"Chemin"}
            }]
        }
        raw_json_input = json.dumps(loc_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "location_details", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNotNone(issues)
        self.assertTrue(any(iss.loc == ['points_of_interest', 0, 'contained_item_ids', 1] and "item_unknown_one" in iss.msg for iss in issues), "Missing item ID issue not found for PoI.")
        self.assertTrue(any(iss.loc == ['connections', 0, 'to_location_id'] and "non_existent_loc_id" in iss.msg for iss in issues), "Missing connected location ID issue not found.")


    async def test_validate_quest_data_semantic_issues(self):
        quest_data = {
            "name_i18n": {"en": "Q Sem", "ru": "К Сем", "fr":"Q Sem"},
            "description_i18n": {"en": "D", "ru": "О", "fr":"D"},
            "steps": [{"title_i18n": {"en":"S1","ru":"Э1","fr":"E1"}, "description_i18n":{"en":"SD1","ru":"ОЭ1","fr":"DE1"}, "required_mechanics_json":"{}", "abstract_goal_json":"{}", "step_order":0, "consequences_json":"{}"}],
            "consequences_json": json.dumps({"items": [{"item_id": "item_unknown_reward"}]}), # Invalid item ID
            "prerequisites_json": "{}",
            "npc_involvement": {"quest_giver": "unknown_npc_archetype"} # Invalid NPC archetype ID
        }
        raw_json_input = json.dumps(quest_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "quest_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNotNone(issues)
        self.assertTrue(any(iss.loc == ['consequences_json', 'items', 0, 'item_id'] and "item_unknown_reward" in iss.msg for iss in issues), "Quest reward item ID issue not found.")
        self.assertTrue(any(iss.loc == ['npc_involvement', 'quest_giver'] and "unknown_npc_archetype" in iss.msg for iss in issues), "Quest NPC involvement ID issue not found.")


    async def test_validate_item_profile_semantic_issues(self):
        item_data = {
            "template_id": "item002_sem_issue_sword",
            "name_i18n": {"en": "Problem Sword", "ru": "Проблемный меч", "fr":"Épée Problème"},
            "description_i18n": {"en": "Desc", "ru":"Опис", "fr":"Desc"},
            "item_type": "weapon",
            "base_value": 10000, # Out of range for rare weapon (max 500)
            "properties_json": json.dumps({"grants_skill": "unknown_skill_id", "grants_ability": "unknown_ability_id"}),
            "rarity_level": "rare" # This should map to item_value_ranges.weapon.rare
        }
        raw_json_input = json.dumps(item_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "item_profile_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNotNone(issues)
        self.assertTrue(any(iss.loc == ['properties_json', 'grants_skill'] and "unknown_skill_id" in iss.msg for iss in issues), "Item grants_skill ID issue not found.")
        self.assertTrue(any(iss.loc == ['properties_json', 'grants_ability'] and "unknown_ability_id" in iss.msg for iss in issues), "Item grants_ability ID issue not found.")
        self.assertTrue(any(iss.loc == ['base_value'] and "above maximum 500" in iss.msg for iss in issues), "Item base_value range issue not found.")

    async def test_validate_npc_profile_no_game_manager(self):
        # Test that stat/value range validation is skipped if game_manager is None
        npc_data = {
            "template_id": "npc_no_gm", "name_i18n": {"en": "Guard NoGM", "ru": "Страж БезГМ", "fr":"Garde SansGM"},
            "role_i18n": {"en":"Guard", "ru":"Страж", "fr":"Garde"}, "archetype": "warrior",
            "stats": {"strength": 5000}, # Would be out of range if GM was present
            "backstory_i18n": {"en":"bs"}, "personality_i18n": {"en":"p"},
            "motivation_i18n": {"en":"m"}, "visual_description_i18n": {"en":"v"},
            "dialogue_hints_i18n": {"en":"d"}, "skills":{}
        }
        raw_json_input = json.dumps(npc_data)
        # Pass game_manager=None
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "npc_profile_generation", game_manager=None
        )
        self.assertIsNotNone(validated_data)
        # Expect Pydantic issues for missing languages if they are enforced by model,
        # but no semantic range issues for stats.
        if issues: # Check that no stat range issues are present
            self.assertFalse(any("out_of_range" in iss.type for iss in issues if iss.loc and iss.loc[0] == "stats"))
            # Example: Check if only i18n issues are present (if any)
            # self.assertTrue(all("missing required language" in iss.msg.lower() for iss in issues if iss.loc == ['name_i18n']))


    async def test_parse_and_validate_ai_response_invalid_json(self):
        invalid_json_str = "this is not json"
        parsed_data, issues = await self.validator.parse_and_validate_ai_response(
            invalid_json_str, self.guild_id, "npc_profile_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNone(parsed_data)
        self.assertIsNotNone(issues)
        self.assertTrue(any(iss.type == "json_decode_error" for iss in issues))

    async def test_parse_and_validate_ai_response_unknown_request_type(self):
        valid_npc_data = { # Reusing valid structure from another test
            "template_id": "npc_valid", "name_i18n": {"en": "OK NPC", "ru": "ОК НПЦ", "fr":"OK NPC"},
            "archetype": "commoner", "stats": {"health": 30}, "role_i18n": {"en":"commoner", "ru":"простолюдин", "fr":"roturier"},
             "backstory_i18n": {"en":"bs", "ru":"бс", "fr":"bs"}, "personality_i18n": {"en":"p", "ru":"п", "fr":"p"},
            "motivation_i18n": {"en":"m", "ru":"м", "fr":"m"}, "visual_description_i18n": {"en":"v", "ru":"в", "fr":"v"},
            "dialogue_hints_i18n": {"en":"d", "ru":"д", "fr":"d"}, "skills":{}
        }
        valid_json_str = json.dumps(valid_npc_data)
        parsed_data, issues = await self.validator.parse_and_validate_ai_response(
            valid_json_str, self.guild_id, "mega_ultra_gen_request_9000", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(parsed_data)
        self.assertIsNotNone(issues)
        self.assertTrue(any(iss.type == "unknown_request_type" for iss in issues))

if __name__ == '__main__':
    unittest.main()
