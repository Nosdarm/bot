import logging
import uuid
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession # For type hinting session if passed around

from bot.database.models import GeneratedFaction
# create_entity might not be directly used if we are creating model instances directly and adding to session
# from bot.database.crud_utils import create_entity

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__)

class FactionManager:
    def __init__(self, game_manager: "GameManager"):
        self.game_manager = game_manager
        if not self.game_manager:
            logger.critical("FactionManager initialized without a valid GameManager instance!")
        logger.info("FactionManager initialized.")

    async def generate_and_save_factions(
        self,
        guild_id: str,
        theme_keywords: Optional[List[str]] = None,
        num_to_generate: int = 2
    ) -> List[GeneratedFaction]:
        """
        Generates new factions using AI based on themes and context,
        validates the response, and saves valid factions to the database.

        Args:
            guild_id: The ID of the guild for which to generate factions.
            theme_keywords: Optional list of keywords to guide faction theme.
            num_to_generate: The number of factions to attempt to generate.

        Returns:
            A list of successfully created and saved GeneratedFaction objects,
            or an empty list if generation, validation, or saving fails.
        """
        log_prefix = f"FactionGeneration (Guild: {guild_id})"
        logger.info(f"{log_prefix}: Starting faction generation. Themes: {theme_keywords}, Num: {num_to_generate}.")

        # 1. Access Services via self.game_manager
        if not (hasattr(self.game_manager, 'multilingual_prompt_generator') and self.game_manager.multilingual_prompt_generator and
                hasattr(self.game_manager, 'openai_service') and self.game_manager.openai_service and
                hasattr(self.game_manager, 'ai_response_validator') and self.game_manager.ai_response_validator and
                hasattr(self.game_manager, 'db_service') and self.game_manager.db_service):
            logger.error(f"{log_prefix}: One or more required services (PromptGenerator, OpenAIService, AIValidator, DBService) are missing from GameManager.")
            return []

        prompt_generator = self.game_manager.multilingual_prompt_generator
        openai_service = self.game_manager.openai_service
        validator = self.game_manager.ai_response_validator
        db_service = self.game_manager.db_service

        created_factions: List[GeneratedFaction] = []

        async with db_service.get_session() as session:
            try:
                # 2. Prepare Prompt
                logger.debug(f"{log_prefix}: Preparing faction generation prompt.")
                prompt = await prompt_generator.prepare_faction_generation_prompt(
                    guild_id, session, self.game_manager, theme_keywords, num_to_generate
                )
                if not prompt or prompt.startswith("Error:"):
                    logger.error(f"{log_prefix}: Failed to generate prompt. Details: {prompt}")
                    return []
                logger.debug(f"{log_prefix}: Prompt generated (first 300 chars): {prompt[:300]}...")

                # 3. Call OpenAI Service
                logger.debug(f"{log_prefix}: Requesting completion from OpenAI.")
                raw_ai_output = await openai_service.get_completion(prompt_text=prompt)
                if not raw_ai_output:
                    logger.error(f"{log_prefix}: AI service returned no output.")
                    return []
                logger.debug(f"{log_prefix}: Raw AI output received (first 100 chars): {raw_ai_output[:100]}")

                # 4. Validate AI Response
                logger.debug(f"{log_prefix}: Validating AI response.")
                validated_faction_data_list = await validator.parse_and_validate_faction_generation_response(
                    raw_ai_output, guild_id, self.game_manager
                )
                if not validated_faction_data_list: # Handles None or empty list if validator returns that for "no valid items"
                    logger.error(f"{log_prefix}: AI response validation failed or returned no valid factions. Raw output: {raw_ai_output}")
                    return []
                logger.info(f"{log_prefix}: AI response validated successfully. Found {len(validated_faction_data_list)} valid factions.")

                # 5. Create and Save Faction Entities
                for faction_data in validated_faction_data_list:
                    faction_model_data = {
                        "id": str(uuid.uuid4()), # Generate new ID for each faction
                        "guild_id": guild_id,
                        "name_i18n": faction_data.get("name_i18n"),
                        "ideology_i18n": faction_data.get("ideology_i18n"), # This is optional in GeneratedFaction model
                        "description_i18n": faction_data.get("description_i18n"),
                        # Optional fields from prompt are not directly in GeneratedFaction model by default.
                        # If GeneratedFaction model is extended to include leader_concept_i18n, etc., add them here.
                        # "leader_concept_i18n": faction_data.get("leader_concept_i18n"),
                        # "resource_notes_i18n": faction_data.get("resource_notes_i18n"),
                        # "alignment_suggestion": faction_data.get("alignment_suggestion") # if you add this
                    }

                    # Filter out None values for optional fields not directly in model or if AI omits them
                    # Example for ideology_i18n which is optional in the DB model:
                    if faction_model_data["ideology_i18n"] is None:
                        del faction_model_data["ideology_i18n"]


                    # Ensure all required fields for GeneratedFaction model are present
                    if not faction_model_data.get("name_i18n") or not faction_model_data.get("description_i18n"):
                        logger.warning(f"{log_prefix}: Skipping faction due to missing required fields (name or description) after validation. Data: {faction_data}")
                        continue

                    new_faction = GeneratedFaction(**faction_model_data)
                    session.add(new_faction)
                    created_factions.append(new_faction)
                    logger.debug(f"{log_prefix}: Prepared and added new faction {new_faction.id} to session.")

                if created_factions:
                    await session.commit()
                    logger.info(f"{log_prefix}: Successfully generated and saved {len(created_factions)} factions to DB.")
                    # Refresh instances from DB to get all DB-generated fields if any
                    for faction in created_factions:
                        await session.refresh(faction) # Ensures any server-side defaults or triggers are loaded
                else:
                    logger.info(f"{log_prefix}: No valid factions were processed to be saved.")
                    # No commit needed if nothing was added

                return created_factions

            except Exception as e:
                logger.error(f"{log_prefix}: Error during faction generation and saving: {e}", exc_info=True)
                if 'session' in locals() and session.is_active: # Check if session was defined and is active
                    await session.rollback()
                return []
