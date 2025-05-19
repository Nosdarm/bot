# bot/game/managers/location_manager.py

from __future__ import annotations
import json
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable


from bot.game.rules.rule_engine import RuleEngine

from bot.game.managers.event_manager import EventManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.time_manager import TimeManager

from bot.game.event_processors.event_action_processor import EventActionProcessor
from bot.game.event_processors.event_stage_processor import EventStageProcessor

from bot.database.sqlite_adapter import SqliteAdapter

SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

class LocationManager:
    """
    Менеджер для управления локациями игрового мира.
    Хранит статические шаблоны локаций и обрабатывает триггеры OnEnter/OnExit.
    """
    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional['RuleEngine'] = None,
        event_manager: Optional['EventManager'] = None,
        character_manager: Optional['CharacterManager'] = None,
        npc_manager: Optional['NpcManager'] = None,
        item_manager: Optional['ItemManager'] = None,
        combat_manager: Optional['CombatManager'] = None,
        status_manager: Optional['StatusManager'] = None,
        party_manager: Optional['PartyManager'] = None,
        time_manager: Optional['TimeManager'] = None,
        send_callback_factory: Optional[SendCallbackFactory] = None,
        event_stage_processor: Optional['EventStageProcessor'] = None,
        event_action_processor: Optional['EventActionProcessor'] = None,
    ):
        print("Initializing LocationManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._rule_engine = rule_engine
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._time_manager = time_manager
        self._send_callback_factory = send_callback_factory
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor

        # Статические шаблоны локаций
        self._location_templates: Dict[str, Dict[str, Any]] = {}
        print("LocationManager initialized.")

    async def load_location_templates(self) -> None:
        print("LocationManager: Loading location templates...")
        self._location_templates.clear()

        if not self._db_adapter:
            # Загрузить заглушки
            default_chan = self._settings.get('default_channel_id') if self._settings else None
            self._location_templates = {
                "placeholder_start_location": {
                    "id": "placeholder_start_location",
                    "name": "Стартовая Локация",
                    "description": "Это место, откуда начинаются все приключения.",
                    "exits": {"north": "forest_clearing"},
                    "channel_id": default_chan,
                    "on_enter_triggers": [],
                    "on_exit_triggers": [],
                }
            }
            print(f"LocationManager: Loaded {len(self._location_templates)} placeholder templates.")
            return

        try:
            rows = await self._db_adapter.fetchall("SELECT id, template_data FROM location_templates")
            for row in rows:
                tpl_id = row['id']
                try:
                    data = json.loads(row['template_data'] or '{}')
                    if not isinstance(data, dict):
                        print(f"LocationManager: Warning: template_data for {tpl_id} is invalid, skipped.")
                        continue
                    data.setdefault('id', tpl_id)
                    self._location_templates[tpl_id] = data
                except json.JSONDecodeError:
                    print(f"LocationManager: ❌ JSON error for template {tpl_id}")
                    traceback.print_exc()
            print(f"LocationManager: Loaded {len(self._location_templates)} templates from DB.")
        except Exception as e:
            print(f"LocationManager: Error loading templates: {e}")
            traceback.print_exc()
            raise

    def get_location_static(self, location_id: str) -> Optional[Dict[str, Any]]:
        return self._location_templates.get(location_id)

    def get_connected_locations(self, location_id: str) -> Dict[str, str]:
        tpl = self.get_location_static(location_id)
        exits = tpl.get('exits') if tpl else None
        return exits if isinstance(exits, dict) else {}

    def get_default_location_id(self) -> Optional[str]:
        return self._settings.get('default_start_location_id') if self._settings else None

    def get_location_channel(self, location_id: str) -> Optional[int]:
        tpl = self.get_location_static(location_id)
        chan = tpl.get('channel_id') if tpl else None
        try:
            return int(chan) if chan is not None else None
        except (ValueError, TypeError):
            print(f"LocationManager: Warning: invalid channel_id for {location_id}")
            return None

    async def move_entity(
        self,
        entity_id: str,
        entity_type: str,
        from_location_id: Optional[str],
        to_location_id: str,
        **kwargs,
    ) -> bool:
        # Универсальный метод для перемещения Character/NPC/Item/Party
        # Обновляет локацию внутри соответствующего менеджера, вызывает триггеры
        manager_attr = f"_{entity_type.lower()}_manager"
        mgr = getattr(self, manager_attr, None)
        if not mgr or not hasattr(mgr, 'get_' + entity_type.lower()):
            print(f"LocationManager: No manager for {entity_type}")
            return False
        entity = getattr(mgr, 'get_' + entity_type.lower())(entity_id)
        if not entity:
            print(f"LocationManager: {entity_type} {entity_id} not found")
            return False
        # Обработать OnExit
        if from_location_id:
            await self.handle_entity_departure(from_location_id, entity_id, entity_type, **kwargs)
        # Обновить location_id внутри модели
        setattr(entity, 'location_id', to_location_id)
        # Пометить dirty в соответствующем менеджере
        dirty_set = getattr(mgr, '_dirty_' + entity_type.lower() + 's', None)
        if isinstance(dirty_set, set):
            dirty_set.add(entity_id)
        # Обработать OnEnter
        await self.handle_entity_arrival(to_location_id, entity_id, entity_type, **kwargs)
        return True

    async def handle_entity_arrival(
        self,
        location_id: str,
        entity_id: str,
        entity_type: str,
        **kwargs,
    ) -> None:
        tpl = self.get_location_static(location_id)
        if not tpl:
            return
        triggers = tpl.get('on_enter_triggers')
        engine = self._rule_engine
        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers'):
            try:
                context = {'entity_id': entity_id, 'entity_type': entity_type, 'location_id': location_id}
                context.update(kwargs)
                await engine.execute_triggers(triggers, context=context)
            except Exception as e:
                print(f"LocationManager: Error OnEnter for {entity_id} in {location_id}: {e}")
                traceback.print_exc()

    async def handle_entity_departure(
        self,
        location_id: str,
        entity_id: str,
        entity_type: str,
        **kwargs,
    ) -> None:
        tpl = self.get_location_static(location_id)
        if not tpl:
            return
        triggers = tpl.get('on_exit_triggers')
        engine = self._rule_engine
        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers'):
            try:
                context = {'entity_id': entity_id, 'entity_type': entity_type, 'location_id': location_id}
                context.update(kwargs)
                await engine.execute_triggers(triggers, context=context)
            except Exception as e:
                print(f"LocationManager: Error OnExit for {entity_id} from {location_id}: {e}")
                traceback.print_exc()
    async def shutdown(self) -> None:
        """
        Останавливает мир, сохраняет состояние и закрывает соединения.
        Вызывается при выключении бота.
        """
        print("GameManager: Running shutdown...")
        # Остановить цикл тика
        if self._world_tick_task:
            self._world_tick_task.cancel()
            try:
                await self._world_tick_task
            except asyncio.CancelledError:
                pass
        # Сохранить состояние игры
        if self._persistence_manager:
            try:
                await self._persistence_manager.save_game_state()
                print("GameManager: Game state saved on shutdown.")
            except Exception as e:
                print(f"GameManager: Error saving game state on shutdown: {e}")
                traceback.print_exc()
        # Закрыть адаптер БД
        if self._db_adapter:
            try:
                await self._db_adapter.close()
                print("GameManager: Database connection closed.")
            except Exception as e:
                print(f"GameManager: Error closing database adapter: {e}")
                traceback.print_exc()
        print("GameManager: Shutdown complete.")