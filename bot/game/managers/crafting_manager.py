# bot/game/managers/crafting_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import time # Added for timestamp in crafting task
# Импорт базовых типов
# ИСПРАВЛЕНИЕ: Импортируем необходимые типы из typing
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union # Added Union

# Импорт модели CraftingQueue (нужен при runtime для кеша и возвращаемых типов)
# TODO: Create a CraftingQueue model if you don't have one.
# For now, we'll just use Dict[str, Any] for queue items and assume the queue itself is a list of these.
# If you create a model like bot.game.models.crafting_queue.CraftingQueue, import it here.
# from bot.game.models.crafting_queue import CraftingQueue # Example import

# Адаптер БД
from bot.database.sqlite_adapter import SqliteAdapter

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins


if TYPE_CHECKING:
    # Чтобы не создавать циклических импортов, импортируем эти типы только для подсказок
    # Используем строковые литералы ("ClassName")
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager
    # Add other managers/processors that might be in context kwargs
    # from bot.game.managers.location_manager import LocationManager
    # from bot.game.managers.combat_manager import CombatManager
    # from bot.game.managers.status_manager import StatusManager
    # from bot.game.managers.party_manager import PartyManager


print("--- CraftingManager module starts loading ---") # Отладочный вывод в начале файла

class CraftingManager:
    """
    Менеджер для управления системой крафтинга:
    рецепты, очереди крафтинга, обработка задач.
    Работает на основе guild_id для многогильдийной поддержки.
    """
    # Required args для PersistenceManager
    # Судя по схеме БД, очереди привязаны к entity_id (характеру/NPC) и guild_id.
    # PersistenceManager должен загружать/сохранять очереди per-guild.
    required_args_for_load: List[str] = ["guild_id"] # Загрузка per-guild
    required_args_for_save: List[str] = ["guild_id"] # Сохранение per-guild
    # ИСПРАВЛЕНИЕ: Добавляем guild_id для rebuild_runtime_caches
    required_args_for_rebuild: List[str] = ["guild_id"] # Rebuild per-guild


    # --- Class-Level Attribute Annotations ---
    # Статические рецепты крафтинга: {guild_id: {recipe_id: data_dict}}
    # ИСПРАВЛЕНИЕ: Рецепты должны быть per-guild
    _crafting_recipes: Dict[str, Dict[str, Dict[str, Any]]]

    # Кеш активных очередей крафтинга: {guild_id: {entity_id: queue_data}}
    # queue_data is a dict potentially with 'queue' (List[Dict]) and 'state_variables' (Dict).
    # The entity_id is the PRIMARY KEY from the DB table crafting_queues.
    # ИСПРАВЛЕНИЕ: Кеш очередей крафтинга должен быть per-guild
    _crafting_queues: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {entity_id: queue_data_dict}}

    # Изменённые очереди, подлежащие записи: {guild_id: set(entity_ids)}
    # ИСПРАВЛЕНИЕ: dirty queues также per-guild
    _dirty_crafting_queues: Dict[str, Set[str]] # {guild_id: {entity_id}}

    # Удалённые очереди, подлежащие удалению из БД: {guild_id: set(entity_ids)}
    # ИСПРАВЛЕНИЕ: deleted queue ids также per-guild
    _deleted_crafting_queue_ids: Dict[str, Set[str]] # {guild_id: {entity_id}}


    def __init__(
        self,
        # Используем строковые литералы для всех опциональных зависимостей
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None, # Use string literal! Needs to create/consume items
        rule_engine: Optional["RuleEngine"] = None, # Use string literal! Needs to process recipes, requirements, results
        time_manager: Optional["TimeManager"] = None, # Use string literal! Needs for task duration/completion time
        character_manager: Optional["CharacterManager"] = None, # Use string literal! Needs to check character inventory/stats
        npc_manager: Optional["NpcManager"] = None, # Use string literal! Needs to check NPC inventory/stats
        # Add other injected dependencies here with Optional and string literals
    ):
        print("Initializing CraftingManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # Инжектированные зависимости
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager


        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        # Статические рецепты: {guild_id: {recipe_id: data_dict}}
        self._crafting_recipes = {} # Инициализируем как пустой dict

        # Кеш активных очередей крафтинга: {guild_id: {entity_id: queue_data_dict}}
        self._crafting_queues = {} # Инициализируем как пустой dict

        # Для оптимизации персистенции
        self._dirty_crafting_queues = {} # Инициализируем как пустой dict
        self._deleted_crafting_queue_ids = {} # Инициализируем как пустой dict

        # Загружаем статические шаблоны НЕ здесь. Загрузка per-guild происходит в load_state.
        # _load_crafting_recipes() # Remove this call from __init__

        print("CraftingManager initialized.\n")

    # load_static_recipes method (not called by PM directly)
    # This method will be called from load_state
    def load_static_recipes(self, guild_id: str) -> None:
        """(Пример) Загружает статические рецепты для определенной гильдии из настроек или файлов."""
        guild_id_str = str(guild_id)
        print(f"CraftingManager: Loading crafting recipes for guild {guild_id_str}...")

        # Очищаем кеш рецептов для этой гильдии перед загрузкой
        self._crafting_recipes.pop(guild_id_str, None)
        guild_recipes_cache = self._crafting_recipes.setdefault(guild_id_str, {}) # Create empty cache for this guild

        try:
            # Пример загрузки из settings (предполагаем структуру settings['guilds'][guild_id]['crafting_recipes']
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            recipes_data = guild_settings.get('crafting_recipes')

            # TODO: Add fallback to global recipes file if needed

            if isinstance(recipes_data, dict):
                 for recipe_id, data in recipes_data.items():
                      # Basic validation
                      if recipe_id and isinstance(data, dict):
                           # Ensure required recipe data fields exist (e.g., 'ingredients', 'results', 'time')
                           if isinstance(data.get('ingredients'), list) and isinstance(data.get('results'), list):
                                data.setdefault('id', str(recipe_id)) # Ensure id is in data
                                data.setdefault('name', f"Unnamed Recipe ({recipe_id})") # Ensure name
                                data.setdefault('time', 10.0) # Default crafting time in game seconds
                                data.setdefault('requirements', {}) # Default requirements (skills, tools, location)
                                guild_recipes_cache[str(recipe_id)] = data # Store with string ID
                           else:
                               print(f"CraftingManager: Warning: Skipping invalid recipe '{recipe_id}' for guild {guild_id_str}: missing 'ingredients' or 'results' lists. Data: {data}")

                 print(f"CraftingManager: Loaded {len(guild_recipes_cache)} crafting recipes for guild {guild_id_str}.")
            elif recipes_data is not None:
                 print(f"CraftingManager: Warning: Crafting recipes data for guild {guild_id_str} is not a dictionary ({type(recipes_data)}). Skipping recipe load.")
            else:
                 print(f"CraftingManager: No crafting recipes found in settings for guild {guild_id_str} or globally.")


        except Exception as e:
            print(f"CraftingManager: ❌ Error loading crafting recipes for guild {guild_id_str}: {e}")
            traceback.print_exc()
            # Decide how to handle error - critical or just log? Log and continue for now.


    # get_recipe now needs guild_id
    def get_recipe(self, guild_id: str, recipe_id: str) -> Optional[Dict[str, Any]]:
        """Возвращает данные рецепта по его ID для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Get recipes from the per-guild cache
        guild_recipes = self._crafting_recipes.get(guild_id_str, {})
        return guild_recipes.get(str(recipe_id)) # Ensure recipe_id is string


    # get_crafting_queue now needs guild_id
    # The queue is identified by entity_id (character or npc)
    def get_crafting_queue(self, guild_id: str, entity_id: str) -> Optional[Dict[str, Any]]: # Returning the raw queue data dict
        """Получить очередь крафтинга для сущности по ее ID для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Get queue from the per-guild cache
        guild_queues = self._crafting_queues.get(guild_id_str) # Get per-guild cache
        if guild_queues:
             # Return a copy of the queue data to prevent external modification
             queue_data = guild_queues.get(str(entity_id)) # Ensure entity_id is string
             if queue_data is not None:
                  return queue_data.copy() # Return a copy
        return None # Guild or queue not found


    # TODO: Implement add_to_queue method
    # Needs guild_id, entity_id, entity_type, recipe_id, quantity, context
    # Should validate recipe, requirements (via RuleEngine), consume ingredients (via ItemManager),
    # add task to queue, mark queue dirty.
    async def add_recipe_to_craft_queue(self, guild_id: str, entity_id: str, entity_type: str, recipe_id: str, quantity: int, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adds a recipe to the crafting queue for a specific entity.
        Performs requirement checks, consumes ingredients, and then queues the task.
        """
        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        recipe_id_str = str(recipe_id)
        print(f"CraftingManager: Attempting to add {quantity}x recipe '{recipe_id_str}' to queue for {entity_type} {entity_id_str} in guild {guild_id_str}.")

        # Retrieve necessary managers from self or context
        rule_engine: Optional["RuleEngine"] = context.get('rule_engine', self._rule_engine)
        item_manager: Optional["ItemManager"] = context.get('item_manager', self._item_manager)
        # CharacterManager and NpcManager are already attributes of self
        time_manager: Optional["TimeManager"] = context.get('time_manager', self._time_manager)

        if not rule_engine: return {"success": False, "message": "Crafting system (RuleEngine) is unavailable."}
        if not item_manager: return {"success": False, "message": "Item system (ItemManager) is unavailable."}
        if not self._character_manager and entity_type == "Character": return {"success": False, "message": "Character system is unavailable."}
        if not self._npc_manager and entity_type == "NPC": return {"success": False, "message": "NPC system is unavailable."}
        if not time_manager: return {"success": False, "message": "Time system (TimeManager) is unavailable."}

        # Fetch the recipe
        recipe = self.get_recipe(guild_id_str, recipe_id_str)
        if not recipe:
            return {"success": False, "message": f"Recipe '{recipe_id_str}' not found."}

        recipe_name = recipe.get('name', recipe_id_str)

        # --- 4. Requirement Checks ---
        # Placeholder: Assume RuleEngine.check_crafting_requirements exists
        # This method would check skills, tools, location, etc.
        # For now, we'll assume it passes or implement a basic check.
        if hasattr(rule_engine, 'check_crafting_requirements'):
            try:
                requirements_met, requirement_message = await rule_engine.check_crafting_requirements(
                    entity_id_str, entity_type, recipe, context
                )
                if not requirements_met:
                    return {"success": False, "message": requirement_message or f"Requirements not met for crafting {recipe_name}."}
            except Exception as e:
                print(f"CraftingManager: Error during rule_engine.check_crafting_requirements for {entity_id_str}, recipe {recipe_id_str}: {e}")
                traceback.print_exc()
                return {"success": False, "message": f"Error checking requirements for {recipe_name}."}
        else:
            print(f"CraftingManager: Warning: RuleEngine.check_crafting_requirements not implemented. Skipping requirement checks.")


        # --- 5. Ingredient Checks & Consumption ---
        ingredients_to_consume = []
        for ingredient in recipe.get('ingredients', []):
            item_template_id = ingredient.get('item_template_id')
            required_quantity = ingredient.get('quantity', 0) * quantity # Total needed for all items
            
            if not item_template_id or required_quantity <= 0:
                continue # Skip invalid ingredient entry

            # Check if entity has enough items
            # Placeholder: Assume ItemManager.entity_has_item_template_id exists
            has_enough = False
            if hasattr(item_manager, 'entity_has_item_template_id'):
                try:
                    has_enough = await item_manager.entity_has_item_template_id(
                        entity_id_str, entity_type, item_template_id, required_quantity, context
                    )
                except Exception as e:
                    print(f"CraftingManager: Error checking ingredients for {entity_id_str}, item {item_template_id}: {e}")
                    traceback.print_exc()
                    return {"success": False, "message": f"Error checking ingredients for {recipe_name}."}
            else:
                print(f"CraftingManager: Warning: ItemManager.entity_has_item_template_id not implemented. Cannot check ingredients.")
                return {"success": False, "message": "Cannot verify ingredients due to system configuration."}


            if not has_enough:
                # Get item name for a nicer message
                ingredient_template = item_manager.get_item_template(guild_id_str, item_template_id)
                ingredient_name = getattr(ingredient_template, 'name', item_template_id) if ingredient_template else item_template_id
                return {"success": False, "message": f"Insufficient ingredients: Missing {required_quantity}x {ingredient_name} for {recipe_name}."}
            
            ingredients_to_consume.append({'item_template_id': item_template_id, 'quantity': required_quantity})

        # All ingredient checks passed, now consume them
        for item_to_consume in ingredients_to_consume:
            # Placeholder: Assume ItemManager.remove_item_from_entity_inventory_by_template_id exists
            if hasattr(item_manager, 'remove_item_from_entity_inventory_by_template_id'):
                try:
                    removed_count = await item_manager.remove_item_from_entity_inventory_by_template_id(
                        entity_id_str, entity_type, item_to_consume['item_template_id'], item_to_consume['quantity'], context
                    )
                    if removed_count < item_to_consume['quantity']:
                        # This should ideally not happen if has_enough check was correct and atomic.
                        # Could indicate a race condition or logic error.
                        print(f"CraftingManager: CRITICAL: Failed to consume enough {item_to_consume['item_template_id']} for {entity_id_str}. Expected {item_to_consume['quantity']}, got {removed_count}.")
                        # Attempt to roll back consumed items (complex, not implemented here) or fail.
                        return {"success": False, "message": f"Critical error consuming ingredients for {recipe_name}. Please contact an admin."}
                except Exception as e:
                    print(f"CraftingManager: Error consuming ingredients for {entity_id_str}, item {item_to_consume['item_template_id']}: {e}")
                    traceback.print_exc()
                    return {"success": False, "message": f"Error consuming ingredients for {recipe_name}."}
            else:
                print(f"CraftingManager: Warning: ItemManager.remove_item_from_entity_inventory_by_template_id not implemented. Cannot consume ingredients.")
                return {"success": False, "message": "Cannot consume ingredients due to system configuration."}
        
        print(f"CraftingManager: Ingredients consumed successfully for {entity_id_str}, recipe {recipe_id_str}.")

        # --- 6. Task Creation ---
        total_duration = float(recipe.get('time', 10.0)) * quantity # Total time for all items
        current_game_time = time_manager.get_current_game_time(guild_id_str) # Assuming this is synchronous for now

        task = {
            'task_id': str(uuid.uuid4()),
            'recipe_id': recipe_id_str,
            'quantity': quantity,
            'progress': 0.0,
            'total_duration': total_duration,
            'added_at': current_game_time 
        }

        # --- 7. Add to Queue ---
        guild_queues_cache = self._crafting_queues.setdefault(guild_id_str, {})
        # Ensure entity_id_str is used as key
        entity_queue_data = guild_queues_cache.setdefault(entity_id_str, {'entity_id': entity_id_str, 'entity_type': entity_type, 'guild_id': guild_id_str, 'queue': [], 'state_variables': {}})
        
        # Ensure 'queue' key exists and is a list
        if not isinstance(entity_queue_data.get('queue'), list):
            entity_queue_data['queue'] = []
            
        entity_queue_data['queue'].append(task)
        self.mark_queue_dirty(guild_id_str, entity_id_str) # Use string entity_id

        print(f"CraftingManager: Task {task['task_id']} for recipe {recipe_id_str} (x{quantity}) added to queue for {entity_type} {entity_id_str}. Queue length: {len(entity_queue_data['queue'])}.")
        
        return {"success": True, "message": f"✅ Started crafting {quantity}x {recipe_name}. It has been added to your queue."}


    # TODO: Implement process_tick method
    # Called by WorldSimulationProcessor
    # Needs guild_id, game_time_delta, context
    # Should iterate through active queues for the guild, update task progress,
    # call RuleEngine to process completed tasks, handle results (ItemManager).
    # Should mark queues dirty if changed.
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        """
        Обрабатывает игровой тик для очередей крафтинга для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        # print(f"CraftingManager: Processing tick for guild {guild_id_str}. Delta: {game_time_delta:.2f}. (Placeholder)") # Too noisy

        # Get RuleEngine from kwargs or self
        rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]
        time_manager = kwargs.get('time_manager', self._time_manager) # type: Optional["TimeManager"]

        if not rule_engine or not hasattr(rule_engine, 'process_crafting_task'):
             # print(f"CraftingManager: Warning: RuleEngine or process_crafting_task method not available for guild {guild_id_str}. Skipping crafting tick.") # Too noisy?
             return # Cannot process tick without RuleEngine logic


        # Get all crafting queues for this guild
        guild_queues = self._crafting_queues.get(guild_id_str)
        if not guild_queues:
             # print(f"CraftingManager: No crafting queues found for guild {guild_id_str} during tick.") # Too noisy?
             return # No queues in this guild


        # Iterate through queues and process
        # Iterate over a copy of the entity_ids in the queue cache to avoid issues if a queue is removed during processing
        entity_ids_with_queues = list(guild_queues.keys())
        for entity_id in entity_ids_with_queues:
             # Check if the queue still exists in the cache for this guild (might have been removed)
             queue_data = guild_queues.get(entity_id)
             if not queue_data: continue # Skip if queue was removed

             queue_list = queue_data.get('queue', []) # Get the list of tasks
             if not isinstance(queue_list, list):
                  print(f"CraftingManager: Warning: Crafting queue for entity {entity_id} in guild {guild_id_str} is not a list ({type(queue_list)}). Resetting to empty list.")
                  queue_list = [] # Reset if not list
                  queue_data['queue'] = queue_list # Update in data dict

             # Process the first item in the queue if it exists
             if queue_list:
                  task = queue_list[0] # Get the current task (Dict[str, Any])
                  if not isinstance(task, dict):
                       print(f"CraftingManager: Warning: Invalid task data in queue for entity {entity_id} in guild {guild_id_str}: {task}. Removing from queue.")
                       queue_list.pop(0) # Remove invalid task
                       self.mark_queue_dirty(guild_id_str, entity_id) # Mark dirty
                       continue # Move to next entity

                  # Ensure task has 'progress' attribute
                  if 'progress' not in task or not isinstance(task.get('progress'), (int, float)):
                       print(f"CraftingManager: Warning: Task for entity {entity_id} in guild {guild_id_str} missing 'progress' attribute. Initializing to 0.0.")
                       task['progress'] = 0.0

                  # Add game time delta to progress
                  task['progress'] += game_time_delta
                  self.mark_queue_dirty(guild_id_str, entity_id) # Mark queue dirty as progress changed

                  # Check if the task is complete
                  recipe_id = task.get('recipe_id')
                  if recipe_id is None:
                       print(f"CraftingManager: Warning: Task for entity {entity_id} in guild {guild_id_str} missing 'recipe_id'. Removing from queue.")
                       queue_list.pop(0) # Remove invalid task
                       # Queue is already marked dirty
                       continue

                  # Get the recipe data to check total time
                  recipe = self.get_recipe(guild_id_str, str(recipe_id)) # Use get_recipe with guild_id
                  if not recipe:
                       print(f"CraftingManager: Warning: Recipe '{recipe_id}' not found for task for entity {entity_id} in guild {guild_id_str}. Removing from queue.")
                       queue_list.pop(0) # Remove task with missing recipe
                       # Queue is already marked dirty
                       continue

                  required_time = float(recipe.get('time', 10.0)) # Default recipe time if not specified

                  if task['progress'] >= required_time:
                       # Task is complete! Process result.
                       print(f"CraftingManager: Crafting task '{recipe_id}' complete for entity {entity_id} in guild {guild_id_str}.")
                       try:
                           # Call RuleEngine to process task completion (give items, grant XP, etc.)
                           # process_crafting_task needs entity_id, entity_type, recipe_id, context
                           # Determine entity_type (Character or NPC?)
                           entity_type = None # Try to determine entity type from managers in kwargs or self
                           char_mgr = kwargs.get('character_manager', self._character_manager)
                           npc_mgr = kwargs.get('npc_manager', self._npc_manager)
                           if char_mgr and hasattr(char_mgr, 'get_character') and char_mgr.get_character(guild_id_str, entity_id): entity_type = 'Character'
                           elif npc_mgr and hasattr(npc_mgr, 'get_npc') and npc_mgr.get_npc(guild_id_str, entity_id): entity_type = 'NPC'

                           if entity_type is None:
                                print(f"CraftingManager: Warning: Could not determine type for entity {entity_id} in guild {guild_id_str} during crafting task completion. Cannot process task results via RuleEngine.")
                                # Remove task anyway to prevent infinite loop
                                queue_list.pop(0)
                                # Queue is already marked dirty
                                continue # Move to next entity


                           # Pass all necessary context to RuleEngine
                           task_context = {**kwargs, 'guild_id': guild_id_str, 'entity_id': entity_id, 'entity_type': entity_type, 'recipe_data': recipe} # Add specific task info

                           await rule_engine.process_crafting_task(
                               entity_id=entity_id,
                               entity_type=entity_type,
                               recipe_id=str(recipe_id), # Ensure string
                               context=task_context # Pass full context
                           )
                           print(f"CraftingManager: RuleEngine.process_crafting_task executed for {entity_id} in guild {guild_id_str}.")

                           # Remove the completed task from the queue
                           queue_list.pop(0)
                           # Queue is already marked dirty from progress update

                           # If there are more tasks in the queue, the next one starts immediately (or at next tick)
                           if queue_list:
                                # Reset progress for the *next* task if it exists
                                next_task = queue_list[0]
                                if isinstance(next_task, dict):
                                     next_task['progress'] = 0.0 # Reset progress for the new first task
                                     self.mark_queue_dirty(guild_id_str, entity_id) # Mark dirty

                       except Exception as e:
                           print(f"CraftingManager: ❌ Error processing crafting task '{recipe_id}' for entity {entity_id} in guild {guild_id_str}: {e}")
                           traceback.print_exc()
                           # Decide how to handle error - remove task or leave it stuck? Remove for now.
                           queue_list.pop(0) # Remove the task that caused error
                           # Queue is already marked dirty
                           # Continue loop

                  # else: Task is not complete yet, leave in queue


        # After processing all entities, save state if any queues were marked dirty.
        # Save happens automatically by PersistenceManager.process_tick if this manager is in its list.


    # load_state - loads per-guild
    # required_args_for_load = ["guild_id"]
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает очереди крафтинга и рецепты для определенной гильдии из базы данных/настроек в кеш."""
        guild_id_str = str(guild_id)
        print(f"CraftingManager: Loading state for guild {guild_id_str} (queues + recipes)...")

        if self._db_adapter is None:
            print(f"CraftingManager: Warning: No DB adapter. Skipping queue/recipe load for guild {guild_id_str}. It will work with empty caches.")
            # TODO: In non-DB mode, load placeholder data
            return

        # --- 1. Загрузка статических рецептов (per-guild) ---
        # Call the helper method
        self.load_static_recipes(guild_id_str)


        # --- 2. Загрузка активных очередей крафтинга (per-guild) ---
        # Очищаем кеши очередей ТОЛЬКО для этой гильдии перед загрузкой
        self._crafting_queues.pop(guild_id_str, None) # Remove old cache for this guild
        self._crafting_queues[guild_id_str] = {} # Create an empty cache for this guild

        # При загрузке, считаем, что все в DB "чистое", поэтому очищаем dirty/deleted для этой гильдии
        self._dirty_crafting_queues.pop(guild_id_str, None)
        self._deleted_crafting_queue_ids.pop(guild_id_str, None)

        rows = []
        try:
            # Execute SQL SELECT FROM crafting_queues WHERE guild_id = ?
            # Assuming table has columns: entity_id, entity_type, guild_id, queue, state_variables
            sql = '''
            SELECT entity_id, entity_type, guild_id, queue, state_variables
            FROM crafting_queues WHERE guild_id = ?
            '''
            rows = await self._db_adapter.fetchall(sql, (guild_id_str,)) # Filter by guild_id
            print(f"CraftingManager: Found {len(rows)} crafting queues in DB for guild {guild_id_str}.")

        except Exception as e:
            print(f"CraftingManager: ❌ CRITICAL ERROR executing DB fetchall for crafting queues for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Clear queue cache for this guild on critical error
            self._crafting_queues.pop(guild_id_str, None)
            raise # Re-raise critical error


        loaded_count = 0
        # Get the cache dict for this specific guild
        guild_queues_cache = self._crafting_queues[guild_id_str]

        for row in rows:
             data = dict(row)
             try:
                 # Validate and parse data
                 entity_id_raw = data.get('entity_id')
                 entity_type_raw = data.get('entity_type')
                 loaded_guild_id_raw = data.get('guild_id') # Should match guild_id_str due to WHERE clause

                 if entity_id_raw is None or entity_type_raw is None or loaded_guild_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                     # This check is mostly redundant due to WHERE clause but safe.
                     print(f"CraftingManager: Warning: Skipping queue row with invalid ID/Type/Guild ('{entity_id_raw}', '{entity_type_raw}', '{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                     continue

                 entity_id = str(entity_id_raw)
                 entity_type = str(entity_type_raw) # Ensure type is string


                 # Parse JSON fields, handle None/malformed data gracefully
                 try:
                     data['queue'] = json.loads(data.get('queue') or '[]') if isinstance(data.get('queue'), (str, bytes)) else []
                 except (json.JSONDecodeError, TypeError):
                      print(f"CraftingManager: Warning: Failed to parse queue for entity {entity_id} in guild {guild_id_str}. Setting to []. Data: {data.get('queue')}")
                      data['queue'] = []
                 else: # Ensure queue items are dicts and have basic required fields (e.g., 'recipe_id')
                      cleaned_queue = []
                      for task in data['queue']:
                           if isinstance(task, dict) and task.get('recipe_id') is not None:
                                # Basic validation for task structure
                                task.setdefault('progress', 0.0) # Ensure progress field
                                cleaned_queue.append(task)
                           else:
                                print(f"CraftingManager: Warning: Invalid task format in queue for entity {entity_id} in guild {guild_id_str}. Skipping task: {task}")
                      data['queue'] = cleaned_queue


                 try:
                     data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                 except (json.JSONDecodeError, TypeError):
                      print(f"CraftingManager: Warning: Failed to parse state_variables for queue of entity {entity_id} in guild {guild_id_str}. Setting to {{}}. Data: {data.get('state_variables')}")
                      data['state_variables'] = {}


                 # Ensure required fields exist and have correct types after parsing
                 data['entity_id'] = entity_id
                 data['entity_type'] = entity_type
                 data['guild_id'] = guild_id_str # Ensure guild_id is string


                 # Store the loaded queue data dict in the per-guild cache, indexed by entity_id
                 # We are not using a dedicated CraftingQueue model currently, just storing the data dicts.
                 guild_queues_cache[entity_id] = {
                     'entity_id': data['entity_id'],
                     'entity_type': data['entity_type'],
                     'guild_id': data['guild_id'],
                     'queue': data['queue'],
                     'state_variables': data['state_variables'],
                 }

                 loaded_count += 1

             except Exception as e:
                 print(f"CraftingManager: Error loading crafting queue for entity {data.get('entity_id', 'N/A')} in guild {guild_id_str}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # Continue loop for other rows


        print(f"CraftingManager: Successfully loaded {loaded_count} crafting queues into cache for guild {guild_id_str}.")
        print(f"CraftingManager: Load state complete for guild {guild_id_str}.")


    # save_state - saves per-guild
    # required_args_for_save = ["guild_id"]
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет измененные очереди крафтинга для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"CraftingManager: Saving crafting queue state for guild {guild_id_str}...")

        if self._db_adapter is None:
            print(f"CraftingManager: Warning: Cannot save crafting queue state for guild {guild_id_str}, DB adapter missing.")
            return

        # ИСПРАВЛЕНИЕ: Соберите dirty/deleted ID ИЗ per-guild кешей
        dirty_queue_entity_ids_set = self._dirty_crafting_queues.get(guild_id_str, set()).copy() # Use a copy
        deleted_queue_entity_ids_set = self._deleted_crafting_queue_ids.get(guild_id_str, set()).copy() # Use a copy

        if not dirty_queue_entity_ids_set and not deleted_queue_entity_ids_set:
            # print(f"CraftingManager: No dirty or deleted crafting queues to save for guild {guild_id_str}.") # Too noisy
            # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем per-guild dirty/deleted сеты
            self._dirty_crafting_queues.pop(guild_id_str, None)
            self._deleted_crafting_queue_ids.pop(guild_id_str, None)
            return

        print(f"CraftingManager: Saving {len(dirty_queue_entity_ids_set)} dirty, {len(deleted_queue_entity_ids_set)} deleted crafting queues for guild {guild_id_str}...")

        try:
            # 1. Удаление очередей, помеченных для удаления для этой гильдии
            if deleted_queue_entity_ids_set:
                ids_to_delete = list(deleted_queue_entity_ids_set)
                placeholders_del = ','.join(['?'] * len(ids_to_delete))
                # Assuming the table PK is just entity_id as per the DB schema in sqlite_adapter
                # If PK is composite (entity_id, entity_type, guild_id), the DELETE WHERE clause needs adjustment.
                # Sticking to entity_id PK for now based on the last adapter code provided.
                sql_delete_batch = f"DELETE FROM crafting_queues WHERE guild_id = ? AND entity_id IN ({placeholders_del})"
                try:
                    await self._db_adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete)))
                    print(f"CraftingManager: Deleted {len(ids_to_delete)} crafting queues from DB for guild {guild_id_str}.")
                    # ИСПРАВЛЕНИЕ: Очищаем per-guild deleted set after successful deletion
                    self._deleted_crafting_queue_ids.pop(guild_id_str, None)
                except Exception as e:
                    print(f"CraftingManager: Error deleting crafting queues for guild {guild_id_str}: {e}"); traceback.print_exc();
                    # Do NOT clear deleted set on error


            # 2. Обновить или вставить измененные очереди для этого guild_id
            # Filter dirty IDs on queues that still exist in the per-guild active cache
            guild_queues_cache = self._crafting_queues.get(guild_id_str, {})
            queues_to_upsert_list: List[Dict[str, Any]] = [ qd for eid in list(dirty_queue_entity_ids_set) if (qd := guild_queues_cache.get(eid)) is not None ] # Iterate over a copy of IDs

            if queues_to_upsert_list:
                 print(f"CraftingManager: Upserting {len(queues_to_upsert_list)} crafting queues for guild {guild_id_str}...")
                 # Assuming table has columns: entity_id, entity_type, guild_id, queue, state_variables
                 # And PK is entity_id
                 upsert_sql = '''
                 INSERT OR REPLACE INTO crafting_queues
                 (entity_id, entity_type, guild_id, queue, state_variables)
                 VALUES (?, ?, ?, ?, ?)
                 '''
                 data_to_upsert = []
                 upserted_entity_ids: Set[str] = set() # Track entity IDs successfully prepared

                 for queue_data in queues_to_upsert_list:
                      try:
                           # Ensure queue data has all required keys
                           entity_id = queue_data.get('entity_id')
                           entity_type = queue_data.get('entity_type')
                           queue_guild_id = queue_data.get('guild_id')

                           # Double check required keys and guild ID match
                           if entity_id is None or entity_type is None or str(queue_guild_id) != guild_id_str:
                               print(f"CraftingManager: Warning: Skipping upsert for queue with invalid ID/Type ('{entity_id}', '{entity_type}') or mismatched guild ('{queue_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                               continue

                           queue_list = queue_data.get('queue', [])
                           state_variables = queue_data.get('state_variables', {})

                           # Ensure data types are suitable for JSON dumping
                           if not isinstance(queue_list, list): queue_list = []
                           if not isinstance(state_variables, dict): state_variables = {}

                           queue_json = json.dumps(queue_list)
                           state_variables_json = json.dumps(state_variables)

                           data_to_upsert.append((
                               str(entity_id),
                               str(entity_type),
                               guild_id_str, # Ensure guild_id string
                               queue_json,
                               state_variables_json,
                           ))
                           upserted_entity_ids.add(str(entity_id)) # Track entity ID

                      except Exception as e:
                           print(f"CraftingManager: Error preparing data for queue of entity {queue_data.get('entity_id', 'N/A')} (guild {queue_data.get('guild_id', 'N/A')}) for upsert: {e}")
                           import traceback
                           print(traceback.format_exc())
                           # This queue won't be saved but remains in _dirty_crafting_queues


                 if data_to_upsert:
                      if self._db_adapter is None:
                           print(f"CraftingManager: Warning: DB adapter is None during queue upsert batch for guild {guild_id_str}.")
                      else:
                           await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                           print(f"CraftingManager: Successfully upserted {len(data_to_upsert)} crafting queues for guild {guild_id_str}.")
                           # Only clear dirty flags for queues that were successfully processed
                           if guild_id_str in self._dirty_crafting_queues:
                                self._dirty_crafting_queues[guild_id_str].difference_update(upserted_entity_ids)
                                # If set is empty after update, remove the guild key
                                if not self._dirty_crafting_queues[guild_id_str]:
                                     del self._dirty_crafting_queues[guild_id_str]

                 # Note: Ended/empty queues that were removed from _crafting_queues
                 # (by clean_up_for_entity calling remove_queue) are NOT saved by this upsert block.
                 # They are handled by the DELETE block.

        except Exception as e:
            print(f"CraftingManager: ❌ Error during saving state for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Do NOT clear dirty/deleted sets on error to allow retry.
            # raise # Re-raise if critical

        print(f"CraftingManager: Save state complete for guild {guild_id_str}.")


    # rebuild_runtime_caches - rebuilds per-guild caches after loading
    # required_args_for_rebuild = ["guild_id"]
    # Already takes guild_id and **kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """
        Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии.
        (Сейчас минимально, так как основные кеши наполняются при загрузке).
        """
        guild_id_str = str(guild_id)
        print(f"CraftingManager: Rebuilding runtime caches for guild {guild_id_str}...")
        # Сейчас ничего дополнительного делать не нужно, так как _crafting_queues
        # уже наполняется в load_state. Если бы были другие кеши, зависящие от
        # данных других менеджеров, они бы строились здесь.
        print(f"CraftingManager: Runtime caches rebuilt for guild {guild_id_str}. Crafting queues count: {len(self._crafting_queues.get(guild_id_str, {}))}")


    # mark_queue_dirty needs guild_id
    # Needs _dirty_crafting_queues Set (per-guild)
    def mark_queue_dirty(self, guild_id: str, entity_id: str) -> None:
         """Помечает очередь крафтинга сущности как измененную для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         entity_id_str = str(entity_id)
         # Add check that the entity ID exists in the per-guild active queue cache
         guild_queues_cache = self._crafting_queues.get(guild_id_str)
         if guild_queues_cache and entity_id_str in guild_queues_cache:
              # Add to the per-guild dirty set
              self._dirty_crafting_queues.setdefault(guild_id_str, set()).add(entity_id_str)
         # else: print(f"CraftingManager: Warning: Attempted to mark non-existent crafting queue for entity {entity_id_str} in guild {guild_id_str} as dirty.") # Too noisy?


    # mark_queue_deleted needs guild_id
    # Needs _deleted_crafting_queue_ids Set (per-guild)
    # Called by remove_queue or clean_up_for_entity
    def mark_queue_deleted(self, guild_id: str, entity_id: str) -> None:
        """Помечает очередь крафтинга сущности как удаленную для определенной гильдии."""
        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)

        # Check if queue exists in the per-guild cache
        guild_queues_cache = self._crafting_queues.get(guild_id_str)
        if guild_queues_cache and entity_id_str in guild_queues_cache:
            # Remove from per-guild cache
            del guild_queues_cache[entity_id_str]
            print(f"CraftingManager: Removed crafting queue for entity {entity_id_str} from cache for guild {guild_id_str}.")

            # Add to per-guild deleted set
            self._deleted_crafting_queue_ids.setdefault(guild_id_str, set()).add(entity_id_str) # uses set()

            # Remove from per-guild dirty set if it was there
            self._dirty_crafting_queues.get(guild_id_str, set()).discard(entity_id_str) # uses set()

            print(f"CraftingManager: Crafting queue for entity {entity_id_str} marked for deletion for guild {guild_id_str}.")

        # Handle case where queue was already deleted but mark_deleted is called again
        elif guild_id_str in self._deleted_crafting_queue_ids and entity_id_str in self._deleted_crafting_queue_ids[guild_id_str]:
             print(f"CraftingManager: Crafting queue for entity {entity_id_str} in guild {guild_id_str} already marked for deletion.")
        else:
             print(f"CraftingManager: Warning: Attempted to mark non-existent crafting queue for entity {entity_id_str} in guild {guild_id_str} as deleted.")


    # TODO: Implement clean_up_for_entity method (used by Character/NPC Managers)
    # This method is called by CharacterManager.remove_character, NpcManager.remove_npc etc.
    # It should remove the crafting queue associated with this entity.
    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         """
         Удаляет очередь крафтинга, связанную с сущностью, когда сущность удаляется.
         Предназначен для вызова менеджерами сущностей (Character, NPC).
         """
         # Get guild_id from context kwargs
         guild_id = kwargs.get('guild_id')
         if guild_id is None:
              print(f"CraftingManager: Warning: clean_up_for_entity called for {entity_type} {entity_id} without guild_id in context. Cannot clean up crafting queue.")
              return # Cannot clean up without guild_id

         guild_id_str = str(guild_id)
         print(f"CraftingManager: Cleaning up crafting queue for {entity_type} {entity_id} in guild {guild_id_str}...")

         # Check if the queue exists for this entity/guild
         guild_queues_cache = self._crafting_queues.get(guild_id_str)
         if guild_queues_cache and entity_id in guild_queues_cache:
              # Mark the queue for deletion
              self.mark_queue_deleted(guild_id_str, entity_id) # Use mark_queue_deleted with guild_id

         # else: print(f"CraftingManager: No crafting queue found for {entity_type} {entity_id} in guild {guild_id_str} for cleanup.") # Too noisy?


# TODO: Implement remove_queue(entity_id, guild_id, **context) method
# A public method to explicitly remove a queue if needed (e.g., player deletes their queue).
# async def remove_queue(self, entity_id: str, guild_id: str, **kwargs: Any) -> None: ...


# TODO: Implement get_entity_id_by_discord_id method (if needed for commands)
# For commands like /craft add, need to find character entity ID by Discord ID.
# This would likely delegate to CharacterManager/NpcManager.
# async def get_entity_id_by_discord_id(self, discord_id: int, guild_id: str, **kwargs: Any) -> Optional[str]: ...

# --- Конец класса CraftingManager ---

print("--- CraftingManager module finished loading ---") # Отладочный вывод в конце файла
