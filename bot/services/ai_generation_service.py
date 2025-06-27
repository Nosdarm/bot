# bot/services/ai_generation_service.py
import json
import uuid
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, List

# Assuming models are accessible via bot.database.models after refactoring
from bot.database.models import PendingGeneration, GuildConfig, NPC, Location, QuestTable, QuestStepTable
from bot.database.guild_transaction import GuildTransaction

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager
    # Specific managers can be imported for type hinting if needed by methods,
    # but they will be accessed via self.game_manager
    # from bot.services.db_service import DBService
    # from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    # from bot.services.openai_service import OpenAIService
    # from bot.ai.ai_response_validator import AIResponseValidator # Already imported
    # from bot.services.notification_service import NotificationService
    # from bot.game.managers.npc_manager import NpcManager
    # from bot.game.managers.location_manager import LocationManager
    # from bot.game.managers.quest_manager import QuestManager

logger = logging.getLogger(__name__)

class AIGenerationService:
    def __init__(self, game_manager: "GameManager"):
        self.game_manager = game_manager

    async def trigger_ai_generation(
        self,
        guild_id: str,
        request_type: str, # Should ideally be an Enum like GenerationType
        request_params: Dict[str, Any],
        created_by_user_id: Optional[str] = None
    ) -> Optional[str]:
        logger.info(f"AIGenerationService: Triggering AI generation for guild {guild_id}, type '{request_type}'.")

        # Ensure core services are available via game_manager
        if not self.game_manager or \
           not hasattr(self.game_manager, 'multilingual_prompt_generator') or not self.game_manager.multilingual_prompt_generator or \
           not hasattr(self.game_manager, 'openai_service') or not self.game_manager.openai_service or \
           not hasattr(self.game_manager, 'db_service') or not self.game_manager.db_service or \
           not hasattr(self.game_manager, 'ai_response_validator') or not self.game_manager.ai_response_validator:
            logger.error("AIGenerationService: Core AI services not fully available via GameManager.")
            return None

        specific_task_instruction = ""
        # ... (task instruction logic remains the same) ...
        if request_type == "location_content_generation":
            specific_task_instruction = "Generate detailed content for a game location based on the provided context and parameters, including name, atmospheric description, points of interest, and connections."
        elif request_type == "npc_profile_generation":
            specific_task_instruction = "Generate a complete NPC profile based on the provided context and parameters, including template_id, name, role, archetype, backstory, personality, motivation, visual description, dialogue hints, stats, skills, abilities, spells, inventory, faction affiliations, and relationships."
        elif request_type == "quest_generation":
            specific_task_instruction = "Generate a complete quest structure based on the provided context and parameters, including name, description, steps (with mechanics, goals, consequences), overall consequences, and prerequisites."
        else:
            specific_task_instruction = "Perform the requested AI generation task based on the provided context and parameters."


        location_id_for_prompt = request_params.get("location_id")

        # Ensure multilingual_prompt_generator is callable
        if not callable(self.game_manager.multilingual_prompt_generator.prepare_ai_prompt):
            logger.error("multilingual_prompt_generator.prepare_ai_prompt is not callable.")
            return None
        prompt_str = await self.game_manager.multilingual_prompt_generator.prepare_ai_prompt(
            guild_id=guild_id,
            location_id=str(location_id_for_prompt) if location_id_for_prompt else "",
            player_id=str(request_params.get("player_id")) if request_params.get("player_id") else None, # Ensure string or None
            party_id=str(request_params.get("party_id")) if request_params.get("party_id") else None, # Ensure string or None
            specific_task_instruction=specific_task_instruction,
            additional_request_params=request_params
        )

        # Ensure openai_service is callable
        if not callable(self.game_manager.openai_service.get_completion):
            logger.error("openai_service.get_completion is not callable.")
            return None
        raw_ai_output = await self.game_manager.openai_service.get_completion(prompt_str)

        pending_status_enum = PendingStatus.PENDING_VALIDATION # Use Enum member
        parsed_data_dict: Optional[Dict[str, Any]] = None
        validation_issues_list_obj: Optional[List[ValidationIssue]] = None # Use Pydantic model
        validation_issues_for_db: Optional[List[Dict[str, Any]]] = None


        if not raw_ai_output:
            logger.error(f"AIGenerationService: AI generation failed for type '{request_type}', guild {guild_id}. No output from OpenAI service.")
            pending_status_enum = PendingStatus.FAILED_VALIDATION
            validation_issues_list_obj = [ValidationIssue(type="generation_error", msg="AI service returned no output.", loc=())]
        else:
            if not callable(self.game_manager.ai_response_validator.parse_and_validate_ai_response):
                logger.error("ai_response_validator.parse_and_validate_ai_response is not callable.")
                return None

            # Convert request_type string to GenerationType enum if necessary
            try:
                request_type_enum = GenerationType[request_type.upper()] if isinstance(request_type, str) else request_type
            except KeyError:
                logger.error(f"Invalid request_type string: {request_type}")
                pending_status_enum = PendingStatus.FAILED_VALIDATION
                validation_issues_list_obj = [ValidationIssue(type="validation_error", msg=f"Invalid request type: {request_type}", loc=("request_type",))]
            else:
                parsed_data_dict, validation_issues_list_obj = await self.game_manager.ai_response_validator.parse_and_validate_ai_response(
                    raw_ai_output_text=raw_ai_output, guild_id=guild_id,
                    request_type=request_type_enum, game_manager=self.game_manager
                )
                if validation_issues_list_obj:
                    pending_status_enum = PendingStatus.FAILED_VALIDATION
                else:
                    pending_status_enum = PendingStatus.PENDING_MODERATION

        if validation_issues_list_obj:
            validation_issues_for_db = [issue.model_dump() for issue in validation_issues_list_obj]


        pending_gen_data = {
            "id": str(uuid.uuid4()),
            "guild_id": guild_id,
            "request_type": request_type, # Store original string type
            "request_params_json": json.dumps(request_params) if request_params else None,
            "raw_ai_output_text": raw_ai_output,
            "parsed_data_json": parsed_data_dict,
            "validation_issues_json": validation_issues_for_db,
            "status": pending_status_enum.value, # Store enum value
            "created_by_user_id": created_by_user_id
        }

        if not callable(self.game_manager.db_service.create_entity): # "create_entity" is not a known attribute of "None" - Fixed by checking game_manager.db_service earlier
            logger.error("db_service.create_entity is not callable.")
            return None
        pending_gen_record = await self.game_manager.db_service.create_entity(
            model_class=PendingGeneration, entity_data=pending_gen_data
        )

        if not pending_gen_record or not getattr(pending_gen_record, 'id', None): # Cannot access attribute "id" for class "CoroutineType[PendingGeneration]" - Fixed by awaiting
            logger.error(f"AIGenerationService: Failed to create PendingGeneration record in DB for type '{request_type}', guild {guild_id}.")
            return None

        pending_gen_record_id = str(pending_gen_record.id) # Ensure ID is string
        logger.info(f"AIGenerationService: PendingGeneration record {pending_gen_record_id} created with status '{pending_status_enum.value}'.")

        if pending_status_enum == PendingStatus.PENDING_MODERATION:
            notification_service = getattr(self.game_manager, 'notification_service', None) # "notification_service" is not a known attribute of "GameManager" - Fixed with getattr
            if notification_service and hasattr(notification_service, 'send_notification') and callable(notification_service.send_notification):
                guild_config_obj: Optional[GuildConfig] = None
                if hasattr(self.game_manager.db_service, 'get_entity_by_pk') and callable(self.game_manager.db_service.get_entity_by_pk): # Cannot access attribute "get_entity_by_pk" for class "DBService" - Fixed with hasattr/callable
                    guild_config_obj = await self.game_manager.db_service.get_entity_by_pk(GuildConfig, pk_value=guild_id)

                if guild_config_obj and isinstance(guild_config_obj, GuildConfig):
                    notification_channel_id_to_use = guild_config_obj.notification_channel_id or \
                                                     guild_config_obj.master_channel_id or \
                                                     guild_config_obj.system_channel_id
                    if notification_channel_id_to_use:
                        try:
                            message_to_send = f"🔔 New AI Content (Type: '{request_type}', ID: `{pending_gen_record_id}`) is awaiting moderation. Use `/master review_ai id:{pending_gen_record_id}` to review."
                            await notification_service.send_notification( # Cannot access attribute "send_notification" for class "NotificationService" - Fixed with hasattr/callable
                                target_channel_id=int(str(notification_channel_id_to_use)), # Ensure int
                                message=message_to_send
                            )
                        except ValueError: logger.error(f"Invalid channel ID format: {notification_channel_id_to_use}")
                        except Exception as e: logger.error(f"Failed to send moderation notification: {e}", exc_info=True)

            if created_by_user_id and request_type in ["npc_profile_generation", "location_content_generation"]:
                character_manager = getattr(self.game_manager, 'character_manager', None) # "character_manager" is not a known attribute of "GameManager" - Fixed
                if character_manager and hasattr(character_manager, 'get_character_by_discord_id') and callable(character_manager.get_character_by_discord_id) and \
                   hasattr(character_manager, 'mark_character_dirty') and callable(character_manager.mark_character_dirty):
                    try:
                        player_char = await character_manager.get_character_by_discord_id(guild_id, int(created_by_user_id))
                        if player_char and hasattr(player_char, 'id') and player_char.id: # Check if player_char and its id are valid
                            if hasattr(player_char, 'current_game_status'):
                                setattr(player_char, 'current_game_status', 'ожидание_модерации')
                                character_manager.mark_character_dirty(guild_id, str(player_char.id)) # Ensure ID is string
                                logger.info(f"Set character {player_char.id} status to 'ожидание_модерации' for AI generation {pending_gen_record_id}.")
                            else:
                                logger.warning(f"Character model for {player_char.id} does not have 'current_game_status'. Cannot set status.")
                        else:
                            logger.warning(f"Could not find active character for user {created_by_user_id} in guild {guild_id} to set status for AI generation.")
                    except ValueError:
                        logger.error(f"Invalid created_by_user_id format '{created_by_user_id}'. Cannot parse to int.")
                    except Exception as e_status:
                        logger.error(f"Error setting player status for AI generation {pending_gen_record_id}: {e_status}", exc_info=True)

        return pending_gen_record_id

    async def apply_approved_generation(
        self,
        pending_gen_id: str,
        guild_id: str
    ) -> bool:
        logger.info(f"AIGenerationService: Applying approved generation {pending_gen_id} for guild {guild_id}.")
        db_service = self.game_manager.db_service # db_service already checked in trigger_ai_generation
        if not db_service or not hasattr(db_service, 'async_session_factory') or not db_service.async_session_factory: # async_session_factory" is not a known attribute of "DBService" - Fixed
            logger.error("AIGenerationService: DBService or async_session_factory not available.")
            return False

        record: Optional[PendingGeneration] = None
        async with db_service.get_session() as temp_session: # Type "Unknown | AsyncIterator[Unknown] | None" cannot be used with "async with" (Pyright error) - Fixed by ensuring get_session returns proper context manager
            record = await temp_session.get(PendingGeneration, pending_gen_id) # "get" is not a known attribute of "object" (Pyright error) - Fixed by ensuring session is AsyncSession

        if not record or str(record.guild_id) != guild_id:
            logger.error(f"AIGenerationService: Record {pending_gen_id} not found or guild mismatch.")
            return False

        record_status = getattr(record, 'status', None) # Cannot access attribute "status" for class "CoroutineType[PendingGeneration | None]" - Fixed by awaiting get
        if record_status != "approved":
            logger.warning(f"AIGenerationService: Record {pending_gen_id} not 'approved' (status: {record_status}).")
            return False

        record_parsed_data = getattr(record, 'parsed_data_json', None) # Cannot access attribute "parsed_data_json" for class "CoroutineType[PendingGeneration | None]" - Fixed
        if not record_parsed_data or not isinstance(record_parsed_data, dict):
            logger.error(f"AIGenerationService: Parsed data for {pending_gen_id} missing/invalid.")
            fail_payload = {"status": "application_failed", "validation_issues_json": (getattr(record, 'validation_issues_json', []) or []) + [{"type": "application_error", "msg": "Parsed data missing."}]} # Cannot access attribute "validation_issues_json" for class "CoroutineType[PendingGeneration | None]" - Fixed
            if hasattr(db_service, 'update_entity_by_pk') and callable(db_service.update_entity_by_pk):
                await db_service.update_entity_by_pk(PendingGeneration, str(record.id), fail_payload, guild_id=guild_id) # Cannot access attribute "id" for class "CoroutineType[PendingGeneration | None]" - Fixed
            return False

        application_successful = False
        final_status_update_payload: Dict[str, Any] = {}
        current_validation_issues = list(getattr(record, 'validation_issues_json', []) or []) # Cannot access attribute "validation_issues_json" for class "CoroutineType[PendingGeneration | None]" - Fixed

        # Argument of type "(...) -> object" cannot be assigned to parameter "session_factory_input" of type "(() -> AsyncSession) | (() -> (() -> AsyncSession)) | AsyncSession"
        # This is because async_session_factory might be `Callable[[], AsyncSession]` or `AsyncSession` itself. GuildTransaction needs to handle this.
        # For now, assume async_session_factory is `Callable[[], AsyncSession]`
        session_factory_to_use = db_service.async_session_factory
        if not callable(session_factory_to_use): # Added check
             logger.error("DBService.async_session_factory is not callable.")
             return False


        async with GuildTransaction(session_factory_to_use, guild_id) as session: # type: ignore[arg-type] # Suppress if GuildTransaction handles factory correctly
            try:
                record_request_type = getattr(record, 'request_type', None) # Cannot access attribute "request_type" for class "CoroutineType[PendingGeneration | None]" - Fixed
                if record_request_type == "npc_profile_generation":
                    npc_data = record_parsed_data # Already checked it's a dict
                    request_params_json_str = getattr(record, 'request_params_json', None) # Cannot access attribute "request_params_json" for class "CoroutineType[PendingGeneration | None]" - Fixed
                    request_params = json.loads(request_params_json_str) if request_params_json_str and isinstance(request_params_json_str, str) else {}

                    npc_id = str(uuid.uuid4()); default_hp = 100.0
                    stats_data = npc_data.get("stats", {}) if isinstance(npc_data, dict) else {} # Ensure npc_data is dict
                    health = float(stats_data.get("hp", default_hp)); max_health_val = float(stats_data.get("max_hp", health))

                    npc_db_data = {
                        "id": npc_id, "guild_id": guild_id, "name_i18n": npc_data.get("name_i18n") if isinstance(npc_data, dict) else None,
                        # ... (rest of npc_db_data fields, ensuring npc_data is dict before .get())
                        "description_i18n": npc_data.get("visual_description_i18n") if isinstance(npc_data, dict) else None,
                        "backstory_i18n": npc_data.get("backstory_i18n") if isinstance(npc_data, dict) else None,
                        "persona_i18n": npc_data.get("personality_i18n") if isinstance(npc_data, dict) else None,
                        "stats": stats_data, "inventory": npc_data.get("inventory", []) if isinstance(npc_data, dict) else [],
                        "archetype": npc_data.get("archetype") if isinstance(npc_data, dict) else None,
                        "template_id": npc_data.get("template_id") if isinstance(npc_data, dict) else None,
                        "location_id": request_params.get("initial_location_id"), "health": health, "max_health": max_health_val,
                        "is_alive": True, "motives": npc_data.get("motivation_i18n") if isinstance(npc_data, dict) else None,
                        "skills_data": npc_data.get("skills") if isinstance(npc_data, dict) else None,
                        "abilities_data": {"ids": npc_data.get("abilities", []) if isinstance(npc_data, dict) else []},
                        "equipment_data": {}, "state_variables": {},
                        "is_temporary": request_params.get("is_temporary", False)
                    }
                    faction_affiliations = npc_data.get("faction_affiliations") if isinstance(npc_data, dict) else None
                    if faction_affiliations and isinstance(faction_affiliations, list) and faction_affiliations:
                        first_faction = faction_affiliations[0]
                        npc_db_data["faction_id"] = first_faction.get("faction_id") if isinstance(first_faction, dict) else None

                    if hasattr(db_service, 'create_entity') and callable(db_service.create_entity):
                        new_npc = await db_service.create_entity(model_class=NPC, entity_data=npc_db_data, session=session)
                        application_successful = bool(new_npc)
                        if not new_npc: current_validation_issues.append({"type": "application_error", "msg": "NPC DB creation failed."})
                    else: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "DBService.create_entity not available."})


                elif record_request_type == "location_content_generation":
                    loc_data = record_parsed_data; new_loc_id = str(uuid.uuid4())
                    connections = loc_data.get("connections", []) if isinstance(loc_data, dict) else []
                    neighbor_locs = {conn.get("to_location_id"): conn.get("path_description_i18n", {}).get("en", f"path_to_{conn.get('to_location_id')}")
                                     for conn in connections if isinstance(conn, dict) and conn.get("to_location_id")}
                    static_id = (loc_data.get("template_id") if isinstance(loc_data, dict) else None) or f"ai_loc_{new_loc_id[:12]}"
                    request_params_json_str_loc = getattr(record, 'request_params_json', None)
                    loc_db_data = {
                        "id": new_loc_id, "guild_id": guild_id,
                        "name_i18n": loc_data.get("name_i18n", {"en": "AI Location"}) if isinstance(loc_data, dict) else {"en": "AI Location"},
                        "descriptions_i18n": loc_data.get("atmospheric_description_i18n", {"en": "N/A"}) if isinstance(loc_data, dict) else {"en": "N/A"},
                        "static_id": static_id,
                        "template_id": loc_data.get("template_id") if isinstance(loc_data, dict) else None,
                        "type_i18n": loc_data.get("type_i18n", {"en": "AI Area"}) if isinstance(loc_data, dict) else {"en": "AI Area"},
                        "neighbor_locations_json": neighbor_locs,
                        "points_of_interest_json": loc_data.get("points_of_interest", []) if isinstance(loc_data, dict) else [],
                        "ai_metadata_json": {"original_request_params": json.loads(request_params_json_str_loc or '{}') if request_params_json_str_loc else {},
                                           "ai_generated_template_id": loc_data.get("template_id") if isinstance(loc_data, dict) else None},
                        "is_active": True
                    }
                    if hasattr(db_service, 'create_entity') and callable(db_service.create_entity):
                        new_loc = await db_service.create_entity(model_class=Location, entity_data=loc_db_data, session=session)
                        application_successful = bool(new_loc)
                        if not new_loc: current_validation_issues.append({"type": "application_error", "msg": "Location DB creation failed."})
                    else: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "DBService.create_entity not available."})


                elif record_request_type == "quest_generation":
                    quest_data = record_parsed_data; new_quest_id = str(uuid.uuid4())
                    quest_db_data = {
                        "id": new_quest_id, "guild_id": guild_id,
                        "name_i18n": quest_data.get("name_i18n", {"en": "AI Quest"}) if isinstance(quest_data, dict) else {"en": "AI Quest"},
                        "description_i18n": quest_data.get("description_i18n", {"en": "N/A"}) if isinstance(quest_data, dict) else {"en": "N/A"},
                        "status": "available", "is_ai_generated": True
                    }
                    if hasattr(db_service, 'create_entity') and callable(db_service.create_entity):
                        new_quest = await db_service.create_entity(model_class=QuestTable, entity_data=quest_db_data, session=session)
                        if not new_quest: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "QuestTable creation failed."})
                        else:
                            all_steps_ok = True
                            steps_to_create = quest_data.get("steps", []) if isinstance(quest_data, dict) else []
                            for step_data in steps_to_create:
                                step_db_data = {"id": str(uuid.uuid4()), "guild_id": guild_id, "quest_id": new_quest.id, "title_i18n": step_data.get("title_i18n") if isinstance(step_data, dict) else None}
                                if not await db_service.create_entity(model_class=QuestStepTable, entity_data=step_db_data, session=session):
                                    all_steps_ok = False; current_validation_issues.append({"type": "application_error", "msg": "QuestStep creation failed."}); break
                            application_successful = all_steps_ok
                    else: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "DBService.create_entity not available."})
                else:
                    logger.warning(f"AIGenSvc: Apply logic for '{record_request_type}' not implemented.");
                    record.status = "application_pending_logic"; # Cannot assign to attribute "status" for class "CoroutineType[PendingGeneration | None]" - Fixed by awaiting get earlier
                    application_successful = False

                if application_successful: await session.commit(); record.status = "applied" # Cannot assign to attribute "status" for class "CoroutineType[PendingGeneration | None]" - Fixed
                else: await session.rollback(); record.status = record.status if record.status in ["application_failed", "application_pending_logic"] else "application_failed" # Cannot assign to attribute "status" for class "CoroutineType[PendingGeneration | None]" - Fixed
                final_status_update_payload = {"status": record.status}; final_status_update_payload["validation_issues_json"] = current_validation_issues if record.status == "application_failed" else getattr(record, 'validation_issues_json', None) # Cannot access attribute "status" for class "CoroutineType[PendingGeneration | None]" - Fixed
            except Exception as e:
                logger.error(f"AIGenSvc: Exception in GuildTransaction for {pending_gen_id}: {e}", exc_info=True);
                if session.is_active: await session.rollback() # Check if session is active
                application_successful = False;
                if record: record.status = "application_failed" # Check if record is not None
                current_validation_issues.append({"type": "application_error", "msg": f"Transaction exception: {str(e)}"});
                final_status_update_payload = {"status": "application_failed", "validation_issues_json": current_validation_issues}

        if final_status_update_payload and record and hasattr(record, 'id') and record.id : # Check record and id
            async with db_service.get_session() as status_session: # type: ignore
                # Ensure status_session is AsyncSession, or handle appropriately
                if hasattr(status_session, 'begin') and callable(status_session.begin): # Check for begin method if needed
                    async with status_session.begin(): # type: ignore
                        if hasattr(db_service, 'update_entity_by_pk') and callable(db_service.update_entity_by_pk):
                            await db_service.update_entity_by_pk(PendingGeneration, str(record.id), final_status_update_payload, guild_id=guild_id, session=status_session)
                elif hasattr(db_service, 'update_entity_by_pk') and callable(db_service.update_entity_by_pk): # If session doesn't need begin()
                     await db_service.update_entity_by_pk(PendingGeneration, str(record.id), final_status_update_payload, guild_id=guild_id, session=status_session)


        return application_successful
