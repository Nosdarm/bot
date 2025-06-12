# bot/game/ai/event_ai_generator.py
from __future__ import annotations
import json
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.services.openai_service import OpenAIService
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator

class EventAIGenerator:
    def __init__(
        self,
        openai_service: "OpenAIService",
        multilingual_prompt_generator: "MultilingualPromptGenerator",
        settings: Dict[str, Any]
    ):
        self._openai_service = openai_service
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._settings = settings

    async def generate_event_details_from_ai(
        self,
        guild_id: str,
        event_concept: str,
        related_context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Uses AI to generate details for a game event.

        Args:
            guild_id: The ID of the guild.
            event_concept: A string describing the event idea or trigger.
            related_context: Optional dictionary providing specific context for the event
                             (e.g., involved NPCs, location, player actions).

        Returns:
            A dictionary containing the structured, multilingual event data from the AI,
            or None if generation fails.
        """
        if not self._multilingual_prompt_generator:
            print("EventAIGenerator ERROR: MultilingualPromptGenerator is not available.")
            return None
        if not self._openai_service:
            print("EventAIGenerator ERROR: OpenAIService is not available.")
            return None
        if not self._settings:
            print("EventAIGenerator ERROR: Settings are not available.")
            return None

        print(f"EventAIGenerator: Generating AI details for event concept '{event_concept}' in guild {guild_id}.")

        context_data = self._multilingual_prompt_generator.context_collector.get_full_context(
            guild_id=guild_id
        )
        if related_context:
            context_data["event_specific_inputs"] = related_context

        specific_task_prompt = f"""
        Design details for a game event based on the following concept and context.
        Event Concept: {event_concept}
        Additional Event Context: {json.dumps(related_context) if related_context else "None provided."}

        The event details should include:
        - event_id (suggest a unique slug-like ID if this is a template, or state if it's an instance)
        - title_i18n (multilingual, compelling title for the event)
        - description_i18n (multilingual, detailed description of what is happening)
        - type (e.g., "dynamic_encounter", "environmental_hazard", "social_interaction", "mini_quest_trigger")
        - duration_description_i18n (multilingual, e.g., "lasts for a few hours", "ongoing until resolved")
        - stages_i18n (optional, if a multi-stage event, an array of stage descriptions, multilingual)
        - involved_entities_i18n (optional, descriptions of how specific NPCs, factions, or locations are involved, multilingual)
        - potential_outcomes_i18n (multilingual, brief on possible results or player impacts)
        - player_interaction_hooks_i18n (multilingual, how players can interact or what choices they might have)

        Ensure all textual fields are in the specified multilingual JSON format ({{"en": "...", "ru": "..."}}).
        Incorporate elements from the broader lore and world state context provided.
        """

        prompt_messages = self._multilingual_prompt_generator._build_full_prompt_for_openai(
            specific_task_prompt=specific_task_prompt,
            context_data=context_data
        )

        system_prompt = prompt_messages["system"]
        user_prompt = prompt_messages["user"]

        ai_settings = self._settings.get("event_generation_ai_settings", {})
        max_tokens = ai_settings.get("max_tokens", 1800)
        temperature = ai_settings.get("temperature", 0.7)

        generated_data = await self._openai_service.generate_structured_multilingual_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

        if generated_data and "error" not in generated_data:
            print(f"EventAIGenerator: Successfully generated AI details for event '{event_concept}'.")
            return generated_data
        else:
            error_detail = generated_data.get("error") if generated_data else "Unknown error"
            raw_text = generated_data.get("raw_text", "") if generated_data else ""
            print(f"EventAIGenerator ERROR: Failed to generate AI details for event '{event_concept}'. Error: {error_detail}")
            if raw_text:
                print(f"EventAIGenerator: Raw response from AI was: {raw_text[:500]}...")
            return None
