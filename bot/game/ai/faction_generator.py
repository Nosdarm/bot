from typing import Dict, Any, Optional, List, Tuple
import json

# Assuming OpenAIService and MultilingualPromptGenerator are importable
# from bot.services.openai_service import OpenAIService
# from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator

# Placeholder for actual imports if not available in subtask environment
OpenAIService = Any
MultilingualPromptGenerator = Any

class AIFactionGenerator:
    def __init__(self, openai_service: OpenAIService, prompt_generator: MultilingualPromptGenerator):
        """
        Initializes the AIFactionGenerator.

        Args:
            openai_service: An instance of the OpenAIService for LLM calls.
            prompt_generator: An instance of MultilingualPromptGenerator for creating prompts.
        """
        self.openai_service = openai_service
        self.prompt_generator = prompt_generator

    async def generate_factions_from_concept(
        self,
        guild_setting: str,
        existing_npcs_summary: Optional[str],
        existing_locations_summary: Optional[str],
        lang: str,
        num_factions: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Generates a list of faction concepts using an LLM.

        Args:
            guild_setting: Brief description of the game world.
            existing_npcs_summary: Optional string summarizing key existing NPCs.
            existing_locations_summary: Optional string summarizing key existing locations.
            lang: The desired language code for the faction details.
            num_factions: The number of distinct faction concepts to generate.

        Returns:
            A list of dictionaries, where each dictionary represents a faction concept,
            or an empty list if generation fails or parsing is unsuccessful.
        """
        if not self.openai_service or not self.prompt_generator:
            print("Error: AI services not configured for faction generation.") # Or log
            return []

        try:
            system_prompt, user_prompt = self.prompt_generator.generate_faction_creation_prompt(
                guild_setting=guild_setting,
                existing_npcs_summary=existing_npcs_summary,
                existing_locations_summary=existing_locations_summary,
                lang=lang,
                num_factions=num_factions
            )

            # Max tokens might need to be generous for multiple factions in JSON
            # Adjust based on typical response length for num_factions
            # Max tokens for gpt-3.5-turbo is 4096 (shared for prompt and completion)
            # Max tokens for gpt-4 is 8192 or 32k
            # Let's assume a reasonable number of factions (e.g., 3-5) won't exceed token limits for standard models.
            # For 3 factions, maybe 1000-1500 tokens for completion is safe.
            llm_response_str = await self.openai_service.generate_master_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=1500 + (num_factions * 200) # Rough estimate, adjust as needed
            )

            if not llm_response_str:
                print(f"AI service returned an empty response for faction generation (lang: {lang}).")
                return []

            # The LLM is prompted to return a JSON list.
            # Need to find the JSON block if it's embedded.
            try:
                # Attempt to find JSON list within ```json ... ``` block or just parse directly
                json_block = llm_response_str # Default to whole string
                if "```json" in llm_response_str:
                    json_block = llm_response_str.split("```json")[1].split("```")[0].strip()
                elif "```" in llm_response_str: # Simpler ``` block
                    json_block = llm_response_str.split("```")[1].strip()
                else: # Assume the whole response is JSON or a JSON list
                    json_block = llm_response_str.strip()

                # Ensure it's treated as a list
                parsed_response: Any
                if json_block.startswith("{") and not json_block.startswith("["):
                    if num_factions == 1:
                         parsed_response = [json.loads(json_block)]
                    else:
                         print(f"AI returned a single JSON object, expected a list for multiple factions. Content: {json_block[:200]}...")
                         # Attempt to parse as a list, expecting it to fail or be an error.
                         # However, if the LLM *really* messed up and returned a dict with faction list inside,
                         # this simple json.loads(json_block) might not be enough.
                         # For now, trust the prompt for a list or a single object if num_factions is 1.
                         parsed_response = json.loads(json_block)


                elif json_block.startswith("["):
                    parsed_response = json.loads(json_block)
                else:
                    print(f"AI response for factions doesn't look like valid JSON list or object. Content: {json_block[:200]}...")
                    return []


                if not isinstance(parsed_response, list):
                    print(f"Parsed AI response for factions is not a list. Type: {type(parsed_response)}")
                    # This case should ideally be caught by the logic above if num_factions == 1 and a dict was returned.
                    # If it's a dict here and num_factions > 1, it's an error.
                    if isinstance(parsed_response, dict) and num_factions != 1:
                        print(f"Error: Received a dictionary but expected a list for {num_factions} factions.")
                        return []
                    elif isinstance(parsed_response, dict) and num_factions == 1: # This should have been wrapped.
                         print("Warning: Single faction dict was not wrapped into list earlier, but should have been.")
                         # This indicates a logic flaw above if not wrapped.
                         # For safety, let's assume if it's a dict and num_factions is 1, it's the single faction.
                         # However, the code above should already handle this.
                         # If it reaches here as a dict, and num_factions is 1, it's an unexpected state.
                         # For robustness, we could re-wrap, but it's better to fix the logic that led here.
                         # For now, let's treat it as an error if it's a dict and wasn't already wrapped.
                         return []


                validated_factions = []
                for faction_data in parsed_response:
                    if isinstance(faction_data, dict) and 'name_i18n' in faction_data and 'description_i18n' in faction_data:
                        validated_factions.append(faction_data)
                    else:
                        print(f"Warning: Skipping faction data due to missing required fields or incorrect format: {str(faction_data)[:200]}...")

                return validated_factions

            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON response from AI for faction generation (lang: {lang}). Error: {e}. Response: {llm_response_str[:500]}...")
                return []
            except Exception as e_parse:
                 print(f"Error processing LLM response for faction generation (lang: {lang}): {e_parse}. Response: {llm_response_str[:500]}...")
                 return []


        except AttributeError as e: # Specifically for self.prompt_generator missing method
            print(f"Error: Missing method in prompt generator for faction creation: {e}")
            return []
        except Exception as e: # Catch-all for other errors during the process
            print(f"Error during AI faction generation (lang: {lang}): {e}")
            return []
