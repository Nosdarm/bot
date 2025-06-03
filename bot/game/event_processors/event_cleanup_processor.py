import json # Optional
from typing import Dict, Optional, Any, List, Callable # Types, changed callable to Callable

# Import models (for type hinting or data structures)
from bot.game.models.event import Event # Needed for event object

# Import manager types needed for cleanup tasks (passed as arguments)
# Эти менеджеры выполняют фактическую очистку
from bot.game.managers.character_manager import CharacterManager # Clear statuses, remove items? Or ItemManager does it.
from bot.game.managers.location_manager import LocationManager # Restore location state?
from bot.game.managers.npc_manager import NpcManager # For despawning NPCs
from bot.game.managers.item_manager import ItemManager # For removing items created by event
from bot.game.managers.combat_manager import CombatManager # For ending combat instance
from bot.game.managers.time_manager import TimeManager # If clearing time-related event state/modifiers

# Import service types if needed
# from bot.services.openai_service import OpenAIService # For AI description of aftermath

# This class handles performing cleanup tasks when an event ends.
# Called by EventManager.end_event.
class EventCleanupProcessor:
    def __init__(self):
        pass # No state.


    # Метод очистки. Вызывается EventManager.end_event.
    # Получает ended event object и ВСЕ менеджеры/сервисы для выполнения задач.
    async def cleanup_event(self,
                            event: Event, # Объект завершенного события (для данных о том, что чистить)
                            send_message_callback: Optional[Callable] = None, # Для отправки финальных сообщений (если EM не сделал)
                            reason: str = "Завершено.", # Причина завершения

                            # !!! ПЕРЕДАЙТЕ ВСЕ МЕНЕДЖЕРЫ, НЕОБХОДИМЫЕ ДЛЯ ЗАДАЧ ОЧИСТКИ НИЖЕ !!!
                            # Должны быть аргументами в сигнатуре и проверены на Optional[None]
                            character_manager: Optional[CharacterManager] = None, # Пример
                            loc_manager: Optional[LocationManager] = None, # Пример
                            npc_manager: Optional[NpcManager] = None, # Пример: для деспавна
                            item_manager: Optional[ItemManager] = None, # Пример: для удаления предметов
                            combat_manager: Optional[CombatManager] = None, # Пример: для завершения боя
                            time_manager: Optional[TimeManager] = None, # Пример

                            # Другие сервисы/правила, если нужны для AI описания очистки
                            # openai_service: Optional[OpenAIService] = None, # Пример
                           ) -> None: # Не возвращает dict, выполняет действия и отправляет сообщения через callback.
        """
        Выполняет действия по очистке мира, связанные с завершением события.
        (деспавн NPC, удаление предметов, завершение боя, сброс статусов и т.п.).
        Не удаляет само событие из коллекции - это делает EventManager после вызова этого метода.
        """
        # event object is assumed to be valid (though ended) when called.
        event_name_for_log = getattr(event, 'name_i18n', {}).get('en', event.id) # Safe name access
        print(f"Event Cleanup Processor: Starting cleanup for event {event_name_for_log} ({event.id}). Reason: {reason}")


        # --- Выполнение Задач Очистки (Делегирование Менеджерам) ---
        # Здесь логика по перебору event.involved_entities, event.state_variables
        # и вызову методов менеджеров для фактической очистки.
        # Нужно проверять, доступен ли менеджер, прежде чем вызывать его метод.


        # Example: Деспавн NPC (требует npc_manager)
        if npc_manager:
             # Предполагаем, что временные NPC для очистки хранятся в event.state_variables['temp_npcs']
             # Или event.involved_entities['npcs'] - это список для деспавна
             npcs_to_despawn_ids = event.state_variables.get('temp_npcs', []) # ID временных NPC
             # Если этот список пустой, возможно, деспавнить нужно всех NPC, упомянутых в involved_entities['npcs']
             if not npcs_to_despawn_ids: npcs_to_despawn_ids = event.involved_entities.get('npcs', [])

             if npcs_to_despawn_ids:
                  print(f"Cleanup: Attempting to despawn NPCs {npcs_to_despawn_ids} for event {event.id}.")
                  try:
                       # await npc_manager.despawn_npcs_by_id(npcs_to_despawn_ids) # Реализовать этот метод в NpcManager!
                       print(f"Cleanup: Despawned listed NPCs for event {event.id}.")
                  except Exception as e: print(f"Error despawning NPCs for event {event.id} during cleanup: {e}")
             else: print(f"Cleanup: No NPCs listed for despawning in event {event.id}.")


        # Example: Удаление предметов (требует item_manager)
        # Предполагаем, что ID предметов для удаления хранятся в event.state_variables['temp_items']
        item_ids_to_clean = event.state_variables.get('temp_items', [])
        if item_ids_to_clean and item_manager:
            print(f"Cleanup: Attempting to clean up items {item_ids_to_clean} for event {event.id}.")
            try:
                # await item_manager.remove_items_by_id(item_ids_to_clean) # Реализовать этот метод в ItemManager!
                print(f"Cleanup: Cleaned up listed items for event {event.id}.")
            except Exception as e: print(f"Error cleaning up items for event {event.id}: {e}")
        else: print(f"Cleanup: No items listed for cleanup in event {event.id}.")


        # Example: Завершение боя (требует combat_manager)
        # Предполагаем, что ID боя хранится в event.state_variables['active_combat_id']
        active_combat_id = event.state_variables.get('active_combat_id')
        if active_combat_id and combat_manager:
            print(f"Cleanup: Attempting to end combat {active_combat_id} started by event {event.id}.")
            try:
                # await combat_manager.end_combat(active_combat_id) # Реализовать этот метод в CombatManager!
                print(f"Cleanup: Ended combat {active_combat_id}.")
            except Exception as e: print(f"Error ending combat for event {event.id}: {e}")
        else: print(f"Cleanup: No active combat listed for cleanup in event {event.id}.")


        # Example: Сброс статусов (требует character_manager)
        # if character_manager:
        #     # Нужна логика определения, какие статусы привязаны к этому событию (ID источника = event.id?)
        #     # await character_manager.clear_status_effects_by_source(event.id) # Реализовать этот метод
        #     pass

        # Example: Сброс модификаторов локации (требует loc_manager)
        # if loc_manager:
        #     # await loc_manager.clear_event_modifiers(event.id) # Реализовать этот метод
        #     pass


        # --- Опционально: Отправить финальное сообщение об Очистке (отличие от сообщения EventEnd) ---
        # Сообщение EventEnd отправляет EventManager ДО вызова cleanup.
        # Если нужно сообщение *после* очистки, его отправляем здесь, если callback и channel есть.
        # Example: if send_message_callback and event.channel_id: await send_message_callback(event.channel_id, "Следы события исчезают...")


        print(f"Cleanup process complete for event {event.id}.")
