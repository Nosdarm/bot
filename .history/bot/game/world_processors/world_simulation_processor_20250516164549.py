# bot/game/world_simulation_processor.py

# --- Импорты ---
import asyncio
import traceback
from typing import Dict, Optional, Any, List, Tuple, Callable, Awaitable, Set # Import needed types


# --- Импорт Менеджеров ---
# Убедитесь, что все менеджеры, чьи process_tick вызываются (или которые передаются в kwargs другим process_tick), импортированы.
# Используйте строковые аннотации, если есть циклы импорта.
from bot.game.managers.event_manager import EventManager
from bot.game.managers.character_manager import CharacterManager # Нужен для получения активных персонажей
from bot.game.managers.location_manager import LocationManager # Может иметь process_tick для окружения, нужен в kwargs
from bot.game.rules.rule_engine import RuleEngine # Нужен в kwargs
from bot.game.managers.npc_manager import NpcManager # Нужен для получения активных NPC, в kwargs. Может иметь свой process_tick или делегировать.
from bot.game.managers.combat_manager import CombatManager # Нужен для активных боев, process_tick, в kwargs
from bot.game.managers.item_manager import ItemManager # Может иметь process_tick, в kwargs
from bot.game.managers.time_manager import TimeManager # Имеет process_tick, нужен в kwargs
from bot.game.managers.status_manager import StatusManager # Имеет process_tick, нужен в kwargs
from bot.game.managers.crafting_manager import CraftingManager # Если есть, имеет process_tick, нужен в kwargs
from bot.game.managers.economy_manager import EconomyManager # Если есть, имеет process_tick, нужен в kwargs
from bot.game.managers.party_manager import PartyManager # Нужен для получения активных партий, в kwargs

# --- Импорт Сервисов ---
from bot.services.openai_service import OpenAIService # Нужен в kwargs

# --- Импорт Процессоров ---
from bot.game.event_processors.event_stage_processor import EventStageProcessor # Нужен для авто-переходов, в kwargs
from bot.game.event_processors.event_action_processor import EventActionProcessor # Нужен в kwargs

# ИСПРАВЛЕНИЕ: Импортируем Processors Действий
from bot.game.character_processors.character_action_processor import CharacterActionProcessor # Координирует действия персонажей
from bot.game.party_processors.party_action_processor import PartyActionProcessor # Координирует действия партий
# TODO: Импортируем NpcActionProcessor, если он будет создан
from bot.game.npc_processors.npc_action_processor import NpcActionProcessor # Координирует действия NPC


# --- Импорт PersistenceManager ---
from bot.game.managers.persistence_manager import PersistenceManager

# --- Импорт Моделей (для аннотаций) ---
# Не обязательно импортировать все модели, только те, которые используются напрямую в сигнатурах методов WSP.
from bot.game.models.event import Event, EventStage
from bot.game.models.character import Character # Нужен для get_entities_with_active_action в CharacterManager, но сам WSP не работает с объектами напрямую здесь.
from bot.game.models.npc import NPC
from bot.game.models.item import Item
from bot.game.models.combat import Combat
from bot.game.models.party import Party # Нужен для get_parties_with_active_action в PartyManager


# Определение Type Alias для Send Callback (функция, отправляющая сообщение в конкретный канал)
# SendToChannelCallback определен в GameManager, его нужно импортировать или определить здесь
# Определим здесь, чтобы избежать цикла WorldSimulationProcessor <-> GameManager
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
                 character_manager: CharacterManager, # WSP получает от него список активных ID персонажей
                 location_manager: LocationManager,
                 rule_engine: RuleEngine,
                 openai_service: OpenAIService, # Обязателен, т.к. передается в tick методы.
                 event_stage_processor: EventStageProcessor,
                 event_action_processor: EventActionProcessor, # Хотя напрямую не вызывается в tick, нужен в kwargs
                 persistence_manager: PersistenceManager,
                 settings: Dict[str, Any],
                 send_callback_factory: SendCallbackFactory, # Фабрика для callback'ов

                 # ИСПРАВЛЕНИЕ: Добавляем Processors Действий как ОБЯЗАТЕЛЬНЫЕ зависимости
                 # WSP *обязательно* нужен процессор для тиков персонажей и партий.
                 character_action_processor: CharacterActionProcessor,
                 party_action_processor: PartyActionProcessor,
                 # TODO: Добавьте NpcActionProcessor, если он будет создан, как ОБЯЗАТЕЛЬНЫЙ
                 # npc_action_processor: NpcActionProcessor,

                 # TODO: Добавьте другие ОБЯЗАТЕЛЬНЫЕ зависимости сюда, если они есть

                 # --- ОПЦИОНАЛЬНЫЕ зависимости (СО значениями по умолчанию) ---
                 # Эти менеджеры могут иметь process_tick, или нужны в kwargs другим tick методам.
                 npc_manager: Optional[NpcManager] = None,
                 combat_manager: Optional[CombatManager] = None,
                 item_manager: Optional[ItemManager] = None,
                 time_manager: Optional[TimeManager] = None,
                 status_manager: Optional[StatusManager] = None,
                 crafting_manager: Optional[CraftingManager] = None,
                 economy_manager: Optional[EconomyManager] = None,
                 # PartyManager уже не нужен здесь как отдельный tick-компонент, т.к. WSP вызывает его ActionProcessor.
                 # Но PartyManager нужен в kwargs для PartyActionProcessor.process_tick, поэтому оставляем его в параметрах.
                 # PartyManager также нужен PartyActionProcessor в __init__.
                 # party_manager: Optional[PartyManager] = None, # PartyManager уже в обязательных зависимостях

                 # TODO: Добавьте другие ОПЦИОНАЛЬНЫЕ менеджеры/сервисы сюда
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
        self._npc_manager = npc_manager # NpcManager нужен для получения активных NPC, и передается в kwargs
        self._combat_manager = combat_manager
        self._item_manager = item_manager
        self._time_manager = time_manager
        self._status_manager = status_manager
        self._crafting_manager = crafting_manager
        self._economy_manager = economy_manager
        # self._party_manager = party_manager # PartyManager уже обязателен

        # TODO: Сохраните другие опциональные менеджеры/сервисы


        self._command_prefix = settings.get('discord_command_prefix', '/')

        print("WorldSimulationProcessor initialized.")


    # --- Методы Жизненного Цикла Событий (start/end event - остаются прежними) ---

    async def start_new_event(self,
                              event_template_id: str,
                              location_id: str,
                              players_discord_ids: List[int],
                              channel_id: int
                             ) -> Optional[str]:
        # ... (логика start_new_event остается прежней, но убедитесь, что она использует self._атрибуты) ...
        """
        Оркестрирует запуск нового события из шаблона.
        """
        print(f"WorldSimulationProcessor initiating start of new event from template '{event_template_id}' at location {location_id} in channel {channel_id}.")
        status_callback = self._send_callback_factory(channel_id)

        # --- 1. Валидация входных данных ---
        event_template_data = self._event_manager.get_event_template(event_template_id)
        if not event_template_data:
             print(f"WorldSimulationProcessor: Error starting event: Event template '{event_template_id}' not found.")
             await status_callback(f"❌ Ошибка: Шаблон события '{event_template_id}' не найден.")
             return None

        location_data = self._location_manager.get_location_static(location_id) # Используем get_location_static
        if not location_data:
             print(f"WorldSimulationProcessor: Error starting event: Location '{location_id}' not found.")
             await status_callback(f"❌ Ошибка: Локация '{location_id}' не найдена.")
             return None

        # Определяем финальный канал события: если в данных локации указан канал, используем его, иначе канал, из которого пришла команда
        event_channel_id_final = location_data.get('channel_id') # Предполагаем, что location_data может содержать 'channel_id'
        if event_channel_id_final is None:
             event_channel_id_final = channel_id # Если в локации не указан, используем канал команды
             print(f"WorldSimulationProcessor: No specific channel_id found for location {location_id}. Using command channel {channel_id} for event.")
             # Валидация, что канал команды (channel_id) передан и является числом
             if not isinstance(event_channel_id_final, int):
                  print(f"WorldSimulationProcessor: Error starting event: Command channel ID is not an integer ({channel_id}). Cannot determine event channel.")
                  await self._send_callback_factory(channel_id)(f"❌ Ошибка: Не удалось определить Discord канал для события.") # Отправляем в канал, откуда пришла команда
                  return None

        player_char_ids: List[str] = []
        if players_discord_ids:
             for discord_id in players_discord_ids:
                  # CharacterManager имеет метод get_character_by_discord_id
                  char = self._character_manager.get_character_by_discord_id(discord_id)
                  if char:
                       player_char_ids.append(char.id)
                  else:
                       print(f"WorldSimulationProcessor: Warning: Character not found for Discord user ID: {discord_id}. Cannot add to event.")


        # TODO: Добавить логику автоматического включения игроков, находящихся в указанной локации, если шаблон позволяет/требует.


        # --- 2. Создание объекта События ---
        try:
            # Передаем менеджеры, которые EventManager может использовать при создании события из шаблона
            # (напр., для спауна NPC/предметов, указанных в шаблоне)
            # EventManager.create_event_from_template должен принимать эти зависимости в kwargs.
            managers_for_event_creation = {
                'rule_engine': self._rule_engine, 'npc_manager': self._npc_manager,
                'item_manager': self._item_manager, 'location_manager': self._location_manager # LocManager может быть нужен для данных локации
                # TODO: Добавьте другие менеджеры
            }
            new_event: Optional[Event] = await self._event_manager.create_event_from_template(
                template_id=event_template_id, location_id=location_id, initial_player_ids=player_char_ids,
                channel_id=event_channel_id_final,
                # Передаем нужные менеджеры в kwargs для create_event_from_template
                **managers_for_event_creation
            )

            if new_event is None:
                 print(f"WorldSimulationProcessor: Error: EventManager failed to create event object from template '{event_template_id}'.")
                 # Используем callback для канала, откуда пришла команда, если канал события еще не определен корректно.
                 await self._send_callback_factory(channel_id)(f"❌ Ошибка при создании события из шаблона '{event_template_id}'. EventManager вернул None.")
                 return None

            print(f"WorldSimulationProcessor: Event object {new_event.id} ('{new_event.name}') created for location {location_id} in channel {new_event.channel_id}. Initial stage: {new_event.current_stage_id}")

        except Exception as e:
             print(f"WorldSimulationProcessor: Exception caught while creating event object from template {event_template_id}: {e}")
             import traceback
             print(traceback.format_exc())
             # Используем callback для канала, откуда пришла команда
             await self._send_callback_factory(channel_id)(f"❌ Критическая ошибка при создании события из шаблона '{event_template_id}': {e}. Смотрите логи бота.")
             return None


        # --- 3. Помечаем событие как активное и добавляем в runtime кеш ---
        new_event.is_active = True
        self._event_manager.add_active_event(new_event) # EventManager добавляет в свой активный кеш


        # --- 4. Запускаем обработку ПЕРВОЙ стадии события ---
        print(f"WorldSimulationProcessor: Calling EventStageProcessor to process the initial stage '{new_event.current_stage_id}' for event {new_event.id}.")

        try:
            # Проверяем, что у созданного события есть channel_id, прежде чем получить callback
            if new_event.channel_id is None:
                 print(f"WorldSimulationProcessor: Error: Newly created event {new_event.id} has no channel_id before processing initial stage.")
                 await self._send_callback_factory(channel_id)(f"❌ Ошибка: Созданное событие не привязано к Discord каналу. Невозможно обработать начальную стадию.") # Сообщаем в канал команды
                 # Пытаемся очистить созданное событие
                 try: await self.end_event(new_event.id) # Вызываем end_event для очистки и удаления
                 except Exception as cleanup_e: print(f"WorldSimulationProcessor: Error during cleanup of event {new_event.id} after channel error: {cleanup_e}")
                 return None


            event_channel_callback = self._send_callback_factory(new_event.channel_id)

            # Передаем ВСЕ необходимые зависимости StageProcessor'у из managers_for_tick (которые были бы доступны).
            # Это требует, чтобы эти менеджеры были инжектированы в WorldSimulationProcessor.__init__.
            # Создаем словарь менеджеров для передачи в advance_stage.
            # Включаем все менеджеры и процессоры, которые могут понадобиться StageProcessor или тем, кого он вызывает.
            managers_for_stage_processor = {
                'character_manager': self._character_manager, 'location_manager': self._location_manager,
                'rule_engine': self._rule_engine, 'openai_service': self._openai_service,
                'npc_manager': self._npc_manager, 'combat_manager': self._combat_manager,
                'item_manager': self._item_manager, 'time_manager': self._time_manager,
                'status_manager': self._status_manager, 'party_manager': self._party_manager,
                'event_manager': self._event_manager, # EventStageProcessor нужен EventManager
                'persistence_manager': self._persistence_manager, # StageProcessor может понадобиться для сохранения
                'send_callback_factory': self._send_callback_factory, # StageProcessor может понадобиться для вызова callback'ов
                # Передаем Processors Действий, если StageProcessor или вызываемые им менеджеры в них нуждаются
                'character_action_processor': self._character_action_processor,
                'party_action_processor': self._party_action_processor,
                # TODO: Передайте NpcActionProcessor, EventActionProcessor (EventActionProcessor уже в списке обязательных WSP, но StageProcessor может его вызвать?)
                # 'event_action_processor': self._event_action_processor, # StageProcessor не должен вызывать ActionProcessor. ActionProcessor вызывает StageProcessor.
                # TODO: Добавьте другие менеджеры/сервисы, если они нужны EventStageProcessor
            }


            await self._event_stage_processor.advance_stage(
                event=new_event, target_stage_id=new_event.current_stage_id, # target_stage_id будет 'event_start' или другой начальный из шаблона
                send_message_callback=event_channel_callback, # Callback для канала САМОГО события
                # Передаем менеджеры/сервисы, используя распаковку словаря
                **managers_for_stage_processor,
                # Контекст перехода
                transition_context={"trigger": "event_start", "template_id": event_template_id, "location_id": location_id}
            )
            print(f"WorldSimulationProcessor: Initial stage processing completed for event {new_event.id}.")


            # --- 5. Сохраняем начальное состояние после обработки первой стадии ---
            # Сохранение происходит здесь один раз после запуска.
            # Дальнейшие изменения состояния сущностей будут помечаться dirty и сохраняться WorldTick'ом.
            if self._persistence_manager:
                 # PersistenceManager.save_game_state ожидает TimeManager в kwargs
                 await self._persistence_manager.save_game_state(time_manager=self._time_manager) # Передаем TimeManager
                 print(f"WorldSimulationProcessor: Initial game state saved after starting event {new_event.id}.")
            else:
                 print("WorldSimulationProcessor: Skipping initial save after event start (PersistenceManager not available).")


            return new_event.id # Возвращаем ID созданного и запущенного события


        except Exception as e:
            print(f"WorldSimulationProcessor: ❌ КРИТИЧЕСКАЯ ОШИБКА во время обработки начальной стадии события {new_event.id}: {e}")
            import traceback
            print(traceback.format_exc())

            # Пытаемся очистить созданное событие в случае ошибки
            try: await self.end_event(new_event.id) # Вызываем end_event для очистки и удаления
            except Exception as cleanup_e: print(f"WorldSimulationProcessor: Error during cleanup of event {new_event.id} after critical stage processing error: {cleanup_e}")

            # Сообщаем об ошибке в канал, откуда пришла команда.
            await self._send_callback_factory(channel_id)(f"❌ КРИТИЧЕСКАЯ ОШИБКА при запуске начальной стадии события '{event_template_id}': {e}. Событие остановлено. Проверьте логи бота.")

            return None


    async def end_event(self, event_id: str) -> None:
        # ... (логика end_event остается прежней, но убедитесь, что cleanup логика использует self._атрибуты) ...
        """
        Оркестрирует процесс завершения события.
        """
        print(f"WorldSimulationProcessor: Received request to end event {event_id}.")

        event: Optional[Event] = self._event_manager.get_event(event_id)
        if not event:
            print(f"WorldSimulationProcessor: Warning: Attempted to end non-existent event {event_id}.")
            return

        # Проверяем, не находится ли событие уже в процессе завершения или завершено
        if not event.is_active and event.current_stage_id == 'event_end':
             print(f"WorldSimulationProcessor: Event {event_id} is already marked as ended. Skipping end process.")
             return

        # Если событие еще не в стадии завершения, переводим его туда (для триггеров OnExit стадии)
        if event.current_stage_id != 'event_end':
             print(f"WorldSimulationProcessor: Forcing event {event.id} current_stage_id to 'event_end' for termination.")
             # TODO: Возможно, вызывать event_stage_processor.advance_stage(..., target='event_end')
             # чтобы все OnExit триггеры для текущей стадии выполнились корректно?
             # Если 'event_end' не определена как стадия, это может вызвать проблемы.
             # Для простоты пока просто меняем ID стадии.
             event.current_stage_id = 'event_end'
             # Помечаем событие как измененное вручную
             self._event_manager._dirty_events.add(event.id)


        print(f"WorldSimulationProcessor: Ending event {event.id} ('{event.name}'). Initiating cleanup.")

        # TODO: --- 1. Выполнение Cleanup Логики ---
        # Используем инжектированные менеджеры (проверяем их наличие перед использованием)
        cleaned_up_npcs_count = 0
        if self._npc_manager: # Проверяем, что NpcManager проинициализирован
            # Получаем список ID временных NPC, связанных с этим событием (хранится в state_variables события)
            temp_npc_ids: List[str] = event.state_variables.get('temp_npcs', [])
            if temp_npc_ids:
                 print(f"WorldSimulationProcessor: Cleaning up {len(temp_npc_ids)} temporary NPCs for event {event.id}.")
                 successfully_removed_npc_ids: List[str] = []
                 # Удаляем NPC по ID через NPCManager.
                 # Итерируем по копии списка, чтобы можно было безопасно менять оригинал в случае успеха (event.state_variables['temp_npcs']).
                 # Передаем менеджеры, которые могут понадобиться NpcManager.remove_npc в kwargs.
                 cleanup_managers_for_npc = {
                     'item_manager': self._item_manager,
                     'status_manager': self._status_manager,
                     'party_manager': self._party_manager,
                     'combat_manager': self._combat_manager, # NPC может быть в бою
                     # TODO: другие менеджеры, нужные для cleanup NPC
                 }
                 for npc_id in list(temp_npc_ids):
                      try:
                           # NpcManager.remove_npc должен удалить NPC из своего кеша и пометить для удаления в БД.
                           removed_id = await self._npc_manager.remove_npc(npc_id, **cleanup_managers_for_npc) # Requires NpcManager.remove_npc implementation
                           if removed_id:
                                successfully_removed_npc_ids.append(removed_id)
                                # Удаляем успешно удаленный NPC из event.state_variables списка (если он там был)
                                if 'temp_npcs' in event.state_variables and npc_id in event.state_variables['temp_npcs']:
                                     event.state_variables['temp_npcs'].remove(npc_id)
                           else:
                                print(f"WorldSimulationProcessor: Warning: NpcManager.remove_npc returned None for NPC {npc_id}.")


                      except Exception as e:
                           print(f"WorldSimulationProcessor: Error removing temp NPC {npc_id} for event {event.id}: {e}")
                           import traceback
                           print(traceback.format_exc())

                 cleaned_up_npcs_count = len(successfully_removed_npc_ids)
                 print(f"WorldSimulationProcessor: Finished NPC cleanup for event {event.id}. {cleaned_up_npcs_count} NPCs removed.")
                 # Если список temp_npcs в state_variables стал пуст после чистки, удаляем сам ключ
                 if 'temp_npcs' in event.state_variables and not event.state_variables['temp_npcs']:
                      event.state_variables.pop('temp_npcs')
                      self._event_manager._dirty_events.add(event.id) # Помечаем событие dirty, если изменили state_variables


        # TODO: Implement cleanup for temporary items (if any) via ItemManager
        # Используйте self._item_manager. Предполагаем, что ID временных предметов хранятся в event.state_variables (например, под ключом 'temp_items').
        # if self._item_manager:
        #     temp_item_ids: List[str] = event.state_variables.get('temp_items', [])
        #     if temp_item_ids:
        #          print(f"WorldSimulationProcessor: Cleaning up {len(temp_item_ids)} temporary items for event {event.id}.")
        #          cleanup_managers_for_item = {
        #              # TODO: менеджеры, нужные для ItemManager.remove_item (или move_item куда-то)
        #          }
        #          successfully_cleaned_item_ids: List[str] = []
        #          for item_id in list(temp_item_ids):
        #               try:
        #                    # ItemManager.remove_item (или move_item) должен удалить/переместить предмет и пометить dirty.
        #                    # Возвращает ID удаленного предмета или None.
        #                    removed_id = await self._item_manager.remove_item(item_id, **cleanup_managers_for_item) # Requires ItemManager.remove_item implementation
        #                    if removed_id:
        #                         successfully_cleaned_item_ids.append(removed_id)
        #                         # Удаляем успешно обработанный предмет из event.state_variables списка
        #                         if 'temp_items' in event.state_variables and item_id in event.state_variables['temp_items']:
        #                              event.state_variables['temp_items'].remove(item_id)
        #               except Exception as e: ... error handling ...
        #          if 'temp_items' in event.state_variables and not event.state_variables['temp_items']:
        #               event.state_variables.pop('temp_items')
        #               self._event_manager._dirty_events.add(event.id)


        # TODO: Очистка активных Combat'ов, связанных с этим событием (нужен CombatManager, link from combat to event_id)
        # Используйте self._combat_manager. Предполагаем, что CombatManager имеет метод get_combats_by_event_id.
        # if self._combat_manager and hasattr(self._combat_manager, 'get_combats_by_event_id'):
        #      event_combats = self._combat_manager.get_combats_by_event_id(event.id)
        #      if event_combats:
        #           print(f"WorldSimulationProcessor: Cleaning up {len(event_combats)} combats for event {event.id}.")
        #           cleanup_managers_for_combat = {
        #               'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
        #               'party_manager': self._party_manager, 'location_manager': self._location_manager,
        #               'status_manager': self._status_manager, 'item_manager': self._item_manager,
        #               # TODO: другие менеджеры
        #           }
        #           for combat in list(event_combats): # Итерируем по копии списка из менеджера
        #                if combat.is_active:
        #                     try:
        #                          # CombatManager.end_combat должен завершить бой, очистить участников, пометить dirty.
        #                          await self._combat_manager.end_combat(combat.id, **cleanup_managers_for_combat) # end_combat ожидает kwargs
        #                     except Exception as e: ... error handling ...


        # TODO: Удаление статус-эффектов, специфичных для события? (StatusManager)
        # Используйте self._status_manager. Предполагаем, что StatusManager имеет метод remove_status_effects_by_event_id.
        # if self._status_manager and hasattr(self._status_manager, 'remove_status_effects_by_event_id'):
        #      cleanup_managers_for_status = {
        #          # TODO: менеджеры, нужные для StatusManager.remove_status_effects
        #      }
        #      try:
        #           await self._status_manager.remove_status_effects_by_event_id(event.id, **cleanup_managers_for_status)
        #           print(f"WorldSimulationProcessor: Cleaned up event-specific status effects for event {event.id}.")
        #      except Exception as e: ... error handling ...


        # --- 2. Оповещение о завершении события ---
        # Проверяем, что у события есть channel_id перед отправкой сообщения
        if event.channel_id is not None:
            send_callback = self._send_callback_factory(event.channel_id)
            end_message_content: str = event.end_message_template if hasattr(event, 'end_message_template') and event.end_message_template else f"Событие **{event.name}** завершилось."
            try:
                 await send_callback(end_message_content)
                 print(f"WorldSimulationProcessor: Sent event end message for event {event.id} to channel {event.channel_id}.")
            except Exception as e:
                 print(f"WorldSimulationProcessor: Error sending event end message for event {event.id} to channel {event.channel_id}: {e}")
                 import traceback
                 print(traceback.format_exc())


        # --- 3. Помечаем событие как неактивное и удаляем из runtime кеша ---
        event.is_active = False
        self._event_manager.remove_active_event(event.id) # EventManager удаляет из своего активного кеша и помечает на удаление/сохранение


        print(f"WorldSimulationProcessor: Event {event.id} marked inactive and removed from active cache.")

        # --- 4. Сохраняем финальное состояние ---
        # PersistenceManager сохранит все dirty сущности, включая событие, помеченное EventManager.remove_active_event
        if self._persistence_manager:
             try:
                 # PersistenceManager.save_game_state ожидает TimeManager в kwargs
                 await self._persistence_manager.save_game_state(time_manager=self._time_manager) # Передаем TimeManager
                 print(f"WorldSimulationProcessor: Final game state saved after ending event {event.id}.")
             except Exception as e:
                 print(f"WorldSimulationProcessor: Error during final save after ending event {event.id}: {e}")
                 import traceback
                 print(traceback.format_exc())
        else:
             print("WorldSimulationProcessor: Skipping final save after ending event (PersistenceManager not available).")


        print(f"WorldSimulationProcessor: Event {event_id} ending process completed.")


    # --- Мировой Тик ---
    async def process_world_tick(self, game_time_delta: Any) -> None: # game_time_delta - в игровых минутах
        """
        Обрабатывает один "тик" игрового времени.
        Координирует вызовы tick-методов у других менеджеров и процессоров.
        """
        # print(f"WorldSimulationProcessor: Processing world tick with delta: {game_time_delta}") # Бывает очень шумно

        # --- Передаем все необходимые менеджеры/сервисы в kwargs для tick методов ---
        # Это нужно, если компонент X в своем process_tick нуждается в компоненте Y,
        # и Y не был инжектирован в X при его __init__.
        # Передаем ссылки на все компоненты, которые WorldSimulationProcessor сам имеет.
        # ИСПРАВЛЕНИЕ: Включаем все опциональные менеджеры и все процессоры, если они проинстанцированы.
        managers_and_processors_for_tick = {
             # Обязательные зависимости WSP (нужны для tick методов других)
             'character_manager': self._character_manager,
             'location_manager': self._location_manager,
             'rule_engine': self._rule_engine,
             'openai_service': self._openai_service,
             'event_stage_processor': self._event_stage_processor,
             'event_action_processor': self._event_action_processor,
             'persistence_manager': self._persistence_manager,
             'send_callback_factory': self._send_callback_factory, # Фабрика callback'ов

             # Processors Действий (их process_tick вызываем, но они также нужны друг другу и менеджерам)
             'character_action_processor': self._character_action_processor,
             'party_action_processor': self._party_action_processor,
             # TODO: Добавьте NpcActionProcessor
             # 'npc_action_processor': self._npc_action_processor,

             # Опциональные менеджеры (могут иметь process_tick или нужны в kwargs)
             'event_manager': self._event_manager, # EventManager нужен StageProcessor
             'npc_manager': self._npc_manager,
             'combat_manager': self._combat_manager,
             'item_manager': self._item_manager,
             'time_manager': self._time_manager, # TimeManager нужен почти всем
             'status_manager': self._status_manager,
             'crafting_manager': self._crafting_manager,
             'economy_manager': self._economy_manager,
             'party_manager': self._party_manager, # PartyManager нужен PartyActionProcessor
             # TODO: Передайте другие менеджеры/сервисы
        }

        # Optional: Фильтруем None значения для чистоты, хотя **kwargs и так обрабатывает None
        # managers_and_processors_for_tick = {k: v for k, v in managers_and_processors_for_tick.items() if v is not None}


        # 1. Обновление времени игры (TimeManager)
        # TimeManager обрабатывает таймеры и может пометить сущности dirty, если таймеры привязаны к ним.
        if self._time_manager:
            try:
                 # TimeManager.process_tick может нуждаться в других менеджерах для доступа к таймерам сущностей
                 await self._time_manager.process_tick(game_time_delta=game_time_delta, **managers_and_processors_for_tick)
                 # print("WorldSimulationProcessor: TimeManager tick processed.")
            except Exception as e: print(f"WorldSimulationProcessor: Error during TimeManager process_tick: {e}"); traceback.print_exc()


        # 2. Обработка статусов (StatusManager)
        # StatusManager обрабатывает длительность статусов и может пометить сущности/статусы dirty.
        if self._status_manager:
             try:
                  # StatusManager.process_tick может нуждаться в менеджерах сущностей для применения/снятия статусов
                  await self._status_manager.process_tick(game_time_delta=game_time_delta, **managers_and_processors_for_tick)
                  # print("WorldSimulationProcessor: StatusManager tick processed.")
             except Exception as e: print(f"WorldSimulationProcessor: Error during StatusManager process_tick: {e}"); traceback.print_exc()


        # 3. Обработка очередей крафтинга (CraftingManager)
        # CraftingManager обрабатывает прогресс крафтинговых задач и может пометить сущности/предметы dirty.
        if self._crafting_manager:
             try:
                  # CraftingManager.process_tick может нуждаться в менеджерах сущностей/предметов
                  await self._crafting_manager.process_tick(game_time_delta=game_time_delta, **managers_and_processors_for_tick)
                  # print("WorldSimulationProcessor: CraftingManager tick processed.")
             except Exception as e: print(f"WorldSimulationProcessor: Error during CraftingManager process_tick: {e}"); traceback.print_exc()


        # 4. Обработка активных боев (CombatManager)
        # CombatManager управляет боями и их участниками, может вызывать тик участников или свою логику.
        # WorldSimulationProcessor итерирует по активным боям (получая их список от CombatManager), вызывает их тик и обрабатывает завершившиеся.
        if self._combat_manager:
            try:
                 # CombatManager должен уметь сам найти свои активные бои и иметь метод end_combat
                 if hasattr(self._combat_manager, 'get_active_combats') and hasattr(self._combat_manager, 'process_combat_round') and hasattr(self._combat_manager, 'end_combat'):
                      active_combats = self._combat_manager.get_active_combats()
                      combats_to_end_ids: List[str] = []

                      if active_combats:
                           # Проходим по активным боям, вызываем их тик. Итерируем по копии.
                           for combat in list(active_combats):
                                if not combat.is_active: continue
                                # process_combat_round должен вернуть сигнал, если бой завершился.
                                # CombatManager.process_combat_round может нуждаться в менеджерах сущностей, RuleEngine, StatusManager и т.д.
                                combat_finished_signal = await self._combat_manager.process_combat_round(combat_id=combat.id, game_time_delta=game_time_delta, **managers_and_processors_for_tick)
                                if combat_finished_signal: combats_to_end_ids.append(combat.id)

                           # Обрабатываем завершившиеся бои
                           for combat_id in combats_to_end_ids:
                                # CombatManager.end_combat может нуждаться в менеджерах сущностей для очистки участников, StatusManager для снятия статусов и т.д.
                                await self._combat_manager.end_combat(combat_id, **managers_and_processors_for_tick) # Передаем менеджеры в end_combat

                 else:
                      print("WorldSimulationProcessor: Warning: CombatManager or its required methods not available for tick processing.")

            except Exception as e: print(f"WorldSimulationProcessor: Error during overall CombatManager tick processing: {e}"); traceback.print_exc()


        # 5. Обработка индивидуальных действий персонажей (CharacterActionProcessor)
        # WorldSimulationProcessor получает список ID активных персонажей от CharacterManager
        # и делегирует обработку тика CharacterActionProcessor.
        if self._character_manager and self._character_action_processor:
             try:
                  # CharacterManager должен иметь метод get_entities_with_active_action()
                  if hasattr(self._character_manager, 'get_entities_with_active_action') and hasattr(self._character_action_processor, 'process_tick'):
                       characters_with_active_action = self._character_manager.get_entities_with_active_action()
                       if characters_with_active_action:
                           # print(f"WorldSimulationProcessor: Ticking {len(characters_with_active_action)} active Characters...") # Debug print
                           # Итерируем по копии, т.k. список в CharacterManager может измениться при завершении действия
                           for char_id in list(characters_with_active_action):
                                # Вызываем process_tick у CharacterActionProcessor, передавая ID персонажа
                                # CharacterActionProcessor.process_tick обрабатывает действие для ОДНОГО персонажа
                                # Ему нужны менеджеры/сервисы, передаем их из managers_and_processors_for_tick
                                await self._character_action_processor.process_tick(char_id=char_id, game_time_delta=game_time_delta, **managers_and_processors_for_tick) # Передаем все зависимости

                  # else: # Это уже проверено в if выше (self._character_manager and self._character_action_processor)
                       # print("WorldSimulationProcessor: Warning: CharacterManager or CharacterActionProcessor or their required methods not available for tick processing.")

             except Exception as e: print(f"WorldSimulationProcessor: Error during CharacterActionProcessor process_tick: {e}"); traceback.print_exc()


        # 6. Обработка индивидуальных действий NPC (NpcManager / NpcActionProcessor)
        # Если есть NpcActionProcessor, вызываем его. Если нет, и NpcManager сам обрабатывает тик, вызываем NpcManager.
        if self._npc_manager: # Проверяем, что NPCManager проинстанцирован (нужен для получения ID)
             # TODO: Если создан NpcActionProcessor, используем его.
             # if self._npc_action_processor:
             #      try:
             #           if hasattr(self._npc_manager, 'get_entities_with_active_action') and hasattr(self._npc_action_processor, 'process_tick'):
             #                npcs_with_active_action = self._npc_manager.get_entities_with_active_action()
             #                if npcs_with_active_action:
             #                     print(f"WorldSimulationProcessor: Ticking {len(npcs_with_active_action)} active NPCs via NpcActionProcessor...")
             #                     for npc_id in list(npcs_with_active_action):
             #                          await self._npc_action_processor.process_tick(npc_id=npc_id, game_time_delta=game_time_delta, **managers_and_processors_for_tick)
             #           else:
             #                print("WorldSimulationProcessor: Warning: NpcManager or NpcActionProcessor or their required methods not available for NPC tick processing.")
             #      except Exception as e: print(f"WorldSimulationProcessor: Error during NpcActionProcessor process_tick: {e}"); traceback.print_exc()
             # else: # Если NpcActionProcessor не создан, и NpcManager сам обрабатывает тик
             try:
                  # NpcManager должен иметь метод get_entities_with_active_action() и process_tick (для себя)
                  if hasattr(self._npc_manager, 'get_entities_with_active_action') and hasattr(self._npc_manager, 'process_tick'):
                       npcs_with_active_action = self._npc_manager.get_entities_with_active_action()
                       if npcs_with_active_action:
                            print(f"WorldSimulationProcessor: Ticking {len(npcs_with_active_action)} active NPCs via NpcManager...")
                            # Итерируем по копии
                            for npc_id in list(npcs_with_active_action):
                                # NpcManager.process_tick обрабатывает действие для ОДНОГО NPC
                                # Ему нужны менеджеры/сервисы, передаем их из managers_and_processors_for_tick
                                await self._npc_manager.process_tick(npc_id=npc_id, game_time_delta=game_time_delta, **managers_and_processors_for_tick) # Передаем все зависимости

                  # else: # Это уже проверено в if выше (if self._npc_manager)
                       # print("WorldSimulationProcessor: Warning: NpcManager or its required methods not available for tick processing.")

             except Exception as e: print(f"WorldSimulationProcessor: Error during NpcManager process_tick: {e}"); traceback.print_exc()


        # 7. Обработка групповых действий партий (PartyActionProcessor)
        # WorldSimulationProcessor получает список ID активных партий от PartyManager
        # и делегирует обработку тика PartyActionProcessor.
        if self._party_manager and self._party_action_processor:
             try:
                  # PartyManager должен иметь метод get_parties_with_active_action()
                  if hasattr(self._party_manager, 'get_parties_with_active_action') and hasattr(self._party_action_processor, 'process_tick'):
                       parties_with_active_action = self._party_manager.get_parties_with_active_action()
                       if parties_with_active_action:
                            # print(f"WorldSimulationProcessor: Ticking {len(parties_with_active_action)} active Parties...") # Debug print
                            # Итерируем по копии, т.k. список в PartyManager может измениться при завершении действия
                            for party_id in list(parties_with_active_action):
                                 # Вызываем process_tick у PartyActionProcessor, передавая ID партии
                                 # PartyActionProcessor.process_tick обрабатывает действие для ОДНОЙ партии
                                 # Ему нужны менеджеры/сервисы, передаем их из managers_and_processors_for_tick
                                 await self._party_action_processor.process_tick(party_id=party_id, game_time_delta=game_time_delta, **managers_and_processors_for_tick) # Передаем все зависимости

                  # else: # Это уже проверено в if выше (self._party_manager and self._party_action_processor)
                       # print("WorldSimulationProcessor: Warning: PartyManager or PartyActionProcessor or their required methods not available for tick processing.")

             except Exception as e: print(f"WorldSimulationProcessor: Error during PartyActionProcessor process_tick: {e}"); traceback.print_exc()


        # 8. Обработка других менеджеров, которым нужен тик (ItemManager, LocationManager, EconomyManager)
        # Эти менеджеры обрабатывают глобальные аспекты или сущности, не связанные напрямую с действиями Char/NPC/Party.
        # ItemManager может обрабатывать временные предметы на земле (их исчезновение).
        if self._item_manager and hasattr(self._item_manager, 'process_tick'):
             try:
                  # ItemManager.process_tick может нуждаться в TimeManager, LocationManager и т.п.
                  await self._item_manager.process_tick(game_time_delta=game_time_delta, **managers_and_processors_for_tick)
             except Exception as e: print(f"WorldSimulationProcessor: Error during ItemManager process_tick: {e}"); traceback.print_exc()

        # LocationManager может обрабатывать изменения в окружении (погоду и т.п.).
        if self._location_manager and hasattr(self._location_manager, 'process_tick'):
             try:
                  # LocationManager.process_tick может нуждаться в TimeManager, RuleEngine и т.п.
                  await self._location_manager.process_tick(game_time_delta=game_time_delta, **managers_and_processors_for_tick)
             except Exception as e: print(f"WorldSimulationProcessor: Error during LocationManager process_tick: {e}"); traceback.print_exc()

        # EconomyManager может обрабатывать изменение цен со временем, пополнение запасов.
        if self._economy_manager and hasattr(self._economy_manager, 'process_tick'):
             try:
                  # EconomyManager.process_tick может нуждаться в TimeManager, RuleEngine, ItemManager и т.п.
                  await self._economy_manager.process_tick(game_time_delta=game_time_delta, **managers_and_processors_for_tick)
             except Exception as e: print(f"WorldSimulationProcessor: Error during EconomyManager process_tick: {e}"); traceback.print_exc()


        # 9. Проверка активных событий на автоматические переходы стадий (по времени, условиям)
        # WorldSimulationProcessor координирует проверку и делегирует EventStageProcessor.
        if self._event_manager and self._event_stage_processor:
             # EventManager должен уметь получить активные события
             if hasattr(self._event_manager, 'get_active_events') and hasattr(self, '_check_event_for_auto_transition') and hasattr(self._event_stage_processor, 'advance_stage'):
                  active_events: List[Event] = self._event_manager.get_active_events()
                  events_to_auto_advance_info: List[Tuple[Event, str]] = []

                  for event in list(active_events): # Итерируем по копии, т.к. advance_stage может повлиять на список
                       if not event.is_active or event.current_stage_id == 'event_end': continue
                       # _check_event_for_auto_transition использует self._атрибуты (TimeManager, RuleEngine, NpcManager),
                       # которые инжектированы в WSP.
                       next_stage_id_auto = self._check_event_for_auto_transition(event)
                       if next_stage_id_auto:
                            print(f"WorldSimulationProcessor: Event {event.id} ('{event.name}'): Auto-transition condition met from stage '{event.current_stage_id}' to stage '{next_stage_id_auto}'. Scheduling transition.")
                            events_to_auto_advance_info.append((event, next_stage_id_auto))

                  # --- Обработка Обнаруженных Авто-Переходов ---
                  # Вызываем StageProcessor для каждого запланированного перехода.
                  for event_to_advance, target_stage_id_auto in events_to_auto_advance_info:
                       try:
                            # Проверяем, что у события есть канал перед получением callback
                            if event_to_advance.channel_id is None:
                                 print(f"WorldSimulationProcessor: Warning: Cannot auto-advance event {event_to_advance.id}. Event has no channel_id for notifications.")
                                 continue # Пропускаем авто-переход, если нет канала для уведомлений.

                            event_channel_callback = self._send_callback_factory(event_to_advance.channel_id)

                            # EventStageProcessor.advance_stage ожидает много менеджеров, передаем их из managers_and_processors_for_tick.
                            await self._event_stage_processor.advance_stage(
                                event=event_to_advance, target_stage_id=target_stage_id_auto,
                                send_message_callback=event_channel_callback,
                                **managers_and_processors_for_tick, # Передаем все зависимости
                                transition_context={"trigger": "auto_advance", "from_stage_id": event_to_advance.current_stage_id, "to_stage_id": target_stage_id_auto}
                            )
                            print(f"WorldSimulationProcessor: Auto-transition to '{target_stage_id_auto}' completed for event {event_to_advance.id}.")
                       except Exception as e: print(f"WorldSimulationProcessor: Error during auto-transition execution for event {event_to_advance.id} to stage {target_stage_id_auto}: {e}"); traceback.print_exc()

             else:
                  print("WorldSimulationProcessor: Warning: EventManager or EventStageProcessor or their required methods not available for auto-transition check.")


        # 10. Очистка завершившихся событий ('event_end' stage)
        # WorldSimulationProcessor координирует завершение, вызывая свой end_event.
        # EventManager должен уметь получить активные события.
        if self._event_manager and hasattr(self._event_manager, 'get_active_events'):
             # Находим активные события, которые уже в стадии 'event_end' (помещены туда вручную или авто-переходом)
             events_already_ending_ids: List[str] = [ event.id for event in list(self._event_manager.get_active_events()) if event.current_stage_id == 'event_end' ]
             # Вызываем end_event для каждого такого события
             for event_id in events_already_ending_ids:
                  # end_event сам удалит событие из active_events в EventManager после очистки
                  await self.end_event(event_id)


        # 11. Опционально: Сохранение состояния игры после каждого тика
        # Рекомендуется сохранять не каждый тик, если тики очень частые.
        # PersistenceManager.save_game_state вызывает save_all_X у всех менеджеров,
        # которые помечали сущности как dirty во время этого тика.
        # Частота сохранения может быть настроена в WorldSimulationProcessor или PersistenceManager.
        # if self._persistence_manager:
        #      # TODO: Добавить логику определения, нужно ли сейчас сохранять (например, по счетчику тиков)
        #      should_auto_save_logic_here = False # Placeholder
        #      if should_auto_save_logic_here:
        #           try:
        #                # PersistenceManager.save_game_state ожидает TimeManager в kwargs
        #                await self._persistence_manager.save_game_state(time_manager=self._time_manager)
        #           except Exception as e: print(f"WorldSimulationProcessor: Error during auto-save: {e}"); traceback.print_exc()


    # --- Вспомогательные методы ---

    # Логика проверки условий авто-перехода. Находится внутри WorldSimulationProcessor.
    def _check_event_for_auto_transition(self, event: Event) -> Optional[str]:
        # ... (логика _check_event_for_auto_transition остается прежней, она использует self._атрибуты) ...
        """
        Проверяет текущую стадию события на условия автоматического перехода.
        Использует данные стадии и менеджеры (TimeManager, RuleEngine, NpcManager) для оценки условий.
        Возвращает target stage ID или None.
        """
        # print(f"WSP: Checking event {event.id} stage '{event.current_stage_id}' for auto-transition conditions...") # Debug print

        current_stage_data = event.stages_data.get(event.current_stage_id)
        if not current_stage_data:
             print(f"WorldSimulationProcessor: Warning: _check_event_for_auto_transition: No stage data found for current stage {event.current_stage_id} in event {event.id}.")
             return None # Cannot check without stage data

        # Создаем временный объект EventStage для удобного доступа к данным стадии
        # Используем EventStage.from_dict, если у вас есть такая модель
        # Если нет, работайте напрямую с current_stage_data: Dict[str, Any]
        current_stage_obj: EventStage = EventStage.from_dict(current_stage_data) # Requires EventStage model imported


        # Проверка правила 'auto_transitions' в данных стадии (ожидаем список словарей)
        # Используем .get() для безопасного доступа к ключу в словаре
        auto_transitions_rules: Optional[List[Dict[str, Any]]] = current_stage_data.get('auto_transitions', None)

        if isinstance(auto_transitions_rules, list):
            # Проходим по каждому правилу авто-перехода в списке
            for rule in auto_transitions_rules:
                 rule_type = rule.get('type') # Тип правила ('time_elapsed', 'state_variable_threshold' и т.д.)

                 # --- Правило: time_elapsed (время истекло) ---
                 # Требует TimeManager для работы с таймерами в event.state_variables.
                 # Используем сохраненный self._time_manager
                 if rule_type == 'time_elapsed' and self._time_manager is not None:
                      timer_var = rule.get('state_var') # Имя переменной таймера в event.state_variables (например, 'stage_timer')
                      threshold = rule.get('threshold') # Значение порога для таймера (число)
                      target_stage_id = rule.get('target_stage') # ID стадии для перехода

                      # Валидация параметров правила
                      if isinstance(timer_var, str) and timer_var and \
                         threshold is not None and isinstance(threshold, (int, float)) and \
                         isinstance(target_stage_id, str) and target_stage_id:

                           # Получаем текущее значение таймера из event.state_variables. TimeManager обновляет это значение в process_tick.
                           current_timer_value: Any = event.state_variables.get(timer_var, 0.0) # Default to 0.0 if timer variable not set yet


                           # Проверка условия: текущее значение таймера достигло или превысило порог
                           if isinstance(current_timer_value, (int, float)) and current_timer_value >= threshold:
                                # Условие выполнено. Возвращаем целевую стадию для перехода.
                                # print(f"WSP: Event {event.id}, stage '{event.current_stage_id}' met 'time_elapsed' condition for timer '{timer_var}' (Current: {current_timer_value}, Threshold: {threshold}). Target stage: '{target_stage_id}'.")
                                return target_stage_id # Возвращаем ID стадии


                 # --- Правило: state_variable_threshold (порог значения переменной состояния) ---
                 # Проверяет значение переменной состояния event.state_variables на соответствие порогу с оператором.
                 elif rule_type == 'state_variable_threshold':
                      variable_name = rule.get('variable') # Имя переменной в event.state_variables
                      operator = rule.get('operator') # Оператор ('<', '<=', '==', '>', '>=', '!=')
                      value_threshold = rule.get('value') # Значение для сравнения
                      target_stage_id = rule.get('target_stage') # ID стадии для перехода

                      # Валидация параметров правила
                      if isinstance(variable_name, str) and variable_name and \
                         isinstance(operator, str) and operator in ['<', '<=', '==', '>', '>=', '!='] and \
                         value_threshold is not None and \
                         isinstance(target_stage_id, str) and target_stage_id:

                           # Получаем текущее значение переменной из event.state_variables
                           current_var_value: Any = event.state_variables.get(variable_name)

                           # Проверка условия сравнения, если переменная существует (не None).
                           if current_var_value is not None:
                                condition_met = False
                                try:
                                    # Выполняем сравнение в зависимости от оператора
                                    # Убеждаемся, что оба значения имеют подходящий тип для сравнения.
                                    # Например, для числовых операторов (<, <=, >, >=) оба значения должны быть числами.
                                    if operator in ['<', '<=', '>', '>='] and (not isinstance(current_var_value, (int, float)) or not isinstance(value_threshold, (int, float))): # ИСПРАВЛЕНИЕ: Убедимся, что оба значения числовые для числовых сравнений
                                         # Если оператор числовой, а значения нет - пропускаем проверку для этого правила.
                                         # print(f"WSP: Info: _check_event_for_auto_transition: Skipping numerical comparison for variable '{variable_name}' ({type(current_var_value).__name__}) with threshold ({type(value_threshold).__name__}) in event {event.id} due to type mismatch.")
                                         pass # Пропускаем это правило, если типы некорректны для числового сравнения
                                    else: # Для == и != можно сравнивать разные типы (число со строкой и т.п.)
                                         if operator == "<":   condition_met = current_var_value < value_threshold
                                         elif operator == "<=": condition_met = current_var_value <= value_threshold
                                         elif operator == "==": condition_met = current_var_value == value_threshold
                                         elif operator == ">":   condition_met = current_var_value > value_threshold
                                         elif operator == ">=": condition_met = current_var_value >= value_threshold
                                         elif operator == "!=": condition_met = current_var_value != value_threshold

                                    if condition_met:
                                         # Условие выполнено. Возвращаем целевую стадию для перехода.
                                         # print(f"WSP: Event {event.id}, stage '{event.current_stage_id}' met 'state_variable_threshold' condition for variable '{variable_name}' ({current_var_value} {operator} {value_threshold}). Target stage: '{target_stage_id}'.")
                                         return target_stage_id # Возвращаем ID стадии

                                except TypeError as e:
                                     # Обработка ошибки типа при сравнении (например, сравниваем число со строкой с <)
                                     print(f"WorldSimulationProcessor: Warning: _check_event_for_auto_transition: TypeError comparing variable '{variable_name}' ({type(current_var_value).__name__}) with threshold ({type(value_threshold).__name__}) for event {event.id}: {e}")
                                except Exception as e:
                                     print(f"WorldSimulationProcessor: Error during 'state_variable_threshold' check for variable '{variable_name}' for event {event.id}: {e}")
                                     import traceback
                                     print(traceback.format_exc())


                           # Если current_var_value is None, условие не может быть проверено (переменной нет).
                           # print(f"WSP: Info: _check_event_for_auto_transition: Variable '{variable_name}' not found in event state for threshold check in event {event.id}.")


                 # --- TODO: Добавить логику для других типов авто-переходов ---
                 # - "all_involved_npcs_defeated": Требует NpcManager (self._npc_manager) и RuleEngine (self._rule_engine).
                 #   Нужно получить NPC IDs из event.state_variables, проверить их статус через NpcManager.
                 #   Пример:
                 #   elif rule_type == 'all_involved_npcs_defeated' and self._npc_manager is not None and self._rule_engine is not None:
                 #       npc_ids_var = rule.get('npc_ids_variable', 'involved_npcs') # Имя переменной с ID NPC в state_variables
                 #       involved_npc_ids: List[str] = event.state_variables.get(npc_ids_var, [])
                 #       if isinstance(involved_npc_ids, list):
                 #           all_defeated = True
                 #           if not involved_npc_ids: # Если список пуст, условие выполнено (нет NPC для поражения)
                 #               all_defeated = True
                 #           else:
                 #               # NpcManager должен уметь получать NPC по ID. RuleEngine должен уметь проверять их статус поражения.
                 #               # RuleEngine.are_npcs_defeated(npc_ids, npc_manager, rule_engine_context_managers?) -> bool
                 #               # Передаем NpcManager в контекст RuleEngine для проверки
                 #               if hasattr(self._rule_engine, 'are_npcs_defeated'):
                 #                    try:
                 #                         # RuleEngine.are_npcs_defeated needs access to NpcManager
                 #                         all_defeated = await self._rule_engine.are_npcs_defeated(involved_npc_ids, context={'npc_manager': self._npc_manager, **self._get_managers_for_rule_engine_context()}) # Pass required managers
                 #                    except Exception as e:
                 #                         print(f"WSP: Error checking 'all_involved_npcs_defeated' condition for event {event.id}: {e}. Skipping.")
                 #                         import traceback
                 #                         print(traceback.format_exc())
                 #                         all_defeated = False # On error, condition is not met
                 #               else:
                 #                    print(f"WSP: Warning: RuleEngine lacks 'are_npcs_defeated' method for trigger in event {event.id}.")
                 #                    all_defeated = False # Cannot check without RuleEngine method
                 #
                 #           if all_defeated:
                 #               target_stage_id = rule.get('target_stage')
                 #               if isinstance(target_stage_id, str) and target_stage_id:
                 #                   # print(f"WSP: Event {event.id}, stage '{event.current_stage_id}' met 'all_involved_npcs_defeated' condition. Target stage: '{target_stage_id}'.")
                 #                   return target_stage_id


                 # - "player_input_idle_timeout": Требует TimeManager (self._time_manager) и, возможно, информацию о последнем действии игрока, хранящуюся в event.state_variables.
                 #   Пример:
                 #   elif rule_type == 'player_input_idle_timeout' and self._time_manager is not None:
                 #        idle_threshold = rule.get('threshold_minutes') # Порог бездействия в игровых минутах
                 #        if isinstance(idle_threshold, (int, float)) and idle_threshold > 0:
                 #             # Нужно найти время последнего действия игрока в этом событии
                 #             # EventActionProcessor должен сохранять это в event.state_variables под ключом 'last_player_action_game_time'.
                 #             last_player_action_time = event.state_variables.get('last_player_action_game_time')
                 #             # Время начала текущей стадии тоже может использоваться как отправная точка, если last_player_action_game_time нет.
                 #             # stage_start_time = event.state_variables.get(f'{event.current_stage_id}_start_game_time') # Если EventStageProcessor сохраняет время начала стадии
                 #             # reference_time = last_player_action_time if last_player_action_time is not None else stage_start_time
                 #             reference_time = last_player_action_time # Пока используем только время последнего действия игрока
                 #
                 #             if reference_time is not None and isinstance(reference_time, (int, float)) and self._time_manager and hasattr(self._time_manager, 'get_current_game_time'):
                 #                  current_game_time = self._time_manager.get_current_game_time()
                 #                  if current_game_time is not None and isinstance(current_game_time, (int, float)):
                 #                       idle_duration = current_game_time - reference_time
                 #                       if idle_duration >= idle_threshold:
                 #                            target_stage_id = rule.get('target_stage')
                 #                            if isinstance(target_stage_id, str) and target_stage_id:
                 #                                 # print(f"WSP: Event {event.id}, stage '{event.current_stage_id}' met 'player_input_idle_timeout' condition ({idle_duration:.2f} >= {idle_threshold:.2f} min). Target stage: '{target_stage_id}'.")
                 #                                 return target_stage_id
                 # else:
                 #      # Лог неизвестных типов правил авто-перехода
                 #      # print(f"WorldSimulationProcessor: Warning: _check_event_for_auto_transition: Unhandled auto-transition rule type '{rule_type}' in stage '{event.current_stage_id}' for event {event.id}.")


        # Если ни одно условие автоматического перехода не выполнилось после проверки всех правил
        return None # Необходимости в авто-переходе нет

    # Вспомогательный метод для получения словаря менеджеров для передачи в контекст RuleEngine
    def _get_managers_for_rule_engine_context(self) -> Dict[str, Any]:
         """
         Возвращает словарь менеджеров и процессоров, которые RuleEngine может использовать в своем контексте.
         Это включает почти все зависимости WorldSimulationProcessor.
         """
         return {
             'character_manager': self._character_manager,
             'event_manager': self._event_manager,
             'location_manager': self._location_manager,
             'rule_engine': self._rule_engine, # RuleEngine может нуждаться в себе? маловероятно
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
