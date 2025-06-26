from __future__ import annotations
import logging
import json
from typing import Optional, Dict, Any, TYPE_CHECKING, List
import uuid

from bot.database.models.world_related import Location
from bot.ai.ai_data_models import GeneratedLocationContent, POIModel, ConnectionModel, GeneratedNpcProfile
from sqlalchemy.orm.attributes import flag_modified

from bot.models.pending_generation import PendingGeneration, GenerationType, PendingStatus
from bot.persistence.pending_generation_crud import PendingGenerationCRUD
from bot.database.guild_transaction import GuildTransaction
from sqlalchemy.future import select

import asyncio # For asyncio.create_task

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.game.managers.game_manager import GameManager
    from sqlalchemy.ext.asyncio import AsyncSession
    from bot.ai.ai_response_validator import parse_and_validate_ai_response # Ensure it's imported for runtime


logger = logging.getLogger(__name__)

class AIGenerationManager:
    def __init__(self,
                 db_service: "DBService",
                 prompt_context_collector: "PromptContextCollector",
                 multilingual_prompt_generator: "MultilingualPromptGenerator",
                 ai_response_validator: "AIResponseValidator",
                 game_manager: "GameManager"
                 ):
        self.db_service = db_service
        self.prompt_context_collector = prompt_context_collector
        self.multilingual_prompt_generator = multilingual_prompt_generator
        self.ai_response_validator = ai_response_validator
        self.game_manager = game_manager
        self.pending_generation_crud = PendingGenerationCRUD(db_service)
        logger.info("AIGenerationManager initialized.")

    async def request_content_generation(
        self,
        guild_id: str,
        request_type: GenerationType,
        context_params: Dict[str, Any], # Parameters for context collection
        prompt_params: Dict[str, Any],  # Parameters for prompt generation (like target_languages)
        created_by_user_id: Optional[str] = None,
        session: Optional["AsyncSession"] = None
    ) -> Optional[PendingGeneration]:
        logger.info(f"AIGenerationManager: Requesting '{request_type.value}' generation for guild {guild_id} by user {created_by_user_id}. Context: {context_params}, Prompt: {prompt_params}")

        # Prepare context for the prompt generator
        # Updated to correctly pass parameters for context collection.
        # Assuming context_params contains all necessary named arguments for get_full_context.
        generation_context_params = {
            "guild_id": guild_id,
            "character_id": context_params.get("character_id"),
            "location_id": context_params.get("location_id"),
            "npc_id": context_params.get("npc_id"),
            "item_id": context_params.get("item_id"),
            "quest_id": context_params.get("quest_id"),
            "faction_id": context_params.get("faction_id"),
            "event_id": context_params.get("event_id"),
            "dialogue_history": context_params.get("dialogue_history"),
            "recent_events": context_params.get("recent_events"),
            "additional_notes": context_params.get("additional_notes")
        }
        # Filter out None values to avoid passing them as keyword arguments
        generation_context_params = {k: v for k, v in generation_context_params.items() if v is not None}
        generation_context = await self.prompt_context_collector.get_full_context(**generation_context_params)


        target_languages_input = prompt_params.get("target_languages") # This is from prompt_params now
        target_languages_list: List[str] = []

        # Robust language list creation
        if isinstance(target_languages_input, list):
            target_languages_list = [str(lang).strip() for lang in target_languages_input if lang and isinstance(lang, (str, int, float)) and str(lang).strip()]
        elif isinstance(target_languages_input, str):
            target_languages_list = [lang.strip() for lang in target_languages_input.split(',') if lang.strip()]

        if not target_languages_list: # If still empty, determine default
            default_lang = "en"
            if self.game_manager and hasattr(self.game_manager, 'get_rule') and callable(getattr(self.game_manager, 'get_rule')):
                get_rule_method = getattr(self.game_manager, 'get_rule')
                lang_rule_val = await get_rule_method(guild_id, "default_language", "en")
                default_lang = lang_rule_val if lang_rule_val and isinstance(lang_rule_val, str) else "en"
            target_languages_list = [default_lang]
            if "en" not in target_languages_list: # Ensure English is always an option if not primary
                target_languages_list.append("en")

        target_languages_list = sorted(list(set(target_languages_list))) # Unique and sorted

        # Prepare prompt parameters, ensuring correct types and defaults
        # Ensure all keys used here are expected by `prepare_ai_prompt` or handled within it.
        # `prepare_ai_prompt` is expected to take specific arguments like `guild_id`, `location_id`,
        # `specific_task_instruction`, etc., and an `additional_request_params` dict for other data.

        # Extract known parameters for prepare_ai_prompt
        location_id_for_prompt = str(context_params.get("location_id")) if context_params.get("location_id") else \
                                 str(generation_context.get("location", {}).get("id")) if generation_context.get("location") else "default_world_space" # type: ignore[union-attr]

        specific_task_instruction = f"Generate content for type: {request_type.value}." # Basic instruction
        if "specific_task_instruction" in prompt_params:
            specific_task_instruction = str(prompt_params["specific_task_instruction"])

        # Consolidate all other prompt_params and relevant context into additional_request_params
        additional_request_params_for_prompt: Dict[str, Any] = {
            "target_character_id": str(prompt_params.get("target_character_id")) if prompt_params.get("target_character_id") else None,
            "target_languages": target_languages_list,
            "npc_profile_data": prompt_params.get("npc_profile_data"),
            "location_data": prompt_params.get("location_data"), # This might be redundant if location_id is primary
            "item_data": prompt_params.get("item_data"),
            "quest_data": prompt_params.get("quest_data"),
            "event_data": prompt_params.get("event_data"),
            "faction_data": prompt_params.get("faction_data"),
            "dialogue_config": prompt_params.get("dialogue_config"),
            "relationship_data": prompt_params.get("relationship_data"),
            "narrative_goal": prompt_params.get("narrative_goal"),
            "output_format_instructions": prompt_params.get("output_format_instructions"),
            "example_outputs": prompt_params.get("example_outputs"),
            "generation_constraints": prompt_params.get("generation_constraints"),
            "style_tone_guidelines": prompt_params.get("style_tone_guidelines"),
            "custom_instructions": prompt_params.get("custom_instructions"),
            "_full_generation_context": generation_context, # Pass the collected context
            "_original_prompt_params": {k: v for k, v in prompt_params.items() if k not in ["target_character_id", "target_languages", "specific_task_instruction"]}
        }
        # Filter None values from the additional_request_params_for_prompt
        additional_request_params_for_prompt = {k: v for k, v in additional_request_params_for_prompt.items() if v is not None}


        # Call prepare_ai_prompt with its expected signature
        # Assuming prepare_ai_prompt takes these specific args and **kwargs for the rest
        final_prompt_str = await self.multilingual_prompt_generator.prepare_ai_prompt(
            guild_id=guild_id, # Passed through
            location_id=location_id_for_prompt,
            specific_task_instruction=specific_task_instruction,
            # Optional: player_id, party_id if available and needed by prepare_ai_prompt
            player_id=str(context_params.get("character_id")) if context_params.get("character_id") else None,
            # party_id=context_params.get("party_id"), # If available
            additional_request_params=additional_request_params_for_prompt
        )

        logger.info(f"AIGenerationManager: Using placeholder AI response for '{request_type.value}'.")
        raw_ai_output_text = ""
        if request_type == GenerationType.LOCATION_DETAILS:
            raw_ai_output_text = json.dumps({
                "template_id": "generic_forest_clearing_template",
                "name_i18n": {"en": "Sun-dappled Clearing", "ru": "Солнечная Поляна"},
                "atmospheric_description_i18n": {"en": "A quiet clearing bathed in sunlight.", "ru": "Тихая поляна, залитая солнечным светом."},
                "points_of_interest": [{"poi_id": "old_oak_tree", "name_i18n": {"en": "Old Oak Tree", "ru": "Старый Дуб"}, "description_i18n": {"en": "A massive, ancient oak stands here.", "ru": "Здесь стоит массивный древний дуб."}}],
                "connections": [{"to_location_id": "forest_path_west", "direction_i18n": {"en": "West", "ru": "Запад"}, "description_i18n": {"en": "A path leads west.", "ru": "Тропа ведет на запад."}}]
            })
        else:
             raw_ai_output_text = json.dumps({"name_i18n": {"en": "Generated Name", "ru": "Сгенерированное Имя"}, "description_i18n": {"en": "Generated description.", "ru": "Сгенерированное описание."}})


        parsed_data, validation_issues_list = await parse_and_validate_ai_response(
            raw_ai_output_text=raw_ai_output_text, guild_id=guild_id,
            request_type=request_type,
            game_manager=self.game_manager
        )
        validation_issues_for_db: Optional[List[Dict[str,Any]]] = None
        if validation_issues_list:
            validation_issues_for_db = [issue.model_dump() for issue in validation_issues_list]


        current_status = PendingStatus.PENDING_MODERATION
        if validation_issues_for_db:
            current_status = PendingStatus.FAILED_VALIDATION
            logger.warning(f"AIGenerationManager: Validation issues for '{request_type.value}' in guild {guild_id}: {validation_issues_for_db}")

        pending_generation_record: Optional[PendingGeneration] = None
        session_to_use: Optional[AsyncSession] = session

        async def create_record_internal(current_session_internal: AsyncSession):
            nonlocal pending_generation_record

            # Ensure request_params_json and parsed_data_json are serializable to JSON
            # context_params is already Dict[str, Any]
            # parsed_data can be Dict or List, ensure it's JSON serializable.
            # If parsed_data is a Pydantic model, .model_dump() would be appropriate before storing.
            # For this example, assuming parsed_data is already a JSON-serializable dict/list.

            pending_generation_record = await self.pending_generation_crud.create_pending_generation(
                session=current_session_internal, guild_id=guild_id, request_type=request_type, status=current_status,
                request_params_json=context_params, # context_params is used here
                raw_ai_output_text=raw_ai_output_text,
                parsed_data_json=parsed_data, # This should be a JSON serializable dict or list
                validation_issues_json=validation_issues_for_db,
                created_by_user_id=str(created_by_user_id) if created_by_user_id else None
            )
            return pending_generation_record


        if session_to_use:
            try:
                await create_record_internal(session_to_use)
            except Exception as e:
                 logger.error(f"AIGenerationManager: Failed to create PendingGeneration record (with passed session) for '{request_type.value}' in guild {guild_id}: {e}", exc_info=True)
                 return None
        else:
            try:
                session_factory_input: Any = getattr(self.db_service, 'get_session_factory', None)
                if not callable(session_factory_input):
                    logger.error("DBService does not have a callable 'get_session_factory' method.")
                    return None
                async with GuildTransaction(session_factory_input, guild_id) as new_session_ctx: # type: ignore[arg-type]
                    await create_record_internal(new_session_ctx)
            except Exception as e:
                logger.exception(f"AIGenerationManager: Failed to create PendingGeneration record (new session) for '{request_type.value}' in guild {guild_id}")
                return None

        if pending_generation_record and hasattr(pending_generation_record, 'id') and pending_generation_record.id:
            logger.info(f"AIGenerationManager: PendingGeneration record {pending_generation_record.id} created for '{request_type.value}' in guild {guild_id}.")

            notification_service = getattr(self.game_manager, 'notification_service', None)
            send_notification_method = getattr(notification_service, 'send_notification', None) if notification_service else None

            if current_status == PendingStatus.PENDING_MODERATION and callable(send_notification_method):
                guild_config_result = None
                db_service_gm = getattr(self.game_manager, 'db_service', None)
                # Ensure models and get_entity_by_pk are correctly accessed
                if db_service_gm and hasattr(db_service_gm, 'get_entity_by_pk') and callable(db_service_gm.get_entity_by_pk): # type: ignore[attr-defined]
                    # Assuming GuildConfig model path is known or can be imported
                    from bot.database.models.guild_config import GuildConfig # Local import if not already available
                    guild_config_result = await db_service_gm.get_entity_by_pk(GuildConfig, guild_id) # type: ignore[attr-defined]


                if guild_config_result:
                    guild_config = guild_config_result # Already GuildConfig instance
                    notification_channel_id_val = getattr(guild_config, "notification_channel_id", None) or \
                                                getattr(guild_config, "master_channel_id", None) or \
                                                getattr(guild_config, "system_channel_id", None)
                    if notification_channel_id_val:
                        msg = f"🔔 New AI Content (Type: '{request_type.value}', ID: `{pending_generation_record.id}`) is awaiting moderation."
                        try:
                            await send_notification_method(int(str(notification_channel_id_val)), msg)
                        except ValueError:
                            logger.error(f"Invalid notification_channel_id format: {notification_channel_id_val} for PG {pending_generation_record.id}")
                        except Exception as e_notify:
                            logger.exception(f"Failed to send notification for PG {pending_generation_record.id}")
            elif current_status == PendingStatus.PENDING_MODERATION:
                 logger.warning(f"NotificationService or its send_notification method not available for PG {getattr(pending_generation_record, 'id', 'UNKNOWN_ID')}.")
        else:
            logger.error(f"AIGenerationManager: PendingGeneration record creation returned None or no ID for '{request_type.value}' in guild {guild_id}.")
            return None

        return pending_generation_record

    async def request_location_generation(
        self, guild_id: str, context_params: Dict[str, Any],
        prompt_params: Dict[str, Any], created_by_user_id: Optional[str] = None,
        session: Optional["AsyncSession"] = None
    ) -> Optional[PendingGeneration]:
        return await self.request_content_generation(
            guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS,
            context_params=context_params, prompt_params=prompt_params,
            created_by_user_id=str(created_by_user_id) if created_by_user_id else None,
            session=session
        )

    async def process_approved_generation(
        self, pending_generation_id: str, guild_id: str, moderator_user_id: str
    ) -> bool:
        logger.info(f"AIGenerationManager: Processing approved generation ID {pending_generation_id} for guild {guild_id} by moderator {moderator_user_id}.")
        try:
            session_factory_input: Any = getattr(self.db_service, 'get_session_factory', None)
            if not callable(session_factory_input):
                logger.error("DBService does not have a callable 'get_session_factory' method for process_approved_generation.")
                return False

            async with GuildTransaction(session_factory_input, guild_id) as session: # type: ignore[arg-type]
                record = await self.pending_generation_crud.get_pending_generation_by_id(session, pending_generation_id, guild_id)
                if not record or not hasattr(record, 'id'):
                    logger.error(f"PendingGeneration record {pending_generation_id} not found or invalid for guild {guild_id}."); return False

                record_id_str = str(record.id)

                record_status_val = record.status # Direct access after check
                if record_status_val != PendingStatus.APPROVED.value:
                    logger.warning(f"Attempted to process {record_id_str} not in APPROVED status (current: {record_status_val})."); return False

                record_parsed_data_json = record.parsed_data_json # Direct access
                if not record_parsed_data_json:
                    logger.error(f"No parsed_data_json for approved generation {record_id_str}.");
                    await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, parsed_data_json="No parsed data.") # Pass as kwarg
                    return False

                request_type_val_str = record.request_type # Direct access
                request_type_val: Optional[GenerationType] = None
                if isinstance(request_type_val_str, str): # Should be Enum from model
                    try: request_type_val = GenerationType[request_type_val_str.upper()]
                    except KeyError: pass
                elif isinstance(request_type_val_str, GenerationType):
                    request_type_val = request_type_val_str


                if not request_type_val:
                    logger.error(f"Invalid or missing request_type '{request_type_val_str}' for PG {record_id_str}.");
                    await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, validation_issues_json=[{"error": "Invalid request type."}]); return False # Pass as kwarg

                parsed_data = record_parsed_data_json; application_success = False; persisted_location_id: Optional[str] = None

                if request_type_val == GenerationType.LOCATION_DETAILS:
                    ai_location_data: Optional[GeneratedLocationContent] = None
                    if isinstance(parsed_data, dict):
                        try:
                            ai_location_data = GeneratedLocationContent(**parsed_data)
                        except Exception as e:
                            logger.exception(f"Failed to parse LOCATION_DETAILS for {record_id_str}")
                            await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, parsed_data_json={"error": f"Parse AI data error: {str(e)[:100]}"}); return False # Pass as kwarg
                    else:
                        logger.error(f"parsed_data for LOCATION_DETAILS {record_id_str} is not a dict.")
                        await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, parsed_data_json={"error": "Parsed data not a dict."}); return False # Pass as kwarg


                    if ai_location_data:
                        loc_to_persist: Optional[Location] = None; existing_loc: Optional[Location] = None
                        loc_static_id = ai_location_data.static_id
                        if loc_static_id and isinstance(loc_static_id, str):
                            stmt = select(Location).filter_by(guild_id=guild_id, static_id=loc_static_id)
                            existing_loc_result = await session.execute(stmt)
                            existing_loc = existing_loc_result.scalars().first()

                        if existing_loc:
                            loc_to_persist = existing_loc
                            logger.info(f"Updating existing location {loc_to_persist.id} with static_id {loc_static_id}")
                        else:
                            loc_to_persist = Location(guild_id=guild_id, id=str(uuid.uuid4()), static_id=str(loc_static_id) if loc_static_id else None)
                            logger.info(f"Creating new location {loc_to_persist.id}")

                        loc_to_persist.name_i18n = ai_location_data.name_i18n # type: ignore[assignment]
                        loc_to_persist.descriptions_i18n = ai_location_data.atmospheric_description_i18n # type: ignore[assignment]
                        loc_to_persist.template_id = str(ai_location_data.template_id) if ai_location_data.template_id else None

                        type_key = ai_location_data.location_type_key if isinstance(ai_location_data.location_type_key, str) else "unknown"
                        type_i18n_map = await self.game_manager.get_location_type_i18n_map(guild_id, type_key) if self.game_manager else {}
                        loc_to_persist.type_i18n = type_i18n_map if type_i18n_map and isinstance(type_i18n_map, dict) else {"en": type_key.replace("_", " ").title()} # type: ignore[assignment]

                        loc_to_persist.coordinates = ai_location_data.coordinates_json # type: ignore[assignment]
                        loc_to_persist.details_i18n = ai_location_data.generated_details_json # type: ignore[assignment]
                        loc_to_persist.ai_metadata_json = ai_location_data.ai_metadata_json # type: ignore[assignment]


                        pois_list = ai_location_data.points_of_interest if isinstance(ai_location_data.points_of_interest, list) else []
                        loc_to_persist.points_of_interest_json = [poi.model_dump() for poi in pois_list if isinstance(poi, POIModel) and hasattr(poi, 'model_dump')] # type: ignore[assignment]

                        conns_list = ai_location_data.connections if isinstance(ai_location_data.connections, list) else []
                        loc_to_persist.neighbor_locations_json = [conn.model_dump() for conn in conns_list if isinstance(conn, ConnectionModel) and hasattr(conn, 'model_dump')] # type: ignore[assignment]

                        flag_modified(loc_to_persist, "name_i18n")
                        flag_modified(loc_to_persist, "descriptions_i18n")
                        flag_modified(loc_to_persist, "type_i18n")
                        flag_modified(loc_to_persist, "coordinates")
                        flag_modified(loc_to_persist, "details_i18n")
                        flag_modified(loc_to_persist, "ai_metadata_json")
                        flag_modified(loc_to_persist, "points_of_interest_json")
                        flag_modified(loc_to_persist, "neighbor_locations_json")


                        try:
                            session.add(loc_to_persist)
                            await session.flush()
                            loc_id_after_flush = loc_to_persist.id # id should be populated after add/flush
                            if loc_id_after_flush is not None:
                                record.entity_id = str(loc_id_after_flush)
                                flag_modified(record, "entity_id")
                                persisted_location_id = str(loc_id_after_flush)
                                application_success = True
                                logger.info(f"Merged location {persisted_location_id} for PG ID {record_id_str}.")

                                created_by_user_id_val = record.created_by_user_id
                                location_interaction_service = getattr(self.game_manager, 'location_interaction_service', None)
                                if created_by_user_id_val and location_interaction_service and \
                                   hasattr(location_interaction_service, 'process_on_enter_location_events') and \
                                   callable(location_interaction_service.process_on_enter_location_events) and \
                                   persisted_location_id:
                                    req_params_val = record.request_params_json
                                    trig_char_id = req_params_val.get("triggering_character_id") if isinstance(req_params_val, dict) else None
                                    if trig_char_id and isinstance(trig_char_id, str):
                                        asyncio.create_task(location_interaction_service.process_on_enter_location_events(guild_id, trig_char_id, "Character", persisted_location_id))
                            else:
                                logger.error(f"Location ID is None after flush for PG ID {record_id_str}.")
                                application_success = False

                        except Exception as e_merge:
                            logger.exception(f"Failed to merge location {getattr(loc_to_persist, 'id', 'UNKNOWN_ID_ON_ERROR')}")
                            application_success = False
                            await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, parsed_data_json={"error": f"DB merge fail: {str(e_merge)[:100]}"}); return False # Pass as kwarg

                        if application_success and persisted_location_id and isinstance(ai_location_data.connections, list):
                            new_loc_name_i18n = loc_to_persist.name_i18n if isinstance(loc_to_persist.name_i18n, dict) else {"en": "Newly discovered area"}
                            for conn_data in ai_location_data.connections:
                                if not isinstance(conn_data, ConnectionModel): continue
                                neighbor_id = conn_data.to_location_id
                                if not neighbor_id or str(neighbor_id) == persisted_location_id: continue
                                neighbor_loc_res = await session.get(Location, str(neighbor_id))
                                if neighbor_loc_res and str(neighbor_loc_res.guild_id) == guild_id:
                                    neighbor_loc: Location = neighbor_loc_res
                                    current_neighbors_val = neighbor_loc.neighbor_locations_json
                                    current_neighbors_list: List[Dict[str,Any]] = current_neighbors_val if isinstance(current_neighbors_val, list) else []
                                    if not any(isinstance(c, dict) and c.get("to_location_id") == persisted_location_id for c in current_neighbors_list):
                                        recip_dir_i18n = {lang: f"Towards {new_loc_name_i18n.get(lang, 'area')}" for lang in (conn_data.direction_i18n or {}).keys()} or {"en": f"Towards {new_loc_name_i18n.get('en','area')}"}
                                        current_neighbors_list.append({"to_location_id": persisted_location_id, "direction_i18n": recip_dir_i18n, "path_description_i18n": conn_data.description_i18n or {}})
                                        neighbor_loc.neighbor_locations_json = current_neighbors_list # type: ignore[assignment]
                                        flag_modified(neighbor_loc, "neighbor_locations_json"); logger.info(f"Added reciprocal link from {neighbor_id} to {persisted_location_id}.")

                        initial_npcs_json_val = ai_location_data.initial_npcs_json if hasattr(ai_location_data, 'initial_npcs_json') else None
                        if application_success and persisted_location_id and isinstance(initial_npcs_json_val, list) and \
                           self.game_manager and self.game_manager.npc_manager and \
                           hasattr(self.game_manager.npc_manager, 'spawn_npc_in_location') and callable(self.game_manager.npc_manager.spawn_npc_in_location): # type: ignore[attr-defined]
                            new_npc_ids: List[str] = []
                            for npc_prof_data_any in initial_npcs_json_val:
                                if not isinstance(npc_prof_data_any, GeneratedNpcProfile): continue
                                npc_prof_data: GeneratedNpcProfile = npc_prof_data_any
                                npc_state = npc_prof_data.model_dump(); npc_state['skills_data'] = npc_state.pop('skills', None); npc_state['abilities_data'] = npc_state.pop('abilities', None)
                                if npc_prof_data.faction_affiliations and isinstance(npc_prof_data.faction_affiliations, list) and len(npc_prof_data.faction_affiliations) > 0:
                                     npc_state['faction_id'] = str(npc_prof_data.faction_affiliations[0].faction_id) if hasattr(npc_prof_data.faction_affiliations[0], 'faction_id') else None
                                     npc_state['faction_details_list'] = [aff.model_dump() for aff in npc_prof_data.faction_affiliations if hasattr(aff, 'model_dump')]
                                npc_state.pop('faction_affiliations', None)
                                npc_template_id_str = str(npc_prof_data.template_id) if npc_prof_data.template_id else "unknown_npc_template"
                                created_npc = await self.game_manager.npc_manager.spawn_npc_in_location(guild_id, persisted_location_id, npc_template_id_str, False, npc_state, session) # type: ignore[attr-defined]
                                if created_npc and hasattr(created_npc, 'id') and created_npc.id: new_npc_ids.append(str(created_npc.id))
                                else: application_success = False; logger.error(f"Failed to spawn NPC {npc_template_id_str} for PG {record_id_str}."); await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, parsed_data_json={"error": "NPC spawn fail."}); break # Pass as kwarg
                            if application_success and new_npc_ids:
                                loc_for_npc_update_res = await session.get(Location, persisted_location_id)
                                if loc_for_npc_update_res:
                                    loc_for_npc_update: Location = loc_for_npc_update_res
                                    current_npc_ids_val = loc_for_npc_update.npc_ids
                                    current_npc_ids_list_val: List[str] = current_npc_ids_val if isinstance(current_npc_ids_val, list) else []
                                    for nid_str in new_npc_ids:
                                        if nid_str not in current_npc_ids_list_val: current_npc_ids_list_val.append(nid_str)
                                    loc_for_npc_update.npc_ids = current_npc_ids_list_val # type: ignore[assignment]
                                    flag_modified(loc_for_npc_update, "npc_ids")
                                elif not loc_for_npc_update_res : application_success = False; logger.critical(f"Location {persisted_location_id} vanished before NPC ID update for PG {record_id_str}.")

                        initial_items_json_val = ai_location_data.initial_items_json if hasattr(ai_location_data, 'initial_items_json') else None
                        if application_success and persisted_location_id and isinstance(initial_items_json_val, list) and \
                           self.game_manager and self.game_manager.item_manager and \
                           hasattr(self.game_manager.item_manager, 'create_item_instance') and callable(self.game_manager.item_manager.create_item_instance): # type: ignore[attr-defined]
                            loc_for_item_updates_res = await session.get(Location, persisted_location_id)
                            if not loc_for_item_updates_res: application_success = False; logger.critical(f"Location {persisted_location_id} vanished for item add for PG {record_id_str}.")
                            else:
                                loc_for_item_updates: Location = loc_for_item_updates_res
                                items_changed_loc = False
                                for item_entry in initial_items_json_val:
                                    if not isinstance(item_entry, dict): continue
                                    item_tpl_id_any = item_entry.get("template_id"); item_qty_any = item_entry.get("quantity",1.0); poi_id_any = item_entry.get("target_poi_id")
                                    if not item_tpl_id_any: continue
                                    item_tpl_id_str = str(item_tpl_id_any)
                                    item_qty_float = 1.0 # Default quantity
                                    try: item_qty_float = float(item_qty_any) if item_qty_any is not None else 1.0
                                    except (ValueError, TypeError): pass # Keep default if conversion fails
                                    poi_id_str = str(poi_id_any) if poi_id_any else None

                                    # Call create_item_instance with correct parameters
                                    # The owner_id is the location itself, and owner_type is "location"
                                    created_item = await self.game_manager.item_manager.create_item_instance( # type: ignore[attr-defined]
                                        guild_id=guild_id, template_id=item_tpl_id_str, quantity=item_qty_float,
                                        owner_id=persisted_location_id, owner_type="location",
                                        location_id=persisted_location_id, # Item is at the location
                                        state_variables={"is_in_poi_id": poi_id_str} if poi_id_str else None,
                                        db_session=session, is_temporary=False # Pass session, not temporary
                                    )
                                    if created_item and hasattr(created_item, 'id') and created_item.id and poi_id_str and isinstance(loc_for_item_updates.points_of_interest_json, list):
                                        for poi_dict in loc_for_item_updates.points_of_interest_json:
                                            if isinstance(poi_dict, dict) and str(poi_dict.get("poi_id")) == poi_id_str:
                                                # Ensure 'contained_item_instance_ids' is a list
                                                if not isinstance(poi_dict.get("contained_item_instance_ids"), list):
                                                    poi_dict["contained_item_instance_ids"] = []
                                                poi_dict["contained_item_instance_ids"].append(str(created_item.id))
                                                items_changed_loc = True; break
                                    elif created_item: items_changed_loc = True
                                    else: application_success = False; logger.error(f"Failed item spawn {item_tpl_id_str} for PG {record_id_str}."); await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, parsed_data_json={"error": "Item spawn fail."}); break # Pass as kwarg
                                if items_changed_loc and loc_for_item_updates:
                                    if loc_for_item_updates.points_of_interest_json is not None: flag_modified(loc_for_item_updates, "points_of_interest_json")
                                    if hasattr(loc_for_item_updates, 'inventory_json') and loc_for_item_updates.inventory_json is not None: flag_modified(loc_for_item_updates, "inventory_json") # Example if inventory is stored in 'inventory_json'
                    else: application_success = False; logger.error(f"ai_location_data was None for PG {record_id_str} after parsing.")

                elif request_type_val in [GenerationType.NPC_PROFILE, GenerationType.QUEST_FULL, GenerationType.ITEM_PROFILE]:
                    logger.info(f"AIGenerationManager: [SIMULATING PERSISTENCE] for {request_type_val.value} - PG ID {record_id_str}")
                    record.entity_id = f"simulated_{request_type_val.value.lower()}_{record_id_str[:8]}"
                    flag_modified(record, "entity_id")
                    application_success = True
                else:
                    logger.warning(f"No specific persistence logic for type '{request_type_val.value}' for PG {record_id_str}.")
                    application_success = False
                    await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, validation_issues_json=[{"error": f"No app logic for {request_type_val.value}."}]); return False # Pass as kwarg

                if application_success:
                    await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLIED, guild_id, moderator_user_id, moderator_notes=str(getattr(record, 'moderator_notes', None))) # Pass as kwarg
                    logger.info(f"Successfully processed and applied PG {pending_generation_id}. Status: APPLIED.")
                    return True
                else:
                    logger.error(f"Application of PG {pending_generation_id} (type: {request_type_val.value}) failed.")
                    record_status_val_after = record.status # Direct access
                    if record_status_val_after != PendingStatus.APPLICATION_FAILED.value:
                         await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, moderator_notes=(str(getattr(record, 'moderator_notes', None) or "")) + " | App persistence failed.") # Pass as kwarg
                    return False
        except Exception as e:
            logger.exception(f"Unexpected error in process_approved_generation for {pending_generation_id}")
            try:
                session_factory_input_err: Any = getattr(self.db_service, 'get_session_factory', None)
                if not callable(session_factory_input_err):
                    logger.error("DBService does not have a callable 'get_session_factory' method for error status update in exception block.")
                    return False
                async with GuildTransaction(session_factory_input_err, guild_id) as error_session: # type: ignore[arg-type]
                    await self.pending_generation_crud.update_pending_generation_status(error_session, pending_generation_id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, moderator_notes=f"App fail exception: {str(e)[:100]}") # Pass as kwarg
            except Exception as e_status: logger.exception(f"CRITICAL: Failed to update status to APPLICATION_FAILED for {pending_generation_id} after error")
            return False
