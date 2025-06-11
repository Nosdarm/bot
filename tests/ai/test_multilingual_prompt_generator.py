import unittest
from unittest.mock import MagicMock, patch
import json

from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
from bot.ai.ai_data_models import GenerationContext, GameTerm, ScalingParameter

class TestMultilingualPromptGenerator(unittest.TestCase):

    def setUp(self):
        self.mock_context_collector = MagicMock()

        self.sample_game_terms = [
            GameTerm(id="str", name_i18n={"en": "Strength", "ru": "Сила"}, term_type="stat"),
            GameTerm(id="item_hp_potion", name_i18n={"en": "Health Potion", "ru": "Зелье здоровья"}, term_type="item_template")
        ]
        self.sample_scaling_params = [
            ScalingParameter(parameter_name="npc_health_scale", value=1.2, context="for elite NPCs")
        ]
        self.sample_generation_context = GenerationContext(
            guild_id="test_guild",
            main_language="en",
            target_languages=["en", "ru"],
            request_type="test_request",
            request_params={"param1": "value1"},
            world_state={"time_of_day": "night"},
            faction_data=[{"id": "f1", "name_i18n": {"en": "Faction1"}}],
            relationship_data=[{"entity1_id": "p1", "entity2_id": "npc1", "type": "friendly"}],
            active_quests_summary=[{"id": "q1", "name_i18n": {"en": "Active Quest 1"}}],
            game_lore_snippets=[{"id": "lore1", "text_en": "Ancient lore"}],
            game_terms_dictionary=self.sample_game_terms,
            scaling_parameters=self.sample_scaling_params,
            game_rules_summary={"max_level": 50},
            player_context={"player_id": "player1", "level_info": {"character_level": 5}}
        )

        self.mock_context_collector.get_full_context.return_value = self.sample_generation_context

        self.prompt_generator = MultilingualPromptGenerator(
            context_collector=self.mock_context_collector,
            # settings are not directly used by MultilingualPromptGenerator itself,
            # but by PromptContextCollector, which is mocked.
            # So, an empty dict or None should be fine here if settings are not directly accessed.
            settings={}
        )

    def test_get_base_system_prompt(self):
        # Test with standard languages
        prompt_en_ru = self.prompt_generator._get_base_system_prompt(["en", "ru"])
        self.assertIn("You are a game content generation assistant.", prompt_en_ru)
        self.assertIn("Generate content in JSON format", prompt_en_ru)
        self.assertIn("All user-facing text MUST be provided in a multilingual JSON object format", prompt_en_ru)
        self.assertIn('"en": "English text example"', prompt_en_ru)
        self.assertIn('"ru": "Пример текста на русском"', prompt_en_ru)
        self.assertNotIn('"de":', prompt_en_ru)

        # Test with different set of languages
        prompt_de_fr = self.prompt_generator._get_base_system_prompt(["de", "fr", "es"])
        self.assertIn('"de": "Beispieltext auf Deutsch"', prompt_de_fr)
        self.assertIn('"fr": "Exemple de texte en français"', prompt_de_fr)
        self.assertIn('"es": "Ejemplo de texto en español"', prompt_de_fr)
        self.assertNotIn('"en":', prompt_de_fr) # Check that it adapts

        # Test with only one language
        prompt_en = self.prompt_generator._get_base_system_prompt(["en"])
        self.assertIn('"en": "English text example"', prompt_en)
        self.assertNotIn('"ru":', prompt_en)

        # Test with empty list (should ideally default or handle gracefully)
        # The current implementation will produce a generic message without specific lang examples if list is empty
        prompt_empty_langs = self.prompt_generator._get_base_system_prompt([])
        self.assertIn("multilingual JSON object format like:", prompt_empty_langs)
        self.assertNotIn('"en":', prompt_empty_langs) # No specific examples if no langs provided

    def test_build_full_prompt_for_openai(self):
        specific_task = "Design a unique sword."
        # get_full_context is already mocked in setUp to return self.sample_generation_context

        full_prompt = self.prompt_generator._build_full_prompt_for_openai(
            specific_task_prompt=specific_task,
            context_data=self.sample_generation_context # Pass the context data directly
        )

        self.assertIn("system", full_prompt)
        self.assertIn("user", full_prompt)

        # System prompt check (basic)
        self.assertIn("You are a game content generation assistant.", full_prompt["system"])
        self.assertIn('"en": "English text example"', full_prompt["system"]) # From sample_generation_context.target_languages

        # User prompt check
        self.assertIn("<game_context>", full_prompt["user"])
        self.assertIn("</game_context>", full_prompt["user"])
        self.assertIn("<task>", full_prompt["user"])
        self.assertIn("</task>", full_prompt["user"])
        self.assertIn(specific_task, full_prompt["user"])

        # Check if GenerationContext JSON is embedded
        # Pydantic v1 uses .json(), v2 uses .model_dump_json()
        if hasattr(self.sample_generation_context, 'model_dump_json'):
            expected_context_json = self.sample_generation_context.model_dump_json(indent=2)
        else:
            expected_context_json = self.sample_generation_context.json(indent=2) # type: ignore

        self.assertIn(expected_context_json, full_prompt["user"])

    @patch('bot.ai.ai_data_models.GenerationContext.json') # For Pydantic v1
    @patch('bot.ai.ai_data_models.GenerationContext.model_dump_json') # For Pydantic v2
    def test_build_full_prompt_for_openai_serialization_error(self, mock_model_dump_json, mock_json):
        # Configure both mocks to raise an exception
        mock_model_dump_json.side_effect = TypeError("Serialization error")
        mock_json.side_effect = TypeError("Serialization error")

        specific_task = "Design a problematic item."

        # Use a fresh GenerationContext instance for this test if the mock affects the global one
        # or ensure the mock is configured per-call if get_full_context was called inside _build_full_prompt_for_openai
        # (it's not, context_data is passed in)

        full_prompt = self.prompt_generator._build_full_prompt_for_openai(
            specific_task_prompt=specific_task,
            context_data=self.sample_generation_context # This context will fail to serialize due to mocks
        )

        self.assertIn("user", full_prompt)
        self.assertIn("<game_context>", full_prompt["user"])
        self.assertIn("Error serializing GenerationContext", full_prompt["user"])
        self.assertIn("TypeError: Serialization error", full_prompt["user"])
        self.assertIn("</game_context>", full_prompt["user"])

    async def _test_specific_generator(self, generator_method_name, request_params, expected_keywords, expected_fields):
        """Helper to test specific prompt generator methods."""
        # Configure get_full_context to be called by the generator method
        # The mock_context_collector is already set up to return self.sample_generation_context
        # We might want to customize the context per test if needed, by re-patching the return_value

        generator_method = getattr(self.prompt_generator, generator_method_name)

        # If the generator method itself calls get_full_context:
        # self.mock_context_collector.get_full_context.reset_mock() # Reset if called multiple times
        # result_prompts = await generator_method(guild_id="test_guild", **request_params)

        # Current structure: specific generators build a task string and call _build_full_prompt_for_openai
        # which takes context_data as an argument. The specific generators get this context_data
        # by calling self.context_collector.get_full_context.

        result_prompts = await generator_method(guild_id="test_guild", **request_params)

        self.assertIn("system", result_prompts)
        self.assertIn("user", result_prompts)

        user_prompt = result_prompts["user"]
        # Check for general instructions
        self.assertIn("Use the <game_context> data extensively", user_prompt)
        self.assertIn("game_terms_dictionary", user_prompt)
        self.assertIn("scaling_parameters", user_prompt)
        self.assertIn("multilingual JSON object format", user_prompt) # This is in system prompt, but task can reiterate

        for keyword in expected_keywords:
            self.assertIn(keyword, user_prompt)

        for field in expected_fields:
            self.assertIn(field, user_prompt) # Check if field names are mentioned in the task

    async def test_generate_npc_profile_prompt(self):
        await self._test_specific_generator(
            "generate_npc_profile_prompt",
            {"npc_id_idea": "strong_warrior_npc", "player_level_override": 10},
            expected_keywords=["NPC profile", "archetype", "backstory", "stats based on scaling parameters"],
            expected_fields=["name_i18n", "description_i18n", "archetype", "level", "stats", "skills", "inventory", "faction_affiliations", "visual_description_i18n"]
        )

    async def test_generate_quest_prompt(self):
        await self._test_specific_generator(
            "generate_quest_prompt",
            {"quest_idea": "a lost artifact retrieval", "triggering_entity_id": "player1"},
            expected_keywords=["quest design", "objectives", "rewards", "suggested_level according to scaling"],
            expected_fields=["title_i18n", "description_i18n", "suggested_level", "stages", "rewards_i18n", "quest_giver_id"]
        )

    async def test_generate_item_description_prompt(self):
        item_properties_example = {"material": "steel", "damage_type": "slashing"}
        await self._test_specific_generator(
            "generate_item_description_prompt",
            {"item_name": "Sword of Flames", "item_type": "weapon", "rarity": "rare", "properties": item_properties_example},
            expected_keywords=["item description", "game world lore", "visual details", "functional properties"],
            expected_fields=["description_i18n", "flavor_text_i18n"] # The method primarily generates descriptions
        )

    async def test_generate_location_description_prompt(self):
        entities_present = ["npc_merchant", "player_hero"]
        await self._test_specific_generator(
            "generate_location_description_prompt",
            {"location_name": "Old Mill", "location_type": "building", "atmosphere": "eerie", "entities_present_ids": entities_present},
            expected_keywords=["location description", "sensory details", "points of interest", "atmosphere"],
            expected_fields=["description_i18n", "interactive_elements_i18n"] # Example fields expected for location
        )

if __name__ == '__main__':
    unittest.main()
