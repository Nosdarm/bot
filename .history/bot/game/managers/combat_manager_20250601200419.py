# bot/game/managers/combat_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import random # Added for initiative rolls
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, Set, Tuple, Union

from bot.game.models.combat import Combat, CombatParticipant # Updated import
from builtins import dict, set, list, str, int, bool, float


if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
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
        db_adapter: Optional["SqliteAdapter"] = None,
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
        self._db_adapter = db_adapter
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
                 # Updated to check CombatParticipant objects
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

    async def start_combat(self, guild_id: str, location_id: Optional[str], participant_ids_types: List[Tuple[str, str]], **kwargs: Any) -> Optional["Combat"]:
        # <<< DETAILED DEBUG PRINTS START OF start_combat >>>
        print(f"CM_START_COMBAT_DEBUG: self._rule_engine is {'NOT None' if self._rule_engine else 'None'}")
        print(f"CM_START_COMBAT_DEBUG: self._character_manager is {'NOT None' if self._character_manager else 'None'}")
        print(f"CM_START_COMBAT_DEBUG: self._npc_manager is {'NOT None' if self._npc_manager else 'None'}")
        # <<< DETAILED DEBUG PRINTS END >>>

        guild_id_str = str(guild_id)
        location_id_str = str(location_id) if location_id is not None else None
        print(f"CombatManager: Starting new combat in location {location_id_str} for guild {guild_id_str} with participants: {participant_ids_types}...")

        if self._db_adapter is None:
            print(f"CombatManager: No DB adapter. Cannot start combat.")
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
                    entity_name = getattr(char, 'name', p_id)
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
                    entity_name = getattr(npc, 'name', p_id)
                    entity_hp = int(getattr(npc, 'health', 10)) # NPC model uses 'health'
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
            'participants': [p.to_dict() for p in combat_participant_objects], # Serialized for DB
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
            if send_cb_factory and combat_channel_id is not None:
                  try:
                      send_cb = send_cb_factory(int(combat_channel_id))
                      location_name_str = location_id_str or "an unknown location"
                      if self._location_manager and location_id_str:
                          loc_details = self._location_manager.get_location_instance(guild_id_str, location_id_str)
                          if loc_details: location_name_str = getattr(loc_details, 'name', location_id_str)

                      start_message = f"Combat begins in {location_name_str}!"
                      if combat.turn_order:
                          first_actor_id = combat.get_current_actor_id()
                          first_actor_participant_obj = combat.get_participant_data(first_actor_id) if first_actor_id else None
                          first_actor_name = "Someone"
                          if first_actor_participant_obj:
                              if first_actor_participant_obj.entity_type == "Character" and self._character_manager:
                                  actor_char = self._character_manager.get_character(guild_id_str, first_actor_participant_obj.entity_id)
                                  if actor_char: first_actor_name = actor_char.name
                              elif first_actor_participant_obj.entity_type == "NPC" and self._npc_manager:
                                  actor_npc = self._npc_manager.get_npc(guild_id_str, first_actor_participant_obj.entity_id)
                                  if actor_npc: first_actor_name = actor_npc.name
                          start_message += f" {first_actor_name} goes first!"
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
             # Try to get guild_id from the combat object if not in kwargs (should not happen if WSP passes it)
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

        # Turn-based logic will go here in later tasks.
        # For now, basic round timer and end condition check remains.
        # 'time_in_current_phase' is not used by the new Combat model for simple turn advancement.
        # We can remove round_timer logic once turns are fully implemented.

        # combat.time_in_current_phase += game_time_delta # No longer using this field in Combat model
        # combat_settings = self._settings.get('combat_settings', {})
        # round_duration = float(combat_settings.get('round_duration_seconds', 6.0))
        # if combat.time_in_current_phase >= round_duration:
        #     print(f"CombatManager: Round {combat.current_round} finished for {combat_id}. Starting new round.")
        #     combat.time_in_current_phase = 0.0
        #     combat.current_round += 1
            # TODO: Reset acted_this_round for all participants

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        combat_finished = False
        if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
            try:
                combat_finished = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs)
            except Exception as e:
                print(f"CombatManager: Error in check_combat_end_conditions for {combat_id}: {e}")
                traceback.print_exc()

        self.mark_combat_dirty(guild_id_str, combat_id)
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

        # Mark actor as having acted (this logic will be refined)
        actor_participant_data.acted_this_round = True
        combat.combat_log.append(f"{getattr(actor_participant_data, 'entity_type', 'Entity')} {participant_id} performed action: {completed_action_data.get('type')}")

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        if rule_engine and hasattr(rule_engine, 'apply_combat_action_effects'):
            print(f"CombatManager: Applying effects for action by {participant_id} in {combat_id}...")
            try:
                 action_outcomes = await rule_engine.apply_combat_action_effects(
                     combat=combat, # Pass the Combat object
                     actor_id=participant_id,
                     action_data=completed_action_data, # The action dict itself
                     context=kwargs
                 )
                 if isinstance(action_outcomes, list): # Expecting list of log messages
                     combat.combat_log.extend(action_outcomes)
                 print(f"CombatManager: Effects applied for {participant_id} in {combat_id}.")
                 self.mark_combat_dirty(guild_id_str, combat_id)
            except Exception as e:
                 print(f"CombatManager: Error applying effects for {participant_id} in {combat_id}: {e}")
                 traceback.print_exc()

        # TODO: Advance turn after action (this will be more complex)
        # combat.current_turn_index = (combat.current_turn_index + 1) % len(combat.turn_order)
        # actor_participant_data.acted_this_round = True (or reset all at start of new round)
        # self.mark_combat_dirty(guild_id_str, combat_id)

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

        cleanup_context = {**kwargs, 'combat': combat, 'guild_id': guild_id_str}
        # ... (rest of cleanup logic from previous version, ensure it uses context correctly) ...

        self._deleted_combats_ids.setdefault(guild_id_str, set()).add(combat_id)
        guild_combats_cache = self._active_combats.get(guild_id_str)
        if guild_combats_cache: guild_combats_cache.pop(combat_id, None)
        self._dirty_combats.get(guild_id_str, set()).discard(combat_id)
        print(f"CombatManager: Combat {combat_id} ended for guild {guild_id_str}.")

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        # ... (load_state needs to be updated to use CombatParticipant.from_dict for participants list) ...
        guild_id_str = str(guild_id)
        print(f"CombatManager: Loading active combats for guild {guild_id_str} from DB...")
        if self._db_adapter is None: return

        self._active_combats[guild_id_str] = {}
        self._dirty_combats.pop(guild_id_str, None)
        self._deleted_combats_ids.pop(guild_id_str, None)
        rows = []
        try:
            # Include new turn_order and current_turn_index columns
            sql = '''
            SELECT id, guild_id, location_id, is_active, participants,
                   current_round, combat_log, state_variables, channel_id, event_id,
                   turn_order, current_turn_index
            FROM combats WHERE guild_id = ? AND is_active = 1
            ''' # Removed round_timer from select as it's less relevant with turns
            rows = await self._db_adapter.fetchall(sql, (guild_id_str,))
        except Exception as e:
            print(f"CombatManager: CRITICAL DB error loading combats for guild {guild_id_str}: {e}")
            traceback.print_exc()
            raise

        loaded_count = 0
        guild_combats_cache = self._active_combats[guild_id_str]
        for row_data in rows:
            data = dict(row_data)
            try:
                # Ensure guild_id from DB matches the one we are loading for
                if str(data.get('guild_id')) != guild_id_str:
                    print(f"CombatManager: Warning - Row for combat {data.get('id')} has mismatched guild_id. Skipping.")
                    continue

                # Participants are stored as JSON string of List[Dict], convert to List[CombatParticipant]
                participants_json_str = data.get('participants', '[]')
                try:
                    participants_dict_list = json.loads(participants_json_str) if isinstance(participants_json_str, str) else participants_json_str
                    if not isinstance(participants_dict_list, list): participants_dict_list = []
                except json.JSONDecodeError:
                    participants_dict_list = []

                data['participants'] = [CombatParticipant.from_dict(p_data) for p_data in participants_dict_list if isinstance(p_data, dict)]

                # turn_order is stored as JSON string of List[str]
                turn_order_json_str = data.get('turn_order', '[]')
                try:
                    data['turn_order'] = json.loads(turn_order_json_str) if isinstance(turn_order_json_str, str) else turn_order_json_str
                    if not isinstance(data['turn_order'], list): data['turn_order'] = []
                except json.JSONDecodeError:
                    data['turn_order'] = []

                data['combat_log'] = json.loads(data.get('combat_log', '[]')) if isinstance(data.get('combat_log'), str) else (data.get('combat_log', []) or [])
                data['state_variables'] = json.loads(data.get('state_variables', '{}')) if isinstance(data.get('state_variables'), str) else (data.get('state_variables', {}) or {})


                combat = Combat.from_dict(data) # This now expects participants to be List[CombatParticipant] if passed directly
                                              # but from_dict handles List[Dict] by calling CombatParticipant.from_dict
                guild_combats_cache[combat.id] = combat
                loaded_count += 1
            except Exception as e:
                print(f"CombatManager: Error loading combat object {data.get('id')}: {e}")
                traceback.print_exc()
        print(f"CombatManager: Loaded {loaded_count} active combats for guild {guild_id_str}.")


    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        # ... (save_state needs to serialize Combat.participants (List[CombatParticipant]) to List[Dict] before JSON dump)...
        guild_id_str = str(guild_id)
        if self._db_adapter is None: return

        dirty_ids = self._dirty_combats.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_combats_ids.get(guild_id_str, set()).copy()
        guild_cache = self._active_combats.get(guild_id_str, {})

        # For saving, we also need to consider ended (is_active=False) but dirty combats
        # to persist their final state before they are removed from active cache by end_combat.
        # The current logic in end_combat marks dirty then removes from _active_combats.
        # This means save_state might not pick up combats that just ended in the same tick cycle
        # if it only iterates over _active_combats.
        # A potential solution: end_combat calls save_state for the specific combat,
        # or save_state also checks a temporary list of recently ended combats.
        # For now, let's assume dirty_ids contains IDs of combats needing save, active or not.

        combats_to_upsert_data = []
        processed_dirty_ids = set()

        for combat_id in list(dirty_ids): # Iterate over a copy
            combat_obj = guild_cache.get(combat_id) # Check active cache
            if not combat_obj:
                # Potentially, it was an ended combat, try to fetch its final state if stored temporarily elsewhere
                # For simplicity now, if not in active cache, we might not save it unless end_combat ensures it's saved once.
                # Let's assume for now that if it's dirty, it should be in _active_combats or its save is handled by end_combat.
                # If end_combat marks it dirty and then it's immediately saved by persistence manager, it works.
                # If end_combat removes it from _active_combats BEFORE save_state is called by persistence, it's missed.
                # Safest: PersistenceManager calls save_state BEFORE WorldSim tick that might call end_combat.
                # Or end_combat directly triggers a save for itself.
                # For now, only save if found in active cache (which means it might be is_active=False but still cached until next load)
                print(f"CombatManager: Combat {combat_id} marked dirty for guild {guild_id_str} but not found in active cache. Skipping save.")
                continue

            combat_dict = combat_obj.to_dict() # This now correctly serializes List[CombatParticipant]

            # Ensure all fields for DB are present
            data_tuple = (
                combat_dict['id'], combat_dict['guild_id'], combat_dict.get('location_id'),
                int(combat_dict['is_active']), json.dumps(combat_dict['participants']),
                0.0, # round_timer - kept for schema compatibility, not actively used by new model
                combat_dict['current_round'], json.dumps(combat_dict['combat_log']),
                json.dumps(combat_dict['state_variables']), combat_dict.get('channel_id'),
                combat_dict.get('event_id'),
                json.dumps(combat_dict.get('turn_order', [])), # New field
                combat_dict.get('current_turn_index', 0)      # New field
            )
            combats_to_upsert_data.append(data_tuple)
            processed_dirty_ids.add(combat_id)

        if deleted_ids:
            placeholders = ','.join(['?'] * len(deleted_ids))
            delete_sql = f"DELETE FROM combats WHERE guild_id = ? AND id IN ({placeholders})"
            try:
                await self._db_adapter.execute(delete_sql, (guild_id_str, *tuple(deleted_ids)))
                self._deleted_combats_ids.pop(guild_id_str, None)
            except Exception as e: print(f"CM Error deleting combats: {e}")

        if combats_to_upsert_data:
            upsert_sql = '''
            INSERT OR REPLACE INTO combats
            (id, guild_id, location_id, is_active, participants, round_timer, current_round,
            combat_log, state_variables, channel_id, event_id, turn_order, current_turn_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            try:
                await self._db_adapter.execute_many(upsert_sql, combats_to_upsert_data)
                if guild_id_str in self._dirty_combats:
                    self._dirty_combats[guild_id_str].difference_update(processed_dirty_ids)
                    if not self._dirty_combats[guild_id_str]: del self._dirty_combats[guild_id_str]
            except Exception as e: print(f"CM Error batch upsert combats: {e}")

        print(f"CM: Save state complete for combats in guild {guild_id_str}.")


    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        print(f"CombatManager: Rebuilding runtime caches for guild {str(guild_id)}.")
        # No specific runtime caches to rebuild in CombatManager itself beyond what load_state does.
        # Other managers (Character, NPC) might use get_active_combats(guild_id) to update their busy states.
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

              # Remove from CombatParticipant list
              new_participants_list = [p for p in combat.participants if p.entity_id != entity_id]

              # Remove from turn_order list
              new_turn_order = [e_id for e_id in combat.turn_order if e_id != entity_id]

              # Adjust current_turn_index if the removed entity was before or at the current turn
              removed_actor_index = -1
              try:
                  original_turn_order = list(combat.turn_order) # copy
                  removed_actor_index = original_turn_order.index(entity_id)
              except ValueError:
                  pass # Entity not in turn order, no index adjustment needed

              combat.participants = new_participants_list
              combat.turn_order = new_turn_order

              if new_turn_order: # If combat is not empty
                  if removed_actor_index != -1 and combat.current_turn_index >= removed_actor_index:
                      # If the removed entity was before or was the current turn, decrement index
                      # This needs careful handling if it makes index < 0 or if list becomes empty
                      combat.current_turn_index = max(0, combat.current_turn_index -1)
                  # Ensure current_turn_index is valid for the new turn_order length
                  if combat.current_turn_index >= len(combat.turn_order):
                       combat.current_turn_index = 0 # Wrap around or reset
              else: # Combat became empty
                  combat.current_turn_index = 0


              print(f"CombatManager: Removed {entity_type} {entity_id} from combat {combat_id}.")
              self.mark_combat_dirty(guild_id_str, combat_id)

              rule_engine = kwargs.get('rule_engine', self._rule_engine)
              if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
                  try:
                      combat_finished = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs)
                      if combat_finished:
                          print(f"CombatManager: Combat {combat_id} ended after {entity_type} {entity_id} removed.")
                          await self.end_combat(combat_id, **kwargs)
                  except Exception as e:
                      print(f"CombatManager: Error checking end_conditions after entity removal: {e}")

print("DEBUG: combat_manager.py module loaded (with updated start_combat).")
