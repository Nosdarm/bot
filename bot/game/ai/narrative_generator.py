from typing import Dict, Any, Optional, Tuple

# Assuming OpenAIService and MultilingualPromptGenerator are importable
# from bot.services.openai_service import OpenAIService
# from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator

# Placeholder for actual imports if not available in subtask environment
OpenAIService = Any
MultilingualPromptGenerator = Any

class AINarrativeGenerator:
    def __init__(self, openai_service: OpenAIService, prompt_generator: MultilingualPromptGenerator):
        """
        Initializes the AINarrativeGenerator.

        Args:
            openai_service: An instance of the OpenAIService for LLM calls.
            prompt_generator: An instance of MultilingualPromptGenerator for creating prompts.
        """
        self.openai_service = openai_service
        self.prompt_generator = prompt_generator

    async def generate_narrative_for_event(
        self,
        event_data: Dict[str, Any],
        guild_context: Dict[str, Any],
        lang: str
    ) -> str:
        """
        Generates a narrative for a game event using an LLM.

        Args:
            event_data: A dictionary containing details about the event. Expected keys:
                - 'event_type': (str) The type of the event (e.g., "PLAYER_MOVE", "ITEM_DROP").
                - 'source_name': (str) Name of the entity that caused the event.
                - 'target_name': (Optional[str]) Name of the entity affected by the event.
                - 'key_details_str': (str) A string summarizing other key details of the event.
                                     (e.g., "item 'Sword of Flames' to location 'Dragon's Lair'")
            guild_context: A dictionary containing context about the guild/world. Expected keys:
                - 'world_setting': (str) Brief description of the game world (e.g., "Dark Fantasy").
                - 'tone': (str) Desired narrative tone (e.g., "Gritty", "Epic", "Humorous").
            lang: The desired language code for the narrative (e.g., "en", "ru").

        Returns:
            A string containing the AI-generated narrative, or an error message string.
        """
        if not self.openai_service or not self.prompt_generator:
            return "Error: AI services not configured for narrative generation."

        event_type = event_data.get("event_type", "UNKNOWN_EVENT")
        source_name = event_data.get("source_name", "Someone")
        target_name = event_data.get("target_name") # Can be None
        key_details_str = event_data.get("key_details_str", "something happened.")

        world_setting = guild_context.get("world_setting", "generic fantasy setting")
        tone = guild_context.get("tone", "neutral")

        try:
            system_prompt, user_prompt = self.prompt_generator.generate_narrative_prompt(
                event_type=event_type,
                source_name=source_name,
                target_name=target_name,
                key_details_str=key_details_str,
                guild_setting=world_setting,
                tone=tone,
                lang=lang
            )

            # Assuming generate_master_response is the correct method in OpenAIService
            # Max tokens might need adjustment based on desired narrative length
            narrative = await self.openai_service.generate_master_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=150 # Adjust as needed
            )

            if not narrative:
                return f"AI service returned an empty narrative for event: {event_type}."

            return narrative

        except AttributeError as e:
            # This might happen if prompt_generator doesn't have generate_narrative_prompt yet
            print(f"Error: Missing method in prompt generator: {e}")
            return f"Error: Narrative prompt generation failed. Method missing. Details: {e}"
        except Exception as e:
            print(f"Error during AI narrative generation for event {event_type}: {e}")
            # traceback.print_exc() # For more detailed server-side logging
            return f"Error: AI narrative generation failed. Details: {e}"
