import unittest
import json
from unittest.mock import MagicMock, patch, mock_open, AsyncMock

from bot.ai.prompt_context_collector import PromptContextCollector
from bot.ai.ai_data_models import GenerationContext # Assuming these are in this path. GameTerm and ScalingParameter removed.

# Mocking the actual game models that might be returned by managers
# These can be simple MagicMock instances or basic dicts if managers are expected to return dicts
MockCharacter = MagicMock
MockNpc = MagicMock
MockQuest = MagicMock # Or dict
MockRelationship = MagicMock # Or dict
MockItem = MagicMock # Or dict
MockLocation = MagicMock # Or dict
MockAbility = MagicMock # Or dict (AbilityTemplate in validator)
MockSpell = MagicMock # Or dict (SpellTemplate in validator)
MockEvent = MagicMock # Or dict
MockParty = MagicMock # Or dict
MockTimeManager = MagicMock # Actual TimeManager class if methods are complex

class TestPromptContextCollector(unittest.TestCase):

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
                        "warrior": {
                            "stats": {
                                "strength": {"min": 10, "max": 20},
                                "dexterity": {"min": 8, "max": 16}
                            }
                        },
                        "mage": {
                             "stats": {
                                "intelligence": {"min": 12, "max": 20}
                            }
                        }
                    },
                    "valid_stats": ["strength", "dexterity", "intelligence"] # Used by validator, good to have for game_terms consistency
                },
                "skill_rules": {
                    "skills": {
                        "mining": {"name_i18n": {"en": "Mining", "ru": "Добыча руды"}, "description_i18n": {"en": "Ability to mine ores", "ru": "Способность добывать руду"}},
                        "herbalism": {"name_i18n": {"en": "Herbalism", "ru": "Травничество"}, "description_i18n": {"en": "Ability to gather herbs", "ru": "Способность собирать травы"}}
                    },
                    "valid_skills": ["mining", "herbalism"] # Used by validator
                },
                "factions_definition": {
                    "empire": {"name_i18n": {"en": "The Empire", "ru": "Империя"}, "description_i18n": {"en": "A lawful empire.", "ru": "Законная империя."}},
                    "rebels": {"name_i18n": {"en": "Rebel Alliance", "ru": "Альянс Повстанцев"}, "description_i18n": {"en": "Freedom fighters.", "ru": "Борцы за свободу."}}
                },
                "faction_rules": { # For fallback in get_faction_data_context
                    "valid_faction_ids": ["empire", "rebels", "neutral_guild"]
                },
                "quest_rules": {
                    "reward_rules": {
                        "xp_reward_range": {"min": 50, "max": 1000}
                    }
                },
                "item_rules": {
                    "price_ranges_by_type": {
                        "weapon": {
                            "common": {"min": 10, "max": 100},
                            "rare": {"min": 101, "max": 500}
                        },
                        "potion": {
                            "common": {"min": 5, "max": 25}
                        }
                    }
                },
                "xp_rules": {
                    "level_difference_modifier": {
                        "-2": 0.5, "0": 1.0, "+2": 1.5
                    }
                },
                # Other rules as needed by get_game_rules_summary etc.
            },
            "item_templates": { # For get_game_rules_summary
                "sword_common": {"type": "weapon", "name_i18n": {"en": "Common Sword", "ru": "Обычный меч"}},
                "health_potion_sml": {"type": "potion", "name_i18n": {"en": "Small Health Potion", "ru": "Малое зелье здоровья"}}
            },
            # TimeManager mock instance will be placed here
        }

        self.mock_character_manager = MagicMock()
        self.mock_npc_manager = MagicMock()
        self.mock_quest_manager = MagicMock()
        self.mock_relationship_manager = MagicMock()
        self.mock_item_manager = MagicMock()
        self.mock_location_manager = MagicMock()
        self.mock_ability_manager = MagicMock()
        self.mock_spell_manager = MagicMock()
        self.mock_event_manager = MagicMock()
        self.mock_db_service = MagicMock() # Added mock for DBService

        # Mock for TimeManager accessed via settings
        self.mock_time_manager_instance = MockTimeManager()
        self.mock_settings["time_manager"] = self.mock_time_manager_instance

        self.collector = PromptContextCollector(
            settings=self.mock_settings,
            db_service=self.mock_db_service, # Added db_service
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            quest_manager=self.mock_quest_manager,
            relationship_manager=self.mock_relationship_manager,
            item_manager=self.mock_item_manager,
            location_manager=self.mock_location_manager,
            ability_manager=self.mock_ability_manager,
            spell_manager=self.mock_spell_manager,
            event_manager=self.mock_event_manager
            # Assuming game_manager is optional and can be None for these tests
        )
        self.guild_id = "test_guild"
        self.character_id = "char_test_id"
        self.main_lang = self.mock_settings["main_language_code"]


    def test_get_main_language_code(self):
        self.assertEqual(self.collector.get_main_language_code(), "en")

        # Test default
        original_settings = self.collector.settings
        self.collector.settings = {} # Temporarily remove settings
        self.assertEqual(self.collector.get_main_language_code(), "ru")
        self.collector.settings = original_settings # Restore

    # Example test for one method (get_faction_data_context)
    def test_get_faction_data_context(self):
        game_rules_data_mock = self.mock_settings["game_rules"]
        # Test with detailed definitions
        faction_data = self.collector.get_faction_data_context(self.guild_id, game_rules_data=game_rules_data_mock)
        self.assertEqual(len(faction_data), 2)
        self.assertIn("empire", [f["id"] for f in faction_data])
        self.assertEqual(faction_data[0]["name_i18n"]["en"], "The Empire")

        # Test fallback to faction_rules
        original_factions_def = game_rules_data_mock["factions_definition"]
        game_rules_data_mock["factions_definition"] = {} # Remove detailed defs
        faction_data_fallback = self.collector.get_faction_data_context(self.guild_id, game_rules_data=game_rules_data_mock)
        self.assertEqual(len(faction_data_fallback), 3)
        self.assertIn("neutral_guild", [f["id"] for f in faction_data_fallback])
        self.assertEqual(faction_data_fallback[2]["name_i18n"]["en"], "neutral_guild")
        game_rules_data_mock["factions_definition"] = original_factions_def # Restore

        # Test no data
        original_faction_rules = game_rules_data_mock["faction_rules"]
        game_rules_data_mock["factions_definition"] = {}
        game_rules_data_mock["faction_rules"] = {}
        faction_data_none = self.collector.get_faction_data_context(self.guild_id, game_rules_data=game_rules_data_mock)
        self.assertEqual(len(faction_data_none), 0)
        # Restore for other tests if game_rules_data_mock is self.mock_settings["game_rules"]
        game_rules_data_mock["factions_definition"] = original_factions_def
        game_rules_data_mock["faction_rules"] = original_faction_rules


    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_get_lore_context(self, mock_json_load, mock_file_open):
        # Test successful load
        mock_json_load.return_value = {"lore_entries": [{"id": "lore1", "text": "Ancient tale"}]}
        context = self.collector.get_lore_context()
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0]["id"], "lore1")
        mock_file_open.assert_called_once_with("game_data/lore_i18n.json", 'r', encoding='utf-8')

        # Test FileNotFoundError
        mock_file_open.side_effect = FileNotFoundError
        context_not_found = self.collector.get_lore_context()
        self.assertEqual(context_not_found, [])

        # Test JSONDecodeError
        mock_file_open.side_effect = None # Reset side effect
        mock_json_load.side_effect = json.JSONDecodeError("Error decoding", "doc", 0)
        context_decode_error = self.collector.get_lore_context()
        self.assertEqual(context_decode_error, [])

    # More tests will follow for other methods...

    def test_get_world_state_context(self):
        # Mock EventManager
        mock_event1 = MockEvent()
        mock_event1.id = "event001"
        mock_event1.name = "Festival of Dragons"
        mock_event1.current_stage_id = "stage2"
        mock_event1.template_id = "dragon_fest_template" # type
        mock_event1.is_active = True
        self.mock_event_manager.get_active_events.return_value = [mock_event1]

        # Mock LocationManager
        mock_loc_instance_data = {
            "loc001": { # This is a dict representing Location data as stored in _location_instances
                "id": "loc001",
                "name_i18n": {"en": "Destroyed Tower", "ru": "Разрушенная башня"},
                "state": {"is_destroyed": True, "is_quest_hub": False} # Location.state
            },
            "loc002": {
                "id": "loc002",
                "name_i18n": {"en": "Busy Market", "ru": "Оживленный рынок"},
                "state": {"is_under_attack": False, "is_quest_hub": True}
            }
        }
        # Mocking _location_instances directly as per collector's current implementation
        self.mock_location_manager._location_instances = {self.guild_id: mock_loc_instance_data}

        # Mock get_location_instance to return mock Location objects
        mock_loc1_obj = MockLocation()
        mock_loc1_obj.id = "loc001"
        mock_loc1_obj.name_i18n = {"en": "Destroyed Tower", "ru": "Разрушенная башня"}
        mock_loc1_obj.state = {"is_destroyed": True, "is_quest_hub": False}

        mock_loc2_obj = MockLocation()
        mock_loc2_obj.id = "loc002"
        mock_loc2_obj.name_i18n = {"en": "Busy Market", "ru": "Оживленный рынок"}
        mock_loc2_obj.state = {"is_under_attack": False, "is_quest_hub": True}

        def get_mock_location_instance(guild_id, loc_id):
            if loc_id == "loc001": return mock_loc1_obj
            if loc_id == "loc002": return mock_loc2_obj
            return None
        self.mock_location_manager.get_location_instance.side_effect = get_mock_location_instance


        # Mock NpcManager
        mock_npc1 = MockNpc()
        mock_npc1.id = "npc001"
        mock_npc1.name = "Injured Guard"
        mock_npc1.health = 20.0
        mock_npc1.max_health = 100.0
        mock_npc1.current_action = None
        mock_npc1.location_id = "loc001"

        mock_npc2 = MockNpc()
        mock_npc2.id = "npc002"
        mock_npc2.name = "Busy Merchant"
        mock_npc2.health = 80.0
        mock_npc2.max_health = 100.0
        mock_npc2.current_action = {"type": "selling_wares"} # Example action structure
        mock_npc2.location_id = "loc002"

        self.mock_npc_manager.get_all_npcs.return_value = [mock_npc1, mock_npc2]

        # Mock TimeManager
        self.mock_time_manager_instance.get_current_game_time.return_value = 90061.0 # 1 day, 1 hour, 1 minute, 1 second

        world_state = self.collector.get_world_state_context(self.guild_id)

        # Assertions for events
        self.assertEqual(len(world_state["active_global_events"]), 1)
        self.assertEqual(world_state["active_global_events"][0]["id"], "event001")
        self.assertEqual(world_state["active_global_events"][0]["type"], "dragon_fest_template")

        # Assertions for locations (only those with key statuses)
        self.assertEqual(len(world_state["key_location_statuses"]), 2) # Both have key flags
        found_loc_ids = [loc["id"] for loc in world_state["key_location_statuses"]]
        self.assertIn("loc001", found_loc_ids)
        self.assertIn("loc002", found_loc_ids)
        loc1_data = next(l for l in world_state["key_location_statuses"] if l["id"] == "loc001")
        self.assertIn("destroyed", loc1_data["status_flags"])

        # Assertions for NPCs (only significant ones)
        self.assertEqual(len(world_state["significant_npc_states"]), 2) # Both are significant (low health, active action)
        npc1_data = next(n for n in world_state["significant_npc_states"] if n["id"] == "npc001")
        self.assertIn("low_health", npc1_data["significance_reasons"])
        npc2_data = next(n for n in world_state["significant_npc_states"] if n["id"] == "npc002")
        self.assertIn("active_action", npc2_data["significance_reasons"])
        self.assertEqual(npc2_data["current_action_type"], "selling_wares")


        # Assertions for time
        self.assertEqual(world_state["current_time"]["game_time_string"], "Day 2, 01:01:01")

        # Test edge case: No active events, no key locations, no significant NPCs
        self.mock_event_manager.get_active_events.return_value = []
        self.mock_location_manager._location_instances = {self.guild_id: {
            "loc003": {"id": "loc003", "name_i18n": {"en": "Quiet Village"}, "state": {}}
        }}
        mock_loc3_obj = MockLocation()
        mock_loc3_obj.id = "loc003"
        mock_loc3_obj.name_i18n = {"en": "Quiet Village"}
        mock_loc3_obj.state = {}
        self.mock_location_manager.get_location_instance.side_effect = lambda g, l_id: mock_loc3_obj if l_id == "loc003" else None

        mock_npc3 = MockNpc()
        mock_npc3.id = "npc003"; mock_npc3.name = "Sleeping Villager"; mock_npc3.health = 100.0; mock_npc3.max_health = 100.0; mock_npc3.current_action = None
        self.mock_npc_manager.get_all_npcs.return_value = [mock_npc3]

        world_state_empty = self.collector.get_world_state_context(self.guild_id)
        self.assertEqual(len(world_state_empty["active_global_events"]), 0)
        self.assertEqual(len(world_state_empty["key_location_statuses"]), 0)
        self.assertEqual(len(world_state_empty["significant_npc_states"]), 0)

    def test_get_relationship_context(self):
        # Mock RelationshipManager
        mock_rel1 = MockRelationship()
        mock_rel1.to_dict.return_value = {
            "entity1_id": self.character_id, "entity1_type": "character",
            "entity2_id": "npc001", "entity2_type": "npc",
            "relationship_type": "friendly", "strength": 75.0,
            "details_i18n": {"en": "Good friends"}
        }
        mock_rel2 = MockRelationship()
        mock_rel2.to_dict.return_value = {
            "entity1_id": "npc002", "entity1_type": "npc",
            "entity2_id": self.character_id, "entity2_type": "character",
            "relationship_type": "hostile", "strength": -50.0,
            "details_i18n": {"en": "Arch enemies"}
        }
        self.mock_relationship_manager.get_relationships_for_entity.return_value = [mock_rel1, mock_rel2]

        context = self.collector.get_relationship_context(self.guild_id, self.character_id, "character")
        self.assertEqual(len(context), 2)
        self.assertEqual(context[0]["strength"], 75.0)
        self.assertEqual(context[1]["relationship_type"], "hostile")
        self.assertEqual(context[0]["details"], {"en": "Good friends"})

        # Test no relationships
        self.mock_relationship_manager.get_relationships_for_entity.return_value = []
        context_empty = self.collector.get_relationship_context(self.guild_id, self.character_id, "character")
        self.assertEqual(len(context_empty), 0)

        # Test manager unavailable (by temporarily removing it from collector)
        original_manager = self.collector.relationship_manager
        self.collector.relationship_manager = None
        context_no_manager = self.collector.get_relationship_context(self.guild_id, self.character_id, "character")
        self.assertEqual(len(context_no_manager), 0)
        self.collector.relationship_manager = original_manager # Restore

    def test_get_quest_context(self):
        # Mock QuestManager
        active_quest_dict1 = {
            "id": "q001", "name_i18n": {"en": "Slay the Dragon", "ru": "Убить дракона"}, "status": "active",
            "current_stage_id": "stage_1",
            "stages": {
                "stage_1": {"description_i18n": {"en": "Find the dragon's lair", "ru": "Найти логово дракона"}}
            }
        }
        self.mock_quest_manager.list_quests_for_character.return_value = [active_quest_dict1]

        # Mocking _completed_quests and _all_quests for completed quest summary
        completed_quest_id = "q000_completed"
        self.mock_quest_manager._completed_quests = {
            self.guild_id: {self.character_id: [completed_quest_id]}
        }

        mock_completed_quest_obj = MockQuest() # Assuming Quest objects are stored in _all_quests
        mock_completed_quest_obj.to_dict.return_value = {
            "id": completed_quest_id,
            "name_i18n": {"en": "Initial Training", "ru": "Начальная тренировка"},
            "status": "completed"
        }
        self.mock_quest_manager._all_quests = {
            self.guild_id: {completed_quest_id: mock_completed_quest_obj}
        }

        context = self.collector.get_quest_context(self.guild_id, self.character_id)

        self.assertEqual(len(context["active_quests"]), 1)
        self.assertEqual(context["active_quests"][0]["id"], "q001")
        self.assertEqual(context["active_quests"][0]["current_objectives_summary"], "Find the dragon's lair")

        self.assertEqual(len(context["completed_quests_summary"]), 1)
        self.assertEqual(context["completed_quests_summary"][0]["id"], completed_quest_id)
        self.assertEqual(context["completed_quests_summary"][0]["name_i18n"]["en"], "Initial Training")

        # Test no active/completed quests
        self.mock_quest_manager.list_quests_for_character.return_value = []
        self.mock_quest_manager._completed_quests = {self.guild_id: {self.character_id: []}}
        context_empty = self.collector.get_quest_context(self.guild_id, self.character_id)
        self.assertEqual(len(context_empty["active_quests"]), 0)
        self.assertEqual(len(context_empty["completed_quests_summary"]), 0)

        # Test QuestManager unavailable
        original_manager = self.collector.quest_manager
        self.collector.quest_manager = None
        context_no_manager = self.collector.get_quest_context(self.guild_id, self.character_id)
        self.assertEqual(len(context_no_manager["active_quests"]), 0)
        self.assertEqual(len(context_no_manager["completed_quests_summary"]), 0)
        self.collector.quest_manager = original_manager # Restore

    def test_get_game_rules_summary(self):
        # Settings already have game_rules for attributes, skills, and item_templates
        summary = self.collector.get_game_rules_summary(self.guild_id)

        # Attributes
        self.assertIn("strength", summary["attributes"])
        self.assertEqual(summary["attributes"]["strength"]["en"], "Physical power")

        # Skills
        self.assertIn("mining", summary["skills"])
        self.assertEqual(summary["skills"]["mining"]["associated_stat"], "strength") # Assuming this from default skill_stat_map
        self.assertEqual(summary["skills"]["mining"]["description_i18n"]["en"], "Ability to mine ores")

        # Abilities (expecting placeholder)
        self.assertIn("placeholder_ability_id_1", summary["abilities"])
        self.assertEqual(summary["abilities"]["placeholder_ability_id_1"]["name_i18n"]["en"], "Placeholder Ability 1")

        # Spells (expecting placeholder)
        self.assertIn("placeholder_spell_id_1", summary["spells"])
        self.assertEqual(summary["spells"]["placeholder_spell_id_1"]["name_i18n"]["en"], "Placeholder Spell 1")

        # Item Rules Summary
        self.assertIn("sword_common", summary["item_rules_summary"])
        self.assertEqual(summary["item_rules_summary"]["sword_common"]["type"], "weapon")
        self.assertIn("name_i18n", summary["item_rules_summary"]["sword_common"]["properties"])

    def test_get_player_level_context(self):
        # Character found, no party
        mock_char_solo = MockCharacter()
        mock_char_solo.level = 5
        mock_char_solo.current_party_id = None
        mock_char_solo.party_id = None # Old field
        self.mock_character_manager.get_character.return_value = mock_char_solo

        context_solo = self.collector.get_player_level_context(self.guild_id, self.character_id)
        self.assertEqual(context_solo["character_level"], 5)
        self.assertEqual(context_solo["party_average_level"], 5.0) # Defaults to char level

        # Character found, in a party
        mock_char_in_party = MockCharacter()
        mock_char_in_party.level = 7
        mock_char_in_party.current_party_id = "party001"

        mock_member1 = MockCharacter(); mock_member1.level = 7
        mock_member2 = MockCharacter(); mock_member2.level = 8
        mock_member3 = MockCharacter(); mock_member3.level = 6

        mock_party_obj = MockParty()
        mock_party_obj.player_ids_list = ["char_test_id", "member2_id", "member3_id"]

        def get_char_side_effect(guild_id, char_id):
            if char_id == self.character_id: return mock_char_in_party
            if char_id == "member2_id": return mock_member2
            if char_id == "member3_id": return mock_member3
            return None
        self.mock_character_manager.get_character.side_effect = get_char_side_effect
        self.mock_party_manager.get_party.return_value = mock_party_obj

        context_party = self.collector.get_player_level_context(self.guild_id, self.character_id)
        self.assertEqual(context_party["character_level"], 7)
        self.assertAlmostEqual(context_party["party_average_level"], (7 + 8 + 6) / 3.0, places=1)

        # Character not found
        self.mock_character_manager.get_character.side_effect = None # Clear previous side_effect
        self.mock_character_manager.get_character.return_value = None
        context_not_found = self.collector.get_player_level_context(self.guild_id, "unknown_char_id")
        self.assertEqual(context_not_found["character_level"], 1)
        self.assertEqual(context_not_found["party_average_level"], 1)

    def test_get_game_terms_dictionary(self):
        # Settings already provide stats and skills
        # Mock AbilityManager
        mock_ability1 = MockAbility()
        mock_ability1.name = "Power Strike" # Plain string name
        mock_ability1.description = "A powerful melee attack."
        self.mock_ability_manager._ability_templates = {self.guild_id: {"ab001": mock_ability1}}

        # Mock SpellManager
        mock_spell1 = MockSpell()
        mock_spell1.name = {"en": "Fireball", "ru": "Огненный шар"} # i18n dict name
        mock_spell1.description = {"en": "Hurls a fiery orb.", "ru": "Метает огненный шар."}
        self.mock_spell_manager._spell_templates = {self.guild_id: {"sp001": mock_spell1}}

        # Mock NpcManager (_npc_archetypes is global)
        self.mock_npc_manager._npc_archetypes = {
            "goblin_warrior": {"name": "Goblin Warrior", "backstory": "A common goblin fighter."} # name_i18n will be derived
        }

        # Mock ItemManager (_item_templates is global)
        self.mock_item_manager._item_templates = {
            "itm001": {"name_i18n": {"en": "Healing Potion", "ru": "Зелье лечения"}, "description_i18n": {"en": "Restores health.", "ru": "Восстанавливает здоровье."}}
        }

        # Mock LocationManager (_location_templates is global)
        self.mock_location_manager._location_templates = {
            "loc_template_001": {"name_i18n": {"en": "Old Forest", "ru": "Старый лес"}, "description_i18n": {"en": "A very old forest.", "ru": "Очень старый лес."}}
        }

        # Faction data is already mocked in settings for get_faction_data_context

        # Mock QuestManager
        self.mock_quest_manager._quest_templates = {
            self.guild_id: {
                "q_template_001": {"name_i18n": {"en": "The Grand Quest", "ru": "Великий Квест"}, "description_i18n": {"en": "An epic journey.", "ru": "Эпическое путешествие."}}
            }
        }
        game_rules_data_mock = self.mock_settings["game_rules"]
        # Mocking the return of get_all_ability_definitions_for_guild and get_all_spell_definitions_for_guild for the kwargs
        # These are now fetched within get_full_context, but get_game_terms_dictionary can be tested standalone.
        mock_abilities = [mock_ability1]
        mock_spells = [mock_spell1]


        terms = self.collector.get_game_terms_dictionary(
            self.guild_id,
            game_rules_data=game_rules_data_mock,
            _ability_definitions_for_terms=mock_abilities, # Pass mocked data for abilities
            _fetched_abilities=True,
            _spell_definitions_for_terms=mock_spells,     # Pass mocked data for spells
            _fetched_spells=True
        )

        # Check total number of terms (2 stats + 2 skills + 1 ability + 1 spell + 1 npc_arch + 1 item_tpl + 1 loc_tpl + 2 factions + 1 quest_tpl = 12)
        # This count was based on placeholder abilities/spells. Now it's based on actual mocked ones.
        # Stats (2) + Skills (2) + Abilities (1) + Spells (1) + NPC Archetypes (1) + Item Templates (1) + Location Templates (1) + Factions (2) + Quest Templates (1) = 12
        self.assertEqual(len(terms), 12) # Count should remain same if placeholders were 1 each

        term_types_collected = [t.term_type for t in terms]
        self.assertIn("stat", term_types_collected)
        self.assertIn("skill", term_types_collected)
        self.assertIn("ability", term_types_collected)
        self.assertIn("spell", term_types_collected)
        self.assertIn("npc_archetype", term_types_collected)
        self.assertIn("item_template", term_types_collected)
        self.assertIn("location_template", term_types_collected)
        self.assertIn("faction", term_types_collected)
        self.assertIn("quest_template", term_types_collected)

        # Spot check a few terms for correct i18n processing
        strength_term = next(t for t in terms if t.id == "strength")
        self.assertEqual(strength_term.name_i18n[self.main_lang], "Strength")

        ability_term = next(t for t in terms if t.id == "ab001") # Ability from plain string name
        self.assertEqual(ability_term.name_i18n[self.main_lang], "Power Strike")
        self.assertEqual(ability_term.description_i18n[self.main_lang], "A powerful melee attack.")

        spell_term = next(t for t in terms if t.id == "sp001") # Spell from i18n dict name
        self.assertEqual(spell_term.name_i18n[self.main_lang], "Fireball")

        npc_term = next(t for t in terms if t.id == "goblin_warrior")
        self.assertEqual(npc_term.name_i18n[self.main_lang], "Goblin Warrior")
        self.assertEqual(npc_term.description_i18n[self.main_lang], "A common goblin fighter.") # from backstory

        # Test _ensure_i18n_dict implicitly via a term with None description
        mock_stat_no_desc = {"name_i18n": {"en": "Vitality"}} # No description_i18n
        self.mock_settings["game_rules"]["character_stats_rules"]["attributes"]["vitality"] = mock_stat_no_desc
        terms_with_none_desc = self.collector.get_game_terms_dictionary(self.guild_id)
        vitality_term = next(t for t in terms_with_none_desc if t.id == "vitality")
        self.assertEqual(vitality_term.description_i18n[self.main_lang], "Описание отсутствует.") # Default desc in main_lang
        # cleanup
        del self.mock_settings["game_rules"]["character_stats_rules"]["attributes"]["vitality"]

    def test_get_scaling_parameters(self):
        # Settings already provide character_stats_rules.stat_ranges_by_role,
        # quest_rules.reward_rules.xp_reward_range, item_rules.price_ranges_by_type,
        # and xp_rules.level_difference_modifier
        game_rules_data_mock = self.mock_settings["game_rules"]
        params = self.collector.get_scaling_parameters(self.guild_id, game_rules_data=game_rules_data_mock)

        # Expected parameters:
        # Warrior stats: str_min, str_max, dex_min, dex_max (4)
        # Mage stats: int_min, int_max (2)
        # Quest XP: min, max (2)
        # Item prices: weapon_common_min/max, weapon_rare_min/max, potion_common_min/max (6)
        # XP modifiers: for diff -2, 0, +2 (3)
        # Total = 4 + 2 + 2 + 6 + 3 = 17
        self.assertEqual(len(params), 17)

        # Spot check some parameters
        param_names = [p.parameter_name for p in params]

        self.assertIn("npc_stat_strength_warrior_min", param_names)
        str_warrior_min = next(p for p in params if p.parameter_name == "npc_stat_strength_warrior_min")
        self.assertEqual(str_warrior_min.value, 10.0)
        self.assertEqual(str_warrior_min.context, "NPC Role: warrior, Stat: strength")

        self.assertIn("quest_xp_reward_max", param_names)
        quest_xp_max = next(p for p in params if p.parameter_name == "quest_xp_reward_max")
        self.assertEqual(quest_xp_max.value, 1000.0)

        self.assertIn("item_price_weapon_rare_max", param_names)
        item_price = next(p for p in params if p.parameter_name == "item_price_weapon_rare_max")
        self.assertEqual(item_price.value, 500.0)
        self.assertEqual(item_price.context, "Item Type: weapon, Rarity: rare")

        self.assertIn("xp_modifier_level_diff_plus2", param_names)
        xp_mod = next(p for p in params if p.parameter_name == "xp_modifier_level_diff_plus2")
        self.assertEqual(xp_mod.value, 1.5)

        # Test with missing sub-rules (e.g., no item_rules)
        original_item_rules = self.mock_settings["game_rules"]["item_rules"]
        del self.mock_settings["game_rules"]["item_rules"]
        params_no_item_rules = self.collector.get_scaling_parameters(self.guild_id)
        self.assertEqual(len(params_no_item_rules), 17 - 6) # 6 item price params should be missing
        self.mock_settings["game_rules"]["item_rules"] = original_item_rules # Restore

    async def test_get_full_context(self):
        # Mock all individual get_* methods of the collector
        self.collector.get_main_language_code = MagicMock(return_value="en")
        self.collector.settings["target_languages"] = ["en", "ru"] # Ensure this is set for the test

        mock_game_rules_summary = {"attributes": {"strength": {"en": "Might"}}}
        self.collector.get_game_rules_summary = MagicMock(return_value=mock_game_rules_summary)

        mock_lore_context = [{"id": "lore1", "text_en": "Ancient history"}]
        self.collector.get_lore_context = MagicMock(return_value=mock_lore_context)

        mock_world_state = {"current_time": {"game_time_string": "Day 1, 10:00:00"}}
        self.collector.get_world_state_context = MagicMock(return_value=mock_world_state)

        mock_game_terms = [{"id":"term1", "name_i18n":{"en":"Term 1"}, "term_type":"general"}] # Changed to dict
        self.collector.get_game_terms_dictionary = MagicMock(return_value=mock_game_terms)

        mock_scaling_params = [{"parameter_name":"xp_scale", "value":1.2, "context":"general"}] # Changed to dict
        self.collector.get_scaling_parameters = MagicMock(return_value=mock_scaling_params)

        mock_faction_data = [{"id": "faction1", "name_i18n": {"en": "The Nobles"}}]
        self.collector.get_faction_data_context = MagicMock(return_value=mock_faction_data)

        # For player-specific context
        # get_player_level_context was removed from PromptContextCollector.
        # This logic is now part of CharacterManager.get_character_details_context
        # which is called by get_full_context.
        mock_char_details_context_val = {
            "player_id": self.character_id, # Assuming this is expected by the test assertion structure
            "level_info": {"character_level": 10, "party_average_level": 9.5},
            # Add other fields that get_character_details_context might return
            # and that GenerationContext might expect under player_context
            "name_i18n": {"en": "Test Character"},
            "current_location_id": "loc_test"
        }
        self.mock_character_manager.get_character_details_context = AsyncMock(return_value=mock_char_details_context_val)


        mock_quest_context = {"active_quests": [{"id": "q1", "name_i18n": {"en": "Main Quest"}}]}
        self.collector.get_quest_context = MagicMock(return_value=mock_quest_context)

        mock_relationship_context = [{"entity1_id": self.character_id, "entity2_id": "npc001"}]
        self.collector.get_relationship_context = MagicMock(return_value=mock_relationship_context)

        request_type = "generate_npc_dialogue"
        request_params = {"npc_id": "npc001", "situation": "greeting"}

        # Test with target_entity_type="character"
        full_context_char = await self.collector.get_full_context(
            self.guild_id, request_type, request_params,
            target_entity_id=self.character_id, target_entity_type="character"
        )

        self.assertIsInstance(full_context_char, GenerationContext)
        self.assertEqual(full_context_char.guild_id, self.guild_id)
        self.assertEqual(full_context_char.main_language, "en")
        self.assertEqual(full_context_char.target_languages, ["en", "ru"])
        self.assertEqual(full_context_char.request_type, request_type)
        self.assertEqual(full_context_char.request_params, request_params)
        self.assertEqual(full_context_char.game_rules_summary, mock_game_rules_summary)
        # For Pydantic v1, direct list comparison works. For v2, might need to compare dicts if model_dump is used.
        self.assertEqual(full_context_char.lore_snippets, mock_lore_context) # lore_snippets is the key in GenerationContext
        self.assertEqual(full_context_char.world_state, mock_world_state)
        self.assertEqual(full_context_char.game_terms_dictionary, mock_game_terms)
        self.assertEqual(full_context_char.scaling_parameters, mock_scaling_params)
        self.assertEqual(full_context_char.faction_data, mock_faction_data)

        self.assertIsNotNone(full_context_char.player_context)
        self.assertEqual(full_context_char.player_context["player_id"], self.character_id)
        self.assertEqual(full_context_char.player_context["level_info"], mock_char_details_context_val["level_info"])
        self.assertEqual(full_context_char.active_quests_summary, mock_quest_context["active_quests"])
        self.assertEqual(full_context_char.relationship_data, mock_relationship_context)

        # Test with no target entity
        full_context_no_target = await self.collector.get_full_context(
            self.guild_id, "generate_world_event", {}
        )
        self.assertIsNone(full_context_no_target.player_context)
        self.assertEqual(full_context_no_target.active_quests_summary, [])
        self.assertEqual(full_context_no_target.relationship_data, [])

        # Test with target_entity_type="npc"
        npc_id_target = "npc_target_001"
        mock_npc_relationship_context = [{"entity1_id": npc_id_target, "entity2_id": "char002", "type": "neutral", "strength": 0}]
        self.mock_relationship_manager.get_relationships_for_entity = AsyncMock(return_value=[MagicMock(to_dict=lambda: r) for r in mock_npc_relationship_context]) # Mock to return list of dicts

        full_context_npc = await self.collector.get_full_context(
            self.guild_id, "generate_npc_interaction", {},
            target_entity_id=npc_id_target, target_entity_type="npc"
        )
        self.assertIsNone(full_context_npc.player_context)
        # Relationship data should be fetched for the NPC
        self.mock_relationship_manager.get_relationships_for_entity.assert_awaited_with(self.guild_id, npc_id_target)
        # Compare the actual data, not just list equality if objects are involved
        self.assertEqual(len(full_context_npc.relationship_data), len(mock_npc_relationship_context))
        if full_context_npc.relationship_data: # Ensure it's not empty before indexing
            self.assertEqual(full_context_npc.relationship_data[0]["entity1_id"], mock_npc_relationship_context[0]["entity1_id"])


        # Test with party_id in request_params
        party_id_param = "party_test_001"
        mock_party_obj = MagicMock() # Simulate a Party DB model or Pydantic model
        mock_party_obj.id = party_id_param
        mock_party_obj.name_i18n = {"en": "The Testers"}
        mock_party_obj.player_ids_list = [self.character_id, "char_member_2"] # Old field, should be player_ids_json
        mock_party_obj.player_ids_json = json.dumps([self.character_id, "char_member_2"])


        mock_char1_for_party = MagicMock()
        mock_char1_for_party.id = self.character_id; mock_char1_for_party.name_i18n = {"en": "Char1"}; mock_char1_for_party.level = 5
        mock_char2_for_party = MagicMock()
        mock_char2_for_party.id = "char_member_2"; mock_char2_for_party.name_i18n = {"en": "Char2"}; mock_char2_for_party.level = 7

        self.mock_party_manager.get_party = AsyncMock(return_value=mock_party_obj)

        async def get_char_for_party_side_effect(guild_id, char_id_val):
            if char_id_val == self.character_id: return mock_char1_for_party
            if char_id_val == "char_member_2": return mock_char2_for_party
            return None
        self.mock_character_manager.get_character = AsyncMock(side_effect=get_char_for_party_side_effect)

        full_context_with_party = await self.collector.get_full_context(
            guild_id=self.guild_id,
            request_type="party_action",
            request_params={"party_id": party_id_param, "location_id": "loc_party_test"}, # Added location_id
            target_entity_id=party_id_param, # Target can be the party itself
            target_entity_type="party"
            # session=self.mock_db_session
        )
        self.assertIsNotNone(full_context_with_party.party_context)
        self.assertEqual(full_context_with_party.party_context["party_id"], party_id_param)
        self.assertEqual(len(full_context_with_party.party_context["member_details"]), 2)
        self.assertAlmostEqual(full_context_with_party.party_context["average_level"], 6.0)
        self.mock_party_manager.get_party.assert_awaited_with(self.guild_id, party_id_param)


    def test_get_player_level_context(self):
        # This test is for a method that was removed.
        # If the logic was integrated elsewhere (e.g., get_character_details_context),
        # that new place should be tested.
        # For now, this test can be removed or adapted if get_player_level_context is reinstated.
        pass # Test removed as method is removed


if __name__ == '__main__':
    unittest.main()
