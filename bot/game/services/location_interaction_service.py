import logging
import random # Added for _on_enter_location logic
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession # Removed unused import

# Assuming models are accessible via bot.database.models after refactoring
from bot.database.models import Player, Location, Character, Party # Added Character, Party
from bot.database.crud_utils import get_entity_by_id

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager
    # Import other managers if needed for type hints within the new method
    # from bot.game.managers.item_manager import ItemManager
    # from bot.game.managers.npc_manager import NpcManager
    # from bot.game.managers.status_manager import StatusManager

logger = logging.getLogger(__name__)
SendToChannelCallback = Callable[..., Awaitable[Any]] # For _get_discord_send_callback type

class LocationInteractionService:
    def __init__(self, game_manager: "GameManager"):
        self.game_manager = game_manager
        if not self.game_manager:
            logger.critical("LocationInteractionService initialized without a valid GameManager instance!")
        logger.info("LocationInteractionService initialized.")

    async def process_on_enter_location_events(self, guild_id: str, entity_id: str, entity_type: str, location_id: str) -> None:
        """
        Handles logic to execute when an entity enters a location, processing defined on_enter_events.
        Moved from GameManager._on_enter_location.
        """
        logger.info(f"LIS: Entity {entity_id} (Type: {entity_type}) entered location {location_id} in guild {guild_id}.")

        if not self.game_manager.location_manager or \
           not self.game_manager.character_manager or \
           not self.game_manager.db_service:
            logger.error(f"LIS: Essential managers not available for guild {guild_id}. Aborting on_enter for loc {location_id}.")
            return

        location_obj = self.game_manager.location_manager.get_location_instance(guild_id, location_id)

        if not location_obj:
            logger.warning(f"LIS: Location {location_id} not found for guild {guild_id}.")
            return

        if not location_obj.on_enter_events_json or \
           not isinstance(location_obj.on_enter_events_json, list) or \
           not location_obj.on_enter_events_json:
            logger.debug(f"LIS: No on_enter_events for location {location_id} in guild {guild_id}.")
            return

        acting_character: Optional[Character] = None
        if entity_type == "Character":
            async with self.game_manager.db_service.get_session() as session: # type: ignore
                acting_character = await session.get(Character, entity_id)
                if not (acting_character and str(acting_character.guild_id) == guild_id):
                    logger.error(f"LIS: Character {entity_id} not found in guild {guild_id}.")
                    acting_character = None
        elif entity_type == "Party":
            if self.game_manager.party_manager:
                async with self.game_manager.db_service.get_session() as session: # type: ignore
                    party_obj_model = await session.get(Party, entity_id)
                    if party_obj_model and str(party_obj_model.guild_id) == guild_id and party_obj_model.leader_id:
                        acting_character = await session.get(Character, party_obj_model.leader_id)
                        if not (acting_character and str(acting_character.guild_id) == guild_id):
                            acting_character = None
                    # ... (logging for party not found or no leader)
            else: logger.warning("LIS: PartyManager not available for Party entry.")

        player_language = "en"
        if acting_character and acting_character.player_id:
            player_account = await self.game_manager.get_player_model_by_id(guild_id, acting_character.player_id)
            if player_account and player_account.selected_language:
                player_language = player_account.selected_language

        send_callback: SendToChannelCallback
        if location_obj.channel_id:
            try: send_callback = self.game_manager._get_discord_send_callback(int(location_obj.channel_id))
            except ValueError: logger.error(f"LIS: Invalid channel_id format '{location_obj.channel_id}'."); send_callback = lambda m, **k: logger.info(f"[LOG_SEND_ERROR_CHANNEL] Loc {location_id}: {m}") # type: ignore
        else: send_callback = lambda m, **k: logger.info(f"[LOG_SEND_NO_CHANNEL] Loc {location_id}: {m}") # type: ignore

        for event_config in location_obj.on_enter_events_json:
            if not isinstance(event_config, dict): continue
            if random.random() > event_config.get("chance", 1.0): continue

            event_type = event_config.get("event_type")
            message_i18n = event_config.get("message_i18n", {})
            localized_message = message_i18n.get(player_language, message_i18n.get("en", "An event occurs."))

            if event_type == "AMBIENT_MESSAGE":
                await send_callback(localized_message)
            elif event_type == "ITEM_DISCOVERY":
                if not acting_character or not self.game_manager.item_manager or not self.game_manager.inventory_manager: continue
                items_to_grant = event_config.get("items", []); discovered_item_names = []
                for item_info in items_to_grant:
                    template_id = item_info.get("item_template_id"); quantity = item_info.get("quantity", 1)
                    if template_id:
                        logger.info(f"LIS: ITEM_DISCOVERY: Char {acting_character.id} granted {quantity}x {template_id}."); grant_success = True # Placeholder
                        if grant_success:
                            item_template_obj = await self.game_manager.item_manager.get_item_template(guild_id, template_id)
                            item_name = item_template_obj.name_i18n.get(player_language, template_id) if item_template_obj else template_id
                            discovered_item_names.append(f"{quantity}x {item_name}")
                if discovered_item_names: await send_callback(localized_message.replace("[item_name]", ", ".join(discovered_item_names)).replace("[items_list]", ", ".join(discovered_item_names)))
            elif event_type == "NPC_APPEARANCE":
                if not self.game_manager.npc_manager: continue
                npc_template_id = event_config.get("npc_template_id"); spawn_count = event_config.get("spawn_count", 1)
                if npc_template_id:
                    logger.info(f"LIS: NPC_APPEARANCE: NPC template {npc_template_id} (x{spawn_count}) would spawn.") # Placeholder
                    npc_template_for_name = await self.game_manager.npc_manager.get_npc_template(guild_id, npc_template_id)
                    npc_name = npc_template_for_name.name_i18n.get(player_language, npc_template_id) if npc_template_for_name else npc_template_id
                    await send_callback(localized_message.replace("[npc_name]", npc_name).replace("[npc_count]", str(spawn_count)))
            elif event_type == "SIMPLE_HAZARD":
                if not acting_character: continue
                effect_type = event_config.get("effect_type")
                if effect_type == "damage":
                    if not self.game_manager.character_manager: continue
                    amount = event_config.get("damage_amount", 0); damage_type = event_config.get("damage_type", "generic")
                    logger.info(f"LIS: SIMPLE_HAZARD: Char {acting_character.id} takes {amount} {damage_type} damage.") # Placeholder
                    await send_callback(localized_message.replace("[damage_amount]", str(amount)).replace("[damage_type]", damage_type))
                elif effect_type == "status_effect":
                    if not self.game_manager.status_manager: continue
                    status_id = event_config.get("status_effect_id")
                    if status_id:
                        logger.info(f"LIS: SIMPLE_HAZARD: Char {acting_character.id} gets status {status_id}.") # Placeholder
                        await send_callback(localized_message.replace("[status_effect_name]", status_id))
                else: await send_callback(localized_message)
            else: logger.warning(f"LIS: Unknown event_type '{event_type}' in location {location_id}.")


    async def handle_intra_location_action(
        self,
        guild_id: str,
        player_id: str,
        action_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        log_prefix = f"IntraLocationAction (Guild: {guild_id}, Player: {player_id})"
        logger.info(f"{log_prefix}: Received action. Data: {action_data}")

        if not self.game_manager or not self.game_manager.db_service:
            logger.error(f"{log_prefix}: GameManager or DBService not available.")
            return False, "Core services are unavailable. Please try again later."

        db_service = self.game_manager.db_service

        # Method now expects an active session to be passed
        session: Optional[AsyncSession] = action_data.get("session") # Expect session in action_data
        if not session:
            logger.error(f"{log_prefix}: DB session not provided in action_data.")
            return False, "Internal error: Database session missing."

        try:
            # Load RuleConfig for the guild
            if not self.game_manager.rule_engine:
                logger.error(f"{log_prefix}: RuleEngine not available.")
                return False, "Game rules are currently unavailable."

            rules_config = await self.game_manager.rule_engine.get_rules_config(guild_id)
            if not rules_config:
                logger.error(f"{log_prefix}: Could not load RuleConfig for guild {guild_id}.")
                return False, "Game rules configuration is missing for this area."

            # Get active character (not Player DB model directly)
            character_model = await session.get(Character, player_id) # player_id is character_id
            if not character_model or str(character_model.guild_id) != guild_id:
                logger.warning(f"{log_prefix}: Character {player_id} not found or guild mismatch."); return False, "Character data error."

            if not character_model.current_location_id:
                logger.warning(f"{log_prefix}: Character {player_id} has no current_location_id."); return False, "Your location is unknown."

            location = await session.get(Location, character_model.current_location_id)
            if not location or str(location.guild_id) != guild_id:
                logger.warning(f"{log_prefix}: Current location {character_model.current_location_id} not found or guild mismatch."); return False, "Location data error."

            intent = action_data.get("intent") # e.g., "INTENT_EXAMINE_OBJECT", "INTENT_TAKE_ITEM_POI"
            # target_id might be POI_id, item_id within POI, etc.
            target_id = action_data.get("target_id") # This should be the ID of the POI or specific feature.
            # sub_target_id could be item_id if intent is to take item from a POI.
            sub_target_id = action_data.get("sub_target_id")

            if not intent: return False, "Your action's intent is unclear."

            location_name_for_log = location.name_i18n.get('en', location.id) if location.name_i18n else location.id
            logger.info(f"{log_prefix}: Character {character_model.id} attempts '{intent}' (target: {target_id}, sub_target: {sub_target_id}) in loc {location.id} ('{location_name_for_log}').")

            interaction_definition_key = target_id # POI_id or feature_id
            interaction_rule = rules_config.location_interactions.get(interaction_definition_key)

            if not interaction_rule and intent == "INTENT_EXAMINE_OBJECT": # Fallback for simple examine if no specific rule
                # This is the old logic, can be kept as a fallback or removed if all examines must be rule-based
                target_object_name = target_id # Assume target_id is the name for examine if no rule
                if not target_object_name: return False, "What exactly do you want to examine?"
                normalized_target_key = target_object_name.lower().strip().replace(" ", "_")
                player_lang = character_model.selected_language or await self.game_manager.get_rule(guild_id, 'default_language', 'en')
                description_to_send = None; description_found = False
                if location.details_i18n and isinstance(location.details_i18n, dict):
                    lang_specific_details = location.details_i18n.get(player_lang)
                    if isinstance(lang_specific_details, dict) and lang_specific_details.get(normalized_target_key):
                        description_to_send = lang_specific_details[normalized_target_key]; description_found = True
                    elif player_lang != 'en' and isinstance(location.details_i18n.get('en'), dict) and location.details_i18n['en'].get(normalized_target_key):
                        description_to_send = location.details_i18n['en'][normalized_target_key]; description_found = True
                if not description_found: return False, f"You look at the {target_object_name}, but find nothing special."
                return True, description_to_send

            if not interaction_rule:
                logger.warning(f"{log_prefix}: No interaction rule found for target '{interaction_definition_key}' in location '{location.id}'.")
                return False, f"You can't seem to interact with '{target_id}' in that way."

            # Check required items
            if interaction_rule.required_items:
                if not self.game_manager.inventory_manager:
                    logger.error(f"{log_prefix}: InventoryManager not available for checking required items."); return False, "Internal error: Inventory system unavailable."
                for req_item_template_id in interaction_rule.required_items:
                    if not await self.game_manager.inventory_manager.character_has_item_template(guild_id, character_model.id, req_item_template_id, session=session):
                        # TODO: Get localized item name for feedback
                        return False, f"You need a specific item ({req_item_template_id}) to do that."

            outcome_to_process: Optional[Dict[str, Any]] = None # This will be Pydantic LocationInteractionOutcome.model_dump()
            check_passed = True # Assume success if no check is required

            if interaction_rule.check_type:
                if not self.game_manager.check_resolver:
                    logger.error(f"{log_prefix}: CheckResolver not available for interaction check."); return False, "Internal error: Check system unavailable."

                # difficulty_dc might come from the interaction_rule itself, or be dynamic
                # For now, assume it's part of the rule or a default is used by CheckResolver
                check_result = await self.game_manager.check_resolver.resolve_check(
                    guild_id=guild_id,
                    check_type=interaction_rule.check_type,
                    performing_entity_id=character_model.id,
                    performing_entity_type="Character", # Assuming player character for now
                    difficulty_dc=interaction_rule.success_outcome.get("dc") # Example: DC might be on the outcome
                )
                check_passed = check_result.succeeded
                # TODO: Send feedback about the check result to the player
                if self.game_manager.notification_service:
                    await self.game_manager.notification_service.send_character_feedback(
                        guild_id, character_model.id, check_result.description, "check_result"
                    )

            outcome_definition = interaction_rule.success_outcome if check_passed else interaction_rule.failure_outcome
            if outcome_definition:
                outcome_to_process = outcome_definition.model_dump()

            if outcome_to_process:
                # Process consequences using ConsequenceProcessor
                if not self.game_manager.consequence_processor:
                    logger.error(f"{log_prefix}: ConsequenceProcessor not available."); return False, "Internal error: Consequence system unavailable."

                # Context for consequence processor
                consequence_context = {
                    "character": character_model, # Pass the SQLAlchemy model
                    "location": location,       # Pass the SQLAlchemy model
                    "interaction_target_id": target_id,
                    "interaction_rule": interaction_rule.model_dump(), # Pass rule data
                    "session": session # Pass the active session
                }

                # The outcome_to_process itself is the list of consequence instructions
                # The ConsequenceProcessor needs to be adapted to take this structure or iterate through it.
                # For now, let's assume a single outcome type is processed.
                # This needs to be a list of consequence dicts.
                # For a single outcome, wrap it in a list.
                consequences_to_apply = [outcome_to_process] # Wrap the single outcome

                # The ConsequenceProcessor.process_consequences expects a JSON string or a list of dicts.
                # We pass the list of dicts directly.
                await self.game_manager.consequence_processor.process_consequences(
                    guild_id=guild_id,
                    consequences_list=consequences_to_apply, # Pass the list of outcome dicts
                    context=consequence_context,
                    actor_id=character_model.id,
                    actor_type="Character"
                )

                # Message is now handled by ConsequenceProcessor if it's a 'display_message' type
                # If there's a specific message from the outcome, it should have been processed.
                # We can return a generic success/failure or a specific message if the outcome was just info.
                final_message = outcome_to_process.get("message_i18n", {}).get(character_model.selected_language or "en")
                if final_message:
                    return True, final_message
                return True, f"You interact with {target_id}. (Outcome processed)"

            return False, f"You interact with {target_id}, but nothing seems to happen."

        except Exception as e:
            logger.error(f"{log_prefix}: Error: {e}", exc_info=True)
            # Important: Do not rollback here if session was passed in. Caller handles it.
            return False, "An unexpected error occurred during interaction."
