from __future__ import annotations
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING

# Модели для аннотаций
from bot.game.models.character import Character
from bot.game.models.npc import NPC

# Адаптер БД
from bot.database.sqlite_adapter import SqliteAdapter

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.managers.time_manager import TimeManager

# Типы коллбэков
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

class DialogueManager:
    """
    Менеджер для управления диалогами между сущностями.
    Отвечает за запуск, продвижение и завершение диалогов.
    """
    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,
        character_manager: Optional['CharacterManager'] = None,
        npc_manager: Optional['NpcManager'] = None,
        rule_engine: Optional['RuleEngine'] = None,
        event_stage_processor: Optional['EventStageProcessor'] = None,
        time_manager: Optional['TimeManager'] = None,
    ):
        print("Initializing DialogueManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._rule_engine = rule_engine
        self._event_stage_processor = event_stage_processor
        self._time_manager = time_manager

        # --- Кеши ---
        self._active_dialogues: Dict[str, Any] = {}
        self._dialogue_templates: Dict[str, Any] = {}
        self._dirty_dialogues: Set[str] = set()
        self._deleted_dialogue_ids: Set[str] = set()

        print("DialogueManager initialized.")

    async def load_dialogue_templates(self) -> None:
        print("DialogueManager: Loading dialogue templates...")
        self._dialogue_templates.clear()
        if not self._db_adapter:
            print("DialogueManager: No DB adapter, skipping templates load.")
            return
        try:
            # TODO: Реализовать SELECT шаблонов из БД
            print("DialogueManager: Dialogue template loading not yet implemented.")
        except Exception as e:
            print(f"DialogueManager: Error loading templates: {e}")
            traceback.print_exc()

    async def start_dialogue(
        self,
        template_id: str,
        participant1_id: str,
        participant2_id: str,
        channel_id: Optional[int] = None,
        event_id: Optional[str] = None,
        initial_state_data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Optional[str]:
        print(f"DialogueManager: Starting dialogue {template_id} between {participant1_id} and {participant2_id}.")
        # TODO: валидации шаблона и участников
        try:
            new_id = str(uuid.uuid4())
            dialogue = {
                'id': new_id,
                'template_id': template_id,
                'participants': [participant1_id, participant2_id],
                'channel_id': channel_id,
                'current_stage_id': 'start',
                'state_variables': initial_state_data or {},
                'last_activity_game_time': None,
                'event_id': event_id,
            }
            self._active_dialogues[new_id] = dialogue
            self._dirty_dialogues.add(new_id)
            print(f"DialogueManager: Dialogue {new_id} started and marked dirty.")
            return new_id
        except Exception as e:
            print(f"DialogueManager: Error starting dialogue: {e}")
            traceback.print_exc()
            return None

    async def advance_dialogue(
        self,
        dialogue_id: str,
        participant_id: str,
        action_data: Dict[str, Any],
        **kwargs,
    ) -> None:
        print(f"DialogueManager: Advancing dialogue {dialogue_id} by {participant_id}.")
        state = self._active_dialogues.get(dialogue_id)
        if not state:
            print(f"DialogueManager: Dialogue {dialogue_id} not found.")
            return
        # TODO: применить логику по шаблону и rule_engine
        # Обновляем last_activity
        if self._time_manager and hasattr(self._time_manager, 'get_current_game_time'):
            state['last_activity_game_time'] = self._time_manager.get_current_game_time()
        self._dirty_dialogues.add(dialogue_id)
        print(f"DialogueManager: Dialogue {dialogue_id} advanced, marked dirty.")

    def is_in_dialogue(self, entity_id: str) -> bool:
        for d in self._active_dialogues.values():
            if entity_id in d.get('participants', []):
                return True
        return False

    async def end_dialogue(self, dialogue_id: str, **kwargs) -> None:
        print(f"DialogueManager: Ending dialogue {dialogue_id}.")
        d = self._active_dialogues.pop(dialogue_id, None)
        if d:
            self._deleted_dialogue_ids.add(dialogue_id)
            print(f"DialogueManager: Dialogue {dialogue_id} marked for deletion.")

    async def save_all_dialogues(self) -> None:
        if not self._db_adapter or (not self._dirty_dialogues and not self._deleted_dialogue_ids):
            return
        try:
            # удаление
            if self._deleted_dialogue_ids:
                ids = list(self._deleted_dialogue_ids)
                sql = f"DELETE FROM dialogues WHERE id IN ({','.join('?'*len(ids))})"
                await self._db_adapter.execute(sql, tuple(ids))
                self._deleted_dialogue_ids.clear()
            # сохранение
            for did in list(self._dirty_dialogues):
                d = self._active_dialogues.get(did)
                if not d:
                    self._dirty_dialogues.discard(did)
                    continue
                sql = (
                    "INSERT OR REPLACE INTO dialogues "
                    "(id, template_id, participants, channel_id, current_stage_id, state_variables, last_activity_game_time, event_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                )
                params = (
                    d['id'],
                    d['template_id'],
                    json.dumps(d['participants']),
                    d['channel_id'],
                    d['current_stage_id'],
                    json.dumps(d['state_variables']),
                    d['last_activity_game_time'],
                    d['event_id'],
                )
                await self._db_adapter.execute(sql, params)
            self._dirty_dialogues.clear()
        except Exception as e:
            print(f"DialogueManager: Error saving dialogues: {e}")
            traceback.print_exc()
            raise

    async def load_all_dialogues(self) -> None:
        print("DialogueManager: Loading dialogues...")
        self._active_dialogues.clear()
        self._dirty_dialogues.clear()
        self._deleted_dialogue_ids.clear()
        if not self._db_adapter:
            return
        try:
            sql = (
                "SELECT id, template_id, participants, channel_id, current_stage_id, state_variables, "
                "last_activity_game_time, event_id FROM dialogues"
            )
            rows = await self._db_adapter.fetchall(sql)
            for row in rows:
                d = dict(row)
                d['participants'] = json.loads(d.get('participants') or '[]')
                d['state_variables'] = json.loads(d.get('state_variables') or '{}')
                self._active_dialogues[d['id']] = d
        except Exception as e:
            print(f"DialogueManager: Error loading dialogues: {e}")
            traceback.print_exc()
            raise

    def rebuild_runtime_caches(self) -> None:
        # no other caches
        pass
