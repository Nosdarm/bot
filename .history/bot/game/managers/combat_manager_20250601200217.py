from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import random
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, Set, Tuple, Union

from bot.game.models.combat import Combat, CombatParticipant
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
        self._party_manager = party_manager
        self._status_manager = status_manager
        self._item_manager = item_manager
        self._location_manager = location_manager

        # <<< DETAILED DEBUG PRINTS START >>>
        print(f"CM_INIT_DEBUG: self._rule_engine is {'NOT None' if self._rule_engine else 'None'}")
        print(f"CM_INIT_DEBUG: self._character_manager is {'NOT None' if self._character_manager else 'None'}")
        print(f"CM_INIT_DEBUG: self._npc_manager is {'NOT None' if self._npc_manager else 'None'}")
        # <<< DETAILED DEBUG PRINTS END >>>

        self._active_combats = {}
        self._dirty_combats = {}
        self._deleted_combats_ids = {}
        print("CombatManager initialized (with updated start_combat).")

    async def start_combat(self, guild_id: str, location_id: Optional[str], participant_ids_types: List[Tuple[str, str]], **kwargs: Any) -> Optional["Combat"]:
        guild_id_str = str(guild_id)
        location_id_str = str(location_id) if location_id is not None else None

        # <<< DETAILED DEBUG PRINTS START OF start_combat >>>
        print(f"CM_START_COMBAT_DEBUG: self._rule_engine is {'NOT None' if self._rule_engine else 'None'}")
        print(f"CM_START_COMBAT_DEBUG: self._character_manager is {'NOT None' if self._character_manager else 'None'}")
        print(f"CM_START_COMBAT_DEBUG: self._npc_manager is {'NOT None' if self._npc_manager else 'None'}")
        # <<< DETAILED DEBUG PRINTS END >>>

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
            if send_cb_factory and combat_channel_id is not None:
                try:
                    send_cb = send_cb_factory(int(combat_channel_id))
                    location_name_str = location_id_str or "an unknown location"
                    if self._location_manager and location_id_str:
                        loc_details = self._location_manager.get_location_instance(guild_id_str, location_id_str)
                        if loc_details:
                            location_name_str = getattr(loc_details, 'name', location_id_str)

                    start_message = f"Combat begins in {location_name_str}!"
                    if combat.turn_order:
                        first_actor_id = combat.get_current_actor_id()
                        first_actor_participant_obj = combat.get_participant_data(first_actor_id) if first_actor_id else None
                        first_actor_name = "Someone"
                        if first_actor_participant_obj:
                            if first_actor_participant_obj.entity_type == "Character" and self._character_manager:
                                actor_char = self._character_manager.get_character(guild_id_str, first_actor_participant_obj.entity_id)
                                if actor_char:
                                    first_actor_name = actor_char.name
                            elif first_actor_participant_obj.entity_type == "NPC" and self._npc_manager:
                                actor_npc = self._npc_manager.get_npc(guild_id_str, first_actor_participant_obj.entity_id)
                                if actor_npc:
                                    first_actor_name = actor_npc.name
                        start_message += f" {first_actor_name} goes first!"
                    await send_cb(start_message)
                except Exception as e:
                    print(f"CombatManager: Error sending combat start message: {e}")
                    traceback.print_exc()
            return combat
        except Exception as e:
            print(f"CombatManager: Error creating Combat object or during setup: {e}")
            traceback.print_exc()
            return None
