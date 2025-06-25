import unittest
from unittest.mock import MagicMock, patch
import json

from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
from bot.ai.ai_data_models import GenerationContext # ScalingParameter removed

class TestMultilingualPromptGenerator(unittest.TestCase):

    def setUp(self):
        self.mock_context_collector = MagicMock()

        # GameTerm is removed, using a list of dicts for game_terms_dictionary
        self.sample_game_terms_data = [
            {"id": "str", "name_i18n": {"en": "Strength", "ru": "Сила"}, "term_type": "stat"},
            {"id": "item_hp_potion", "name_i18n": {"en": "Health Potion", "ru": "Зелье здоровья"}, "term_type": "item_template"}
        ]
        # ScalingParameter is removed, using a list of dicts for scaling_parameters
        self.sample_scaling_params_data = [
            {"parameter_name": "npc_health_scale", "value": 1.2, "context": "for elite NPCs"}
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
            lore_snippets=[{"id": "lore1", "text_en": "Ancient lore", "relevance_score": 0.8}], # Added lore_snippets
            game_terms_dictionary=self.sample_game_terms_data,
            scaling_parameters=self.sample_scaling_params_data, # Use the list of dicts
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
        # For specific generators, they now directly call self.context_collector.get_full_context
        # So, we'll mock that call within each test.

        self.mock_context_collector.get_full_context.reset_mock() # Reset before each specific generator test
        # The mock_context_collector.get_full_context is already set up to return self.sample_generation_context
        # We can override this per test if a different GenerationContext is needed for a specific prompt type.

        generator_method = getattr(self.prompt_generator, generator_method_name)

        # The specific generator methods (e.g., generate_npc_profile_prompt) now internally call
        # self.context_collector.get_full_context and then self._build_full_prompt_for_openai.
        # The request_params passed to _test_specific_generator are part of what's passed to get_full_context.

        # Example: generate_npc_profile_prompt takes GenerationContext as input
        # We need to ensure that the GenerationContext passed to it (or used by it) is correct.
        # The refactored specific generators (e.g., generate_npc_profile_prompt) now take GenerationContext directly.
        # The `await generator_method(guild_id="test_guild", **request_params)` pattern is for the old `prepare_ai_prompt` style.

        # For the new structure, we pass GenerationContext to the specific generators.
        # The test for these generators should verify the task_prompt string they create,
        # and then separately test _build_full_prompt_for_openai.
        # However, the prompt in the problem asks to test `prepare_ai_prompt` and ensure context is correct.
        # The specific `generate_..._prompt` methods in the provided code *do* call `_build_full_prompt_for_openai`
        # and take `GenerationContext` as an argument.
        # It seems `prepare_ai_prompt` is the more generic one to test for context collection.

        # Let's assume _test_specific_generator is testing the output of methods like `generate_npc_profile_prompt(self, generation_context: GenerationContext)`
        # So, `request_params` here are actually used to form the `generation_context` that is passed.
        # For these tests, we'll use the self.sample_generation_context and modify its request_params if needed.

        current_test_context = self.sample_generation_context.model_copy(deep=True) # Use model_copy for Pydantic v2
        current_test_context.request_params = request_params

        result_prompts = generator_method(generation_context=current_test_context) # Pass the context

        # Assert that get_full_context was NOT called directly by these specific generators anymore,
        # as they now receive GenerationContext as an argument.
        # This assertion is tricky if the helper _test_specific_generator is too generic.
        # The main thing is that the `user_prompt` part of `result_prompts` is correct.

        self.assertIn("system", result_prompts)
        self.assertIn("user", result_prompts)
        user_prompt = result_prompts["user"]

        # Check that the specific task prompt part is correct
        for keyword in expected_keywords:
            self.assertIn(keyword, user_prompt)
        for field in expected_fields:
            self.assertIn(field, user_prompt)

        # Check that the <game_context> was embedded
        self.assertIn("<game_context>", user_prompt)
        # Pydantic v1 uses .json(), v2 uses .model_dump_json()
        if hasattr(current_test_context, 'model_dump_json'):
            expected_context_json = current_test_context.model_dump_json(indent=2, exclude_none=True)
        else:
            expected_context_json = current_test_context.json(indent=2, exclude_none=True) # type: ignore
        self.assertIn(expected_context_json, user_prompt)


    async def test_generate_npc_profile_prompt(self):
        # This method now takes GenerationContext. We use self.sample_generation_context.
        # The request_params for NPC idea would be part of this context.
        context = self.sample_generation_context.model_copy(deep=True)
        context.request_params = {"npc_id_idea": "strong_warrior_npc"}
        # The target_languages for the prompt are derived from context.target_languages

        # No await needed as it's not an async method anymore
        prompts = self.prompt_generator.generate_npc_profile_prompt(context)

        self.assertIn("NPC Identifier/Concept: strong_warrior_npc", prompts["user"])
        self.assertIn("`name_i18n`: {\"en\": \"...\", \"ru\": \"...\"}", prompts["user"]) # Check lang example
        self.assertIn("`stats`: A dictionary", prompts["user"])


    async def test_generate_quest_prompt(self):
        context = self.sample_generation_context.model_copy(deep=True)
        context.request_params = {"quest_idea": "a lost artifact retrieval"}
        prompts = self.prompt_generator.generate_quest_prompt(context)
        self.assertIn("Quest Idea/Trigger: a lost artifact retrieval", prompts["user"])
        self.assertIn("`name_i18n`: {\"en\": \"...\", \"ru\": \"...\"}", prompts["user"])
        self.assertIn("`steps`: An array of step objects", prompts["user"])
        self.assertIn("`required_mechanics_json`: string", prompts["user"])

    async def test_generate_item_description_prompt(self):
        context = self.sample_generation_context.model_copy(deep=True)
        context.request_params = {"item_idea": "Sword of Flames"}
        prompts = self.prompt_generator.generate_item_description_prompt(context)
        self.assertIn("Item Idea/Keywords: Sword of Flames", prompts["user"])
        self.assertIn("`name_i18n`: {\"en\": \"...\", \"ru\": \"...\"}", prompts["user"])
        self.assertIn("`item_type`: string", prompts["user"])
        self.assertIn("`base_price`", prompts["user"]) # Check for base_price mention

    async def test_generate_location_description_prompt(self):
        context = self.sample_generation_context.model_copy(deep=True)
        context.request_params = {"location_idea": "Old Mill"}
        prompts = self.prompt_generator.generate_location_description_prompt(context)
        self.assertIn("Location Idea/Current Location ID (if updating): Old Mill", prompts["user"])
        self.assertIn("`name_i18n`: {\"en\": \"...\", \"ru\": \"...\"}", prompts["user"])
        self.assertIn("`atmospheric_description_i18n`", prompts["user"])
        self.assertIn("`points_of_interest`", prompts["user"])

    async def test_prepare_ai_prompt_generic(self):
        """ Test the generic prepare_ai_prompt method. """
        guild_id = "test_guild"
        location_id = "loc1"
        specific_task = "Describe the weather."
        player_id = "player1"

        # get_full_context is already mocked in setUp to return self.sample_generation_context
        # We need to ensure it's called with the correct parameters by prepare_ai_prompt.
        self.mock_context_collector.get_full_context.reset_mock() # Reset from setUp

        user_prompt_str = await self.prompt_generator.prepare_ai_prompt(
            guild_id=guild_id,
            location_id=location_id,
            specific_task_instruction=specific_task,
            player_id=player_id,
            additional_request_params={"mood": "gloomy"}
        )

        self.mock_context_collector.get_full_context.assert_awaited_once()
        call_args = self.mock_context_collector.get_full_context.call_args

        self.assertEqual(call_args.kwargs['guild_id'], guild_id)
        self.assertEqual(call_args.kwargs['request_type'], "player_specific_task") # Since player_id is provided

        expected_request_params = {
            "location_id": location_id,
            "player_id": player_id,
            "mood": "gloomy", # from additional_request_params
            "event": { # Added by prepare_ai_prompt
                "type": "player_specific_task",
                "specific_task_instruction": specific_task,
                "player_id": player_id
            }
        }
        self.assertEqual(call_args.kwargs['request_params'], expected_request_params)
        self.assertEqual(call_args.kwargs['target_entity_id'], player_id)
        self.assertEqual(call_args.kwargs['target_entity_type'], "character")

        self.assertIn(specific_task, user_prompt_str)
        self.assertIn("<game_context>", user_prompt_str)
        # Pydantic v1 uses .json(), v2 uses .model_dump_json()
        if hasattr(self.sample_generation_context, 'model_dump_json'):
            expected_context_json = self.sample_generation_context.model_dump_json(indent=2, exclude_none=True)
        else:
            expected_context_json = self.sample_generation_context.json(indent=2, exclude_none=True) # type: ignore
        self.assertIn(expected_context_json, user_prompt_str)

if __name__ == '__main__':
    unittest.main()
