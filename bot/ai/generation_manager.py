from __future__ import annotations
import logging
import json
from typing import Optional, Dict, Any, TYPE_CHECKING, List
import uuid # Added for location ID generation

# Models for persistence
from bot.database.models.world_related import Location
from bot.ai.ai_data_models import GeneratedLocationContent, POIModel, ConnectionModel, GeneratedNpcProfile # Added GeneratedNpcProfile
from sqlalchemy.orm.attributes import flag_modified # Added for npc_ids update

from bot.models.pending_generation import PendingGeneration, GenerationType, PendingStatus
from bot.persistence.pending_generation_crud import PendingGenerationCRUD # Assuming this path is correct
from bot.database.guild_transaction import GuildTransaction # Added import
from sqlalchemy.future import select # Added for querying existing location

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
                    ai_location_data: Optional[GeneratedLocationContent] = None
                    logger.info(f"Attempting to parse LOCATION_DETAILS data for PG ID {record.id}...")
                    try:
                        # parsed_data is already a dict from JSONB
                        ai_location_data = GeneratedLocationContent(**parsed_data)
                        logger.info(f"Successfully parsed LOCATION_DETAILS data for PG ID {record.id}.")
                    except Exception as e:
                        logger.error(f"Failed to parse LOCATION_DETAILS data for PG ID {record.id}: {e}", exc_info=True)
                        application_success = False
                        await self.pending_generation_crud.update_pending_generation_status(
                            session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                            moderator_user_id=moderator_user_id,
                            moderator_notes=record.moderator_notes + f" | Failed to parse AI data: {str(e)[:100]}" if record.moderator_notes else f"Failed to parse AI data: {str(e)[:100]}"
                        )
                        # Return False here as we cannot proceed with this specific generation
                        return False # Critical parsing error, stop processing this record

                    if ai_location_data: # Ensure parsing was successful
                        location_to_persist: Optional[Location] = None
                        location_id_to_use: Optional[str] = None
                        existing_location: Optional[Location] = None

                        if ai_location_data.static_id:
                            stmt = select(Location).filter_by(guild_id=guild_id, static_id=ai_location_data.static_id)
                            result = await session.execute(stmt)
                            existing_location = result.scalars().first()

                        if existing_location:
                            location_to_persist = existing_location
                            location_id_to_use = existing_location.id
                            logger.info(f"Updating existing location {location_id_to_use} with static_id {ai_location_data.static_id} for PG ID {record.id}")
                        else:
                            location_to_persist = Location(guild_id=guild_id)
                            location_to_persist.id = str(uuid.uuid4()) # Set new UUID
                            location_id_to_use = location_to_persist.id
                            if ai_location_data.static_id:
                                location_to_persist.static_id = ai_location_data.static_id
                            logger.info(f"Creating new location {location_id_to_use} (static_id: {ai_location_data.static_id}) for PG ID {record.id}")
                            # session.add(location_to_persist) # Add is done by merge if new

                        # Populate fields
                        location_to_persist.name_i18n = ai_location_data.name_i18n
                        location_to_persist.descriptions_i18n = ai_location_data.atmospheric_description_i18n
                        location_to_persist.template_id = ai_location_data.template_id
                        # Ensure static_id is set if provided and it's a new record or updating an old one
                        if ai_location_data.static_id:
                             location_to_persist.static_id = ai_location_data.static_id

                        # Get translated location type name
                        type_key = ai_location_data.location_type_key
                        type_i18n_map = await self.game_manager.get_location_type_i18n_map(guild_id, type_key)

                        if type_i18n_map and isinstance(type_i18n_map, dict):
                            location_to_persist.type_i18n = type_i18n_map
                            logger.info(f"Applied translated type_i18n for key '{type_key}' for location ID '{location_id_to_use}' (PG ID {record.id}).")
                        else:
                            fallback_type_i18n = {"en": type_key.replace("_", " ").title()}
                            location_to_persist.type_i18n = fallback_type_i18n
                            logger.warning(
                                f"Location type key '{type_key}' not found or invalid map in definitions for location ID '{location_id_to_use}' (PG ID {record.id}). "
                                f"Using fallback: {fallback_type_i18n}. Returned map: {type_i18n_map}"
                            )

                        location_to_persist.coordinates = ai_location_data.coordinates_json
                        location_to_persist.details_i18n = ai_location_data.generated_details_json
                        location_to_persist.ai_metadata_json = ai_location_data.ai_metadata_json

                        if ai_location_data.points_of_interest:
                            location_to_persist.points_of_interest_json = [poi.model_dump() for poi in ai_location_data.points_of_interest]
                        else:
                            location_to_persist.points_of_interest_json = []

                        if ai_location_data.connections:
                            location_to_persist.neighbor_locations_json = [conn.model_dump() for conn in ai_location_data.connections]
                        else:
                            location_to_persist.neighbor_locations_json = []

                        # NPC and Item lists are intentionally NOT handled here per subtask instructions
                        # location_to_persist.npc_ids = []
                        # location_to_persist.item_ids = []

                        try:
                            await session.merge(location_to_persist)
                            await session.flush() # Ensure location_to_persist.id is populated if new
                            record.entity_id = location_to_persist.id # Store created/updated entity ID back on PendingGeneration
                            persisted_location_id = location_to_persist.id # Use this for NPCs
                            logger.info(f"Successfully merged location {persisted_location_id} (template: {location_to_persist.template_id}, static: {location_to_persist.static_id}) for PG ID {record.id}.")
                            application_success = True

                            # Call on_enter_location if a new location was effectively created or significantly updated
                            # We need to determine the "entity" that "entered".
                            # If this generation was triggered by a player moving to an "unknown" area, that player is the entity.
                            # If it's a GM creating a location, there might not be an immediate entering entity.
                            # For now, let's assume if record.created_by_user_id exists, it's a player character.
                            # This is a simplification. A more robust system would pass the triggering entity's ID and type.

                            entering_entity_id_for_event: Optional[str] = None
                            entering_entity_type_for_event: Optional[str] = None

                            if record.created_by_user_id: # Assume this is a discord_id
                                request_params = record.request_params_json or {}
                                if isinstance(request_params, str): # Should be dict if from DB JSONB
                                    try: request_params = json.loads(request_params)
                                    except: request_params = {}

                                entering_entity_id_for_event = request_params.get("triggering_character_id")
                                if entering_entity_id_for_event:
                                    entering_entity_type_for_event = "Character"
                                else: # Fallback to party if character not specified but party is
                                    entering_entity_id_for_event = request_params.get("triggering_party_id")
                                    if entering_entity_id_for_event:
                                        entering_entity_type_for_event = "Party"

                            if entering_entity_id_for_event and entering_entity_type_for_event and self.game_manager.location_interaction_service and persisted_location_id:
                                logger.info(f"AIGenerationManager: Scheduling on_enter_location for entity {entering_entity_id_for_event} ({entering_entity_type_for_event}) into new/updated location {persisted_location_id}")
                                import asyncio # Make sure asyncio is imported
                                asyncio.create_task(
                                    self.game_manager.location_interaction_service.process_on_enter_location_events(
                                        guild_id_str=guild_id, # Ensure this is string
                                        entity_id=str(entering_entity_id_for_event),
                                        entity_type=str(entering_entity_type_for_event),
                                        location_id=str(persisted_location_id)
                                    )
                                )
                            elif persisted_location_id:
                                logger.info(f"AIGenerationManager: Location {persisted_location_id} created/updated, but no specific entering entity identified from PendingGeneration record to trigger on_enter_location.")

                            # --- Update Neighbor Connections Start (Задача 4.3.1) ---
                            if application_success and persisted_location_id and ai_location_data.connections:
                                logger.info(f"Updating neighbor connections for new/updated location {persisted_location_id} (PG ID {record.id}).")
                                new_location_name_i18n = location_to_persist.name_i18n or {"en": "Newly discovered area"}

                                for connection_data in ai_location_data.connections:
                                    if not isinstance(connection_data, ConnectionModel): # Should already be parsed
                                        logger.warning(f"Connection data is not a ConnectionModel instance for PG ID {record.id}. Skipping: {connection_data}")
                                        continue

                                    neighbor_id = connection_data.to_location_id
                                    if not neighbor_id or neighbor_id == persisted_location_id: # Don't connect to self
                                        continue

                                    neighbor_location = await session.get(Location, neighbor_id)
                                    if neighbor_location:
                                        if neighbor_location.guild_id != guild_id: # Security check
                                            logger.warning(f"Attempted to connect to location {neighbor_id} in different guild. Skipping.")
                                            continue

                                        if neighbor_location.neighbor_locations_json is None:
                                            neighbor_location.neighbor_locations_json = []

                                        # Check if reciprocal connection already exists
                                        reciprocal_exists = any(
                                            conn.get("to_location_id") == persisted_location_id
                                            for conn in neighbor_location.neighbor_locations_json
                                        )

                                        if not reciprocal_exists:
                                            # Create reciprocal connection
                                            # For direction_i18n and path_description_i18n, it's complex to auto-generate
                                            # For now, we can use a generic or reuse parts of original if sensible.
                                            # A more advanced system might try to flip directions (e.g., "North" -> "South")
                                            reciprocal_direction_i18n = {}
                                            default_lang_for_reciprocal = await self.game_manager.get_rule(guild_id, "default_language", "en")

                                            for lang, desc in (connection_data.direction_i18n or {}).items():
                                                reciprocal_direction_i18n[lang] = f"Towards {new_location_name_i18n.get(lang, new_location_name_i18n.get(default_lang_for_reciprocal, 'the new area'))}" # Simplified

                                            if not reciprocal_direction_i18n : # fallback if original direction was empty
                                                 reciprocal_direction_i18n = {default_lang_for_reciprocal: f"Towards {new_location_name_i18n.get(default_lang_for_reciprocal, 'the new area')}"}


                                            reciprocal_connection = {
                                                "to_location_id": persisted_location_id,
                                                "path_description_i18n": connection_data.description_i18n or \
                                                                         {default_lang_for_reciprocal: f"A path leading to {new_location_name_i18n.get(default_lang_for_reciprocal, 'a newly discovered area')}"},
                                                "direction_i18n": reciprocal_direction_i18n,
                                                "travel_time_hours": connection_data.travel_time_hours,
                                                "required_items": connection_data.required_items or [],
                                                "visibility_conditions_json": connection_data.visibility_conditions_json or {}
                                            }
                                            neighbor_location.neighbor_locations_json.append(reciprocal_connection)
                                            flag_modified(neighbor_location, "neighbor_locations_json")
                                            logger.info(f"Added reciprocal connection from {neighbor_id} to {persisted_location_id} (PG ID {record.id}).")
                                        else:
                                            logger.info(f"Reciprocal connection from {neighbor_id} to {persisted_location_id} already exists. Skipping. (PG ID {record.id})")
                                    else:
                                        logger.warning(f"Neighbor location ID '{neighbor_id}' specified in connections for PG ID {record.id} not found. Cannot create reciprocal link.")
                            # --- Update Neighbor Connections End ---

                            # --- NPC Persistence Start ---
                            if application_success and ai_location_data.initial_npcs_json:
                                logger.info(f"Starting NPC persistence for location {persisted_location_id}, PG ID {record.id}.")
                                newly_created_npc_ids = []
                                npc_persistence_failed_flag = False
                                for npc_profile_data in ai_location_data.initial_npcs_json:
                                    if not isinstance(npc_profile_data, GeneratedNpcProfile):
                                        logger.warning(f"NPC profile data is not of type GeneratedNpcProfile for PG ID {record.id}. Skipping this NPC. Data: {npc_profile_data}")
                                        continue

                                    initial_state_for_npc = npc_profile_data.model_dump()

                                    # Adjust keys for NpcManager.spawn_npc_in_location
                                    if 'skills' in initial_state_for_npc:
                                        initial_state_for_npc['skills_data'] = initial_state_for_npc.pop('skills')
                                    if 'abilities' in initial_state_for_npc:
                                        initial_state_for_npc['abilities_data'] = initial_state_for_npc.pop('abilities')

                                    # New faction handling
                                    if npc_profile_data.faction_affiliations: # Check if the list exists and is not empty
                                        initial_state_for_npc['faction_id'] = npc_profile_data.faction_affiliations[0].faction_id
                                        initial_state_for_npc['faction_details_list'] = [
                                            affiliation.model_dump() for affiliation in npc_profile_data.faction_affiliations
                                        ]
                                    else:
                                        initial_state_for_npc['faction_id'] = None
                                        initial_state_for_npc['faction_details_list'] = None # Or [] if preferred for JSONB

                                    # Remove the original Pydantic model list from the state dict being passed to NpcManager
                                    initial_state_for_npc.pop('faction_affiliations', None)


                                    logger.info(f"Attempting to spawn NPC with template_id '{npc_profile_data.template_id}' in location '{persisted_location_id}' for PG ID {record.id}")
                                    created_npc = await self.game_manager.npc_manager.spawn_npc_in_location(
                                        guild_id=guild_id,
                                        location_id=persisted_location_id,
                                        npc_template_id=npc_profile_data.template_id,
                                        is_temporary=False, # Assuming persistent NPCs from location generation
                                        initial_state=initial_state_for_npc,
                                        session=session
                                    )

                                    if created_npc:
                                        newly_created_npc_ids.append(created_npc.id)
                                        logger.info(f"Successfully spawned NPC {created_npc.id} for PG ID {record.id}.")
                                    else:
                                        error_msg = f"Failed to spawn NPC with template_id '{npc_profile_data.template_id}' for PG ID {record.id}."
                                        logger.error(error_msg)
                                        application_success = False # Mark overall failure
                                        npc_persistence_failed_flag = True # Mark NPC specific failure
                                        # Update PendingGeneration status with this specific failure
                                        await self.pending_generation_crud.update_pending_generation_status(
                                            session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                                            moderator_user_id=moderator_user_id,
                                            moderator_notes=record.moderator_notes + f" | {error_msg}" if record.moderator_notes else error_msg
                                        )
                                        break # Stop processing further NPCs for this location

                                if npc_persistence_failed_flag:
                                    logger.error(f"NPC persistence failed for location {persisted_location_id}, PG ID {record.id}.")
                                elif application_success: # Check application_success again in case it was modified by other logic
                                    logger.info(f"Finished NPC persistence for location {persisted_location_id}. {len(newly_created_npc_ids)} NPCs processed/created for PG ID {record.id}.")
                                    if newly_created_npc_ids: # Only try to update if there are new IDs and previous steps were successful
                                        loc_for_npc_update = await session.get(Location, persisted_location_id)
                                        if loc_for_npc_update:
                                            if loc_for_npc_update.npc_ids is None:
                                                loc_for_npc_update.npc_ids = []

                                            for npc_id_to_add in newly_created_npc_ids:
                                                if npc_id_to_add not in loc_for_npc_update.npc_ids:
                                                    loc_for_npc_update.npc_ids.append(npc_id_to_add)

                                            flag_modified(loc_for_npc_update, "npc_ids")
                                            logger.info(f"Updated location {persisted_location_id} with new NPC IDs: {newly_created_npc_ids} for PG ID {record.id}")
                                        else:
                                            crit_error_msg = f"CRITICAL: Location {persisted_location_id} not found after successful merge, cannot update npc_ids for PG ID {record.id}."
                                            logger.critical(crit_error_msg)
                                            application_success = False
                                            await self.pending_generation_crud.update_pending_generation_status(
                                                session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                                                moderator_user_id=moderator_user_id,
                                                moderator_notes=record.moderator_notes + f" | {crit_error_msg}" if record.moderator_notes else crit_error_msg
                                            )
                            # --- NPC Persistence End ---

                            # --- Item Persistence Start ---
                            if application_success and ai_location_data.initial_items_json:
                                logger.info(f"Starting item persistence for location {persisted_location_id}, PG ID {record.id}.")
                                items_processed_successfully = True # Internal flag for this section
                                location_for_item_updates = await session.get(Location, persisted_location_id)

                                if not location_for_item_updates:
                                    crit_item_err_msg = f"CRITICAL: Location {persisted_location_id} not found before item processing for PG ID {record.id}."
                                    logger.critical(crit_item_err_msg)
                                    application_success = False # This is a critical failure
                                    await self.pending_generation_crud.update_pending_generation_status(
                                        session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                                        moderator_user_id=moderator_user_id,
                                        moderator_notes=record.moderator_notes + f" | {crit_item_err_msg}" if record.moderator_notes else crit_item_err_msg
                                    )
                                else:
                                    if location_for_item_updates.points_of_interest_json is None:
                                        location_for_item_updates.points_of_interest_json = []
                                    if location_for_item_updates.inventory is None:
                                        location_for_item_updates.inventory = {}

                                    items_changed_in_location = False

                                    for item_entry_dict in ai_location_data.initial_items_json:
                                        item_template_id = item_entry_dict.get("template_id")
                                        item_quantity = item_entry_dict.get("quantity", 1)
                                        target_poi_id = item_entry_dict.get("target_poi_id")

                                        if not item_template_id:
                                            logger.warning(f"Missing template_id in initial_items_json entry for PG ID {record.id}. Entry: {item_entry_dict}")
                                            continue

                                        if target_poi_id:
                                            # Create item instance
                                            created_item_instance = await self.game_manager.item_manager.create_item_instance(
                                                guild_id=guild_id,
                                                template_id=item_template_id,
                                                quantity=item_quantity,
                                                location_id=persisted_location_id,
                                                owner_type="location",
                                                owner_id=persisted_location_id,
                                                initial_state={"is_in_poi_id": target_poi_id},
                                                session=session
                                            )

                                            if created_item_instance and created_item_instance.id:
                                                poi_found_for_item = False
                                                for poi_dict in location_for_item_updates.points_of_interest_json:
                                                    if poi_dict.get("poi_id") == target_poi_id:
                                                        poi_found_for_item = True
                                                        poi_dict.setdefault("contained_item_instance_ids", [])
                                                        if created_item_instance.id not in poi_dict["contained_item_instance_ids"]:
                                                            poi_dict["contained_item_instance_ids"].append(created_item_instance.id)
                                                            items_changed_in_location = True
                                                            logger.info(f"Created item instance '{created_item_instance.id}' (template: '{item_template_id}') and added to POI '{target_poi_id}' in location '{persisted_location_id}' for PG ID {record.id}.")
                                                        # Optionally, remove from old template ID list if migrating:
                                                        # if "contained_item_ids" in poi_dict and item_template_id in poi_dict["contained_item_ids"]:
                                                        #     poi_dict["contained_item_ids"].remove(item_template_id)
                                                        #     items_changed_in_location = True # Ensure flag is set
                                                        break
                                                if not poi_found_for_item:
                                                    logger.warning(f"Target POI ID '{target_poi_id}' for item instance '{created_item_instance.id}' (template: '{item_template_id}') not found in location '{persisted_location_id}' (PG ID {record.id}). Item instance created but not linked to a specific POI's new list.")
                                            else:
                                                item_err_msg = f"Failed to create item instance for template '{item_template_id}' in POI '{target_poi_id}' for PG ID {record.id}."
                                                logger.error(item_err_msg)
                                                application_success = False
                                                items_processed_successfully = False
                                                await self.pending_generation_crud.update_pending_generation_status(
                                                    session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                                                    moderator_user_id=moderator_user_id,
                                                    moderator_notes=record.moderator_notes + f" | {item_err_msg}" if record.moderator_notes else item_err_msg
                                                )
                                                break # Stop item processing loop
                                        else:
                                            # General location loot - create item instance
                                            created_item_instance = await self.game_manager.item_manager.create_item_instance(
                                                guild_id=guild_id,
                                                template_id=item_template_id,
                                                quantity=item_quantity,
                                                location_id=persisted_location_id,
                                                owner_type="location",
                                                owner_id=persisted_location_id,
                                                session=session
                                            )
                                            if created_item_instance and created_item_instance.id:
                                                items_changed_in_location = True # An item instance was created for the location
                                                logger.info(f"Created general loot item instance '{created_item_instance.id}' (template: '{item_template_id}', qty: {item_quantity}) for location '{persisted_location_id}' for PG ID {record.id}.")
                                                # No longer adding to location_for_item_updates.inventory["initial_ai_loot"]
                                            else:
                                                item_err_msg = f"Failed to create general loot item instance for template '{item_template_id}' in location '{persisted_location_id}' for PG ID {record.id}."
                                                logger.error(item_err_msg)
                                                application_success = False
                                                items_processed_successfully = False # Ensure this local flag is also set
                                                await self.pending_generation_crud.update_pending_generation_status(
                                                    session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                                                    moderator_user_id=moderator_user_id,
                                                    moderator_notes=record.moderator_notes + f" | {item_err_msg}" if record.moderator_notes else item_err_msg
                                                )
                                                break # Stop item processing loop

                                    if items_changed_in_location: # This flag now also covers successful general loot creation
                                        flag_modified(location_for_item_updates, "points_of_interest_json") # Keep this if PoIs could have been modified
                                        flag_modified(location_for_item_updates, "inventory") # Keep this, as other logic might still use/modify inventory JSON directly, or future state might.
                                        # session.add(location_for_item_updates) # Will be part of the transaction, merge handles it.
                                        logger.info(f"Marked points_of_interest_json and/or inventory as modified for location {persisted_location_id} (PG ID {record.id}) due to item instance changes.")
                                    logger.info(f"Finished item persistence for location {persisted_location_id}, PG ID {record.id}. Items changed in DB: {items_changed_in_location}.")

                                # If decided that certain item processing errors should fail the application:
                                if not items_processed_successfully: # Check local flag in case of break from loop
                                    pass
                                #     application_success = False
                                #     # Ensure PendingGeneration notes are updated if needed
                            # --- Item Persistence End ---

                        except Exception as e_merge:
                            logger.error(f"Failed to merge location {location_id_to_use} (PG ID {record.id}): {e_merge}", exc_info=True)
                            application_success = False
                            # Update status with specific error for this stage
                            await self.pending_generation_crud.update_pending_generation_status(
                                session, record.id, PendingStatus.APPLICATION_FAILED, guild_id,
                                moderator_user_id=moderator_user_id,
                                moderator_notes=record.moderator_notes + f" | DB merge failed: {str(e_merge)[:100]}" if record.moderator_notes else f"DB merge failed: {str(e_merge)[:100]}"
                            )
                            return False # Stop processing this record

                    else: # This else corresponds to `if ai_location_data:`
                        # This case should have been handled by the initial try-except for parsing
                        # but as a safeguard:
                        logger.error(f"ai_location_data was None after parsing attempt for PG ID {record.id}. This should not happen.")
                        application_success = False
                        # Status should have been set already by the parsing exception handler.

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

