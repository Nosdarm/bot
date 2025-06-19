from __future__ import annotations
import logging
import json
from typing import Optional, Dict, Any, TYPE_CHECKING, List

from bot.models.pending_generation import PendingGeneration, GenerationType, PendingStatus
from bot.persistence.pending_generation_crud import PendingGenerationCRUD # Assuming this path is correct
from bot.database.guild_transaction import GuildTransaction # Added import

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.game.managers.game_manager import GameManager # For get_rule, and other manager access

logger = logging.getLogger(__name__)

class AIGenerationManager:
    def __init__(self,
                 db_service: DBService,
                 prompt_context_collector: PromptContextCollector,
                 multilingual_prompt_generator: MultilingualPromptGenerator,
                 ai_response_validator: AIResponseValidator,
                 game_manager: GameManager # Added GameManager
                 ):
        self.db_service = db_service
        self.prompt_context_collector = prompt_context_collector
        self.multilingual_prompt_generator = multilingual_prompt_generator
        self.ai_response_validator = ai_response_validator
        self.game_manager = game_manager # Store GameManager
        self.pending_generation_crud = PendingGenerationCRUD(db_service) # Initialize CRUD helper
        logger.info("AIGenerationManager initialized.")

    async def request_content_generation(
        self,
        guild_id: str,
        request_type: GenerationType,
        context_params: Dict[str, Any], # Params for PromptContextCollector
        prompt_params: Dict[str, Any],  # Params for MultilingualPromptGenerator (e.g. specific_task_instruction)
        created_by_user_id: Optional[str] = None
    ) -> Optional[PendingGeneration]:
        """
        Central method to request any type of AI content generation.
        It gathers context, generates a prompt, (simulates) calls AI, validates, and stores the pending generation.
        """
        logger.info(f"AIGenerationManager: Requesting '{request_type.value}' generation for guild {guild_id} by user {created_by_user_id}. Context: {context_params}, Prompt: {prompt_params}")

        # 1. Gather Context
        # PromptContextCollector needs character_id, target_entity_id, location_id etc.
        # These should be passed in context_params.
        generation_context = await self.prompt_context_collector.get_full_context(
            guild_id=guild_id,
            character_id=context_params.get("character_id"), # Ensure these are provided as needed by request_type
            target_entity_id=context_params.get("target_entity_id"),
            target_entity_type=context_params.get("target_entity_type"),
            location_id=context_params.get("location_id"),
            event_id=context_params.get("event_id"),
            # Pass other kwargs from context_params that get_full_context might use
            **context_params
        )

        # 2. Generate Prompt
        # prepare_ai_prompt expects generation_type (string), context, optional player_id (should be character_id), target_languages
        # The `player_id` param in `prepare_ai_prompt` should ideally be `character_id` as per previous review (A.2.3.4).
        # For now, we'll pass character_id if available in context_params.

        # Determine target languages for the prompt
        # This could come from GuildConfig via GameManager, or passed in prompt_params
        target_languages = prompt_params.get("target_languages")
        if not target_languages:
            default_lang = await self.game_manager.get_rule(guild_id, "default_language", "en")
            target_languages = sorted(list(set([default_lang, "en"])))

        final_prompt_str = await self.multilingual_prompt_generator.prepare_ai_prompt(
            generation_type_str=request_type.value, # Pass the string value of the enum
            context=generation_context,
            # This should align with the refined parameter name (character_id) after A.2.3.4 is implemented
            character_id=context_params.get("character_id"),
            target_languages=target_languages,
            specific_task_instruction=prompt_params.get("specific_task_instruction"),
            # Pass other kwargs from prompt_params that prepare_ai_prompt might use
            **prompt_params
        )

        # 3. Call AI Service (Simulated for now)
        # In a real scenario, this would be: raw_ai_output = await self.openai_service.get_completion(final_prompt_str)
        logger.info(f"AIGenerationManager: Using placeholder AI response for '{request_type.value}'.")
        if request_type == GenerationType.LOCATION_DETAILS:
            # More complex structure for LOCATION_DETAILS
            raw_ai_output = json.dumps({
                "template_id": "generic_forest_clearing_template",
                "name_i18n": {"en": "Sun-dappled Clearing", "ru": "Солнечная Поляна"},
                "atmospheric_description_i18n": {"en": "A quiet clearing bathed in sunlight.", "ru": "Тихая поляна, залитая солнечным светом."},
                "points_of_interest": [
                    {"poi_id": "old_oak_tree", "name_i18n": {"en": "Old Oak Tree", "ru": "Старый Дуб"}, "description_i18n": {"en": "A massive, ancient oak stands here.", "ru": "Здесь стоит массивный древний дуб."}}
                ],
                "connections": [
                    {"to_location_id": "forest_path_west", "direction_i18n": {"en": "West", "ru": "Запад"}, "description_i18n": {"en": "A path leads west.", "ru": "Тропа ведет на запад."}}
                ]
            })
        else: # Generic placeholder for other types
             raw_ai_output = json.dumps({"name_i18n": {"en": "Generated Name", "ru": "Сгенерированное Имя"}, "description_i18n": {"en": "Generated description.", "ru": "Сгенерированное описание."}})


        # 4. Validate Response
        parsed_data, validation_issues = await self.ai_response_validator.parse_and_validate_ai_response(
            raw_ai_output_text=raw_ai_output,
            guild_id=guild_id,
            request_type=request_type.value, # Pass string value
            game_manager=self.game_manager # Pass GameManager for semantic validation rules
        )

        current_status = PendingStatus.PENDING_MODERATION
        if validation_issues:
            current_status = PendingStatus.FAILED_VALIDATION
            logger.warning(f"AIGenerationManager: Validation issues for '{request_type.value}' in guild {guild_id}: {validation_issues}")

        # 5. Create PendingGeneration Record using CRUD
        # The CRUD methods expect an active session, so this manager method should be called within a transaction.
        # For now, assuming the caller (e.g., a command or service) handles the transaction.
        # If not, AIGenerationManager would need to start one here.
        # Let's make it explicit that it needs a session.

        # This method should be called within a session scope managed by the caller.
        # For standalone use or testing, a session would need to be created here.
        # For now, let's assume session is handled by caller or by db_service.get_session() within CRUD
        # if CRUD methods are refactored to manage their own sessions (less ideal for multiple ops).
        # The CRUD methods defined expect a session to be passed.
        # So, this method must be called from within a GuildTransaction block.

        # To make this method testable and usable, it should accept an optional session.
        # If no session is passed, it could create one, but that's less flexible.
        # The prompt implies this manager method is called, and it then uses CRUD.
        # So, the transaction should ideally wrap the call to this manager method.
        # For now, this method will create its own transaction for the CRUD operation.
        # This is NOT ideal if multiple AIGenerationManager calls are part of a larger operation.

        pending_generation_record = None
        try:
            async with GuildTransaction(self.db_service.get_session_factory, guild_id) as session:
                pending_generation_record = await self.pending_generation_crud.create_pending_generation(
                    session=session,
                    guild_id=guild_id,
                    request_type=request_type,
                    status=current_status,
                    request_params_json=context_params, # Storing context_params as request_params for now
                    raw_ai_output_text=raw_ai_output,
                    parsed_data_json=parsed_data,
                    validation_issues_json=[issue.model_dump() for issue in validation_issues] if validation_issues else None,
                    created_by_user_id=created_by_user_id
                )
            logger.info(f"AIGenerationManager: PendingGeneration record {pending_generation_record.id} created for '{request_type.value}' in guild {guild_id}.")

            # TODO: Send notification if status is PENDING_MODERATION (using NotificationService)
            # This was planned for GameManager.trigger_ai_generation. This manager could do it too.
            if current_status == PendingStatus.PENDING_MODERATION and self.game_manager.notification_service:
                 guild_config = await self.game_manager.db_service.get_entity_by_pk(self.game_manager.db_service.models.GuildConfig, guild_id) # type: ignore
                 if guild_config:
                    notification_channel_id = guild_config.notification_channel_id or guild_config.master_channel_id or guild_config.system_channel_id
                    if notification_channel_id:
                        msg = f"🔔 New AI Content (Type: '{request_type.value}', ID: `{pending_generation_record.id}`) is awaiting moderation."
                        await self.game_manager.notification_service.send_notification(int(notification_channel_id), msg)

        except Exception as e:
            logger.error(f"AIGenerationManager: Failed to create PendingGeneration record for '{request_type.value}' in guild {guild_id}: {e}", exc_info=True)
            # If record creation fails, the AI call was still made. This might need more robust error handling.
            return None

        return pending_generation_record

    async def request_location_generation(
        self,
        guild_id: str,
        context_params: Dict[str, Any], # e.g., {"location_template_id": "forest_clearing", "theme_hints": ["ancient", "mysterious"]}
        prompt_params: Dict[str, Any],  # e.g., {"specific_task_instruction": "Generate a forest clearing with a hidden shrine."}
        created_by_user_id: Optional[str] = None
    ) -> Optional[PendingGeneration]:
        """Helper method specifically for location generation requests."""
        # Assuming LOCATION_DETAILS is the more comprehensive type for full location generation
        return await self.request_content_generation(
            guild_id=guild_id,
            request_type=GenerationType.LOCATION_DETAILS,
            context_params=context_params,
            prompt_params=prompt_params,
            created_by_user_id=created_by_user_id
        )

    async def process_approved_generation(
        self,
        pending_generation_id: str,
        guild_id: str,
        moderator_user_id: str
    ) -> bool:
        """
        Processes a PendingGeneration record that has been marked as APPROVED.
        This involves creating the actual game entities (Location, NPC, Quest, etc.)
        based on the parsed_data_json.
        Returns True if processing was successful and entity applied, False otherwise.
        """
        logger.info(f"AIGenerationManager: Processing approved generation ID {pending_generation_id} for guild {guild_id} by moderator {moderator_user_id}.")

        try:
            async with GuildTransaction(self.db_service.get_session_factory, guild_id) as session:
                # Fetch the PendingGeneration record within the transaction
                record = await self.pending_generation_crud.get_pending_generation_by_id(session, pending_generation_id, guild_id)

                if not record:
                    logger.error(f"AIGenerationManager: PendingGeneration record {pending_generation_id} not found for guild {guild_id} during processing.")
                    return False

                if record.status != PendingStatus.APPROVED:
                    logger.warning(f"AIGenerationManager: Attempted to process generation {pending_generation_id} which is not in APPROVED status (current: {record.status.value}).")
                    # Optionally update status to FAILED_APPLICATION if this is considered an error state
                    # await self.pending_generation_crud.update_pending_generation_status(
                    #     session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_notes="Attempted to process non-approved record."
                    # )
                    return False

                if not record.parsed_data_json:
                    logger.error(f"AIGenerationManager: No parsed_data_json found for approved generation {pending_generation_id}. Cannot process.")
                    await self.pending_generation_crud.update_pending_generation_status(
                        session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                        moderator_user_id=moderator_user_id,
                        moderator_notes="No parsed data available for application."
                    )
                    return False

                request_type = record.request_type
                parsed_data = record.parsed_data_json
                application_success = False

                # TODO: Implement detailed entity persistence based on request_type
                # This is where the actual game objects (Locations, NPCs, Quests, Items etc.) are created from parsed_data
                # Each block will call relevant GameManager methods or specific manager methods, passing the session.

                logger.info(f"AIGenerationManager: [PLACEHOLDER] Processing request_type: {request_type.value} for PG ID {record.id}")
                logger.debug(f"AIGenerationManager: [PLACEHOLDER] Data for PG ID {record.id}: {json.dumps(parsed_data, indent=2, ensure_ascii=False)[:500]}...") # Log snippet of data

                if request_type == GenerationType.LOCATION_DETAILS:
                    logger.info(f"AIGenerationManager: [SIMULATING PERSISTENCE] Would create/update location from: {parsed_data.get('name_i18n', {}).get('en', 'Unknown Location')}")
                    # Example (conceptual - actual methods might differ or be on GameManager):
                    # loc_success = await self.game_manager.location_manager.create_location_from_ai_data(session, guild_id, parsed_data)
                    # if loc_success and parsed_data.get("npcs"):
                    #    for npc_data in parsed_data.get("npcs"):
                    #        await self.game_manager.npc_manager.create_npc_from_ai_data(session, guild_id, npc_data, new_location_id=loc_success.id)
                    # application_success = bool(loc_success) # Update based on actual outcome
                    application_success = True # Placeholder for MVP

                elif request_type == GenerationType.NPC_PROFILE:
                    logger.info(f"AIGenerationManager: [SIMULATING PERSISTENCE] Would create/update NPC from: {parsed_data.get('name_i18n', {}).get('en', 'Unknown NPC')}")
                    # npc_success = await self.game_manager.npc_manager.create_npc_from_ai_data(session, guild_id, parsed_data)
                    # application_success = bool(npc_success)
                    application_success = True # Placeholder

                elif request_type == GenerationType.QUEST_FULL:
                    logger.info(f"AIGenerationManager: [SIMULATING PERSISTENCE] Would create/update Quest from: {parsed_data.get('name_i18n', {}).get('en', 'Unknown Quest')}")
                    # quest_success = await self.game_manager.quest_manager.create_quest_from_ai_data(session, guild_id, parsed_data)
                    # application_success = bool(quest_success)
                    application_success = True # Placeholder

                elif request_type == GenerationType.ITEM_PROFILE:
                    logger.info(f"AIGenerationManager: [SIMULATING PERSISTENCE] Would create/update Item Template from: {parsed_data.get('name_i18n', {}).get('en', 'Unknown Item')}")
                    # item_success = await self.game_manager.item_manager.create_item_template_from_ai_data(session, guild_id, parsed_data)
                    # application_success = bool(item_success)
                    application_success = True # Placeholder

                # Add other request_type handlers here...
                else:
                    logger.warning(f"AIGenerationManager: No specific persistence logic defined for request_type '{request_type.value}' for PG ID {record.id}.")
                    # Decide if this is an error or if some types don't need persistence (e.g., dialogue line if it was just for display)
                    # For now, assume types that reach here and aren't handled should not be marked as APPLIED.
                    application_success = False # Or True if some types are informational and don't persist.
                    await self.pending_generation_crud.update_pending_generation_status(
                        session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                        moderator_user_id=moderator_user_id,
                        moderator_notes=f"No application logic for type '{request_type.value}'."
                    )
                    return False


                if application_success:
                    await self.pending_generation_crud.update_pending_generation_status(
                        session, record.id, PendingStatus.APPLIED, guild_id,
                        moderator_user_id=moderator_user_id, # Keep moderator info
                        moderator_notes=record.moderator_notes # Keep original notes
                    )
                    logger.info(f"AIGenerationManager: Successfully processed and applied generation {pending_generation_id}. Status set to APPLIED.")
                    return True
                else:
                    logger.error(f"AIGenerationManager: Application of generation {pending_generation_id} (type: {request_type.value}) failed during persistence logic.")
                    # If not already set by specific failure
                    if record.status != PendingStatus.APPLICATION_FAILED:
                         await self.pending_generation_crud.update_pending_generation_status(
                            session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                            moderator_user_id=moderator_user_id,
                            moderator_notes=record.moderator_notes + " | Application persistence failed." if record.moderator_notes else "Application persistence failed."
                        )
                    return False

        except Exception as e:
            logger.error(f"AIGenerationManager: Unexpected error in process_approved_generation for ID {pending_generation_id}: {e}", exc_info=True)
            # Attempt to update status to FAILED_PROCESSING even if other parts of transaction failed
            try:
                async with GuildTransaction(self.db_service.get_session_factory, guild_id) as error_session:
                    await self.pending_generation_crud.update_pending_generation_status(
                        error_session, pending_generation_id, PendingStatus.APPLICATION_FAILED, guild_id,
                        moderator_user_id=moderator_user_id,
                        moderator_notes=f"Application failed due to exception: {str(e)[:100]}" # Truncate long errors
                    )
            except Exception as e_status_update:
                 logger.error(f"AIGenerationManager: CRITICAL - Failed to update status to APPLICATION_FAILED for {pending_generation_id} after error: {e_status_update}", exc_info=True)
            return False

    # Other specific request_... methods can be added here later, e.g.:
    # async def request_npc_generation(...) -> Optional[PendingGeneration]:
    # async def request_quest_generation(...) -> Optional[PendingGeneration]:
    # async def request_item_generation(...) -> Optional[PendingGeneration]:

