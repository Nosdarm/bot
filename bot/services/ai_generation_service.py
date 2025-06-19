# bot/services/ai_generation_service.py
import json
import uuid
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, List

# Assuming models are accessible via bot.database.models after refactoring
from bot.database.models import PendingGeneration, GuildConfig, NPC, Location, QuestTable, QuestStepTable
from bot.ai.ai_response_validator import parse_and_validate_ai_response
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
        # Direct access to managers/services via game_manager instance
        # e.g., self.game_manager.db_service, self.game_manager.npc_manager

    async def trigger_ai_generation(
        self,
        guild_id: str,
        request_type: str,
        request_params: Dict[str, Any],
        created_by_user_id: Optional[str] = None
    ) -> Optional[str]:
        logger.info(f"AIGenerationService: Triggering AI generation for guild {guild_id}, type '{request_type}'.")

        if not all([
            self.game_manager.multilingual_prompt_generator,
            self.game_manager.openai_service,
            self.game_manager.db_service,
            self.game_manager.ai_response_validator # Ensure this is initialized in GameManager
        ]):
            logger.error("AIGenerationService: Core AI services (prompt_generator, openai, db_service, ai_validator) not fully available.")
            return None

        specific_task_instruction = ""
        if request_type == "location_content_generation":
            specific_task_instruction = "Generate detailed content for a game location based on the provided context and parameters, including name, atmospheric description, points of interest, and connections."
        elif request_type == "npc_profile_generation":
            specific_task_instruction = "Generate a complete NPC profile based on the provided context and parameters, including template_id, name, role, archetype, backstory, personality, motivation, visual description, dialogue hints, stats, skills, abilities, spells, inventory, faction affiliations, and relationships."
        elif request_type == "quest_generation":
            specific_task_instruction = "Generate a complete quest structure based on the provided context and parameters, including name, description, steps (with mechanics, goals, consequences), overall consequences, and prerequisites."
        else:
            specific_task_instruction = "Perform the requested AI generation task based on the provided context and parameters."

        location_id_for_prompt = request_params.get("location_id")

        prompt_str = await self.game_manager.multilingual_prompt_generator.prepare_ai_prompt(
            guild_id=guild_id,
            location_id=str(location_id_for_prompt) if location_id_for_prompt else "",
            player_id=request_params.get("player_id"),
            party_id=request_params.get("party_id"),
            specific_task_instruction=specific_task_instruction,
            additional_request_params=request_params
        )

        raw_ai_output = await self.game_manager.openai_service.get_completion(prompt_str)

        pending_status = "pending_validation"
        parsed_data_dict: Optional[Dict[str, Any]] = None
        validation_issues_list: Optional[List[Dict[str, Any]]] = None

        if not raw_ai_output:
            logger.error(f"AIGenerationService: AI generation failed for type '{request_type}', guild {guild_id}. No output from OpenAI service.")
            pending_status = "failed_validation"
            validation_issues_list = [{"type": "generation_error", "msg": "AI service returned no output."}]
        else:
            # parse_and_validate_ai_response might need game_manager or specific managers
            parsed_data_dict, validation_issues_list = await parse_and_validate_ai_response(
                raw_ai_output_text=raw_ai_output,
                guild_id=guild_id,
                request_type=request_type,
                game_manager=self.game_manager # Pass GameManager instance
            )
            if validation_issues_list:
                pending_status = "failed_validation"
            else:
                pending_status = "pending_moderation"

        pending_gen_data = {
            "id": str(uuid.uuid4()), # Ensure ID is generated here
            "guild_id": guild_id,
            "request_type": request_type,
            "request_params_json": json.dumps(request_params) if request_params else None,
            "raw_ai_output_text": raw_ai_output,
            "parsed_data_json": parsed_data_dict,
            "validation_issues_json": validation_issues_list,
            "status": pending_status,
            "created_by_user_id": created_by_user_id
        }

        pending_gen_record = await self.game_manager.db_service.create_entity(
            model_class=PendingGeneration,
            entity_data=pending_gen_data
        )

        if not pending_gen_record or not pending_gen_record.id:
            logger.error(f"AIGenerationService: Failed to create PendingGeneration record in DB for type '{request_type}', guild {guild_id}.")
            return None

        logger.info(f"AIGenerationService: PendingGeneration record {pending_gen_record.id} created with status '{pending_status}'.")

        if pending_status == "pending_moderation" and self.game_manager.notification_service:
            guild_config_obj: Optional[GuildConfig] = await self.game_manager.db_service.get_entity_by_pk(GuildConfig, pk_value=guild_id)
            if guild_config_obj:
                notification_channel_id_to_use = guild_config_obj.notification_channel_id or \
                                                 guild_config_obj.master_channel_id or \
                                                 guild_config_obj.system_channel_id
                if notification_channel_id_to_use:
                    try:
                        message_to_send = f"🔔 New AI Content (Type: '{pending_gen_record.request_type}', ID: `{pending_gen_record.id}`) is awaiting moderation. Use `/master review_ai id:{pending_gen_record.id}` to review."
                        await self.game_manager.notification_service.send_notification(
                            target_channel_id=int(notification_channel_id_to_use),
                            message=message_to_send
                        )
                    except ValueError: logger.error(f"Invalid channel ID format: {notification_channel_id_to_use}")
                    except Exception as e: logger.error(f"Failed to send moderation notification: {e}", exc_info=True)
        return pending_gen_record.id

    async def apply_approved_generation(
        self,
        pending_gen_id: str,
        guild_id: str
    ) -> bool:
        logger.info(f"AIGenerationService: Applying approved generation {pending_gen_id} for guild {guild_id}.")
        db_service = self.game_manager.db_service
        if not db_service or not db_service.async_session_factory:
            logger.error("AIGenerationService: DBService not available.")
            return False

        async with db_service.get_session() as temp_session: # type: ignore
            record: Optional[PendingGeneration] = await temp_session.get(PendingGeneration, pending_gen_id)

        if not record or str(record.guild_id) != guild_id:
            logger.error(f"AIGenerationService: Record {pending_gen_id} not found or guild mismatch.")
            return False
        if record.status != "approved":
            logger.warning(f"AIGenerationService: Record {pending_gen_id} not 'approved' (status: {record.status}).")
            return False
        if not record.parsed_data_json or not isinstance(record.parsed_data_json, dict):
            logger.error(f"AIGenerationService: Parsed data for {pending_gen_id} missing/invalid.")
            fail_payload = {"status": "application_failed", "validation_issues_json": (record.validation_issues_json or []) + [{"type": "application_error", "msg": "Parsed data missing."}]}
            await db_service.update_entity_by_pk(PendingGeneration, record.id, fail_payload, guild_id=guild_id)
            return False

        application_successful = False
        final_status_update_payload: Dict[str, Any] = {}
        current_validation_issues = list(record.validation_issues_json or [])

        async with GuildTransaction(db_service.async_session_factory, guild_id, commit_on_exit=False) as session:
            try:
                if record.request_type == "npc_profile_generation":
                    npc_data = record.parsed_data_json
                    request_params = json.loads(record.request_params_json) if record.request_params_json else {}
                    npc_id = str(uuid.uuid4()); default_hp = 100.0
                    stats_data = npc_data.get("stats", {}); health = float(stats_data.get("hp", default_hp)); max_health_val = float(stats_data.get("max_hp", health))
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
                    new_npc = await db_service.create_entity(model_class=NPC, entity_data=npc_db_data, session=session)
                    application_successful = bool(new_npc)
                    if not new_npc: current_validation_issues.append({"type": "application_error", "msg": "NPC DB creation failed."})

                elif record.request_type == "location_content_generation":
                    loc_data = record.parsed_data_json; new_loc_id = str(uuid.uuid4())
                    neighbor_locs = {conn.get("to_location_id"): conn.get("path_description_i18n", {}).get("en", f"path_to_{conn.get('to_location_id')}")
                                     for conn in loc_data.get("connections", []) if isinstance(conn, dict) and conn.get("to_location_id")}
                    static_id = loc_data.get("template_id") or f"ai_loc_{new_loc_id[:12]}"
                    loc_db_data = {
                        "id": new_loc_id, "guild_id": guild_id, "name_i18n": loc_data.get("name_i18n", {"en": "AI Location"}),
                        "descriptions_i18n": loc_data.get("atmospheric_description_i18n", {"en": "N/A"}), "static_id": static_id,
                        "template_id": loc_data.get("template_id"), "type_i18n": loc_data.get("type_i18n", {"en": "AI Area"}),
                        "neighbor_locations_json": neighbor_locs, "points_of_interest_json": loc_data.get("points_of_interest", []),
                        "ai_metadata_json": {"original_request_params": json.loads(record.request_params_json or '{}'), "ai_generated_template_id": loc_data.get("template_id")},
                        "is_active": True
                    }
                    new_loc = await db_service.create_entity(model_class=Location, entity_data=loc_db_data, session=session)
                    application_successful = bool(new_loc)
                    if not new_loc: current_validation_issues.append({"type": "application_error", "msg": "Location DB creation failed."})

                elif record.request_type == "quest_generation":
                    quest_data = record.parsed_data_json; new_quest_id = str(uuid.uuid4())
                    quest_db_data = {
                        "id": new_quest_id, "guild_id": guild_id, "name_i18n": quest_data.get("name_i18n", {"en": "AI Quest"}),
                        "description_i18n": quest_data.get("description_i18n", {"en": "N/A"}), "status": "available",
                        "is_ai_generated": True # Other fields from model as needed
                    }
                    new_quest = await db_service.create_entity(model_class=QuestTable, entity_data=quest_db_data, session=session)
                    if not new_quest: application_successful = False; current_validation_issues.append({"type": "application_error", "msg": "QuestTable creation failed."})
                    else:
                        all_steps_ok = True
                        for step_data in quest_data.get("steps", []):
                            step_db_data = {"id": str(uuid.uuid4()), "guild_id": guild_id, "quest_id": new_quest.id, "title_i18n": step_data.get("title_i18n")} # Simplified
                            if not await db_service.create_entity(model_class=QuestStepTable, entity_data=step_db_data, session=session):
                                all_steps_ok = False; current_validation_issues.append({"type": "application_error", "msg": "QuestStep creation failed."}); break
                        application_successful = all_steps_ok
                else:
                    logger.warning(f"AIGenSvc: Apply logic for '{record.request_type}' not implemented."); record.status = "application_pending_logic"; application_successful = False

                if application_successful: await session.commit(); record.status = "applied"
                else: await session.rollback(); record.status = record.status if record.status in ["application_failed", "application_pending_logic"] else "application_failed"
                final_status_update_payload = {"status": record.status}; final_status_update_payload["validation_issues_json"] = current_validation_issues if record.status == "application_failed" else record.validation_issues_json
            except Exception as e:
                logger.error(f"AIGenSvc: Exception in GuildTransaction for {pending_gen_id}: {e}", exc_info=True); await session.rollback(); application_successful = False; record.status = "application_failed"; current_validation_issues.append({"type": "application_error", "msg": f"Transaction exception: {str(e)}"}); final_status_update_payload = {"status": "application_failed", "validation_issues_json": current_validation_issues}

        if final_status_update_payload:
            async with db_service.get_session() as status_session: # type: ignore
                async with status_session.begin(): # type: ignore
                    await db_service.update_entity_by_pk(PendingGeneration, record.id, final_status_update_payload, guild_id=guild_id, session=status_session)
        return application_successful
