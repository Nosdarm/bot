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
                        "intelligence": StatRange(min=5, max=10)
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
                    "weapon": ItemPriceCategory(prices={
                        "common": ItemPriceDetail(min=10, max=100),
                        "rare": ItemPriceDetail(min=101, max=500)
                    }),
                    "potion": ItemPriceCategory(prices={
                        "common": ItemPriceDetail(min=5, max=50)
                    }),
                    "armor": ItemPriceCategory(prices={ # Added for more test cases
                        "common": ItemPriceDetail(min=20, max=120)
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

    def _create_base_npc_data(self, npc_id="test_npc"):
        return {
            "id": npc_id, "archetype": "commoner",
            "name_i18n": {"en": "Test NPC", "ru": "Тестовый НПС"},
            "role_i18n": {"en": "Commoner", "ru": "Простолюдин"},
            "description_i18n": {"en": "Desc", "ru": "DescRu"}, "backstory_i18n": {"en": "Desc", "ru": "DescRu"},
            "personality_i18n": {"en": "Desc", "ru": "DescRu"}, "motivation_i18n": {"en": "Desc", "ru": "DescRu"},
            "dialogue_hints_i18n": {"en": "Desc", "ru": "DescRu"}, "visual_description_i18n": {"en": "Desc", "ru": "DescRu"},
            "stats": {"strength": 7, "health": 30, "intelligence": 10},
            "skills": {"stealth": 25}
        }

    def _create_base_quest_data(self, quest_id="test_quest"):
        return {
            "id": quest_id,
            "name_i18n": {"en": "Test Quest", "ru": "Тестовый Квест"},
            "description_i18n": {"en": "Desc", "ru": "DescRu"},
            "quest_giver_details_i18n": {"en": "Desc", "ru": "DescRu"},
            "consequences_summary_i18n": {"en": "Desc", "ru": "DescRu"},
            "stages_i18n": {
                "stage1": {
                    "title_i18n": {"en": "S1 Title", "ru": "S1 Заголовок"},
                    "description_i18n": {"en": "S1 Desc", "ru": "S1 Описание"},
                    "requirements_description_i18n": {"en": "S1 Req", "ru": "S1 Требования"},
                    "alternative_solutions_i18n": {"en": "S1 Alt", "ru": "S1 Альт"},
                    "objectives_i18n": [
                        {"description_i18n": {"en": "Obj1", "ru": "Цель1"}}
                    ]
                }
            }
        }

    def _create_base_item_data(self, item_id="test_item"):
        return {
            "id": item_id, # Or template_id if that's primary
            "template_id": item_id,
            "name_i18n": {"en": "Test Item", "ru": "Тестовый Предмет"},
            "description_i18n": {"en": "A test item.", "ru": "Тестовый предмет."},
            "type": "potion", # Default valid type
            "rarity": "common",
            "price": 10
        }

    # --- Existing Tests (condensed for brevity in this display) ---
    def test_invalid_json_format(self):
        invalid_json = "this is not json"
        result = self.validator.validate_ai_response(invalid_json, "single_npc")
        self.assertEqual(result["overall_status"], "error")
        self.assertTrue(any("Invalid JSON format" in error for error in result["global_errors"]))

    def test_list_vs_dict_structure(self):
        npc_dict_json = json.dumps({"id": "npc1", "name_i18n": {"en": "Guard", "ru": "Страж"}})
        result = self.validator.validate_ai_response(npc_dict_json, "list_of_npcs")
        self.assertEqual(result["overall_status"], "error")
        self.assertTrue(any("Expected a list for 'list_of_npcs'" in error for error in result["global_errors"]))
        npc_list_json = json.dumps([{"id": "npc1", "name_i18n": {"en": "Guard", "ru": "Страж"}}])
        result = self.validator.validate_ai_response(npc_list_json, "single_npc")
        self.assertEqual(result["overall_status"], "error")
        self.assertTrue(any("Expected a dictionary for 'single_npc'" in error for error in result["global_errors"]))

    def test_i18n_completeness_npc_name_missing_lang(self):
        npc_data = self._create_base_npc_data()
        npc_data["name_i18n"] = {"en": "Warrior"}
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Field 'name_i18n' is missing translation for language 'ru'" in error for error in entity_result["errors"]))

    def test_i18n_completeness_npc_name_empty_lang(self):
        npc_data = self._create_base_npc_data()
        npc_data["name_i18n"] = {"en": "Warrior", "ru": "  "}
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Field 'name_i18n' has empty or non-string content for language 'ru'" in error for error in entity_result["errors"]))

    def test_npc_stat_validation_out_of_range_and_clamped(self):
        npc_data = self._create_base_npc_data("npc_warrior_low_str")
        npc_data["archetype"] = "warrior"
        npc_data["role_i18n"] = {"en": "Warrior", "ru": "Воин"}
        npc_data["stats"]["strength"] = 5
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Stat 'strength' value 5 for role 'warrior' was out of range (10-20). Clamped to 10." in error for error in entity_result["errors"]))
        expected_notification_fragment = "AUTO-CORRECT: NPC 'npc_warrior_low_str': Stat 'strength' value 5 for role 'warrior' was out of range (10-20). Clamped to 10."
        self.assertTrue(any(expected_notification_fragment in notif for notif in entity_result["notifications"]))
        self.assertEqual(entity_result["validated_data"]["stats"]["strength"], 10)

    def test_npc_stat_validation_invalid_name(self):
        npc_data = self._create_base_npc_data("npc_invalid_stat")
        npc_data["stats"]["invalid_stat_name"] = 10
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Invalid stat name: 'invalid_stat_name'" in error for error in entity_result["errors"]))

    def test_successful_validation_npc(self):
        npc_data = self._create_base_npc_data("npc_valid_commoner")
        npc_data["archetype"] = "commoner" # Ensure it matches base data stats
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "success", msg=f"Full result: {result}")
        entity_result = result["entities"][0]
        self.assertEqual(entity_result["status"], "success")
        self.assertFalse(entity_result["requires_moderation"])
        self.assertEqual(len(entity_result["errors"]), 0)

    def test_validation_with_auto_corrections_only(self):
        npc_data = self._create_base_npc_data("npc_autocorrect_warrior")
        npc_data["archetype"] = "warrior"
        npc_data["role_i18n"] = {"en": "Warrior", "ru": "Воин"}
        npc_data["stats"]["intelligence"] = 20 # Warrior int max 10
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertEqual(entity_result["status"], "requires_moderation")
        expected_error_fragment = "Stat 'intelligence' value 20 for role 'warrior' was out of range (5-10). Clamped to 10."
        self.assertTrue(any(expected_error_fragment in error for error in entity_result["errors"]))
        expected_notification_fragment = "AUTO-CORRECT: NPC 'npc_autocorrect_warrior': Stat 'intelligence' value 20 for role 'warrior' was out of range (5-10). Clamped to 10."
        self.assertTrue(any(expected_notification_fragment in notif for notif in entity_result["notifications"]))
        self.assertEqual(entity_result["validated_data"]["stats"]["intelligence"], 10)

    # --- New Tests ---

    # NPC Skill and Faction
    def test_npc_skill_validation_invalid_name(self):
        npc_data = self._create_base_npc_data("npc_invalid_skill")
        npc_data["skills"]["unknown_skill"] = 50
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Invalid skill name: 'unknown_skill'" in error for error in entity_result["errors"]))

    def test_npc_skill_validation_valid(self):
        npc_data = self._create_base_npc_data("npc_valid_skill_user")
        npc_data["skills"]["combat"] = 50 # 'combat' is a valid skill
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "success", msg=f"Full result: {result}") # Assuming base NPC is otherwise valid

    def test_npc_faction_validation_invalid_id(self):
        npc_data = self._create_base_npc_data("npc_invalid_faction")
        npc_data["faction_affiliations"] = [{"faction_id": "faction_c", "rank_i18n": {"en": "Member", "ru": "Член"}}]
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Invalid faction_id 'faction_c'" in error for error in entity_result["errors"]))

    def test_npc_faction_i18n_rank(self):
        npc_data = self._create_base_npc_data("npc_faction_i18n_rank")
        npc_data["faction_affiliations"] = [{"faction_id": "faction_a", "rank_i18n": {"en": "Leader"}}] # Missing 'ru'
        result = self.validator.validate_ai_response(json.dumps(npc_data), "single_npc")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Field 'rank_i18n' is missing translation for language 'ru'" in error for error in entity_result["errors"]))

    # Quest Validation
    def test_quest_prerequisites_invalid_id(self):
        quest_data = self._create_base_quest_data("q_invalid_prereq")
        quest_data["prerequisites"] = ["non_existent_quest"]
        result = self.validator.validate_ai_response(json.dumps(quest_data), "single_quest", existing_quest_ids={"q1"})
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        expected_error = f"Quest '{quest_data['id']}': Prerequisite quest ID 'non_existent_quest' invalid/not found."
        self.assertTrue(any(expected_error == error for error in entity_result["errors"]), msg=f"Expected error: '{expected_error}'. Actual: {entity_result['errors']}")

    def test_quest_npc_involvement_invalid_id(self):
        quest_data = self._create_base_quest_data("q_invalid_npc")
        quest_data["npc_involvement"] = {"quest_giver": "non_existent_npc"}
        result = self.validator.validate_ai_response(json.dumps(quest_data), "single_quest", existing_npc_ids={"n1"})
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        # Corrected format based on validator code: ({role}) not (role: {role}) and ensure period.
        expected_error = f"Quest '{quest_data['id']}': Involved NPC ID 'non_existent_npc' (quest_giver) invalid/not found."
        self.assertTrue(any(expected_error == error for error in entity_result["errors"]), msg=f"Expected error: '{expected_error}'. Actual: {entity_result['errors']}")

    def test_quest_stage_structure_missing_objectives(self):
        quest_data = self._create_base_quest_data("q_missing_obj")
        del quest_data["stages_i18n"]["stage1"]["objectives_i18n"]
        result = self.validator.validate_ai_response(json.dumps(quest_data), "single_quest")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        expected_error = f"Quest '{quest_data['id']}', Stage 'stage1': Objectives missing/invalid."
        self.assertTrue(any(expected_error == error for error in entity_result["errors"]), msg=f"Expected error: '{expected_error}'. Actual: {entity_result['errors']}")

    def test_quest_reward_xp_clamped(self):
        quest_data = self._create_base_quest_data("q_xp_clamp")
        quest_data["rewards"] = {"experience": 2000} # Max is 1000
        result = self.validator.validate_ai_response(json.dumps(quest_data), "single_quest")
        self.assertEqual(result["overall_status"], "requires_moderation") # Clamping is an error
        entity_result = result["entities"][0]
        expected_error = f"Quest '{quest_data['id']}': XP 2000 out of range (10-1000). Clamped to 1000."
        self.assertTrue(any(expected_error == error for error in entity_result["errors"]), msg=f"Expected error: '{expected_error}'. Actual: {entity_result['errors']}")
        expected_notif_full = f"AUTO-CORRECT: Quest '{quest_data['id']}': XP 2000 out of range (10-1000). Clamped to 1000."
        self.assertTrue(any(expected_notif_full == notif for notif in entity_result["notifications"]), msg=f"Expected notification: '{expected_notif_full}'. Actual: {entity_result['notifications']}")
        self.assertEqual(entity_result["validated_data"]["rewards"]["experience"], 1000)

    def test_quest_reward_item_invalid_template_id(self):
        quest_data = self._create_base_quest_data("q_invalid_item_reward")
        quest_data["rewards"] = {"items": ["non_existent_item_template"]}
        result = self.validator.validate_ai_response(json.dumps(quest_data), "single_quest", existing_item_template_ids={"item1"})
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Item template_id 'non_existent_item_template' not found" in error for error in entity_result["errors"]))

    # Item Validation
    def test_item_invalid_type(self):
        item_data = self._create_base_item_data("item_invalid_type")
        item_data["type"] = "magical_scroll" # Not in default valid_item_types
        result = self.validator.validate_ai_response(json.dumps(item_data), "single_item")
        self.assertEqual(result["overall_status"], "requires_moderation")
        entity_result = result["entities"][0]
        self.assertTrue(any("Invalid item type: 'magical_scroll'" in error for error in entity_result["errors"]))

    def test_item_price_out_of_range_and_clamped(self):
        item_data = self._create_base_item_data("item_pricey_potion")
        item_data["type"] = "potion"
        item_data["rarity"] = "common"
        item_data["price"] = 200 # Potion common max is 50
        result = self.validator.validate_ai_response(json.dumps(item_data), "single_item")
        self.assertEqual(result["overall_status"], "requires_moderation") # Clamping is an error
        entity_result = result["entities"][0]

        # Precise error message based on validator code and traceback
        expected_error = f"Item '{item_data['id']}': Price 200 for type 'potion' rarity 'common' out of range (5-50). Clamped to 50."
        self.assertTrue(any(expected_error == error for error in entity_result["errors"]), msg=f"Expected error: '{expected_error}'. Actual errors: {entity_result['errors']}")

        expected_notif_full = f"AUTO-CORRECT: Item '{item_data['id']}': Price 200 for type 'potion' rarity 'common' out of range (5-50). Clamped to 50."
        self.assertTrue(any(expected_notif_full == notif for notif in entity_result["notifications"]), msg=f"Expected notification: '{expected_notif_full}'. Actual notifications: {entity_result['notifications']}")
        self.assertEqual(entity_result["validated_data"]["price"], 50)

    def test_item_missing_expected_property_weapon(self):
        item_data = self._create_base_item_data("item_weapon_no_dmg")
        item_data["type"] = "weapon"
        # 'damage' field is missing
        result = self.validator.validate_ai_response(json.dumps(item_data), "single_item")
        # This is a notification-only, so overall status might be success if no other errors
        # Depending on base_item_data, it might have other issues if not perfectly valid.
        # Let's assume base_item_data for type 'weapon' would be valid if 'damage' was there.
        # For this test, we ensure the notification is present.
        # If other parts of base_item_data are not perfect for 'weapon', status might be requires_moderation.
        # For now, let's just check notification.
        entity_result = result["entities"][0]
        # Corrected based on debug output
        expected_notif_correct_full = f"Item '{item_data['id']}': Weapon missing 'damage' field (soft check)."

        found = any(expected_notif_correct_full in notif for notif in entity_result["notifications"])
        if not found:
            print(f"\nDEBUG: test_item_missing_expected_property_weapon - Actual Notifications: {entity_result['notifications']}")
            print(f"DEBUG: test_item_missing_expected_property_weapon - Expected Full: {expected_notif_correct_full}")

        self.assertTrue(found, msg=f"Expected notification containing '{expected_notif_correct_full}' not found in {entity_result['notifications']}")


    # Overall Status
    def test_validate_ai_response_overall_status_requires_moderation_list(self):
        npc1_valid = self._create_base_npc_data("npc1_valid")
        npc2_invalid_skill = self._create_base_npc_data("npc2_invalid_skill")
        npc2_invalid_skill["skills"]["super_skill"] = 100 # invalid skill name

        npcs_json = json.dumps([npc1_valid, npc2_invalid_skill])
        result = self.validator.validate_ai_response(npcs_json, "list_of_npcs")
        self.assertEqual(result["overall_status"], "requires_moderation")
        self.assertEqual(result["entities"][0]["status"], "success")
        self.assertEqual(result["entities"][1]["status"], "requires_moderation")

    def test_validate_ai_response_overall_status_success_list(self):
        npc1_valid = self._create_base_npc_data("npc1_all_good")
        npc2_valid = self._create_base_npc_data("npc2_all_good")

        npcs_json = json.dumps([npc1_valid, npc2_valid])
        result = self.validator.validate_ai_response(npcs_json, "list_of_npcs")
        self.assertEqual(result["overall_status"], "success", msg=f"Full result: {result}")
        self.assertEqual(result["entities"][0]["status"], "success")
        self.assertEqual(result["entities"][1]["status"], "success")


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
