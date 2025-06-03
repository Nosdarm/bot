# bot/game/world_simulation_processor.py

# --- Импорты ---
import asyncio
import traceback
# ИСПРАВЛЕНИЕ: Добавляем Union для аннотаций, если нужно
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable, Set, Union


# --- Импорт Менеджеров ---
# Убедитесь, что все менеджеры, чьи process_tick вызываются (или которые передаются в kwargs другим process_tick), импортированы.
# Используйте строковые аннотации, если есть циклы импорта.
# В данном файле, видимо, прямые импорты менеджеров используются для type hints в __init__.
# Если EventManager, CharacterManager и т.д. нужны для создания их инстансов где-то, их надо импортировать там.
# Здесь они нужны для Type Hinting в __init__ и вложенных методах.
# Используя from __future__ import annotations и строковые литералы в __init__,
# эти импорты МОГЛИ БЫ быть только в TYPE_CHECKING, но текущая структура использует их напрямую.
# Пока оставим прямые импорты здесь, если они нужны для аннотаций, кроме строковых.
from bot.game.managers.event_manager import EventManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.crafting_manager import CraftingManager
from bot.game.managers.economy_manager import EconomyManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.dialogue_manager import DialogueManager
from bot.game.managers.quest_manager import QuestManager
from bot.game.managers.relationship_manager import RelationshipManager
from bot.game.managers.game_log_manager import GameLogManager

# --- Импорт Сервисов ---
from bot.services.openai_service import OpenAIService
from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator

# --- Импорт Процессоров ---
from bot.game.event_processors.event_stage_processor import EventStageProcessor
from bot.game.event_processors.event_action_processor import EventActionProcessor # Нужен в kwargs (или нет?), GameManager его передает

# ИСПРАВЛЕНИЕ: Импортируем Processors Действий
from bot.game.character_processors.character_action_processor import CharacterActionProcessor
from bot.game.party_processors.party_action_processor import PartyActionProcessor
# TODO: Импортируем NpcActionProcessor, если он будет создан
from bot.game.npc_processors.npc_action_processor import NpcActionProcessor


# --- Импорт PersistenceManager ---
from bot.game.managers.persistence_manager import PersistenceManager

# --- Импорт Моделей (для аннотаций) ---
from bot.game.models.event import Event, EventStage
from bot.game.models.character import Character
from bot.game.models.npc import NPC
from bot.game.models.item import Item
from bot.game.models.combat import Combat
from bot.game.models.party import Party


# Определение Type Alias для Send Callback (функция, отправляющая сообщение в конкретный канал)
# SendToChannelCallback определен в GameManager, его нужно импортировать или определить здесь
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class WorldSimulationProcessor:
    """
    Отвечает за координацию динамической части игры:
    - Жизненный цикл событий (старт, завершение).
    - Обработка мирового "тика" (обновление времени, статусов, таймеров событий, бои, действия сущностей).
    - Использует другие менеджеры, сервисы и процессоры для выполнения своих задач.
    """
    def __init__(self,
                 # Принимаем зависимости, которые передает GameManager.
                 # Убедитесь, что порядок параметров здесь соответствует порядку, в котором GameManager их передает.

                 # --- ОБЯЗАТЕЛЬНЫЕ зависимости ---
                 event_manager: EventManager,
                 character_manager: CharacterManager,
                 location_manager: LocationManager,
                 rule_engine: RuleEngine,
                 openai_service: OpenAIService, # Обязателен, т.к. передается в tick методы.
                 event_stage_processor: EventStageProcessor,
                 event_action_processor: EventActionProcessor,
                 persistence_manager: PersistenceManager,
                 settings: Dict[str, Any],
                 send_callback_factory: SendCallbackFactory,

                 # ИСПРАВЛЕНИЕ: Добавляем Processors Действий как ОБЯЗАТЕЛЬНЫЕ зависимости
                 character_action_processor: CharacterActionProcessor,
                 party_action_processor: PartyActionProcessor,
                 # TODO: Добавьте NpcActionProcessor, если он будет создан, как ОБЯЗАТЕЛЬНЫЙ
                 # npc_action_processor: NpcActionProcessor,

                 # TODO: Добавьте другие ОБЯЗАТЕЛЬНЫЕ зависимости сюда, если они есть

                 # --- ОПЦИОНАЛЬНЫЕ зависимости (СО значениями по умолчанию) ---
                 npc_manager: Optional[NpcManager] = None,
                 combat_manager: Optional[CombatManager] = None,
                 item_manager: Optional[ItemManager] = None,
                 time_manager: Optional[TimeManager] = None,
                 status_manager: Optional[StatusManager] = None,
                 crafting_manager: Optional[CraftingManager] = None,
                 economy_manager: Optional[EconomyManager] = None,
                 party_manager: Optional[PartyManager] = None, # PartyManager нужен PartyActionProcessor, но PartyActionProcessor его получает в __init__
                                                                # WorldSimulationProcessor может передавать его в kwargs при вызове process_tick др. менеджеров
                                                                # или party_manager нужен WSP напрямую? (см. get_parties_with_active_action)
                                                                # Да, PartyManager нужен WSP для get_parties_with_active_action. Сделаем его ОПЦИОНАЛЬНЫМ.
                 dialogue_manager: Optional[DialogueManager] = None,
                 quest_manager: Optional[QuestManager] = None,
                 relationship_manager: Optional[RelationshipManager] = None,
                 game_log_manager: Optional[GameLogManager] = None,
                 multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None,
                ):
        print("Initializing WorldSimulationProcessor...")
        # --- Сохранение всех переданных аргументов в self._... ---
        # Обязательные
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._openai_service = openai_service
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor
        self._persistence_manager = persistence_manager
        self._settings = settings
        self._send_callback_factory = send_callback_factory

        # ИСПРАВЛЕНИЕ: Сохраняем Processors Действий
        self._character_action_processor = character_action_processor
        self._party_action_processor = party_action_processor
        # TODO: Сохраните NpcActionProcessor
        # self._npc_action_processor = npc_action_processor


        # Опциональные
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._item_manager = item_manager
        self._time_manager = time_manager
        self._status_manager = status_manager
        self._crafting_manager = crafting_manager
        self._economy_manager = economy_manager
        self._party_manager = party_manager # PartyManager нужен WSP
        self._dialogue_manager = dialogue_manager
        self._quest_manager = quest_manager
        self._relationship_manager = relationship_manager
        self._game_log_manager = game_log_manager
        self._multilingual_prompt_generator = multilingual_prompt_generator

        # TODO: Сохраните другие опциональные менеджеры/сервисы


        self._command_prefix = settings.get('discord_command_prefix', '/')

        print("WorldSimulationProcessor initialized.")


    # --- Методы Жизненного Цикла Событий (start/end event - остаются прежними) ---

    async def start_new_event(self,
                              event_template_id: str,
                              location_id: str,
                              # ИСПРАВЛЕНИЕ: Принимаем guild_id явно
                              guild_id: str,
                              players_discord_ids: List[int],
                              channel_id: int,
                              **kwargs: Any # Принимаем дополнительный контекст извне
                             ) -> Optional[str]:
        # ... (логика start_new_event остается прежней, но убедитесь, что она использует self._атрибуты и передает guild_id где нужно) ...
        """
        Оркестрирует запуск нового события из шаблона.
        """
        print(f"WorldSimulationProcessor initiating start of new event from template '{event_template_id}' at location {location_id} in guild {guild_id} channel {channel_id}.")
        status_callback = self._send_callback_factory(channel_id) # Callback для канала, откуда пришла команда


        # Создаем словарь контекста для передачи в другие менеджеры/процессоры
        context_for_managers: Dict[str, Any] = {
            'guild_id': guild_id, # Передаем guild_id
            'channel_id': channel_id, # Передаем channel_id команды
            'send_callback_factory': self._send_callback_factory, # Передаем фабрику
            'settings': self._settings, # Передаем настройки
            # Передаем ссылки на себя и другие менеджеры/процессоры
            'world_simulation_processor': self,
            'character_manager': self._character_manager, 'location_manager': self._location_manager,
            'rule_engine': self._rule_engine, 'openai_service': self._openai_service,
            'npc_manager': self._npc_manager, 'combat_manager': self._combat_manager,
            'item_manager': self._item_manager, 'time_manager': self._time_manager,
            'status_manager': self._status_manager, 'party_manager': self._party_manager,
            'event_manager': self._event_manager, 'persistence_manager': self._persistence_manager,
            'character_action_processor': self._character_action_processor,
            'party_action_processor': self._party_action_processor,
            'event_stage_processor': self._event_stage_processor, # StageProcessor нужен сам себе, но также передается другим
            # TODO: Добавьте другие менеджеры/процессоры, включая NpcActionProcessor
        }
        context_for_managers.update(kwargs) # Добавляем любые дополнительные kwargs, переданные извне

        # --- 1. Валидация входных данных ---
        # EventManager.get_event_template обычно не требует guild_id
        event_template_data = self._event_manager.get_event_template(event_template_id)
        if not event_template_data:
             print(f"WorldSimulationProcessor: Error starting event: Event template '{event_template_id}' not found.")
             await status_callback(f"❌ Ошибка: Шаблон события '{event_template_id}' не найден.")
             return None

        # LocationManager.get_location_static может принимать guild_id, если локации пер-гильдийные
        location_data = self._location_manager.get_location_static(guild_id, location_id) # Убедитесь в сигнатуре get_location_static
        if not location_data:
             print(f"WorldSimulationProcessor: Error starting event: Location '{location_id}' not found for guild {guild_id}.")
             await status_callback(f"❌ Ошибка: Локация '{location_id}' не найдена для вашей гильдии.")
             return None

        # Определяем финальный канал события: если в данных локации указан канал, используем его, иначе канал, из которого пришла команда
        event_channel_id_final = location_data.get('channel_id') # Предполагаем, что location_data может содержать 'channel_id'
        if event_channel_id_final is None:
             event_channel_id_final = channel_id # Если в локации не указан, используем канал команды
             print(f"WorldSimulationProcessor: No specific channel_id found for location {location_id} in guild {guild_id}. Using command channel {channel_id} for event.")
             # Валидация, что канал команды (channel_id) передан и является числом
             if not isinstance(event_channel_id_final, int):
                  print(f"WorldSimulationProcessor: Error starting event: Command channel ID is not an integer ({channel_id}). Cannot determine event channel.")
                  await status_callback(f"❌ Ошибка: Не удалось определить Discord канал для события.")
                  return None

        player_char_ids: List[str] = []
        if players_discord_ids:
             for discord_id in players_discord_ids:
                  # CharacterManager.get_character_by_discord_id должен принимать guild_id
                  char = self._character_manager.get_character_by_discord_id(guild_id, discord_id) # Убедитесь в сигнатуре
                  if char:
                       player_char_ids.append(getattr(char, 'id')) # Получаем ID из объекта
                  else:
                       print(f"WorldSimulationProcessor: Warning: Character not found for Discord user ID: {discord_id} in guild {guild_id}. Cannot add to event.")


        # TODO: Добавить логику автоматического включения игроков, находящихся в указанной локации, если шаблон позволяет/требует.
        # Используйте self._character_manager.get_characters_in_location(guild_id, location_id)


        # --- 2. Создание объекта События ---
        try:
            # Передаем ВСЕ менеджеры и контекст в kwargs для create_event_from_template.
            # EventManager.create_event_from_template должен иметь **kwargs в сигнатуре и извлекать нужные менеджеры.
            new_event: Optional[Event] = await self._event_manager.create_event_from_template(
                template_id=event_template_id,
                location_id=location_id,
                guild_id=guild_id, # Передаем guild_id
                initial_player_ids=player_char_ids,
                channel_id=event_channel_id_final,
                **context_for_managers # Передаем все собранные менеджеры и контекст
            )

            if new_event is None:
                 print(f"WorldSimulationProcessor: Error: EventManager failed to create event object from template '{event_template_id}' for guild {guild_id}.")
                 await status_callback(f"❌ Ошибка при создании события из шаблона '{event_template_id}'. EventManager вернул None.")
                 return None

            print(f"WorldSimulationProcessor: Event object {new_event.id} ('{new_event.name}') created for guild {guild_id} location {location_id} in channel {new_event.channel_id}. Initial stage: {new_event.current_stage_id}")

        except Exception as e:
             print(f"WorldSimulationProcessor: Exception caught while creating event object from template {event_template_id} for guild {guild_id}: {e}")
             import traceback
             print(traceback.format_exc())
             await status_callback(f"❌ Критическая ошибка при создании события из шаблона '{event_template_id}': {e}. Смотрите логи бота.")
             return None


        # --- 3. Помечаем событие как активное и добавляем в runtime кеш ---
        new_event.is_active = True
        # EventManager.add_active_event должен обрабатывать пер-гильдийный кеш, если используется.
        self._event_manager.add_active_event(guild_id, new_event) # Убедитесь в сигнатуре EventManager


        # --- 4. Запускаем обработку ПЕРВОЙ стадии события ---
        print(f"WorldSimulationProcessor: Calling EventStageProcessor to process the initial stage '{new_event.current_stage_id}' for event {new_event.id} in guild {guild_id}.")

        try:
            if new_event.channel_id is None:
                 print(f"WorldSimulationProcessor: Error: Newly created event {new_event.id} in guild {guild_id} has no channel_id before processing initial stage.")
                 await status_callback(f"❌ Ошибка: Созданное событие не привязано к Discord каналу. Невозможно обработать начальную стадию.")
                 try: await self.end_event(guild_id, new_event.id) # Вызываем end_event с guild_id
                 except Exception as cleanup_e: print(f"WorldSimulationProcessor: Error during cleanup of event {new_event.id} after channel error: {cleanup_e}")
                 return None

            event_channel_callback = self._send_callback_factory(new_event.channel_id)

            # Передаем ВСЕ необходимые зависимости StageProcessor'у из context_for_managers
            await self._event_stage_processor.advance_stage(
                event=new_event, target_stage_id=new_event.current_stage_id,
                send_message_callback=event_channel_callback,
                **context_for_managers, # Передаем все зависимости
                transition_context={"trigger": "event_start", "template_id": event_template_id, "location_id": location_id, "guild_id": guild_id}
            )
            print(f"WorldSimulationProcessor: Initial stage processing completed for event {new_event.id} in guild {guild_id}.")


            # --- 5. Сохраняем начальное состояние после обработки первой стадии ---
            # PersistenceManager.save_game_state ожидает guild_ids: List[str]
            if self._persistence_manager:
                 try:
                     # Передаем TimeManager и другие нужные менеджеры в kwargs сохранения
                     save_kwargs = {'time_manager': self._time_manager} # TimeManager нужен для сохранения
                     save_kwargs.update(context_for_managers) # Добавляем остальной контекст (менеджеры и т.д.)
                     # PersistenceManager.save_game_state ожидает список ID гильдий
                     await self._persistence_manager.save_game_state(guild_ids=[guild_id], **save_kwargs) # Сохраняем только для этой гильдии
                     print(f"WorldSimulationProcessor: Initial game state saved after starting event {new_event.id} for guild {guild_id}.")
                 except Exception as e:
                     print(f"WorldSimulationProcessor: Error during initial save after event start for guild {guild_id}: {e}")
                     import traceback
                     print(traceback.format_exc())
            else:
                  print("WorldSimulationProcessor: Skipping initial save after event start (PersistenceManager not available).")


            return new_event.id

        except Exception as e:
            print(f"WorldSimulationProcessor: ❌ КРИТИЧЕСКАЯ ОШИБКА во время обработки начальной стадии события {new_event.id} для гильдии {guild_id}: {e}")
            import traceback
            print(traceback.format_exc())

            try: await self.end_event(guild_id, new_event.id) # Вызываем end_event с guild_id
            except Exception as cleanup_e: print(f"WorldSimulationProcessor: Error during cleanup of event {new_event.id} after critical stage processing error: {cleanup_e}")

            await status_callback(f"❌ КРИТИЧЕСКАЯ ОШИБКА при запуске начальной стадии события '{event_template_id}': {e}. Событие остановлено. Проверьте логи бота.")

            return None


    # ИСПРАВЛЕНИЕ: end_event должен принимать guild_id
    async def end_event(self, guild_id: str, event_id: str) -> None:
        # ... (логика end_event остается прежней, но убедитесь, что cleanup логика использует self._атрибуты и guild_id где нужно) ...
        """
        Оркестрирует процесс завершения события для определенной гильдии.
        """
        print(f"WorldSimulationProcessor: Received request to end event {event_id} for guild {guild_id}.")

        # Создаем словарь контекста для передачи в cleanup методы менеджеров
        cleanup_context: Dict[str, Any] = {
            'guild_id': guild_id,
            'event_id': event_id,
            'send_callback_factory': self._send_callback_factory,
            'settings': self._settings,
            # Передаем менеджеры/процессоры, которые могут понадобиться в cleanup методах
            'character_manager': self._character_manager, 'location_manager': self._location_manager,
            'rule_engine': self._rule_engine, 'openai_service': self._openai_service,
            'npc_manager': self._npc_manager, 'combat_manager': self._combat_manager,
            'item_manager': self._item_manager, 'time_manager': self._time_manager,
            'status_manager': self._status_manager, 'party_manager': self._party_manager,
            'event_manager': self._event_manager,
            # TODO: Передайте Processors Действий, если они нужны в cleanup
            # 'character_action_processor': self._character_action_processor,
            # 'party_action_processor': self._party_action_processor,
            # 'npc_action_processor': self._npc_action_processor,
        }

        # EventManager.get_event должен принимать guild_id
        event: Optional[Event] = self._event_manager.get_event(guild_id, event_id) # Убедитесь в сигнатуре

        if not event:
            print(f"WorldSimulationProcessor: Warning: Attempted to end non-existent event {event_id} for guild {guild_id}.")
            return

        # Проверяем, не находится ли событие уже в процессе завершения или завершено
        if not event.is_active and event.current_stage_id == 'event_end':
             print(f"WorldSimulationProcessor: Event {event_id} for guild {guild_id} is already marked as ended. Skipping end process.")
             return

        # Если событие еще не в стадии завершения, переводим его туда (для триггеров OnExit стадии)
        if event.current_stage_id != 'event_end':
             print(f"WorldSimulationProcessor: Forcing event {event.id} for guild {guild_id} current_stage_id to 'event_end' for termination.")
             # TODO: Возможно, вызывать event_stage_processor.advance_stage(..., target='event_end') с guild_id
             # Чтобы все OnExit триггеры для текущей стадии выполнились корректно?
             # Требует, чтобы 'event_end' была определена как стадия в шаблоне.
             # Если 'event_end' не определена как стадия, это может вызвать проблемы.
             # Для простоты пока просто меняем ID стадии.
             event.current_stage_id = 'event_end'
             # Помечаем событие как измененное вручную через EventManager
             self._event_manager.mark_event_dirty(guild_id, event.id) # Убедитесь в сигнатуре EventManager


        print(f"WorldSimulationProcessor: Ending event {event.id} ('{event.name}') for guild {guild_id}. Initiating cleanup.")

        # TODO: --- 1. Выполнение Cleanup Логики ---
        # Используем инжектированные менеджеры (проверяем их наличие перед использованием)
        # Передаем cleanup_context (который содержит guild_id) во все cleanup методы менеджеров.

        # Очистка временных NPC
        cleaned_up_npcs_count = 0
        if self._npc_manager:
            temp_npc_ids: List[str] = getattr(event, 'state_variables', {}).get('temp_npcs', []) # Safely get from event
            if temp_npc_ids:
                 print(f"WorldSimulationProcessor: Cleaning up {len(temp_npc_ids)} temporary NPCs for event {event.id} in guild {guild_id}.")
                 successfully_removed_npc_ids: List[str] = []
                 for npc_id in list(temp_npc_ids):
                      try:
                           # NpcManager.remove_npc должен принимать npc_id, guild_id и context
                           removed_id = await self._npc_manager.remove_npc(npc_id, guild_id, **cleanup_context) # Убедитесь в сигнатуре
                           if removed_id:
                                successfully_removed_npc_ids.append(removed_id)
                           # Удаляем успешно удаленный NPC из event.state_variables списка (если он там был) ПОСЛЕ успешного удаления через менеджер.
                           if 'temp_npcs' in getattr(event, 'state_variables', {}) and npc_id in event.state_variables['temp_npcs']:
                                event.state_variables['temp_npcs'].remove(npc_id)

                      except Exception as e:
                           print(f"WorldSimulationProcessor: Error removing temp NPC {npc_id} for event {event.id} in guild {guild_id}: {e}")
                           import traceback
                           print(traceback.format_exc())

                 cleaned_up_npcs_count = len(successfully_removed_npc_ids)
                 print(f"WorldSimulationProcessor: Finished NPC cleanup for event {event.id} in guild {guild_id}. {cleaned_up_npcs_count} NPCs removed.")
                 # Если список temp_npcs в state_variables стал пуст после чистки, удаляем сам ключ
                 if 'temp_npcs' in getattr(event, 'state_variables', {}) and not event.state_variables['temp_npcs']:
                      event.state_variables.pop('temp_npcs')
                      self._event_manager.mark_event_dirty(guild_id, event.id) # Помечаем событие dirty, если изменили state_variables


        # TODO: Implement cleanup for temporary items (if any) via ItemManager
        # ItemManager.remove_item должен принимать item_id, guild_id и context

        # TODO: Очистка активных Combat'ов, связанных с этим событием (нужен CombatManager)
        # CombatManager.get_combats_by_event_id может принимать event_id И guild_id.
        # CombatManager.end_combat должен принимать combat_id, guild_id и context.

        # TODO: Удаление статус-эффектов, специфичных для события? (StatusManager)
        # StatusManager.remove_status_effects_by_event_id должен принимать event_id, guild_id и context.

        # --- 2. Оповещение о завершении события ---
        if event.channel_id is not None:
            send_callback = self._send_callback_factory(event.channel_id)
            end_message_content: str = getattr(event, 'end_message_template', None)
            if not end_message_content:
                 end_message_content = f"Событие **{getattr(event, 'name', 'N/A')}** завершилось."

            try:
                 await send_callback(end_message_content)
                 print(f"WorldSimulationProcessor: Sent event end message for event {event.id} to channel {event.channel_id} in guild {guild_id}.")
            except Exception as e:
                 print(f"WorldSimulationProcessor: Error sending event end message for event {event.id} to channel {event.channel_id} in guild {guild_id}: {e}")
                 import traceback
                 print(traceback.format_exc())


        # --- 3. Помечаем событие как неактивное и удаляем из runtime кеша ---
        event.is_active = False
        # EventManager.remove_active_event должен принимать guild_id и event.id
        self._event_manager.remove_active_event(guild_id, event.id)


        print(f"WorldSimulationProcessor: Event {event.id} for guild {guild_id} marked inactive and removed from active cache.")

        # --- 4. Сохраняем финальное состояние ---
        if self._persistence_manager:
             try:
                 # PersistenceManager.save_game_state ожидает guild_ids: List[str] и context
                 save_kwargs = {'time_manager': self._time_manager} # TimeManager нужен для сохранения
                 save_kwargs.update(cleanup_context) # Добавляем остальной контекст
                 await self._persistence_manager.save_game_state(guild_ids=[guild_id], **save_kwargs) # Сохраняем только для этой гильдии
                 print(f"WorldSimulationProcessor: Final game state saved after ending event {event.id} for guild {guild_id}.")
             except Exception as e:
                 print(f"WorldSimulationProcessor: Error during final save after ending event {event.id} for guild {guild_id}: {e}")
                 import traceback
                 print(traceback.format_exc())
        else:
             print("WorldSimulationProcessor: Skipping final save after ending event (PersistenceManager not available).")


        print(f"WorldSimulationProcessor: Event {event_id} ending process completed for guild {guild_id}.")


    # --- Мировой Тик ---
    # ИСПРАВЛЕНИЕ: Добавляем **kwargs к сигнатуре
    # ИСПРАВЛЕНИЕ: Аннотируем game_time_delta как float
    async def process_world_tick(self, game_time_delta: float, **kwargs: Any) -> None:
        """
        Обрабатывает один "тик" игрового времени.
        Координирует вызовы tick-методов у других менеджеров и процессоров.
        """
        # print(f"WorldSimulationProcessor: Processing world tick with delta: {game_time_delta}") # Бывает очень шумно

        # --- Передаем все необходимые менеджеры/сервисы в kwargs для tick методов ---
        # Это нужно, если компонент X в своем process_tick нуждается в компоненте Y,
        # и Y не был инжектирован в X при его __init__.
        # Передаем ссылки на все компоненты, которые WorldSimulationProcessor сам имеет.
        # ИСПРАВЛЕНИЕ: Собираем все менеджеры и процессоры из self._ атрибутов для передачи в kwargs.
        # Приоритет отдается тем, что инжектированы (self._...).
        # Также включаем те, что пришли в kwargs этого метода process_world_tick (если GameManager передал их иначе).
        # Но лучший подход - чтобы GameManager передавал все менеджеры/процессоры в kwargs в initialize() WorldSimulationProcessor,
        # а затем WSP просто использовал self._атрибуты или передавал их в kwargs.
        # Поскольку GameManager собирает словарь в _world_tick_loop и передает его как **kwargs: Any
        # managers_and_processors_for_tick = {k: v for k, v in self.__dict__.items() if isinstance(v, (EventManager, CharacterManager, ...))}
        #
        # Вместо сбора всех self._ атрибутов, просто используем **kwargs, которые УЖЕ содержат все менеджеры
        # из GameManager._world_tick_loop. Это более чистый подход.
        # Проверим, что GameManager передает все нужные зависимости в kwargs.
        # managers_and_processors_for_tick = kwargs # Все менеджеры и т.д. из GameManager.tick_context_kwargs


        # WorldSimulationProcessor должен работать per-guild.
        # GameManager передает tick_context_kwargs, который содержит ссылку на PersistenceManager.
        # PersistenceManager должен знать, для каких guild_ids нужно симулировать тик.
        # Или WorldSimulationProcessor запрашивает список активных гильдий у PersistenceManager?
        # PersistenceManager.get_active_guild_ids()?
        #
        # Или же WorldSimulationProcessor.process_world_tick вызывается GameManager для каждой гильдии?
        # Нет, судя по GameManager._world_tick_loop, process_world_tick вызывается ОДИН раз на тик для ВСЕХ гильдий.
        # Значит, WorldSimulationProcessor должен получить список активных гильдий и итерировать по ним.

        active_guild_ids: List[str] = []
        persistence_manager = kwargs.get('persistence_manager') # Type: Optional[PersistenceManager]
        if persistence_manager and hasattr(persistence_manager, 'get_loaded_guild_ids'):
            # PersistenceManager знает, какие гильдии он загрузил.
            active_guild_ids = persistence_manager.get_loaded_guild_ids() # Assumes this method exists


        if not active_guild_ids:
             # print("WorldSimulationProcessor: No active guilds to tick.") # Too noisy
             return # Нечего тикать


        # Итерируем по каждой активной гильдии и обрабатываем ее состояние
        for guild_id in active_guild_ids:
             # print(f"WorldSimulationProcessor: Ticking for guild {guild_id}...") # Debug print per guild

             # TODO: Передавать контекст, специфичный для гильдии, в tick методы менеджеров
             # kwargs уже содержат все менеджеры. Нужно добавить guild_id.
             # Можно создать новый словарь контекста для передачи в tick методы менеджеров для этой гильдии.
             guild_tick_context: Dict[str, Any] = {'guild_id': guild_id}
             guild_tick_context.update(kwargs) # Добавляем все менеджеры и т.д. из общего kwargs


             # 1. Обновление времени игры (TimeManager)
             if self._time_manager:
                 try:
                      # TimeManager.process_tick должен принимать guild_id и context
                      await self._time_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                      # print(f"WorldSimulationProcessor: TimeManager tick processed for guild {guild_id}.")
                 except Exception as e: print(f"WorldSimulationProcessor: Error during TimeManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()


             # 2. Обработка статусов (StatusManager)
             if self._status_manager:
                  try:
                       # StatusManager.process_tick должен принимать guild_id и context
                       await self._status_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                       # print(f"WorldSimulationProcessor: StatusManager tick processed for guild {guild_id}.")
                  except Exception as e: print(f"WorldSimulationProcessor: Error during StatusManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()


             # 3. Обработка очередей крафтинга (CraftingManager)
             if self._crafting_manager:
                  try:
                       # CraftingManager.process_tick должен принимать guild_id и context
                       await self._crafting_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                       # print(f"WorldSimulationProcessor: CraftingManager tick processed for guild {guild_id}.")
                  except Exception as e: print(f"WorldSimulationProcessor: Error during CraftingManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()


             # 4. Обработка активных боев (CombatManager)
             if self._combat_manager:
                 try:
                      # CombatManager должен сам найти свои активные бои ДЛЯ ЭТОЙ ГИЛЬДИИ и иметь метод end_combat
                      # Если CombatManager.process_tick_for_guild существует
                      if hasattr(self._combat_manager, 'process_tick_for_guild'):
                           # process_tick_for_guild должен обрабатывать все бои одной гильдии
                           await self._combat_manager.process_tick_for_guild(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                      # Иначе, если CombatManager имеет общую process_tick, он должен сам итерировать по гильдиям
                      # Это зависит от реализации CombatManager.
                      # Пока предполагаем, что CombatManager либо сам работает per-guild, либо WSP вызывает его метод per-guild.
                      # Если CombatManager.process_combat_round(combat_id, ...) вызвается WSP, то WSP должен получить список активных боев per-guild.
                      elif hasattr(self._combat_manager, 'get_active_combats_by_guild'): # Метод для получения активных боев per-guild
                          active_combats_in_guild = self._combat_manager.get_active_combats_by_guild(guild_id)
                          combats_to_end_ids: List[str] = []
                          if active_combats_in_guild:
                               for combat in list(active_combats_in_guild):
                                    if not combat.is_active: continue # Проверка на всякий случай
                                    # process_combat_round должен быть методом CombatManager, принимать combat_id, guild_id, game_time_delta, context
                                    combat_finished_signal = await self._combat_manager.process_combat_round(combat_id=combat.id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                                    if combat_finished_signal: combats_to_end_ids.append(combat.id)

                           # Обрабатываем завершившиеся бои для этой гильдии
                          for combat_id in combats_to_end_ids:
                                # end_combat должен принимать combat_id, guild_id, context
                                await self._combat_manager.end_combat(combat_id, guild_id=guild_id, **guild_tick_context)

                      else:
                           print(f"WorldSimulationProcessor: Warning: CombatManager or its required methods not available for tick processing for guild {guild_id}.")


                 except Exception as e: print(f"WorldSimulationProcessor: Error during CombatManager tick processing for guild {guild_id}: {e}"); traceback.print_exc()


             # 5. Обработка индивидуальных действий персонажей (CharacterActionProcessor)
             if self._character_manager and self._character_action_processor:
                  try:
                       # CharacterManager должен иметь метод get_entities_with_active_action(guild_id)
                       if hasattr(self._character_manager, 'get_entities_with_active_action') and hasattr(self._character_action_processor, 'process_tick'):
                            # Получаем активных персонажей ДЛЯ ЭТОЙ ГИЛЬДИИ
                            characters_with_active_action = self._character_manager.get_entities_with_active_action(guild_id) # Передаем guild_id
                            if characters_with_active_action:
                                # print(f"WorldSimulationProcessor: Ticking {len(characters_with_active_action)} active Characters for guild {guild_id}...") # Debug print
                                for char_id in list(characters_with_active_action):
                                     # CharacterActionProcessor.process_tick должен принимать entity_id, guild_id, game_time_delta, context
                                     await self._character_action_processor.process_tick(entity_id=char_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)

                       # else:
                            # print(f"WorldSimulationProcessor: Info: No active characters to tick for guild {guild_id}.")

                  except Exception as e: print(f"WorldSimulationProcessor: Error during CharacterActionProcessor process_tick for guild {guild_id}: {e}"); traceback.print_exc()


             # 6. Обработка индивидуальных действий NPC (NpcManager / NpcActionProcessor)
             if self._npc_manager:
                  # TODO: Если создан NpcActionProcessor, используем его.
                  # if self._npc_action_processor and hasattr(self._npc_action_processor, 'process_tick'):
                  #      try:
                  #           if hasattr(self._npc_manager, 'get_entities_with_active_action'):
                  #                npcs_with_active_action = self._npc_manager.get_entities_with_active_action(guild_id) # Передаем guild_id
                  #                if npcs_with_active_action:
                  #                     # print(f"WorldSimulationProcessor: Ticking {len(npcs_with_active_action)} active NPCs via NpcActionProcessor for guild {guild_id}...")
                  #                     for npc_id in list(npcs_with_active_action):
                  #                          await self._npc_action_processor.process_tick(entity_id=npc_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  #      except Exception as e: ...
                  # else: # Если NpcActionProcessor не создан, и NpcManager сам обрабатывает тик
                  #      try:
                  #           if hasattr(self._npc_manager, 'get_entities_with_active_action') and hasattr(self._npc_manager, 'process_tick'):
                  #                npcs_with_active_action = self._npc_manager.get_entities_with_active_action(guild_id) # Передаем guild_id
                  #                if npcs_with_active_action:
                  #                     # print(f"WorldSimulationProcessor: Ticking {len(npcs_with_active_action)} active NPCs via NpcManager for guild {guild_id}...")
                  #                     for npc_id in list(npcs_with_active_action):
                  #                          await self._npc_manager.process_tick(entity_id=npc_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  #      except Exception as e: ...
                  pass # Placeholder for NPC tick logic

             # 7. Обработка групповых действий партий (PartyActionProcessor)
             if self._party_manager and self._party_action_processor:
                  try:
                       # PartyManager должен иметь метод get_parties_with_active_action(guild_id)
                       if hasattr(self._party_manager, 'get_parties_with_active_action') and hasattr(self._party_action_processor, 'process_tick'):
                            # Получаем активные партии ДЛЯ ЭТОЙ ГИЛЬДИИ
                            parties_with_active_action = self._party_manager.get_parties_with_active_action(guild_id) # Передаем guild_id
                            if parties_with_active_action:
                                 # print(f"WorldSimulationProcessor: Ticking {len(parties_with_active_action)} active Parties for guild {guild_id}...") # Debug print
                                 for party_id in list(parties_with_active_action):
                                      # PartyActionProcessor.process_tick должен принимать party_id, guild_id, game_time_delta, context
                                      await self._party_action_processor.process_tick(party_id=party_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)

                       # else:
                            # print(f"WorldSimulationProcessor: Info: No active parties to tick for guild {guild_id}.")

                  except Exception as e: print(f"WorldSimulationProcessor: Error during PartyActionProcessor process_tick for guild {guild_id}: {e}"); traceback.print_exc()


             # 8. Обработка других менеджеров, которым нужен тик (ItemManager, LocationManager, EconomyManager)
             # ItemManager.process_tick должен принимать guild_id и context
             if self._item_manager and hasattr(self._item_manager, 'process_tick'):
                  try: await self._item_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during ItemManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             # LocationManager.process_tick должен принимать guild_id и context
             if self._location_manager and hasattr(self._location_manager, 'process_tick'):
                  try: await self._location_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during LocationManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             # EconomyManager.process_tick должен принимать guild_id и context
             if self._economy_manager and hasattr(self._economy_manager, 'process_tick'):
                  try: await self._economy_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during EconomyManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()


             # 9. Проверка активных событий на автоматические переходы стадий (по времени, условиям)
             if self._event_manager and self._event_stage_processor:
                  # EventManager должен уметь получить активные события ДЛЯ ЭТОЙ ГИЛЬДИИ
                  if hasattr(self._event_manager, 'get_active_events_by_guild') and hasattr(self, '_check_event_for_auto_transition') and hasattr(self._event_stage_processor, 'advance_stage'):
                       active_events: List[Event] = self._event_manager.get_active_events_by_guild(guild_id) # Передаем guild_id
                       events_to_auto_advance_info: List[Tuple[Event, str]] = []

                       for event in list(active_events):
                            if not event.is_active or event.current_stage_id == 'event_end': continue
                            # _check_event_for_auto_transition использует self._атрибуты (TimeManager, RuleEngine, NpcManager),
                            # которые инжектированы в WSP. Оно должно работать с пер-гильдийными данными.
                            # Возможно, _check_event_for_auto_transition должен принимать guild_id?
                            # Нет, он принимает Event объект, который уже должен иметь guild_id.
                            next_stage_id_auto = self._check_event_for_auto_transition(event) # Передаем Event объект
                            if next_stage_id_auto:
                                 print(f"WorldSimulationProcessor: Event {event.id} ('{getattr(event, 'name', 'N/A')}') for guild {guild_id}: Auto-transition condition met from stage '{event.current_stage_id}' to stage '{next_stage_id_auto}'. Scheduling transition.")
                                 events_to_auto_advance_info.append((event, next_stage_id_auto))

                       # --- Обработка Обнаруженных Авто-Переходов ---
                       for event_to_advance, target_stage_id_auto in events_to_auto_advance_info:
                            try:
                                 if event_to_advance.channel_id is None:
                                      print(f"WorldSimulationProcessor: Warning: Cannot auto-advance event {event_to_advance.id} for guild {guild_id}. Event has no channel_id for notifications.")
                                      continue

                                 event_channel_callback = self._send_callback_factory(event_to_advance.channel_id)

                                 # EventStageProcessor.advance_stage ожидает context, guild_id уже в контексте
                                 # Передаем все зависимости из guild_tick_context
                                 await self._event_stage_processor.advance_stage(
                                     event=event_to_advance, target_stage_id=target_stage_id_auto,
                                     send_message_callback=event_channel_callback,
                                     **guild_tick_context, # Передаем все зависимости, включая guild_id
                                     transition_context={"trigger": "auto_advance", "from_stage_id": event_to_advance.current_stage_id, "to_stage_id": target_stage_id_auto}
                                 )
                                 print(f"WorldSimulationProcessor: Auto-transition to '{target_stage_id_auto}' completed for event {event_to_advance.id} in guild {guild_id}.")
                            except Exception as e: print(f"WorldSimulationProcessor: Error during auto-transition execution for event {event_to_advance.id} to stage {target_stage_id_auto} in guild {guild_id}: {e}"); traceback.print_exc()

                  else:
                       print(f"WorldSimulationProcessor: Warning: EventManager or EventStageProcessor or their required methods not available for auto-transition check for guild {guild_id}.")


             # 10. Очистка завершившихся событий ('event_end' stage)
             if self._event_manager and hasattr(self._event_manager, 'get_active_events_by_guild'): # ИСПОЛЬЗУЕМ get_active_events_by_guild
                  events_already_ending_ids: List[str] = [ event.id for event in list(self._event_manager.get_active_events_by_guild(guild_id)) if event.current_stage_id == 'event_end' ]
                  for event_id in events_already_ending_ids:
                       # end_event должен принимать guild_id и event_id
                       await self.end_event(guild_id, event_id)


             # 11. Опционально: Сохранение состояния игры для этой гильдии (периодически)
             if self._persistence_manager:
                  # TODO: Добавить логику определения, нужно ли сейчас сохранять (например, по счетчику тиков) ДЛЯ ЭТОЙ ГИЛЬДИИ
                  should_auto_save_logic_here = False # Placeholder
                  # Пример получения интервала сохранения из настроек для этой гильдии
                  # guild_settings = kwargs.get('settings', {}).get('guilds', {}).get(guild_id, {})
                  # auto_save_interval = guild_settings.get('auto_save_interval_seconds', kwargs.get('settings', {}).get('auto_save_interval_seconds', 300))
                  # Requires tracking last_save_time per guild. PersistenceManager might handle this internally.
                  # If WSP handles save logic, it needs a self._last_save_time_per_guild: Dict[str, float]

                  if should_auto_save_logic_here:
                       try:
                            # PersistenceManager.save_game_state ожидает guild_ids: List[str]
                            await self._persistence_manager.save_game_state(guild_ids=[guild_id], **guild_tick_context) # Сохраняем только для этой гильдии, передаем контекст
                            # TODO: Обновить self._last_save_time_per_guild[guild_id] = current_game_time
                       except Exception as e: print(f"WorldSimulationProcessor: Error during auto-save for guild {guild_id}: {e}"); traceback.print_exc()


        # print("DEBUG: WorldSimulationProcessor tick processing finished for all guilds.") # Debug


    # --- Вспомогательные методы ---

    async def generate_dynamic_event_narrative(self, guild_id: str, event_concept: str, related_entities: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Uses AI to generate a narrative for a dynamic world event or a general
        atmospheric description of world changes.

        Args:
            guild_id: The ID of the guild.
            event_concept: A string describing the event concept or desired narrative.
            related_entities: Optional list of entity IDs (characters, locations, factions) relevant to the event.

        Returns:
            A dictionary containing the structured, multilingual narrative content,
            or None if generation fails.
        """
        if not self._multilingual_prompt_generator:
            print("WorldSimulationProcessor ERROR: MultilingualPromptGenerator is not available.")
            return None
        if not self._openai_service: # Should have been caught by generator check too
            print("WorldSimulationProcessor ERROR: OpenAIService is not available.")
            return None
        if not self._settings:
            print("WorldSimulationProcessor ERROR: Settings are not available.")
            return None

        print(f"WorldSimulationProcessor: Generating AI narrative for event concept '{event_concept}' in guild {guild_id}.")

        context_data = self._multilingual_prompt_generator.context_collector.get_full_context(
            guild_id=guild_id,
            # Potentially pass related_entities to focus the context if get_full_context supports it
        )

        # Create a specific task prompt for this generation type
        specific_task_prompt = f"""
        Generate a rich, atmospheric narrative or dynamic event description for the game world.
        Event Concept/Narrative Idea: {event_concept}
        Potentially involved entities (use context for them if provided): {related_entities if related_entities else "General world atmosphere"}

        The output should include:
        - title_i18n (multilingual title for this event/narrative snippet)
        - description_i18n (multilingual, detailed narrative text. This could describe changes in the world, a developing situation, or an unfolding event.)
        - affected_locations_i18n (optional, list of location names/IDs with multilingual notes on how they are affected)
        - involved_npcs_i18n (optional, list of NPC names/IDs with multilingual notes on their involvement)
        - potential_player_hooks_i18n (optional, multilingual ideas on how players might get involved or notice this)

        Ensure all textual fields are in the specified multilingual JSON format ({{"en": "...", "ru": "..."}}).
        Incorporate elements from the lore and current world state context.
        """

        prompt_messages = self._multilingual_prompt_generator._build_full_prompt_for_openai(
            specific_task_prompt=specific_task_prompt,
            context_data=context_data
        )

        system_prompt = prompt_messages["system"]
        user_prompt = prompt_messages["user"]

        ai_settings = self._settings.get("world_event_ai_settings", {})
        max_tokens = ai_settings.get("max_tokens", 1500)
        temperature = ai_settings.get("temperature", 0.7)

        generated_data = await self._openai_service.generate_structured_multilingual_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

        if generated_data and "error" not in generated_data:
            print(f"WorldSimulationProcessor: Successfully generated AI narrative for '{event_concept}'.")
            return generated_data
        else:
            error_detail = generated_data.get("error") if generated_data else "Unknown error"
            raw_text = generated_data.get("raw_text", "") if generated_data else ""
            print(f"WorldSimulationProcessor ERROR: Failed to generate AI narrative for '{event_concept}'. Error: {error_detail}")
            if raw_text:
                print(f"WorldSimulationProcessor: Raw response from AI was: {raw_text[:500]}...")
            return None

    def _check_event_for_auto_transition(self, event: Event) -> Optional[str]:
        # ... (логика _check_event_for_auto_transition остается прежней, она использует self._атрибуты и Event объект) ...
        """
        Проверяет текущую стадию события на условия автоматического перехода.
        Использует данные стадии события и менеджеры (TimeManager, RuleEngine, NpcManager, PartyManager) для оценки условий.
        Возвращает target stage ID или None.
        """
        # print(f"WSP: Checking event {event.id} stage '{event.current_stage_id}' for auto-transition conditions...") # Debug print

        current_stage_data = getattr(event, 'stages_data', {}).get(event.current_stage_id) # Safely get stages_data
        if not current_stage_data:
             print(f"WorldSimulationProcessor: Warning: _check_event_for_auto_transition: No stage data found for current stage {event.current_stage_id} in event {event.id}.")
             return None # Cannot check without stage data

        # Создаем временный объект EventStage для удобного доступа к данным стадии
        # Используем EventStage.from_dict, если у вас есть такая модель
        # Если нет, работайте напрямую с current_stage_data: Dict[str, Any]
        # Убедитесь, что EventStage.from_dict корректно обрабатывает словарь
        try:
             current_stage_obj: EventStage = EventStage.from_dict(current_stage_data)
        except Exception as e:
             print(f"WorldSimulationProcessor: Error creating EventStage from dict for event {event.id}, stage {event.current_stage_id}: {e}")
             import traceback
             print(traceback.format_exc())
             # Продолжаем с raw dict data если object creation failed
             current_stage_obj = current_stage_data # Use the raw dictionary as fallback


        # Проверка правила 'auto_transitions' в данных стадии (ожидаем список словарей)
        auto_transitions_rules: Optional[List[Dict[str, Any]]] = getattr(current_stage_obj, 'auto_transitions', []) if isinstance(current_stage_obj, EventStage) else current_stage_obj.get('auto_transitions', []) # Adapt for object or dict

        if isinstance(auto_transitions_rules, list):
            for rule in auto_transitions_rules:
                 if not isinstance(rule, dict): continue # Skip if rule entry is not a dict

                 rule_type = rule.get('type') # Тип правила ('time_elapsed', 'state_variable_threshold' и т.д.)

                 # --- Правило: time_elapsed (время истекло) ---
                 if rule_type == 'time_elapsed' and self._time_manager is not None:
                      timer_var = rule.get('state_var')
                      threshold = rule.get('threshold')
                      target_stage_id = rule.get('target_stage')

                      if isinstance(timer_var, str) and timer_var and \
                         threshold is not None and isinstance(threshold, (int, float)) and \
                         isinstance(target_stage_id, str) and target_stage_id:

                           # Получаем текущее значение таймера из event.state_variables. TimeManager обновляет это значение в process_tick.
                           # Таймеры привязаны к сущностям или к самому событию (event).
                           # WorldSimulationProcessor передает event в TimeManager.process_tick,
                           # и TimeManager должен обновлять таймеры в event.state_variables.
                           # Получаем таймер из state_variables события.
                           current_timer_value: Any = getattr(event, 'state_variables', {}).get(timer_var, 0.0) # Safely get from event object

                           if isinstance(current_timer_value, (int, float)) and current_timer_value >= threshold:
                                # Условие выполнено. Возвращаем целевую стадию для перехода.
                                # print(f"WSP: Event {event.id}, stage '{event.current_stage_id}' met 'time_elapsed' condition for timer '{timer_var}' (Current: {current_timer_value}, Threshold: {threshold}). Target stage: '{target_stage_id}'.")
                                return target_stage_id # Возвращаем ID стадии

                 # --- Правило: state_variable_threshold (порог значения переменной состояния) ---
                 elif rule_type == 'state_variable_threshold':
                      variable_name = rule.get('variable')
                      operator = rule.get('operator')
                      value_threshold = rule.get('value')
                      target_stage_id = rule.get('target_stage')

                      if isinstance(variable_name, str) and variable_name and \
                         isinstance(operator, str) and operator in ['<', '<=', '==', '>', '>=', '!='] and \
                         value_threshold is not None and \
                         isinstance(target_stage_id, str) and target_stage_id:

                           # Получаем текущее значение переменной из event.state_variables
                           current_var_value: Any = getattr(event, 'state_variables', {}).get(variable_name) # Safely get from event object


                           if current_var_value is not None:
                                condition_met = False
                                try:
                                    if operator in ['<', '<=', '>', '>='] and (not isinstance(current_var_value, (int, float)) or not isinstance(value_threshold, (int, float))):
                                         pass
                                    else:
                                         if operator == "<":   condition_met = current_var_value < value_threshold
                                         elif operator == "<=": condition_met = current_var_value <= value_threshold
                                         elif operator == "==": condition_met = current_var_value == value_threshold
                                         elif operator == ">":   condition_met = current_var_value > value_threshold
                                         elif operator == ">=": condition_met = current_var_value >= value_threshold
                                         elif operator == "!=": condition_met = current_var_value != value_threshold

                                    if condition_met:
                                         return target_stage_id

                                except TypeError as e:
                                     print(f"WorldSimulationProcessor: Warning: _check_event_for_auto_transition: TypeError comparing variable '{variable_name}' ({type(current_var_value).__name__}) with threshold ({type(value_threshold).__name__}) for event {event.id}: {e}")
                                except Exception as e:
                                     print(f"WorldSimulationProcessor: Error during 'state_variable_threshold' check for variable '{variable_name}' for event {event.id}: {e}")
                                     import traceback
                                     print(traceback.format_exc())


                 # --- TODO: Добавить логику для других типов авто-переходов ---
                 # - "all_involved_npcs_defeated":
                 #   Требует NpcManager (self._npc_manager), RuleEngine (self._rule_engine), и Event (для npc_ids).
                 #   Проверка, что self._npc_manager and self._rule_engine доступны.
                 #   Использование self._get_managers_for_rule_engine_context() для контекста RuleEngine.
                 #   RuleEngine.are_npcs_defeated(npc_ids, context={'npc_manager': self._npc_manager, ...})
                 #   NpcManager.get_npc(npc_id) должен быть доступен для RuleEngine через контекст.

                 # - "all_party_members_in_location": Требует PartyManager (self._party_manager), CharacterManager (self._character_manager), Event (для party_id/player_ids).
                 #   Используйте self._party_manager.get_party_by_event_id(event.id) или получите player_ids из event.state_variables.
                 #   Проверьте локацию каждого участника через self._character_manager.get_character(player_id).location_id.


                 # - "player_input_idle_timeout": Требует TimeManager (self._time_manager), Event (для last_player_action_game_time).
                 #   Проверка, что self._time_manager доступен. Получение current_game_time и last_player_action_game_time из event.state_variables.


        # Если ни одно условие автоматического перехода не выполнилось после проверки всех правил
        return None # Необходимости в авто-переходе нет

    # Вспомогательный метод для получения словаря менеджеров для передачи в контекст RuleEngine
    def _get_managers_for_rule_engine_context(self) -> Dict[str, Any]:
         """
         Возвращает словарь менеджеров и процессоров, которые RuleEngine может использовать в своем контексте.
         Это включает почти все зависимости WorldSimulationProcessor.
         """
         return {
             # Передаем все инжектированные менеджеры и процессоры из self._ атрибутов
             'character_manager': self._character_manager,
             'event_manager': self._event_manager,
             'location_manager': self._location_manager,
             'rule_engine': self._rule_engine,
             'openai_service': self._openai_service,
             'event_stage_processor': self._event_stage_processor,
             'event_action_processor': self._event_action_processor,
             'persistence_manager': self._persistence_manager,
             'send_callback_factory': self._send_callback_factory,
             'character_action_processor': self._character_action_processor,
             'party_action_processor': self._party_action_processor,
             # TODO: Добавьте NpcActionProcessor
             # 'npc_action_processor': self._npc_action_processor,
             'npc_manager': self._npc_manager,
             'combat_manager': self._combat_manager,
             'item_manager': self._item_manager,
             'time_manager': self._time_manager,
             'status_manager': self._status_manager,
             'crafting_manager': self._crafting_manager,
             'economy_manager': self._economy_manager,
             'party_manager': self._party_manager,
             # Добавьте другие менеджеры/сервисы
             # Например, если CharacterViewService нужен RuleEngine, его тоже можно добавить сюда?
             # 'character_view_service': self._character_view_service # CharacterViewService не является зависимостью WSP напрямую
         }


    # TODO: Возможно, добавить метод для запуска периодического тика извне
    # def start_tick_loop(self, tick_interval_seconds: float): ...

# Конец класса WorldSimulationProcessor