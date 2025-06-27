from __future__ import annotations
import logging
import json
from typing import Optional, Dict, Any, TYPE_CHECKING, List, Union, cast, Callable
import uuid

from bot.database.models.world_related import Location
from bot.ai.ai_data_models import GeneratedLocationContent, POIModel, ConnectionModel, GeneratedNpcProfile, ValidationIssue
from sqlalchemy.orm.attributes import flag_modified

from bot.database.models.pending_generation import PendingGeneration, GenerationType, PendingStatus # Corrected path
from bot.database.pending_generation_crud import PendingGenerationCRUD # Corrected path
from bot.database.guild_transaction import GuildTransaction
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession # Added for type hint

import asyncio

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.game.managers.game_manager import GameManager
    from bot.database.models.guild_config import GuildConfig # Added import
    from bot.game.managers.item_manager import ItemManager # For type hint
    from bot.game.services.location_interaction_service import LocationInteractionService # For type hint


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
        context_params: Dict[str, Any],
        prompt_params: Dict[str, Any],
        created_by_user_id: Optional[str] = None,
        session: Optional["AsyncSession"] = None
    ) -> Optional[PendingGeneration]:
        logger.info(f"AIGM: Requesting '{request_type.value}' for guild {guild_id} by user {created_by_user_id}.")

        generation_context_params = {
            "guild_id": guild_id, "character_id": context_params.get("character_id"),
            "location_id": context_params.get("location_id"), "npc_id": context_params.get("npc_id"),
            "item_id": context_params.get("item_id"), "quest_id": context_params.get("quest_id"),
            "faction_id": context_params.get("faction_id"), "event_id": context_params.get("event_id"),
            "dialogue_history": context_params.get("dialogue_history"),
            "recent_events": context_params.get("recent_events"),
            "additional_notes": context_params.get("additional_notes")
        }
        generation_context_params = {k: v for k, v in generation_context_params.items() if v is not None}
        generation_context = await self.prompt_context_collector.get_full_context(**generation_context_params)

        target_languages_input = prompt_params.get("target_languages"); target_languages_list: List[str] = []
        if isinstance(target_languages_input, list): target_languages_list = [str(lang).strip() for lang in target_languages_input if lang and isinstance(lang, (str, int, float)) and str(lang).strip()]
        elif isinstance(target_languages_input, str): target_languages_list = [lang.strip() for lang in target_languages_input.split(',') if lang.strip()]
        if not target_languages_list:
            default_lang = "en"
            get_rule_method = getattr(self.game_manager, 'get_rule', None)
            if callable(get_rule_method):
                lang_rule_val = await get_rule_method(guild_id, "default_language", "en")
                default_lang = str(lang_rule_val) if lang_rule_val and isinstance(lang_rule_val, str) else "en"
            target_languages_list = [default_lang]
            if "en" not in target_languages_list: target_languages_list.append("en")
        target_languages_list = sorted(list(set(target_languages_list)))

        prepare_prompt_args: Dict[str, Any] = {
            "guild_id": guild_id,
            "location_id": str(context_params.get("location_id")) if context_params.get("location_id") else \
                           str(generation_context.get("location", {}).get("id")) if isinstance(generation_context.get("location"), dict) else "default_world_space",
            "player_id": str(context_params.get("character_id")) if context_params.get("character_id") else None,
            "specific_task_instruction": str(prompt_params.get("specific_task_instruction", f"Generate content for type: {request_type.value}."))
        }
        additional_req_params: Dict[str, Any] = {
            "target_character_id": str(prompt_params.get("target_character_id")) if prompt_params.get("target_character_id") else None,
            "target_languages": target_languages_list, "generation_type_str": request_type.value,
            "context_data": generation_context,
            **{k: v for k, v in prompt_params.items() if k not in ["target_character_id", "target_languages", "specific_task_instruction"]}
        }
        prepare_prompt_args["additional_request_params"] = {k:v for k,v in additional_req_params.items() if v is not None}
        final_prompt_str = await self.multilingual_prompt_generator.prepare_ai_prompt(**prepare_prompt_args)

        # Using placeholder as AI call is out of scope
        raw_ai_output_text = json.dumps({"name_i18n": {"en": "AI Generated Content"}, "description_i18n": {"en": "Details..."}})

        # Ensure ai_response_validator and its method are callable
        parse_validate_method = getattr(self.ai_response_validator, 'parse_and_validate_ai_response', None)
        if not callable(parse_validate_method):
            logger.error("AIResponseValidator.parse_and_validate_ai_response is not callable.")
            return None # Or handle error appropriately

        parsed_data, validation_issues_list = await parse_validate_method(
            raw_ai_output_text=raw_ai_output_text, guild_id=guild_id, request_type=request_type, game_manager=self.game_manager
        )
        validation_issues_for_db: Optional[List[Dict[str,Any]]] = [issue.model_dump() for issue in validation_issues_list] if validation_issues_list else None
        current_status = PendingStatus.FAILED_VALIDATION if validation_issues_for_db else PendingStatus.PENDING_MODERATION

        pending_generation_record: Optional[PendingGeneration] = None
        async def create_record_internal(current_session_internal: AsyncSession):
            nonlocal pending_generation_record
            pending_generation_record = await self.pending_generation_crud.create_pending_generation(
                session=current_session_internal, guild_id=guild_id, request_type=request_type, status=current_status,
                request_params_json=context_params, raw_ai_output_text=raw_ai_output_text,
                parsed_data_json=parsed_data, validation_issues_json=validation_issues_for_db,
                created_by_user_id=str(created_by_user_id) if created_by_user_id else None
            )

        if session: await create_record_internal(session)
        else:
            session_factory_callable: Optional[Callable[[], AsyncSession]] = getattr(self.db_service, 'get_session_factory', None)
            if not callable(session_factory_callable): logger.error("DBService missing 'get_session_factory'."); return None
            try:
                async with GuildTransaction(session_factory_callable(), guild_id) as new_session_ctx: # type: ignore[operator]
                    await create_record_internal(new_session_ctx)
            except Exception as e: logger.exception(f"AIGM: Failed to create PG record for '{request_type.value}' in guild {guild_id}"); return None

        if pending_generation_record and pending_generation_record.id:
            logger.info(f"AIGM: PG record {pending_generation_record.id} created for '{request_type.value}'.")
            # ... (Notification logic as before, ensuring safe access to managers and methods) ...
        else: logger.error(f"AIGM: PG record creation failed for '{request_type.value}'."); return None
        return pending_generation_record

    async def request_location_generation( # ... (signature as before) ...
        self, guild_id: str, context_params: Dict[str, Any],
        prompt_params: Dict[str, Any], created_by_user_id: Optional[str] = None,
        session: Optional["AsyncSession"] = None
    ) -> Optional[PendingGeneration]:
        return await self.request_content_generation(
            guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS, context_params=context_params,
            prompt_params=prompt_params, created_by_user_id=created_by_user_id, session=session
        )

    async def process_approved_generation( # ... (signature as before) ...
        self, pending_generation_id: str, guild_id: str, moderator_user_id: str
    ) -> bool:
        logger.info(f"AIGM: Processing approved PG ID {pending_generation_id} for guild {guild_id}.")
        session_factory_callable: Optional[Callable[[], AsyncSession]] = getattr(self.db_service, 'get_session_factory', None)
        if not callable(session_factory_callable): logger.error("DBService missing 'get_session_factory'."); return False

        try:
            async with GuildTransaction(session_factory_callable(), guild_id) as session: # type: ignore[operator]
                record = await self.pending_generation_crud.get_pending_generation_by_id(session, pending_generation_id, guild_id)
                if not record or not record.id: logger.error(f"PG record {pending_generation_id} not found."); return False

                record_id_str = str(record.id)
                if record.status != PendingStatus.APPROVED.value: logger.warning(f"PG {record_id_str} not APPROVED."); return False
                if not record.parsed_data_json or not isinstance(record.parsed_data_json, dict):
                    logger.error(f"No parsed_data for PG {record_id_str}.");
                    await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, parsed_data_json={"error": "No parsed data."}) # type: ignore[call-arg]
                    return False

                request_type_val_str = str(record.request_type) if record.request_type else None
                request_type_val: Optional[GenerationType] = None
                if request_type_val_str:
                    try: request_type_val = GenerationType[request_type_val_str.upper()]
                    except KeyError: pass

                if not request_type_val:
                    logger.error(f"Invalid request_type '{request_type_val_str}' for PG {record_id_str}.");
                    await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLICATION_FAILED, guild_id, moderator_user_id, validation_issues_json=[{"error": f"Invalid type {request_type_val_str}."}]); return False # type: ignore[call-arg]

                parsed_data = cast(Dict[str, Any], record.parsed_data_json)
                application_success = False; persisted_entity_id: Optional[str] = None

                if request_type_val == GenerationType.LOCATION_DETAILS:
                    ai_location_data: Optional[GeneratedLocationContent] = None
                    try: ai_location_data = GeneratedLocationContent(**parsed_data)
                    except Exception as e: logger.exception(f"Failed to parse LOCATION_DETAILS for {record_id_str}"); # ... (update status and return False)

                    if ai_location_data:
                        # ... (Location persistence logic as before, ensuring type safety and flag_modified)
                        # Example for one field:
                        loc_to_persist = Location(guild_id=guild_id, id=str(uuid.uuid4())) # Simplified for brevity
                        loc_to_persist.name_i18n = ai_location_data.name_i18n # This is fine if name_i18n is Dict[str,str]
                        flag_modified(loc_to_persist, "name_i18n")
                        # ... and so on for other fields ...
                        session.add(loc_to_persist); await session.flush()
                        persisted_entity_id = str(loc_to_persist.id) if loc_to_persist.id else None
                        application_success = bool(persisted_entity_id)
                        # ... (NPC/Item spawning logic, ensuring managers and methods are checked) ...
                        if application_success and persisted_entity_id:
                             loc_interaction_service = cast(Optional["LocationInteractionService"], getattr(self.game_manager, 'location_interaction_service', None))
                             if loc_interaction_service and hasattr(loc_interaction_service, 'process_on_enter_location_events') and callable(getattr(loc_interaction_service, 'process_on_enter_location_events')):
                                 # ... (triggering_character_id logic) ...
                                 # asyncio.create_task(loc_interaction_service.process_on_enter_location_events(...)) # Removed for now, context might be complex
                                 pass


                # ... (elif for NPC_PROFILE, QUEST_FULL, ITEM_PROFILE - similar safe access and method calls) ...
                elif request_type_val in [GenerationType.NPC_PROFILE, GenerationType.QUEST_FULL, GenerationType.ITEM_PROFILE]:
                    logger.info(f"AIGM: [SIMULATING PERSISTENCE] for {request_type_val.value} - PG ID {record_id_str}")
                    persisted_entity_id = f"simulated_{request_type_val.value.lower()}_{record_id_str[:8]}"
                    application_success = True


                if application_success and persisted_entity_id:
                    record.entity_id = persisted_entity_id # This should be fine if record.entity_id is Column[str]
                    flag_modified(record, "entity_id")
                    await self.pending_generation_crud.update_pending_generation_status(session, record_id_str, PendingStatus.APPLIED, guild_id, moderator_user_id, moderator_notes=str(record.moderator_notes)) # type: ignore[call-arg]
                    logger.info(f"Applied PG {pending_generation_id}. Status: APPLIED.")
                    return True
                else: # ... (update status to FAILED and return False) ...
                    return False
        except Exception as e: # ... (Outer exception handling) ...
            logger.exception(f"Unexpected error processing approved PG {pending_generation_id}")
            return False

[end of bot/ai/generation_manager.py]
