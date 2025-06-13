# bot/game/managers/combat_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import random # Added for initiative rolls
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, Set, Tuple, Union

from bot.game.models.combat import Combat, CombatParticipant # Updated import
from bot.game.ai.npc_combat_ai import NpcCombatAI # <<< Added Import
from bot.game.models.npc import NPC as NpcModel # For type hinting actual NPC objects
from bot.game.utils import stats_calculator
from bot.ai.rules_schema import CoreGameRulesConfig
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.models.character import Character as CharacterModel # For type hinting Character objects
from builtins import dict, set, list, str, int, bool, float


if TYPE_CHECKING:
    from bot.services.db_service import DBService # Changed
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


# print("DEBUG: combat_manager.py module loaded (with updated start_combat).") # Reduced verbosity


class CombatManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _active_combats: Dict[str, Dict[str, "Combat"]]
    _dirty_combats: Dict[str, Set[str]]
    _deleted_combats_ids: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None, # Changed
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        location_manager: Optional["LocationManager"] = None,
    ):
        print("Initializing CombatManager (with updated start_combat)...")
        self._db_service = db_service # Changed
        self._settings = settings
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._npc_manager = npc_manager

        # <<< DETAILED DEBUG PRINTS START >>>
        print(f"CM_INIT_DEBUG: self._rule_engine is {'NOT None' if self._rule_engine else 'None'}")
        print(f"CM_INIT_DEBUG: self._character_manager is {'NOT None' if self._character_manager else 'None'}")
        print(f"CM_INIT_DEBUG: self._npc_manager is {'NOT None' if self._npc_manager else 'None'}")
        # <<< DETAILED DEBUG PRINTS END >>>

        self._party_manager = party_manager
        self._status_manager = status_manager
        self._item_manager = item_manager
        self._location_manager = location_manager

        self._active_combats = {}
        self._dirty_combats = {}
        self._deleted_combats_ids = {}
        # print("CombatManager initialized (with updated start_combat).") # Reduced verbosity

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
        """Checks if an entity is in any active combat and returns the combat_id if so."""
        combat = self.get_combat_by_participant_id(guild_id, entity_id)
        return combat.id if combat and hasattr(combat, 'id') else None

    # Removed apply_damage_to_participant and record_attack as their logic
    # is now expected to be handled by the RuleEngine or within the
    # handle_participant_action_complete method based on RuleEngine results.

    def mark_participant_acted(self, guild_id: str, combat_id: str, entity_id: str) -> None:
        """Marks a participant as having acted in the current round."""
        combat = self.get_combat(guild_id, combat_id)
        if combat:
            participant = combat.get_participant_data(entity_id)
            if participant:
                participant.acted_this_round = True
                self.mark_combat_dirty(guild_id, combat_id)
                print(f"CM.mark_participant_acted: Participant {entity_id} in combat {combat_id} marked as acted.")
            else:
                print(f"CM.mark_participant_acted: Participant {entity_id} not found in combat {combat_id}.")
        else:
            print(f"CM.mark_participant_acted: Combat {combat_id} not found for guild {guild_id}.")

    async def start_combat(self, guild_id: str, location_id: Optional[str], participant_ids_types: List[Tuple[str, str]], **kwargs: Any) -> Optional["Combat"]:
        # <<< DETAILED DEBUG PRINTS START OF start_combat >>>
        print(f"CM_START_COMBAT_DEBUG: self._rule_engine is {'NOT None' if self._rule_engine else 'None'}")
        print(f"CM_START_COMBAT_DEBUG: self._character_manager is {'NOT None' if self._character_manager else 'None'}")
        print(f"CM_START_COMBAT_DEBUG: self._npc_manager is {'NOT None' if self._npc_manager else 'None'}")
        # <<< DETAILED DEBUG PRINTS END >>>

        guild_id_str = str(guild_id)
        location_id_str = str(location_id) if location_id is not None else None
        game_log_manager: Optional[GameLogManager] = kwargs.get('game_log_manager')

        log_message_start = f"CombatManager: Starting new combat in location {location_id_str} for guild {guild_id_str} with participants: {participant_ids_types}..."
        if game_log_manager: asyncio.create_task(game_log_manager.log_info(log_message_start, guild_id=guild_id_str, location_id=location_id_str))
        else: print(log_message_start)


        if self._db_service is None: # Changed
            err_msg = "CombatManager: No DB service. Cannot start combat."
            if game_log_manager: asyncio.create_task(game_log_manager.log_error(err_msg, guild_id=guild_id_str))
            else: print(err_msg)
            return None
        if not self._character_manager or not self._npc_manager or not self._rule_engine:
            err_msg = "CombatManager: ERROR - CharacterManager, NpcManager, or RuleEngine not initialized. Cannot fetch participant details."
            if game_log_manager: asyncio.create_task(game_log_manager.log_error(err_msg, guild_id=guild_id_str))
            else: print(err_msg)
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
                    print(f"CombatManager: Warning - Character {p_id} not found for combat.")
                    continue
            elif p_type == "NPC":
                npc = self._npc_manager.get_npc(guild_id_str, p_id)
                if npc:
                    name_i18n_dict = getattr(npc, 'name_i18n', {})
                    entity_name = name_i18n_dict.get('en', p_id) if isinstance(name_i18n_dict, dict) else p_id
                    entity_hp = int(getattr(npc, 'health', 10))
                    entity_max_hp = int(getattr(npc, 'max_health', 10))
                    stats = getattr(npc, 'stats', {})
                    entity_dex = stats.get('dexterity', 10) if isinstance(stats, dict) else 10
                else:
                    print(f"CombatManager: Warning - NPC {p_id} not found for combat.")
                    continue
            else:
                print(f"CombatManager: Warning - Unknown participant type {p_type} for entity {p_id}.")
                continue

            dex_modifier = (entity_dex - 10) // 2
            initiative_roll = random.randint(1, 20)
            initiative_score = initiative_roll + dex_modifier
            print(f"CombatManager: Initiative for {entity_name} ({p_id}): 1d20({initiative_roll}) + Dex({dex_modifier}) = {initiative_score}")

            participant_obj = CombatParticipant(
                entity_id=p_id, entity_type=p_type, hp=entity_hp, max_hp=entity_max_hp,
                initiative=initiative_score, acted_this_round=False
            )
            combat_participant_objects.append(participant_obj)

        if not combat_participant_objects:
            print(f"CombatManager: No valid participants. Aborting start_combat.")
            return None

        combat_participant_objects.sort(key=lambda p: (p.initiative if p.initiative is not None else -1, p.max_hp), reverse=True)

        turn_order_ids = [p.entity_id for p in combat_participant_objects]
        current_turn_idx = 0

        new_combat_id = str(uuid.uuid4())
        combat_data: Dict[str, Any] = {
            'id': new_combat_id,
            'guild_id': guild_id_str,
            'location_id': location_id_str,
            'is_active': True,
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
            else: print(f"CombatManager: {log_message_success}")

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
                       print(f"CombatManager: Error sending combat start message: {e}"); traceback.print_exc();
            return combat
        except Exception as e:
            err_msg_create = f"CombatManager: Error creating Combat object or during setup: {e}"
            if game_log_manager: asyncio.create_task(game_log_manager.log_error(f"{err_msg_create}\n{traceback.format_exc()}", guild_id=guild_id_str))
            else: print(err_msg_create); traceback.print_exc();
            return None

    async def process_tick(self, combat_id: str, game_time_delta: float, **kwargs: Dict[str, Any]) -> bool:
        # The full context including all managers should be passed in kwargs for check_combat_end_conditions and end_combat
        guild_id = kwargs.get('guild_id')
        if guild_id is None:
             temp_combat_for_guild_check = None
             for gid_str_key in self._active_combats.keys():
                 if combat_id in self._active_combats[gid_str_key]:
                     temp_combat_for_guild_check = self._active_combats[gid_str_key][combat_id]
                     guild_id = getattr(temp_combat_for_guild_check, 'guild_id', None)
                     break

        if guild_id is None:
             print(f"CombatManager: Warning: process_tick for combat {combat_id} without guild_id. Cannot process.")
             return True

        guild_id_str = str(guild_id)
        combat = self.get_combat(guild_id_str, combat_id)

        if not combat or not getattr(combat, 'is_active', False):
            return True

        current_actor_id = combat.get_current_actor_id()
        if not current_actor_id:
            print(f"CombatManager: No current actor in combat {combat_id}, advancing turn to clear.")
            if combat.turn_order:
                combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
            else:
                combat.is_active = False
                print(f"CombatManager: Combat {combat_id} has no participants in turn_order. Ending combat.")
                self.mark_combat_dirty(guild_id_str, combat_id)
                return True
            self.mark_combat_dirty(guild_id_str, combat_id)

            rule_engine_for_check = kwargs.get('rule_engine', self._rule_engine)
            if rule_engine_for_check and hasattr(rule_engine_for_check, 'check_combat_end_conditions'):
                if await rule_engine_for_check.check_combat_end_conditions(combat=combat, context=kwargs): # type: ignore
                    return True
            return False

        actor_participant_data = combat.get_participant_data(current_actor_id)

        if actor_participant_data and actor_participant_data.entity_type == "NPC" and \
           not actor_participant_data.acted_this_round and actor_participant_data.hp > 0 and \
           self._npc_manager and self._character_manager: # Ensure managers are available

            print(f"CombatManager: NPC Turn: {current_actor_id} in combat {combat_id}")
            npc_object = self._npc_manager.get_npc(guild_id_str, current_actor_id)

            if npc_object:
                # Prepare context for NpcCombatAI.get_npc_combat_action
                # This requires actor_effective_stats and targets_effective_stats

                # Get actor's effective stats
                # Ensure rules_config is available in kwargs or self
                rules_config_data = kwargs.get('rules_config', self._settings.get('rules', {})) # Fallback to self._settings
                if not rules_config_data and hasattr(self._rule_engine, 'rules_config_data'): # Check RuleEngine if available
                    rules_config_data = self._rule_engine.rules_config_data

                actor_eff_stats = await stats_calculator.calculate_effective_stats(
                    self._db_service, current_actor_id, actor_participant_data.entity_type, rules_config_data,
                    managers=kwargs # Pass all managers for stat calculation needs
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
                # The full context for AI needs all managers, rules_config, and the effective stats
                ai_context = {
                    **kwargs, # Includes all managers passed to process_tick
                    'guild_id': guild_id_str,
                    'rule_engine': self._rule_engine,
                    'rules_config': rules_config_data,
                    'actor_effective_stats': actor_eff_stats,
                    'targets_effective_stats': targets_eff_stats_map,
                    # RelationshipManager might be in kwargs if provided by GameLoop
                }

                action_dict = ai_instance.get_npc_combat_action(
                    combat_instance=combat,
                    potential_targets=potential_target_entities_for_ai,
                    context=ai_context
                )

                if action_dict and action_dict.get("type") != "wait":
                    # Ensure guild_id is in action_kwargs for handle_participant_action_complete
                    # actor_type is also needed by handle_participant_action_complete
                    action_kwargs_for_handler = {
                        **kwargs, # Pass the original full context
                        'guild_id': guild_id_str, # Ensure guild_id is present
                        'rules_config': rules_config_data, # Ensure rules_config is present
                        # game_log_manager should be in kwargs already
                    }
                    await self.handle_participant_action_complete(
                        combat_instance_id=combat_id, # Use renamed parameter
                        actor_id=current_actor_id,    # Use renamed parameter
                        actor_type=actor_participant_data.entity_type, # Pass actor_type
                        action_data=action_dict,      # Use renamed parameter
                        **action_kwargs_for_handler
                    )
                elif action_dict and action_dict.get("type") == "wait":
                    combat.combat_log.append(f"NPC {getattr(npc_object, 'name', current_actor_id)} waits.")
                    actor_participant_data.acted_this_round = True
                    if combat.turn_order:
                        combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                        if combat.current_turn_index == 0:
                            combat.current_round += 1
                            combat.combat_log.append(f"Round {combat.current_round} begins.")
                            for p_data_reset in combat.participants: p_data_reset.acted_this_round = False
                    self.mark_combat_dirty(guild_id_str, combat_id)
                else:
                    combat.combat_log.append(f"NPC {getattr(npc_object, 'name', current_actor_id)} hesitates.")
                    actor_participant_data.acted_this_round = True
                    if combat.turn_order:
                        combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                        if combat.current_turn_index == 0:
                            combat.current_round += 1
                            combat.combat_log.append(f"Round {combat.current_round} begins.")
                            for p_data_reset in combat.participants: p_data_reset.acted_this_round = False
                    self.mark_combat_dirty(guild_id_str, combat_id)
            else:
                print(f"CombatManager: ERROR - NPC object {current_actor_id} not found. Cannot process turn.")
                if actor_participant_data: actor_participant_data.acted_this_round = True
                if combat.turn_order:
                    combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                    if combat.current_turn_index == 0:
                        combat.current_round += 1
                        combat.combat_log.append(f"Round {combat.current_round} begins.")
                        for p_data_reset in combat.participants: p_data_reset.acted_this_round = False
                self.mark_combat_dirty(guild_id_str, combat_id)

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        combat_finished = False
        if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
            try:
                # Pass the full kwargs as context, it should contain all necessary managers
                combat_end_result = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs) # type: ignore

                if isinstance(combat_end_result, dict): # Expecting dict like {"ended": True, "winners": [], "losers": []}
                    combat_finished = combat_end_result.get("ended", False)
                    winning_entity_ids = combat_end_result.get("winners", [])
                elif isinstance(combat_end_result, bool): # Backwards compatibility if it just returns a boolean
                    combat_finished = combat_end_result
                    winning_entity_ids = [] # Need to determine winners if not provided by rule_engine
                    if combat_finished: # Basic winner determination: all living players if all NPCs are dead, or all living NPCs if all players are dead.
                        # This is a simplified approach. Faction-based or specific scenario rules would be better.
                        living_chars = [p.entity_id for p in combat.participants if p.entity_type == "Character" and p.hp > 0]
                        living_npcs = [p.entity_id for p in combat.participants if p.entity_type == "NPC" and p.hp > 0]

                        if not living_npcs and living_chars: # All NPCs defeated
                            winning_entity_ids = living_chars
                        elif not living_chars and living_npcs: # All Characters defeated
                            winning_entity_ids = living_npcs
                        # If both (or neither) have living members, it's a draw or ongoing; RE should handle this.
                        # Or, if one side fled, the other side wins. This logic should be in RE.
                else:
                    combat_finished = False
                    winning_entity_ids = []

            except Exception as e:
                game_log_manager = kwargs.get('game_log_manager')
                err_msg = f"CombatManager: Error in check_combat_end_conditions for {combat_id}: {e}"
                if game_log_manager: await game_log_manager.log_error(f"{err_msg}\n{traceback.format_exc()}", guild_id=guild_id_str, combat_id=combat_id)
                else: print(err_msg); traceback.print_exc()
                combat_finished = False # Ensure combat doesn't end on error here
                winning_entity_ids = []


        if combat_finished:
            game_log_manager = kwargs.get('game_log_manager')
            log_msg_end_conditions = f"Combat {combat_id} meets end conditions. Winners: {winning_entity_ids}."
            if game_log_manager: await game_log_manager.log_info(log_msg_end_conditions, guild_id=guild_id_str, combat_id=combat_id)
            else: print(f"CombatManager: {log_msg_end_conditions}")

            # Pass the full kwargs as context to end_combat
            await self.end_combat(guild_id_str, combat_id, winning_entity_ids, context=kwargs)
            return True # Signal that combat processing for this tick should stop as it has ended.
        return False

    async def handle_participant_action_complete(
        self, combat_instance_id: str, actor_id: str,
        actor_type: str, # Added actor_type for clarity, though participant_id might imply it
        action_data: Dict[str, Any], **kwargs: Any
    ) -> None: # Return type will be CombatActionResult or similar, for now None
        # Renamed parameters to match process_combat_action conceptual signature
        # participant_id is now actor_id
        # completed_action_data is now action_data

        guild_id = kwargs.get('guild_id')
        game_log_manager: Optional[GameLogManager] = kwargs.get('game_log_manager')
        rules_config: Optional[Union[CoreGameRulesConfig, Dict]] = kwargs.get('rules_config') # Can be object or dict

        if guild_id is None:
            if game_log_manager:
                await game_log_manager.log_error(
                    f"CombatManager: handle_participant_action_complete called for combat {combat_instance_id} without guild_id."
                )
            else:
                print(f"CombatManager: handle_participant_action_complete for {combat_instance_id} without guild_id.")
            return

        guild_id_str = str(guild_id)

        if game_log_manager:
            await game_log_manager.log_info(
                f"Processing combat action: combat_id={combat_instance_id}, actor_id={actor_id}, "
                f"actor_type={actor_type}, action_type={action_data.get('type')}",
                guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id
            )

        if self._db_service is None:
            log_msg = "CombatManager: DBService not available, cannot process action with transactions."
            if game_log_manager: await game_log_manager.log_error(log_msg, guild_id=guild_id_str)
            else: print(log_msg)
            return

        await self._db_service.begin_transaction()
        try:
            combat = self.get_combat(guild_id_str, combat_instance_id)

            if not combat or not getattr(combat, 'is_active', False) or str(getattr(combat, 'guild_id', None)) != guild_id_str:
                log_msg = f"Action for non-active/mismatched combat {combat_instance_id}. Ignoring."
                if game_log_manager: await game_log_manager.log_warning(log_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                else: print(f"CombatManager: {log_msg}")
                await self._db_service.rollback_transaction() # Rollback as we are exiting due to invalid combat state
                return

            actor_participant_data = combat.get_participant_data(actor_id)
            if not actor_participant_data:
                log_msg = f"Action for non-participant {actor_id} in combat {combat_instance_id}. Ignoring."
                if game_log_manager: await game_log_manager.log_warning(log_msg, guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id)
                else: print(f"CombatManager: {log_msg}")
                await self._db_service.rollback_transaction()
                return

            if actor_participant_data.hp <= 0 and action_data.get("type") != "system_death_processing":
                log_msg = (f"Participant {actor_id} is incapacitated (HP: {actor_participant_data.hp}). "
                           f"Action {action_data.get('type')} ignored.")
                if game_log_manager: await game_log_manager.log_info(log_msg, guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id)
                else: print(f"CombatManager: {log_msg}")

                # Advance turn if actor is incapacitated
                if combat.turn_order:
                    combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                    if combat.current_turn_index == 0:
                        combat.current_round += 1
                        round_msg = f"Round {combat.current_round} begins (turn advanced due to incapacitated actor)."
                        combat.combat_log.append(round_msg)
                        if game_log_manager: await game_log_manager.log_info(round_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                        for p_data_reset in combat.participants: p_data_reset.acted_this_round = False # Reset for new round
                self.mark_combat_dirty(guild_id_str, combat_instance_id)
                await self._db_service.commit_transaction() # Commit changes like turn advancement
                return

            # Load Effective Stats for Actor
            actor_effective_stats = await stats_calculator.calculate_effective_stats(
                self._db_service, actor_id, actor_participant_data.entity_type, rules_config, # type: ignore
                managers={'character_manager': self._character_manager, 'npc_manager': self._npc_manager, 'status_manager': self._status_manager, 'item_manager': self._item_manager}
            )

            # Determine targets and load their effective stats
            target_ids = action_data.get('target_ids', []) # Assuming target_ids is a list in action_data
            targets_effective_stats = {}
            targets_data_for_rule_engine = []

            for target_id in target_ids:
                target_participant_data = combat.get_participant_data(target_id)
                if target_participant_data:
                    target_effective_stats = await stats_calculator.calculate_effective_stats(
                        self._db_service, target_id, target_participant_data.entity_type, rules_config, # type: ignore
                        managers={'character_manager': self._character_manager, 'npc_manager': self._npc_manager, 'status_manager': self._status_manager, 'item_manager': self._item_manager}
                    )
                    targets_effective_stats[target_id] = target_effective_stats
                    targets_data_for_rule_engine.append({
                        "id": target_id,
                        "type": target_participant_data.entity_type,
                        "hp": target_participant_data.hp,
                        "max_hp": target_participant_data.max_hp,
                        "stats": target_effective_stats
                    })
                else:
                    if game_log_manager: await game_log_manager.log_warning(f"Target {target_id} not found in combat {combat_instance_id}", guild_id=guild_id_str, combat_id=combat_instance_id)


            actor_participant_data.acted_this_round = True # Mark actor as acted before calling RuleEngine

            # Prepare context for RuleEngine
            rule_engine_context = {
                **kwargs, # Pass along existing kwargs
                'db_service': self._db_service,
                'rules_config': rules_config,
                'actor_effective_stats': actor_effective_stats,
                'targets_effective_stats': targets_effective_stats, # Dict of target_id -> stats
                'actor_data_for_rule_engine': { # Pass actor data in a structured way
                     "id": actor_id,
                     "type": actor_participant_data.entity_type,
                     "hp": actor_participant_data.hp,
                     "max_hp": actor_participant_data.max_hp,
                     "stats": actor_effective_stats
                },
                'targets_data_for_rule_engine': targets_data_for_rule_engine, # List of target data dicts
                'game_log_manager': game_log_manager, # For RuleEngine to log things
                # Potentially pass other managers if RuleEngine needs them directly
                'character_manager': self._character_manager,
                'npc_manager': self._npc_manager,
                'status_manager': self._status_manager,
                'item_manager': self._item_manager,
            }

            rule_engine = kwargs.get('rule_engine', self._rule_engine)
            if rule_engine and hasattr(rule_engine, 'apply_combat_action_effects'):
                if game_log_manager:
                    await game_log_manager.log_debug(
                        f"Calling RuleEngine.apply_combat_action_effects for actor {actor_id} in {combat_instance_id}",
                        guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id
                    )

                # Delegate to RuleEngine
                action_results = await rule_engine.apply_combat_action_effects( # type: ignore
                    combat=combat, # Pass the main combat object
                    actor_id=actor_id,
                    action_data=action_data,
                    context=rule_engine_context
                )

                # Process results from RuleEngine
                # Expected results: hp_changes, status_applications, log_messages
                if action_results:
                    for log_entry in action_results.get("log_messages", []):
                        combat.combat_log.append(log_entry)
                        if game_log_manager: await game_log_manager.log_info(log_entry, guild_id=guild_id_str, combat_id=combat_instance_id)

                    for hp_change in action_results.get("hp_changes", []):
                        target_p = combat.get_participant_data(hp_change["participant_id"])
                        if target_p:
                            original_hp = target_p.hp
                            target_p.hp = hp_change["new_hp"]
                            # Update Character/NPC model HP directly (RuleEngine might do this, or here)
                            # This part might need careful review based on where HP authority lies.
                            # For now, assume CombatParticipant is updated, and Character/NPC managers sync from it.
                            if target_p.entity_type == "Character" and self._character_manager:
                                char_target = self._character_manager.get_character(guild_id_str, target_p.entity_id)
                                if char_target:
                                    char_target.hp = target_p.hp
                                    self._character_manager.mark_character_dirty(guild_id_str, target_p.entity_id)
                            elif target_p.entity_type == "NPC" and self._npc_manager:
                                npc_target = self._npc_manager.get_npc(guild_id_str, target_p.entity_id)
                                if npc_target:
                                    npc_target.health = target_p.hp # Assuming 'health' attribute for NPC
                                    self._npc_manager.mark_npc_dirty(guild_id_str, target_p.entity_id)

                            if game_log_manager:
                                await game_log_manager.log_debug(
                                    f"Participant {target_p.entity_id} HP changed from {original_hp} to {target_p.hp}",
                                    guild_id=guild_id_str, combat_id=combat_instance_id
                                )
                            if target_p.hp <= 0:
                                # Log defeat, RuleEngine might provide a specific message
                                defeat_msg = f"Participant {target_p.entity_id} has been defeated."
                                combat.combat_log.append(defeat_msg)
                                if game_log_manager: await game_log_manager.log_info(defeat_msg, guild_id=guild_id_str, combat_id=combat_instance_id)


                    # Status effects application needs to be defined. Assuming RuleEngine returns them.
                    # for status_effect_data in action_results.get("status_effects", []):
                    #    target_id = status_effect_data["target_id"]
                    #    status_id = status_effect_data["status_id"]
                    #    duration = status_effect_data["duration"]
                    #    # Apply status effect via StatusManager or directly to participant
                    #    # This part needs more detail on how statuses are represented and applied.

            else:
                no_re_msg = "RuleEngine or apply_combat_action_effects not found. Combat logic skipped."
                if game_log_manager: await game_log_manager.log_error(no_re_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                else: print(f"CombatManager: {no_re_msg}")


            # Advance turn if the current actor was the one who acted and combat is still active
            if combat.is_active and combat.get_current_actor_id() == actor_id:
                if combat.turn_order: # Ensure there's a turn order
                    combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                    if combat.current_turn_index == 0: # New round
                        combat.current_round += 1
                        round_msg = f"Round {combat.current_round} begins."
                        combat.combat_log.append(round_msg)
                        if game_log_manager: await game_log_manager.log_info(round_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                        # Reset 'acted_this_round' for all non-defeated participants
                        for p_data_reset in combat.participants:
                            if p_data_reset.hp > 0:
                                p_data_reset.acted_this_round = False
                            else: # Ensure defeated participants are marked as acted to prevent them from taking turns
                                p_data_reset.acted_this_round = True
                else: # No turn order, should not happen in active combat
                    combat.is_active = False
                    no_turn_order_msg = f"Combat {combat_instance_id} has no participants in turn_order after action. Ending combat."
                    if game_log_manager: await game_log_manager.log_warning(no_turn_order_msg, guild_id=guild_id_str, combat_id=combat_instance_id)
                    else: print(f"CombatManager: {no_turn_order_msg}")
                    combat.combat_log.append(no_turn_order_msg)


            self.mark_combat_dirty(guild_id_str, combat_instance_id)
            await self._db_service.commit_transaction()
            if game_log_manager:
                await game_log_manager.log_info(
                    f"Combat action by {actor_id} in {combat_instance_id} processed successfully.",
                    guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id
                )

        except Exception as e:
            await self._db_service.rollback_transaction()
            error_msg = f"Error processing combat action for {actor_id} in {combat_instance_id}: {e}\n{traceback.format_exc()}"
            if game_log_manager:
                await game_log_manager.log_error(error_msg, guild_id=guild_id_str, combat_id=combat_instance_id, actor_id=actor_id)
            else:
                print(f"CombatManager: {error_msg}")
            # Potentially return an error result or raise exception
        finally:
            # Ensure transaction is closed if begin_transaction was called and not committed/rolled back explicitly
            # This might be handled by the DBService's context manager if it has one,
            # otherwise, a check like `if self._db_service.in_transaction(): await self._db_service.rollback_transaction()`
            # might be needed here if errors could bypass the commit/rollback in the try/except.
            # For now, assuming commit/rollback in try/except is sufficient.
            pass

    async def process_combat_consequences(self, combat: Combat, winning_entity_ids: List[str], context: Dict[str, Any]) -> None:
        guild_id_str = str(combat.guild_id)
        combat_id = combat.id
        game_log_manager: Optional[GameLogManager] = context.get('game_log_manager')

        log_msg_consequences = f"Processing combat consequences for combat {combat_id}. Winners: {winning_entity_ids}"
        if game_log_manager: await game_log_manager.log_info(log_msg_consequences, guild_id=guild_id_str, combat_id=combat_id)
        else: print(log_msg_consequences)

        # Extract Managers and Config from Context
        # rule_engine = context.get('rule_engine')
        character_manager: Optional[CharacterManager] = context.get('character_manager')
        npc_manager: Optional[NpcManager] = context.get('npc_manager')
        item_manager: Optional[ItemManager] = context.get('item_manager')
        inventory_manager = context.get('inventory_manager') # Actual manager name may vary
        party_manager: Optional[PartyManager] = context.get('party_manager')
        relationship_manager = context.get('relationship_manager') # Actual manager name may vary
        quest_manager = context.get('quest_manager') # Actual manager name may vary
        rules_config: Optional[Union[CoreGameRulesConfig, Dict]] = context.get('rules_config')

        if not rules_config:
            if game_log_manager: await game_log_manager.log_error("rules_config not found in context for process_combat_consequences", guild_id=guild_id_str, combat_id=combat_id)
            return

        # Convert rules_config to dict if it's an object, for easier access, or ensure attribute access
        rules_data = rules_config if isinstance(rules_config, dict) else rules_config.to_dict() if hasattr(rules_config, 'to_dict') else {}


        # XP Awarding
        if character_manager and self._rule_engine and npc_manager:
            player_characters_in_combat = [p for p in combat.participants if p.entity_type == "Character"]
            defeated_npcs_participants = [p for p in combat.participants if p.entity_type == "NPC" and p.hp <= 0]

            total_xp_yield = 0
            experience_rules = rules_data.get('experience_rules', {})
            combat_xp_rules = experience_rules.get('xp_awards', {}).get('combat', {})
            xp_map_per_cr = combat_xp_rules.get('xp_per_npc_cr', {})
            base_xp_per_kill_fallback = combat_xp_rules.get('base_xp_per_kill', 0)

            for defeated_npc_p_data in defeated_npcs_participants:
                npc_model = npc_manager.get_npc(guild_id_str, defeated_npc_p_data.entity_id)
                if npc_model:
                    npc_stats = getattr(npc_model, 'stats', {})
                    if not isinstance(npc_stats, dict): npc_stats = {}

                    # Try to get CR, could be string or number, ensure string for map lookup
                    npc_cr_any_type = npc_stats.get('challenge_rating', npc_stats.get('cr'))
                    npc_cr_str = str(npc_cr_any_type) if npc_cr_any_type is not None else None

                    npc_xp_value = 0
                    if npc_cr_str and npc_cr_str in xp_map_per_cr:
                        npc_xp_value = xp_map_per_cr[npc_cr_str]
                    elif isinstance(npc_cr_any_type, float) and str(int(npc_cr_any_type)) in xp_map_per_cr and npc_cr_any_type == int(npc_cr_any_type): # handle "1.0" vs "1"
                        npc_xp_value = xp_map_per_cr[str(int(npc_cr_any_type))]
                    else:
                        npc_xp_value = base_xp_per_kill_fallback

                    total_xp_yield += npc_xp_value
                    if game_log_manager:
                        await game_log_manager.log_debug(
                            f"NPC {npc_model.id} (CR: {npc_cr_str or 'N/A'}) defeated, base XP value: {npc_xp_value}. Total XP yield now: {total_xp_yield}",
                            guild_id=guild_id_str, combat_id=combat_id
                        )

            if total_xp_yield > 0:
                # Filter for player characters who are among the winners and are still alive (or considered eligible)
                winning_player_character_ids = [
                    p.entity_id for p in player_characters_in_combat
                    if p.entity_id in winning_entity_ids and p.hp > 0 # Typically only alive winners get XP
                ]

                if winning_player_character_ids:
                    # participant_distribution_rule from new settings
                    participant_distribution_rule = combat_xp_rules.get('participant_distribution_rule', "even_split")

                    xp_per_winner = 0
                    if participant_distribution_rule == "even_split":
                        xp_per_winner = total_xp_yield // len(winning_player_character_ids) if len(winning_player_character_ids) > 0 else 0
                    else: # Add other rules like "solo_credit_highest_damage" or "full_to_all" if needed
                        xp_per_winner = total_xp_yield # Fallback or other rule

                    if xp_per_winner > 0:
                        for char_id in winning_player_character_ids:
                            character_obj = character_manager.get_character(guild_id_str, char_id)
                            if character_obj:
                                # Pass the full context, RuleEngine might need notification_service from it
                                await self._rule_engine.award_experience(
                                    character=character_obj,
                                    amount=xp_per_winner,
                                    source_type="combat",
                                    guild_id=guild_id_str,
                                    source_id="combat_encounter_rewards", # Generic, as CR calculation is done here
                                    **context
                                )
                                # GameLogManager inside award_experience will log the XP award and level up
                                if game_log_manager:
                                     await game_log_manager.log_info(
                                         f"Character {character_obj.name} ({char_id}) processed for {xp_per_winner} XP from combat {combat_id}.",
                                         guild_id=guild_id_str, combat_id=combat_id, character_id=char_id
                                     )
                            else:
                                if game_log_manager:
                                    await game_log_manager.log_warning(f"Could not find character object for ID {char_id} to award XP.", guild_id=guild_id_str, combat_id=combat_id)
                    else:
                        if game_log_manager:
                             await game_log_manager.log_info(f"Calculated XP per winner is {xp_per_winner}. No XP awarded from combat {combat_id}.", guild_id=guild_id_str, combat_id=combat_id)
                else:
                    if game_log_manager:
                        await game_log_manager.log_warning(f"Total XP yield was {total_xp_yield} from combat {combat_id}, but no eligible winning player characters found for distribution.", guild_id=guild_id_str, combat_id=combat_id)
            else:
                 if game_log_manager:
                      await game_log_manager.log_info(f"No XP yield from defeated NPCs in combat {combat_id}.", guild_id=guild_id_str, combat_id=combat_id)
        else:
            if game_log_manager:
                 missing_managers = [
                     name for manager, name in [
                         (character_manager, "CharacterManager"),
                         (self._rule_engine, "RuleEngine"),
                         (npc_manager, "NpcManager")
                     ] if not manager
                 ]
                 await game_log_manager.log_warning(f"XP awarding skipped for combat {combat_id} due to missing managers: {', '.join(missing_managers)}.", guild_id=guild_id_str, combat_id=combat_id)


        # Loot Distribution
        if item_manager and inventory_manager: # Assuming InventoryManager handles adding items to characters/parties
            loot_rules = rules_data.get('loot_rules', {})
            all_dropped_loot = [] # List of item_ids or item objects

            for defeated_npc_participant in defeated_npcs_participants:
                # npc_model = npc_manager.get_npc(guild_id_str, defeated_npc_participant.entity_id) if npc_manager else None
                # loot_table_id = getattr(npc_model, 'loot_table_id', None)
                # RuleEngine might have: generated_loot = await rule_engine.resolve_loot_drop(defeated_npc_participant.entity_id, context)
                # Placeholder: simple loot
                if random.random() < loot_rules.get("default_drop_chance", 0.1): # 10% chance to drop a placeholder item
                    placeholder_item_id = loot_rules.get("placeholder_loot_item_id", "potion_health_lesser")
                    all_dropped_loot.append(placeholder_item_id)
                    if game_log_manager: await game_log_manager.log_debug(f"NPC {defeated_npc_participant.entity_id} dropped {placeholder_item_id}.", guild_id=guild_id_str, combat_id=combat_id)

            if all_dropped_loot:
                # Distribute loot among winning_entity_ids that are players
                winning_players_for_loot = [eid for eid in winning_entity_ids if any(p.entity_id == eid and p.entity_type == "Character" for p in combat.participants)]
                distribution_method = loot_rules.get("distribution_method", "random_assignment_to_winner")

                if winning_players_for_loot:
                    if distribution_method == "random_assignment_to_winner":
                        for item_id in all_dropped_loot:
                            chosen_loot_recipient = random.choice(winning_players_for_loot)
                            # await inventory_manager.add_item_to_character(guild_id_str, chosen_loot_recipient, item_id, 1)
                            if game_log_manager: await game_log_manager.log_info(f"Item {item_id} awarded to character {chosen_loot_recipient}.", guild_id=guild_id_str, combat_id=combat_id, character_id=chosen_loot_recipient)
                    # Other methods like "party_leader_decides" or "add_to_party_stash" would need PartyManager integration
                    else:
                         if game_log_manager: await game_log_manager.log_warning(f"Loot distribution method '{distribution_method}' not fully implemented.", guild_id=guild_id_str, combat_id=combat_id)
                else:
                    if game_log_manager: await game_log_manager.log_warning("Loot dropped but no eligible winning player characters for distribution.", guild_id=guild_id_str, combat_id=combat_id)

        # Update World State / Relationships (Placeholder)
        if relationship_manager:
            # for winner_id in winning_entity_ids:
            #     for p in combat.participants:
            #         if p.hp <= 0 and p.entity_id not in winning_entity_ids: # A defeated entity
            #             # await relationship_manager.update_relationship_on_combat_outcome(winner_id, p.entity_id, "victory")
            #             pass
            if game_log_manager: await game_log_manager.log_debug("Relationship updates placeholder.", guild_id=guild_id_str, combat_id=combat_id)

        # Update Quest Progress (Placeholder)
        if quest_manager:
            # for char_id in winning_entity_ids:
            #    if any(p.entity_id == char_id and p.entity_type == "Character" for p in combat.participants):
            #        # defeated_ids_for_quest = [p.entity_id for p in combat.participants if p.hp <= 0]
            #        # await quest_manager.update_quests_on_combat_end(char_id, combat, defeated_ids_for_quest)
            #        pass
            if game_log_manager: await game_log_manager.log_debug("Quest progress updates placeholder.", guild_id=guild_id_str, combat_id=combat_id)

        # --- Enhanced Logging for Relationship Updates ---
        detailed_participants_data = []
        default_lang = self._settings.get('main_bot_language', 'en') if self._settings else 'en'

        for p in combat.participants:
            entity_id = p.entity_id
            entity_type = p.entity_type
            faction_id: Optional[str] = None
            entity_name: str = p.entity_id # Fallback name

            if entity_type == "Character" and character_manager:
                char_obj = await character_manager.get_character(guild_id_str, entity_id)
                if char_obj:
                    faction_id = getattr(char_obj, 'faction_id', None)
                    # Consistent name fetching similar to start_combat
                    name_i18n_dict = getattr(char_obj, 'name_i18n', {})
                    entity_name = name_i18n_dict.get(default_lang, p.entity_id) if isinstance(name_i18n_dict, dict) else getattr(char_obj, 'name', p.entity_id)
            elif entity_type == "NPC" and npc_manager:
                npc_obj = await npc_manager.get_npc(guild_id_str, entity_id)
                if npc_obj:
                    faction_id = getattr(npc_obj, 'faction_id', None)
                    name_i18n_dict = getattr(npc_obj, 'name_i18n', {})
                    entity_name = name_i18n_dict.get(default_lang, p.entity_id) if isinstance(name_i18n_dict, dict) else getattr(npc_obj, 'name', p.entity_id)

            status = "unknown"
            if entity_id in winning_entity_ids and p.hp > 0:
                status = "winner_survived"
            elif entity_id in winning_entity_ids and p.hp <= 0:
                status = "winner_defeated"
            elif p.hp <= 0:
                status = "loser_defeated"
            else:
                status = "loser_survived"

            detailed_participants_data.append({
                "entity_id": entity_id,
                "entity_type": entity_type,
                "name": entity_name,
                "faction_id": faction_id,
                "initial_hp": p.max_hp,
                "final_hp": p.hp,
                "status": status
            })

        player_ids_involved = list(set(p_data['entity_id'] for p_data in detailed_participants_data if p_data['entity_type'] == "Character"))
        party_ids_involved = []
        if party_manager and character_manager:
            for player_id_involved in player_ids_involved:
                char_obj_for_party = await character_manager.get_character(guild_id_str, player_id_involved)
                if char_obj_for_party:
                    p_party_id = getattr(char_obj_for_party, 'party_id', None)
                    if p_party_id:
                        party_ids_involved.append(p_party_id)

        event_data_for_relationships = {
            "guild_id": guild_id_str, # Though guild_id is top-level in log_event, useful for rules if they only get details
            "combat_id": combat.id,
            "location_id": combat.location_id,
            "event_id": combat.event_id,
            "winning_entity_ids": winning_entity_ids,
            "participants": detailed_participants_data,
            "player_ids_involved": player_ids_involved,
            "party_ids_involved": list(set(party_ids_involved)),
            "combat_difficulty": getattr(combat, 'difficulty_metric', None)
        }

        if game_log_manager:
            await game_log_manager.log_event(
                guild_id=guild_id_str,
                event_type="COMBAT_ENDED",
                details=event_data_for_relationships,
                player_id=None, # Top-level player_id not primary, details has list
                party_id=None,  # Top-level party_id not primary, details has list
                location_id=combat.location_id,
                channel_id=combat.channel_id
            )
        # --- End of Enhanced Logging ---

        if game_log_manager: await game_log_manager.log_info(f"Combat consequences processed for {combat_id}.", guild_id=guild_id_str, combat_id=combat_id)


    async def end_combat(self, guild_id: str, combat_id: str, winning_entity_ids: List[str], context: Dict[str, Any]) -> None:
        guild_id_str = str(guild_id)
        game_log_manager: Optional[GameLogManager] = context.get('game_log_manager')

        combat = self.get_combat(guild_id_str, combat_id)
        if not combat:
            err_msg = f"CombatManager: Attempted to end non-existent combat {combat_id}."
            if game_log_manager: await game_log_manager.log_error(err_msg, guild_id=guild_id_str, combat_id=combat_id)
            else: print(err_msg)
            return

        if not combat.is_active:
            info_msg = f"CombatManager: Combat {combat_id} already ended."
            if game_log_manager: await game_log_manager.log_info(info_msg, guild_id=guild_id_str, combat_id=combat_id)
            else: print(info_msg)
            # Still proceed to ensure consequences are processed if called again, or handle idempotency
            # return # Optionally return if already ended and processed.

        combat.is_active = False
        # It's important to mark it dirty BEFORE processing consequences if consequences might save other managers
        # but the combat object itself also needs saving with is_active = False.
        self.mark_combat_dirty(guild_id_str, combat_id)

        log_message_ending = f"Combat {combat_id} ended. Winners: {winning_entity_ids}."
        if game_log_manager: await game_log_manager.log_info(log_message_ending, guild_id=guild_id_str, combat_id=combat_id)
        else: print(f"CombatManager: {log_message_ending}")

        # Process consequences like XP, loot, relationship changes, quest updates
        await self.process_combat_consequences(combat, winning_entity_ids, context)

        # Perform cleanup from active memory. Actual DB deletion is handled by save_state based on _deleted_combats_ids.
        # For now, marking as dirty and inactive should be enough for save_state to update it.
        # If it needs to be removed from _active_combats immediately:
        # self._deleted_combats_ids.setdefault(guild_id_str, set()).add(combat_id) # Mark for DB deletion
        # guild_active_combats = self._active_combats.get(guild_id_str)
        # if guild_active_combats and combat_id in guild_active_combats:
        #    del guild_active_combats[combat_id] # Remove from active cache
        # if guild_id_str in self._dirty_combats and combat_id in self._dirty_combats[guild_id_str]:
        #    self._dirty_combats[guild_id_str].discard(combat_id) # Remove from dirty set if it was only marked for this
        #    if not self._dirty_combats[guild_id_str]:
        #        del self._dirty_combats[guild_id_str]

        # The current save_state handles updating is_active=False. If combat should be fully deleted,
        # then it needs to be added to _deleted_combats_ids and removed from _active_combats.
        # For now, just marking it inactive is fine. The save_state will persist this.
        # If a combat is truly "over" and should not be queryable as an active combat anymore,
        # then popping from _active_combats makes sense.

        # The `save_state` will handle persisting the is_active=False state.
        # If we want to remove it from memory immediately:
        # active_guild_combats = self._active_combats.get(guild_id_str)
        # if active_guild_combats and combat_id in active_guild_combats:
        #     del active_guild_combats[combat_id]
        # The current end_combat in the original file has more nuanced cleanup logic that should be preserved or adapted.
        # For now, the critical part is setting is_active = False and marking dirty.
        # The original end_combat also added to _deleted_combats_ids. Let's reconsider this.
        # If ending means soft delete (marked inactive), then just marking dirty is fine.
        # If ending means hard delete eventually, then _deleted_combats_ids is right.
        # The subtask implies cleanup from active memory, but DB state is also a concern.
        # Let's stick to marking inactive, and save_state will update the record.
        # For actual removal from memory and DB, a separate "archive" or "delete_old_combats" might be better.
        # However, the original code did remove it from active_combats and added to _deleted_combats_ids.
        # Let's replicate that behavior for consistency with potential existing save/load logic.

        guild_combats_cache = self._active_combats.get(guild_id_str)
        if guild_combats_cache:
            guild_combats_cache.pop(combat_id, None) # Remove from active memory

        # Add to _deleted_combats_ids only if we intend to delete it from DB entirely upon next save.
        # If we just want to mark it inactive, this line is not needed and save_state handles it.
        # Given the original code, it seems combats are deleted once ended.
        self._deleted_combats_ids.setdefault(guild_id_str, set()).add(combat_id)
        if guild_id_str in self._dirty_combats and combat_id in self._dirty_combats[guild_id_str]:
            self._dirty_combats[guild_id_str].discard(combat_id)
            if not self._dirty_combats[guild_id_str]:
                 del self._dirty_combats[guild_id_str]

        if game_log_manager: await game_log_manager.log_info(f"Combat {combat_id} fully cleaned up from active manager.", guild_id=guild_id_str, combat_id=combat_id)


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        print(f"CombatManager: Loading active combats for guild {guild_id_str} from DB...")
        if self._db_service is None or self._db_service.adapter is None: return

        self._active_combats[guild_id_str] = {}
        self._dirty_combats.pop(guild_id_str, None)
        self._deleted_combats_ids.pop(guild_id_str, None)
        rows = []
        try:
            sql = '''
            SELECT id, guild_id, location_id, is_active, participants,
                   current_round, combat_log, state_variables, channel_id, event_id,
                   turn_order, current_turn_index
            FROM combats WHERE guild_id = $1 AND is_active = TRUE
            '''
            rows = await self._db_service.adapter.fetchall(sql, (guild_id_str,))
        except Exception as e:
            print(f"CombatManager: CRITICAL DB error loading combats for guild {guild_id_str}: {e}")
            traceback.print_exc()
            raise

        loaded_count = 0
        guild_combats_cache = self._active_combats[guild_id_str]
        for row_data in rows:
            data = dict(row_data)
            try:
                if str(data.get('guild_id')) != guild_id_str:
                    print(f"CombatManager: Warning - Row for combat {data.get('id')} has mismatched guild_id. Skipping.")
                    continue

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
                print(f"CombatManager: Error loading combat object {data.get('id')}: {e}")
                traceback.print_exc()
        print(f"CombatManager: Loaded {loaded_count} active combats for guild {guild_id_str}.")

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None: return

        dirty_ids = self._dirty_combats.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_combats_ids.get(guild_id_str, set()).copy()
        guild_cache = self._active_combats.get(guild_id_str, {})

        combats_to_upsert_data = []
        processed_dirty_ids = set()

        for combat_id in list(dirty_ids):
            combat_obj = guild_cache.get(combat_id)
            if not combat_obj:
                print(f"CombatManager: Combat {combat_id} marked dirty for guild {guild_id_str} but not found in active cache. Skipping save.")
                continue

            combat_dict = combat_obj.to_dict()

            data_tuple = (
                combat_dict['id'], combat_dict['guild_id'], combat_dict.get('location_id'),
                combat_dict['is_active'], json.dumps(combat_dict['participants']),
                0.0, # round_timer placeholder
                combat_dict['current_round'], json.dumps(combat_dict['combat_log']),
                json.dumps(combat_dict['state_variables']), combat_dict.get('channel_id'),
                combat_dict.get('event_id'),
                json.dumps(combat_dict.get('turn_order', [])),
                combat_dict.get('current_turn_index', 0)
            )
            combats_to_upsert_data.append(data_tuple)
            processed_dirty_ids.add(combat_id)

        if deleted_ids:
            if deleted_ids:
                placeholders = ', '.join([f'${i+2}' for i in range(len(deleted_ids))])
                delete_sql = f"DELETE FROM combats WHERE guild_id = $1 AND id IN ({placeholders})"
                try:
                    await self._db_service.adapter.execute(delete_sql, (guild_id_str, *tuple(deleted_ids)))
                    self._deleted_combats_ids.pop(guild_id_str, None)
                except Exception as e: print(f"CM Error deleting combats: {e}")
            else:
                self._deleted_combats_ids.pop(guild_id_str, None)

        if combats_to_upsert_data:
            upsert_sql = '''
            INSERT INTO combats
            (id, guild_id, location_id, is_active, participants, round_timer, current_round,
            combat_log, state_variables, channel_id, event_id, turn_order, current_turn_index)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (id) DO UPDATE SET
                guild_id = EXCLUDED.guild_id, location_id = EXCLUDED.location_id,
                is_active = EXCLUDED.is_active, participants = EXCLUDED.participants,
                round_timer = EXCLUDED.round_timer, current_round = EXCLUDED.current_round,
                combat_log = EXCLUDED.combat_log, state_variables = EXCLUDED.state_variables,
                channel_id = EXCLUDED.channel_id, event_id = EXCLUDED.event_id,
                turn_order = EXCLUDED.turn_order, current_turn_index = EXCLUDED.current_turn_index
            '''
            try:
                await self._db_service.adapter.execute_many(upsert_sql, combats_to_upsert_data)
                if guild_id_str in self._dirty_combats:
                    self._dirty_combats[guild_id_str].difference_update(processed_dirty_ids)
                    if not self._dirty_combats[guild_id_str]: del self._dirty_combats[guild_id_str]
            except Exception as e: print(f"CM Error batch upsert combats: {e}")

        print(f"CM: Save state complete for combats in guild {guild_id_str}.")

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        print(f"CombatManager: Rebuilding runtime caches for guild {str(guild_id)}.")
        print(f"CombatManager: Rebuild runtime caches complete for guild {str(guild_id)}.")

    def mark_combat_dirty(self, guild_id: str, combat_id: str) -> None:
         guild_id_str = str(guild_id)
         guild_combats_cache = self._active_combats.get(guild_id_str)
         if guild_combats_cache and combat_id in guild_combats_cache:
              self._dirty_combats.setdefault(guild_id_str, set()).add(combat_id)

    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         guild_id = kwargs.get('guild_id')
         if guild_id is None: return
         guild_id_str = str(guild_id)
         combat = self.get_combat_by_participant_id(guild_id_str, entity_id)

         if combat:
              combat_id = getattr(combat, 'id', None)
              if not combat_id: return
              new_participants_list = [p for p in combat.participants if p.entity_id != entity_id]
              new_turn_order = [e_id for e_id in combat.turn_order if e_id != entity_id]
              removed_actor_index = -1
              try:
                  original_turn_order = list(combat.turn_order)
                  removed_actor_index = original_turn_order.index(entity_id)
              except ValueError: pass

              combat.participants = new_participants_list
              combat.turn_order = new_turn_order

              if new_turn_order:
                  if removed_actor_index != -1 and combat.current_turn_index >= removed_actor_index:
                      combat.current_turn_index = max(0, combat.current_turn_index -1)
                  if combat.current_turn_index >= len(combat.turn_order):
                       combat.current_turn_index = 0
              else:
                  combat.current_turn_index = 0

              print(f"CombatManager: Removed {entity_type} {entity_id} from combat {combat_id}.")
              self.mark_combat_dirty(guild_id_str, combat_id)

              rule_engine = kwargs.get('rule_engine', self._rule_engine)
              if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
                  try:
                      combat_finished = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs) # type: ignore
                      if combat_finished:
                          print(f"CombatManager: Combat {combat_id} ended after {entity_type} {entity_id} removed.")
                          await self.end_combat(combat_id, **kwargs)
                  except Exception as e:
                      print(f"CombatManager: Error checking end_conditions after entity removal: {e}")

# print("DEBUG: combat_manager.py module loaded (with updated start_combat).") # Reduced verbosity
