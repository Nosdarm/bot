# bot/game/managers/crafting_manager.py

from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import time
import logging # Added
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union

from bot.services.db_service import DBService
from builtins import dict, set, list, str, int, bool, float

if TYPE_CHECKING:
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager

logger = logging.getLogger(__name__) # Added

logger.debug("--- CraftingManager module starts loading ---") # Changed

class CraftingManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _crafting_recipes: Dict[str, Dict[str, Any]]
    _crafting_queues: Dict[str, Dict[str, Dict[str, Any]]]
    _dirty_crafting_queues: Dict[str, Set[str]]
    _deleted_crafting_queue_ids: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        time_manager: Optional["TimeManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
    ):
        logger.info("Initializing CraftingManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager

        self._crafting_recipes = {}
        self._crafting_queues = {}
        self._dirty_crafting_queues = {}
        self._deleted_crafting_queue_ids = {}

        self.load_static_recipes()
        logger.info("CraftingManager initialized.") # Changed

    def load_static_recipes(self) -> None:
        logger.info("CraftingManager: Loading global crafting recipes...") # Changed
        self._crafting_recipes = {}

        if self._settings and 'crafting_recipes' in self._settings:
            recipes_data_dict = self._settings['crafting_recipes']
            if isinstance(recipes_data_dict, dict):
                for recipe_id, data in recipes_data_dict.items():
                    if recipe_id and isinstance(data, dict):
                        if isinstance(data.get('ingredients'), list) and isinstance(data.get('results'), list):
                            data.setdefault('id', str(recipe_id))
                            data.setdefault('name_i18n', {"en": f"Unnamed Recipe ({recipe_id})", "ru": f"Рецепт без имени ({recipe_id})"})
                            data.setdefault('crafting_time_seconds', 10.0)
                            data.setdefault('requirements', {})
                            self._crafting_recipes[str(recipe_id)] = data
                        else:
                            logger.warning("CraftingManager: Skipping invalid recipe '%s': missing 'ingredients' or 'results' lists. Data: %s", recipe_id, data) # Changed
                logger.info("CraftingManager: Loaded %s global crafting recipes.", len(self._crafting_recipes)) # Changed
            else:
                logger.warning("CraftingManager: 'crafting_recipes' in settings is not a dictionary.") # Changed
        else:
            logger.info("CraftingManager: No 'crafting_recipes' found in settings.") # Changed

    def get_recipe(self, recipe_id: str) -> Optional[Dict[str, Any]]:
        return self._crafting_recipes.get(str(recipe_id))

    def get_crafting_queue(self, guild_id: str, entity_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        guild_queues = self._crafting_queues.get(guild_id_str)
        if guild_queues:
             queue_data = guild_queues.get(str(entity_id))
             if queue_data is not None:
                  return queue_data.copy()
        return None

    async def add_recipe_to_craft_queue(self, guild_id: str, entity_id: str, entity_type: str, recipe_id: str, quantity: int, context: Dict[str, Any]) -> Dict[str, Any]:
        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        recipe_id_str = str(recipe_id)
        logger.info("CraftingManager: Attempting to add %sx recipe '%s' to queue for %s %s in guild %s.", quantity, recipe_id_str, entity_type, entity_id_str, guild_id_str) # Changed

        rule_engine: Optional["RuleEngine"] = context.get('rule_engine', self._rule_engine)
        item_manager: Optional["ItemManager"] = context.get('item_manager', self._item_manager)
        time_manager: Optional["TimeManager"] = context.get('time_manager', self._time_manager)

        if not rule_engine: return {"success": False, "message": "Crafting system (RuleEngine) is unavailable."}
        if not item_manager: return {"success": False, "message": "Item system (ItemManager) is unavailable."}
        if not self._character_manager and entity_type == "Character": return {"success": False, "message": "Character system is unavailable."}
        if not self._npc_manager and entity_type == "NPC": return {"success": False, "message": "NPC system is unavailable."}
        if not time_manager: return {"success": False, "message": "Time system (TimeManager) is unavailable."}

        recipe = self.get_recipe(recipe_id_str)
        if not recipe:
            return {"success": False, "message": f"Recipe '{recipe_id_str}' not found."}

        default_lang = 'en'
        recipe_name_i18n = recipe.get('name_i18n', {})
        recipe_name = recipe_name_i18n.get(default_lang, recipe_name_i18n.get('en', recipe_id_str))
        
        logger.warning("CraftingManager: FIXME: RuleEngine.check_crafting_requirements call skipped as method is missing for recipe %s, entity %s, guild %s.", recipe_id_str, entity_id_str, guild_id_str) # Changed
        logger.warning("CraftingManager: FIXME: Ingredient consumption skipped for recipe %s, entity %s, guild %s as ItemManager methods are missing. Assuming ingredients are available and consumed.", recipe_id_str, entity_id_str, guild_id_str) # Changed

        total_duration = float(recipe.get('crafting_time_seconds', 10.0)) * quantity # Changed 'time' to 'crafting_time_seconds'
        current_game_time = time_manager.get_current_game_time(guild_id_str)

        task = {
            'task_id': str(uuid.uuid4()), 'recipe_id': recipe_id_str, 'quantity': quantity,
            'progress': 0.0, 'total_duration': total_duration, 'added_at': current_game_time
        }

        guild_queues_cache = self._crafting_queues.setdefault(guild_id_str, {})
        entity_queue_data = guild_queues_cache.setdefault(entity_id_str, {'entity_id': entity_id_str, 'entity_type': entity_type, 'guild_id': guild_id_str, 'queue': [], 'state_variables': {}})
        
        if not isinstance(entity_queue_data.get('queue'), list):
            entity_queue_data['queue'] = []
            
        entity_queue_data['queue'].append(task)
        self.mark_queue_dirty(guild_id_str, entity_id_str)

        logger.info("CraftingManager: Task %s for recipe %s (x%s) added to queue for %s %s in guild %s. Queue length: %s.", task['task_id'], recipe_id_str, quantity, entity_type, entity_id_str, guild_id_str, len(entity_queue_data['queue'])) # Changed
        
        return {"success": True, "message": f"✅ Started crafting {quantity}x {recipe_name}. It has been added to your queue."}

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        time_manager = kwargs.get('time_manager', self._time_manager)

        if not rule_engine or not hasattr(rule_engine, 'process_crafting_task'):
             # logger.debug("CraftingManager: RuleEngine or process_crafting_task method not available for guild %s. Skipping crafting tick.", guild_id_str) # Too noisy
             return

        guild_queues = self._crafting_queues.get(guild_id_str)
        if not guild_queues:
             # logger.debug("CraftingManager: No crafting queues found for guild %s during tick.", guild_id_str) # Too noisy
             return

        entity_ids_with_queues = list(guild_queues.keys())
        for entity_id in entity_ids_with_queues:
             queue_data = guild_queues.get(entity_id)
             if not queue_data: continue

             queue_list = queue_data.get('queue', [])
             if not isinstance(queue_list, list):
                  logger.warning("CraftingManager: Crafting queue for entity %s in guild %s is not a list (%s). Resetting to empty list.", entity_id, guild_id_str, type(queue_list)) # Changed
                  queue_list = []
                  queue_data['queue'] = queue_list

             if queue_list:
                  task = queue_list[0]
                  if not isinstance(task, dict):
                       logger.warning("CraftingManager: Invalid task data in queue for entity %s in guild %s: %s. Removing from queue.", entity_id, guild_id_str, task) # Changed
                       queue_list.pop(0)
                       self.mark_queue_dirty(guild_id_str, entity_id)
                       continue

                  if 'progress' not in task or not isinstance(task.get('progress'), (int, float)):
                       logger.warning("CraftingManager: Task for entity %s in guild %s missing 'progress' attribute. Initializing to 0.0.", entity_id, guild_id_str) # Changed
                       task['progress'] = 0.0

                  task['progress'] += game_time_delta
                  self.mark_queue_dirty(guild_id_str, entity_id)

                  recipe_id = task.get('recipe_id')
                  if recipe_id is None:
                       logger.warning("CraftingManager: Task for entity %s in guild %s missing 'recipe_id'. Removing from queue.", entity_id, guild_id_str) # Changed
                       queue_list.pop(0)
                       continue

                  recipe = self.get_recipe(str(recipe_id))
                  if not recipe:
                       logger.warning("CraftingManager: Recipe '%s' not found for task for entity %s in guild %s. Removing from queue.", recipe_id, entity_id, guild_id_str) # Changed
                       queue_list.pop(0)
                       continue

                  required_time = float(recipe.get('crafting_time_seconds', 10.0))

                  if task['progress'] >= required_time:
                       logger.info("CraftingManager: Crafting task '%s' complete for entity %s in guild %s.", recipe_id, entity_id, guild_id_str) # Changed
                       try:
                           entity_type = None
                           char_mgr = kwargs.get('character_manager', self._character_manager)
                           npc_mgr = kwargs.get('npc_manager', self._npc_manager)
                           if char_mgr and hasattr(char_mgr, 'get_character') and char_mgr.get_character(guild_id_str, entity_id): entity_type = 'Character'
                           elif npc_mgr and hasattr(npc_mgr, 'get_npc') and npc_mgr.get_npc(guild_id_str, entity_id): entity_type = 'NPC'

                           if entity_type is None:
                                logger.warning("CraftingManager: Could not determine type for entity %s in guild %s during crafting task completion. Cannot process task results via RuleEngine.", entity_id, guild_id_str) # Changed
                                queue_list.pop(0)
                                continue

                           task_context = {**kwargs, 'guild_id': guild_id_str, 'entity_id': entity_id, 'entity_type': entity_type, 'recipe_data': recipe}

                           logger.warning("CraftingManager: FIXME: Crafting task completion logic via RuleEngine.process_crafting_task skipped for entity %s, recipe %s, guild %s.", entity_id, recipe_id, guild_id_str) # Changed
                           if self._item_manager and hasattr(self._item_manager, 'add_item_to_entity_inventory_by_template_id'):
                               for result_item_data in recipe.get('results', []):
                                   result_template_id = result_item_data.get('item_template_id')
                                   result_quantity = result_item_data.get('quantity', 1) * task.get('quantity', 1)
                                   if result_template_id and result_quantity > 0:
                                       await self._item_manager.add_item_to_entity_inventory_by_template_id(
                                           entity_id, entity_type, result_template_id, result_quantity, task_context
                                       )
                                       logger.info("CraftingManager: Placeholder: Granted %sx %s to %s in guild %s.", result_quantity, result_template_id, entity_id, guild_id_str) # Changed
                           else:
                               logger.warning("CraftingManager: Placeholder: ItemManager or add_item_to_entity_inventory_by_template_id missing for guild %s. Cannot grant items for completed task %s.", guild_id_str, recipe_id) # Changed

                           queue_list.pop(0)
                           if queue_list:
                                next_task = queue_list[0]
                                if isinstance(next_task, dict):
                                     next_task['progress'] = 0.0
                                     self.mark_queue_dirty(guild_id_str, entity_id)

                       except Exception as e:
                           logger.error("CraftingManager: Error processing crafting task '%s' for entity %s in guild %s: %s", recipe_id, entity_id, guild_id_str, e, exc_info=True) # Changed
                           queue_list.pop(0)

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("CraftingManager: Loading state for guild %s (queues + recipes)...", guild_id_str) # Changed

        if self._db_service is None or self._db_service.adapter is None:
            logger.warning("CraftingManager: No DB service or adapter for guild %s. Skipping queue/recipe load. Will work with empty caches.", guild_id_str) # Changed
            return

        self._crafting_queues.pop(guild_id_str, None)
        self._crafting_queues[guild_id_str] = {}
        self._dirty_crafting_queues.pop(guild_id_str, None)
        self._deleted_crafting_queue_ids.pop(guild_id_str, None)

        rows = []
        try:
            sql = 'SELECT entity_id, entity_type, guild_id, queue, state_variables FROM crafting_queues WHERE guild_id = $1'
            rows = await self._db_service.adapter.fetchall(sql, (guild_id_str,))
            logger.info("CraftingManager: Found %s crafting queues in DB for guild %s.", len(rows), guild_id_str) # Changed
        except Exception as e:
            logger.critical("CraftingManager: CRITICAL ERROR executing DB fetchall for crafting queues for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            self._crafting_queues.pop(guild_id_str, None)
            raise

        loaded_count = 0
        guild_queues_cache = self._crafting_queues[guild_id_str]
        for row in rows:
             data = dict(row)
             try:
                 entity_id_raw = data.get('entity_id')
                 entity_type_raw = data.get('entity_type')
                 loaded_guild_id_raw = data.get('guild_id')

                 if entity_id_raw is None or entity_type_raw is None or loaded_guild_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                     logger.warning("CraftingManager: Skipping queue row with invalid ID/Type/Guild ('%s', '%s', '%s') during load for guild %s. Row: %s.", entity_id_raw, entity_type_raw, loaded_guild_id_raw, guild_id_str, row) # Changed
                     continue

                 entity_id = str(entity_id_raw)
                 entity_type = str(entity_type_raw)

                 try:
                     data['queue'] = json.loads(data.get('queue') or '[]') if isinstance(data.get('queue'), (str, bytes)) else []
                 except (json.JSONDecodeError, TypeError):
                      logger.warning("CraftingManager: Failed to parse queue for entity %s in guild %s. Setting to []. Data: %s", entity_id, guild_id_str, data.get('queue')) # Changed
                      data['queue'] = []
                 else:
                      cleaned_queue = []
                      for task in data['queue']:
                           if isinstance(task, dict) and task.get('recipe_id') is not None:
                                task.setdefault('progress', 0.0)
                                cleaned_queue.append(task)
                           else:
                                logger.warning("CraftingManager: Invalid task format in queue for entity %s in guild %s. Skipping task: %s", entity_id, guild_id_str, task) # Changed
                      data['queue'] = cleaned_queue

                 try:
                     data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                 except (json.JSONDecodeError, TypeError):
                      logger.warning("CraftingManager: Failed to parse state_variables for queue of entity %s in guild %s. Setting to {}. Data: %s", entity_id, guild_id_str, data.get('state_variables')) # Changed
                      data['state_variables'] = {}

                 data['entity_id'] = entity_id
                 data['entity_type'] = entity_type
                 data['guild_id'] = guild_id_str

                 guild_queues_cache[entity_id] = {
                     'entity_id': data['entity_id'], 'entity_type': data['entity_type'],
                     'guild_id': data['guild_id'], 'queue': data['queue'],
                     'state_variables': data['state_variables'],
                 }
                 loaded_count += 1
             except Exception as e:
                 logger.error("CraftingManager: Error loading crafting queue for entity %s in guild %s: %s", data.get('entity_id', 'N/A'), guild_id_str, e, exc_info=True) # Changed
        logger.info("CraftingManager: Successfully loaded %s crafting queues into cache for guild %s.", loaded_count, guild_id_str) # Changed
        logger.info("CraftingManager: Load state complete for guild %s.", guild_id_str) # Changed

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("CraftingManager: Saving crafting queue state for guild %s...", guild_id_str) # Changed

        if self._db_service is None or self._db_service.adapter is None:
            logger.warning("CraftingManager: Cannot save crafting queue state for guild %s, DB service or adapter missing.", guild_id_str) # Changed
            return

        dirty_queue_entity_ids_set = self._dirty_crafting_queues.get(guild_id_str, set()).copy()
        deleted_queue_entity_ids_set = self._deleted_crafting_queue_ids.get(guild_id_str, set()).copy()

        if not dirty_queue_entity_ids_set and not deleted_queue_entity_ids_set:
            # logger.debug("CraftingManager: No dirty or deleted crafting queues to save for guild %s.", guild_id_str) # Too noisy
            self._dirty_crafting_queues.pop(guild_id_str, None)
            self._deleted_crafting_queue_ids.pop(guild_id_str, None)
            return

        logger.info("CraftingManager: Saving %s dirty, %s deleted crafting queues for guild %s...", len(dirty_queue_entity_ids_set), len(deleted_queue_entity_ids_set), guild_id_str) # Changed

        try:
            if deleted_queue_entity_ids_set:
                ids_to_delete = list(deleted_queue_entity_ids_set)
                if ids_to_delete:
                    placeholders_del = ','.join([f'${i+2}' for i in range(len(ids_to_delete))])
                    sql_delete_batch = f"DELETE FROM crafting_queues WHERE guild_id = $1 AND entity_id IN ({placeholders_del})"
                    try:
                        await self._db_service.adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete)))
                        logger.info("CraftingManager: Deleted %s crafting queues from DB for guild %s.", len(ids_to_delete), guild_id_str) # Changed
                        self._deleted_crafting_queue_ids.pop(guild_id_str, None)
                    except Exception as e:
                        logger.error("CraftingManager: Error deleting crafting queues for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            else:
                self._deleted_crafting_queue_ids.pop(guild_id_str, None)

            guild_queues_cache = self._crafting_queues.get(guild_id_str, {})
            queues_to_upsert_list: List[Dict[str, Any]] = [ qd for eid in list(dirty_queue_entity_ids_set) if (qd := guild_queues_cache.get(eid)) is not None ]

            if queues_to_upsert_list:
                 logger.info("CraftingManager: Upserting %s crafting queues for guild %s...", len(queues_to_upsert_list), guild_id_str) # Changed
                 upsert_sql = '''
                 INSERT INTO crafting_queues (entity_id, entity_type, guild_id, queue, state_variables)
                 VALUES ($1, $2, $3, $4, $5)
                 ON CONFLICT (entity_id) DO UPDATE SET
                    entity_type = EXCLUDED.entity_type, guild_id = EXCLUDED.guild_id,
                    queue = EXCLUDED.queue, state_variables = EXCLUDED.state_variables
                 '''
                 data_to_upsert = []
                 upserted_entity_ids: Set[str] = set()

                 for queue_data in queues_to_upsert_list:
                      try:
                           entity_id = queue_data.get('entity_id')
                           entity_type = queue_data.get('entity_type')
                           queue_guild_id = queue_data.get('guild_id')

                           if entity_id is None or entity_type is None or str(queue_guild_id) != guild_id_str:
                               logger.warning("CraftingManager: Skipping upsert for queue with invalid ID/Type ('%s', '%s') or mismatched guild ('%s') during save for guild %s. Expected guild %s.", entity_id, entity_type, queue_guild_id, guild_id_str, guild_id_str) # Changed
                               continue

                           queue_list = queue_data.get('queue', [])
                           state_variables = queue_data.get('state_variables', {})
                           if not isinstance(queue_list, list): queue_list = []
                           if not isinstance(state_variables, dict): state_variables = {}
                           queue_json = json.dumps(queue_list)
                           state_variables_json = json.dumps(state_variables)
                           data_to_upsert.append((str(entity_id), str(entity_type), guild_id_str, queue_json, state_variables_json))
                           upserted_entity_ids.add(str(entity_id))
                      except Exception as e:
                           logger.error("CraftingManager: Error preparing data for queue of entity %s (guild %s) for upsert: %s", queue_data.get('entity_id', 'N/A'), queue_data.get('guild_id', 'N/A'), e, exc_info=True) # Changed
                 if data_to_upsert:
                      if self._db_service is None or self._db_service.adapter is None:
                           logger.warning("CraftingManager: DB service or adapter is None during queue upsert batch for guild %s.", guild_id_str) # Changed
                      else:
                           await self._db_service.adapter.execute_many(upsert_sql, data_to_upsert)
                           logger.info("CraftingManager: Successfully upserted %s crafting queues for guild %s.", len(data_to_upsert), guild_id_str) # Changed
                           if guild_id_str in self._dirty_crafting_queues:
                                self._dirty_crafting_queues[guild_id_str].difference_update(upserted_entity_ids)
                                if not self._dirty_crafting_queues[guild_id_str]:
                                     del self._dirty_crafting_queues[guild_id_str]
            else: # No queues to upsert (dirty set might have been for queues now deleted)
                if dirty_queue_entity_ids_set: # If there were dirty IDs but no corresponding queues in cache
                    logger.warning("CraftingManager: Dirty queues %s for guild %s were not found in cache for saving.", dirty_queue_entity_ids_set, guild_id_str)
                # Clear the dirty set for the guild if it exists and is now empty or was for non-cached items
                if guild_id_str in self._dirty_crafting_queues:
                    self._dirty_crafting_queues[guild_id_str].clear() # Clear all, as those not found are no longer relevant
                    if not self._dirty_crafting_queues[guild_id_str]:
                        del self._dirty_crafting_queues[guild_id_str]


        except Exception as e:
            logger.error("CraftingManager: Error during saving state for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
        logger.info("CraftingManager: Save state complete for guild %s.", guild_id_str) # Changed

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("CraftingManager: Rebuilding runtime caches for guild %s...", guild_id_str) # Changed
        logger.info("CraftingManager: Runtime caches rebuilt for guild %s. Crafting queues count: %s", guild_id_str, len(self._crafting_queues.get(guild_id_str, {}))) # Changed

    def mark_queue_dirty(self, guild_id: str, entity_id: str) -> None:
         guild_id_str = str(guild_id)
         entity_id_str = str(entity_id)
         guild_queues_cache = self._crafting_queues.get(guild_id_str)
         if guild_queues_cache and entity_id_str in guild_queues_cache:
              self._dirty_crafting_queues.setdefault(guild_id_str, set()).add(entity_id_str)
         # else: logger.debug("CraftingManager: Attempted to mark non-existent crafting queue for entity %s in guild %s as dirty.", entity_id_str, guild_id_str) # Too noisy

    def mark_queue_deleted(self, guild_id: str, entity_id: str) -> None:
        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        guild_queues_cache = self._crafting_queues.get(guild_id_str)
        if guild_queues_cache and entity_id_str in guild_queues_cache:
            del guild_queues_cache[entity_id_str]
            logger.info("CraftingManager: Removed crafting queue for entity %s from cache for guild %s.", entity_id_str, guild_id_str) # Changed
            self._deleted_crafting_queue_ids.setdefault(guild_id_str, set()).add(entity_id_str)
            self._dirty_crafting_queues.get(guild_id_str, set()).discard(entity_id_str)
            logger.info("CraftingManager: Crafting queue for entity %s marked for deletion for guild %s.", entity_id_str, guild_id_str) # Changed
        elif guild_id_str in self._deleted_crafting_queue_ids and entity_id_str in self._deleted_crafting_queue_ids[guild_id_str]:
             logger.debug("CraftingManager: Crafting queue for entity %s in guild %s already marked for deletion.", entity_id_str, guild_id_str) # Changed
        else:
             logger.warning("CraftingManager: Attempted to mark non-existent crafting queue for entity %s in guild %s as deleted.", entity_id_str, guild_id_str) # Changed

    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         guild_id = kwargs.get('guild_id')
         if guild_id is None:
              logger.warning("CraftingManager: clean_up_for_entity called for %s %s without guild_id in context. Cannot clean up crafting queue.", entity_type, entity_id) # Changed
              return
         guild_id_str = str(guild_id)
         logger.info("CraftingManager: Cleaning up crafting queue for %s %s in guild %s...", entity_type, entity_id, guild_id_str) # Changed
         guild_queues_cache = self._crafting_queues.get(guild_id_str)
         if guild_queues_cache and entity_id in guild_queues_cache:
              self.mark_queue_deleted(guild_id_str, entity_id)
         # else: logger.debug("CraftingManager: No crafting queue found for %s %s in guild %s for cleanup.", entity_type, entity_id, guild_id_str) # Too noisy

logger.debug("--- CraftingManager module finished loading ---") # Changed
