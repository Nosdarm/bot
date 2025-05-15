# bot/game/managers/combat_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING

from bot.game.models.combat import Combat
from bot.database.sqlite_adapter import SqliteAdapter

if TYPE_CHECKING:
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.item_manager import ItemManager

SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

class CombatManager:
    """
    Менеджер для управления боевыми сценами.
    Отвечает за запуск, ведение и завершение боев,
    хранит активные бои и координирует взаимодействие менеджеров.
    """
    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional['RuleEngine'] = None,
        character_manager: Optional['CharacterManager'] = None,
        npc_manager: Optional['NpcManager'] = None,
        party_manager: Optional['PartyManager'] = None,
        status_manager: Optional['StatusManager'] = None,
        item_manager: Optional['ItemManager'] = None,
    ):
        print("Initializing CombatManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._party_manager = party_manager
        self._status_manager = status_manager
        self._item_manager = item_manager

        self._active_combats: Dict[str, Combat] = {}
        print("CombatManager initialized.")

    def get_combat(self, combat_id: str) -> Optional[Combat]:
        return self._active_combats.get(combat_id)

    def get_active_combats(self) -> List[Combat]:
        return list(self._active_combats.values())

    def get_combat_by_participant_id(self, entity_id: str) -> Optional[Combat]:
        for combat in self._active_combats.values():
            participants = getattr(combat, 'participants', [])
            for info in participants:
                if isinstance(info, dict) and info.get('entity_id') == entity_id:
                    return combat
        return None

    async def process_combat_round(
        self,
        combat_id: str,
        game_time_delta: float,
        **kwargs: Any,
    ) -> bool:
        combat = self.get_combat(combat_id)
        if not combat or not combat.is_active:
            return True

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        try:
            if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
                finished = await rule_engine.check_combat_end_conditions(combat, context=kwargs)
                return finished
        except Exception as e:
            print(f"CombatManager: Error in end check: {e}")
            traceback.print_exc()
        return False

    async def handle_participant_action_complete(
        self,
        combat_id: str,
        participant_id: str,
        completed_action_data: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        print(f"CombatManager: Action complete for {participant_id} in combat {combat_id}")
        combat = self.get_combat(combat_id)
        if not combat or not combat.is_active:
            return

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        if rule_engine and hasattr(rule_engine, 'apply_combat_action_effects'):
            try:
                await rule_engine.apply_combat_action_effects(
                    combat,
                    participant_id,
                    completed_action_data,
                    context=kwargs
                )
            except Exception as e:
                print(f"CombatManager: Error applying action effects: {e}")
                traceback.print_exc()

    async def end_combat(
        self,
        combat_id: str,
        **kwargs: Any,
    ) -> None:
        print(f"CombatManager: Ending combat {combat_id}")
        combat = self.get_combat(combat_id)
        if not combat:
            return
        combat.is_active = False

        status_manager = kwargs.get('status_manager', self._status_manager)
        if status_manager and hasattr(status_manager, 'remove_combat_statuses_from_participants'):
            try:
                await status_manager.remove_combat_statuses_from_participants(combat_id, **kwargs)
            except Exception:
                traceback.print_exc()

        npc_manager = kwargs.get('npc_manager', self._npc_manager)
        if npc_manager and hasattr(npc_manager, 'handle_combat_end'):
            try:
                await npc_manager.handle_combat_end(combat_id, **kwargs)
            except Exception:
                traceback.print_exc()

        # Убираем из кеша
        self._active_combats.pop(combat_id, None)
        print(f"CombatManager: Combat {combat_id} removed from active cache.")

    async def save_all_combats(self) -> None:
        print("CombatManager: save_all_combats not implemented.")

    async def load_all_combats(self) -> None:
        print("CombatManager: load_all_combats not implemented.")

    def rebuild_runtime_caches(self) -> None:
        print("CombatManager: rebuild_runtime_caches not implemented.")
