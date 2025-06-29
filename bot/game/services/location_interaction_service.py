import logging
import random
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING, Callable, Awaitable, cast

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Player, Location, Character as CharacterDBModel, Party as PartyDBModel # Use specific DB model names
from bot.game.models.character import Character as CharacterPydanticModel # Pydantic model
from bot.game.models.location import Location as LocationPydanticModel # Pydantic model for location_obj

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.services.db_service import DBService
    from bot.services.notification_service import NotificationService
    from bot.game.check_framework.check_resolver import CheckResolver # For type hint
    from bot.game.services.consequence_processor import ConsequenceProcessor # For type hint
    from bot.ai.rules_schema import CoreGameRulesConfig, LocationInteractionRule # For type hint

logger = logging.getLogger(__name__)
SendToChannelCallback = Callable[[str], Awaitable[Any]] # Simplified: assumes callback takes only message string

class LocationInteractionService:
    def __init__(self, location_manager: "LocationManager", character_manager: "CharacterManager", npc_manager: "NpcManager"):
        self.location_manager = location_manager
        self.character_manager = character_manager
        self.npc_manager = npc_manager
        logger.info("LocationInteractionService initialized.")

    async def process_on_enter_location_events(self, guild_id: str, entity_id: str, entity_type: str, location_id: str) -> None:
        logger.info(f"LIS: Entity {entity_id} (Type: {entity_type}) entered loc {location_id} in guild {guild_id}.")

        loc_mgr: Optional["LocationManager"] = getattr(self.game_manager, 'location_manager', None)
        char_mgr: Optional["CharacterManager"] = getattr(self.game_manager, 'character_manager', None)
        db_svc: Optional["DBService"] = getattr(self.game_manager, 'db_service', None)
        party_mgr: Optional["PartyManager"] = getattr(self.game_manager, 'party_manager', None)
        item_mgr: Optional["ItemManager"] = getattr(self.game_manager, 'item_manager', None)
        npc_mgr: Optional["NpcManager"] = getattr(self.game_manager, 'npc_manager', None)
        status_mgr: Optional["StatusManager"] = getattr(self.game_manager, 'status_manager', None)


        if not loc_mgr or not char_mgr or not db_svc:
            logger.error(f"LIS: Essential managers NA for guild {guild_id}. Aborting on_enter for loc {location_id}.")
            return

        location_obj_pydantic: Optional[LocationPydanticModel] = loc_mgr.get_location_instance(guild_id, location_id)
        if not location_obj_pydantic:
            logger.warning(f"LIS: Location {location_id} (Pydantic) not found for guild {guild_id}.")
            return

        on_enter_events = getattr(location_obj_pydantic, 'on_enter_events_json', [])
        if not isinstance(on_enter_events, list) or not on_enter_events:
            logger.debug(f"LIS: No on_enter_events for location {location_id} in guild {guild_id}.")
            return

        acting_char_db: Optional[CharacterDBModel] = None
        player_language = "en" # Default

        async with db_svc.get_session() as session_context:
            session = cast(AsyncSession, session_context)
            if entity_type == "Character":
                acting_char_db = await session.get(CharacterDBModel, entity_id)
                if not (acting_char_db and str(acting_char_db.guild_id) == guild_id):
                    logger.error(f"LIS: Character {entity_id} DB model not found in guild {guild_id}.")
                    acting_char_db = None
            elif entity_type == "Party" and party_mgr:
                party_obj_db = await session.get(PartyDBModel, entity_id)
                if party_obj_db and str(party_obj_db.guild_id) == guild_id and party_obj_db.leader_id:
                    acting_char_db = await session.get(CharacterDBModel, str(party_obj_db.leader_id))
                    if not (acting_char_db and str(acting_char_db.guild_id) == guild_id): acting_char_db = None

            if acting_char_db and getattr(acting_char_db, 'player_id', None):
                player_account_db = await session.get(Player, str(acting_char_db.player_id))
                if player_account_db and getattr(player_account_db, 'selected_language', None):
                    player_language = str(player_account_db.selected_language)

        send_callback: SendToChannelCallback = lambda m: logger.info(f"[LOG_SEND_NO_CB_DEF] Loc {location_id}: {m}")
        if hasattr(location_obj_pydantic, 'channel_id') and location_obj_pydantic.channel_id and \
           hasattr(self.game_manager, '_get_discord_send_callback') and callable(getattr(self.game_manager, '_get_discord_send_callback')):
            try:
                send_callback_method = getattr(self.game_manager, '_get_discord_send_callback')
                send_callback = send_callback_method(int(location_obj_pydantic.channel_id)) # type: ignore
            except ValueError: logger.error(f"LIS: Invalid channel_id format '{location_obj_pydantic.channel_id}'.")

        for event_config in on_enter_events:
            if not isinstance(event_config, dict): continue
            if random.random() > float(event_config.get("chance", 1.0)): continue

            event_type = event_config.get("event_type")
            message_i18n: Dict[str, str] = event_config.get("message_i18n", {})
            localized_message = message_i18n.get(player_language, message_i18n.get("en", "An event occurs."))

            if event_type == "AMBIENT_MESSAGE":
                await send_callback(localized_message)
            elif event_type == "ITEM_DISCOVERY":
                if not acting_char_db or not item_mgr or not hasattr(self.game_manager, 'inventory_manager'): continue # inventory_manager is on game_manager
                inv_mgr = cast("InventoryManager", getattr(self.game_manager, 'inventory_manager'))
                if not inv_mgr or not hasattr(inv_mgr, 'give_item_to_character_by_template_id'): continue

                items_to_grant = event_config.get("items", []); discovered_item_names = []
                for item_info in items_to_grant:
                    template_id = item_info.get("item_template_id"); quantity = int(item_info.get("quantity", 1))
                    if template_id and hasattr(acting_char_db, 'id'):
                        grant_success = await inv_mgr.give_item_to_character_by_template_id(guild_id, str(acting_char_db.id), template_id, quantity)
                        if grant_success:
                            item_template_obj = item_mgr.get_item_template(template_id) # Assuming sync
                            item_name = getattr(item_template_obj, 'name_i18n', {}).get(player_language, template_id) if item_template_obj else template_id
                            discovered_item_names.append(f"{quantity}x {item_name}")
                if discovered_item_names: await send_callback(localized_message.replace("[item_name]", ", ".join(discovered_item_names)).replace("[items_list]", ", ".join(discovered_item_names)))
            elif event_type == "NPC_APPEARANCE":
                if not npc_mgr or not hasattr(npc_mgr, 'spawn_npc_from_template'): continue
                npc_tpl_id = event_config.get("npc_template_id"); spawn_count = int(event_config.get("spawn_count", 1))
                if npc_tpl_id:
                    # Actual spawning logic: await npc_mgr.spawn_npc_from_template(guild_id, npc_tpl_id, location_id, count=spawn_count)
                    logger.info(f"LIS: NPC_APPEARANCE: NPC template {npc_tpl_id} (x{spawn_count}) would spawn in {location_id}.")
                    npc_tpl_obj = npc_mgr.get_npc_template(guild_id, npc_tpl_id) # Assuming sync
                    npc_name = getattr(npc_tpl_obj, 'name_i18n', {}).get(player_language, npc_tpl_id) if npc_tpl_obj else npc_tpl_id
                    await send_callback(localized_message.replace("[npc_name]", npc_name).replace("[npc_count]", str(spawn_count)))
            elif event_type == "SIMPLE_HAZARD":
                if not acting_char_db: continue
                effect_type = event_config.get("effect_type")
                if effect_type == "damage":
                    if not char_mgr or not hasattr(char_mgr, 'update_health'): continue
                    amount = float(event_config.get("damage_amount", 0)); damage_type = str(event_config.get("damage_type", "generic"))
                    await char_mgr.update_health(guild_id, str(acting_char_db.id), -amount) # Negative for damage
                    await send_callback(localized_message.replace("[damage_amount]", str(amount)).replace("[damage_type]", damage_type))
                elif effect_type == "status_effect":
                    if not status_mgr or not hasattr(status_mgr, 'apply_status_effect'): continue
                    status_id = event_config.get("status_effect_id")
                    if status_id and hasattr(acting_char_db, 'id'):
                        await status_mgr.apply_status_effect(guild_id, str(acting_char_db.id), "Character", status_id)
                        await send_callback(localized_message.replace("[status_effect_name]", status_id))
                else: await send_callback(localized_message)
            else: logger.warning(f"LIS: Unknown event_type '{event_type}' in location {location_id}.")

    async def handle_intra_location_action(
        self, guild_id: str, character_id: str, action_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        log_prefix = f"IntraLocAction (Guild: {guild_id}, Char: {character_id})"
        logger.info(f"{log_prefix}: Received action. Data: {action_data}")

        if not self.game_manager: return False, "GameManager NA."
        db_svc: Optional["DBService"] = getattr(self.game_manager, 'db_service', None)
        rule_eng: Optional["RuleEngine"] = getattr(self.game_manager, 'rule_engine', None)
        inv_mgr: Optional["InventoryManager"] = getattr(self.game_manager, 'inventory_manager', None)
        check_res: Optional["CheckResolver"] = getattr(self.game_manager, 'check_resolver', None)
        cons_proc: Optional["ConsequenceProcessor"] = getattr(self.game_manager, 'consequence_processor', None)
        notif_svc: Optional["NotificationService"] = getattr(self.game_manager, 'notification_service', None)


        if not db_svc or not hasattr(db_svc, 'get_session') or not callable(db_svc.get_session):
            return False, "DBService NA."

        session_from_action = action_data.get("session")
        if not isinstance(session_from_action, AsyncSession) : # Check if it's a valid AsyncSession
            logger.error(f"{log_prefix}: DB session not provided or invalid in action_data.")
            return False, "Internal error: DB session missing/invalid."

        session = cast(AsyncSession, session_from_action)

        try:
            if not rule_eng or not hasattr(rule_eng, 'get_rules_config') or not callable(getattr(rule_eng, 'get_rules_config')):
                return False, "RuleEngine NA."
            rules_config: Optional["CoreGameRulesConfig"] = await rule_eng.get_rules_config(guild_id)
            if not rules_config: return False, "Game rules config missing."

            char_db_model = await session.get(CharacterDBModel, character_id)
            if not char_db_model or str(char_db_model.guild_id) != guild_id: return False, "Character data error."

            current_loc_id = getattr(char_db_model, 'current_location_id', None)
            if not current_loc_id: return False, "Your location is unknown."

            loc_db_model = await session.get(Location, str(current_loc_id))
            if not loc_db_model or str(loc_db_model.guild_id) != guild_id: return False, "Location data error."

            intent = action_data.get("intent"); target_id = action_data.get("target_id"); sub_target_id = action_data.get("sub_target_id")
            if not intent: return False, "Action intent unclear."

            logger.info(f"{log_prefix}: Char {char_db_model.id} attempts '{intent}' (target: {target_id}) in loc {loc_db_model.id}.")

            player_lang = str(getattr(char_db_model, 'selected_language', DEFAULT_BOT_LANGUAGE))
            interaction_def_key = str(target_id) if target_id else ""

            loc_interactions_rules: Optional[Dict[str, LocationInteractionRule]] = getattr(rules_config, 'location_interactions', None)
            interaction_rule: Optional[LocationInteractionRule] = loc_interactions_rules.get(interaction_def_key) if loc_interactions_rules else None


            if not interaction_rule and intent == "INTENT_EXAMINE_OBJECT":
                target_obj_name = str(target_id) if target_id else ""
                if not target_obj_name: return False, "What to examine?"

                loc_details_i18n: Optional[Dict[str, Any]] = getattr(loc_db_model, 'details_i18n', None)
                desc_to_send: Optional[str] = None
                if isinstance(loc_details_i18n, dict): # Check if it's a dict after loading
                    norm_key = target_obj_name.lower().strip().replace(" ", "_")
                    lang_details = loc_details_i18n.get(player_lang)
                    if isinstance(lang_details, dict): desc_to_send = lang_details.get(norm_key)
                    if not desc_to_send and player_lang != 'en':
                        en_details = loc_details_i18n.get('en')
                        if isinstance(en_details, dict): desc_to_send = en_details.get(norm_key)
                return (True, desc_to_send) if desc_to_send else (False, f"Nothing special about {target_obj_name}.")

            if not interaction_rule: return False, f"Cannot interact with '{target_id}' that way."

            if interaction_rule.required_items and inv_mgr and hasattr(inv_mgr, 'character_has_item_template'):
                for req_item_id in interaction_rule.required_items:
                    if not await inv_mgr.character_has_item_template(guild_id, character_id, req_item_id, session=session):
                        return False, f"You need {req_item_id} to do that." # TODO: Localize item name

            outcome_def: Optional[Dict[str, Any]] = None; check_passed = True
            if interaction_rule.check_type and check_res and hasattr(check_res, 'resolve_check'):
                check_result_obj = await check_res.resolve_check(guild_id, interaction_rule.check_type, character_id, "Character", dc=interaction_rule.success_dc) # Use success_dc
                check_passed = check_result_obj.succeeded
                if notif_svc and hasattr(notif_svc, 'send_character_feedback'):
                    await notif_svc.send_character_feedback(guild_id, character_id, check_result_obj.description, "check_result")

            final_outcome_rule = interaction_rule.success_outcome if check_passed else interaction_rule.failure_outcome
            if final_outcome_rule: outcome_def = final_outcome_rule.model_dump()

            if outcome_def and cons_proc and hasattr(cons_proc, 'process_consequences'):
                consequence_ctx = {"character_db": char_db_model, "location_db": loc_db_model, "interaction_target_id": target_id, "interaction_rule": interaction_rule.model_dump(), "session": session}
                await cons_proc.process_consequences(guild_id, [outcome_def], source_entity_id=character_id, target_entity_id=target_id, event_context=consequence_ctx)

                final_msg_i18n: Optional[Dict[str,str]] = outcome_def.get("message_i18n")
                final_msg = final_msg_i18n.get(player_lang, final_msg_i18n.get("en")) if final_msg_i18n else f"You interact with {target_id}."
                return True, final_msg

            return False, f"Interacting with {target_id} yields no result."
        except Exception as e:
            logger.error(f"{log_prefix}: Error: {e}", exc_info=True)
            return False, "Unexpected error during interaction."
