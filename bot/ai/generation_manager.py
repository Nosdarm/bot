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

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.game.managers.game_manager import GameManager
    from sqlalchemy.ext.asyncio import AsyncSession # For type hinting session


logger = logging.getLogger(__name__)

class AIGenerationManager:
    def __init__(self,
                 db_service: DBService,
                 prompt_context_collector: PromptContextCollector,
                 multilingual_prompt_generator: MultilingualPromptGenerator,
                 ai_response_validator: AIResponseValidator,
                 game_manager: GameManager
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
        context_params: Dict[str, Any],
        prompt_params: Dict[str, Any],
        created_by_user_id: Optional[str] = None,
        session: Optional[AsyncSession] = None # Allow passing an existing session
    ) -> Optional[PendingGeneration]:
        logger.info(f"AIGenerationManager: Requesting '{request_type.value}' generation for guild {guild_id} by user {created_by_user_id}. Context: {context_params}, Prompt: {prompt_params}")

        # Prepare context for prompt_context_collector.get_full_context
        # Explicitly pass known params and use **other_context_params for the rest
        known_context_keys = {"character_id", "target_entity_id", "target_entity_type", "location_id", "event_id"}
        collector_context_params = {k: v for k, v in context_params.items() if k in known_context_keys}
        other_context_params = {k: v for k, v in context_params.items() if k not in known_context_keys}

        generation_context = await self.prompt_context_collector.get_full_context(
            guild_id=guild_id,
            character_id=collector_context_params.get("character_id"),
            target_entity_id=collector_context_params.get("target_entity_id"),
            target_entity_type=collector_context_params.get("target_entity_type"),
            location_id=collector_context_params.get("location_id"),
            event_id=collector_context_params.get("event_id"),
            **other_context_params # Pass remaining context_params here
        )

        target_languages_input = prompt_params.get("target_languages")
        target_languages_list: List[str] = [] # Initialize as empty list
        if isinstance(target_languages_input, list):
            target_languages_list = [str(lang) for lang in target_languages_input if isinstance(lang, (str, int, float))] # Ensure elements are strings
        elif isinstance(target_languages_input, str):
            target_languages_list = [lang.strip() for lang in target_languages_input.split(',') if lang.strip()]

        if not target_languages_list:
            default_lang = "en"
            if self.game_manager and hasattr(self.game_manager, 'get_rule') and callable(getattr(self.game_manager, 'get_rule')):
                default_lang = await self.game_manager.get_rule(guild_id, "default_language", "en") or "en"
            target_languages_list = sorted(list(set([default_lang, "en"])))

        # Ensure all elements in target_languages_list are strings and sort
        target_languages_list = sorted([str(lang) for lang in target_languages_list if lang])


        # Prepare params for multilingual_prompt_generator.prepare_ai_prompt
        known_prompt_gen_keys = {"specific_task_instruction"} # Add other known direct params if any
        prompt_gen_specific_params = {k: v for k, v in prompt_params.items() if k in known_prompt_gen_keys}
        other_prompt_gen_params = {k: v for k, v in prompt_params.items() if k not in known_prompt_gen_keys}


        final_prompt_str = await self.multilingual_prompt_generator.prepare_ai_prompt(
            generation_type_str=request_type.value, # Renamed from generation_type
            context_data=generation_context, # Renamed from context
            target_character_id=context_params.get("character_id"), # Renamed from character_id
            target_languages=target_languages_list,
            specific_task_instruction=prompt_gen_specific_params.get("specific_task_instruction"),
            **other_prompt_gen_params # Pass remaining prompt_params here
        )

        logger.info(f"AIGenerationManager: Using placeholder AI response for '{request_type.value}'.")
        raw_ai_output = ""
        if request_type == GenerationType.LOCATION_DETAILS:
            raw_ai_output = json.dumps({
                "template_id": "generic_forest_clearing_template",
                "name_i18n": {"en": "Sun-dappled Clearing", "ru": "Солнечная Поляна"},
                "atmospheric_description_i18n": {"en": "A quiet clearing bathed in sunlight.", "ru": "Тихая поляна, залитая солнечным светом."},
                "points_of_interest": [{"poi_id": "old_oak_tree", "name_i18n": {"en": "Old Oak Tree", "ru": "Старый Дуб"}, "description_i18n": {"en": "A massive, ancient oak stands here.", "ru": "Здесь стоит массивный древний дуб."}}],
                "connections": [{"to_location_id": "forest_path_west", "direction_i18n": {"en": "West", "ru": "Запад"}, "description_i18n": {"en": "A path leads west.", "ru": "Тропа ведет на запад."}}]
            })
        else:
             raw_ai_output = json.dumps({"name_i18n": {"en": "Generated Name", "ru": "Сгенерированное Имя"}, "description_i18n": {"en": "Generated description.", "ru": "Сгенерированное описание."}})

        parsed_data, validation_issues = await self.ai_response_validator.parse_and_validate_ai_response(
            raw_ai_output_text=raw_ai_output, guild_id=guild_id,
            request_type=request_type.value, game_manager=self.game_manager
        )

        current_status = PendingStatus.PENDING_MODERATION
        if validation_issues:
            current_status = PendingStatus.FAILED_VALIDATION
            logger.warning(f"AIGenerationManager: Validation issues for '{request_type.value}' in guild {guild_id}: {validation_issues}")

        pending_generation_record = None

        async def create_record(current_session: AsyncSession):
            nonlocal pending_generation_record # Allow assignment to outer scope variable
            return await self.pending_generation_crud.create_pending_generation(
                session=current_session, guild_id=guild_id, request_type=request_type, status=current_status,
                request_params_json=context_params, raw_ai_output_text=raw_ai_output, parsed_data_json=parsed_data,
                validation_issues_json=[issue.model_dump() for issue in validation_issues] if validation_issues else None,
                created_by_user_id=created_by_user_id
            )

        if session: # Use passed session if available
            try:
                pending_generation_record = await create_record(session)
            except Exception as e:
                 logger.error(f"AIGenerationManager: Failed to create PendingGeneration record (with passed session) for '{request_type.value}' in guild {guild_id}: {e}", exc_info=True)
                 return None
        else: # Create a new transaction
            try:
                async with GuildTransaction(self.db_service.get_session_factory, guild_id) as new_session:
                    pending_generation_record = await create_record(new_session)
            except Exception as e:
                logger.error(f"AIGenerationManager: Failed to create PendingGeneration record (new session) for '{request_type.value}' in guild {guild_id}: {e}", exc_info=True)
                return None

        if pending_generation_record and pending_generation_record.id :
            logger.info(f"AIGenerationManager: PendingGeneration record {pending_generation_record.id} created for '{request_type.value}' in guild {guild_id}.")
            if current_status == PendingStatus.PENDING_MODERATION and self.game_manager and self.game_manager.notification_service and hasattr(self.game_manager.notification_service, 'send_notification') and callable(getattr(self.game_manager.notification_service, 'send_notification')):
                 guild_config_result = None
                 if self.game_manager.db_service and hasattr(self.game_manager.db_service, 'models') and hasattr(self.game_manager.db_service.models, 'GuildConfig') and hasattr(self.game_manager.db_service, 'get_entity_by_pk') and callable(getattr(self.game_manager.db_service, 'get_entity_by_pk')):
                    guild_config_result = await self.game_manager.db_service.get_entity_by_pk(self.game_manager.db_service.models.GuildConfig, guild_id)

                 if guild_config_result:
                    guild_config = guild_config_result
                    notification_channel_id_val = getattr(guild_config, "notification_channel_id", None) or \
                                                getattr(guild_config, "master_channel_id", None) or \
                                                getattr(guild_config, "system_channel_id", None)
                    if notification_channel_id_val:
                        msg = f"🔔 New AI Content (Type: '{request_type.value}', ID: `{pending_generation_record.id}`) is awaiting moderation."
                        try:
                            await self.game_manager.notification_service.send_notification(int(notification_channel_id_val), msg)
                        except ValueError:
                            logger.error(f"Invalid notification_channel_id format: {notification_channel_id_val}")
                        except Exception as e_notify:
                            logger.error(f"Failed to send notification for PG {pending_generation_record.id}: {e_notify}")
            elif current_status == PendingStatus.PENDING_MODERATION:
                 logger.warning(f"NotificationService or its send_notification method not available for PG {pending_generation_record.id}.")

        else:
            logger.error(f"AIGenerationManager: PendingGeneration record creation returned None or no ID for '{request_type.value}' in guild {guild_id}.")
            return None


        return pending_generation_record

    async def request_location_generation(
        self, guild_id: str, context_params: Dict[str, Any],
        prompt_params: Dict[str, Any], created_by_user_id: Optional[str] = None,
        session: Optional[AsyncSession] = None
    ) -> Optional[PendingGeneration]:
        return await self.request_content_generation(
            guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS,
            context_params=context_params, prompt_params=prompt_params,
            created_by_user_id=created_by_user_id, session=session
        )

    async def process_approved_generation(
        self, pending_generation_id: str, guild_id: str, moderator_user_id: str
    ) -> bool:
        logger.info(f"AIGenerationManager: Processing approved generation ID {pending_generation_id} for guild {guild_id} by moderator {moderator_user_id}.")
        try:
            async with GuildTransaction(self.db_service.get_session_factory, guild_id) as session:
                record = await self.pending_generation_crud.get_pending_generation_by_id(session, pending_generation_id, guild_id)
                if not record:
                    logger.error(f"PendingGeneration record {pending_generation_id} not found for guild {guild_id}."); return False
                if record.status != PendingStatus.APPROVED:
                    logger.warning(f"Attempted to process {pending_generation_id} not in APPROVED status (current: {record.status.value})."); return False
                if not record.parsed_data_json:
                    logger.error(f"No parsed_data_json for approved generation {pending_generation_id}.");
                    await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, "No parsed data.") # type: ignore[arg-type]
                    return False

                request_type = record.request_type; parsed_data = record.parsed_data_json; application_success = False; persisted_location_id: Optional[str] = None

                if request_type == GenerationType.LOCATION_DETAILS:
                    ai_location_data: Optional[GeneratedLocationContent] = None
                    if isinstance(parsed_data, dict):
                        try:
                            ai_location_data = GeneratedLocationContent(**parsed_data)
                        except Exception as e:
                            logger.error(f"Failed to parse LOCATION_DETAILS for {record.id}: {e}", exc_info=True)
                            await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, f"Parse AI data error: {str(e)[:100]}"); return False # type: ignore[arg-type]
                    else:
                        logger.error(f"parsed_data for LOCATION_DETAILS {record.id} is not a dict.")
                        await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, "Parsed data not a dict."); return False # type: ignore[arg-type]


                    if ai_location_data: # ai_location_data is now confirmed to be GeneratedLocationContent or None
                        loc_to_persist: Optional[Location] = None; existing_loc: Optional[Location] = None
                        if ai_location_data.static_id: # static_id is Optional[str]
                            stmt = select(Location).filter_by(guild_id=guild_id, static_id=ai_location_data.static_id)
                            existing_loc = (await session.execute(stmt)).scalars().first()

                        if existing_loc:
                            loc_to_persist = existing_loc
                            logger.info(f"Updating existing location {loc_to_persist.id} with static_id {ai_location_data.static_id}")
                        else:
                            loc_to_persist = Location(guild_id=guild_id, id=str(uuid.uuid4()), static_id=ai_location_data.static_id if ai_location_data.static_id else None)
                            logger.info(f"Creating new location {loc_to_persist.id}")

                        loc_to_persist.name_i18n = ai_location_data.name_i18n
                        loc_to_persist.descriptions_i18n = ai_location_data.atmospheric_description_i18n
                        loc_to_persist.template_id = ai_location_data.template_id

                        type_key = ai_location_data.location_type_key or "unknown" # Ensure type_key is not None
                        type_i18n_map = await self.game_manager.get_location_type_i18n_map(guild_id, type_key) if self.game_manager else {}
                        loc_to_persist.type_i18n = type_i18n_map if type_i18n_map and isinstance(type_i18n_map, dict) else {"en": type_key.replace("_", " ").title()}

                        loc_to_persist.coordinates = ai_location_data.coordinates_json
                        loc_to_persist.details_i18n = ai_location_data.generated_details_json
                        loc_to_persist.ai_metadata_json = ai_location_data.ai_metadata_json
                        loc_to_persist.points_of_interest_json = [poi.model_dump() for poi in ai_location_data.points_of_interest] if ai_location_data.points_of_interest else []
                        loc_to_persist.neighbor_locations_json = [conn.model_dump() for conn in ai_location_data.connections] if ai_location_data.connections else []

                        # Mark fields that are JSON for SQLAlchemy to detect changes if assigned in-place
                        if loc_to_persist.name_i18n is not None: flag_modified(loc_to_persist, "name_i18n")
                        if loc_to_persist.descriptions_i18n is not None: flag_modified(loc_to_persist, "descriptions_i18n")
                        if loc_to_persist.type_i18n is not None: flag_modified(loc_to_persist, "type_i18n")
                        if loc_to_persist.coordinates is not None: flag_modified(loc_to_persist, "coordinates")
                        if loc_to_persist.details_i18n is not None: flag_modified(loc_to_persist, "details_i18n")
                        if loc_to_persist.ai_metadata_json is not None: flag_modified(loc_to_persist, "ai_metadata_json")
                        if loc_to_persist.points_of_interest_json is not None: flag_modified(loc_to_persist, "points_of_interest_json")
                        if loc_to_persist.neighbor_locations_json is not None: flag_modified(loc_to_persist, "neighbor_locations_json")


                        try:
                            session.add(loc_to_persist) # Use add for both new and existing (merged by PK)
                            await session.flush()
                            if loc_to_persist.id is not None: # Check after flush
                                record.entity_id = str(loc_to_persist.id)
                                persisted_location_id = str(loc_to_persist.id)
                                application_success = True
                                logger.info(f"Merged location {persisted_location_id} for PG ID {record.id}.")
                                # Simplified on_enter_location trigger
                                if record.created_by_user_id and self.game_manager and self.game_manager.location_interaction_service and persisted_location_id:
                                    req_params = record.request_params_json if isinstance(record.request_params_json, dict) else {}
                                    trig_char_id = req_params.get("triggering_character_id")
                                    if trig_char_id and isinstance(trig_char_id, str): # Ensure trig_char_id is str
                                        import asyncio # Ensure asyncio is imported
                                        asyncio.create_task(self.game_manager.location_interaction_service.process_on_enter_location_events(guild_id, trig_char_id, "Character", persisted_location_id))
                            else: # Should not happen if flush was successful
                                logger.error(f"Location ID is None after flush for PG ID {record.id}.")
                                application_success = False

                        except Exception as e_merge:
                            logger.error(f"Failed to merge location {getattr(loc_to_persist, 'id', 'UNKNOWN_ID_ON_ERROR')}: {e_merge}", exc_info=True)
                            application_success = False
                            await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, f"DB merge fail: {str(e_merge)[:100]}"); return False # type: ignore[arg-type]

                        if application_success and persisted_location_id and ai_location_data.connections: # Update Neighbors
                            new_loc_name_i18n = loc_to_persist.name_i18n or {"en": "Newly discovered area"}
                            for conn_data in ai_location_data.connections:
                                if not isinstance(conn_data, ConnectionModel): continue
                                neighbor_id = conn_data.to_location_id
                                if not neighbor_id or neighbor_id == persisted_location_id: continue
                                neighbor_loc = await session.get(Location, neighbor_id)
                                if neighbor_loc and neighbor_loc.guild_id == guild_id:
                                    current_neighbors = neighbor_loc.neighbor_locations_json if isinstance(neighbor_loc.neighbor_locations_json, list) else []
                                    if not any(c.get("to_location_id") == persisted_location_id for c in current_neighbors):
                                        recip_dir_i18n = {lang: f"Towards {new_loc_name_i18n.get(lang, 'area')}" for lang in (conn_data.direction_i18n or {}).keys()} or {"en": f"Towards {new_loc_name_i18n.get('en','area')}"}
                                        current_neighbors.append({"to_location_id": persisted_location_id, "direction_i18n": recip_dir_i18n, "path_description_i18n": conn_data.description_i18n or {}})
                                        neighbor_loc.neighbor_locations_json = current_neighbors # Re-assign to trigger modification tracking
                                        flag_modified(neighbor_loc, "neighbor_locations_json"); logger.info(f"Added reciprocal link from {neighbor_id} to {persisted_location_id}.")

                        if application_success and persisted_location_id and ai_location_data.initial_npcs_json and self.game_manager and self.game_manager.npc_manager and hasattr(self.game_manager.npc_manager, 'spawn_npc_in_location') and callable(getattr(self.game_manager.npc_manager, 'spawn_npc_in_location')): # Spawn NPCs
                            new_npc_ids = []
                            for npc_prof_data in ai_location_data.initial_npcs_json:
                                if not isinstance(npc_prof_data, GeneratedNpcProfile): continue
                                npc_state = npc_prof_data.model_dump(); npc_state['skills_data'] = npc_state.pop('skills', None); npc_state['abilities_data'] = npc_state.pop('abilities', None)
                                if npc_prof_data.faction_affiliations: npc_state['faction_id'] = npc_prof_data.faction_affiliations[0].faction_id; npc_state['faction_details_list'] = [aff.model_dump() for aff in npc_prof_data.faction_affiliations]
                                npc_state.pop('faction_affiliations', None)
                                created_npc = await self.game_manager.npc_manager.spawn_npc_in_location(guild_id, persisted_location_id, npc_prof_data.template_id, False, npc_state, session)
                                if created_npc and created_npc.id: new_npc_ids.append(str(created_npc.id))
                                else: application_success = False; logger.error(f"Failed to spawn NPC {npc_prof_data.template_id} for PG {record.id}."); await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, "NPC spawn fail."); break # type: ignore[arg-type]
                            if application_success and new_npc_ids:
                                loc_for_npc_update = await session.get(Location, persisted_location_id)
                                if loc_for_npc_update:
                                    current_npc_ids = loc_for_npc_update.npc_ids if isinstance(loc_for_npc_update.npc_ids, list) else []
                                    for nid in new_npc_ids:
                                        if nid not in current_npc_ids: current_npc_ids.append(nid)
                                    loc_for_npc_update.npc_ids = current_npc_ids
                                    flag_modified(loc_for_npc_update, "npc_ids")
                                elif not loc_for_npc_update : application_success = False; logger.critical(f"Location {persisted_location_id} vanished before NPC ID update for PG {record.id}.")

                        if application_success and persisted_location_id and ai_location_data.initial_items_json and self.game_manager and self.game_manager.item_manager and hasattr(self.game_manager.item_manager, 'create_item_instance') and callable(getattr(self.game_manager.item_manager, 'create_item_instance')): # Add Items
                            loc_for_item_updates = await session.get(Location, persisted_location_id)
                            if not loc_for_item_updates: application_success = False; logger.critical(f"Location {persisted_location_id} vanished for item add for PG {record.id}.")
                            else:
                                items_changed_loc = False
                                for item_entry in ai_location_data.initial_items_json:
                                    item_tpl_id = item_entry.get("template_id"); item_qty = item_entry.get("quantity",1.0); poi_id = item_entry.get("target_poi_id")
                                    if not item_tpl_id: continue
                                    created_item = await self.game_manager.item_manager.create_item_instance(guild_id, item_tpl_id, item_qty, persisted_location_id, "location", persisted_location_id, {"is_in_poi_id": poi_id} if poi_id else None, session)
                                    if created_item and created_item.id and poi_id and isinstance(loc_for_item_updates.points_of_interest_json, list):
                                        for poi_dict in loc_for_item_updates.points_of_interest_json:
                                            if isinstance(poi_dict, dict) and poi_dict.get("poi_id") == poi_id:
                                                poi_dict.setdefault("contained_item_instance_ids", []).append(str(created_item.id))
                                                items_changed_loc = True; break
                                    elif created_item: items_changed_loc = True
                                    else: application_success = False; logger.error(f"Failed item spawn {item_tpl_id} for PG {record.id}."); await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id,"Item spawn fail."); break # type: ignore[arg-type]
                                if items_changed_loc and loc_for_item_updates:
                                    if loc_for_item_updates.points_of_interest_json is not None: flag_modified(loc_for_item_updates, "points_of_interest_json")
                                    if loc_for_item_updates.inventory is not None: flag_modified(loc_for_item_updates, "inventory") # Assuming items might also go to general location inventory
                    else: application_success = False; logger.error(f"ai_location_data was None for PG {record.id} after parsing.")

                elif request_type in [GenerationType.NPC_PROFILE, GenerationType.QUEST_FULL, GenerationType.ITEM_PROFILE]:
                    logger.info(f"AIGenerationManager: [SIMULATING PERSISTENCE] for {request_type.value} - PG ID {record.id}")
                    application_success = True # Placeholder
                else: # Unknown or unhandled type
                    logger.warning(f"No specific persistence logic for type '{request_type.value}' for PG {record.id}.")
                    application_success = False
                    await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, f"No app logic for {request_type.value}.") # type: ignore[arg-type]
                    return False

                if application_success:
                    await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLIED, guild_id, moderator_user_id, record.moderator_notes) # type: ignore[arg-type]
                    logger.info(f"Successfully processed and applied PG {pending_generation_id}. Status: APPLIED.")
                    return True
                else: # application_success is False
                    logger.error(f"Application of PG {pending_generation_id} (type: {request_type.value}) failed.")
                    if record.status != PendingStatus.APPLICATION_FAILED: # If not already set by a sub-process
                         await self.pending_generation_crud.update_pending_generation_status(session, record.id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, (record.moderator_notes or "") + " | App persistence failed.") # type: ignore[arg-type]
                    return False
        except Exception as e:
            logger.error(f"Unexpected error in process_approved_generation for {pending_generation_id}: {e}", exc_info=True)
            try: # Attempt to mark as failed even if outer transaction failed
                async with GuildTransaction(self.db_service.get_session_factory, guild_id) as error_session: # type: ignore[attr-defined]
                    await self.pending_generation_crud.update_pending_generation_status(error_session, pending_generation_id, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, f"App fail exception: {str(e)[:100]}") # type: ignore[arg-type]
            except Exception as e_status: logger.error(f"CRITICAL: Failed to update status to APPLICATION_FAILED for {pending_generation_id} after error: {e_status}", exc_info=True)
            return False
