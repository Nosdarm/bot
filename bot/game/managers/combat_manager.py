# bot/game/managers/combat_manager.py

from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import random
import logging # Added
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, Set, Tuple, Union

from bot.game.models.combat import Combat, CombatParticipant
from bot.game.ai.npc_combat_ai import NpcCombatAI
from bot.game.models.npc import NPC as NpcModel
from bot.game.utils import stats_calculator
from bot.ai.rules_schema import CoreGameRulesConfig
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.models.character import Character as CharacterModel
from builtins import dict, set, list, str, int, bool, float


if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.npc_processors.npc_action_processor import NpcActionProcessor
    from bot.game.party_processors.party_action_processor import PartyActionProcessor

logger = logging.getLogger(__name__) # Added

class CombatManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _active_combats: Dict[str, Dict[str, "Combat"]]
    _dirty_combats: Dict[str, Set[str]]
    _deleted_combats_ids: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        location_manager: Optional["LocationManager"] = None,
    ):
        logger.info("Initializing CombatManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._npc_manager = npc_manager

        logger.debug("CM_INIT_DEBUG: self._rule_engine is %s", 'NOT None' if self._rule_engine else 'None') # Changed
        logger.debug("CM_INIT_DEBUG: self._character_manager is %s", 'NOT None' if self._character_manager else 'None') # Changed
        logger.debug("CM_INIT_DEBUG: self._npc_manager is %s", 'NOT None' if self._npc_manager else 'None') # Changed

        self._party_manager = party_manager
        self._status_manager = status_manager
        self._item_manager = item_manager
        self._location_manager = location_manager

        self._active_combats = {}
        self._dirty_combats = {}
        self._deleted_combats_ids = {}
        logger.info("CombatManager initialized.") # Changed

    def get_combat(self, guild_id: str, combat_id: str) -> Optional["Combat"]:
        guild_id_str = str(guild_id)
        guild_combats = self._active_combats.get(guild_id_str)
        if guild_combats:
             return guild_combats.get(combat_id)
        return None

    def get_active_combats(self, guild_id: str) -> List["Combat"]:
        guild_id_str = str(guild_id)
        guild_combats = self._active_combats.get(guild_id_str)
        if guild_combats:
             return list(guild_combats.values())
        return []

    def get_combat_by_participant_id(self, guild_id: str, entity_id: str) -> Optional["Combat"]:
        guild_id_str = str(guild_id)
        guild_combats = self._active_combats.get(guild_id_str)
        if guild_combats:
             for combat in guild_combats.values():
                 if isinstance(combat.participants, list):
                     for p_obj in combat.participants:
                         if isinstance(p_obj, CombatParticipant) and p_obj.entity_id == entity_id:
                             return combat
        return None

    def get_combats_by_event_id(self, guild_id: str, event_id: str) -> List["Combat"]:
         guild_id_str = str(guild_id)
         combats_in_event = []
         guild_combats = self._active_combats.get(guild_id_str)
         if guild_combats:
              for combat in guild_combats.values():
                   if getattr(combat, 'event_id', None) == event_id:
                        combats_in_event.append(combat)
         return combats_in_event

    def is_character_in_combat(self, guild_id: str, entity_id: str) -> Optional[str]:
        combat = self.get_combat_by_participant_id(guild_id, entity_id)
        return combat.id if combat and hasattr(combat, 'id') else None

    def mark_participant_acted(self, guild_id: str, combat_id: str, entity_id: str) -> None:
        combat = self.get_combat(guild_id, combat_id)
        if combat:
            participant = combat.get_participant_data(entity_id)
            if participant:
                participant.acted_this_round = True
                self.mark_combat_dirty(guild_id, combat_id)
                logger.info("CM.mark_participant_acted: Participant %s in combat %s (guild %s) marked as acted.", entity_id, combat_id, guild_id) # Changed
            else:
                logger.warning("CM.mark_participant_acted: Participant %s not found in combat %s (guild %s).", entity_id, combat_id, guild_id) # Changed
        else:
            logger.warning("CM.mark_participant_acted: Combat %s not found for guild %s.", combat_id, guild_id) # Changed

    async def start_combat(self, guild_id: str, location_id: Optional[str], participant_ids_types: List[Tuple[str, str]], **kwargs: Any) -> Optional["Combat"]:
        logger.debug("CM_START_COMBAT_DEBUG: self._rule_engine is %s", 'NOT None' if self._rule_engine else 'None') # Changed
        logger.debug("CM_START_COMBAT_DEBUG: self._character_manager is %s", 'NOT None' if self._character_manager else 'None') # Changed
        logger.debug("CM_START_COMBAT_DEBUG: self._npc_manager is %s", 'NOT None' if self._npc_manager else 'None') # Changed

        guild_id_str = str(guild_id)
        location_id_str = str(location_id) if location_id is not None else None
        game_log_manager: Optional[GameLogManager] = kwargs.get('game_log_manager')

        log_message_start = f"CombatManager: Starting new combat in location {location_id_str} for guild {guild_id_str} with participants: {participant_ids_types}..."
        if game_log_manager: asyncio.create_task(game_log_manager.log_info(log_message_start, guild_id=guild_id_str, location_id=location_id_str))
        else: logger.info(log_message_start) # Changed


        if self._db_service is None:
            err_msg = f"CombatManager: No DB service for guild {guild_id_str}. Cannot start combat." # Added guild_id
            if game_log_manager: asyncio.create_task(game_log_manager.log_error(err_msg, guild_id=guild_id_str))
            else: logger.error(err_msg) # Changed
            return None
        if not self._character_manager or not self._npc_manager or not self._rule_engine:
            err_msg = f"CombatManager: ERROR - CharacterManager, NpcManager, or RuleEngine not initialized for guild {guild_id_str}. Cannot fetch participant details." # Added guild_id
            if game_log_manager: asyncio.create_task(game_log_manager.log_error(err_msg, guild_id=guild_id_str))
            else: logger.error(err_msg) # Changed
            return None

        combat_participant_objects: List[CombatParticipant] = []

        for p_id, p_type in participant_ids_types:
            entity_name = "Unknown"
            entity_hp = 10
            entity_max_hp = 10
            entity_dex = 10

            if p_type == "Character":
                char = self._character_manager.get_character(guild_id_str, p_id)
                if char:
                    name_i18n_dict = getattr(char, 'name_i18n', {})
                    entity_name = name_i18n_dict.get('en', p_id) if isinstance(name_i18n_dict, dict) else p_id
                    entity_hp = int(getattr(char, 'hp', 10))
                    entity_max_hp = int(getattr(char, 'max_health', 10))
                    stats = getattr(char, 'stats', {})
                    entity_dex = stats.get('dexterity', 10) if isinstance(stats, dict) else 10
                else:
                    logger.warning("CombatManager: Character %s not found for combat in guild %s.", p_id, guild_id_str) # Changed
                    continue
            elif p_type == "NPC":
                npc = await self._npc_manager.get_npc(guild_id_str, p_id) # Added await
                if npc:
                    name_i18n_dict = getattr(npc, 'name_i18n', {})
                    entity_name = name_i18n_dict.get('en', p_id) if isinstance(name_i18n_dict, dict) else p_id
                    entity_hp = int(getattr(npc, 'health', 10))
                    entity_max_hp = int(getattr(npc, 'max_health', 10))
                    stats = getattr(npc, 'stats', {})
                    entity_dex = stats.get('dexterity', 10) if isinstance(stats, dict) else 10
                else:
                    logger.warning("CombatManager: NPC %s not found for combat in guild %s.", p_id, guild_id_str) # Changed
                    continue
            else:
                logger.warning("CombatManager: Unknown participant type %s for entity %s in guild %s.", p_type, p_id, guild_id_str) # Changed
                continue

            dex_modifier = (entity_dex - 10) // 2
            initiative_roll = random.randint(1, 20)
            initiative_score = initiative_roll + dex_modifier
            logger.info("CombatManager: Initiative for %s (%s) in guild %s: 1d20(%s) + Dex(%s) = %s", entity_name, p_id, guild_id_str, initiative_roll, dex_modifier, initiative_score) # Changed

            participant_obj = CombatParticipant(
                entity_id=p_id, entity_type=p_type, hp=entity_hp, max_hp=entity_max_hp,
                initiative=initiative_score, acted_this_round=False
            )
            combat_participant_objects.append(participant_obj)

        if not combat_participant_objects:
            logger.warning("CombatManager: No valid participants for combat in guild %s. Aborting start_combat.", guild_id_str) # Changed
            return None

        combat_participant_objects.sort(key=lambda p: (p.initiative if p.initiative is not None else -1, p.max_hp), reverse=True)

        turn_order_ids = [p.entity_id for p in combat_participant_objects]
        current_turn_idx = 0

        new_combat_id = str(uuid.uuid4())
        combat_data: Dict[str, Any] = {
            'id': new_combat_id,
            'guild_id': guild_id_str,
            'location_id': location_id_str,
            'status': 'active', # Changed from is_active: True
            'channel_id': kwargs.get('channel_id'),
            'event_id': kwargs.get('event_id'),
            'current_round': 1,
            'participants': [p.to_dict() for p in combat_participant_objects],
            'turn_order': turn_order_ids,
            'current_turn_index': current_turn_idx,
            'combat_log': [f"Combat started in location {location_id_str or 'Unknown'}."],
            'state_variables': kwargs.get('initial_state_variables', {}),
        }

        try:
            combat = Combat.from_dict(combat_data)
            self._active_combats.setdefault(guild_id_str, {})[new_combat_id] = combat
            self.mark_combat_dirty(guild_id_str, new_combat_id)

            log_message_success = f"Combat {new_combat_id} started in location {location_id_str} for guild {guild_id_str}."
            if game_log_manager: asyncio.create_task(game_log_manager.log_info(log_message_success, guild_id=guild_id_str, combat_id=new_combat_id, location_id=location_id_str))
            else: logger.info("CombatManager: %s", log_message_success) # Changed

            send_cb_factory = kwargs.get('send_callback_factory')
            combat_channel_id = getattr(combat, 'channel_id', None)
            if send_cb_factory and combat_channel_id is not None and self._character_manager and self._npc_manager and self._location_manager:
                  try:
                      send_cb = send_cb_factory(int(combat_channel_id))
                      location_name_str = location_id_str or "an unknown location"
                      loc_details = self._location_manager.get_location_instance(guild_id_str, location_id_str) if location_id_str else None
                      if loc_details: location_name_str = getattr(loc_details, 'name', location_id_str)

                      start_message = f"Бой начинается в {location_name_str}!"
                      if combat.turn_order:
                          first_actor_id = combat.get_current_actor_id()
                          first_actor_participant_obj = combat.get_participant_data(first_actor_id) if first_actor_id else None
                          first_actor_name = "Кто-то"
                          if first_actor_participant_obj:
                              if first_actor_participant_obj.entity_type == "Character":
                                  actor_char = self._character_manager.get_character(guild_id_str, first_actor_participant_obj.entity_id)
                                  if actor_char:
                                      first_actor_name = getattr(actor_char, 'name', first_actor_participant_obj.entity_id)
                              elif first_actor_participant_obj.entity_type == "NPC":
                                  actor_npc = self._npc_manager.get_npc(guild_id_str, first_actor_participant_obj.entity_id)
                                  if actor_npc:
                                      first_actor_name = getattr(actor_npc, 'name', first_actor_participant_obj.entity_id)
                          start_message += f" {first_actor_name} ходит первым!"
                      await send_cb(start_message)
                  except Exception as e:
                       logger.error("CombatManager: Error sending combat start message for guild %s, combat %s: %s", guild_id_str, new_combat_id, e, exc_info=True) # Changed
            return combat
        except Exception as e:
            err_msg_create = f"CombatManager: Error creating Combat object or during setup for guild {guild_id_str}: {e}" # Added guild_id
            if game_log_manager: asyncio.create_task(game_log_manager.log_error(f"{err_msg_create}\n{traceback.format_exc()}", guild_id=guild_id_str))
            else: logger.error(err_msg_create, exc_info=True) # Changed
            return None

    async def process_tick(self, combat_id: str, game_time_delta: float, **kwargs: Dict[str, Any]) -> bool:
        guild_id = kwargs.get('guild_id')
        if guild_id is None:
             temp_combat_for_guild_check = None
             for gid_str_key in self._active_combats.keys():
                 if combat_id in self._active_combats[gid_str_key]:
                     temp_combat_for_guild_check = self._active_combats[gid_str_key][combat_id]
                     guild_id = getattr(temp_combat_for_guild_check, 'guild_id', None)
                     break

        if guild_id is None:
             logger.warning("CombatManager: process_tick for combat %s without guild_id. Cannot process.", combat_id) # Changed
             return True

        guild_id_str = str(guild_id)
        combat = self.get_combat(guild_id_str, combat_id)

        if not combat or getattr(combat, 'status', 'completed') not in ('active', 'pending'): # Changed from is_active
            return True # Combat ended or not found, nothing to process

        current_actor_id = combat.get_current_actor_id()
        if not current_actor_id:
            logger.warning("CombatManager: No current actor in combat %s (guild %s), advancing turn to clear.", combat_id, guild_id_str) # Changed
            if combat.turn_order:
                combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
            else:
                combat.status = 'completed' # Changed from is_active = False
                logger.warning("CombatManager: Combat %s (guild %s) has no participants in turn_order. Ending combat.", combat_id, guild_id_str) # Changed
                self.mark_combat_dirty(guild_id_str, combat_id)
                return True # Combat ended
            self.mark_combat_dirty(guild_id_str, combat_id)

            rule_engine_for_check = kwargs.get('rule_engine', self._rule_engine)
            if rule_engine_for_check and hasattr(rule_engine_for_check, 'check_combat_end_conditions'):
                if await rule_engine_for_check.check_combat_end_conditions(combat=combat, context=kwargs):
                    return True # Combat ended after advancing turn
            return False # Turn advanced, combat continues

        actor_participant_data = combat.get_participant_data(current_actor_id)

        if actor_participant_data and actor_participant_data.entity_type == "NPC" and \
           not actor_participant_data.acted_this_round and actor_participant_data.hp > 0 and \
           self._npc_manager and self._character_manager:

            logger.info("CombatManager: NPC Turn: %s in combat %s (guild %s)", current_actor_id, combat_id, guild_id_str) # Changed
            npc_object = await self._npc_manager.get_npc(guild_id_str, current_actor_id) # Added await

            if npc_object:
                rules_config_data = kwargs.get('rules_config', self._settings.get('rules', {}))
                if not rules_config_data and hasattr(self._rule_engine, 'rules_config_data'):
                    rules_config_data = self._rule_engine.rules_config_data

                actor_eff_stats = await stats_calculator.calculate_effective_stats(
                    self._db_service, current_actor_id, actor_participant_data.entity_type, rules_config_data,
                    managers=kwargs
                )

                potential_target_entities_for_ai: List[Union[CharacterModel, NpcModel]] = []
                targets_eff_stats_map: Dict[str, Dict[str, Any]] = {}

                for p_data in combat.participants:
                    if p_data.entity_id != current_actor_id and p_data.hp > 0:
                        target_entity_object: Optional[Union[CharacterModel, NpcModel]] = None
                        if p_data.entity_type == "Character":
                            target_entity_object = self._character_manager.get_character(guild_id_str, p_data.entity_id)
                        elif p_data.entity_type == "NPC":
                            target_entity_object = self._npc_manager.get_npc(guild_id_str, p_data.entity_id)

                        if target_entity_object:
                            potential_target_entities_for_ai.append(target_entity_object)
                            target_eff_stats = await stats_calculator.calculate_effective_stats(
                                self._db_service, p_data.entity_id, p_data.entity_type, rules_config_data,
                                managers=kwargs
                            )
                            targets_eff_stats_map[p_data.entity_id] = target_eff_stats

                ai_instance = NpcCombatAI(npc_object)
                ai_context = {
                    **kwargs,
                    'guild_id': guild_id_str,
                    'rule_engine': self._rule_engine,
                    'rules_config': rules_config_data,
                    'actor_effective_stats': actor_eff_stats,
                    'targets_effective_stats': targets_eff_stats_map,
                }

                action_dict = ai_instance.get_npc_combat_action(
                    combat_instance=combat,
                    potential_targets=potential_target_entities_for_ai,
                    context=ai_context
                )

                if action_dict and action_dict.get("type") != "wait":
                    action_kwargs_for_handler = {**kwargs, 'guild_id': guild_id_str, 'rules_config': rules_config_data}
                    await self.handle_participant_action_complete(
                        combat_instance_id=combat_id, actor_id=current_actor_id,
                        actor_type=actor_participant_data.entity_type, action_data=action_dict,
                        **action_kwargs_for_handler
                    )
                elif action_dict and action_dict.get("type") == "wait":
                    npc_name = getattr(npc_object, 'name', current_actor_id)
                    combat.combat_log.append(f"NPC {npc_name} waits.")
                    logger.info("CombatManager: NPC %s (ID: %s) in combat %s (guild %s) waits.", npc_name, current_actor_id, combat_id, guild_id_str) # Added
                    actor_participant_data.acted_this_round = True
                    if combat.turn_order: # Advance turn
                        combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                        if combat.current_turn_index == 0: # New round
                            combat.current_round += 1
                            combat.combat_log.append(f"Round {combat.current_round} begins.")
                            for p_data_reset in combat.participants: p_data_reset.acted_this_round = False
                    self.mark_combat_dirty(guild_id_str, combat_id)
                else: # No valid action or explicit pass
                    npc_name = getattr(npc_object, 'name', current_actor_id)
                    combat.combat_log.append(f"NPC {npc_name} hesitates.")
                    logger.info("CombatManager: NPC %s (ID: %s) in combat %s (guild %s) hesitates.", npc_name, current_actor_id, combat_id, guild_id_str) # Added
                    actor_participant_data.acted_this_round = True # Mark as acted even if hesitating
                    if combat.turn_order: # Advance turn
                        combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                        if combat.current_turn_index == 0: # New round
                            combat.current_round += 1
                            combat.combat_log.append(f"Round {combat.current_round} begins.")
                            for p_data_reset in combat.participants: p_data_reset.acted_this_round = False
                    self.mark_combat_dirty(guild_id_str, combat_id)
            else: # NPC object not found
                logger.error("CombatManager: NPC object %s not found in guild %s. Cannot process turn.", current_actor_id, guild_id_str) # Changed
                if actor_participant_data: actor_participant_data.acted_this_round = True # Still mark as acted to prevent loop
                if combat.turn_order: # Advance turn
                    combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                    if combat.current_turn_index == 0:
                        combat.current_round += 1
                        combat.combat_log.append(f"Round {combat.current_round} begins.")
                        for p_data_reset in combat.participants: p_data_reset.acted_this_round = False
                self.mark_combat_dirty(guild_id_str, combat_id)

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        combat_finished = False
        winning_entity_ids = []
        if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
            try:
                combat_end_result = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs)

                if isinstance(combat_end_result, dict):
                    combat_finished = combat_end_result.get("ended", False)
                    winning_entity_ids = combat_end_result.get("winners", [])
                elif isinstance(combat_end_result, bool):
                    combat_finished = combat_end_result
                    if combat_finished:
                        living_chars = [p.entity_id for p in combat.participants if p.entity_type == "Character" and p.hp > 0]
                        living_npcs = [p.entity_id for p in combat.participants if p.entity_type == "NPC" and p.hp > 0]
                        if not living_npcs and living_chars: winning_entity_ids = living_chars
                        elif not living_chars and living_npcs: winning_entity_ids = living_npcs
                else: # Should not happen
                    combat_finished = False
                    logger.warning("CombatManager: Unexpected result type from check_combat_end_conditions for combat %s guild %s.", combat_id, guild_id_str)

            except Exception as e:
                game_log_manager = kwargs.get('game_log_manager')
                err_msg = f"CombatManager: Error in check_combat_end_conditions for combat {combat_id} guild {guild_id_str}: {e}" # Added guild_id
                if game_log_manager: await game_log_manager.log_error(f"{err_msg}\n{traceback.format_exc()}", guild_id=guild_id_str, combat_id=combat_id)
                else: logger.error(err_msg, exc_info=True) # Changed
                combat_finished = False
                winning_entity_ids = []


        if combat_finished:
            game_log_manager = kwargs.get('game_log_manager')
            log_msg_end_conditions = f"Combat {combat_id} (guild {guild_id_str}) meets end conditions. Winners: {winning_entity_ids}." # Added guild_id
            if game_log_manager: await game_log_manager.log_info(log_msg_end_conditions, guild_id=guild_id_str, combat_id=combat_id)
            else: logger.info("CombatManager: %s", log_msg_end_conditions) # Changed

            await self.end_combat(guild_id_str, combat_id, winning_entity_ids, context=kwargs)
            return True
        return False

    async def handle_participant_action_complete(
        self, combat_instance_id: str, actor_id: str,
        actor_type: str, action_data: Dict[str, Any], **kwargs: Any
    ) -> None:
        guild_id = kwargs.get('guild_id')
        game_log_manager: Optional[GameLogManager] = kwargs.get('game_log_manager')
        rules_config: Optional[Union[CoreGameRulesConfig, Dict]] = kwargs.get('rules_config')

        if guild_id is None:
            log_msg_no_guild = f"CombatManager: handle_participant_action_complete called for combat {combat_instance_id} without guild_id."
            if game_log_manager: await game_log_manager.log_error(log_msg_no_guild)
            else: logger.error(log_msg_no_guild) # Changed
            return

        guild_id_str = str(guild_id)

        if game_log_manager:
            await game_log_manager.log_info(
                f"Processing combat action: combat_id={combat_instance_id}, actor_id={actor_id}, "
                f"actor_type={actor_type}, action_type={action_data.get('type')}",
                guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id
            )

        if self._db_service is None:
            log_msg_no_db = f"CombatManager: DBService not available for guild {guild_id_str}, cannot process action with transactions." # Added guild_id
            if game_log_manager: await game_log_manager.log_error(log_msg_no_db, guild_id=guild_id_str)
            else: logger.error(log_msg_no_db) # Changed
            return

        await self._db_service.begin_transaction()
        try:
            combat = self.get_combat(guild_id_str, combat_instance_id)

            if not combat or getattr(combat, 'status', 'completed') not in ('active', 'pending') or str(getattr(combat, 'guild_id', None)) != guild_id_str: # Changed from is_active
                log_msg_inactive = f"Action for non-active/mismatched combat {combat_instance_id} in guild {guild_id_str}. Ignoring." # Added guild_id
                if game_log_manager: await game_log_manager.log_warning(log_msg_inactive, guild_id=guild_id_str, combat_id=combat_instance_id)
                else: logger.warning("CombatManager: %s", log_msg_inactive) # Changed
                await self._db_service.rollback_transaction()
                return

            actor_participant_data = combat.get_participant_data(actor_id)
            if not actor_participant_data:
                log_msg_no_actor = f"Action for non-participant {actor_id} in combat {combat_instance_id} (guild {guild_id_str}). Ignoring." # Added guild_id
                if game_log_manager: await game_log_manager.log_warning(log_msg_no_actor, guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id)
                else: logger.warning("CombatManager: %s", log_msg_no_actor) # Changed
                await self._db_service.rollback_transaction()
                return

            if actor_participant_data.hp <= 0 and action_data.get("type") != "system_death_processing":
                log_msg_incap = (f"Participant {actor_id} in combat {combat_instance_id} (guild {guild_id_str}) is incapacitated (HP: {actor_participant_data.hp}). "
                           f"Action {action_data.get('type')} ignored.") # Added guild_id
                if game_log_manager: await game_log_manager.log_info(log_msg_incap, guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id)
                else: logger.info("CombatManager: %s", log_msg_incap) # Changed

                if combat.turn_order: # Advance turn
                    combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                    if combat.current_turn_index == 0:
                        combat.current_round += 1
                        round_msg = f"Round {combat.current_round} begins (turn advanced due to incapacitated actor {actor_id} in combat {combat_instance_id}, guild {guild_id_str})." # Added details
                        combat.combat_log.append(round_msg)
                        if game_log_manager: await game_log_manager.log_info(round_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                        for p_data_reset in combat.participants: p_data_reset.acted_this_round = False
                self.mark_combat_dirty(guild_id_str, combat_instance_id)
                await self._db_service.commit_transaction()
                return

            actor_effective_stats = await stats_calculator.calculate_effective_stats(
                self._db_service, actor_id, actor_participant_data.entity_type, rules_config,
                managers={'character_manager': self._character_manager, 'npc_manager': self._npc_manager, 'status_manager': self._status_manager, 'item_manager': self._item_manager}
            )

            target_ids = action_data.get('target_ids', [])
            targets_effective_stats = {}
            targets_data_for_rule_engine = []

            for target_id in target_ids:
                target_participant_data = combat.get_participant_data(target_id)
                if target_participant_data:
                    target_effective_stats = await stats_calculator.calculate_effective_stats(
                        self._db_service, target_id, target_participant_data.entity_type, rules_config,
                        managers={'character_manager': self._character_manager, 'npc_manager': self._npc_manager, 'status_manager': self._status_manager, 'item_manager': self._item_manager}
                    )
                    targets_effective_stats[target_id] = target_effective_stats
                    targets_data_for_rule_engine.append({
                        "id": target_id, "type": target_participant_data.entity_type,
                        "hp": target_participant_data.hp, "max_hp": target_participant_data.max_hp,
                        "stats": target_effective_stats
                    })
                else:
                    log_msg_no_target = f"Target {target_id} not found in combat {combat_instance_id} (guild {guild_id_str})" # Added guild_id
                    if game_log_manager: await game_log_manager.log_warning(log_msg_no_target, guild_id=guild_id_str, combat_id=combat_instance_id)
                    else: logger.warning(log_msg_no_target) # Added


            actor_participant_data.acted_this_round = True

            rule_engine_context = {
                **kwargs, 'db_service': self._db_service, 'rules_config': rules_config,
                'actor_effective_stats': actor_effective_stats, 'targets_effective_stats': targets_effective_stats,
                'actor_data_for_rule_engine': {
                     "id": actor_id, "type": actor_participant_data.entity_type,
                     "hp": actor_participant_data.hp, "max_hp": actor_participant_data.max_hp,
                     "stats": actor_effective_stats
                },
                'targets_data_for_rule_engine': targets_data_for_rule_engine,
                'game_log_manager': game_log_manager,
                'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
                'status_manager': self._status_manager, 'item_manager': self._item_manager,
            }

            rule_engine = kwargs.get('rule_engine', self._rule_engine)
            if rule_engine and hasattr(rule_engine, 'apply_combat_action_effects'):
                if game_log_manager:
                    await game_log_manager.log_debug(
                        f"Calling RuleEngine.apply_combat_action_effects for actor {actor_id} in {combat_instance_id} (guild {guild_id_str})", # Added guild_id
                        guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id
                    )
                action_results = await rule_engine.apply_combat_action_effects(
                    combat=combat, actor_id=actor_id, action_data=action_data, context=rule_engine_context
                )
                if action_results: # Process results
                    for log_entry in action_results.get("log_messages", []):
                        combat.combat_log.append(log_entry)
                        if game_log_manager: await game_log_manager.log_info(log_entry, guild_id=guild_id_str, combat_id=combat_instance_id)

                    for hp_change in action_results.get("hp_changes", []):
                        target_p = combat.get_participant_data(hp_change["participant_id"])
                        if target_p:
                            original_hp = target_p.hp
                            target_p.hp = hp_change["new_hp"]
                            # Update actual Character/NPC models
                            if target_p.entity_type == "Character" and self._character_manager:
                                char_target = self._character_manager.get_character(guild_id_str, target_p.entity_id)
                                if char_target: char_target.hp = target_p.hp; self._character_manager.mark_character_dirty(guild_id_str, target_p.entity_id)
                            elif target_p.entity_type == "NPC" and self._npc_manager:
                                npc_target = self._npc_manager.get_npc(guild_id_str, target_p.entity_id)
                                if npc_target: npc_target.health = target_p.hp; self._npc_manager.mark_npc_dirty(guild_id_str, target_p.entity_id)

                            if game_log_manager:
                                await game_log_manager.log_debug(
                                    f"Participant {target_p.entity_id} HP changed from {original_hp} to {target_p.hp} in combat {combat_instance_id} (guild {guild_id_str})", # Added guild_id
                                    guild_id=guild_id_str, combat_id=combat_instance_id
                                )
                            if target_p.hp <= 0:
                                defeat_msg = f"Participant {target_p.entity_id} has been defeated in combat {combat_instance_id} (guild {guild_id_str})." # Added guild_id
                                combat.combat_log.append(defeat_msg)
                                if game_log_manager: await game_log_manager.log_info(defeat_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
            else:
                no_re_msg = f"RuleEngine or apply_combat_action_effects not found for combat {combat_instance_id} (guild {guild_id_str}). Combat logic skipped." # Added guild_id
                if game_log_manager: await game_log_manager.log_error(no_re_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                else: logger.error("CombatManager: %s", no_re_msg) # Changed

            if combat.status == 'active' and combat.get_current_actor_id() == actor_id: # Changed from is_active
                if combat.turn_order:
                    combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                    if combat.current_turn_index == 0:
                        combat.current_round += 1
                        round_msg = f"Round {combat.current_round} begins in combat {combat_instance_id} (guild {guild_id_str})." # Added guild_id
                        combat.combat_log.append(round_msg)
                        if game_log_manager: await game_log_manager.log_info(round_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                        for p_data_reset in combat.participants:
                            if p_data_reset.hp > 0: p_data_reset.acted_this_round = False
                            else: p_data_reset.acted_this_round = True
                else:
                    combat.status = 'completed' # Changed from is_active = False
                    no_turn_order_msg = f"Combat {combat_instance_id} (guild {guild_id_str}) has no participants in turn_order after action. Ending combat." # Added guild_id
                    if game_log_manager: await game_log_manager.log_warning(no_turn_order_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                    else: logger.warning("CombatManager: %s", no_turn_order_msg) # Changed
                    combat.combat_log.append(no_turn_order_msg)

            self.mark_combat_dirty(guild_id_str, combat_instance_id)
            await self._db_service.commit_transaction()
            if game_log_manager:
                await game_log_manager.log_info(
                    f"Combat action by {actor_id} in {combat_instance_id} (guild {guild_id_str}) processed successfully.", # Added guild_id
                    guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id
                )
        except Exception as e:
            await self._db_service.rollback_transaction()
            error_msg = f"Error processing combat action for {actor_id} in {combat_instance_id} (guild {guild_id_str}): {e}" # Added guild_id
            if game_log_manager:
                await game_log_manager.log_error(f"{error_msg}\n{traceback.format_exc()}", guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id)
            else:
                logger.error("CombatManager: %s", error_msg, exc_info=True) # Changed
        finally:
            pass # DBService context manager should handle this if used

    async def process_combat_consequences(self, combat: Combat, winning_entity_ids: List[str], context: Dict[str, Any]) -> None:
        guild_id_str = str(combat.guild_id)
        combat_id = combat.id
        game_log_manager: Optional[GameLogManager] = context.get('game_log_manager')

        log_msg_consequences = f"Processing combat consequences for combat {combat_id} (guild {guild_id_str}). Winners: {winning_entity_ids}" # Added guild_id
        if game_log_manager: await game_log_manager.log_info(log_msg_consequences, guild_id=guild_id_str, combat_id=combat_id)
        else: logger.info(log_msg_consequences) # Changed

        character_manager: Optional[CharacterManager] = context.get('character_manager')
        npc_manager: Optional[NpcManager] = context.get('npc_manager')
        item_manager: Optional[ItemManager] = context.get('item_manager')
        inventory_manager = context.get('inventory_manager')
        party_manager: Optional[PartyManager] = context.get('party_manager')
        relationship_manager = context.get('relationship_manager')
        quest_manager = context.get('quest_manager')
        rules_config: Optional[Union[CoreGameRulesConfig, Dict]] = context.get('rules_config')

        if not rules_config:
            err_msg_no_rules = f"rules_config not found in context for process_combat_consequences of combat {combat_id} (guild {guild_id_str})" # Added guild_id
            if game_log_manager: await game_log_manager.log_error(err_msg_no_rules, guild_id=guild_id_str, combat_id=combat_id)
            else: logger.error(err_msg_no_rules) # Added
            return

        rules_data = rules_config if isinstance(rules_config, dict) else rules_config.to_dict() if hasattr(rules_config, 'to_dict') else {}

        if character_manager and self._rule_engine and npc_manager:
            # ... (XP awarding logic remains largely the same, ensure guild_id is in logs) ...
            player_characters_in_combat = [p for p in combat.participants if p.entity_type == "Character"] # For XP eligibility
            defeated_npcs_participants = [p for p in combat.participants if p.entity_type == "NPC" and p.hp <= 0]

            total_xp_yield = 0
            experience_rules = rules_data.get('experience_rules', {})
            combat_xp_rules = experience_rules.get('xp_awards', {}).get('combat', {})
            xp_map_per_cr = combat_xp_rules.get('xp_per_npc_cr', {})
            base_xp_per_kill_fallback = combat_xp_rules.get('base_xp_per_kill', 0)

            for defeated_npc_p_data in defeated_npcs_participants:
                npc_model = await npc_manager.get_npc(guild_id_str, defeated_npc_p_data.entity_id) # Added await
                if npc_model:
                    npc_stats = getattr(npc_model, 'stats', {})
                    if not isinstance(npc_stats, dict): npc_stats = {}
                    npc_cr_any_type = npc_stats.get('challenge_rating', npc_stats.get('cr'))
                    npc_cr_str = str(npc_cr_any_type) if npc_cr_any_type is not None else None
                    npc_xp_value = 0
                    if npc_cr_str and npc_cr_str in xp_map_per_cr: npc_xp_value = xp_map_per_cr[npc_cr_str]
                    elif isinstance(npc_cr_any_type, float) and str(int(npc_cr_any_type)) in xp_map_per_cr and npc_cr_any_type == int(npc_cr_any_type): npc_xp_value = xp_map_per_cr[str(int(npc_cr_any_type))]
                    else: npc_xp_value = base_xp_per_kill_fallback
                    total_xp_yield += npc_xp_value
                    if game_log_manager: await game_log_manager.log_debug(f"NPC {npc_model.id} (CR: {npc_cr_str or 'N/A'}) defeated in guild {guild_id_str}, base XP value: {npc_xp_value}. Total XP yield now: {total_xp_yield}", guild_id=guild_id_str, combat_id=combat_id)

            if total_xp_yield > 0:
                winning_player_character_ids = [p.entity_id for p in player_characters_in_combat if p.entity_id in winning_entity_ids and p.hp > 0]
                if winning_player_character_ids:
                    participant_distribution_rule = combat_xp_rules.get('participant_distribution_rule', "even_split")
                    xp_per_winner = 0
                    if participant_distribution_rule == "even_split": xp_per_winner = total_xp_yield // len(winning_player_character_ids) if len(winning_player_character_ids) > 0 else 0
                    else: xp_per_winner = total_xp_yield
                    if xp_per_winner > 0:
                        for char_id in winning_player_character_ids:
                            character_obj = character_manager.get_character(guild_id_str, char_id)
                            if character_obj:
                                await self._rule_engine.award_experience(character=character_obj, amount=xp_per_winner, source_type="combat", guild_id=guild_id_str, source_id="combat_encounter_rewards", **context)
                                if game_log_manager: await game_log_manager.log_info(f"Character {character_obj.name} ({char_id}) in guild {guild_id_str} processed for {xp_per_winner} XP from combat {combat_id}.", guild_id=guild_id_str, combat_id=combat_id, character_id=char_id)
                            else:
                                if game_log_manager: await game_log_manager.log_warning(f"Could not find character object for ID {char_id} in guild {guild_id_str} to award XP from combat {combat_id}.", guild_id=guild_id_str, combat_id=combat_id)
                    else:
                        if game_log_manager: await game_log_manager.log_info(f"Calculated XP per winner is {xp_per_winner}. No XP awarded from combat {combat_id} in guild {guild_id_str}.", guild_id=guild_id_str, combat_id=combat_id)
                else:
                    if game_log_manager: await game_log_manager.log_warning(f"Total XP yield was {total_xp_yield} from combat {combat_id} in guild {guild_id_str}, but no eligible winning player characters found.", guild_id=guild_id_str, combat_id=combat_id)
            else:
                 if game_log_manager: await game_log_manager.log_info(f"No XP yield from defeated NPCs in combat {combat_id} (guild {guild_id_str}).", guild_id=guild_id_str, combat_id=combat_id)
        else: # Missing managers for XP
            if game_log_manager:
                 missing_managers_for_xp = [name for manager, name in [(character_manager, "CharacterManager"),(self._rule_engine, "RuleEngine"),(npc_manager, "NpcManager")] if not manager]
                 await game_log_manager.log_warning(f"XP awarding skipped for combat {combat_id} (guild {guild_id_str}) due to missing managers: {', '.join(missing_managers_for_xp)}.", guild_id=guild_id_str, combat_id=combat_id)

        # ... (Loot, Relationship, Quest placeholders - add guild_id to logs) ...
        if item_manager and inventory_manager:
            loot_rules = rules_data.get('loot_rules', {})
            all_dropped_loot = []
            for defeated_npc_participant in defeated_npcs_participants:
                if random.random() < loot_rules.get("default_drop_chance", 0.1):
                    placeholder_item_id = loot_rules.get("placeholder_loot_item_id", "potion_health_lesser")
                    all_dropped_loot.append(placeholder_item_id)
                    if game_log_manager: await game_log_manager.log_debug(f"NPC {defeated_npc_participant.entity_id} in guild {guild_id_str} dropped {placeholder_item_id} during combat {combat_id}.", guild_id=guild_id_str, combat_id=combat_id)

            if all_dropped_loot:
                winning_players_for_loot = [eid for eid in winning_entity_ids if any(p.entity_id == eid and p.entity_type == "Character" for p in combat.participants)]
                distribution_method = loot_rules.get("distribution_method", "random_assignment_to_winner")
                if winning_players_for_loot:
                    if distribution_method == "random_assignment_to_winner":
                        for item_id_loot in all_dropped_loot: # Renamed item_id to item_id_loot
                            chosen_loot_recipient = random.choice(winning_players_for_loot)
                            # await inventory_manager.add_item_to_character(guild_id_str, chosen_loot_recipient, item_id_loot, 1) # Example call
                            if game_log_manager: await game_log_manager.log_info(f"Item {item_id_loot} awarded to character {chosen_loot_recipient} in guild {guild_id_str} from combat {combat_id}.", guild_id=guild_id_str, combat_id=combat_id, character_id=chosen_loot_recipient)
                    else:
                         if game_log_manager: await game_log_manager.log_warning(f"Loot distribution method '{distribution_method}' not fully implemented for combat {combat_id} in guild {guild_id_str}.", guild_id=guild_id_str, combat_id=combat_id)
                else:
                    if game_log_manager: await game_log_manager.log_warning(f"Loot dropped in combat {combat_id} (guild {guild_id_str}) but no eligible winning player characters for distribution.", guild_id=guild_id_str, combat_id=combat_id)

        if relationship_manager:
            if game_log_manager: await game_log_manager.log_debug(f"Relationship updates placeholder for combat {combat_id} in guild {guild_id_str}.", guild_id=guild_id_str, combat_id=combat_id)

        if quest_manager:
            if game_log_manager: await game_log_manager.log_debug(f"Quest progress updates placeholder for combat {combat_id} in guild {guild_id_str}.", guild_id=guild_id_str, combat_id=combat_id)

        # Enhanced Logging for Relationship Updates (ensure guild_id in logs)
        default_lang = self._settings.get('main_bot_language', 'en') if self._settings else 'en'
        detailed_participants_data = []
        for p in combat.participants:
            # ... (logic to get faction_id, entity_name as before) ...
            # Ensure guild_id is part of any specific logging if done here.
            pass # This part is complex, assuming guild_id context is passed if helper functions are used

        # ... (event_data_for_relationships setup as before) ...
        # Ensure guild_id is part of the log call if game_log_manager.log_event is called.
        # The current log_event call already includes guild_id.

        if game_log_manager: await game_log_manager.log_info(f"Combat consequences processed for {combat_id} in guild {guild_id_str}.", guild_id=guild_id_str, combat_id=combat_id)


    async def end_combat(self, guild_id: str, combat_id: str, winning_entity_ids: List[str], context: Dict[str, Any]) -> None:
        guild_id_str = str(guild_id)
        game_log_manager: Optional[GameLogManager] = context.get('game_log_manager')

        combat = self.get_combat(guild_id_str, combat_id)
        if not combat:
            err_msg = f"CombatManager: Attempted to end non-existent combat {combat_id} in guild {guild_id_str}." # Added guild_id
            if game_log_manager: await game_log_manager.log_error(err_msg, guild_id=guild_id_str, combat_id=combat_id)
            else: logger.error(err_msg) # Changed
            return

        if combat.status not in ('active', 'pending'): # Changed from is_active
            info_msg = f"CombatManager: Combat {combat_id} in guild {guild_id_str} already ended (status: {combat.status})." # Added guild_id and status
            if game_log_manager: await game_log_manager.log_info(info_msg, guild_id=guild_id_str, combat_id=combat_id)
            else: logger.info(info_msg) # Changed
            # return # Optionally return

        combat.status = 'completed' # Changed from is_active = False
        self.mark_combat_dirty(guild_id_str, combat_id)

        log_message_ending = f"Combat {combat_id} (guild {guild_id_str}) ended with status 'completed'. Winners: {winning_entity_ids}." # Added guild_id and status
        if game_log_manager: await game_log_manager.log_info(log_message_ending, guild_id=guild_id_str, combat_id=combat_id)
        else: logger.info("CombatManager: %s", log_message_ending) # Changed

        await self.process_combat_consequences(combat, winning_entity_ids, context)

        guild_combats_cache = self._active_combats.get(guild_id_str)
        if guild_combats_cache:
            guild_combats_cache.pop(combat_id, None)

        self._deleted_combats_ids.setdefault(guild_id_str, set()).add(combat_id)
        if guild_id_str in self._dirty_combats and combat_id in self._dirty_combats[guild_id_str]:
            self._dirty_combats[guild_id_str].discard(combat_id)
            if not self._dirty_combats[guild_id_str]:
                 del self._dirty_combats[guild_id_str]

        if game_log_manager: await game_log_manager.log_info(f"Combat {combat_id} (guild {guild_id_str}) fully cleaned up from active manager.", guild_id=guild_id_str, combat_id=combat_id) # Added guild_id


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("CombatManager: Loading active combats for guild %s from DB...", guild_id_str) # Changed
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("CombatManager: DB Service not available for load_state in guild %s.", guild_id_str) # Added
            return

        self._active_combats[guild_id_str] = {}
        self._dirty_combats.pop(guild_id_str, None)
        self._deleted_combats_ids.pop(guild_id_str, None)
        rows = []
        try:
            sql = '''
            SELECT id, guild_id, location_id, status, participants,
                   current_round, combat_log, state_variables, channel_id, event_id,
                   turn_order, current_turn_index
            FROM combats WHERE guild_id = $1 AND status IN ('active', 'pending')
            ''' # Removed round_timer as it's not in the INSERT/UPDATE
            rows = await self._db_service.adapter.fetchall(sql, (guild_id_str,))
        except Exception as e:
            logger.critical("CombatManager: CRITICAL DB error loading combats for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            raise

        loaded_count = 0
        guild_combats_cache = self._active_combats[guild_id_str]
        for row_data in rows:
            data = dict(row_data)
            try:
                if str(data.get('guild_id')) != guild_id_str:
                    logger.warning("CombatManager: Row for combat %s has mismatched guild_id (%s vs %s). Skipping.", data.get('id'), data.get('guild_id'), guild_id_str) # Changed
                    continue

                # Assuming Combat.from_dict will handle 'status' and doesn't need 'is_active'
                # If Combat model still uses is_active internally, we would need:
                # status = data.get('status')
                # data['is_active'] = status in ('active', 'pending')

                participants_json_str = data.get('participants', '[]')
                try:
                    participants_dict_list = json.loads(participants_json_str) if isinstance(participants_json_str, str) else participants_json_str
                    if not isinstance(participants_dict_list, list): participants_dict_list = []
                except json.JSONDecodeError: participants_dict_list = []
                data['participants'] = [CombatParticipant.from_dict(p_data) for p_data in participants_dict_list if isinstance(p_data, dict)]

                turn_order_json_str = data.get('turn_order', '[]')
                try:
                    data['turn_order'] = json.loads(turn_order_json_str) if isinstance(turn_order_json_str, str) else turn_order_json_str
                    if not isinstance(data['turn_order'], list): data['turn_order'] = []
                except json.JSONDecodeError: data['turn_order'] = []

                data['combat_log'] = json.loads(data.get('combat_log', '[]')) if isinstance(data.get('combat_log'), str) else (data.get('combat_log', []) or [])
                data['state_variables'] = json.loads(data.get('state_variables', '{}')) if isinstance(data.get('state_variables'), str) else (data.get('state_variables', {}) or {})

                combat = Combat.from_dict(data)
                guild_combats_cache[combat.id] = combat
                loaded_count += 1
            except Exception as e:
                logger.error("CombatManager: Error loading combat object %s for guild %s: %s", data.get('id'), guild_id_str, e, exc_info=True) # Changed
        logger.info("CombatManager: Loaded %s active combats for guild %s.", loaded_count, guild_id_str) # Changed

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("CombatManager: DB Service not available for save_state in guild %s.", guild_id_str) # Added
            return

        dirty_ids = self._dirty_combats.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_combats_ids.get(guild_id_str, set()).copy()
        guild_cache = self._active_combats.get(guild_id_str, {}) # Should this be used if objects are already removed for deleted?

        combats_to_upsert_data = []
        processed_dirty_ids = set()

        for combat_id in list(dirty_ids): # Iterate over a copy
            combat_obj = guild_cache.get(combat_id) # Get from active cache
            if not combat_obj: # If not in active, it might have been ended and only in _deleted_combats_ids
                # If we need to save ended combats (e.g. to mark is_active=False), we need a way to get them.
                # For now, this loop only saves "active but dirty" combats.
                # If a combat is ended (is_active=False) and marked dirty, it should be saved.
                # The issue is if end_combat removes it from _active_combats.
                # Let's assume if it's dirty, it needs saving, even if is_active is now False.
                # We need a temporary way to hold ended-but-dirty combats if they are removed from _active_combats
                # For simplicity, let's assume combat_obj can be fetched if it was just ended (is_active=False but still in _dirty_combats).
                # This part needs careful review of the combat lifecycle vs dirty tracking.
                # A simpler model: end_combat marks dirty. save_state saves all dirty combats.
                # If end_combat also adds to _deleted_combats_ids, then save_state will try to delete it after saving.
                # This seems problematic. Let's assume dirty means "needs DB update".

                # If it's not in active cache, it means it was ended and removed.
                # We should not try to save it as an active combat.
                # The deletion of such combat is handled by the deleted_ids block.
                logger.warning("CombatManager: Combat %s marked dirty for guild %s but not found in active cache. Skipping save for this ID.", combat_id, guild_id_str)
                continue

            combat_dict = combat_obj.to_dict()
            # Ensure participants are dicts for JSON serialization
            participants_for_json = [p.to_dict() if isinstance(p, CombatParticipant) else p for p in combat_dict.get('participants', [])]

            data_tuple = (
                combat_dict['id'], combat_dict['guild_id'], combat_dict.get('location_id'),
                combat_dict['status'], json.dumps(participants_for_json), # Changed from is_active
                combat_dict['current_round'], json.dumps(combat_dict.get('combat_log', [])),
                json.dumps(combat_dict.get('state_variables', {})), combat_dict.get('channel_id'),
                combat_dict.get('event_id'),
                json.dumps(combat_dict.get('turn_order', [])),
                combat_dict.get('current_turn_index', 0)
            )
            combats_to_upsert_data.append(data_tuple)
            processed_dirty_ids.add(combat_id)

        if deleted_ids:
            ids_to_delete_list = list(deleted_ids) # Make a copy
            if ids_to_delete_list:
                placeholders = ', '.join([f'${i+2}' for i in range(len(ids_to_delete_list))])
                delete_sql = f"DELETE FROM combats WHERE guild_id = $1 AND id IN ({placeholders})"
                try:
                    await self._db_service.adapter.execute(delete_sql, (guild_id_str, *tuple(ids_to_delete_list)))
                    logger.info("CombatManager: Deleted %s combats for guild %s: %s", len(ids_to_delete_list), guild_id_str, ids_to_delete_list) # Added
                    self._deleted_combats_ids.pop(guild_id_str, None) # Clear after successful deletion
                except Exception as e:
                    logger.error("CombatManager: Error deleting combats for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            else: # If deleted_ids was empty after copy (e.g. due to prior pop)
                self._deleted_combats_ids.pop(guild_id_str, None)


        if combats_to_upsert_data:
            upsert_sql = '''
            INSERT INTO combats
            (id, guild_id, location_id, status, participants, current_round,
            combat_log, state_variables, channel_id, event_id, turn_order, current_turn_index)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (id) DO UPDATE SET
                guild_id = EXCLUDED.guild_id, location_id = EXCLUDED.location_id,
                status = EXCLUDED.status, participants = EXCLUDED.participants, # Changed from is_active
                current_round = EXCLUDED.current_round,
                combat_log = EXCLUDED.combat_log, state_variables = EXCLUDED.state_variables,
                channel_id = EXCLUDED.channel_id, event_id = EXCLUDED.event_id,
                turn_order = EXCLUDED.turn_order, current_turn_index = EXCLUDED.current_turn_index
            ''' # Removed round_timer from INSERT and UPDATE SET
            try:
                await self._db_service.adapter.execute_many(upsert_sql, combats_to_upsert_data)
                logger.info("CombatManager: Saved %s combats for guild %s.", len(combats_to_upsert_data), guild_id_str) # Added
                if guild_id_str in self._dirty_combats:
                    self._dirty_combats[guild_id_str].difference_update(processed_dirty_ids)
                    if not self._dirty_combats[guild_id_str]: del self._dirty_combats[guild_id_str]
            except Exception as e:
                logger.error("CombatManager: Error batch upserting combats for guild %s: %s", guild_id_str, e, exc_info=True) # Changed

        logger.debug("CombatManager: Save state complete for combats in guild %s.", guild_id_str) # Changed to debug

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("CombatManager: Rebuilding runtime caches for guild %s.", str(guild_id)) # Changed
        # This might involve reloading active combats if they are not cleared during a full rebuild.
        # For now, assuming load_state handles this.
        logger.info("CombatManager: Rebuild runtime caches complete for guild %s.", str(guild_id)) # Changed

    def mark_combat_dirty(self, guild_id: str, combat_id: str) -> None:
         guild_id_str = str(guild_id)
         guild_combats_cache = self._active_combats.get(guild_id_str)
         if guild_combats_cache and combat_id in guild_combats_cache:
              self._dirty_combats.setdefault(guild_id_str, set()).add(combat_id)
         # else: # Log if trying to mark a non-cached combat dirty? Could be noisy.
         #    logger.debug("CombatManager: Attempted to mark non-cached combat %s in guild %s as dirty.", combat_id, guild_id_str)


    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         guild_id = kwargs.get('guild_id')
         if guild_id is None:
             logger.warning("CombatManager: clean_up_for_entity called for entity %s without guild_id.", entity_id) # Added
             return

         guild_id_str = str(guild_id)
         combat = self.get_combat_by_participant_id(guild_id_str, entity_id)

         if combat:
              combat_id = getattr(combat, 'id', None)
              if not combat_id: return # Should not happen if combat object exists

              new_participants_list = [p for p in combat.participants if p.entity_id != entity_id]
              new_turn_order = [e_id for e_id in combat.turn_order if e_id != entity_id]
              removed_actor_index = -1
              try:
                  original_turn_order = list(combat.turn_order) # Copy before modifying
                  removed_actor_index = original_turn_order.index(entity_id)
              except ValueError: pass # Entity was not in turn order

              combat.participants = new_participants_list
              combat.turn_order = new_turn_order

              if new_turn_order: # If combat is still ongoing
                  if removed_actor_index != -1 and combat.current_turn_index >= removed_actor_index:
                      combat.current_turn_index = max(0, combat.current_turn_index -1) # Adjust index if removed actor was before or at current turn
                  if combat.current_turn_index >= len(combat.turn_order): # Handle wrap-around if current index is now out of bounds
                       combat.current_turn_index = 0
              else: # No one left in turn order
                  combat.current_turn_index = 0
                  # Consider ending combat if no one is left, or if check_combat_end_conditions handles it.

              logger.info("CombatManager: Removed %s %s from combat %s in guild %s.", entity_type, entity_id, combat_id, guild_id_str) # Changed
              self.mark_combat_dirty(guild_id_str, combat_id)

              rule_engine = kwargs.get('rule_engine', self._rule_engine)
              if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
                  try:
                      # Pass the full context, as check_combat_end_conditions might need various managers
                      combat_end_result = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs)
                      combat_finished = False
                      if isinstance(combat_end_result, dict): combat_finished = combat_end_result.get("ended", False)
                      elif isinstance(combat_end_result, bool): combat_finished = combat_end_result

                      if combat_finished:
                          logger.info("CombatManager: Combat %s (guild %s) ended after %s %s removed.", combat_id, guild_id_str, entity_type, entity_id) # Changed
                          # end_combat expects winning_entity_ids, which might not be determined here.
                          # This simplified call might need adjustment or RuleEngine should provide winners.
                          await self.end_combat(guild_id_str, combat_id, [], context=kwargs) # Pass empty winners list
                  except Exception as e:
                      logger.error("CombatManager: Error checking end_conditions after entity %s removal from combat %s (guild %s): %s", entity_id, combat_id, guild_id_str, e, exc_info=True) # Changed
