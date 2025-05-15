# bot/game/managers/status_manager.py

# --- Импорты ---
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING
from dataclasses import dataclass, field

# Импорт модели StatusEffect
from bot.game.models.status_effect import StatusEffect
# Импорт адаптера БД
from bot.database.sqlite_adapter import SqliteAdapter

if TYPE_CHECKING:
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.event_processors.event_stage_processor import EventStageProcessor

# Define send callback type (нужен для отправки уведомлений о статусах)
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class StatusManager:
    """
    Менеджер для управления статус-эффектами.
    Отвечает за наложение, снятие, обновление длительности и применение эффектов статусов.
    Централизованно обрабатывается в мировом тике.
    """
    def __init__(self,
                 db_adapter: Optional[SqliteAdapter] = None,
                 settings: Optional[Dict[str, Any]] = None,

                 rule_engine: Optional['RuleEngine'] = None,
                 time_manager: Optional['TimeManager'] = None,
                 character_manager: Optional['CharacterManager'] = None,
                 npc_manager: Optional['NpcManager'] = None,
                 combat_manager: Optional['CombatManager'] = None,
                 party_manager: Optional['PartyManager'] = None,
                 # event_manager: Optional['EventManager'] = None,
                 # event_stage_processor: Optional['EventStageProcessor'] = None,
                 ):
        print("Initializing StatusManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._party_manager = party_manager
        # self._event_manager = event_manager
        # self._event_stage_processor = event_stage_processor

        # --- Внутренние кеши ---
        self._status_effects: Dict[str, StatusEffect] = {}
        self._status_templates: Dict[str, Dict[str, Any]] = {}
        # self._status_effects_by_target: Dict[str, Set[str]] = {}

        self._dirty_status_effects: Set[str] = set()
        self._deleted_status_effects_ids: Set[str] = set()

        # Загрузить статические шаблоны статусов
        self._load_status_templates()

        print("StatusManager initialized.")

    def _load_status_templates(self):
        """(Пример) Загружает статические шаблоны статус-эффектов из settings."""
        print("StatusManager: Loading status templates...")
        self._status_templates = {}
        try:
            if self._settings and 'status_templates' in self._settings:
                self._status_templates = self._settings.get('status_templates', {})
            print(f"StatusManager: Loaded {len(self._status_templates)} status templates.")
        except Exception as e:
            print(f"StatusManager: Error loading status templates: {e}")
            traceback.print_exc()

    def get_status_template(self, status_type: str) -> Optional[Dict[str, Any]]:
        return self._status_templates.get(status_type)

    def get_status_name(self, status_type: str) -> Optional[str]:
        tpl = self.get_status_template(status_type)
        return tpl.get('name', status_type) if tpl else None

    def get_status_effect(self, status_effect_id: str) -> Optional[StatusEffect]:
        return self._status_effects.get(status_effect_id)

    def get_status_effect_description(self, status_effect_id: str) -> Optional[str]:
        effect = self.get_status_effect(status_effect_id)
        if not effect:
            return None
        tpl = self.get_status_template(effect.status_type)
        name = tpl.get('name', effect.status_type) if tpl else effect.status_type
        desc = [name]
        if effect.duration is not None:
            desc.append(f"({effect.duration:.1f} ост.)")
        return " ".join(desc)

    async def add_status_effect_to_entity(self,
                                          target_id: str,
                                          target_type: str,
                                          status_type: str,
                                          duration: Optional[Any] = None,
                                          source_id: Optional[str] = None,
                                          **kwargs) -> Optional[str]:
        print(f"StatusManager: Adding status '{status_type}' to {target_type} {target_id}...")
        if self._db_adapter is None:
            print("StatusManager: No DB adapter.")
            return None

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        try:
            new_id = str(uuid.uuid4())
            time_mgr = kwargs.get('time_manager', self._time_manager)
            applied_at = None
            if time_mgr and hasattr(time_mgr, 'get_current_game_time'):
                applied_at = time_mgr.get_current_game_time()
            pdur = None
            if duration is not None:
                try:
                    pdur = float(duration)
                except:
                    print(f"StatusManager: Bad duration '{duration}', making permanent.")
            data = {
                'id':      new_id,
                'status_type': status_type,
                'target_id':   target_id,
                'target_type': target_type,
                'duration':    pdur,
                'applied_at':  applied_at,
                'source_id':   source_id,
                'state_variables': {}
            }
            eff = StatusEffect.from_dict(data)
            self._status_effects[new_id] = eff
            self._dirty_status_effects.add(new_id)
            print(f"StatusManager: Status {new_id} added.")
            return new_id
        except Exception as e:
            print(f"StatusManager: Error adding status: {e}")
            traceback.print_exc()
            return None

    async def remove_status_effect(self, status_effect_id: str, **kwargs) -> Optional[str]:
        print(f"StatusManager: Removing status {status_effect_id}...")
        eff = self.get_status_effect(status_effect_id)
        if not eff:
            print("StatusManager: Not found.")
            return None

        # Локальный импорт только если нужен
        # from bot.game.rules.rule_engine import RuleEngine
        # rule_engine = kwargs.get('rule_engine', self._rule_engine)
        # if rule_engine and hasattr(rule_engine, 'apply_status_on_remove'):
        #     await rule_engine.apply_status_on_remove(eff, **kwargs)

        self._status_effects.pop(status_effect_id)
        self._dirty_status_effects.discard(status_effect_id)
        self._deleted_status_effects_ids.add(status_effect_id)
        print(f"StatusManager: Status {status_effect_id} marked for deletion.")
        return status_effect_id

    async def process_tick(self, game_time_delta: float, **kwargs) -> None:
        if self._db_adapter is None:
            return

        time_mgr = kwargs.get('time_manager', self._time_manager)
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        char_mgr = kwargs.get('character_manager', self._character_manager)
        npc_mgr  = kwargs.get('npc_manager', self._npc_manager)

        to_remove: List[str] = []

        for eff_id, eff in list(self._status_effects.items()):
            try:
                if eff.duration is not None:
                    if not isinstance(eff.duration, (int, float)):
                        to_remove.append(eff_id)
                        continue
                    eff.duration -= game_time_delta
                    self._dirty_status_effects.add(eff_id)
                    if eff.duration <= 0:
                        to_remove.append(eff_id)
                        continue

                tpl = self.get_status_template(eff.status_type)
                if tpl and rule_engine and hasattr(rule_engine, 'apply_status_periodic_effects'):
                    target = None
                    if eff.target_type == 'Character' and char_mgr:
                        target = char_mgr.get_character(eff.target_id)
                    elif eff.target_type == 'NPC' and npc_mgr:
                        target = npc_mgr.get_npc(eff.target_id)
                    if target:
                        await rule_engine.apply_status_periodic_effects(
                            status_effect=eff,
                            target_entity=target,
                            game_time_delta=game_time_delta,
                            **kwargs
                        )
            except Exception as e:
                print(f"StatusManager: Error in tick for status {eff_id}: {e}")
                traceback.print_exc()
                to_remove.append(eff_id)

        for eid in set(to_remove):
            await self.remove_status_effect(eid, **kwargs)

    async def save_all_statuses(self) -> None:
        if self._db_adapter is None or (not self._dirty_status_effects and not self._deleted_status_effects_ids):
            return

        print(f"StatusManager: Saving {len(self._dirty_status_effects)} dirty and {len(self._deleted_status_effects_ids)} deleted statuses...")
        try:
            if self._deleted_status_effects_ids:
                dels = list(self._deleted_status_effects_ids)
                sql_del = f"DELETE FROM statuses WHERE id IN ({','.join('?'*len(dels))})"
                await self._db_adapter.execute(sql_del, tuple(dels))
                self._deleted_status_effects_ids.clear()

            for sid in list(self._dirty_status_effects):
                eff = self._status_effects.get(sid)
                if not eff:
                    self._dirty_status_effects.discard(sid)
                    continue
                sv_json = json.dumps(eff.state_variables) if eff.state_variables else "{}"
                sql = """
                    INSERT OR REPLACE INTO statuses
                    (id, status_type, target_id, target_type, duration, applied_at, source_id, state_variables)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """
                params = (
                    eff.id,
                    eff.status_type,
                    eff.target_id,
                    eff.target_type,
                    eff.duration,
                    eff.applied_at,
                    eff.source_id,
                    sv_json
                )
                await self._db_adapter.execute(sql, params)

            await self._db_adapter.commit()
            self._dirty_status_effects.clear()
            print("StatusManager: Save complete.")
        except Exception as e:
            print(f"StatusManager: Error saving statuses: {e}")
            traceback.print_exc()
            if self._db_adapter:
                await self._db_adapter.rollback()

    async def load_all_statuses(self, **kwargs) -> None:
        print("StatusManager: Loading statuses from DB...")
        self._status_effects.clear()
        self._dirty_status_effects.clear()
        self._deleted_status_effects_ids.clear()

        if self._db_adapter is None:
            print("StatusManager: No DB adapter; skipping load.")
            return

        try:
            rows = await self._db_adapter.fetchall(
                "SELECT id, status_type, target_id, target_type, duration, applied_at, source_id, state_variables FROM statuses"
            )
            tm = kwargs.get('time_manager', self._time_manager)
            now = None
            if tm and hasattr(tm, 'get_current_game_time'):
                now = tm.get_current_game_time()

            for row in rows:
                try:
                    rd = dict(row)
                    rd['state_variables'] = json.loads(rd.get('state_variables') or '{}')
                    eff = StatusEffect.from_dict(rd)
                    if eff.duration is not None and eff.applied_at is not None and now is not None:
                        elapsed = now - eff.applied_at
                        if elapsed > 0:
                            eff.duration -= elapsed
                            if eff.duration <= 0:
                                self._deleted_status_effects_ids.add(eff.id)
                                continue
                            else:
                                self._dirty_status_effects.add(eff.id)
                    self._status_effects[eff.id] = eff
                except Exception as e:
                    print(f"StatusManager: Error loading row {row.get('id')}: {e}")
                    traceback.print_exc()
            print(f"StatusManager: Loaded {len(self._status_effects)} statuses.")
        except Exception as e:
            print(f"StatusManager: Error loading statuses: {e}")
            traceback.print_exc()

    def rebuild_runtime_caches(self) -> None:
        """Перестраивает кеши, если они есть."""
        print("StatusManager: Rebuilding runtime caches...")
        # Если реализуется _status_effects_by_target, здесь его инициализировать.
        print("StatusManager: Runtime caches rebuilt.")


@dataclass
class NPC:
    """
    Модель данных для неигрового персонажа (экземпляра NPC в мире).
    """
    id: str
    template_id: str
    name: str
    location_id: Optional[str]
    owner_id: Optional[str]
    is_temporary: bool = False
    stats: Dict[str, Any] = field(default_factory=dict)
    inventory: List[str] = field(default_factory=list)
    current_action: Optional[Dict[str, Any]] = None
    action_queue: List[Dict[str, Any]] = field(default_factory=list)
    party_id: Optional[str] = None
    state_variables: Dict[str, Any] = field(default_factory=dict)
    health: float = 0.0
    max_health: float = 0.0
    is_alive: bool = True
    status_effects: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'template_id': self.template_id,
            'name': self.name,
            'location_id': self.location_id,
            'owner_id': self.owner_id,
            'is_temporary': self.is_temporary,
            'stats': self.stats,
            'inventory': self.inventory,
            'current_action': self.current_action,
            'action_queue': self.action_queue,
            'party_id': self.party_id,
            'state_variables': self.state_variables,
            'health': self.health,
            'max_health': self.max_health,
            'is_alive': self.is_alive,
            'status_effects': self.status_effects,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "NPC":
        npc_id = data['id']
        tpl_id = data['template_id']
        name = data['name']
        location_id = data.get('location_id')
        owner_id = data.get('owner_id')
        is_temp = bool(data.get('is_temporary', False))
        stats = data.get('stats', {}) or {}
        inv = data.get('inventory', []) or []
        cur = data.get('current_action')
        queue = data.get('action_queue', []) or []
        if not isinstance(queue, list):
            print(f"NPC Model: action_queue is not a list, resetting.")
            queue = []
        party_id = data.get('party_id')
        sv = data.get('state_variables', {}) or {}
        health = float(data.get('health', 0.0))
        max_h = float(data.get('max_health', 0.0))
        alive = bool(data.get('is_alive', False))
        se = data.get('status_effects', []) or []
        if not isinstance(se, list):
            print(f"NPC Model: status_effects not list, resetting.")
            se = []
        return NPC(
            id=npc_id,
            template_id=tpl_id,
            name=name,
            location_id=location_id,
            owner_id=owner_id,
            is_temporary=is_temp,
            stats=stats,
            inventory=inv,
            current_action=cur,
            action_queue=queue,
            party_id=party_id,
            state_variables=sv,
            health=health,
            max_health=max_h,
            is_alive=alive,
            status_effects=se,
        )
