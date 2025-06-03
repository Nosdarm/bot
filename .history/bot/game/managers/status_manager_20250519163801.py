# bot/game/managers/status_manager.py

# --- Импорты ---
import json
import uuid
import traceback
import asyncio
# ИСПРАВЛЕНИЕ: Добавляем Union
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union # Добавляем Union
# from dataclasses import dataclass, field # dataclass и field не нужны в StatusManager, если только не используются для внутренней вспомогательной структуры, но не для модели NPC.

# Импорт модели StatusEffect (для объектов эффектов)
from bot.game.models.status_effect import StatusEffect
# Импорт адаптера БД
from bot.database.sqlite_adapter import SqliteAdapter

if TYPE_CHECKING:
    # Импорты менеджеров, которые нужны StatusManager для получения данных или вызова их методов
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager # Нужен для получения текущего времени и работы с длительностью
    from bot.game.managers.character_manager import CharacterManager # Нужен для получения целевых персонажей (в process_tick, clean_up)
    from bot.game.managers.npc_manager import NpcManager # Нужен для получения целевых NPC (в process_tick, clean_up)
    from bot.game.managers.combat_manager import CombatManager # Нужен для очистки статусов при завершении боя (clean_up)
    from bot.game.managers.party_manager import PartyManager # Нужен для получения целевых групп (если статусы на группу)
    # from bot.game.managers.location_manager import LocationManager # Если статусы привязаны к локациям
    # from bot.game.event_processors.event_stage_processor import EventStageProcessor # Если статусы привязаны к стадиям событий

# Define send callback type (нужен для отправки уведомлений о статусах)
# SendToChannelCallback определен в GameManager, но его можно определить и здесь, если нужно.
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class StatusManager:
    """
    Менеджер для управления статус-эффектами.
    Отвечает за наложение, снятие, обновление длительности и применение эффектов статусов.
    Централизованно обрабатывается в мировом тике.
    """
    # Добавляем required_args для совместимости с PersistenceManager
    # NOTE: Если статус-эффекты пер-гильдийные, эти поля должны быть ["guild_id"]
    # Исходя из логов, статус-эффекты, вероятно, привязаны к сущностям, у которых есть guild_id.
    # StatusManager.save_state должен работать по guild_id, если PersistentManager вызывает его per-guild.
    # В схеме БД таблица statuses имеет guild_id.
    # Значит, StatusManager должен работать per-guild.
    required_args_for_load = ["guild_id"] # load_all_statuses должен принимать guild_id
    required_args_for_save = ["guild_id"] # save_all_statuses должен принимать guild_id
    required_args_for_rebuild = ["guild_id"] # rebuild_runtime_caches должен принимать guild_id


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
        # NOTE: Кеш статус-эффектов должен быть пер-гильдийным: {guild_id: {status_effect_id: StatusEffect_object}}
        self._status_effects: Dict[str, Dict[str, StatusEffect]] = {} # <-- ИСПРАВЛЕНО: Пер-гильдийный кеш статусов

        # NOTE: Шаблоны статусов обычно глобальные и не зависят от гильдии
        self._status_templates: Dict[str, Dict[str, Any]] = {}

        # Кеши для персистентности - тоже пер-гильдийные
        self._dirty_status_effects: Dict[str, Set[str]] = {} # {guild_id: set(status_effect_ids)}
        self._deleted_status_effects_ids: Dict[str, Set[str]] = {} # {guild_id: set(status_effect_ids)}

        # TODO: Возможно, добавить кеш {target_id: Set[status_effect_id]} для быстрого поиска статусов на сущности
        # Этот кеш также должен быть пер-гильдийным: {guild_id: {target_id: Set[status_effect_id]}}
        # self._status_effects_by_target: Dict[str, Dict[str, Set[str]]] = {}


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
        """Получить статический шаблон статуса по его типу (глобально)."""
        return self._status_templates.get(status_type)

    # ИСПРАВЛЕНИЕ: get_status_name должен принимать status_instance или status_type
    # И, возможно, template_id, если имя берется оттуда.
    # В CharacterViewService вызывается get_status_display_name с status_instance=status_instance
    def get_status_display_name(self, status_instance: StatusEffect) -> str:
         """Получить отображаемое имя статус-эффекта по его объекту."""
         if not isinstance(status_instance, StatusEffect):
              return "Неизвестный статус"
         # Ищем шаблон по status_type в объекте экземпляра
         tpl = self.get_status_template(status_instance.status_type)
         name = getattr(tpl, 'name', status_instance.status_type) if tpl else status_instance.status_type

         desc_parts = [name]
         if status_instance.duration is not None:
             # TODO: Форматирование длительности (например, минуты/секунды)
             desc_parts.append(f"({status_instance.duration:.1f} ост.)") # Осталось длительности

         # TODO: Добавить отображение стаков, если есть (status_instance.stacks)

         return " ".join(desc_parts)


    # ИСПРАВЛЕНИЕ: get_status_effect должен принимать guild_id.
    def get_status_effect(self, guild_id: str, status_effect_id: str) -> Optional[StatusEffect]:
        """Получить объект статус-эффекта по его ID для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Получаем из пер-гильдийного кеша
        guild_statuses = self._status_effects.get(guild_id_str)
        if guild_statuses:
             return guild_statuses.get(status_effect_id)
        return None # Гильдия или статус-эффект не найдены


    # TODO: Реализовать get_status_effects_on_target(guild_id, target_id, target_type) для получения всех статусов на сущности

    # TODO: Реализовать get_status_effect_instance(status_effect_id) - возможно, просто синоним get_status_effect, но без guild_id?
    # Если ID статус-эффекта глобально уникален, то guild_id не нужен в этой специфической функции.
    # Если ID уникален per-guild, то эта функция должна принимать guild_id.
    # В схеме БД statuses.id PRIMARY KEY, что подразумевает глобальную уникальность ID экземпляра статуса.
    # Значит, get_status_effect_instance должен искать по глобальному кешу или по всем пер-гильдийным кешам.
    # Для простоты, пока сделаем, что get_status_effect - основной метод для получения по ID+guild_id.
    # get_status_effect_instance, если он нужен, должен работать по guild_id.


    # ИСПРАВЛЕНИЕ: add_status_effect_to_entity должен принимать guild_id и **kwargs.
    async def add_status_effect_to_entity(self,
                                          target_id: str,
                                          target_type: str,
                                          status_type: str,
                                          guild_id: str, # <-- ДОБАВЛЕН guild_id
                                          duration: Optional[Any] = None, # Any, т.к. может прийти str ('permanent') или число
                                          source_id: Optional[str] = None,
                                          **kwargs: Any # Принимаем весь контекст
                                         ) -> Optional[str]:
        """
        Налагает новый статус-эффект на сущность для определенной гильдии.
        Сохраняет его в БД и добавляет в кеш активных статусов.
        """
        guild_id_str = str(guild_id)
        print(f"StatusManager: Adding status '{status_type}' to {target_type} {target_id} for guild {guild_id_str}...")

        if self._db_adapter is None:
             print(f"StatusManager: Error adding status for guild {guild_id_str}: Database adapter is not available.")
             return None

        # TODO: Валидация target_id существует ли сущность (через Character/NPC/Party Manager из kwargs)
        # target_entity = None
        # if target_type == 'Character':
        #     char_mgr = kwargs.get('character_manager', self._character_manager)
        #     if char_mgr: target_entity = char_mgr.get_character(guild_id_str, target_id)
        # ... и т.д. для NPC, Party

        # TODO: Валидация status_type существует ли шаблон статуса (через get_status_template)

        # Обработка длительности (число или 'permanent')
        resolved_duration: Optional[float] = None
        if duration is not None:
            if isinstance(duration, (int, float)):
                resolved_duration = float(duration)
            elif isinstance(duration, str) and duration.lower() == 'permanent':
                resolved_duration = None # Null in DB for permanent
            else:
                 print(f"StatusManager: Warning: Bad duration format for status '{status_type}' on {target_type} {target_id}: '{duration}'. Expected number or 'permanent'.")
                 # Решите, что делать: игнорировать длительность, сделать временным по умолчанию, рейзить ошибку.
                 # Пока сделаем временным по умолчанию (например, 1 тик?), или просто null?
                 # Оставим None, что означает постоянный, если формат неправильный - небезопасно.
                 # Давайте сделаем duration обязательным и числовым или 'permanent'.
                 # Сейчас просто логируем и оставляем resolved_duration как None (постоянный).


        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        time_mgr = kwargs.get('time_manager', self._time_manager)

        applied_at = None
        if time_mgr and hasattr(time_mgr, 'get_current_game_time'):
            # Используем пер-гильдийное время
            applied_at = time_mgr.get_current_game_time(guild_id_str) # Убедитесь в сигнатуре TimeManager


        try:
            new_id = str(uuid.uuid4())

            data: Dict[str, Any] = { # Явная аннотация словаря
                'id': new_id,
                'status_type': status_type,
                'target_id': target_id,
                'target_type': target_type,
                'duration': resolved_duration, # None для постоянного
                'applied_at': applied_at, # None если time_manager недоступен?
                'source_id': source_id,
                'guild_id': guild_id_str, # <-- СОХРАНЯЕМ guild_id в данных статуса
                'state_variables': {}, # Инстанс-специфичные переменные статуса
            }

            # TODO: Возможно, вызвать RuleEngine для "on_apply" эффектов
            # if rule_engine and hasattr(rule_engine, 'apply_status_on_apply'):
            #      target_entity = # Получить целевую сущность из менеджера через kwargs
            #      if target_entity:
            #           await rule_engine.apply_status_on_apply(
            #               status_effect_data=data, # Или объект StatusEffect?
            #               target_entity=target_entity,
            #               **kwargs # Передаем контекст
            #           )

            # Создаем объект StatusEffect из данных
            eff = StatusEffect.from_dict(data)

            # --- Сохранение в БД ---
            if self._db_adapter:
                 # TODO: Убедитесь, что SQL запрос соответствует ВСЕМ полям StatusEffect модели, включая guild_id
                 sql = '''
                     INSERT INTO statuses (id, status_type, target_id, target_type, duration, applied_at, source_id, state_variables, guild_id)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                     -- TODO: Добавить другие колонки
                 '''
                 params = (
                     eff.id, eff.status_type, eff.target_id, eff.target_type,
                     eff.duration, eff.applied_at, eff.source_id,
                     json.dumps(eff.state_variables),
                     eff.guild_id # <-- Параметр guild_id
                     # TODO: Добавить другие параметры
                 )
                 await self._db_adapter.execute(sql, params)
                 # execute уже коммитит
                 print(f"StatusManager: Status {eff.id} added and saved to DB for guild {guild_id_str}.")
            else:
                 print(f"StatusManager: No DB adapter. Simulating save for status {eff.id} for guild {guild_id_str}.")


            # --- Добавление в кеш после успешного сохранения ---
            # Добавляем в пер-гильдийный кеш статусов
            self._status_effects.setdefault(guild_id_str, {})[eff.id] = eff
            # TODO: Добавить в пер-гильдийный кеш {target_id: Set[status_effect_id]} если он используется
            # self._status_effects_by_target.setdefault(guild_id_str, {}).setdefault(target_id, set()).add(eff.id)


            # TODO: Пометить целевую сущность dirty, если она имеет атрибут status_effects,
            # который ссылается на список ID статусов.
            # Эту логику лучше делать в clean_up_for_* методах менеджеров сущностей,
            # которые вызываются здесь в process_tick или remove_status_effect.

            self._dirty_status_effects.setdefault(guild_id_str, set()).add(eff.id) # Помечаем статус dirty для этой гильдии

            print(f"StatusManager: Status {eff.id} added to cache for guild {guild_id_str}.")

            return eff.id

        except Exception as e:
            print(f"StatusManager: ❌ Error adding or saving status effect for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # rollback уже в execute
            return None

    # ИСПРАВЛЕНИЕ: remove_status_effect должен принимать guild_id.
    async def remove_status_effect(self, status_effect_id: str, guild_id: str, **kwargs: Any) -> Optional[str]:
        """
        Удаляет статус-эффект по ID из кеша и БД для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        status_effect_id_str = str(status_effect_id)
        print(f"StatusManager: Removing status {status_effect_id_str} for guild {guild_id_str}...")

        # Получаем объект статус-эффекта из пер-гильдийного кеша
        eff = self.get_status_effect(guild_id_str, status_effect_id_str)
        if not eff:
            print(f"StatusManager: Warning: Attempted to remove non-existent or inactive status {status_effect_id_str} for guild {guild_id_str} (not found in cache).")
             # TODO: Если не нашли в кеше, но он в _deleted_status_effects_ids для этой гильдии, просто логируем.
            # Если его нет нигде, логируем Warning.
            pass # Продолжаем попытку удаления из БД, на случай если он там есть, но нет в кеше.


        # TODO: Возможно, вызвать RuleEngine для "on_remove" эффектов
        # if rule_engine and hasattr(rule_engine, 'apply_status_on_remove'):
        #     target_entity = # Получить целевую сущность из менеджера через kwargs или eff.target_id
        #     if target_entity and eff:
        #          await rule_engine.apply_status_on_remove(
        #              status_effect=eff,
        #              target_entity=target_entity,
        #              **kwargs # Передаем контекст
        #          )


        try:
            # --- Удаляем из БД ---
            if self._db_adapter:
                # ИСПРАВЛЕНИЕ: Добавляем фильтр по guild_id в SQL DELETE
                sql = 'DELETE FROM statuses WHERE id = ? AND guild_id = ?'
                await self._db_adapter.execute(sql, (status_effect_id_str, guild_id_str))
                # execute уже коммитит
                print(f"StatusManager: Status {status_effect_id_str} deleted from DB for guild {guild_id_str}.")
            else:
                print(f"StatusManager: No DB adapter. Simulating delete from DB for status {status_effect_id_str} for guild {guild_id_str}.")

            # --- Удаляем из кеша ---
            # Удаляем из пер-гильдийного кеша
            guild_statuses_cache = self._status_effects.get(guild_id_str)
            if guild_statuses_cache: # Проверяем, что кеш для гильдии существует
                 guild_statuses_cache.pop(status_effect_id_str, None) # Удаляем по ID
                 # Если после удаления кеш для гильдии опустел, можно удалить и сам ключ гильдии из self._status_effects
                 if not guild_statuses_cache:
                      self._status_effects.pop(guild_id_str, None)

            # TODO: Удалить из пер-гильдийного кеша {target_id: Set[status_effect_id]} если он используется
            # if self._status_effects_by_target.get(guild_id_str) and eff:
            #     target_statuses = self._status_effects_by_target[guild_id_str].get(eff.target_id)
            #     if target_statuses and status_effect_id_str in target_statuses:
            #          target_statuses.discard(status_effect_id_str)
            #          if not target_statuses:
            #               self._status_effects_by_target[guild_id_str].pop(eff.target_id)
            #               if not self._status_effects_by_target[guild_id_str]:
            #                    self._status_effects_by_target.pop(guild_id_str, None)


            # TODO: Пометить целевую сущность dirty, чтобы удалить ID статуса из ее списка status_effects
            # Это должно делаться в clean_up_for_* методах менеджеров сущностей,
            # которые вызываются здесь в remove_status_effect.

            # Удаляем из пер-гильдийных персистентных кешей
            self._dirty_status_effects.get(guild_id_str, set()).discard(status_effect_id_str) # Удаляем из dirty
            self._deleted_status_effects_ids.setdefault(guild_id_str, set()).add(status_effect_id_str) # Добавляем в deleted

            print(f"StatusManager: Status {status_effect_id_str} removed from cache and marked for deletion for guild {guild_id_str}.")

            return status_effect_id_str

        except Exception as e:
            print(f"StatusManager: ❌ Error removing status {status_effect_id_str} for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # rollback уже в execute


    # Метод обработки тика (используется WorldSimulationProcessor)
    # ИСПРАВЛЕНИЕ: Добавляем guild_id и **kwargs к сигнатуре
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        """
        Обрабатывает тик игрового времени для статус-эффектов определенной гильдии.
        Обновляет длительность активных статусов, применяет периодические эффекты и удаляет истекшие.
        Принимает game_time_delta и менеджеры/сервисы через kwargs.
        """
        # print(f"StatusManager: Processing tick for guild {guild_id} with delta: {game_time_delta}") # Debug print

        guild_id_str = str(guild_id)

        # Получаем пер-гильдийный кеш статусов
        guild_statuses_cache = self._status_effects.get(guild_id_str, {})

        if not guild_statuses_cache:
             # print(f"StatusManager: No active statuses in cache for guild {guild_id_str} to process.") # Too noisy
             return # Нет статусов для этой гильдии в кеше


        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        char_mgr = kwargs.get('character_manager', self._character_manager)
        npc_mgr  = kwargs.get('npc_manager', self._npc_manager)
        # TODO: Получить другие менеджеры, если нужны для apply_status_periodic_effects (PartyManager?)


        to_remove_ids: List[str] = [] # Список ID статусов для удаления после итерации

        # Проходим по всем активным статус-эффектам в кеше ДЛЯ ЭТОЙ ГИЛЬДИИ
        # Итерируем по копии values(), т.к. статус может быть помечен на удаление
        for eff_id, eff in list(guild_statuses_cache.items()):
            # eff - это объект StatusEffect
            if not isinstance(eff, StatusEffect):
                 print(f"StatusManager: Warning: Invalid object in cache for guild {guild_id_str}, ID {eff_id}. Expected StatusEffect, got {type(eff).__name__}. Marking for removal.")
                 to_remove_ids.append(eff_id)
                 continue

            try:
                # 1. Обновление длительности (если не постоянный)
                if eff.duration is not None: # Если длительность задана (не постоянный статус)
                    if not isinstance(eff.duration, (int, float)):
                         print(f"StatusManager: Warning: Invalid duration type for status {eff_id} ('{eff.status_type}') in guild {guild_id_str}: {eff.duration}. Expected number. Marking for removal.")
                         to_remove_ids.append(eff_id)
                         continue # Пропускаем этот статус

                    eff.duration -= game_time_delta # Уменьшаем оставшуюся длительность
                    self._dirty_status_effects.setdefault(guild_id_str, set()).add(eff_id) # Помечаем как измененный

                    if eff.duration <= 0: # Если длительность истекла
                        # print(f"StatusManager: Status {eff_id} ('{eff.status_type}') for {eff.target_type} {eff.target_id} in guild {guild_id_str} duration ended.") # Debug
                        to_remove_ids.append(eff_id) # Маркируем для удаления
                        continue # Переходим к следующему статусу, не применяя периодический эффект (он уже закончился)


                # 2. Применение периодических эффектов (если есть и статус не истек)
                tpl = self.get_status_template(eff.status_type)

                # RuleEngine.apply_status_periodic_effects должен быть асинхронным и принимать status_effect, target_entity, game_time_delta, context
                if tpl and rule_engine and hasattr(rule_engine, 'apply_status_periodic_effects'):
                    # Нужно получить целевую сущность по target_id и target_type
                    target_entity = None
                    if eff.target_type == 'Character' and char_mgr:
                         target_entity = char_mgr.get_character(guild_id_str, eff.target_id) # Получаем персонажа по guild_id

                    elif eff.target_type == 'NPC' and npc_mgr:
                         target_entity = npc_mgr.get_npc(guild_id_str, eff.target_id) # Получаем NPC по guild_id

                    # TODO: Получить целевую сущность для Party, Location и т.д. если статусы могут быть на них
                    # elif eff.target_type == 'Party' and party_mgr:
                    #     target_entity = party_mgr.get_party(guild_id_str, eff.target_id)
                    # elif eff.target_type == 'Location' and loc_manager:
                    #     target_entity = loc_manager.get_location(guild_id_str, eff.target_id)

                    if target_entity: # Если целевая сущность найдена
                        # print(f"StatusManager: Applying periodic effect for status {eff_id} on {eff.target_type} {eff.target_id} in guild {guild_id_str}...") # Debug
                        await rule_engine.apply_status_periodic_effects(
                            status_effect=eff, # Передаем объект статус-эффекта
                            target_entity=target_entity, # Передаем объект целевой сущности
                            game_time_delta=game_time_delta,
                            **kwargs # Передаем ВСЕ менеджеры/сервисы из process_tick (контекст WSP)
                        )
                        # Результат apply_status_periodic_effects может включать изменение состояния сущности,
                        # менеджер сущности должен пометить ее dirty.
                    # else:
                        # print(f"StatusManager: Warning: Target entity {eff.target_type} {eff.target_id} for status {eff_id} not found in guild {guild_id_str}. Cannot apply periodic effect.") # Не всегда ошибка, сущность может быть удалена

                # else:
                    # print(f"StatusManager: Warning: RuleEngine or 'apply_status_periodic_effects' not available for status type '{eff.status_type}' or template not found for status {eff_id} in guild {guild_id_str}.") # Слишком шумно?


            except Exception as e:
                print(f"StatusManager: ❌ Error in tick processing for status {eff_id} ('{eff.status_type}') on {eff.target_type} {eff.target_id} for guild {guild_id_str}: {e}")
                import traceback
                print(traceback.format_exc())
                to_remove_ids.append(eff_id) # Маркируем на удаление при ошибке обработки


        # --- Удаление истекших статусов ---
        # Проходим по списку ID статусов, которые нужно удалить
        for status_id_to_remove in set(to_remove_ids): # Используем set для уникальности
             # remove_status_effect принимает status_id, guild_id и context
             # context содержит менеджеры и т.д.
             await self.remove_status_effect(status_id_to_remove, guild_id_str, **kwargs) # Удаляем, передавая guild_id и контекст


        # print(f"StatusManager: Tick processing finished for guild {guild_id_str}.")


    # --- Методы персистентности (Используются PersistenceManager'ом) ---

    # ИСПРАВЛЕНИЕ: save_state должен принимать guild_id и **kwargs
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """
        Сохраняет состояние StatusManager (активные статус-эффекты) для определенной гильдии в БД.
        """
        print(f"StatusManager: Saving state for guild {guild_id}...")
        if self._db_adapter is None:
             print(f"StatusManager: Database adapter is not available. Skipping save for guild {guild_id}.")
             return

        guild_id_str = str(guild_id)

        try:
            # Получаем пер-гильдийные персистентные кеши
            dirty_status_ids_for_guild_set = self._dirty_status_effects.get(guild_id_str, set()).copy() # Рабочая копия Set
            deleted_status_ids_for_guild_set = self._deleted_status_effects_ids.get(guild_id_str, set()).copy() # Рабочая копия Set

            if not dirty_status_ids_for_guild_set and not deleted_status_ids_for_guild_set:
                 # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем пер-гильдийные dirty/deleted сеты
                 self._dirty_status_effects.pop(guild_id_str, None)
                 self._deleted_status_effects_ids.pop(guild_id_str, None)
                 # print(f"StatusManager: No dirty or deleted statuses to save for guild {guild_id_str}.") # Debug
                 return

            print(f"StatusManager: Saving {len(dirty_status_ids_for_guild_set)} dirty and {len(deleted_status_ids_for_guild_set)} deleted statuses for guild {guild_id_str}.")

            # --- Удаляем помеченные для удаления статус-эффекты для этой гильдии ---
            if deleted_status_ids_for_guild_set:
                ids_to_delete = list(deleted_status_ids_for_guild_set)
                placeholders = ','.join(['?'] * len(ids_to_delete))
                # ИСПРАВЛЕНИЕ: Добавляем фильтр по guild_id в SQL DELETE
                sql_del = f"DELETE FROM statuses WHERE id IN ({placeholders}) AND guild_id = ?" # Filter by guild_id LAST
                # Параметры: сначала ID'ы, затем guild_id
                params_del = tuple(ids_to_delete) + (guild_id_str,)

                await self._db_adapter.execute(sql_del, params_del)
                # execute уже коммитит
                print(f"StatusManager: Deleted {len(ids_to_delete)} statuses from DB for guild {guild_id_str}.")
                # ИСПРАВЛЕНИЕ: Очищаем deleted set для этой гильдии после успешного удаления
                self._deleted_status_effects_ids.pop(guild_id_str, None)


            # --- Обновляем или вставляем измененные статус-эффекты для этой гильдии ---
            # Получаем пер-гильдийный кеш статусов
            guild_statuses_cache = self._status_effects.get(guild_id_str, {})

            # Фильтруем dirty_status_ids на те, что все еще существуют в пер-гильдийном кеше
            statuses_to_save: List[StatusEffect] = []
            upserted_status_ids: Set[str] = set() # Track IDs successfully prepared

            for sid in list(dirty_status_ids_for_guild_set):
                 eff = guild_statuses_cache.get(sid) # Получаем из кеша гильдии
                 if eff and isinstance(eff, StatusEffect) and getattr(eff, 'guild_id', None) == guild_id_str:
                      statuses_to_save.append(eff)
                 else:
                      # Если статус не найден в кеше или не принадлежит гильдии - удаляем из dirty set
                      print(f"StatusManager: Warning: Dirty status {sid} not found in cache or mismatched guild ({getattr(eff, 'guild_id', 'N/A')} vs {guild_id_str}). Removing from dirty set.")
                      self._dirty_status_effects.get(guild_id_str, set()).discard(sid)


            if statuses_to_save:
                # TODO: Убедитесь, что SQL запрос соответствует ВСЕМ полям StatusEffect модели, включая guild_id
                sql_upsert = '''
                    INSERT OR REPLACE INTO statuses
                    (id, status_type, target_id, target_type, duration, applied_at, source_id, state_variables, guild_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    -- TODO: Добавить другие колонки в SQL
                '''
                data_to_upsert = []
                for eff in statuses_to_save:
                    # Убедимся, что все нужные атрибуты существуют и имеют правильный тип
                    if not isinstance(eff, StatusEffect) or not eff.id or not eff.status_type or not eff.target_id or not eff.target_type or not eff.guild_id:
                        print(f"StatusManager: Warning: Skipping upsert for invalid StatusEffect object: {eff}. Missing mandatory attributes.")
                        continue

                    sv_json = json.dumps(getattr(eff, 'state_variables', {})) # Safely get state_variables

                    data_to_upsert.append((
                        eff.id, eff.status_type, eff.target_id, eff.target_type,
                        eff.duration, eff.applied_at, eff.source_id, # duration и applied_at могут быть None или float
                        sv_json,
                        eff.guild_id # <-- Параметр guild_id из объекта
                        # TODO: Добавить другие параметры в кортеж
                    ))
                    upserted_status_ids.add(eff.id) # Track ID

                if data_to_upsert: # Только если есть что сохранять
                     await self._db_adapter.execute_many(sql_upsert, data_to_upsert)
                     # execute_many коммитит сам
                     print(f"StatusManager: Successfully upserted {len(data_to_upsert)} statuses for guild {guild_id_str}.")
                     # ИСПРАВЛЕНИЕ: Очищаем dirty set для этой гильдии только для успешно сохраненных ID
                     self._dirty_status_effects.get(guild_id_str, set()).difference_update(upserted_status_ids)
                     # Если после очистки set пуст, удаляем ключ гильдии
                     if guild_id_str in self._dirty_status_effects and not self._dirty_status_effects[guild_id_str]:
                          self._dirty_status_effects.pop(guild_id_str)


            # Note: При использовании execute и execute_many с авто-коммитом в каждом вызове,
            # нет необходимости в явном self._conn.commit() в конце save_state.

            print(f"StatusManager: Successfully saved state for guild {guild_id_str}.")

        except Exception as e:
            print(f"StatusManager: ❌ Error during saving state for guild {guild_id_str}: {e}")
            traceback.print_exc()
            # При ошибке в execute_many, он сам откатит свою транзакцию.
            # Если ошибка в первом execute (delete), только он откатится.
            # Явный rollback в конце save_state может откатить предыдущие операции,
            # если они не были закоммичены (но execute/execute_many авто-коммитят).
            # Если нужна атомарность всего save_state, нужно использовать одну транзакцию.
            # Для простоты пока оставим как есть с авто-коммитом по операциям.


    # ИСПРАВЛЕНИЕ: load_state должен принимать guild_id и **kwargs
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """
        Загружает состояние StatusManager (активные статус-эффекты) для определенной гильдии из БД в кеш.
        """
        print(f"StatusManager: Loading state for guild {guild_id}...")
        guild_id_str = str(guild_id)

        if self._db_adapter is None:
             print(f"StatusManager: Database adapter is not available. Loading placeholder state or leaving default for guild {guild_id_str}.")
             # Очищаем или инициализируем кеши для этой гильдии
             self._status_effects.pop(guild_id_str, None)
             self._status_effects[guild_id_str] = {}
             self._dirty_status_effects.pop(guild_id_str, None)
             self._deleted_status_effects_ids.pop(guild_id_str, None)
             # TODO: Очистить/инициализировать пер-гильдийный кеш по цели, если используется
             # self._status_effects_by_target.pop(guild_id_str, None)
             # self._status_effects_by_target[guild_id_str] = {}

             print(f"StatusManager: State is default after load (no DB adapter) for guild {guild_id_str}. Status Effects = 0.")
             return

        try:
            # Очищаем кеши ДЛЯ ЭТОЙ ГИЛЬДИИ перед загрузкой
            self._status_effects.pop(guild_id_str, None)
            self._status_effects[guild_id_str] = {} # Создаем пустой кеш для этой гильдии

            self._dirty_status_effects.pop(guild_id_str, None)
            self._deleted_status_effects_ids.pop(guild_id_str, None)
            # TODO: Очистить/инициализировать пер-гильдийный кеш по цели, если используется
            # self._status_effects_by_target.pop(guild_id_str, None)
            # self._status_effects_by_target[guild_id_str] = {}


            # Выбираем ВСЕ статус-эффекты ТОЛЬКО для этой гильдии
            # TODO: Убедитесь, что SELECT соответствует ВСЕМ колонкам таблицы statuses, включая guild_id
            sql_statuses = '''
                SELECT id, status_type, target_id, target_type, duration, applied_at, source_id, state_variables, guild_id
                FROM statuses WHERE guild_id = ?
            '''
            rows_statuses = await self._db_adapter.fetchall(sql_statuses, (guild_id_str,))

            if rows_statuses:
                 print(f"StatusManager: Found {len(rows_statuses)} statuses in DB for guild {guild_id_str}.")

                 # Получаем текущее игровое время для этой гильдии (нужно для расчета истекшей длительности при загрузке)
                 # Время должно быть загружено TimeManager'ом перед StatusManager'ом или передано в kwargs.
                 time_mgr = kwargs.get('time_manager', self._time_manager) # TimeManager из контекста
                 current_game_time_for_guild = None
                 if time_mgr and hasattr(time_mgr, 'get_current_game_time'):
                      current_game_time_for_guild = time_mgr.get_current_game_time(guild_id_str) # Убедитесь в сигнатуре TimeManager

                 loaded_count = 0
                 for row in rows_statuses:
                      try:
                           # Создаем словарь данных статуса из строки БД
                           row_dict = dict(row)

                           # TODO: Убедитесь, что все нужные поля присутствуют и имеют правильные типы (особенно после json.loads)
                           status_id = row_dict.get('id')
                           if status_id is None:
                                print(f"StatusManager: Warning: Skipping status row with missing ID for guild {guild_id_str}: {row_dict}.")
                                continue # Пропускаем строку без ID

                           # Преобразуем JSON и булевы
                           row_dict['state_variables'] = json.loads(row_dict.get('state_variables') or '{}') if isinstance(row_dict.get('state_variables'), (str, bytes)) else {}
                           # is_active уже фильтруется в SQL, но его можно загрузить, если нужно.
                           # row_dict['is_active'] = bool(row_dict.get('is_active', 0))

                           # duration и applied_at могут быть NULL в БД (None в Python) или REAL (float)
                           row_dict['duration'] = float(row_dict['duration']) if row_dict['duration'] is not None else None
                           row_dict['applied_at'] = float(row_dict['applied_at']) if row_dict['applied_at'] is not None else None

                           # Загружаем guild_id
                           loaded_row_guild_id = row_dict.get('guild_id')
                           if loaded_row_guild_id is None or str(loaded_row_guild_id) != guild_id_str:
                                print(f"StatusManager: Warning: Skipping status {status_id} with mismatched guild_id ({loaded_row_guild_id}) for guild {guild_id_str}. Data: {row_dict}.")
                                continue # Пропускаем строку с неправильной гильдией

                           # Создаем объект StatusEffect из данных
                           status_instance = StatusEffect.from_dict(row_dict)

                           # Проверка на истекшую длительность при загрузке (для временных статусов)
                           # Если время игры доступно
                           if status_instance.duration is not None and status_instance.applied_at is not None and current_game_time_for_guild is not None:
                                elapsed = current_game_time_for_guild - status_instance.applied_at
                                if elapsed > 0:
                                    status_instance.duration -= elapsed # Обновляем длительность
                                    if status_instance.duration <= 0:
                                        # Если длительность истекла при загрузке - помечаем для удаления
                                        self._deleted_status_effects_ids.setdefault(guild_id_str, set()).add(status_instance.id)
                                        # print(f"StatusManager: Status {status_instance.id} for guild {guild_id_str} expired upon loading. Marked for deletion.") # Debug
                                        continue # Пропускаем добавление в кеш

                           # Если статус не истек при загрузке - добавляем в кеш
                           self._status_effects.setdefault(guild_id_str, {})[status_instance.id] = status_instance
                           loaded_count += 1

                           # TODO: Добавить в пер-гильдийный кеш по цели, если используется
                           # self._status_effects_by_target.setdefault(guild_id_str, {}).setdefault(status_instance.target_id, set()).add(status_instance.id)


                      except (json.JSONDecodeError, ValueError, TypeError) as e:
                           print(f"StatusManager: ❌ Error decoding or converting status data from DB for ID {row.get('id', 'Unknown')} for guild {guild_id_str}: {e}. Skipping status.")
                           import traceback
                           print(traceback.format_exc())
                      except Exception as e: # Ловим другие ошибки при обработке строки
                           print(f"StatusManager: ❌ Error processing status row for ID {row.get('id', 'Unknown')} for guild {guild_id_str}: {e}. Skipping status.")
                           import traceback
                           print(traceback.format_exc())


                 print(f"StatusManager: Successfully loaded {loaded_count} active statuses into cache for guild {guild_id_str}. {len(rows_statuses) - loaded_count} expired or failed to load.")

            else:
                 print(f"StatusManager: No active statuses found in DB for guild {guild_id_str}.")


        except Exception as e:
            print(f"StatusManager: ❌ CRITICAL ERROR during loading state for guild {guild_id_str} from DB: {e}")
            import traceback
            print(traceback.format_exc())
            print(f"StatusManager: Loading failed for guild {guild_id_str}. State for this guild might be incomplete.")
            # Оставляем кеши для этой гильдии в том состоянии, в котором они оказались (скорее всего пустые или частично заполненные)


    # --- Метод перестройки кешей (обычно простая заглушка для StatusManager) ---
    # ИСПРАВЛЕНИЕ: Добавляем guild_id и **kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         """
         Перестраивает внутренние кеши StatusManager после загрузки для определенной гильдии.
         """
         print(f"StatusManager: Simulating rebuilding runtime caches for guild {guild_id}.")
         # TODO: Если используется _status_effects_by_target, его нужно перестроить здесь
         # based on the loaded statuses in self._status_effects[guild_id].
         # guild_id_str = str(guild_id)
         # self._status_effects_by_target.pop(guild_id_str, None)
         # self._status_effects_by_target[guild_id_str] = {}
         # if guild_id_str in self._status_effects:
         #      for status_id, status_instance in self._status_effects[guild_id_str].items():
         #           if isinstance(status_instance, StatusEffect) and status_instance.target_id:
         #                self._status_effects_by_target[guild_id_str].setdefault(status_instance.target_id, set()).add(status_id)

         print(f"StatusManager: Runtime caches rebuilt for guild {guild_id}.")

    # TODO: Добавьте clean_up_for_character(character_id, context), clean_up_for_npc, clean_up_for_party и т.д.
    # async def clean_up_for_character(self, character_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
    #      """Удаляет все статус-эффекты с персонажа."""
    #      guild_id = context.get('guild_id')
    #      if guild_id is None:
    #           print(f"StatusManager: Error in clean_up_for_character: Missing guild_id in context for character {character_id}.")
    #           return
    #      guild_id_str = str(guild_id)
    #      # Получаем все статусы на этой цели для этой гильдии
    #      # Requires get_status_effects_on_target method, or iterate cache
    #      statuses_on_target_ids = [ sid for sid, s in self._status_effects.get(guild_id_str, {}).items()
    #                                if isinstance(s, StatusEffect) and s.target_id == character_id and s.target_type == 'Character']
    #      for status_id in statuses_on_target_ids:
    #           await self.remove_status_effect(status_id, guild_id_str, **context) # Удаляем каждый статус

    # TODO: Добавьте remove_status_effects_by_event_id(event_id, guild_id, context)

# Конец класса StatusManager
