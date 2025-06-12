import unittest
from unittest.mock import MagicMock
import json

from bot.ai.ai_response_validator import AIResponseValidator
from bot.ai.ai_data_models import GenerationContext, GameTerm, ValidationIssue, ValidatedEntity, ParsedAiData
from bot.ai.rules_schema import (
    GameRules, CharacterStatRules, SkillRules, ItemRules, QuestRules,
    FactionRules, RoleStatRules, StatRange, ItemPriceCategory, ItemPriceDetail,
    QuestRewardRules
    # Add other necessary rule models if they become relevant, e.g., GeneralSettings from the prompt context collector
)

class TestAIResponseValidator(unittest.TestCase):

    def setUp(self):
        # 1. Mock GameRules object
        self.mock_game_rules = GameRules(
            character_stats_rules=CharacterStatRules(
                valid_stats=["strength", "dexterity", "intelligence", "health", "mana"],
                stat_ranges_by_role={
                    "warrior": RoleStatRules(stats={
                        "strength": StatRange(min=10, max=20),
                        "health": StatRange(min=50, max=150)
                    }),
                    "mage": RoleStatRules(stats={
                        "intelligence": StatRange(min=12, max=22),
                        "mana": StatRange(min=70, max=180)
                    }),
                    "commoner": RoleStatRules(stats={ # For NPCs without a specific combat role
                        "strength": StatRange(min=5, max=15),
                        "health": StatRange(min=20, max=80)
                    })
                }
            ),
            skill_rules=SkillRules(
                valid_skills=["mining", "herbalism", "lockpicking"],
                skill_stat_map={"mining": "strength", "herbalism": "intelligence"}, # Example
                skill_value_ranges=StatRange(min=0, max=100)
            ),
            item_rules=ItemRules(
                valid_item_types=["weapon", "potion", "armor", "misc"],
                price_ranges_by_type={
                    "weapon": ItemPriceCategory(prices={
                        "common": ItemPriceDetail(min=10, max=100),
                        "rare": ItemPriceDetail(min=101, max=500)
                    }),
                    "potion": ItemPriceCategory(prices={
                        "common": ItemPriceDetail(min=5, max=50)
                    })
                },
                # valid_rarities=["common", "uncommon", "rare"] # Assuming this might exist or be added
            ),
            faction_rules=FactionRules(valid_faction_ids=["empire", "rebels", "neutral_guild"]),
            quest_rules=QuestRules(
                reward_rules=QuestRewardRules(xp_reward_range=StatRange(min=50, max=1000)),
                valid_objective_types=["kill", "collect", "goto", "interact_npc"] # Added for quest validation
                # min_quest_level=1, max_quest_level=50 # Example, if these were part of QuestRules directly
            ),
            # Mock general_settings if it's part of GameRules or used directly by validator
            # For now, assuming QuestRules might hold level ranges or we use defaults
            general_settings=MagicMock( # Using MagicMock if GeneralSettings model is not in rules_schema.py
                min_quest_level=1,
                max_character_level=60 # Used as max_quest_level by validator
            )
        )
        # Add valid_rarities to item_rules if it's a direct attribute based on rules_schema
        if hasattr(self.mock_game_rules.item_rules, 'valid_rarities'):
             self.mock_game_rules.item_rules.valid_rarities = ["common", "uncommon", "rare"]


        self.validator = AIResponseValidator(rules=self.mock_game_rules)

        # 2. Mock GenerationContext
        self.mock_game_terms_list = [
            GameTerm(id="strength", name_i18n={"en": "Strength"}, term_type="stat"),
            GameTerm(id="dexterity", name_i18n={"en": "Dexterity"}, term_type="stat"),
            GameTerm(id="intelligence", name_i18n={"en": "Intelligence"}, term_type="stat"),
            GameTerm(id="health", name_i18n={"en": "Health"}, term_type="stat"),
            GameTerm(id="mana", name_i18n={"en": "Mana"}, term_type="stat"),
            GameTerm(id="mining", name_i18n={"en": "Mining"}, term_type="skill"),
            GameTerm(id="herbalism", name_i18n={"en": "Herbalism"}, term_type="skill"),
            GameTerm(id="lockpicking", name_i18n={"en": "Lockpicking"}, term_type="skill"),
            GameTerm(id="ab001", name_i18n={"en": "Power Attack"}, term_type="ability"),
            GameTerm(id="sp001", name_i18n={"en": "Fireball"}, term_type="spell"),
            GameTerm(id="npc_guard", name_i18n={"en": "Guard"}, term_type="npc"), # Example NPC ID
            GameTerm(id="npc_merchant", name_i18n={"en": "Merchant"}, term_type="npc"),
            GameTerm(id="item_sword", name_i18n={"en": "Sword"}, term_type="item_template"),
            GameTerm(id="item_potion_health", name_i18n={"en": "Health Potion"}, term_type="item_template"),
            GameTerm(id="loc_town_square", name_i18n={"en": "Town Square"}, term_type="location"),
            GameTerm(id="empire", name_i18n={"en": "The Empire"}, term_type="faction"),
            GameTerm(id="rebels", name_i18n={"en": "Rebel Alliance"}, term_type="faction"),
            GameTerm(id="neutral_guild", name_i18n={"en": "Neutral Guild"}, term_type="faction"),
            GameTerm(id="q001_main_story", name_i18n={"en": "Main Story Quest"}, term_type="quest"),
            GameTerm(id="warrior", name_i18n={"en": "Warrior"}, term_type="archetype"), # Archetype
            GameTerm(id="mage", name_i18n={"en": "Mage"}, term_type="archetype"),
            GameTerm(id="commoner", name_i18n={"en": "Commoner"}, term_type="archetype"),
        ]
        self.mock_generation_context = GenerationContext(
            guild_id="test_guild",
            main_language="en",
            target_languages=["en", "ru", "fr"], # Adding a third for thoroughness
            request_type="test_generation",
            game_terms_dictionary=self.mock_game_terms_list
            # Other fields can be default or mocked if needed by specific validation paths
        )

        # Prepare game_terms dict for validator methods
        self.game_terms_dict_for_validation = {
            "stat_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "stat"},
            "skill_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "skill"},
            "ability_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "ability"},
            "spell_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "spell"},
            "npc_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "npc"},
            "item_template_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "item_template"},
            "location_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "location"},
            "faction_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "faction"},
            "quest_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "quest"},
            "archetype_ids": {t.id for t in self.mock_game_terms_list if t.term_type == "archetype"},
        }

    def test_validate_i18n_field_completeness(self):
        issues = []
        # Test complete
        self.validator._validate_i18n_field_completeness(
            {"en": "Hello", "ru": "Привет", "fr": "Bonjour"}, "test_field", "Entity1", issues, self.mock_generation_context.target_languages
        )
        self.assertEqual(len(issues), 0)

        # Test missing 'ru' (which is in target_languages and also a default required)
        issues.clear()
        self.validator._validate_i18n_field_completeness(
            {"en": "Hello", "fr": "Bonjour"}, "test_field", "Entity1", issues, self.mock_generation_context.target_languages
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "missing_translation")
        self.assertIn("'ru'", issues[0].message)

        # Test missing 'fr' (which is in target_languages but not a default required)
        # The refined logic ensures "ru" and "en" are always checked.
        # So, if target_languages = ["en", "ru", "fr"], and only "fr" is missing, only 1 issue.
        # If target_languages = ["de"], and "de", "en", "ru" are missing, 3 issues.
        issues.clear()
        self.validator._validate_i18n_field_completeness(
            {"en": "Hello", "ru": "Привет"}, "test_field", "Entity1", issues, ["en", "ru", "fr"] # Explicitly pass target langs for this test
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "missing_translation")
        self.assertIn("'fr'", issues[0].message) # Checks "fr" from target_languages
        issues.clear()


        # Test empty string for 'en'
        self.validator._validate_i18n_field_completeness(
            {"en": "  ", "ru": "Привет", "fr": "Bonjour"}, "test_field", "Entity1", issues, self.mock_generation_context.target_languages
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "empty_translation")
        self.assertIn("'en'", issues[0].message)
        issues.clear()

        # Test non-string value
        self.validator._validate_i18n_field_completeness(
            {"en": "Hello", "ru": 123, "fr": "Bonjour"}, "test_field", "Entity1", issues, self.mock_generation_context.target_languages
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "empty_translation") # current logic treats non-string as empty/invalid
        self.assertIn("'ru'", issues[0].message)
        issues.clear()

        # Test that "en" and "ru" are checked even if not in target_languages (as per refinement)
        custom_target_langs = ["de"] # "en" and "ru" should still be checked due to update(["ru", "en"])
        self.validator._validate_i18n_field_completeness(
            {"de": "Hallo"}, "test_field", "Entity1", issues, custom_target_langs
        )
        self.assertEqual(len(issues), 2) # Missing en, missing ru. "de" is present.
        self.assertTrue(any("'en'" in issue.message and issue.issue_type == "missing_translation" for issue in issues))
        self.assertTrue(any("'ru'" in issue.message and issue.issue_type == "missing_translation" for issue in issues))
        issues.clear()


    # Placeholder for other test methods
    def test_validate_npc_block_valid(self):
        npc_data = {
            "template_id": "npc001",
            "name_i18n": {"en": "Valid Guard", "ru": "Валидный стражник", "fr": "Garde Valide"},
            "backstory_i18n": {"en": "A sturdy guard.", "ru": "Крепкий стражник.", "fr": "Un garde robuste."},
            "role_i18n": {"en": "Guard", "ru": "Страж", "fr":"Garde"},
            "archetype": "commoner", # Assuming 'commoner' is in game_terms.archetype_ids or rules
            "stats": {"strength": 12, "health": 50},
            "skills": {"mining": 10},
            "abilities": ["ab001"],
            "spells": [],
            "inventory": [{"item_template_id": "item_sword", "quantity": 1}],
            "faction_affiliations": [{"faction_id": "empire", "rank_i18n": {"en": "Soldier"}}]
        }
        result = self.validator.validate_npc_block(npc_data, self.mock_generation_context, self.game_terms_dict_for_validation)
        self.assertEqual(result.validation_status, "success")
        # Minor info issues might be present from _get_canonical_role_key, so check specific errors
        error_issues = [iss for iss in result.issues if iss.severity == "error"]
        self.assertEqual(len(error_issues), 0, f"Expected no errors, got: {result.issues}")


    def test_validate_npc_block_issues_and_autocorrections(self):
        npc_data = {
            "template_id": "npc002",
            "name_i18n": {"en": "Problematic NPC"}, # Missing ru, fr
            "backstory_i18n": {"en": "Story only in English.", "ru": "", "fr": "   "}, # Empty/whitespace
            "archetype": "unknown_archetype", # Invalid
            "stats": {
                "strength": 30, # Out of range for 'commoner' (assuming role determination falls back or uses a default)
                "invalid_stat": 10 # Not in valid_stats
            },
            "skills": {"mining": 150, "unknown_skill": 50}, # Out of range, invalid skill
            "abilities": ["ab001", "unknown_ability"],
            "inventory": [
                {"item_template_id": "item_potion_health"}, # Quantity missing (should auto-correct to 1)
                {"item_template_id": "unknown_item", "quantity": 1},
                {"item_template_id": "item_sword", "quantity": 0} # Invalid quantity
            ],
            "faction_affiliations": [{"faction_id": "unknown_faction"}]
        }

        # For role determination, let's assume it defaults to 'commoner' if archetype is invalid,
        # or we can explicitly set a role_i18n that maps to commoner.
        npc_data["role_i18n"] = {"en": "commoner"}


        result = self.validator.validate_npc_block(npc_data, self.mock_generation_context, self.game_terms_dict_for_validation)

        self.assertNotEqual(result.validation_status, "success")
        self.assertTrue(any(iss.issue_type == "missing_translation" for iss in result.issues))
        self.assertTrue(any(iss.issue_type == "empty_translation" for iss in result.issues))
        self.assertTrue(any(iss.field == "archetype" and iss.issue_type == "invalid_reference" for iss in result.issues))

        # Check stat auto-correction and errors
        self.assertTrue(any(iss.field == "stats.strength" and iss.issue_type == "auto_correction" for iss in result.issues))
        self.assertEqual(result.data["stats"]["strength"], self.mock_game_rules.character_stats_rules.stat_ranges_by_role["commoner"].stats["strength"].max) # Clamped
        self.assertTrue(any(iss.field == "stats.invalid_stat" and iss.issue_type == "invalid_reference" for iss in result.issues))

        # Check skill auto-correction and errors
        self.assertTrue(any(iss.field == "skills.mining" and iss.issue_type == "auto_correction" for iss in result.issues))
        self.assertEqual(result.data["skills"]["mining"], self.mock_game_rules.skill_rules.skill_value_ranges.max) # Clamped
        self.assertTrue(any(iss.field == "skills.unknown_skill" and iss.issue_type == "invalid_reference" for iss in result.issues))

        # Check list validations (abilities, inventory)
        self.assertTrue(any(iss.field == "abilities[1]" and iss.issue_type == "invalid_reference" for iss in result.issues)) # unknown_ability

        inv_issues = [iss for iss in result.issues if iss.field.startswith("inventory")]
        self.assertTrue(any(iss.field == "inventory[0].quantity" and iss.issue_type == "auto_correction" for iss in inv_issues)) # Missing quantity
        self.assertEqual(result.data["inventory"][0]["quantity"], 1)
        self.assertTrue(any(iss.field == "inventory[1].item_template_id" and iss.issue_type == "invalid_reference" for iss in inv_issues)) # unknown_item
        self.assertTrue(any(iss.field == "inventory[2].quantity" and iss.issue_type == "invalid_value" for iss in inv_issues)) # quantity 0

        # Check faction affiliation
        self.assertTrue(any(iss.field == "faction_affiliations[0].faction_id" and iss.issue_type == "invalid_reference" for iss in result.issues))

    def test_validate_quest_block_valid(self):
        quest_data = {
            "id": "q001",
            "title_i18n": {"en": "The Dragon's Tooth", "ru": "Зуб Дракона", "fr": "La Dent du Dragon"},
            "description_i18n": {"en": "A quest to find a legendary artifact.", "ru": "Квест по поиску легендарного артефакта.", "fr": "Une quête pour trouver un artefact légendaire."},
            "suggested_level": 5,
            "quest_giver_id": "npc_guard",
            "prerequisites": [],
            "stages": [
                {
                    "stage_id": "s1",
                    "title_i18n": {"en": "Gather Clues", "ru": "Собрать улики", "fr": "Recueillir des indices"},
                    "description_i18n": {"en": "Ask around the village.", "ru": "Расспросить в деревне.", "fr": "Demandez autour du village."},
                    "objectives": [
                        {"objective_id": "o1_1", "description_i18n": {"en": "Talk to the Elder", "ru": "Поговорить со старейшиной", "fr": "Parler à l'Ancien"}, "type": "interact_npc", "target_id": "npc_merchant"}
                    ]
                }
            ],
            "rewards": {"experience_points": 200, "items": [{"item_template_id": "item_sword", "quantity": 1}]}
        }
        result = self.validator.validate_quest_block(quest_data, self.mock_generation_context, self.game_terms_dict_for_validation)
        self.assertEqual(result.validation_status, "success", f"Expected success, got issues: {result.issues}")
        error_issues = [iss for iss in result.issues if iss.severity == "error"]
        self.assertEqual(len(error_issues), 0, f"Expected no errors, got: {result.issues}")


    def test_validate_quest_block_issues_and_autocorrections(self):
        quest_data = {
            "id": "q002",
            "title_i18n": {"en": "Problematic Quest"}, # Missing ru, fr
            "description_i18n": {"en": "Desc", "ru": "", "fr": "   "}, # Empty/whitespace
            "suggested_level": 200, # Out of range (max_character_level is 60 in mock_game_rules.general_settings)
            "quest_giver_id": "unknown_npc", # Invalid
            "prerequisites": ["unknown_quest_id"],
            "stages": [
                { # Stage 0
                    "stage_id": "s1_bad",
                    "title_i18n": {"en": "Bad Stage"}, # Missing other langs
                    "description_i18n": {"en": "This stage has issues."},
                    "objectives": [
                        {"objective_id": "o1_badtype", "description_i18n": {"en":"Invalid Type Obj"}, "type": "unknown_type", "target_id": "npc_guard"},
                        {"objective_id": "o2_badtarget", "description_i18n": {"en":"Kill Item?"}, "type": "kill", "target_id": "item_sword"}, # kill target should be NPC
                        {"objective_id": "o3_badskillcheck", "description_i18n": {"en":"Bad Skill Check"}, "type": "interact_npc", "target_id": "npc_guard",
                         "skill_check": {"skill_id": "unknown_skill", "dc": -5, "description_i18n": {"en":"Desc"}}}
                    ]
                },
                { # Stage 1 (missing objectives list)
                    "stage_id": "s2_no_objectives",
                    "title_i18n": {"en": "Stage Lacking Objectives", "ru": "Этап без целей", "fr":"Étape sans objectifs"},
                    "description_i18n": {"en": "This stage has no objectives array.", "ru": "У этого этапа нет списка целей.", "fr":"Cette étape n'a pas de tableau d'objectifs."},
                    # "objectives": [] # Missing objectives key
                }
            ],
            "rewards": {
                "experience_points": 20000, # Out of range
                "items": [
                    {"item_template_id": "unknown_item", "quantity": 1},
                    {"item_template_id": "item_potion_health", "quantity": -1} # Invalid quantity
                ]
            }
        }
        result = self.validator.validate_quest_block(quest_data, self.mock_generation_context, self.game_terms_dict_for_validation)
        self.assertNotEqual(result.validation_status, "success")

        # Check for specific issues
        self.assertTrue(any(iss.field == "title_i18n" and iss.issue_type == "missing_translation" for iss in result.issues))
        self.assertTrue(any(iss.field == "description_i18n.ru" and iss.issue_type == "empty_translation" for iss in result.issues))

        self.assertTrue(any(iss.field == "suggested_level" and iss.issue_type == "auto_correction" for iss in result.issues))
        self.assertEqual(result.data["suggested_level"], self.mock_game_rules.general_settings.max_character_level) # Clamped

        self.assertTrue(any(iss.field == "quest_giver_id" and iss.issue_type == "invalid_reference" for iss in result.issues))
        self.assertTrue(any(iss.field == "prerequisites[0]" and iss.issue_type == "invalid_reference" for iss in result.issues))

        # Stage 0 issues
        self.assertTrue(any(iss.field == "stages[0].objectives[0].type" and iss.issue_type == "invalid_value" for iss in result.issues)) # unknown_type
        self.assertTrue(any(iss.field == "stages[0].objectives[1].target_id" and iss.issue_type == "invalid_reference" for iss in result.issues)) # kill item_sword
        self.assertTrue(any(iss.field == "stages[0].objectives[2].skill_check.skill_id" and iss.issue_type == "invalid_reference" for iss in result.issues)) # unknown_skill
        self.assertTrue(any(iss.field == "stages[0].objectives[2].skill_check.dc" and iss.issue_type == "invalid_value" for iss in result.issues)) # dc -5

        # Stage 1 issues
        self.assertTrue(any(iss.field == "stages[1].objectives" and iss.issue_type == "missing_or_invalid_type" for iss in result.issues)) # Missing objectives

        # Reward issues
        self.assertTrue(any(iss.field == "rewards.experience_points" and iss.issue_type == "auto_correction" for iss in result.issues))
        self.assertEqual(result.data["rewards"]["experience_points"], self.mock_game_rules.quest_rules.reward_rules.xp_reward_range.max) # Clamped
        self.assertTrue(any(iss.field == "rewards.items[0].item_template_id" and iss.issue_type == "invalid_reference" for iss in result.issues))
        self.assertTrue(any(iss.field == "rewards.items[1].quantity" and iss.issue_type == "invalid_value" for iss in result.issues))

    def test_validate_item_block_valid(self):
        item_data = {
            "template_id": "item001_valid_sword",
            "name_i18n": {"en": "Fine Sword", "ru": "Отличный меч", "fr": "Bonne Épée"},
            "description_i18n": {"en": "A well-crafted sword.", "ru": "Хорошо сделанный меч.", "fr": "Une épée bien conçue."},
            "item_type": "weapon",
            "rarity": "common",
            "value": 50, # In range for weapon/common (10-100)
            "stackable": False,
            "properties_i18n": {
                "damage_bonus": {"en": "5"}, # Numeric property
                "weight": {"en": "3.5"}      # Numeric property
            },
            "requirements": {"level": 5, "strength": 10}
        }
        result = self.validator.validate_item_block(item_data, self.mock_generation_context, self.game_terms_dict_for_validation)
        self.assertEqual(result.validation_status, "success", f"Expected success, got issues: {result.issues}")
        error_issues = [iss for iss in result.issues if iss.severity == "error"]
        self.assertEqual(len(error_issues), 0, f"Expected no errors, got: {result.issues}")

    def test_validate_item_block_issues_and_autocorrections(self):
        item_data = {
            "template_id": "item002_problem_potion",
            "name_i18n": {"en": "Problematic Potion"}, # Missing ru, fr
            "description_i18n": {"en": "Desc only en", "ru": "", "fr":" "}, # Empty/whitespace
            "item_type": "unknown_type", # Invalid
            "rarity": "mythical", # Not in mock valid_rarities (if self.mock_game_rules.item_rules.valid_rarities was set)
            "value": 1000, # Out of range for potion/common (5-50), will be clamped
            "stackable": "not_a_boolean",
            "properties_i18n": {
                "healing_amount": {"en": "a lot"}, # Known numeric, but not a number
                "weight": {"en": "-5"} # Assuming weight should be positive, though not explicitly checked yet
            },
            "requirements": {"level": "high", "unknown_stat": 100, "mining": 0} # Invalid level type, unknown_stat, skill value 0
        }
        # For price clamping, AIResponseValidator uses item_type if valid, or might not clamp if type is invalid.
        # Let's make item_type valid to test clamping properly.
        item_data_for_price_clamp = item_data.copy()
        item_data_for_price_clamp["item_type"] = "potion"
        item_data_for_price_clamp["rarity"] = "common" # to use potion/common range 5-50

        result = self.validator.validate_item_block(item_data_for_price_clamp, self.mock_generation_context, self.game_terms_dict_for_validation)
        self.assertNotEqual(result.validation_status, "success")

        # Check for specific issues
        self.assertTrue(any(iss.field == "name_i18n" and iss.issue_type == "missing_translation" for iss in result.issues))
        self.assertTrue(any(iss.field == "description_i18n.ru" and iss.issue_type == "empty_translation" for iss in result.issues))

        # item_type "unknown_type" would be an error if valid_item_types is enforced by rules_schema or a check.
        # Current test mock_game_rules.item_rules.valid_item_types = ["weapon", "potion", "armor", "misc"]
        # The original item_data had "unknown_type". The test uses item_data_for_price_clamp which has "potion".
        # To test invalid item_type, we'd pass original item_data.
        # Let's assume that test is covered if valid_item_types is used.
        # For rarity "mythical", if valid_rarities = ["common", "uncommon", "rare"] in GameRules, it would flag.
        # This depends on whether valid_rarities is actually part of ItemRules or just used implicitly.
        # The current ItemRules Pydantic model in rules_schema.py does not have valid_rarities.
        # So, no issue for "mythical" rarity unless GameRules is updated.

        self.assertTrue(any(iss.field == "value" and iss.issue_type == "auto_correction" for iss in result.issues))
        # Potion/common is 5-50. Value 1000 clamped to 50.
        self.assertEqual(result.data["value"], self.mock_game_rules.item_rules.price_ranges_by_type["potion"].prices["common"].max)

        self.assertTrue(any(iss.field == "stackable" and iss.issue_type == "invalid_type" for iss in result.issues))

        self.assertTrue(any(iss.field == "properties_i18n.healing_amount" and iss.issue_type == "invalid_type" for iss in result.issues))

        self.assertTrue(any(iss.field == "requirements.level" and iss.issue_type == "invalid_value" for iss in result.issues))
        self.assertTrue(any(iss.field == "requirements.unknown_stat" for iss in result.issues)) # Implicitly an issue as it's not a known stat/skill
        self.assertTrue(any(iss.field == "requirements.mining" and iss.issue_type == "invalid_value" for iss in result.issues)) # quantity 0

    def test_validate_ai_response_orchestration(self):
        # Test valid single NPC
        valid_npc_json = json.dumps({
            "template_id": "npc_valid", "name_i18n": {"en": "OK NPC", "ru": "ОК НПЦ", "fr":"OK NPC"},
            "archetype": "commoner", "stats": {"health": 30}, "role_i18n": {"en":"commoner"}
        })
        result = self.validator.validate_ai_response(valid_npc_json, "single_npc", self.mock_generation_context)
        self.assertEqual(result.overall_status, "success")
        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.entities[0].entity_type, "npc")
        self.assertEqual(result.entities[0].validation_status, "success")

        # Test list of NPCs, one problematic
        list_npc_json = json.dumps([
            {"template_id": "npc_good", "name_i18n": {"en": "Good", "ru": "Хороший", "fr":"Bien"}, "archetype": "commoner", "stats": {"health": 40}, "role_i18n": {"en":"commoner"}},
            {"template_id": "npc_bad_stats", "name_i18n": {"en": "Bad Stats", "ru": "Плохие статы", "fr":"Mauvais Stats"}, "archetype": "warrior", "stats": {"strength": 500}, "role_i18n": {"en":"warrior"}} # Strength out of range
        ])
        result_list = self.validator.validate_ai_response(list_npc_json, "list_of_npcs", self.mock_generation_context)
        self.assertEqual(result_list.overall_status, "success_with_autocorrections") # Due to clamping
        self.assertEqual(len(result_list.entities), 2)
        self.assertEqual(result_list.entities[0].validation_status, "success")
        self.assertEqual(result_list.entities[1].validation_status, "success_with_autocorrections")
        self.assertTrue(any(iss.issue_type == "auto_correction" for iss in result_list.entities[1].issues))

        # Test invalid JSON string
        invalid_json = "{'bad_json': True,}" # Python dict style, not valid JSON
        result_bad_json = self.validator.validate_ai_response(invalid_json, "single_npc", self.mock_generation_context)
        self.assertEqual(result_bad_json.overall_status, "error")
        self.assertTrue(any("Invalid JSON format" in err for err in result_bad_json.global_errors))

        # Test valid JSON but wrong root structure (expected list, got dict)
        wrong_structure_json = json.dumps({"template_id": "not_a_list_npc", "name_i18n": {"en": "NPC", "ru": "НПЦ", "fr":"NPC"}})
        result_wrong_structure = self.validator.validate_ai_response(wrong_structure_json, "list_of_npcs", self.mock_generation_context)
        self.assertEqual(result_wrong_structure.overall_status, "error")
        self.assertTrue(any("Expected a list" in err for err in result_wrong_structure.global_errors))
        self.assertEqual(len(result_wrong_structure.entities), 0)

        # Test list input where an item is not a dict
        list_with_bad_item_json = json.dumps([
            {"template_id": "npc_item1", "name_i18n": {"en": "Item 1", "ru": "Итем 1", "fr":"Item 1"}, "archetype":"commoner", "role_i18n": {"en":"commoner"}},
            "not_a_dictionary_item"
        ])
        result_list_bad_item = self.validator.validate_ai_response(list_with_bad_item_json, "list_of_npcs", self.mock_generation_context)
        self.assertEqual(result_list_bad_item.overall_status, "requires_moderation") # One good, one bad (error severity on bad item)
        self.assertEqual(len(result_list_bad_item.entities), 2)
        self.assertEqual(result_list_bad_item.entities[0].validation_status, "success")
        self.assertEqual(result_list_bad_item.entities[1].validation_status, "requires_moderation")
        self.assertTrue(any(iss.issue_type == "invalid_type" and "not a dictionary" in iss.message for iss in result_list_bad_item.entities[1].issues))

        # Test unknown expected_structure
        result_unknown_struct = self.validator.validate_ai_response(valid_npc_json, "unknown_structure_type", self.mock_generation_context)
        self.assertEqual(result_unknown_struct.overall_status, "error")
        self.assertTrue(any("Unknown expected_structure" in err for err in result_unknown_struct.global_errors))


if __name__ == '__main__':
    unittest.main()
