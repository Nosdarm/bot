# bot/game/managers/npc_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable

from bot.game.models.npc import NPC
from bot.database.sqlite_adapter import SqliteAdapter


from bot.game.managers.item_manager import ItemManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.dialogue_manager import DialogueManager

from bot.game.rules.rule_engine import RuleEngine


SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

class NpcManager:
    """
    Менеджер для управления NPC: создание, хранение, обновление и персистенция.
    Логика действий вынесена в NpcActionProcessor.
    """
    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional['ItemManager'] = None,
        status_manager: Optional['StatusManager'] = None,
        party_manager: Optional['PartyManager'] = None,
        character_manager: Optional['CharacterManager'] = None,
        rule_engine: Optional['RuleEngine'] = None,
        combat_manager: Optional['CombatManager'] = None,
        dialogue_manager: Optional['DialogueManager'] = None,
    ):
        print("Initializing NpcManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager

        # Кеш NPC
        self._npcs: Dict[str, NPC] = {}
        # Сет NPC с активным действием
        self._entities_with_active_action: Set[str] = set()
        # Изменённые и удалённые NPC для персистенции
        self._dirty_npcs: Set[str] = set()
        self._deleted_npc_ids: Set[str] = set()

        print("NpcManager initialized.")

    def get_npc(self, npc_id: str) -> Optional[NPC]:
        return self._npcs.get(npc_id)

    def get_all_npcs(self) -> List[NPC]:
        return list(self._npcs.values())

    def get_entities_with_active_action(self) -> Set[str]:
        return set(self._entities_with_active_action)

    def is_busy(self, npc_id: str) -> bool:
        npc = self.get_npc(npc_id)
        if not npc:
            return False
        if getattr(npc, 'current_action', None) is not None:
            return True
        if getattr(npc, 'party_id', None) and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
            return self._party_manager.is_party_busy(npc.party_id)
        return False

    async def create_npc(
        self,
        npc_template_id: str,
        location_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        print(f"NpcManager: Creating NPC from template '{npc_template_id}' at location {location_id}...")
        if not self._db_adapter:
            print("NpcManager: No DB adapter available.")
            return None

        # Генерация статов через RuleEngine
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        stats = {"strength":5,"dexterity":5,"intelligence":5}
        if rule_engine and hasattr(rule_engine, 'generate_initial_npc_stats'):
            try:
                out = await rule_engine.generate_initial_npc_stats(npc_template_id=npc_template_id, **kwargs)
                if isinstance(out, dict):
                    stats = out
            except Exception as e:
                print(f"NpcManager: Error gen stats: {e}")
                traceback.print_exc()

        try:
            npc_id = str(uuid.uuid4())
            data: Dict[str, Any] = {
                'id': npc_id,
                'template_id': npc_template_id,
                'name': f"NPC_{npc_id[:8]}",
                'location_id': location_id,
                'stats': stats,
                'inventory': [],
                'current_action': None,
                'action_queue': [],
                'party_id': None,
                'state_variables': {},
                'health': 50.0,
                'max_health': 50.0,
                'is_alive': True,
                'status_effects': [],
                'is_temporary': bool(kwargs.get('is_temporary', False)),
            }
            npc = NPC.from_dict(data)
            self._npcs[npc_id] = npc
            self._dirty_npcs.add(npc_id)
            print(f"NpcManager: NPC {npc_id} created.")
            return npc_id
        except Exception as e:
            print(f"NpcManager: Error creating NPC: {e}")
            traceback.print_exc()
            return None

    async def remove_npc(self, npc_id: str, **kwargs) -> Optional[str]:
        print(f"NpcManager: Removing NPC {npc_id}...")
        npc = self.get_npc(npc_id)
        if not npc:
            if npc_id in self._deleted_npc_ids:
                return npc_id
            return None

        # Очистка предметов
        im = kwargs.get('item_manager', self._item_manager)
        if im and hasattr(im, 'remove_items_by_owner'):
            try:
                await im.remove_items_by_owner(npc_id, 'NPC', **kwargs)
            except Exception:
                traceback.print_exc()
        # Очистка статусов
        sm = kwargs.get('status_manager', self._status_manager)
        if sm and hasattr(sm, 'remove_status_effects_by_target'):
            try:
                await sm.remove_status_effects_by_target(npc_id, 'NPC', **kwargs)
            except Exception:
                traceback.print_exc()
        # Очистка партии
        pm = kwargs.get('party_manager', self._party_manager)
        if getattr(npc, 'party_id', None) and pm and hasattr(pm, 'remove_member'):
            try:
                await pm.remove_member(npc.party_id, npc_id, **kwargs)
            except Exception:
                traceback.print_exc()
        # Очистка боя
        cm = kwargs.get('combat_manager', self._combat_manager)
        if cm and hasattr(cm, 'remove_participant'):
            try:
                combat = cm.get_combat_by_participant_id(npc_id)
                if combat:
                    await cm.remove_participant(combat.id, npc_id, 'NPC', **kwargs)
            except Exception:
                traceback.print_exc()
        # Очистка диалогов
        dm = kwargs.get('dialogue_manager', self._dialogue_manager)
        if dm and hasattr(dm, 'end_dialogue_by_participant'):
            try:
                await dm.end_dialogue_by_participant(npc_id, 'NPC', **kwargs)
            except Exception:
                traceback.print_exc()

        # Сброс действий
        npc.current_action = None
        npc.action_queue = []
        self._entities_with_active_action.discard(npc_id)

        # Удаление из кеша
        self._npcs.pop(npc_id, None)
        self._deleted_npc_ids.add(npc_id)
        self._dirty_npcs.discard(npc_id)
        print(f"NpcManager: NPC {npc_id} removed.")
        return npc_id

    # Методы инвентаря аналогичны CharacterManager; исправлена опечатка char -> npc
    async def add_item_to_inventory(self, npc_id: str, item_id: str, **kwargs) -> bool:
        print(f"NpcManager: Adding item {item_id} to NPC {npc_id}")
        npc = self.get_npc(npc_id)
        im = kwargs.get('item_manager', self._item_manager)
        if not npc or not im or not hasattr(im, 'move_item'):
            return False
        try:
            if not hasattr(npc, 'inventory') or not isinstance(npc.inventory, list):
                npc.inventory = []
            if item_id in npc.inventory:
                return False
            npc.inventory.append(item_id)
            self._dirty_npcs.add(npc_id)
            success = await im.move_item(item_id, new_owner_id=npc_id, new_location_id=None, **kwargs)
            return success
        except Exception:
            traceback.print_exc()
            return False

    async def remove_item_from_inventory(self, npc_id: str, item_id: str, **kwargs) -> bool:
        print(f"NpcManager: Removing item {item_id} from NPC {npc_id}")
        npc = self.get_npc(npc_id)
        im = kwargs.get('item_manager', self._item_manager)
        if not npc or not im or not hasattr(im, 'move_item'):
            return False
        if not hasattr(npc, 'inventory') or item_id not in npc.inventory:
            return False
        try:
            npc.inventory.remove(item_id)
            self._dirty_npcs.add(npc_id)
            loc = getattr(npc, 'location_id', None)
            success = await im.move_item(item_id, new_owner_id=None, new_location_id=loc, **kwargs)
            return success
        except Exception:
            traceback.print_exc()
            return False

    async def add_status_effect(self, npc_id: str, status_type: str, duration: Any, source_id: Optional[str] = None, **kwargs) -> Optional[str]:
        npc = self.get_npc(npc_id)
        sm = kwargs.get('status_manager', self._status_manager)
        if not npc or not sm or not hasattr(sm, 'add_status_effect_to_entity'):
            return None
        try:
            sid = await sm.add_status_effect_to_entity(target_id=npc_id, target_type='NPC', status_type=status_type, duration=duration, source_id=source_id, **kwargs)
            if sid:
                if not hasattr(npc, 'status_effects') or not isinstance(npc.status_effects, list):
                    npc.status_effects = []
                if sid not in npc.status_effects:
                    npc.status_effects.append(sid)
                    self._dirty_npcs.add(npc_id)
            return sid
        except Exception:
            traceback.print_exc()
            return None

    async def remove_status_effect(self, npc_id: str, status_effect_id: str, **kwargs) -> Optional[str]:
        npc = self.get_npc(npc_id)
        sm = kwargs.get('status_manager', self._status_manager)
        if not npc or not sm or not hasattr(sm, 'remove_status_effect'):
            return None
        if hasattr(npc, 'status_effects') and status_effect_id in npc.status_effects:
            npc.status_effects.remove(status_effect_id)
            self._dirty_npcs.add(npc_id)
        try:
            rid = await sm.remove_status_effect(status_effect_id, **kwargs)
            return rid
        except Exception:
            traceback.print_exc()
            return None

    async def save_all_npcs(self) -> None:
        if not self._db_adapter or (not self._dirty_npcs and not self._deleted_npc_ids):
            return
        try:
            if self._deleted_npc_ids:
                ids = list(self._deleted_npc_ids)
                ph = ','.join(['?']*len(ids))
                await self._db_adapter.execute(f"DELETE FROM npcs WHERE id IN ({ph})", tuple(ids))
                self._deleted_npc_ids.clear()
            for nid in list(self._dirty_npcs):
                npc = self._npcs.get(nid)
                if not npc:
                    self._dirty_npcs.discard(nid)
                    continue
                params = (
                    npc.id,
                    npc.template_id,
                    npc.name,
                    npc.location_id,
                    json.dumps(npc.stats),
                    json.dumps(npc.inventory),
                    json.dumps(npc.current_action) if npc.current_action is not None else None,
                    json.dumps(npc.action_queue),
                    npc.party_id,
                    json.dumps(npc.state_variables),
                    float(npc.health),
                    float(npc.max_health),
                    int(npc.is_alive),
                    json.dumps(npc.status_effects),
                    int(npc.is_temporary),
                )
                sql = '''
                    INSERT OR REPLACE INTO npcs
                    (id, template_id, name, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects, is_temporary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
                await self._db_adapter.execute(sql, params)
            self._dirty_npcs.clear()
        except Exception:
            traceback.print_exc()
            raise

    async def load_all_npcs(self) -> None:
        print("NpcManager: Loading all NPCs...")
        self._npcs.clear()
        self._entities_with_active_action.clear()
        self._dirty_npcs.clear()
        self._deleted_npc_ids.clear()
        if not self._db_adapter:
            return
        try:
            rows = await self._db_adapter.fetchall(
                'SELECT id, template_id, name, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects, is_temporary FROM npcs'
            )
            for row in rows:
                data = dict(row)
                data['stats'] = json.loads(data.get('stats') or '{}')
                data['inventory'] = json.loads(data.get('inventory') or '[]')
                data['current_action'] = json.loads(data.get('current_action') or 'null')
                data['action_queue'] = json.loads(data.get('action_queue') or '[]')
                data['state_variables'] = json.loads(data.get('state_variables') or '{}')
                data['status_effects'] = json.loads(data.get('status_effects') or '[]')
                data['health'] = float(data.get('health', 0))
                data['max_health'] = float(data.get('max_health', 0))
                data['is_alive'] = bool(data.get('is_alive', 0))
                data['is_temporary'] = bool(data.get('is_temporary', 0))
                npc = NPC.from_dict(data)
                self._npcs[npc.id] = npc
                if getattr(npc, 'current_action', None) or (hasattr(npc, 'action_queue') and npc.action_queue):
                    self._entities_with_active_action.add(npc.id)
        except Exception:
            traceback.print_exc()
            raise

    def rebuild_runtime_caches(self) -> None:
        print("NpcManager: Rebuilding caches...")
        self._entities_with_active_action = {nid for nid, npc in self._npcs.items()
                                             if getattr(npc, 'current_action', None) or (hasattr(npc, 'action_queue') and npc.action_queue)}