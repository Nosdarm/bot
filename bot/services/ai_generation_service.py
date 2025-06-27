# bot/services/ai_generation_service.py
import json
import uuid
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, List, cast, Callable

from bot.database.models.pending_generation import PendingGeneration, PendingStatus, GenerationType, ValidationIssue
from bot.database.models.guild_config import GuildConfig
from bot.database.models.npc import NPC
from bot.database.models.location import Location
from bot.database.models.quest_related import QuestTable, QuestStepTable # Assuming this is the correct location
from bot.database.guild_transaction import GuildTransaction
from sqlalchemy.ext.asyncio import AsyncSession


if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager
    from bot.services.db_service import DBService
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.services.openai_service import OpenAIService
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.services.notification_service import NotificationService
    from bot.game.managers.character_manager import CharacterManager


logger = logging.getLogger(__name__)

class AIGenerationService:
    def __init__(self, game_manager: "GameManager"):
        self.game_manager = game_manager

    async def trigger_ai_generation(
        self,
        guild_id: str,
        request_type: str,
        request_params: Dict[str, Any],
        created_by_user_id: Optional[str] = None
    ) -> Optional[str]:
        logger.info(f"AIGenerationService: Triggering AI generation for guild {guild_id}, type '{request_type}'.")

        multilingual_prompt_generator = getattr(self.game_manager, 'multilingual_prompt_generator', None)
        openai_service = getattr(self.game_manager, 'openai_service', None)
        db_service = getattr(self.game_manager, 'db_service', None)
        ai_response_validator = getattr(self.game_manager, 'ai_response_validator', None)

        if not all([multilingual_prompt_generator, openai_service, db_service, ai_response_validator]):
            logger.error("AIGenerationService: Core AI services not fully available via GameManager.")
            return None

        specific_task_instruction = ""
        if request_type == GenerationType.LOCATION_CONTENT_GENERATION.value:
            specific_task_instruction = "Generate detailed content for a game location based on the provided context and parameters, including name, atmospheric description, points of interest, and connections."
        elif request_type == GenerationType.NPC_PROFILE_GENERATION.value:
            specific_task_instruction = "Generate a complete NPC profile based on the provided context and parameters, including template_id, name, role, archetype, backstory, personality, motivation, visual description, dialogue hints, stats, skills, abilities, spells, inventory, faction affiliations, and relationships."
        elif request_type == GenerationType.QUEST_GENERATION.value:
            specific_task_instruction = "Generate a complete quest structure based on the provided context and parameters, including name, description, steps (with mechanics, goals, consequences), overall consequences, and prerequisites."
        else:
            specific_task_instruction = "Perform the requested AI generation task based on the provided context and parameters."

        location_id_for_prompt = request_params.get("location_id")

        prepare_ai_prompt_method = getattr(multilingual_prompt_generator, 'prepare_ai_prompt', None)
        if not callable(prepare_ai_prompt_method):
            logger.error("multilingual_prompt_generator.prepare_ai_prompt is not callable.")
            return None
        prompt_str = await prepare_ai_prompt_method(
            guild_id=guild_id,
            location_id=str(location_id_for_prompt) if location_id_for_prompt else None, # Ensure string or None
            player_id=str(request_params.get("player_id")) if request_params.get("player_id") else None,
            party_id=str(request_params.get("party_id")) if request_params.get("party_id") else None,
            specific_task_instruction=specific_task_instruction,
            additional_request_params=request_params
        )

        get_completion_method = getattr(openai_service, 'get_completion', None)
        if not callable(get_completion_method):
            logger.error("openai_service.get_completion is not callable.")
            return None
        raw_ai_output = await get_completion_method(prompt_str)

        pending_status_enum = PendingStatus.PENDING_VALIDATION
        parsed_data_dict: Optional[Dict[str, Any]] = None
        validation_issues_list_obj: Optional[List[ValidationIssue]] = None
        validation_issues_for_db: Optional[List[Dict[str, Any]]] = None

        if not raw_ai_output:
            logger.error(f"AIGenerationService: AI generation failed for type '{request_type}', guild {guild_id}. No output from OpenAI service.")
            pending_status_enum = PendingStatus.FAILED_VALIDATION
            validation_issues_list_obj = [ValidationIssue(type="generation_error", msg="AI service returned no output.", loc=())]
        else:
            parse_validate_method = getattr(ai_response_validator, 'parse_and_validate_ai_response', None)
            if not callable(parse_validate_method):
                logger.error("ai_response_validator.parse_and_validate_ai_response is not callable.")
                pending_status_enum = PendingStatus.FAILED_VALIDATION # Fail if validator is missing
                validation_issues_list_obj = [ValidationIssue(type="internal_error", msg="AI Response Validator not available.", loc=())]
            else:
                try:
                    request_type_enum_val = GenerationType[request_type.upper()]
                except KeyError:
                    logger.error(f"Invalid request_type string: {request_type}")
                    pending_status_enum = PendingStatus.FAILED_VALIDATION
                    validation_issues_list_obj = [ValidationIssue(type="validation_error", msg=f"Invalid request type: {request_type}", loc=("request_type",))]
                else:
                    parsed_data_dict, validation_issues_list_obj = await parse_validate_method(
                        raw_ai_output_text=raw_ai_output, guild_id=guild_id,
                        request_type=request_type_enum_val, game_manager=self.game_manager
                    )
                    if validation_issues_list_obj:
                        pending_status_enum = PendingStatus.FAILED_VALIDATION
                    else:
                        pending_status_enum = PendingStatus.PENDING_MODERATION

        if validation_issues_list_obj:
            validation_issues_for_db = [issue.model_dump() for issue in validation_issues_list_obj]

        pending_gen_data = {
            "id": str(uuid.uuid4()), "guild_id": guild_id, "request_type": request_type,
            "request_params_json": json.dumps(request_params) if request_params else None,
            "raw_ai_output_text": raw_ai_output, "parsed_data_json": parsed_data_dict,
            "validation_issues_json": validation_issues_for_db, "status": pending_status_enum.value,
            "created_by_user_id": created_by_user_id
        }

        create_entity_method = getattr(db_service, 'create_entity', None)
        if not callable(create_entity_method):
            logger.error("db_service.create_entity is not callable.")
            return None

        pending_gen_record_obj = await create_entity_method(
            model_class=PendingGeneration, entity_data=pending_gen_data
        )

        if not pending_gen_record_obj or not getattr(pending_gen_record_obj, 'id', None):
            logger.error(f"AIGenerationService: Failed to create PendingGeneration record in DB for type '{request_type}', guild {guild_id}.")
            return None

        pending_gen_record_id = str(pending_gen_record_obj.id)
        logger.info(f"AIGenerationService: PendingGeneration record {pending_gen_record_id} created with status '{pending_status_enum.value}'.")

        if pending_status_enum == PendingStatus.PENDING_MODERATION:
            notification_service = getattr(self.game_manager, 'notification_service', None)
            send_notification_method = getattr(notification_service, 'send_notification', None)
            get_entity_by_pk_method = getattr(db_service, 'get_entity_by_pk', None)

            if notification_service and callable(send_notification_method) and callable(get_entity_by_pk_method):
                guild_config_obj = await get_entity_by_pk_method(GuildConfig, pk_value=guild_id)

                if isinstance(guild_config_obj, GuildConfig):
                    notification_channel_id_to_use = guild_config_obj.notification_channel_id or \
                                                     guild_config_obj.master_channel_id or \
                                                     guild_config_obj.system_channel_id
                    if notification_channel_id_to_use:
                        try:
                            message_to_send = f"🔔 New AI Content (Type: '{request_type}', ID: `{pending_gen_record_id}`) is awaiting moderation. Use `/master review_ai id:{pending_gen_record_id}` to review."
                            await send_notification_method(
                                target_channel_id=int(str(notification_channel_id_to_use)),
                                message=message_to_send
                            )
                        except ValueError: logger.error(f"Invalid channel ID format: {notification_channel_id_to_use}")
                        except Exception as e: logger.error(f"Failed to send moderation notification: {e}", exc_info=True)

            if created_by_user_id and request_type in [GenerationType.NPC_PROFILE_GENERATION.value, GenerationType.LOCATION_CONTENT_GENERATION.value]:
                character_manager = cast(Optional['CharacterManager'], getattr(self.game_manager, 'character_manager', None))
                if character_manager:
                    get_char_method = getattr(character_manager, 'get_character_by_discord_id', None)
                    mark_dirty_method = getattr(character_manager, 'mark_character_dirty', None)
                    if callable(get_char_method) and callable(mark_dirty_method):
                        try:
                            player_char = await get_char_method(guild_id, int(created_by_user_id))
                            if player_char and hasattr(player_char, 'id') and player_char.id:
                                if hasattr(player_char, 'current_game_status'):
                                    setattr(player_char, 'current_game_status', 'ожидание_модерации')
                                    mark_dirty_method(guild_id, str(player_char.id))
                                    logger.info(f"Set character {player_char.id} status to 'ожидание_модерации' for AI generation {pending_gen_record_id}.")
                                else:
                                    logger.warning(f"Character model for {player_char.id} does not have 'current_game_status'. Cannot set status.")
                            else:
                                logger.warning(f"Could not find active character for user {created_by_user_id} in guild {guild_id} to set status for AI generation.")
                        except ValueError: logger.error(f"Invalid created_by_user_id format '{created_by_user_id}'. Cannot parse to int.")
                        except Exception as e_status: logger.error(f"Error setting player status for AI generation {pending_gen_record_id}: {e_status}", exc_info=True)
        return pending_gen_record_id

    async def apply_approved_generation(
        self,
        pending_gen_id: str,
        guild_id: str
    ) -> bool:
        logger.info(f"AIGenerationService: Applying approved generation {pending_gen_id} for guild {guild_id}.")
        db_service = cast(Optional['DBService'], getattr(self.game_manager, 'db_service', None))
        if not db_service:
            logger.error("AIGenerationService: DBService not available.")
            return False

        session_factory_method = getattr(db_service, 'async_session_factory', None)
        if not callable(session_factory_method): # Check if it's a callable that returns a session factory
             session_factory_method = getattr(db_service, 'get_session_factory', None) # Try alternative common name

        if not callable(session_factory_method):
            logger.error("AIGenerationService: DBService.async_session_factory or get_session_factory is not callable.")
            return False

        actual_session_factory: Callable[[], AsyncSession] = session_factory_method

        record: Optional[PendingGeneration] = None
        get_session_context_manager = getattr(db_service, 'get_session', None)
        if not callable(get_session_context_manager):
            logger.error("DBService.get_session is not callable for fetching record.")
            return False

        async with get_session_context_manager() as temp_session:
            if not isinstance(temp_session, AsyncSession):
                logger.error("DBService.get_session did not yield an AsyncSession.")
                return False
            record = await temp_session.get(PendingGeneration, pending_gen_id)

        if not record or str(record.guild_id) != guild_id:
            logger.error(f"AIGenerationService: Record {pending_gen_id} not found or guild mismatch.")
            return False

        if record.status != PendingStatus.APPROVED.value:
            logger.warning(f"AIGenerationService: Record {pending_gen_id} not 'approved' (status: {record.status}).")
            return False

        if not record.parsed_data_json or not isinstance(record.parsed_data_json, dict):
            logger.error(f"AIGenerationService: Parsed data for {pending_gen_id} missing/invalid.")
            fail_payload = {"status": PendingStatus.APPLICATION_FAILED.value, "validation_issues_json": (record.validation_issues_json or []) + [{"type": "application_error", "msg": "Parsed data missing."}]}
            update_entity_method = getattr(db_service, 'update_entity_by_pk', None)
            if callable(update_entity_method):
                await update_entity_method(PendingGeneration, str(record.id), fail_payload, guild_id=guild_id)
            return False

        application_successful = False
        final_status_update_payload: Dict[str, Any] = {}
        current_validation_issues = list(record.validation_issues_json or [])

        async with GuildTransaction(actual_session_factory, guild_id) as session:
            try:
                if record.request_type == GenerationType.NPC_PROFILE_GENERATION.value:
                    npc_data = cast(Dict[str, Any], record.parsed_data_json)
                    request_params = json.loads(record.request_params_json or '{}')

                    npc_id = str(uuid.uuid4()); default_hp = 100.0
                    stats_data = npc_data.get("stats", {})
                    health = float(stats_data.get("hp", default_hp)); max_health_val = float(stats_data.get("max_hp", health))
                    npc_db_data = {
                        "id": npc_id, "guild_id": guild_id, "name_i18n": npc_data.get("name_i18n"),
                        "description_i18n": npc_data.get("visual_description_i18n"), "backstory_i18n": npc_data.get("backstory_i18n"),
                        "persona_i18n": npc_data.get("personality_i18n"), "stats": stats_data, "inventory": npc_data.get("inventory", []),
                        "archetype": npc_data.get("archetype"), "template_id": npc_data.get("template_id"),
                        "location_id": request_params.get("initial_location_id"), "health": health, "max_health": max_health_val,
                        "is_alive": True, "motives": npc_data.get("motivation_i18n"), "skills_data": npc_data.get("skills"),
                        "abilities_data": {"ids": npc_data.get("abilities", [])}, "equipment_data": {}, "state_variables": {},
                        "is_temporary": request_params.get("is_temporary", False)
                    }
                    faction_affiliations = npc_data.get("faction_affiliations")
                    if faction_affiliations and isinstance(faction_affiliations, list) and faction_affiliations:
                        first_faction = faction_affiliations[0]
                        npc_db_data["faction_id"] = first_faction.get("faction_id") if isinstance(first_faction, dict) else None

                    create_entity_method_gs = getattr(db_service, 'create_entity', None)
                    if callable(create_entity_method_gs):
                        new_npc = await create_entity_method_gs(model_class=NPC, entity_data=npc_db_data, session=session)
                        application_successful = bool(new_npc)
                        if not new_npc: current_validation_issues.append({"type": "application_error", "msg": "NPC DB creation failed."})
                    else: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "DBService.create_entity not available."})

                elif record.request_type == GenerationType.LOCATION_CONTENT_GENERATION.value:
                    loc_data = cast(Dict[str, Any], record.parsed_data_json); new_loc_id = str(uuid.uuid4())
                    connections = loc_data.get("connections", [])
                    neighbor_locs = {conn.get("to_location_id"): conn.get("path_description_i18n", {}).get("en", f"path_to_{conn.get('to_location_id')}")
                                     for conn in connections if isinstance(conn, dict) and conn.get("to_location_id")}
                    static_id = loc_data.get("template_id") or f"ai_loc_{new_loc_id[:12]}"
                    loc_db_data = {
                        "id": new_loc_id, "guild_id": guild_id,
                        "name_i18n": loc_data.get("name_i18n", {"en": "AI Location"}),
                        "descriptions_i18n": loc_data.get("atmospheric_description_i18n", {"en": "N/A"}),
                        "static_id": static_id, "template_id": loc_data.get("template_id"),
                        "type_i18n": loc_data.get("type_i18n", {"en": "AI Area"}), "neighbor_locations_json": neighbor_locs,
                        "points_of_interest_json": loc_data.get("points_of_interest", []),
                        "ai_metadata_json": {"original_request_params": json.loads(record.request_params_json or '{}'), "ai_generated_template_id": loc_data.get("template_id")},
                        "is_active": True
                    }
                    create_entity_method_gs = getattr(db_service, 'create_entity', None)
                    if callable(create_entity_method_gs):
                        new_loc = await create_entity_method_gs(model_class=Location, entity_data=loc_db_data, session=session)
                        application_successful = bool(new_loc)
                        if not new_loc: current_validation_issues.append({"type": "application_error", "msg": "Location DB creation failed."})
                    else: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "DBService.create_entity not available."})

                elif record.request_type == GenerationType.QUEST_GENERATION.value:
                    quest_data = cast(Dict[str, Any], record.parsed_data_json); new_quest_id = str(uuid.uuid4())
                    quest_db_data = {
                        "id": new_quest_id, "guild_id": guild_id,
                        "name_i18n": quest_data.get("name_i18n", {"en": "AI Quest"}),
                        "description_i18n": quest_data.get("description_i18n", {"en": "N/A"}),
                        "status": "available", "is_ai_generated": True
                    }
                    create_entity_method_gs = getattr(db_service, 'create_entity', None)
                    if callable(create_entity_method_gs):
                        new_quest = await create_entity_method_gs(model_class=QuestTable, entity_data=quest_db_data, session=session)
                        if not new_quest: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "QuestTable creation failed."})
                        else:
                            all_steps_ok = True
                            steps_to_create = quest_data.get("steps", [])
                            for step_data in steps_to_create:
                                step_db_data = {"id": str(uuid.uuid4()), "guild_id": guild_id, "quest_id": new_quest.id, "title_i18n": step_data.get("title_i18n") if isinstance(step_data, dict) else None} # Ensure step_data is dict
                                if not await create_entity_method_gs(model_class=QuestStepTable, entity_data=step_db_data, session=session):
                                    all_steps_ok = False; current_validation_issues.append({"type": "application_error", "msg": "QuestStep creation failed."}); break
                            application_successful = all_steps_ok
                    else: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "DBService.create_entity not available."})
                else:
                    logger.warning(f"AIGenSvc: Apply logic for '{record.request_type}' not implemented.");
                    record.status = PendingStatus.APPLICATION_PENDING_LOGIC.value
                    application_successful = False

                if application_successful: await session.commit(); record.status = PendingStatus.APPLIED.value
                else: await session.rollback(); record.status = record.status if record.status in [PendingStatus.APPLICATION_FAILED.value, PendingStatus.APPLICATION_PENDING_LOGIC.value] else PendingStatus.APPLICATION_FAILED.value
                final_status_update_payload = {"status": record.status, "validation_issues_json": current_validation_issues if record.status == PendingStatus.APPLICATION_FAILED.value else record.validation_issues_json}
            except Exception as e:
                logger.error(f"AIGenSvc: Exception in GuildTransaction for {pending_gen_id}: {e}", exc_info=True);
                if session.is_active: await session.rollback()
                application_successful = False;
                if record: record.status = PendingStatus.APPLICATION_FAILED.value
                current_validation_issues.append({"type": "application_error", "msg": f"Transaction exception: {str(e)}"});
                final_status_update_payload = {"status": PendingStatus.APPLICATION_FAILED.value, "validation_issues_json": current_validation_issues}

        if final_status_update_payload and record and record.id :
            update_entity_pk_method = getattr(db_service, 'update_entity_by_pk', None)
            if callable(update_entity_pk_method) and callable(get_session_context_manager):
                async with get_session_context_manager() as status_session: # type: ignore[attr-defined]
                    if not isinstance(status_session, AsyncSession):
                         logger.error("DBService.get_session for status update did not yield an AsyncSession.")
                    else:
                        # Some DB adapters might require begin() explicitly even for single updates if not auto-committing
                        if hasattr(status_session, 'begin') and callable(status_session.begin):
                             async with status_session.begin(): # type: ignore[attr-defined]
                                await update_entity_pk_method(PendingGeneration, str(record.id), final_status_update_payload, guild_id=guild_id, session=status_session)
                        else: # Assume direct execution is fine
                            await update_entity_pk_method(PendingGeneration, str(record.id), final_status_update_payload, guild_id=guild_id, session=status_session)
            elif not callable(update_entity_pk_method):
                 logger.error("DBService.update_entity_by_pk is not callable for final status update.")


        return application_successful

[end of bot/services/ai_generation_service.py]
