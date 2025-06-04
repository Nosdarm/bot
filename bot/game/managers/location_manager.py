# bot/game/managers/location_manager.py

from __future__ import annotations
import json
import traceback
import asyncio
# --- Необходимые импорты для runtime ---
import uuid # uuid нужен для генерации ID инстансов

# --- Базовые типы и TYPE_CHECKING ---
# Set и другие типы нужны для аннотаций
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins

# --- Imports needed ONLY for Type Checking ---
if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
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
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator


# Define Callback Types
SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class LocationManager:
    """
    Менеджер для управления локациями игрового мира.
    Хранит статические шаблоны локаций и динамические инстансы (per-guild),
    обрабатывает триггеры OnEnter/OnExit.
    """
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]


    # --- Class-Level Attribute Annotations ---
    # Статические шаблоны локаций (теперь per-guild, соответствует предполагаемой схеме)
    _location_templates: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {tpl_id: data}}
    # Динамические инстансы (per-guild)
    _location_instances: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {instance_id: data}}
    # Наборы "грязных" и удаленных инстансов (per-guild)
    _dirty_instances: Dict[str, Set[str]] # {guild_id: {instance_id, ...}}
    _deleted_instances: Dict[str, Set[str]] # {guild_id: {instance_id, ...}}


    def __init__(
        self,
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        event_manager: Optional["EventManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        time_manager: Optional["TimeManager"] = None,
        send_callback_factory: Optional[SendCallbackFactory] = None,
        event_stage_processor: Optional["EventStageProcessor"] = None,
        event_action_processor: Optional["EventActionProcessor"] = None,
        on_enter_action_executor: Optional["OnEnterActionExecutor"] = None,
        stage_description_generator: Optional["StageDescriptionGenerator"] = None,
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
        self._on_enter_action_executor = on_enter_action_executor
        self._stage_description_generator = stage_description_generator

        self._location_templates = {}
        self._location_instances = {}
        self._dirty_instances = {}
        self._deleted_instances = {}

        print("LocationManager initialized.")

    # --- Методы для PersistenceManager ---
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает статические шаблоны локаций и динамические инстансы для гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Loading state for guild {guild_id_str} (static templates + instances)...")

        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"]
        if db_adapter is None:
             print(f"LocationManager: Database adapter is not available. Cannot load state for guild {guild_id_str}.")
             self._clear_guild_state_cache(guild_id_str)
             return # Let PM handle if critical

        self._clear_guild_state_cache(guild_id_str)

        guild_templates_cache: Dict[str, Dict[str, Any]] = self._location_templates.setdefault(guild_id_str, {})

        loaded_templates_count = 0
        try:
            # Corrected SQL query based on schema - template data is in 'properties' column
            # Using per-guild filter WHERE guild_id = ? as assumed for LocationManager
            sql_templates = "SELECT id, name, description, properties FROM location_templates WHERE guild_id = ?"
            # Passing guild_id parameter for fetchall on per-guild table
            rows_templates = await db_adapter.fetchall(sql_templates, (guild_id_str,))
            print(f"LocationManager: Found {len(rows_templates)} location template rows for guild {guild_id_str}.")
            for row in rows_templates:
                 tpl_id = row['id'] # Use direct access
                 tpl_data_json = row['properties'] # Use direct access
                 if tpl_id is None: # Should not happen if ID is PK and NOT NULL
                      print(f"LocationManager: Warning: Skipping template row with missing ID for guild {guild_id_str}. Row: {row}.");
                      continue
                 try:
                      data: Dict[str, Any] = json.loads(tpl_data_json or '{}') if isinstance(tpl_data_json, (str, bytes)) else {}
                      if not isinstance(data, dict):
                           print(f"LocationManager: Warning: Template data for template '{tpl_id}' is not a dictionary ({type(data)}) for guild {guild_id_str}. Skipping.");
                           continue
                      data['id'] = str(tpl_id) # Ensure string ID
                      data.setdefault('name', row['name'] if row['name'] is not None else str(tpl_id)) # Use direct access
                      data.setdefault('description', row['description'] if row['description'] is not None else "") # Use direct access
                      # Ensure exits/connected_locations are parsed correctly if they exist
                      exits = data.get('exits') or data.get('connected_locations') # .get() is fine for dict `data`
                      if isinstance(exits, str):
                           try: exits = json.loads(exits)
                           except (json.JSONDecodeError, TypeError): exits = {}
                      if not isinstance(exits, dict): exits = {}
                      data['exits'] = exits
                      data.pop('connected_locations', None)

                      # Store in per-guild cache
                      guild_templates_cache[str(tpl_id)] = data
                      loaded_templates_count += 1
                 except json.JSONDecodeError:
                     print(f"LocationManager: Error decoding template '{tpl_id}' for guild {guild_id_str}: {traceback.format_exc()}. Skipping template row.");
                 except Exception as e:
                      print(f"LocationManager: Error processing template row '{tpl_id}' for guild {guild_id_str}: {e}. Skipping."); traceback.print_exc();


            print(f"LocationManager: Loaded {loaded_templates_count} templates for guild {guild_id_str} from DB.")


        except Exception as e:
            print(f"LocationManager: ❌ Error during DB template load for guild {guild_id_str}: {e}"); traceback.print_exc();
            self._location_templates.pop(guild_id_str, None)
            raise

        # --- Загрузка динамических инстансов (per-guild) ---
        guild_instances_cache = self._location_instances.setdefault(guild_id_str, {})
        # dirty_instances set and deleted_instances set for this guild were cleared by _clear_guild_state_cache

        loaded_instances_count = 0

        try:
            # Added descriptions_i18n to SELECT
            sql_instances = '''
            SELECT id, template_id, name, description, descriptions_i18n, exits, state_variables, is_active, guild_id
            FROM locations WHERE guild_id = ?
            '''
            rows_instances = await db_adapter.fetchall(sql_instances, (guild_id_str,))
            if rows_instances:
                 print(f"LocationManager: Found {len(rows_instances)} instances for guild {guild_id_str}.")

                 for row in rows_instances:
                      try:
                           instance_id_raw = row['id']
                           loaded_guild_id_raw = row['guild_id']

                           if instance_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                                print(f"LocationManager: Warning: Skipping instance row with invalid ID ('{instance_id_raw}') or mismatched guild_id ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                                continue

                           instance_id = str(instance_id_raw)
                           template_id = str(row['template_id']) if row['template_id'] is not None else None

                           # name and description from DB are treated as potential i18n JSON strings
                           # or plain text for the default language. Location model handles this.
                           raw_name_from_db = row['name']
                           raw_description_from_db = row['description'] # This is for description_template_i18n

                           # Load instance-specific descriptions_i18n
                           descriptions_i18n_json = row.get('descriptions_i18n')
                           instance_descriptions_i18n_dict = {}
                           if isinstance(descriptions_i18n_json, str):
                               try:
                                   instance_descriptions_i18n_dict = json.loads(descriptions_i18n_json)
                               except json.JSONDecodeError:
                                   print(f"LocationManager: Warning: Invalid JSON in descriptions_i18n for instance {instance_id}. Treating as plain text for 'en'.")
                                   instance_descriptions_i18n_dict = {"en": descriptions_i18n_json}
                           elif isinstance(descriptions_i18n_json, dict): # Already a dict (e.g. if mock returns dict)
                                instance_descriptions_i18n_dict = descriptions_i18n_json

                           instance_exits_json = row['exits']
                           instance_state_json_raw = row['state_variables']
                           is_active = row['is_active'] if 'is_active' in row.keys() else 0

                           instance_state_data = json.loads(instance_state_json_raw or '{}') if isinstance(instance_state_json_raw, (str, bytes)) else {}
                           if not isinstance(instance_state_data, dict):
                               instance_state_data = {}
                               print(f"LocationManager: Warning: State data for instance ID {instance_id} not a dict ({type(instance_state_data)}) for guild {guild_id_str}. Resetting.")

                           instance_exits = json.loads(instance_exits_json or '{}') if isinstance(instance_exits_json, (str, bytes)) else {}
                           if not isinstance(instance_exits, dict):
                               instance_exits = {}
                               print(f"LocationManager: Warning: Exits data for instance ID {instance_id} not a dict ({type(instance_exits)}) for guild {guild_id_str}. Resetting.")

                           # Prepare data for Location.from_dict or direct cache
                           # The Location model's from_dict will handle creating name_i18n from raw_name_from_db
                           # and description_template_i18n from raw_description_from_db.
                           instance_data_for_model: Dict[str, Any] = {
                               'id': instance_id,
                               'guild_id': guild_id_str,
                               'template_id': template_id,
                               'name': raw_name_from_db, # Pass raw name, model converts to name_i18n
                               'description_template': raw_description_from_db, # Pass raw template desc
                               'descriptions_i18n': instance_descriptions_i18n_dict, # Parsed instance-specific descriptions
                               'exits': instance_exits,
                               'state': instance_state_data, # Renamed from 'state_variables' to 'state' for model
                               'is_active': bool(is_active),
                               # Include other fields from DB if Location model expects them directly
                               'static_name': row.get('static_name'),
                               'static_connections': row.get('static_connections')
                           }

                           # If caching dicts directly:
                           # guild_instances_cache[instance_id] = instance_data_for_model
                           # If caching Location objects (preferred for consistency):
                           from bot.game.models.location import Location # Local import
                           location_obj = Location.from_dict(instance_data_for_model)
                           guild_instances_cache[location_obj.id] = location_obj.to_dict() # Store as dict in cache for now to match existing type

                           # Validation (template existence check can remain the same)
                           if template_id is not None:
                               if not self.get_location_static(guild_id_str, template_id):
                                    print(f"LocationManager: Warning: Template '{template_id}' not found for instance '{instance_id}' in guild {guild_id_str} during load.")
                           else:
                                print(f"LocationManager: Warning: Instance ID {instance_id} missing template_id for guild {guild_id_str} during load.")
                                continue # Or handle as location without template

                           loaded_instances_count += 1

                      except json.JSONDecodeError:
                          print(f"LocationManager: Error decoding JSON for instance row (ID: {row.get('id', 'N/A')}, guild: {row.get('guild_id', 'N/A')}): {traceback.format_exc()}. Skipping instance row.");
                      except Exception as e:
                          print(f"LocationManager: Error processing instance row (ID: {row.get('id', 'N/A')}, guild: {row.get('guild_id', 'N/A')}): {e}. Skipping instance row."); traceback.print_exc();


                 print(f"LocationManager: Loaded {loaded_instances_count} instances for guild {guild_id_str}.")
            else: print(f"LocationManager: No instances found for guild {guild_id_str}.")

        except Exception as e:
            print(f"LocationManager: ❌ Error during DB instance load for guild {guild_id_str}: {e}"); traceback.print_exc();
            self._location_instances.pop(guild_id_str, None)
            self._dirty_instances.pop(guild_id_str, None)
            self._deleted_instances.pop(guild_id_str, None)
            raise

        print(f"LocationManager: Load state complete for guild {guild_id_str}.")

    async def generate_location_details_from_ai(self, guild_id: str, location_idea: str, existing_location_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Uses AI services to generate detailed location data.
        Args:
            guild_id: The ID of the guild.
            location_idea: A string concept for the new location.
            existing_location_id: Optional ID of an existing location to provide context or flesh out.

        Returns:
            A dictionary with structured, validated location data, or None on failure.
        """
        if not self._multilingual_prompt_generator or not self._openai_service or not self._ai_validator:
            print("LocationManager ERROR: AI services (PromptGen, OpenAI, Validator) not fully available.")
            return None

        print(f"LocationManager: Generating AI details for location concept '{location_idea}' in guild {guild_id}.")

        # 1. Generate prompt
        prompt_messages = self._multilingual_prompt_generator.generate_location_description_prompt(
            guild_id=guild_id,
            location_idea=location_idea,
            # Pass other relevant context if needed, e.g., surrounding locations, campaign theme
        )
        system_prompt = prompt_messages["system"]
        user_prompt = prompt_messages["user"]

        # 2. Call OpenAI service
        # TODO: Add specific settings for location generation if needed in self._settings
        location_gen_settings = self._settings.get("location_generation_ai_settings", {})
        max_tokens = location_gen_settings.get("max_tokens", 2000)
        temperature = location_gen_settings.get("temperature", 0.7)

        ai_response = await self._openai_service.generate_structured_multilingual_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

        if not ai_response or "error" in ai_response or not isinstance(ai_response.get("json_string"), str):
            error_detail = ai_response.get("error") if ai_response else "Unknown error or invalid format from AI service"
            raw_text = ai_response.get("raw_text", "") if ai_response else ""
            print(f"LocationManager ERROR: Failed to generate AI content for location '{location_idea}'. Error: {error_detail}")
            if raw_text: print(f"LocationManager: Raw AI response: {raw_text[:500]}...")
            return None

        generated_content_str = ai_response["json_string"]

        # 3. Validate AI response
        # TODO: Define "single_location" structure in AIResponseValidator and what existing IDs are relevant.
        # For now, using placeholders for existing IDs.
        validation_result = await self._ai_validator.validate_ai_response(
            ai_json_string=generated_content_str,
            expected_structure="single_location",
            existing_npc_ids=set(),      # Placeholder
            existing_quest_ids=set(),    # Placeholder
            existing_item_template_ids=set(), # Placeholder
            existing_location_template_ids=set(self._location_templates.get(guild_id, {}).keys()) # Pass existing location template IDs for context
        )

        if validation_result.get('global_errors'):
            print(f"LocationManager ERROR: AI content validation failed globally for location '{location_idea}': {validation_result['global_errors']}")
            return None

        if not validation_result.get('entities'): # Expecting one location entity
            print(f"LocationManager ERROR: AI content validation produced no entities for location '{location_idea}'.")
            return None

        location_validation_details = validation_result['entities'][0] # Assuming single_location returns one entity

        if location_validation_details.get('errors'):
            print(f"LocationManager WARNING: Validation errors for location '{location_idea}': {location_validation_details['errors']}")
        if location_validation_details.get('notifications'):
            print(f"LocationManager INFO: Validation notifications for location '{location_idea}': {location_validation_details['notifications']}")
        # If validation failed at any global step or produces no entities (handled above by returning None),
        # the caller (create_location_instance) will construct the error dictionary.
        # This method's responsibility is to return the validated data and moderation flag,
        # or None if critical validation steps (global, entity count) fail.

        validated_data = location_validation_details.get('validated_data')
        # Default to True if not present or if there were errors that imply moderation needed.
        requires_moderation = location_validation_details.get('requires_moderation', True)
        if location_validation_details.get('errors'):
            requires_moderation = True # Errors imply moderation is needed

        # Log errors and notifications regardless
        if location_validation_details.get('errors'):
            print(f"LocationManager WARNING: Validation errors for location '{location_idea}': {location_validation_details['errors']}")
        if location_validation_details.get('notifications'):
            print(f"LocationManager INFO: Validation notifications for location '{location_idea}': {location_validation_details['notifications']}")

        # Per subtask: if validation is successful, it should return a dictionary containing
        # both the validated_data and the requires_moderation flag.
        # "Successful" here means global checks passed and at least one entity was processed,
        # even if that entity has errors or its validated_data is None.
        # The case where validated_data is None but there were no global errors or entity count issues
        # means the validator decided the content was unsuitable but didn't fail validation entirely.
        print(f"LocationManager: Validation result for location '{location_idea}'. Requires Moderation: {requires_moderation}")
        return {
            "validated_data": validated_data,
            "requires_moderation": requires_moderation
        }

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет измененные/удаленные динамические инстансы локаций для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Saving state for guild {guild_id_str}...")

        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"]
        if db_adapter is None:
             print(f"LocationManager: Database adapter not available. Skipping save for guild {guild_id_str}.")
             return

        guild_instances_cache = self._location_instances.get(guild_id_str, {})
        dirty_instances_set = self._dirty_instances.get(guild_id_str, set()).copy()
        deleted_instances_set = self._deleted_instances.get(guild_id_str, set()).copy()


        if not dirty_instances_set and not deleted_instances_set:
            self._dirty_instances.pop(guild_id_str, None)
            self._deleted_instances.pop(guild_id_str, None)
            return

        print(f"LocationManager: Saving {len(dirty_instances_set)} dirty, {len(deleted_instances_set)} deleted instances for guild {guild_id_str}...")


        try:
            # Удалить помеченные для удаления инстансы для этого guild_id
            if deleted_instances_set:
                 ids_to_delete = list(deleted_instances_set)
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 sql_delete_batch = f"DELETE FROM locations WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await db_adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete)));
                 print(f"LocationManager: Deleted {len(ids_to_delete)} instances from DB for guild {guild_id_str}.")
                 self._deleted_instances.pop(guild_id_str, None)


            # Обновить или вставить измененные инстансы для этого guild_id
            instances_to_upsert_list = [inst for id_key in list(dirty_instances_set) if (inst := guild_instances_cache.get(id_key)) is not None]

            if instances_to_upsert_list:
                 print(f"LocationManager: Upserting {len(instances_to_upsert_list)} instances for guild {guild_id_str}...")
                 # Added descriptions_i18n to SQL
                 upsert_sql = '''
                 INSERT OR REPLACE INTO locations (
                     id, guild_id, template_id, name, description, descriptions_i18n,
                     exits, state_variables, is_active
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                 ''' # 9 columns
                 data_to_upsert = []
                 upserted_instance_ids: Set[str] = set()

                 for instance_data_dict in instances_to_upsert_list: # instance_data_dict is a dict from cache
                      try:
                          instance_id = instance_data_dict.get('id')
                          instance_guild_id = instance_data_dict.get('guild_id')

                          if instance_id is None or str(instance_guild_id) != guild_id_str:
                              print(f"LocationManager: Warning: Skipping upsert for instance with invalid ID ('{instance_id}') or mismatched guild ('{instance_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                              continue

                          template_id = instance_data_dict.get('template_id')

                          # name_i18n from model/cache should be used for 'name' column (as JSON string)
                          # description_template_i18n for 'description' column (as JSON string)
                          name_i18n_dict = instance_data_dict.get('name_i18n', {"en": instance_id})
                          desc_template_i18n_dict = instance_data_dict.get('description_template_i18n', {"en": ""})

                          # This is the new instance-specific descriptions_i18n
                          instance_descriptions_i18n_dict = instance_data_dict.get('descriptions_i18n', {})

                          instance_exits = instance_data_dict.get('exits', {})
                          # 'state_variables' in DB, 'state' in model/cache dict
                          state_variables = instance_data_dict.get('state', instance_data_dict.get('state_variables', {}))
                          is_active = instance_data_dict.get('is_active', True)

                          if not isinstance(state_variables, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} state_variables is not a dict ({type(state_variables)}) for guild {guild_id_str}. Saving as empty dict.")
                              state_variables = {}
                          if not isinstance(instance_exits, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} exits is not a dict ({type(instance_exits)}) for guild {guild_id_str}. Saving as empty dict.")
                              instance_exits = {}
                          if not isinstance(instance_descriptions_i18n_dict, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} descriptions_i18n is not a dict ({type(instance_descriptions_i18n_dict)}). Saving as empty dict.")
                              instance_descriptions_i18n_dict = {}


                          data_to_upsert.append((
                              str(instance_id), # id
                              guild_id_str,     # guild_id
                              str(template_id) if template_id is not None else None, # template_id
                              json.dumps(name_i18n_dict),               # name (stores name_i18n JSON)
                              json.dumps(desc_template_i18n_dict),      # description (stores template_description_i18n JSON)
                              json.dumps(instance_descriptions_i18n_dict), # descriptions_i18n (stores instance specific i18n JSON)
                              json.dumps(instance_exits),               # exits
                              json.dumps(state_variables),              # state_variables
                              int(bool(is_active)),                     # is_active
                          ));
                          upserted_instance_ids.add(str(instance_id))

                      except Exception as e:
                          print(f"LocationManager: Error preparing data for instance {instance_data.get('id', 'N/A')} (guild {instance_data.get('guild_id', 'N/A')}) for upsert: {e}"); traceback.print_exc();

                 if data_to_upsert:
                     try:
                         await db_adapter.execute_many(upsert_sql, data_to_upsert);
                         print(f"LocationManager: Successfully upserted {len(data_to_upsert)} instances for guild {guild_id_str}.")
                         if guild_id_str in self._dirty_instances:
                              self._dirty_instances[guild_id_str].difference_update(upserted_instance_ids)
                              if not self._dirty_instances[guild_id_str]:
                                   del self._dirty_instances[guild_id_str]

                     except Exception as e:
                          print(f"LocationManager: Error during batch upsert for guild {guild_id_str}: {e}"); traceback.print_exc();


        except Exception as e:
             print(f"LocationManager: ❌ Error during saving state for guild {guild_id_str}: {e}"); traceback.print_exc();


        print(f"LocationManager: Save state complete for guild {guild_id_str}.")


    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Rebuilding runtime caches for guild {guild_id_str}. (Placeholder)")

        print(f"LocationManager: Rebuild runtime caches complete for guild {guild_id_str}.")


    # --- Dynamic Instance Management ---
    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None, instance_name: Optional[str] = None, instance_description: Optional[str] = None, instance_exits: Optional[Dict[str, str]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
         """Создает динамический инстанс локации из шаблона для определенной гильдии."""
         guild_id_str = str(guild_id)
         print(f"LocationManager: Creating instance for guild {guild_id_str} from template {template_id} in memory...")

         guild_templates = self._location_templates.get(guild_id_str, {})
         template = guild_templates.get(str(template_id))

         if not template:
             print(f"LocationManager: Error creating instance: Template '{template_id}' not found for guild {guild_id_str}.")
             return None
         if not template.get('name'):
             print(f"LocationManager: Warning: Template '{template_id}' missing 'name' for guild {guild_id_str}. Using template ID as name.")

         new_instance_id = str(uuid.uuid4())

         template_initial_state = template.get('initial_state', {})
         if not isinstance(template_initial_state, dict): template_initial_state = {}
         instance_state_data = dict(template_initial_state)
         if initial_state is not None:
             if isinstance(initial_state, dict): instance_state_data.update(initial_state)
             else: print(f"LocationManager: Warning: Provided initial_state is not a dict. Ignoring.")

         resolved_instance_name = instance_name if instance_name is not None else template.get('name', str(template_id))
         resolved_instance_description = instance_description if instance_description is not None else template.get('description', "")
         resolved_instance_exits = instance_exits if instance_exits is not None else template.get('exits', {})
         if not isinstance(resolved_instance_exits, dict):
              print(f"LocationManager: Warning: Resolved instance exits is not a dict ({type(resolved_instance_exits)}). Using {{}}.")
              resolved_instance_exits = {}

         instance_for_cache: Dict[str, Any] = {
             'id': new_instance_id,
             'guild_id': guild_id_str,
             'template_id': str(template_id),
             'name': str(resolved_instance_name) if resolved_instance_name is not None else None,
             'description': str(resolved_instance_description) if resolved_instance_description is not None else None,
             'exits': resolved_instance_exits,
             'state': instance_state_data,
             'is_active': True,
         }
            # If generate_location_details_from_ai returned None (global validation failure, no entities)
            # or if it returned a dict that has an "error" key.
            if ai_response_data is None or ai_response_data.get("error"):
                error_msg = "AI generation failed or content validation produced critical errors."
                if isinstance(ai_response_data, dict) and ai_response_data.get("error"):
                    error_msg = ai_response_data["error"]

                print(f"LocationManager: AI generation failed for concept '{location_concept}'. Error: {error_msg}. Instance creation aborted.")
                return {"error": error_msg, "requires_moderation": True}

            ai_generated_data = ai_response_data.get("validated_data") # This could be None
            requires_moderation = ai_response_data.get("requires_moderation", True) # Default to True

            if requires_moderation:
                if ai_generated_data is None:
                    print(f"LocationManager: AI generation for '{location_concept}' requires moderation, but no validated data was returned by the validator. Aborting.")
                    return {"error": "AI data requires moderation, but no content was validated for submission.", "requires_moderation": True}

                user_id = kwargs.get('user_id')
                if user_id is None: # Ensure user_id is present
                    print(f"LocationManager: CRITICAL - user_id not found in kwargs for AI location generation needing moderation. Aborting.")
                    # Logged as critical, return error structure
                    return {"error": "User ID not found for moderation process. Location creation aborted.", "requires_moderation": True}

                user_id_str = str(user_id)
                request_id = str(uuid.uuid4())
                content_type = 'location'

                try:
                    # Ensure self._db_adapter is available
                    if not self._db_adapter:
                        print(f"LocationManager: ERROR - DB adapter not available. Cannot save AI location for moderation.")
                        return {"error": "Database service unavailable. Moderation request cannot be saved.", "requires_moderation": True}

                    data_json = json.dumps(ai_generated_data)
                    await self._db_adapter.save_pending_moderation_request(
                        request_id, guild_id_str, user_id_str, content_type, data_json
                    )
                    print(f"LocationManager: AI-generated location data for '{location_concept}' (User: {user_id_str}) saved for moderation. Request ID: {request_id}")

                    # Send notification to Master channel (TODO)
                    print(f"TODO: Send notification to Master channel about moderation request {request_id} for location generated by {user_id_str}")

                    # Change player status
                    if self._status_manager:
                        target_id_for_status = user_id_str
                        target_type_for_status = 'player' # Default to 'player' as per subtask

                        # Try to get character_id if CharacterManager is available
                        if self._character_manager:
                            try:
                                player_char = await self._character_manager.get_character_by_discord_id(
                                    discord_user_id=int(user_id_str), # Requires int
                                    guild_id=guild_id_str
                                )
                                if player_char and hasattr(player_char, 'id'):
                                    target_id_for_status = player_char.id
                                    target_type_for_status = 'Character' # More specific
                                else:
                                    print(f"LocationManager: Could not find Character for user_id {user_id_str}. Applying status to 'player' ID directly.")
                            except ValueError:
                                print(f"LocationManager: ERROR - user_id '{user_id_str}' is not a valid integer for Character lookup. Applying status to 'player' ID.")
                            except Exception as e_char_lookup:
                                print(f"LocationManager: Error looking up character for status application: {e_char_lookup}. Applying status to 'player' ID.")

                        try:
                            status_context = kwargs.get('context', {}) # Pass existing context if any
                            await self._status_manager.add_status_effect_to_entity(
                                target_id=str(target_id_for_status),
                                target_type=target_type_for_status,
                                status_type='waiting_moderation',
                                guild_id=guild_id_str,
                                duration='permanent', # As per subtask
                                source_id='ai_generation_location', # Specific source
                                context=status_context
                            )
                            print(f"LocationManager: Status 'waiting_moderation' applied to {target_type_for_status} {target_id_for_status} (User: {user_id_str}) for request {request_id}.")
                        except Exception as e_status:
                            print(f"LocationManager: ERROR applying 'waiting_moderation' status to {target_type_for_status} {target_id_for_status} (User: {user_id_str}): {e_status}")
                            traceback.print_exc() # Log full error for status failure
                    else:
                        print("LocationManager: StatusManager not available. Cannot apply 'waiting_moderation' status.")

                    return {"status": "pending_moderation", "request_id": request_id, "message": "Ваш запрос на создание локации принят и ожидает одобрения Мастером."}

                except json.JSONDecodeError as e_json:
                    print(f"LocationManager: ERROR - Failed to serialize AI location data for moderation: {e_json}")
                    traceback.print_exc()
                    return {"error": "Internal error: Failed to process AI data for moderation.", "requires_moderation": True}
                except Exception as e_mod_save: # Catch other potential errors during DB save or status
                    print(f"LocationManager: ERROR saving AI location content for moderation or applying status: {e_mod_save}")
                    traceback.print_exc()
                    return {"error": "Failed to save content for moderation due to an internal error.", "requires_moderation": True}

            else: # requires_moderation is false (content is auto-approved)
                if ai_generated_data is None:
                    print(f"LocationManager: ERROR - AI location for '{location_concept}' was auto-approved but no validated data was returned. Aborting.")
                    return {"error": "AI data was auto-approved but no content was validated. This is an inconsistent state.", "requires_moderation": True}

                print(f"LocationManager: AI-generated location for '{location_concept}' is auto-approved.")
                source_data = ai_generated_data # Use the validated, auto-approved data
                is_ai_auto_approved_flow = True

        # This block executes if not trigger_ai_generation (using campaign_template_data)
        # OR if AI generation was auto-approved (source_data is set to ai_generated_data).
        if source_data is None:
            # This should ideally not be reached if logic above is correct.
            # If non-AI, campaign_template_data should have been used, or AI triggered if not found.
            # If AI, auto-approved path ensures ai_generated_data (now source_data) is not None.
            print(f"LocationManager: CRITICAL - No source_data available for instance creation. Concept: '{location_concept}'. This indicates a flaw in control flow.")
            return {"error": "Internal error: Could not determine data source for location creation.", "requires_moderation": True}

        # --- Common instance creation logic starts here ---
        new_instance_id = str(uuid.uuid4())
        instance_for_cache: Dict[str, Any] = {
            'id': new_instance_id,
            'guild_id': guild_id_str,
            'is_active': True,
            'state': {},
        }

        # Populate instance_for_cache using source_data
         # Template ID: From source if available, else use original template_id_str or a generated one for AI
         instance_for_cache['template_id'] = source_data.get('template_id', source_data.get('id'))
         if not instance_for_cache['template_id']: # Fallback if 'id' also missing in source_data (unlikely for valid template/AI data)
            instance_for_cache['template_id'] = template_id_str if not trigger_ai_generation else f"AI_gen_{new_instance_id[:8]}"


         # Name: source_data (name_i18n or name)
         instance_for_cache['name_i18n'] = source_data.get('name_i18n', {"en": source_data.get('name', f"Location {new_instance_id[:6]}")})

         # Description: source_data (description_i18n, description_template_i18n, or description)
         desc_key_options = ['description_i18n', 'description_template_i18n']
         desc_val = None
         for key_opt in desc_key_options:
             if key_opt in source_data and isinstance(source_data[key_opt], dict):
                 desc_val = source_data[key_opt]
                 break
         if not desc_val and 'description' in source_data: # Fallback to plain description
             desc_val = {"en": source_data['description']}
         instance_for_cache['description_i18n'] = desc_val if desc_val else {"en": "A generated location."}


         # Exits: source_data
         instance_for_cache['exits'] = source_data.get('exits', {})
         if not isinstance(instance_for_cache['exits'], dict):
             print(f"LocationManager: Warning: Exits from source for instance '{new_instance_id}' is not a dict. Using {{}}.")
             instance_for_cache['exits'] = {}

         # Initial State: source_data (initial_state or state_variables)
         base_initial_state = source_data.get('initial_state', source_data.get('state_variables', {}))
         if isinstance(base_initial_state, dict):
             instance_for_cache['state'].update(base_initial_state)
         else:
             print(f"LocationManager: Warning: Base initial state for instance '{new_instance_id}' is not a dict. Using {{}}.")


         # Layer explicit overrides from method arguments (for non-AI or even for AI if desired for some fields)
         if initial_state is not None and isinstance(initial_state, dict):
             instance_for_cache['state'].update(initial_state)
         elif initial_state is not None:
             print(f"LocationManager: Warning: Provided initial_state override is not a dict. Ignoring.")

         if instance_name is not None:
             instance_for_cache['name_i18n'] = {"en": instance_name}

         if instance_description is not None:
             instance_for_cache['description_i18n'] = {"en": instance_description}

         if instance_exits is not None and isinstance(instance_exits, dict):
             instance_for_cache['exits'] = instance_exits
         elif instance_exits is not None:
             print(f"LocationManager: Warning: Provided instance_exits override is not a dict. Ignoring.")


         self._location_instances.setdefault(guild_id_str, {})[new_instance_id] = instance_for_cache
         self._dirty_instances.setdefault(guild_id_str, set()).add(new_instance_id)

         print(f"LocationManager: Instance {new_instance_id} created and added to cache and marked dirty for guild {guild_id_str}. Template: {template_id}, Name: '{resolved_instance_name}'.")


         return instance_for_cache
         if is_ai_auto_approved_flow:
             user_id_for_db = kwargs.get('user_id') # Already fetched and validated if moderation path was taken
             if user_id_for_db is None: # Should not happen if logic is correct, but as a safeguard
                 print(f"LocationManager: CRITICAL - user_id is None for auto-approved AI flow for instance {new_instance_id}. Cannot log to DB or trigger post-save logic.")
             else:
                 user_id_str_for_db = str(user_id_for_db)
                 if self._db_adapter:
                     try:
                         await self._db_adapter.add_generated_location(new_instance_id, guild_id_str, user_id_str_for_db)
                         print(f"LocationManager: Auto-approved AI Instance {new_instance_id} ('{log_name}') by user {user_id_str_for_db} logged in generated_locations.")
                     except Exception as e_db_log:
                         print(f"LocationManager: ERROR logging auto-approved AI location {new_instance_id} to DB: {e_db_log}")
                         traceback.print_exc()
                 else:
                     print(f"LocationManager: WARNING - DB adapter not available. Cannot log auto-approved AI location {new_instance_id} to generated_locations.")

                 # --- Call logic for loading generated content (14) ---
                 # This corresponds to handle_entity_arrival for the character who generated it.
                 print(f"TODO: Trigger post-save logic (14) for auto-approved location {new_instance_id}") # As per subtask
                 if self._character_manager:
                     try:
                         player_char = await self._character_manager.get_character_by_discord_id(
                             discord_user_id=int(user_id_str_for_db),
                             guild_id=guild_id_str
                         )
                         if player_char and hasattr(player_char, 'id'):
                             arrival_context = {
                                 'guild_id': guild_id_str,
                                 'player_id': player_char.id,
                                 'character': player_char,
                                 'location_manager': self,
                                 'character_manager': self._character_manager,
                                 'npc_manager': self._npc_manager,
                                 'item_manager': self._item_manager,
                                 'event_manager': self._event_manager,
                                 'status_manager': self._status_manager,
                                 'rule_engine': self._rule_engine,
                                 'time_manager': self._time_manager,
                                 'send_callback_factory': self._send_callback_factory,
                                 'location_instance_data': instance_for_cache,
                                 'event_stage_processor': self._event_stage_processor,
                                 'event_action_processor': self._event_action_processor,
                                 'on_enter_action_executor': self._on_enter_action_executor,
                                 'stage_description_generator': self._stage_description_generator,
                                 **(kwargs.get('context', {})) # Merge original context
                             }
                             print(f"LocationManager: Triggering handle_entity_arrival for character {player_char.id} at auto-approved location {new_instance_id}.")
                             await self.handle_entity_arrival(
                                 location_id=new_instance_id,
                                 entity_id=player_char.id,
                                 entity_type='Character',
                                 **arrival_context
                             )
                         else:
                             print(f"LocationManager: WARNING - Could not find Character for user_id {user_id_str_for_db} for post-save logic (handle_entity_arrival) on auto-approved location {new_instance_id}.")
                     except ValueError:
                         print(f"LocationManager: WARNING - Invalid user_id format '{user_id_str_for_db}' for post-save logic on auto-approved location {new_instance_id}.")
                     except Exception as e_arrival:
                         print(f"LocationManager: ERROR during post-save logic (handle_entity_arrival) for auto-approved location {new_instance_id}: {e_arrival}")
                         traceback.print_exc()
                 else:
                     print(f"LocationManager: WARNING - CharacterManager not available. Cannot execute post-save logic (handle_entity_arrival) for auto-approved location {new_instance_id}.")

             print(f"LocationManager: Instance {new_instance_id} ('{log_name}') created from auto-approved AI data, added to cache, marked dirty.")
         else: # Non-AI path (campaign template)
             print(f"LocationManager: Instance {new_instance_id} ('{log_name}') created from campaign template, added to cache, marked dirty.")

         return instance_for_cache # This is returned for non-AI path and auto-approved AI path.

    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
         """Получить динамический инстанс локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         guild_instances = self._location_instances.get(guild_id_str, {})
         return guild_instances.get(str(instance_id))


    async def delete_location_instance(self, guild_id: str, instance_id: str, **kwargs: Any) -> bool:
        """Пометить динамический инстанс локации для удаления для данной гильдии."""
        guild_id_str = str(guild_id)
        instance_id_str = str(instance_id)
        print(f"LocationManager: Marking instance {instance_id_str} for deletion for guild {guild_id_str}...")

        guild_instances_cache = self._location_instances.get(guild_id_str, {})
        instance_to_delete = guild_instances_cache.get(instance_id_str)

        if instance_to_delete:
             cleanup_context = {**kwargs, 'guild_id': guild_id_str, 'location_instance_id': instance_id_str, 'location_instance_data': instance_to_delete}
             await self.clean_up_location_contents(instance_id_str, **cleanup_context)

             del guild_instances_cache[instance_id_str]
             print(f"LocationManager: Removed instance {instance_id_str} from cache for guild {guild_id_str}.")

             self._deleted_instances.setdefault(guild_id_str, set()).add(instance_id_str)
             self._dirty_instances.get(guild_id_str, set()).discard(instance_id_str)

             print(f"LocationManager: Instance {instance_id_str} marked for deletion for guild {guild_id_str}.")
             return True
        print(f"LocationManager: Warning: Attempted to delete non-existent instance {instance_id_str} for guild {guild_id_str}.")
        return False


    async def clean_up_location_contents(self, location_instance_id: str, **kwargs: Any) -> None:
         """Очищает сущности и предметы, находящиеся в указанном инстансе локации, при удалении локации."""
         guild_id = kwargs.get('guild_id')
         if not guild_id: print("LocationManager: Warning: guild_id missing in context for clean_up_location_contents."); return
         guild_id_str = str(guild_id)
         print(f"LocationManager: Cleaning up contents of location instance {location_instance_id} in guild {guild_id_str}...")

         char_manager = kwargs.get('character_manager', self._character_manager)
         npc_manager = kwargs.get('npc_manager', self._npc_manager)
         item_manager = kwargs.get('item_manager', self._item_manager)
         party_manager = kwargs.get('party_manager', self._party_manager)
         event_manager = kwargs.get('event_manager', self._event_manager)


         cleanup_context = {**kwargs, 'location_instance_id': location_instance_id}

         if char_manager and hasattr(char_manager, 'get_characters_in_location') and hasattr(char_manager, 'remove_character'):
              characters_to_remove = char_manager.get_characters_in_location(guild_id_str, location_instance_id, **cleanup_context)
              print(f"LocationManager: Found {len(characters_to_remove)} characters in location {location_instance_id} for guild {guild_id_str}.")
              for char in list(characters_to_remove):
                   char_id = getattr(char, 'id', None)
                   if char_id:
                        try:
                             await char_manager.remove_character(char_id, guild_id_str, **cleanup_context)
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error removing character {char_id} from location {location_instance_id} for guild {guild_id_str}.");


         if npc_manager and hasattr(npc_manager, 'get_npcs_in_location') and hasattr(npc_manager, 'remove_npc'):
              npcs_to_remove = npc_manager.get_npcs_in_location(guild_id_str, location_instance_id, **cleanup_context)
              print(f"LocationManager: Found {len(npcs_to_remove)} NPCs in location {location_instance_id} for guild {guild_id_str}.")
              for npc in list(npcs_to_remove):
                   npc_id = getattr(npc, 'id', None)
                   if npc_id:
                        try:
                             await npc_manager.remove_npc(guild_id_str, npc_id, **cleanup_context)
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error removing NPC {npc_id} from location {location_instance_id} for guild {guild_id_str}.");


         if item_manager and hasattr(item_manager, 'remove_items_by_location'):
              try:
                   await item_manager.remove_items_by_location(location_instance_id, guild_id_str, **cleanup_context)
                   print(f"LocationManager: Removed items from location {location_instance_id} for guild {guild_id_str}.")
              except Exception: traceback.print_exc(); print(f"LocationManager: Error removing items from location {location_instance_id} for guild {guild_id_str}.");

         if event_manager and hasattr(event_manager, 'get_events_in_location') and hasattr(event_manager, 'cancel_event'):
              events_in_loc = event_manager.get_events_in_location(guild_id_str, location_instance_id, **cleanup_context)
              print(f"LocationManager: Found {len(events_in_loc)} events in location {location_instance_id} for guild {guild_id_str}.")
              for event in list(events_in_loc):
                   event_id = getattr(event, 'id', None)
                   if event_id:
                        try:
                             await event_manager.cancel_event(event_id, guild_id_str, **cleanup_context)
                             print(f"LocationManager: Cancelled event {event_id} in location {location_instance_id} for guild {guild_id_str}.")
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error cancelling event {event_id} in location {location_instance_id} for guild {guild_id_str}.");


         if party_manager and hasattr(party_manager, 'get_parties_in_location') and hasattr(party_manager, 'disband_party'):
              parties_in_loc = party_manager.get_parties_in_location(guild_id_str, location_instance_id, **cleanup_context)
              print(f"LocationManager: Found {len(parties_in_loc)} parties in location {location_instance_id} for guild {guild_id_str}.")
              for party in list(parties_in_loc):
                   party_id = getattr(party, 'id', None)
                   if party_id:
                        try:
                             await party_manager.disband_party(party_id, guild_id_str, **cleanup_context)
                             print(f"LocationManager: Disbanded party {party_id} in location {location_instance_id} for guild {guild_id_str}.")
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error disbanding party {party_id} in location {location_instance_id} for guild {guild_id_str}.");


         print(f"LocationManager: Cleanup of contents complete for location instance {location_instance_id} in guild {guild_id_str}.")


    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]:
         """Получить название инстанса локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         instance = self.get_location_instance(guild_id_str, instance_id)
         if instance:
             instance_name = instance.get('name')
             if instance_name is not None:
                 return str(instance_name)

             template_id = instance.get('template_id')
             template = self.get_location_static(guild_id_str, template_id)
             if template and template.get('name') is not None:
                  return str(template['name'])

         if isinstance(instance_id, str):
             return f"Unknown Location ({instance_id[:6]})"
         return None

    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]:
         """Получить связанные локации (выходы) для инстанса локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         instance = self.get_location_instance(guild_id_str, instance_id)
         if instance:
              instance_exits = instance.get('exits')
              if instance_exits is not None:
                  if isinstance(instance_exits, dict):
                       return {str(k): str(v) for k, v in instance_exits.items()}
                  print(f"LocationManager: Warning: Instance {instance_id} exits data is not a dict ({type(instance_exits)}) for guild {guild_id_str}. Falling back to template exits.")


              template_id = instance.get('template_id')
              template = self.get_location_static(guild_id_str, template_id)
              if template:
                  template_exits = template.get('exits')
                  if template_exits is None:
                       template_exits = template.get('connected_locations')

                  if isinstance(template_exits, dict):
                       return {str(k): str(v) for k, v in template_exits.items()}
                  if isinstance(template_exits, list):
                       return {str(loc_id): str(loc_id) for loc_id in template_exits if loc_id is not None}
                  if template_exits is not None:
                       print(f"LocationManager: Warning: Template {template_id} exits data is not a dict or list ({type(template_exits)}) for instance {instance_id} in guild {guild_id_str}. Returning {{}}.")


         return {}

    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any], **kwargs: Any) -> bool:
        """Обновляет динамическое состояние инстанса локации для данной гильдии."""
        guild_id_str = str(guild_id)
        instance_data = self.get_location_instance(guild_id_str, instance_id)
        if instance_data:
            current_state = instance_data.setdefault('state', {})
            if not isinstance(current_state, dict):
                print(f"LocationManager: Warning: Instance {instance_data.get('id', 'N/A')} state is not a dict ({type(current_state)}) for guild {guild_id_str}. Resetting to {{}}.")
                current_state = {}
                instance_data['state'] = current_state

            if isinstance(state_updates, dict):
                 current_state.update(state_updates)
                 self._dirty_instances.setdefault(guild_id_str, set()).add(instance_data['id'])
                 print(f"LocationManager: Updated state for instance {instance_data['id']} for guild {guild_id_str}. Marked dirty.")
                 return True
            else:
                 print(f"LocationManager: Warning: state_updates is not a dict ({type(state_updates)}) for instance {instance_id} in guild {guild_id_str}. Ignoring update.")
                 return False


        print(f"LocationManager: Warning: Attempted to update state for non-existent instance {instance_id} for guild {guild_id_str}.")
        return False


    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]:
        """Получить ID канала для инстанса локации для данной гильдии."""
        guild_id_str = str(guild_id)
        instance = self.get_location_instance(guild_id_str, instance_id)
        if instance:
            template_id = instance.get('template_id')
            template = self.get_location_static(guild_id_str, template_id)
            if template and template.get('channel_id') is not None:
                 channel_id_raw = template['channel_id']
                 try:
                      return int(channel_id_raw)
                 except (ValueError, TypeError):
                      print(f"LocationManager: Warning: Invalid channel_id '{channel_id_raw}' in template {template.get('id', 'N/A')} for instance {instance_id} in guild {guild_id_str}. Expected integer.");
                      return None
        return None

    def get_default_location_id(self, guild_id: str) -> Optional[str]:
        """Получить ID дефолтной начальной локации для данной гильдии."""
        guild_id_str = str(guild_id)
        guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
        default_id = guild_settings.get('default_start_location_id')
        if default_id is None:
             default_id = self._settings.get('default_start_location_id')

        if isinstance(default_id, (str, int)):
             default_id_str = str(default_id)
             if self.get_location_instance(guild_id_str, default_id_str):
                 print(f"LocationManager: Found default start location instance ID '{default_id_str}' in settings for guild {guild_id_str}.")
                 return default_id_str
             else:
                 print(f"LocationManager: Warning: Default start location instance ID '{default_id_str}' found in settings for guild {guild_id_str}, but no corresponding instance exists.")
                 return None

        print(f"LocationManager: Warning: Default start location setting ('default_start_location_id') not found or is invalid for guild {guild_id_str}.")
        return None

    async def move_entity(
        self,
        guild_id: str,
        entity_id: str,
        entity_type: str,
        from_location_id: Optional[str],
        to_location_id: str,
        **kwargs: Any,
    ) -> bool:
        """Универсальный метод для перемещения сущности (Character/NPC/Item/Party) между инстансами локаций для данной гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Attempting to move {entity_type} {entity_id} for guild {guild_id_str} from {from_location_id} to {to_location_id}.")

        target_instance = self.get_location_instance(guild_id_str, to_location_id)
        if not target_instance:
             print(f"LocationManager: Error: Target location instance '{to_location_id}' not found for guild {guild_id_str}. Cannot move {entity_type} {entity_id}.")
             send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
             channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
             if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Целевая локация `{to_location_id}` не найдена.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback for move failure: {cb_e}")
             return False

        mgr: Optional[Any] = None
        update_location_method_name: Optional[str] = None
        manager_attr_name: Optional[str] = None

        if entity_type == 'Character':
            mgr = kwargs.get('character_manager', self._character_manager)
            update_location_method_name = 'update_character_location'
            manager_attr_name = '_character_manager'
        elif entity_type == 'NPC':
            mgr = kwargs.get('npc_manager', self._npc_manager)
            update_location_method_name = 'update_npc_location'
            manager_attr_name = '_npc_manager'
        elif entity_type == 'Item':
             mgr = kwargs.get('item_manager', self._item_manager)
             update_location_method_name = 'update_item_location'
             manager_attr_name = '_item_manager'
        # TODO: Add other entity types like 'Party'
        # elif entity_type == 'Party':
        #      mgr = kwargs.get('party_manager', self._party_manager)
        #      update_location_method_name = 'update_party_location'
        #      manager_attr_name = '_party_manager'
        # TODO: Add other entity types like 'Party'
        # elif entity_type == 'Party':
        #      mgr = kwargs.get('party_manager', self._party_manager)
        #      update_location_method_name = 'update_party_location'
        #      manager_attr_name = '_party_manager'
        else:
            print(f"LocationManager: Error: Movement not supported for entity type {entity_type} for guild {guild_id_str}.")
            send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
            channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
            if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Перемещение сущностей типа `{entity_type}` не поддерживается.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")
            return False

        if not mgr or not hasattr(mgr, update_location_method_name):
            print(f"LocationManager: Error: No suitable manager ({manager_attr_name} or via kwargs) or update method ('{update_location_method_name}') found for entity type {entity_type} for guild {guild_id_str}.")
            send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
            channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
            if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Внутренняя ошибка сервера (не найден обработчик для {entity_type}).")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")

            return False

        movement_context: Dict[str, Any] = {
            **kwargs,
            'guild_id': guild_id_str,
            'entity_id': entity_id,
            'entity_type': entity_type,
            'from_location_instance_id': from_location_id,
            'to_location_instance_id': to_location_id,
            'location_manager': self,
        }
        critical_managers = {
            'rule_engine': self._rule_engine, 'event_manager': self._event_manager,
            'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
            'item_manager': self._item_manager, 'combat_manager': self._combat_manager,
            'status_manager': self._status_manager, 'party_manager': self._party_manager,
            'time_manager': self._time_manager, 'send_callback_factory': self._send_callback_factory,
            'event_stage_processor': self._event_stage_processor, 'event_action_processor': self._event_action_processor,
            'on_enter_action_executor': self._on_enter_action_executor, 'stage_description_generator': self._stage_description_generator,
        }
        for mgr_name, mgr_instance in critical_managers.items():
             if mgr_instance is not None and mgr_name not in movement_context:
                  movement_context[mgr_name] = mgr_instance


        if from_location_id:
            from_instance_data = self.get_location_instance(guild_id_str, from_location_id)
            departure_context = {**movement_context, 'location_instance_data': from_instance_data}
            await self.handle_entity_departure(from_location_id, entity_id, entity_type, **departure_context)

        try:
            await getattr(mgr, update_location_method_name)(
                 entity_id,
                 to_location_id,
                 context=movement_context
            )
            await getattr(mgr, update_location_method_name)(
                 entity_id,
                 to_location_id,
                 context=movement_context
            )
            print(f"LocationManager: Successfully updated location for {entity_type} {entity_id} to {to_location_id} for guild {guild_id_str} via {type(mgr).__name__}.")
        except Exception as e:
             print(f"LocationManager: ❌ Error updating location for {entity_type} {entity_id} to {to_location_id} for guild {guild_id_str} via {type(mgr).__name__}: {e}")
             traceback.print_exc()
             send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
             channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
             if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Произошла внутренняя ошибка при попытке обновить вашу локацию. Пожалуйста, сообщите об этом администратору.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")
             return False

        target_instance_data = self.get_location_instance(guild_id_str, to_location_id) # Get target instance data AFTER entity is moved
        arrival_context = {**movement_context, 'location_instance_data': target_instance_data}
        await self.handle_entity_arrival(to_location_id, entity_id, entity_type, **arrival_context)

        print(f"LocationManager: Completed movement process for {entity_type} {entity_id} for guild {guild_id_str} to {to_location_id}.")
        return True

    async def handle_entity_arrival(
        self,
        location_id: str,
        entity_id: str,
        entity_type: str,
        **kwargs: Any,
    ) -> None:
        """Обработка триггеров при входе сущности в локацию (инстанс) для определенной гильдии."""
        guild_id = kwargs.get('guild_id')
        if not guild_id: print("LocationManager: Warning: guild_id missing in context for handle_entity_arrival."); return
        guild_id_str = str(guild_id)

        instance_data = kwargs.get('location_instance_data', self.get_location_instance(guild_id_str, location_id))

        template_id = instance_data.get('template_id') if instance_data else None
        tpl = self.get_location_static(guild_id_str, template_id)

        if not tpl:
             print(f"LocationManager: Warning: No template found for location instance {location_id} (guild {guild_id_str}) on arrival of {entity_type} {entity_id}. Cannot execute triggers.")
             return

        triggers = tpl.get('on_enter_triggers')

        engine: Optional["RuleEngine"] = kwargs.get('rule_engine')
        if engine is None: engine = self._rule_engine

        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers'):
            print(f"LocationManager: Executing {len(triggers)} OnEnter triggers for {entity_type} {entity_id} in location {location_id} (guild {guild_id_str}).")
            try:
                trigger_context = {
                     **kwargs,
                     'location_instance_id': location_id,
                     'entity_id': entity_id, 'entity_type': entity_type,
                     'location_template_id': tpl.get('id'),
                     'location_instance_data': instance_data,
                     'location_template_data': tpl,
                 }
                await engine.execute_triggers(triggers, context=trigger_context)
                print(f"LocationManager: OnEnter triggers executed for {entity_type} {entity_id}.")

            except Exception as e:
                print(f"LocationManager: ❌ Error executing OnEnter triggers for {entity_type} {entity_id} in {location_id} (guild {guild_id_str}): {e}")
                traceback.print_exc()
        elif triggers:
             missing = []
             if not engine: missing.append("RuleEngine (injected or in context)")
             if missing:
                 print(f"LocationManager: Warning: OnEnter triggers defined for location {location_id} (guild {guild_id_str}), but missing dependencies: {', '.join(missing)}.")


    async def handle_entity_departure(
        self,
        location_id: str,
        entity_id: str,
        entity_type: str,
        **kwargs: Any,
    ) -> None:
        """Обработка триггеров при выходе сущности из локации (инстанс) для определенной гильдии."""
        guild_id = kwargs.get('guild_id')
        if not guild_id: print("LocationManager: Warning: guild_id missing in context for handle_entity_departure."); return
        guild_id_str = str(guild_id)

        instance_data = kwargs.get('location_instance_data', self.get_location_instance(guild_id_str, location_id))

        template_id = instance_data.get('template_id') if instance_data else None
        if template_id is None: template_id = kwargs.get('location_template_id')

        tpl = self.get_location_static(guild_id_str, template_id)

        if not tpl:
             print(f"LocationManager: Warning: No template found for location instance {location_id} (guild {guild_id_str}) on departure of {entity_type} {entity_id}. Cannot execute triggers.")
             return

        triggers = tpl.get('on_exit_triggers')

        engine: Optional["RuleEngine"] = kwargs.get('rule_engine')
        if engine is None: engine = self._rule_engine

        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers'):
            print(f"LocationManager: Executing {len(triggers)} OnExit triggers for {entity_type} {entity_id} from location {location_id} (guild {guild_id_str}).")
            try:
                 # --- Начало блока try (отступ 4 пробела от if) ---
                 # --- Начало блока try (отступ 4 пробела от if) ---
                 trigger_context = {
                     **kwargs,
                     'location_instance_id': location_id,
                     'entity_id': entity_id, 'entity_type': entity_type,
                     'location_template_id': tpl.get('id'),
                     'location_instance_data': instance_data,
                     'location_template_data': tpl,
                 }
                 await engine.execute_triggers(triggers, context=trigger_context)
                 print(f"LocationManager: OnExit triggers executed for {entity_type} {entity_id}.")
            # --- Конец блока try ---
            except Exception as e: # <--- except должен быть на том же уровне отступа, что и try
                 print(f"LocationManager: ❌ Error executing OnExit triggers for {entity_type} {entity_id} from {location_id} (guild {guild_id_str}): {e}")
                 traceback.print_exc() # <--- print и traceback должны быть внутри except блока (отступ 4 пробела от except)
        # --- Конец блока if ---
            # --- Конец блока try ---
            except Exception as e: # <--- except должен быть на том же уровне отступа, что и try
                 print(f"LocationManager: ❌ Error executing OnExit triggers for {entity_type} {entity_id} from {location_id} (guild {guild_id_str}): {e}")
                 traceback.print_exc() # <--- print и traceback должны быть внутри except блока (отступ 4 пробела от except)
        # --- Конец блока if ---
        elif triggers:
            # ... остальная логика elif ...
            pass

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
         """Обработка игрового тика для локаций для определенной гильдии."""
         guild_id_str = str(guild_id)

         rule_engine = kwargs.get('rule_engine', self._rule_engine)

         if rule_engine and hasattr(rule_engine, 'process_location_tick'):
             guild_instances = self._location_instances.get(guild_id_str, {}).values()
             managers_context = {
                 **kwargs,
                 'guild_id': guild_id_str,
                 'location_manager': self,
                 'game_time_delta': game_time_delta,
             }
             critical_managers = {
                 'item_manager': self._item_manager, 'status_manager': self._status_manager,
                 'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
                 'party_manager': self._party_manager,
             }
             for mgr_name, mgr_instance in critical_managers.items():
                  if mgr_instance is not None and mgr_name not in managers_context:
                       managers_context[mgr_name] = mgr_instance

             for instance_data in list(guild_instances): # Iterate over a copy
                  instance_id = instance_data.get('id')
                  is_active = instance_data.get('is_active', False)

                  if instance_id and is_active:
                       try: # <-- Corrected Indentation Start
                       try: # <-- Corrected Indentation Start
                            template_id = instance_data.get('template_id')
                            template = self.get_location_static(guild_id_str, template_id)

                            if not template:
                                 print(f"LocationManager: Warning: Template not found for active instance {instance_id} in guild {guild_id_str} during tick.")
                                 continue

                            await rule_engine.process_location_tick(
                                instance=instance_data,
                                template=template,
                                context=managers_context
                            )

                       except Exception as e: # <-- Corrected Indentation (aligned with try)

                       except Exception as e: # <-- Corrected Indentation (aligned with try)
                           print(f"LocationManager: ❌ Error processing tick for location instance {instance_id} in guild {guild_id_str}: {e}")
                           traceback.print_exc() # <-- Corrected Indentation (aligned with print above)

                           traceback.print_exc() # <-- Corrected Indentation (aligned with print above)

         elif rule_engine:
              print(f"LocationManager: Warning: RuleEngine injected/found, but 'process_location_tick' method not found for tick processing.")

    def get_location_static(self, guild_id: str, template_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Получить статический шаблон локации по ID для данной гильдии."""
        guild_id_str = str(guild_id)
        guild_templates = self._location_templates.get(guild_id_str, {})
        return guild_templates.get(str(template_id)) if template_id is not None else None

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        self._location_templates.pop(guild_id_str, None)
        self._location_instances.pop(guild_id_str, None)
        self._dirty_instances.pop(guild_id_str, None)
        self._deleted_instances.pop(guild_id_str, None)
        print(f"LocationManager: Cleared cache for guild {guild_id_str}.")

    def mark_location_instance_dirty(self, guild_id: str, instance_id: str) -> None:
         """Помечает инстанс локации как измененный для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         instance_id_str = str(instance_id)
         if guild_id_str in self._location_instances and instance_id_str in self._location_instances[guild_id_str]:
              self._dirty_instances.setdefault(guild_id_str, set()).add(instance_id_str)

    def find_active_instance_by_template_id(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        """Finds the first active location instance for a given template ID in a guild."""
        guild_id_str = str(guild_id)
        template_id_str = str(template_id)
        guild_instances = self._location_instances.get(guild_id_str, {})
        for instance_data in guild_instances.values():
            # Ensure instance_data is a dict before using .get()
            if isinstance(instance_data, dict):
                if instance_data.get('template_id') == template_id_str and instance_data.get('is_active', True):
                    return instance_data
            # If instance_data is not a dict (e.g., it's a Location object directly in cache)
            elif hasattr(instance_data, 'template_id') and hasattr(instance_data, 'is_active') and hasattr(instance_data, 'id'):
                if getattr(instance_data, 'template_id') == template_id_str and getattr(instance_data, 'is_active', True):
                    # If it's an object, return its dict representation if consistent with other methods
                    if hasattr(instance_data, 'to_dict') and callable(getattr(instance_data, 'to_dict')):
                        return instance_data.to_dict()
                    else: # Fallback if no to_dict, try to construct one (less ideal)
                        return {
                            'id': getattr(instance_data, 'id'),
                            'template_id': getattr(instance_data, 'template_id'),
                            'name': getattr(instance_data, 'name', ''), # Assuming name attribute exists
                            'description': getattr(instance_data, 'description', ''), # Assuming description attribute
                            'exits': getattr(instance_data, 'exits', {}), # Assuming exits attribute
                            'state': getattr(instance_data, 'state', {}), # Assuming state attribute
                            'is_active': getattr(instance_data, 'is_active', True)
                            # Add other relevant fields as needed to match dict structure
                        }
        return None

# --- Конец класса LocationManager ---
