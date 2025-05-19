# bot/game/managers/event_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

from bot.game.models.event import Event
from bot.database.sqlite_adapter import SqliteAdapter

if TYPE_CHECKING:
    # Опциональные зависимости только для аннотаций, чтобы разорвать циклы
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.event_processors.event_stage_processor import EventStageProcessor


class EventManager:
    """
    Менеджер для загрузки шаблонов и управления событиями:
    создание, хранение, сохранение/загрузка и удаление.
    """
    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,
        npc_manager: Optional['NpcManager'] = None,
        item_manager: Optional['ItemManager'] = None,
        location_manager: Optional['LocationManager'] = None,
        rule_engine: Optional['RuleEngine'] = None,
        character_manager: Optional['CharacterManager'] = None,
        combat_manager: Optional['CombatManager'] = None,
        status_manager: Optional['StatusManager'] = None,
        party_manager: Optional['PartyManager'] = None,
        time_manager: Optional['TimeManager'] = None,
        event_stage_processor: Optional['EventStageProcessor'] = None,
    ):
        print("Initializing EventManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # Инжектированные зависимости
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._time_manager = time_manager
        self._event_stage_processor = event_stage_processor

        # Шаблоны и активные события
        self._event_templates: Dict[str, Dict[str, Any]] = {}
        self._active_events: Dict[str, Event] = {}
        self._active_events_by_channel: Dict[int, str] = {}
        self._dirty_events: Set[str] = set()
        self._deleted_event_ids: Set[str] = set()

        self._load_event_templates()
        print("EventManager initialized.\n")

    def _load_event_templates(self) -> None:
        print("EventManager: Loading event templates...")
        try:
            raw = self._settings.get('event_templates', {}) if self._settings else {}
            for tpl_id, data in raw.items():
                if isinstance(data, dict):
                    clone = data.copy()
                    clone.setdefault('id', tpl_id)
                    self._event_templates[tpl_id] = clone
                else:
                    print(f"EventManager: Warning – template {tpl_id} is not a dict, skipped.")
            print(f"EventManager: Loaded {len(self._event_templates)} templates.")
        except Exception as e:
            print(f"EventManager: Error loading templates: {e}")
            traceback.print_exc()

    def get_event_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        return self._event_templates.get(template_id)

    def get_event(self, event_id: str) -> Optional[Event]:
        return self._active_events.get(event_id)

    def get_active_events(self) -> List[Event]:
        return list(self._active_events.values())

    def get_event_by_channel_id(self, channel_id: int) -> Optional[Event]:
        eid = self._active_events_by_channel.get(channel_id)
        return self._active_events.get(eid) if eid else None

    async def create_event_from_template(
        self,
        template_id: str,
        location_id: Optional[str] = None,
        initial_player_ids: Optional[List[str]] = None,
        channel_id: Optional[int] = None,
        **kwargs,
    ) -> Optional[Event]:
        print(f"EventManager: Creating event from template '{template_id}'")
        if not self._db_adapter:
            print("EventManager: No DB adapter.")
            return None

        tpl = self.get_event_template(template_id)
        if not tpl:
            print(f"EventManager: Template '{template_id}' not found.")
            return None

        try:
            eid = str(uuid.uuid4())
            data: Dict[str, Any] = {
                'id': eid,
                'template_id': template_id,
                'name': tpl.get('name', 'Событие'),
                'is_active': True,
                'channel_id': channel_id,
                'current_stage_id': tpl.get('start_stage_id', 'start'),
                'players': initial_player_ids or [],
                'state_variables': tpl.get('initial_state_variables', {}).copy(),
                'stages_data': tpl.get('stages_data', {}).copy(),
                'end_message_template': tpl.get(
                    'end_message_template',
                    'Событие завершилось.'
                ),
            }
            event = Event.from_dict(data)

            # Спавн NPC
            npc_mgr = kwargs.get('npc_manager', self._npc_manager)
            for spawn in tpl.get('npc_spawn_templates', []):
                temp_list = event.state_variables.setdefault('temp_npcs', [])
                for _ in range(spawn.get('count', 1)):
                    nid = await npc_mgr.create_npc(
                        spawn['template_id'],
                        location_id=spawn.get('location_id', location_id),
                        owner_id=eid,
                        is_temporary=spawn.get('is_temporary', True),
                        **kwargs
                    )
                    if nid:
                        temp_list.append(nid)

            # Спавн предметов
            item_mgr = kwargs.get('item_manager', self._item_manager)
            for spawn in tpl.get('item_spawn_templates', []):
                temp_list = event.state_variables.setdefault('temp_items', [])
                for _ in range(spawn.get('count', 1)):
                    iid = await item_mgr.create_item(
                        {'template_id': spawn['template_id'],
                         'is_temporary': spawn.get('is_temporary', True)},
                        **kwargs
                    )
                    if iid:
                        await item_mgr.move_item(
                            iid,
                            spawn.get('owner_id'),
                            spawn.get('location_id', location_id),
                            **kwargs
                        )
                        temp_list.append(iid)

            # Сохраняем в активные
            self._active_events[eid] = event
            self._dirty_events.add(eid)

            if channel_id is not None:
                prev = self._active_events_by_channel.get(channel_id)
                if prev:
                    print(f"EventManager: Warning – channel {channel_id} "
                          f"already had event {prev}, overriding.")
                self._active_events_by_channel[channel_id] = eid

            print(f"EventManager: Event '{eid}' created, marked dirty.")
            return event

        except Exception as exc:
            print(f"EventManager: Error creating event: {exc}")
            traceback.print_exc()
            return None

    def remove_active_event(self, event_id: str) -> Optional[str]:
        print(f"EventManager: Removing event '{event_id}'")
        ev = self._active_events.pop(event_id, None)
        if not ev:
            if event_id in self._deleted_event_ids:
                return event_id
            return None

        ch = ev.channel_id
        if ch is not None:
            self._active_events_by_channel.pop(ch, None)
        self._deleted_event_ids.add(event_id)
        self._dirty_events.discard(event_id)

        print(f"EventManager: Event '{event_id}' marked for deletion.")
        return event_id

    async def save_all_events(self) -> None:
        if (
            not self._db_adapter
            or (not self._dirty_events and not self._deleted_event_ids)
        ):
            return

        try:
            # Удаляем
            if self._deleted_event_ids:
                ids = list(self._deleted_event_ids)
                ph = ",".join("?" for _ in ids)
                await self._db_adapter.execute(
                    f"DELETE FROM events WHERE id IN ({ph})",
                    tuple(ids)
                )
                self._deleted_event_ids.clear()

            # Сохраняем
            for eid in list(self._dirty_events):
                ev = self._active_events.get(eid)
                if not ev:
                    self._dirty_events.discard(eid)
                    continue

                params = (
                    ev.id,
                    ev.template_id,
                    ev.name,
                    int(ev.is_active),
                    ev.channel_id,
                    ev.current_stage_id,
                    json.dumps(ev.players),
                    json.dumps(ev.state_variables),
                    json.dumps(ev.stages_data),
                    ev.end_message_template,
                )
                await self._db_adapter.execute(
                    """
                    INSERT OR REPLACE INTO events
                    (id, template_id, name, is_active, channel_id,
                     current_stage_id, players, state_variables,
                     stages_data, end_message_template)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params
                )
            self._dirty_events.clear()

        except Exception as exc:
            print(f"EventManager: Error saving events: {exc}")
            traceback.print_exc()
            raise

    async def load_all_events(self) -> None:
        print("EventManager: Loading events from DB...")
        self._active_events.clear()
        self._active_events_by_channel.clear()
        self._dirty_events.clear()
        self._deleted_event_ids.clear()

        if not self._db_adapter:
            return

        try:
            rows = await self._db_adapter.fetchall(
                """
                SELECT id, template_id, name, is_active, channel_id,
                       current_stage_id, players, state_variables,
                       stages_data, end_message_template
                FROM events
                """
            )
            for row in rows:
                data = dict(row)
                data['is_active'] = bool(data['is_active'])
                data['players'] = json.loads(data.get('players') or '[]')
                data['state_variables'] = json.loads(data.get('state_variables') or '{}')
                data['stages_data'] = json.loads(data.get('stages_data') or '{}')
                ev = Event.from_dict(data)
                if ev.is_active:
                    self._active_events[ev.id] = ev
                    if ev.channel_id is not None:
                        self._active_events_by_channel[ev.channel_id] = ev.id

            print(f"EventManager: Loaded {len(self._active_events)} active events.")
        except Exception as exc:
            print(f"EventManager: Error loading events: {exc}")
            traceback.print_exc()
            raise

    def rebuild_runtime_caches(self) -> None:
        print("EventManager: Rebuilding runtime caches...")
        self._active_events_by_channel.clear()
        for eid, ev in self._active_events.items():
            if ev.channel_id is not None:
                self._active_events_by_channel[ev.channel_id] = eid
        print("EventManager: Caches rebuilt.")
