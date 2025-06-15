import unittest
from unittest.mock import MagicMock, AsyncMock, patch, ANY
import json
from typing import Optional, Dict, Any, List # Ensure these are imported for type hints


# Modules to test
from bot.game.ai.narrative_generator import AINarrativeGenerator
from bot.game.services.report_formatter import ReportFormatter, I18nUtilsWrapper

# Dependencies that will be mocked
# from bot.services.openai_service import OpenAIService # Mocked
# from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator # Mocked
# from bot.game.managers.character_manager import CharacterManager # Mocked
# from bot.game.managers.npc_manager import NpcManager # Mocked
# from bot.game.managers.item_manager import ItemManager # Mocked
# import bot.utils.i18n_utils # Mocked via wrapper

# --- Mock Models (Simplified) ---
# Used by ReportFormatter._get_entity_name
class MockEntity:
    def __init__(self, id, name, name_i18n=None, guild_id=None): # Added guild_id for completeness
        self.id = id
        self.name = name # Fallback if name_i18n not used as expected
        self.name_i18n = name_i18n if name_i18n else {"en": name, "ru": f"{name}_ru"}
        self.guild_id = guild_id


class TestAINarrativeGenerator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_openai_service = AsyncMock()
        self.mock_prompt_generator = MagicMock()
        self.narrative_generator = AINarrativeGenerator(
            openai_service=self.mock_openai_service,
            prompt_generator=self.mock_prompt_generator
        )

    async def test_generate_narrative_for_event_success(self):
        event_data = {
            "event_type": "ITEM_LOOT",
            "source_name": "Player1",
            "target_name": None,
            "key_details_str": "found a Rusty Dagger in a chest"
        }
        guild_context = {"world_setting": "High Fantasy", "tone": "Adventurous"}
        lang = "en"
        expected_system_prompt = "System prompt for en"
        expected_user_prompt = "User prompt for Item Loot"
        expected_narrative = "Player1 triumphantly discovered a Rusty Dagger within the dusty confines of an old chest!"

        self.mock_prompt_generator.generate_narrative_prompt.return_value = (expected_system_prompt, expected_user_prompt)
        self.mock_openai_service.generate_master_response.return_value = expected_narrative

        narrative = await self.narrative_generator.generate_narrative_for_event(event_data, guild_context, lang)

        self.mock_prompt_generator.generate_narrative_prompt.assert_called_once_with(
            event_type="ITEM_LOOT",
            source_name="Player1",
            target_name=None,
            key_details_str="found a Rusty Dagger in a chest",
            guild_setting="High Fantasy",
            tone="Adventurous",
            lang="en"
        )
        self.mock_openai_service.generate_master_response.assert_called_once_with(
            system_prompt=expected_system_prompt,
            user_prompt=expected_user_prompt,
            max_tokens=150
        )
        self.assertEqual(narrative, expected_narrative)

    async def test_generate_narrative_openai_fails(self):
        event_data = {"event_type": "TEST", "source_name": "S", "key_details_str": "D"}
        guild_context = {}
        lang = "en"
        self.mock_prompt_generator.generate_narrative_prompt.return_value = ("sys", "user")
        self.mock_openai_service.generate_master_response.return_value = ""

        narrative = await self.narrative_generator.generate_narrative_for_event(event_data, guild_context, lang)
        self.assertIn("empty narrative", narrative)

    async def test_generate_narrative_services_not_configured(self):
        generator = AINarrativeGenerator(None, None) # type: ignore
        narrative = await generator.generate_narrative_for_event({}, {}, "en")
        self.assertIn("Error: AI services not configured", narrative)


class TestReportFormatter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_char_mgr = AsyncMock()
        self.mock_npc_mgr = AsyncMock()
        self.mock_item_mgr = AsyncMock()

        self.mock_i18n_module = MagicMock()
        self.mock_i18n_module.get_localized_string.side_effect = lambda key, lang, **kwargs: f"i18n[{lang}]:{key}{kwargs if kwargs else ''}"
        # Add default_lang to the mock module itself, so I18nUtilsWrapper can access it
        self.mock_i18n_module.default_lang = "en"


        self.formatter = ReportFormatter(
            character_manager=self.mock_char_mgr,
            npc_manager=self.mock_npc_mgr,
            item_manager=self.mock_item_mgr,
            i18n_module=self.mock_i18n_module
        )
        # Also set the default_lang for the wrapper instance for consistency if module doesn't have it
        self.formatter.i18n.default_lang = "en"


    async def test_get_entity_name_player(self):
        # Assuming get_character method exists on CharacterManager
        self.mock_char_mgr.get_character.return_value = MockEntity(id="p1", name="Player One", name_i18n={"en": "Player One", "ru": "Игрок Один"})
        name = await self.formatter._get_entity_name("p1", "PLAYER", "ru", guild_id="g1")
        self.assertEqual(name, "Игрок Один")
        self.mock_char_mgr.get_character.assert_called_once_with("g1", "p1")

    async def test_get_entity_name_npc(self):
        self.mock_npc_mgr.get_npc.return_value = MockEntity(id="n1", name="Goblin", name_i18n={"en": "Goblin", "ru":"Гоблин"})
        name = await self.formatter._get_entity_name("n1", "NPC", "en", guild_id="g1")
        self.assertEqual(name, "Goblin")
        self.mock_npc_mgr.get_npc.assert_called_once_with("g1", "n1")


    async def test_format_story_log_entry_basic_i18n(self):
        log_entry = {
            "guild_id": "g1",
            "description_key": "event.player.move",
            "description_params_json": json.dumps({"location_name": "The Shire"}),
            "source_entity_id": "player1",
            "source_entity_type": "PLAYER",
            "details": json.dumps({})
        }
        self.mock_char_mgr.get_character.return_value = MockEntity(id="player1", name="Frodo")

        formatted_string = await self.formatter.format_story_log_entry(log_entry, "en")

        expected_i18n_call_params = {'location_name': 'The Shire', 'source_name': 'Frodo'}
        self.mock_i18n_module.get_localized_string.assert_called_with("event.player.move", "en", **expected_i18n_call_params)
        self.assertEqual(formatted_string, f"i18n[en]:event.player.move{expected_i18n_call_params}")

    async def test_format_story_log_entry_with_ai_narrative(self):
        log_entry = {
            "guild_id": "g1",
            "description_key": "event.item.pickup",
            "description_params_json": json.dumps({"item_name": "Ring"}),
            "source_entity_id": "player1",
            "source_entity_type": "PLAYER",
            "details": json.dumps({"ai_narrative_en": "A glint of gold caught his eye."})
        }
        self.mock_char_mgr.get_character.return_value = MockEntity(id="player1", name="Bilbo")

        formatted_string = await self.formatter.format_story_log_entry(log_entry, "en")

        expected_i18n_params = {'item_name': 'Ring', 'source_name': 'Bilbo'}
        self.assertEqual(formatted_string, f"i18n[en]:event.item.pickup{expected_i18n_params} A glint of gold caught his eye.")

    async def test_format_story_log_entry_with_ai_narrative_lang_fallback(self):
        log_entry = {
            "guild_id": "g1",
            "description_key": "event.item.pickup",
            "description_params_json": json.dumps({"item_name": "Ring"}),
            "source_entity_id": "player1",
            "source_entity_type": "PLAYER",
            "details": json.dumps({"ai_narrative_en": "English narrative."})
        }
        self.mock_char_mgr.get_character.return_value = MockEntity(id="player1", name="Bilbo")

        formatted_string = await self.formatter.format_story_log_entry(log_entry, "ru")

        expected_i18n_params = {'item_name': 'Ring', 'source_name': 'Bilbo'}
        # The mock i18n module has default_lang = "en"
        self.assertEqual(formatted_string, f"i18n[ru]:event.item.pickup{expected_i18n_params} English narrative.")


    async def test_generate_turn_report(self):
        log_entries = [
            {
                "guild_id": "g1", "description_key": "event.start",
                "description_params_json": json.dumps({}),
                "details": json.dumps({"ai_narrative_en": "The adventure begins."})
            },
            {
                "guild_id": "g1", "description_key": "event.end",
                "description_params_json": json.dumps({}),
                "details": json.dumps({"ai_narrative_en": "All is quiet."})
            }
        ]
        # Mock _get_entity_name to return simple IDs to avoid manager calls in this specific test
        # For generate_turn_report, we are testing the aggregation, not individual name resolution.
        async def mock_get_name(id_val, type_val, lang_val, guild_id_val): # Match expected signature
            return id_val if id_val else "Unknown"

        self.formatter._get_entity_name = AsyncMock(side_effect=mock_get_name)


        report = await self.formatter.generate_turn_report("g1", "en", log_entries)

        expected_line1 = f"i18n[en]:event.start{{}} The adventure begins."
        expected_line2 = f"i18n[en]:event.end{{}} All is quiet."
        self.assertIn(expected_line1, report)
        self.assertIn(expected_line2, report)
        self.assertEqual(report, f"{expected_line1}\n{expected_line2}")

    async def test_generate_turn_report_empty(self):
        report = await self.formatter.generate_turn_report("g1", "en", [])
        self.assertEqual(report, "i18n[en]:report.nothing_happened{}")

# Ensure these imports are at the top of tests/game/ai/test_narrative_and_reporting.py
# (some might be duplicates of what's already there for other test classes in the file)
# import unittest # Should already be there
# from unittest.mock import MagicMock, AsyncMock, patch, ANY # Should already be there
# import json # Should already be there

from bot.game.managers.game_log_manager import GameLogManager
# from bot.game.ai.narrative_generator import AINarrativeGenerator # Already imported
# from bot.game.services.report_formatter import ReportFormatter # Already imported
# from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator # Mocked
# from bot.services.openai_service import OpenAIService # Mocked
# from bot.services.db_service import DBService # Mocked for GameLogManager
# from bot.game.managers.character_manager import CharacterManager # Mocked for ReportFormatter
# from bot.game.managers.npc_manager import NpcManager # Mocked for ReportFormatter

# MockEntity should already be defined in this file if TestReportFormatter is present.
# If not, ensure it or a similar mock is available for Character/NPC objects.
# class MockEntity: ... (defined earlier)


class TestLoggingAndReportingIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild_id = "integration_test_guild"
        self.lang_en = "en"
        self.lang_ru = "ru"

        # --- Mock Dependant Services & Managers ---
        self.mock_db_adapter = AsyncMock() # Mock for the DB adapter (e.g., PostgresAdapter)
        self.mock_db_service = MagicMock() # Mock for DBService
        self.mock_db_service.adapter = self.mock_db_adapter

        self.mock_openai_service = AsyncMock()
        self.mock_prompt_generator = MagicMock()

        self.mock_char_mgr = AsyncMock()
        self.mock_npc_mgr = AsyncMock()
        self.mock_item_mgr = AsyncMock() # Though not directly used in this simple test's data

        # Mock i18n_utils module for ReportFormatter
        self.mock_i18n_module = MagicMock()
        self.mock_i18n_module.get_localized_string.side_effect = lambda key, lang, **kwargs: f"i18n[{lang}]:{key}{kwargs if kwargs else ''}"
        self.mock_i18n_module.default_lang = self.lang_en


        # --- Initialize Services Under Test ---
        # AINarrativeGenerator is already imported at the top level of this file
        self.narrative_generator = AINarrativeGenerator(
            openai_service=self.mock_openai_service,
            prompt_generator=self.mock_prompt_generator
        )

        self.game_log_manager = GameLogManager(
            db_service=self.mock_db_service,
            settings={ # Provide settings for narrative languages
                'guilds': {
                    self.guild_id: {
                        'narrative_langs': [self.lang_en, self.lang_ru],
                        'world_setting': 'Mythic Greece',
                        'narrative_tone': 'Epic'
                    }
                }
            },
            relationship_event_processor=None, # Not relevant for this test
            narrative_generator=self.narrative_generator # Inject real narrative_generator
        )

        # ReportFormatter is already imported at the top level of this file
        self.report_formatter = ReportFormatter(
            character_manager=self.mock_char_mgr,
            npc_manager=self.mock_npc_mgr,
            item_manager=self.mock_item_mgr,
            i18n_module=self.mock_i18n_module
        )

    async def test_log_event_with_narrative_and_format_it(self):
        # --- 1. Configure Mocks for this specific test ---
        event_type = "HEROIC_DEED"
        source_id = "player_achilles"
        source_name = "Achilles"
        target_id = "npc_hector"
        target_name = "Hector"
        description_key = "event.combat.victory"
        description_params = {"enemy_name": target_name, "loot_found": "Bronze Armor"}

        details_for_log = {
            "weapon_used": "Spear of Destiny",
            # source_name and target_name could be passed here if GameLogManager doesn't resolve them
        }

        # Mock entity fetching for ReportFormatter
        # Assuming MockEntity is defined globally in this test file
        self.mock_char_mgr.get_character_by_id.return_value = MockEntity(id=source_id, name=source_name)
        # For ReportFormatter._get_entity_name, it calls get_character (not get_character_by_id)
        self.mock_char_mgr.get_character.return_value = MockEntity(id=source_id, name=source_name)


        # For _get_entity_name, npc_manager.get_npc is called with guild_id.
        self.mock_npc_mgr.get_npc.return_value = MockEntity(id=target_id, name=target_name, guild_id=self.guild_id)


        # Mock prompt generation
        self.mock_prompt_generator.generate_narrative_prompt.side_effect = [
            ("system_en", "user_prompt_en_for_heroic_deed"), # For lang_en
            ("system_ru", "user_prompt_ru_for_heroic_deed")  # For lang_ru
        ]
        # Mock LLM response
        narrative_en = "Achilles, with a mighty roar, vanquished Hector, claiming the legendary Bronze Armor!"
        narrative_ru = "Ахиллес, с могучим рыком, одолел Гектора, забрав легендарные Бронзовые Доспехи!"
        self.mock_openai_service.generate_master_response.side_effect = [narrative_en, narrative_ru]

        # --- 2. Log the event using GameLogManager ---
        await self.game_log_manager.log_event(
            guild_id=self.guild_id,
            event_type=event_type,
            details=details_for_log.copy(), # Pass a copy as details might be modified
            player_id=source_id, # Assuming player is the source
            source_entity_id=source_id,
            source_entity_type="PLAYER",
            target_entity_id=target_id,
            target_entity_type="NPC",
            description_key=description_key,
            description_params=description_params.copy(),
            generate_narrative=True # Enable narrative generation
        )

        # --- 3. Verify GameLogManager's interaction with DB and NarrativeGenerator ---
        self.mock_db_adapter.execute.assert_called_once()
        _, sql_params_tuple = self.mock_db_adapter.execute.call_args[0]

        logged_details_json = sql_params_tuple[10]
        logged_details = json.loads(logged_details_json)

        self.assertEqual(self.mock_prompt_generator.generate_narrative_prompt.call_count, 2)
        self.mock_openai_service.generate_master_response.assert_any_call(system_prompt="system_en", user_prompt="user_prompt_en_for_heroic_deed", max_tokens=150)
        self.mock_openai_service.generate_master_response.assert_any_call(system_prompt="system_ru", user_prompt="user_prompt_ru_for_heroic_deed", max_tokens=150)

        self.assertIn("ai_narrative_en", logged_details)
        self.assertEqual(logged_details["ai_narrative_en"], narrative_en)
        self.assertIn("ai_narrative_ru", logged_details)
        self.assertEqual(logged_details["ai_narrative_ru"], narrative_ru)
        self.assertEqual(logged_details["weapon_used"], "Spear of Destiny")


        # --- 4. Format the logged event using ReportFormatter ---
        mock_log_entry_from_db = {
            "guild_id": self.guild_id,
            "event_type": event_type,
            "description_key": description_key,
            "description_params_json": json.dumps(description_params),
            "details": logged_details_json,
            "source_entity_id": source_id,
            "source_entity_type": "PLAYER",
            "target_entity_id": target_id,
            "target_entity_type": "NPC",
        }

        formatted_en = await self.report_formatter.format_story_log_entry(mock_log_entry_from_db, self.lang_en)

        expected_i18n_params_en = {'enemy_name': target_name, 'loot_found': 'Bronze Armor', 'source_name': source_name, 'target_name': target_name}
        expected_base_desc_en = f"i18n[{self.lang_en}]:{description_key}{expected_i18n_params_en}"
        self.assertEqual(formatted_en, f"{expected_base_desc_en} {narrative_en}")

        self.mock_char_mgr.get_character.assert_called_with(self.guild_id, source_id)
        self.mock_npc_mgr.get_npc.assert_called_with(guild_id=self.guild_id, npc_id=target_id)

        self.mock_char_mgr.get_character.reset_mock()
        self.mock_npc_mgr.get_npc.reset_mock()

        self.mock_char_mgr.get_character.return_value = MockEntity(id=source_id, name="Ахиллес", name_i18n={"ru": "Ахиллес", "en": "Achilles"})
        self.mock_npc_mgr.get_npc.return_value = MockEntity(id=target_id, name="Гектор", name_i18n={"ru": "Гектор", "en": "Hector"}, guild_id=self.guild_id)


        formatted_ru = await self.report_formatter.format_story_log_entry(mock_log_entry_from_db, self.lang_ru)
        expected_i18n_params_ru = {'enemy_name': 'Гектор', 'loot_found': 'Bronze Armor', 'source_name': 'Ахиллес', 'target_name': 'Гектор'}
        expected_base_desc_ru = f"i18n[{self.lang_ru}]:{description_key}{expected_i18n_params_ru}"
        self.assertEqual(formatted_ru, f"{expected_base_desc_ru} {narrative_ru}")

        self.mock_char_mgr.get_character.assert_called_with(self.guild_id, source_id)
        self.mock_npc_mgr.get_npc.assert_called_with(guild_id=self.guild_id, npc_id=target_id)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
