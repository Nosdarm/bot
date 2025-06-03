import unittest
import json

from bot.ai.ai_response_validator import AIResponseValidator
from bot.ai.rules_schema import (
    GameRules, CharacterStatRules, SkillRules, ItemRules,
    StatRange, RoleStatRules, FactionRules, QuestRules,
    QuestRewardRules, ItemPriceCategory, ItemPriceDetail
)

class TestAIResponseValidator(unittest.TestCase):

    def setUp(self):
        self.default_rules = GameRules(
            character_stats_rules=CharacterStatRules(
                valid_stats=["strength", "dexterity", "health", "intelligence"],
                stat_ranges_by_role={
                    "warrior": RoleStatRules(stats={
                        "strength": StatRange(min=10, max=20),
                        "health": StatRange(min=50, max=150),
                        "intelligence": StatRange(min=5, max=10) # Added for more tests
                    }),
                    "commoner": RoleStatRules(stats={
                        "strength": StatRange(min=5, max=12),
                        "health": StatRange(min=20, max=80),
                        "intelligence": StatRange(min=8, max=15)
                    })
                }
            ),
            skill_rules=SkillRules(
                valid_skills=["combat", "stealth", "magic"],
                skill_stat_map={"combat": "strength", "magic": "intelligence"},
                skill_value_ranges=StatRange(min=0, max=100)
            ),
            item_rules=ItemRules(
                valid_item_types=["weapon", "potion", "armor"],
                price_ranges_by_type={
                    "weapon": ItemPriceCategory(prices={ # Corrected nested structure
                        "common": ItemPriceDetail(min=10, max=100),
                        "rare": ItemPriceDetail(min=101, max=500)
                    }),
                    "potion": ItemPriceCategory(prices={
                        "common": ItemPriceDetail(min=5, max=50)
                    })
                }
            ),
            faction_rules=FactionRules(valid_faction_ids=["faction_a", "faction_b"]),
            quest_rules=QuestRules(
                reward_rules=QuestRewardRules(xp_reward_range=StatRange(min=10, max=1000))
            )
        )
        self.validator = AIResponseValidator(rules=self.default_rules, required_languages=['en', 'ru'])
        self.validator_en_only = AIResponseValidator(rules=self.default_rules, required_languages=['en'])


    def test_invalid_json_format(self):
        invalid_json = "this is not json"
        result = self.validator.validate_ai_response(invalid_json, "single_npc")
        self.assertEqual(result["overall_status"], "error")
        self.assertTrue(any("Invalid JSON format" in error for error in result["global_errors"]))

    def test_list_vs_dict_structure(self):
        # Expected list, got dict
        npc_dict_json = json.dumps({"id": "npc1", "name_i18n": {"en": "Guard", "ru": "Страж"}})
        result = self.validator.validate_ai_response(npc_dict_json, "list_of_npcs")
        self.assertEqual(result["overall_status"], "error")
        self.assertTrue(any("Expected a list for 'list_of_npcs'" in error for error in result["global_errors"]))

        # Expected dict, got list
        npc_list_json = json.dumps([{"id": "npc1", "name_i18n": {"en": "Guard", "ru": "Страж"}}])
        result = self.validator.validate_ai_response(npc_list_json, "single_npc")
        self.assertEqual(result["overall_status"], "error")
        self.assertTrue(any("Expected a dictionary for 'single_npc'" in error for error in result["global_errors"]))


    def test_i18n_completeness_npc_name_missing_lang(self):
        npc_data = {
            "id": "npc1",
            "name_i18n": {"en": "Warrior"}, # Missing 'ru'
            "role_i18n": {"en": "Warrior", "ru": "Воин"},
            "description_i18n": {"en": "Desc", "ru": "DescRu"},
            "backstory_i18n": {"en": "Desc", "ru": "DescRu"},
            "personality_i18n": {"en": "Desc", "ru": "DescRu"},
            "motivation_i18n": {"en": "Desc", "ru": "DescRu"},
            "dialogue_hints_i18n": {"en": "Desc", "ru": "DescRu"},
            "visual_description_i18n": {"en": "Desc", "ru": "DescRu"},
            "stats": {"strength": 15, "health": 100},
            "skills": {"combat": 50}
        }
        npc_json = json.dumps(npc_data)
        result = self.validator.validate_ai_response(npc_json, "single_npc")

        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertEqual(entity_result["status"], "requires_moderation")
        self.assertTrue(entity_result["requires_moderation"])
        self.assertTrue(any("Field 'name_i18n' is missing translation for language 'ru'" in error for error in entity_result["errors"]))

    def test_i18n_completeness_npc_name_empty_lang(self):
        npc_data = {
            "id": "npc1",
            "name_i18n": {"en": "Warrior", "ru": "  "}, # Empty 'ru'
            "role_i18n": {"en": "Warrior", "ru": "Воин"},
            "description_i18n": {"en": "Desc", "ru": "DescRu"},
            "backstory_i18n": {"en": "Desc", "ru": "DescRu"},
            "personality_i18n": {"en": "Desc", "ru": "DescRu"},
            "motivation_i18n": {"en": "Desc", "ru": "DescRu"},
            "dialogue_hints_i18n": {"en": "Desc", "ru": "DescRu"},
            "visual_description_i18n": {"en": "Desc", "ru": "DescRu"},
            "stats": {"strength": 15, "health": 100},
            "skills": {"combat": 50}
        }
        npc_json = json.dumps(npc_data)
        result = self.validator.validate_ai_response(npc_json, "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertEqual(entity_result["status"], "requires_moderation")
        self.assertTrue(any("Field 'name_i18n' has empty or non-string content for language 'ru'" in error for error in entity_result["errors"]))


    def test_npc_stat_validation_out_of_range_and_clamped(self):
        npc_data = {
            "id": "npc_warrior_low_str",
            "archetype": "warrior", # Using archetype to set role
            "name_i18n": {"en": "Weak Warrior", "ru": "Слабый Воин"},
            "role_i18n": {"en": "Warrior", "ru": "Воин"}, # role_i18n also present
            "description_i18n": {"en": "Desc", "ru": "DescRu"},
            "backstory_i18n": {"en": "Desc", "ru": "DescRu"},
            "personality_i18n": {"en": "Desc", "ru": "DescRu"},
            "motivation_i18n": {"en": "Desc", "ru": "DescRu"},
            "dialogue_hints_i18n": {"en": "Desc", "ru": "DescRu"},
            "visual_description_i18n": {"en": "Desc", "ru": "DescRu"},
            "stats": {"strength": 5, "health": 100}, # Strength 5 is below warrior min 10
            "skills": {"combat": 50}
        }
        npc_json = json.dumps(npc_data)
        result = self.validator.validate_ai_response(npc_json, "single_npc")

        self.assertEqual(result["overall_status"], "requires_moderation") # Because clamping is an "error" condition by current design
        entity_result = result["entities"][0]
        self.assertEqual(entity_result["status"], "requires_moderation")
        self.assertTrue(entity_result["requires_moderation"])

        self.assertTrue(any("Stat 'strength' value 5 for role 'warrior' was out of range (10-20). Clamped to 10." in error for error in entity_result["errors"]))
        expected_notification_fragment = "AUTO-CORRECT: NPC 'npc_warrior_low_str': Stat 'strength' value 5 for role 'warrior' was out of range (10-20). Clamped to 10."
        self.assertTrue(any(expected_notification_fragment in notif for notif in entity_result["notifications"]))
        self.assertEqual(entity_result["validated_data"]["stats"]["strength"], 10) # Check clamping

    def test_npc_stat_validation_invalid_name(self):
        npc_data = {
            "id": "npc_invalid_stat", "archetype": "commoner",
            "name_i18n": {"en": "Test", "ru": "Тест"}, "role_i18n": {"en": "Commoner", "ru": "Житель"},
            "description_i18n": {"en": "Desc", "ru": "DescRu"}, "backstory_i18n": {"en": "Desc", "ru": "DescRu"},
            "personality_i18n": {"en": "Desc", "ru": "DescRu"}, "motivation_i18n": {"en": "Desc", "ru": "DescRu"},
            "dialogue_hints_i18n": {"en": "Desc", "ru": "DescRu"}, "visual_description_i18n": {"en": "Desc", "ru": "DescRu"},
            "stats": {"invalid_stat_name": 10, "health": 50},
            "skills": {}
        }
        npc_json = json.dumps(npc_data)
        result = self.validator.validate_ai_response(npc_json, "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Invalid stat name: 'invalid_stat_name'" in error for error in entity_result["errors"]))

    def test_successful_validation_npc(self):
        npc_data = {
            "id": "npc_valid_warrior",
            "archetype": "warrior",
            "name_i18n": {"en": "Valid Warrior", "ru": "Правильный Воин"},
            "role_i18n": {"en": "Warrior", "ru": "Воин"},
            "description_i18n": {"en": "A valid warrior.", "ru": "Правильный воин."},
            "backstory_i18n": {"en": "Born to fight.", "ru": "Рожден сражаться."},
            "personality_i18n": {"en": "Brave", "ru": "Храбрый"},
            "motivation_i18n": {"en": "Glory", "ru": "Слава"},
            "dialogue_hints_i18n": {"en": "Speaks loudly.", "ru": "Говорит громко."},
            "visual_description_i18n": {"en": "Big and strong.", "ru": "Большой и сильный."},
            "stats": {"strength": 15, "health": 120, "intelligence": 7},
            "skills": {"combat": 70, "stealth": 20}
        }
        npc_json = json.dumps(npc_data)
        result = self.validator.validate_ai_response(npc_json, "single_npc")

        self.assertEqual(result["overall_status"], "success", msg=f"Errors: {result.get('entities', [{}])[0].get('errors', [])}, Notifications: {result.get('entities', [{}])[0].get('notifications', [])}")
        entity_result = result["entities"][0]
        self.assertEqual(entity_result["status"], "success")
        self.assertFalse(entity_result["requires_moderation"])
        self.assertEqual(len(entity_result["errors"]), 0)


    def test_validation_with_auto_corrections_only(self):
        # This NPC has intelligence out of warrior range, but everything else is fine.
        # It should be auto-corrected, resulting in "success_with_autocorrections".
        npc_data = {
            "id": "npc_autocorrect_warrior",
            "archetype": "warrior",
            "name_i18n": {"en": "Smart Warrior?", "ru": "Умный Воин?"},
            "role_i18n": {"en": "Warrior", "ru": "Воин"},
            "description_i18n": {"en": "Desc", "ru": "DescRu"}, "backstory_i18n": {"en": "Desc", "ru": "DescRu"},
            "personality_i18n": {"en": "Desc", "ru": "DescRu"}, "motivation_i18n": {"en": "Desc", "ru": "DescRu"},
            "dialogue_hints_i18n": {"en": "Desc", "ru": "DescRu"}, "visual_description_i18n": {"en": "Desc", "ru": "DescRu"},
            "stats": {"strength": 15, "health": 100, "intelligence": 20}, # Intelligence 20 is above warrior max 10
            "skills": {"combat": 50}
        }
        npc_json = json.dumps(npc_data)
        # In this version, auto-correction of stats/skills still creates an "error" message,
        # thus leading to "requires_moderation".
        # To achieve "success_with_autocorrections", the design would need to be that
        # clampings are *only* notifications and not errors.
        # The current setup: Error + Notification for clamping.
        result = self.validator.validate_ai_response(npc_json, "single_npc")

        # Current behavior: Clamping is an error, so it's "requires_moderation"
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertEqual(entity_result["status"], "requires_moderation")
        self.assertTrue(entity_result["requires_moderation"])
        self.assertTrue(any("Stat 'intelligence' value 20 for role 'warrior' was out of range (5-10). Clamped to 10." in error for error in entity_result["errors"]))
        expected_notification_fragment_intel = "AUTO-CORRECT: NPC 'npc_autocorrect_warrior': Stat 'intelligence' value 20 for role 'warrior' was out of range (5-10). Clamped to 10."
        self.assertTrue(any(expected_notification_fragment_intel in notif for notif in entity_result["notifications"]))
        self.assertEqual(entity_result["validated_data"]["stats"]["intelligence"], 10)

        # If clamping were ONLY a notification (not an error), the test would be:
        # self.assertEqual(result["overall_status"], "success_with_autocorrections")
        # entity_result = result["entities"][0]
        # self.assertEqual(entity_result["status"], "success_with_autocorrections")
        # self.assertFalse(entity_result["requires_moderation"])
        # self.assertEqual(len(entity_result["errors"]), 0) # No actual errors
        # self.assertTrue(any("AUTO-CORRECT: Stat 'intelligence' value 20 for role 'warrior' was out of range (5-10). Clamped to 10." in notif for notif in entity_result["notifications"]))
        # self.assertEqual(entity_result["validated_data"]["stats"]["intelligence"], 10)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
