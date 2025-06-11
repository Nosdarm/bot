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


print("DEBUG: combat_manager.py module loaded (with updated start_combat).")


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
        print("CombatManager initialized (with updated start_combat).")

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

    async def apply_damage_to_participant(self, guild_id: str, combat_id: str, target_id: str, damage_amount: int, damage_type: str) -> Dict[str, Any]:
        """Applies damage to a combat participant and updates their state in the Combat object."""
        log_prefix = f"CM.apply_damage(g='{guild_id}',c='{combat_id}',t='{target_id}',amt={damage_amount}):"
        combat = self.get_combat(guild_id, combat_id)
        if not combat:
            print(f"{log_prefix} Combat not found.")
            return {"success": False, "message": "Бой не найден.", "hp_after_damage": -1, "defeated": False}

        participant_data = combat.get_participant_data(target_id)
        if not participant_data:
            print(f"{log_prefix} Target participant not found in combat.")
            return {"success": False, "message": "Цель не найдена в этом бою.", "hp_after_damage": -1, "defeated": False}

        original_hp = participant_data.hp
        participant_data.hp = max(0, original_hp - damage_amount)

        target_name = target_id
        target_is_defeated = participant_data.hp <= 0
        message_parts = []

        if participant_data.entity_type == "Character" and self._character_manager:
            char_target = self._character_manager.get_character(guild_id, target_id)
            if char_target:
                target_name = getattr(char_target, 'name', target_id)
                char_target.hp = participant_data.hp
                self._character_manager.mark_character_dirty(guild_id, target_id)
                if target_is_defeated:
                     message_parts.append(f"{target_name} повержен(а)!")
            else: print(f"{log_prefix} Character target {target_id} not found for HP update.")
        elif participant_data.entity_type == "NPC" and self._npc_manager:
            npc_target = self._npc_manager.get_npc(guild_id, target_id)
            if npc_target:
                target_name = getattr(npc_target, 'name', target_id)
                npc_target.health = participant_data.hp
                self._npc_manager.mark_npc_dirty(guild_id, target_id)
                if target_is_defeated:
                    message_parts.append(f"{target_name} ({participant_data.entity_type}) повержен(а)!")
            else: print(f"{log_prefix} NPC target {target_id} not found for HP update.")

        combat.combat_log.append(f"{target_name} получает {damage_amount} ед. урона ({damage_type}). Осталось HP: {participant_data.hp}.")
        self.mark_combat_dirty(guild_id, combat_id)

        return {
            "success": True,
            "message": " ".join(filter(None, message_parts)),
            "hp_after_damage": participant_data.hp,
            "defeated": target_is_defeated,
            "target_name": target_name
        }

    async def record_attack(self, guild_id: str, combat_id: str, attacker_id: str, target_id: str, outcome: Dict[str, Any]) -> bool:
        """Records an attack attempt in the combat log. The 'message' in outcome is preferred if available."""
        combat = self.get_combat(guild_id, combat_id)
        if not combat: return False

        log_message = outcome.get("message")

        if not log_message:
            attacker_name = attacker_id
            target_name = target_id

            attacker_participant = combat.get_participant_data(attacker_id)
            if attacker_participant and self._character_manager and self._npc_manager: # Ensure managers are available
                if attacker_participant.entity_type == "Character":
                    char = self._character_manager.get_character(guild_id, attacker_id)
                    if char: attacker_name = getattr(char, 'name', attacker_id)
                elif attacker_participant.entity_type == "NPC":
                    npc = self._npc_manager.get_npc(guild_id, attacker_id)
                    if npc: attacker_name = getattr(npc, 'name', attacker_id)

            target_participant = combat.get_participant_data(target_id)
            if target_participant and self._character_manager and self._npc_manager: # Ensure managers are available
                if target_participant.entity_type == "Character":
                    char = self._character_manager.get_character(guild_id, target_id)
                    if char: target_name = getattr(char, 'name', target_id)
                elif target_participant.entity_type == "NPC":
                    npc = self._npc_manager.get_npc(guild_id, target_id)
                    if npc: target_name = getattr(npc, 'name', target_id)

            log_message = f"Атака: {attacker_name} -> {target_name}. "
            if outcome.get("hit"):
                log_message += f"Попадание! Урон: {outcome.get('damage', 0)}."
            else:
                log_message += "Промах."

        combat.combat_log.append(log_message)
        self.mark_combat_dirty(guild_id, combat_id)
        return True

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
        print(f"CombatManager: Starting new combat in location {location_id_str} for guild {guild_id_str} with participants: {participant_ids_types}...")

        if self._db_service is None: # Changed
            print(f"CombatManager: No DB service. Cannot start combat.")
            return None
        if not self._character_manager or not self._npc_manager or not self._rule_engine:
            print(f"CombatManager: ERROR - CharacterManager, NpcManager, or RuleEngine not initialized. Cannot fetch participant details.")
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
            print(f"CombatManager: Combat {new_combat_id} started in location {location_id_str} for guild {guild_id_str}.")

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
            print(f"CombatManager: Error creating Combat object or during setup: {e}")
            traceback.print_exc()
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
                ai_instance = NpcCombatAI(npc_object)
                potential_target_entities: List[Union[CharacterModel, NpcModel]] = []
                for p_data in combat.participants:
                    if p_data.entity_id != current_actor_id and p_data.hp > 0:
                        target_entity: Optional[Union[CharacterModel, NpcModel]] = None
                        if p_data.entity_type == "Character":
                            target_entity = self._character_manager.get_character(guild_id_str, p_data.entity_id)
                        elif p_data.entity_type == "NPC":
                            target_entity = self._npc_manager.get_npc(guild_id_str, p_data.entity_id)
                        if target_entity:
                            potential_target_entities.append(target_entity)

                combat_context_for_ai = {"combat": combat, "guild_id": guild_id_str, "rule_engine": self._rule_engine}
                selected_target = ai_instance.select_target(potential_target_entities, combat_context_for_ai)
                action_dict = ai_instance.select_action(selected_target, combat_context_for_ai)

                if action_dict and action_dict.get("type") != "wait":
                    action_kwargs = {**kwargs, 'guild_id': guild_id_str, 'rule_engine': self._rule_engine}
                    await self.handle_participant_action_complete(combat_id, current_actor_id, action_dict, **action_kwargs)
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
                combat_finished = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs) # type: ignore
            except Exception as e:
                print(f"CombatManager: Error in check_combat_end_conditions for {combat_id}: {e}")
                traceback.print_exc()

        if combat_finished:
             print(f"CombatManager: Combat {combat_id} meets end conditions.")
             return True
        return False

    async def handle_participant_action_complete(
        self, combat_id: str, participant_id: str,
        completed_action_data: Dict[str, Any], **kwargs: Any
    ) -> None:
        guild_id = kwargs.get('guild_id')
        if guild_id is None:
             print(f"CombatManager: handle_participant_action_complete for {combat_id} without guild_id.")
             return

        guild_id_str = str(guild_id)
        combat = self.get_combat(guild_id_str, combat_id)

        if not combat or not getattr(combat, 'is_active', False) or str(getattr(combat, 'guild_id', None)) != guild_id_str:
             print(f"CombatManager: Action for non-active/mismatched combat {combat_id}. Ignoring.")
             return

        actor_participant_data = combat.get_participant_data(participant_id)
        if not actor_participant_data:
            print(f"CombatManager: Action for non-participant {participant_id} in combat {combat_id}. Ignoring.")
            return

        if actor_participant_data.hp <= 0 and completed_action_data.get("type") != "system_death_processing":
            print(f"CombatManager: Participant {participant_id} is incapacitated (HP: {actor_participant_data.hp}). Action {completed_action_data.get('type')} ignored.")
            if combat.turn_order:
                combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                if combat.current_turn_index == 0:
                    combat.current_round += 1
                    combat.combat_log.append(f"Round {combat.current_round} begins (turn advanced due to incapacitated actor).")
                    for p_data_reset in combat.participants: p_data_reset.acted_this_round = False
            self.mark_combat_dirty(guild_id_str, combat_id)
            return

        actor_participant_data.acted_this_round = True
        actor_name_for_log = participant_id
        if self._character_manager and self._npc_manager: # Ensure managers available for name lookup
            if actor_participant_data.entity_type == "Character":
                char = self._character_manager.get_character(guild_id_str, participant_id)
                if char: actor_name_for_log = getattr(char, 'name', participant_id)
            elif actor_participant_data.entity_type == "NPC":
                npc = self._npc_manager.get_npc(guild_id_str, participant_id)
                if npc: actor_name_for_log = getattr(npc, 'name', participant_id)

        combat.combat_log.append(f"{actor_name_for_log} ({actor_participant_data.entity_type}) performed action: {completed_action_data.get('type')}")

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        if rule_engine and hasattr(rule_engine, 'apply_combat_action_effects'):
            print(f"CombatManager: Applying effects for action by {participant_id} in {combat_id}...")
            try:
                 action_outcomes = await rule_engine.apply_combat_action_effects( # type: ignore
                     combat=combat, actor_id=participant_id,
                     action_data=completed_action_data, context=kwargs
                 )
                 if isinstance(action_outcomes, list): combat.combat_log.extend(action_outcomes)
                 print(f"CombatManager: Effects applied for {participant_id} in {combat_id}.")
            except Exception as e:
                 print(f"CombatManager: Error applying effects for {participant_id} in {combat_id}: {e}")
                 traceback.print_exc()

        if combat.is_active and combat.get_current_actor_id() == participant_id:
            if combat.turn_order:
                combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
                if combat.current_turn_index == 0:
                    combat.current_round += 1
                    combat.combat_log.append(f"Round {combat.current_round} begins.")
                    for p_data_reset in combat.participants:
                        if p_data_reset.hp > 0: p_data_reset.acted_this_round = False
                        else: p_data_reset.acted_this_round = True
            else:
                combat.is_active = False
                print(f"CombatManager: Combat {combat_id} has no participants in turn_order after action. Ending combat.")

        self.mark_combat_dirty(guild_id_str, combat_id)

    async def end_combat(self, combat_id: str, **kwargs: Any) -> None:
        guild_id = kwargs.get('guild_id')
        if guild_id is None:
             print(f"CombatManager: end_combat for {combat_id} without guild_id.")
             return
        guild_id_str = str(guild_id)
        combat = self.get_combat(guild_id_str, combat_id)
        if not combat or str(getattr(combat, 'guild_id', None)) != guild_id_str:
            print(f"CombatManager: Attempted to end non-existent/mismatched combat {combat_id}.")
            return
        if not getattr(combat, 'is_active', False):
             print(f"CombatManager: Combat {combat_id} already ended.")
             return

        if hasattr(combat, 'is_active'): combat.is_active = False
        self.mark_combat_dirty(guild_id_str, combat_id)

        # cleanup_context = {**kwargs, 'combat': combat, 'guild_id': guild_id_str} # Not used currently

        self._deleted_combats_ids.setdefault(guild_id_str, set()).add(combat_id)
        guild_combats_cache = self._active_combats.get(guild_id_str)
        if guild_combats_cache: guild_combats_cache.pop(combat_id, None)
        if guild_id_str in self._dirty_combats and combat_id in self._dirty_combats[guild_id_str]:
            self._dirty_combats[guild_id_str].discard(combat_id)
            if not self._dirty_combats[guild_id_str]:
                del self._dirty_combats[guild_id_str]
        print(f"CombatManager: Combat {combat_id} ended for guild {guild_id_str}.")

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

print("DEBUG: combat_manager.py module loaded (with updated start_combat).")

[end of bot/game/managers/combat_manager.py]
