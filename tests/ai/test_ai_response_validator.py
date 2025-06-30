import unittest
from unittest.mock import MagicMock, AsyncMock
import json
import logging
from typing import List, Optional, Any, Dict # Added Dict

from bot.ai.ai_response_validator import AIResponseValidator
from bot.ai.ai_data_models import GenerationContext, ValidationIssue
from bot.ai.ai_data_models import (
    GeneratedLocationContent, GeneratedNpcProfile, GeneratedQuestData, GeneratedItemProfile
)
from bot.ai.rules_schema import (
    GameRules, CharacterStatRules, SkillRules, ItemRules, QuestRules,
    FactionRules, RoleStatRules, StatRange, ItemPriceCategory, ItemPriceDetail,
    QuestRewardRules, CoreGameRulesConfig # Removed GeneralSettings, NPCStatRangesByRole, GlobalStatLimits
)
from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__)

class TestAIResponseValidator(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.sample_rules_dict: Dict[str, Any] = { # Added type hint
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
            "general_settings": { # This is a direct attribute of CoreGameRulesConfig
                "min_quest_level": 1,
                "max_character_level": 60,
                "default_language": "en",
                "target_languages": ["en", "ru", "fr"]
            },
            # "action_conflicts": [] # Assuming this is part of a different schema or not used by validator directly
        }
        self.mock_core_game_rules = CoreGameRulesConfig(**self.sample_rules_dict)

        self.mock_game_manager = AsyncMock(spec=GameManager)

        async def get_rule_side_effect(guild_id: str, rule_key: str, default: Optional[Any] = None) -> Optional[Any]:
            # Check direct attributes of CoreGameRulesConfig first
            if hasattr(self.mock_core_game_rules, rule_key):
                return getattr(self.mock_core_game_rules, rule_key)

            # Check attributes within general_settings
            if self.mock_core_game_rules.general_settings and \
               hasattr(self.mock_core_game_rules.general_settings, rule_key):
                return getattr(self.mock_core_game_rules.general_settings, rule_key)

            # Specific mappings for semantic validation based on how AIResponseValidator calls get_rule
            if rule_key == "npc_stat_ranges" and self.mock_core_game_rules.character_stats_rules:
                return self.mock_core_game_rules.character_stats_rules.stat_ranges_by_role

            # Example for global_stat_limits if it's structured differently
            # For commoner stats as global limits:
            if rule_key == "npc_global_stat_limits" and \
               self.mock_core_game_rules.character_stats_rules and \
               self.mock_core_game_rules.character_stats_rules.stat_ranges_by_role and \
               "commoner" in self.mock_core_game_rules.character_stats_rules.stat_ranges_by_role:
                commoner_role_stats = self.mock_core_game_rules.character_stats_rules.stat_ranges_by_role["commoner"]
                if commoner_role_stats:
                    return commoner_role_stats.stats # Return the dict of StatRange for "commoner"

            if rule_key == "item_value_ranges" and self.mock_core_game_rules.item_rules:
                 return self.mock_core_game_rules.item_rules.price_ranges_by_type


            logger.warning(f"Mock get_rule (validator test): Unhandled rule_key '{rule_key}', returning default: {default}")
            return default

        self.mock_game_manager.get_rule = AsyncMock(side_effect=get_rule_side_effect)

        self.mock_game_terms_list_data: List[Dict[str, Any]] = [ # Added type hint
            {"id": "strength", "name_i18n": {"en": "Strength"}, "term_type": "stat"},
            {"id": "mining", "name_i18n": {"en": "Mining"}, "term_type": "skill"},
            {"id": "ab001", "name_i18n": {"en": "Power Attack"}, "term_type": "ability"},
            {"id": "item_sword", "name_i18n": {"en": "Sword"}, "term_type": "item_template"},
            {"id": "empire", "name_i18n": {"en": "The Empire"}, "term_type": "faction"},
            {"id": "commoner", "name_i18n": {"en": "Commoner"}, "term_type": "npc_archetype"},
            {"id": "warrior", "name_i18n": {"en": "Warrior"}, "term_type": "npc_archetype"},
        ]

        mock_prompt_collector = AsyncMock()
        mock_prompt_collector.get_game_terms_dictionary = AsyncMock(return_value=self.mock_game_terms_list_data)
        mock_prompt_collector.get_game_rules_summary = AsyncMock(return_value=self.sample_rules_dict)

        self.mock_game_manager.prompt_context_collector = mock_prompt_collector

        self.validator = AIResponseValidator()
        self.guild_id = "test_guild_validator"

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
        if validated_data: # Check validated_data is not None before subscripting
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
        issues_list = issues if issues is not None else [] # Ensure issues is a list for iteration
        self.assertTrue(any(iss.loc == ['name_i18n'] and "missing required language(s): ru, fr" in iss.msg.lower() for iss in issues_list))
        self.assertTrue(any(iss.loc == ['archetype'] and "invalid id" in iss.msg.lower() and "unknown_archetype" in iss.msg.lower() for iss in issues_list), "Archetype issue not found or message mismatch")
        self.assertTrue(any(iss.loc == ['stats', 'strength'] and "above maximum 15" in iss.msg.lower() for iss in issues_list), "Strength out of range issue not found")
        self.assertTrue(any(iss.loc == ['stats', 'invalid_stat_id'] and "invalid id" in iss.msg.lower() for iss in issues_list), "Invalid stat ID issue not found")

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
            "location_type_key": "forest" # Assuming 'forest' is a valid key known to the system/rules
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
                "contained_item_ids": ["item_sword", "item_unknown_one"]
            }],
            "connections": [{
                "to_location_id": "non_existent_loc_id",
                "path_description_i18n": {"en":"Path", "ru":"Путь", "fr":"Chemin"}
            }]
        }
        raw_json_input = json.dumps(loc_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "location_details", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNotNone(issues)
        issues_list = issues if issues is not None else []
        self.assertTrue(any(iss.loc == ['points_of_interest', 0, 'contained_item_ids', 1] and "item_unknown_one" in iss.msg for iss in issues_list), "Missing item ID issue not found for PoI.")
        self.assertTrue(any(iss.loc == ['connections', 0, 'to_location_id'] and "non_existent_loc_id" in iss.msg for iss in issues_list), "Missing connected location ID issue not found.")


    async def test_validate_quest_data_semantic_issues(self):
        quest_data = {
            "name_i18n": {"en": "Q Sem", "ru": "К Сем", "fr":"Q Sem"},
            "description_i18n": {"en": "D", "ru": "О", "fr":"D"},
            "steps": [{"title_i18n": {"en":"S1","ru":"Э1","fr":"E1"}, "description_i18n":{"en":"SD1","ru":"ОЭ1","fr":"DE1"}, "required_mechanics_json":"{}", "abstract_goal_json":"{}", "step_order":0, "consequences_json":"{}"}],
            "consequences_json": json.dumps({"items": [{"item_id": "item_unknown_reward"}]}),
            "prerequisites_json": "{}",
            "npc_involvement": {"quest_giver": "unknown_npc_archetype"}
        }
        raw_json_input = json.dumps(quest_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "quest_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNotNone(issues)
        issues_list = issues if issues is not None else []
        self.assertTrue(any(iss.loc == ['consequences_json', 'items', 0, 'item_id'] and "item_unknown_reward" in iss.msg for iss in issues_list), "Quest reward item ID issue not found.")
        self.assertTrue(any(iss.loc == ['npc_involvement', 'quest_giver'] and "unknown_npc_archetype" in iss.msg for iss in issues_list), "Quest NPC involvement ID issue not found.")


    async def test_validate_item_profile_semantic_issues(self):
        item_data = {
            "template_id": "item002_sem_issue_sword",
            "name_i18n": {"en": "Problem Sword", "ru": "Проблемный меч", "fr":"Épée Problème"},
            "description_i18n": {"en": "Desc", "ru":"Опис", "fr":"Desc"},
            "item_type": "weapon",
            "base_value": 10000,
            "properties_json": json.dumps({"grants_skill": "unknown_skill_id", "grants_ability": "unknown_ability_id"}),
            "rarity_level": "rare"
        }
        raw_json_input = json.dumps(item_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "item_profile_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNotNone(validated_data)
        self.assertIsNotNone(issues)
        issues_list = issues if issues is not None else []
        self.assertTrue(any(iss.loc == ['properties_json', 'grants_skill'] and "unknown_skill_id" in iss.msg for iss in issues_list), "Item grants_skill ID issue not found.")
        self.assertTrue(any(iss.loc == ['properties_json', 'grants_ability'] and "unknown_ability_id" in iss.msg for iss in issues_list), "Item grants_ability ID issue not found.")
        self.assertTrue(any(iss.loc == ['base_value'] and "above maximum 500" in iss.msg for iss in issues_list), "Item base_value range issue not found.")

    async def test_validate_npc_profile_no_game_manager(self):
        npc_data = {
            "template_id": "npc_no_gm", "name_i18n": {"en": "Guard NoGM", "ru": "Страж БезГМ", "fr":"Garde SansGM"},
            "role_i18n": {"en":"Guard", "ru":"Страж", "fr":"Garde"}, "archetype": "warrior",
            "stats": {"strength": 5000},
            "backstory_i18n": {"en":"bs"}, "personality_i18n": {"en":"p"},
            "motivation_i18n": {"en":"m"}, "visual_description_i18n": {"en":"v"},
            "dialogue_hints_i18n": {"en":"d"}, "skills":{}
        }
        raw_json_input = json.dumps(npc_data)
        validated_data, issues = await self.validator.parse_and_validate_ai_response(
            raw_json_input, self.guild_id, "npc_profile_generation", game_manager=None
        )
        self.assertIsNotNone(validated_data)
        issues_list = issues if issues is not None else []
        self.assertFalse(any("out_of_range" in (iss.type or "") for iss in issues_list if iss.loc and iss.loc[0] == "stats"))


    async def test_parse_and_validate_ai_response_invalid_json(self):
        invalid_json_str = "this is not json"
        parsed_data, issues = await self.validator.parse_and_validate_ai_response(
            invalid_json_str, self.guild_id, "npc_profile_generation", game_manager=self.mock_game_manager
        )
        self.assertIsNone(parsed_data)
        self.assertIsNotNone(issues)
        issues_list = issues if issues is not None else []
        self.assertTrue(any(iss.type == "json_decode_error" for iss in issues_list))

    async def test_parse_and_validate_ai_response_unknown_request_type(self):
        valid_npc_data = {
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
        self.assertIsNotNone(parsed_data) # Data is still parsed to the base model if possible
        self.assertIsNotNone(issues)
        issues_list = issues if issues is not None else []
        self.assertTrue(any(iss.type == "unknown_request_type" for iss in issues_list))

if __name__ == '__main__':
    unittest.main()
