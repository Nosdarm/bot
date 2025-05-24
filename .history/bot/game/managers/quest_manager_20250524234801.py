import json
import uuid
import time
import traceback # Keep for potential future use, though not explicitly used in current methods
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.db.sqlite_adapter import SqliteAdapter
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.engine.rule_engine import RuleEngine
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.engine.consequence_processor import ConsequenceProcessor
    # The import for 'Quest' model is removed as per instruction 10, assuming dicts are used.

class QuestManager:
    # Instruction 11: Add required class attributes
    required_args_for_load: List[str] = ["guild_id"] # Example, adjust if different logic needed for load_state
    required_args_for_save: List[str] = ["guild_id"] # Example, adjust if different logic needed for save_state
    required_args_for_rebuild: List[str] = ["guild_id"] # Placeholder, actual usage might vary

    # Instruction 2 & 3: Merged __init__ and consolidated cache initializations
    def __init__(
        self,
        db_adapter: Optional["SqliteAdapter"],
        settings: Optional[Dict[str, Any]],
        npc_manager: Optional["NpcManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        consequence_processor: Optional["ConsequenceProcessor"] = None,
    ):
        self._db_adapter = db_adapter
        self._settings = settings if settings else {} # Ensure settings is a dict
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._relationship_manager = relationship_manager
        self._consequence_processor = consequence_processor

        # guild_id -> character_id -> quest_id -> quest_data
        self._active_quests: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # guild_id -> quest_template_id -> quest_template_data
        self._quest_templates: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # guild_id -> character_id -> list of completed quest_ids
        self._completed_quests: Dict[str, Dict[str, List[str]]] = {}
        # guild_id -> set of character_ids with dirty quest data
        self._dirty_quests: Dict[str, Set[str]] = {}
        
        # Removed _deleted_quest_ids as per instruction 3.

        # Load campaign data from settings
        self.campaign_data: Dict[str, Any] = self._settings.get("campaign_data", {})

    # Instruction 4: Corrected load_quest_templates
    def load_quest_templates(self, guild_id: str) -> None:
        """Loads quest templates from campaign data and potentially guild-specific settings."""
        guild_id_str = str(guild_id) # Ensure guild_id is a string for dict keys
        
        # Initialize cache for the guild if it doesn't exist
        self._quest_templates.setdefault(guild_id_str, {})
        guild_templates_cache = self._quest_templates[guild_id_str]

        # Load from campaign_data (e.g., global templates)
        campaign_templates_list = self.campaign_data.get("quest_templates", [])
        
        if isinstance(campaign_templates_list, list):
            for template_dict in campaign_templates_list:
                if isinstance(template_dict, dict) and "id" in template_dict:
                    tpl_id = str(template_dict["id"]) # Ensure template ID is a string
                    guild_templates_cache[tpl_id] = template_dict
                else:
                    # Using print for now, consider a logging framework for production
                    print(f"Warning: Invalid quest template format in campaign_data: {template_dict}")
        else:
            print(f"Warning: 'quest_templates' in campaign_data is not a list for guild {guild_id_str}.")

        # Placeholder for loading from guild-specific settings (e.g., DB)
        # This part would typically involve fetching from self._db_adapter
        # For example:
        # guild_specific_db_templates = self._load_guild_specific_templates_from_db(guild_id_str)
        # for tpl_id, template_data in guild_specific_db_templates.items():
        #     guild_templates_cache[str(tpl_id)] = template_data # Ensure tpl_id is string
        
        # print(f"Loaded {len(guild_templates_cache)} quest templates for guild {guild_id_str}.")

    # Instruction 5: Ensure single functional version of helper methods
    def get_quest_template(self, guild_id: str, quest_template_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a specific quest template for a guild."""
        guild_id_str = str(guild_id)
        quest_template_id_str = str(quest_template_id)

        if guild_id_str not in self._quest_templates:
            self.load_quest_templates(guild_id_str) # Load if not already loaded for the guild
        
        return self._quest_templates.get(guild_id_str, {}).get(quest_template_id_str)

    # Instruction 6: Quest lifecycle methods compatible with ConsequenceProcessor
    def list_quests_for_character(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        """Lists active quests for a character."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        return list(self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).values())

    def start_quest(self, guild_id: str, character_id: str, quest_template_id: str) -> Optional[Dict[str, Any]]:
        """Starts a new quest for a character."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_template_id_str = str(quest_template_id)

        template = self.get_quest_template(guild_id_str, quest_template_id_str)
        if not template:
            print(f"Error: Quest template '{quest_template_id_str}' not found for guild '{guild_id_str}'.")
            return None

        # Basic check for character existence (if character_manager is available)
        if self._character_manager:
            # Assuming get_character_by_id returns None if not found
            if not self._character_manager.get_character_by_id(guild_id_str, character_id_str):
                print(f"Error: Character '{character_id_str}' not found in guild '{guild_id_str}'.")
                return None
            
        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        
        # Check if a quest from this template is already active (using template_id for this check)
        # This logic might need refinement: what if multiple instances of the same quest type are allowed?
        # For now, assume only one active instance per template_id.
        for existing_quest in self._active_quests[guild_id_str][character_id_str].values():
            if existing_quest.get("template_id") == quest_template_id_str:
                print(f"Warning: Quest (Template: '{quest_template_id_str}') already active for character '{character_id_str}'.")
                return existing_quest

        quest_id = str(uuid.uuid4()) # Unique ID for this specific quest instance
        new_quest_data = {
            "id": quest_id,
            "template_id": quest_template_id_str,
            "character_id": character_id_str,
            "status": "active", # e.g., active, completed, failed
            "start_time": time.time(),
            "objectives": [obj.copy() for obj in template.get("objectives", [])], # Deep copy objectives
            "progress": {}, # To store progress for each objective, e.g., {"objective_id_1": 5}
            "data": template.get("data", {}).copy(), # Copy any other non-structural template data
        }
        
        self._active_quests[guild_id_str][character_id_str][quest_id] = new_quest_data
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        
        # print(f"Quest '{quest_id}' (Template: '{quest_template_id_str}') started for character '{character_id_str}'.")
        
        if self._consequence_processor:
            context = self._build_consequence_context(guild_id_str, character_id_str, new_quest_data)
            start_consequences = template.get("consequences", {}).get("on_start", [])
            if start_consequences:
                self._consequence_processor.process_consequences(start_consequences, context)
        
        return new_quest_data

    def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool:
        """Marks a quest as completed if all objectives are met."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_id_str = str(quest_id)

        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data:
            print(f"Error: Active quest '{quest_id_str}' not found for character '{character_id_str}'.")
            return False

        # Objective completion check (simplified - real logic would be more complex)
        # This needs to be implemented based on how objectives and progress are structured.
        # For now, assume a function self._are_all_objectives_complete(quest_data) exists.
        if not self._are_all_objectives_complete(quest_data): # Placeholder for actual check
            print(f"Quest '{quest_id_str}' cannot be completed: Not all objectives met.")
            return False

        quest_data["status"] = "completed"
        quest_data["completion_time"] = time.time()
        
        template = self.get_quest_template(guild_id_str, quest_data["template_id"])

        if self._consequence_processor and template:
            context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
            completion_consequences = template.get("consequences", {}).get("on_complete", [])
            if completion_consequences:
                self._consequence_processor.process_consequences(completion_consequences, context)

        self._completed_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, []).append(quest_id_str)
        del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests[guild_id_str][character_id_str]: # Cleanup if no more active quests for char
            del self._active_quests[guild_id_str][character_id_str]
        
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        # print(f"Quest '{quest_id_str}' completed for character '{character_id_str}'.")
        return True

    def fail_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool:
        """Marks a quest as failed."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_id_str = str(quest_id)

        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data:
            print(f"Error: Active quest '{quest_id_str}' not found for character '{character_id_str}'.")
            return False

        quest_data["status"] = "failed"
        quest_data["failure_time"] = time.time()
        
        template = self.get_quest_template(guild_id_str, quest_data["template_id"])

        if self._consequence_processor and template:
            context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
            failure_consequences = template.get("consequences", {}).get("on_fail", [])
            if failure_consequences:
                self._consequence_processor.process_consequences(failure_consequences, context)
        
        del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests[guild_id_str][character_id_str]: # Cleanup
            del self._active_quests[guild_id_str][character_id_str]
            
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        # print(f"Quest '{quest_id_str}' failed for character '{character_id_str}'.")
        return True

    # Instruction 12: load_state and save_state consistent with dict structure
    def load_state(self, guild_id: str, character_id: str, data: List[Dict[str, Any]]) -> None:
        """Loads active quests for a character from a list of quest data objects."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)

        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        active_quests_for_char = self._active_quests[guild_id_str][character_id_str]
        
        for quest_data_item in data:
            quest_id = quest_data_item.get("id")
            if quest_id:
                # Assuming data is already in the correct Python dict format.
                # If fields like 'objectives' or 'progress' were stored as JSON strings in DB,
                # they would need json.loads() here.
                # e.g., if quest_data_item["progress"] is a string:
                # try:
                #    quest_data_item["progress"] = json.loads(quest_data_item["progress"])
                # except (TypeError, json.JSONDecodeError):
                #    print(f"Warning: Could not deserialize progress for quest {quest_id}")
                #    quest_data_item["progress"] = {} # Default to empty dict
                active_quests_for_char[str(quest_id)] = quest_data_item
            else:
                print(f"Warning: Quest data without ID found during load_state for char '{character_id_str}'")

        # print(f"Loaded {len(data)} active quests for character '{character_id_str}' in guild '{guild_id_str}'.")

    def save_state(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        """Saves active quests for a character. Returns a list of quest data objects."""
        guild_id_str = str(guild_id)
        if not self._db_adapter:
            print(f"QuestManager: DB adapter missing for guild {guild_id_str}. Cannot save quest state.")
            return

        dirty_char_ids = self._dirty_quests.get(guild_id_str, set()).copy()
        if not dirty_char_ids:
            self._dirty_quests.pop(guild_id_str, None) # Clean up empty set for guild
            return # Nothing to save for this guild

        print(f"QuestManager: Saving quest states for {len(dirty_char_ids)} characters in guild {guild_id_str}...")
        
        all_quests_to_save = []
        # We need to save all quests for dirty characters, not just active ones, 
        # as some might have been completed or failed.
        # However, the current structure only explicitly stores active quests in _active_quests.
        # Completed quests are tracked by template_id in _completed_quests.
        # Failed quests are not explicitly stored after being removed from active.

        # This logic will only save currently "active" quests from the _active_quests cache
        # for characters marked as dirty. If a quest was completed or failed, it's removed
        # from _active_quests. We need a more robust way to save all states (active, completed, failed)
        # if they are all meant to be persisted in the `character_quests` table with their final status.

        # For now, this will save the current state of any quest still in _active_quests for a dirty character.
        for char_id in list(dirty_char_ids): # Iterate a copy if we modify the set
            active_guild_quests = self._active_quests.get(guild_id_str, {})
            char_active_quests = active_guild_quests.get(char_id, {})
            for quest_id, quest_data in char_active_quests.items():
                 # Ensure we only save quests that belong to the current char_id being processed
                if str(quest_data.get('character_id')) == char_id:
                    all_quests_to_save.append((
                        quest_id, # Active quest instance ID
                        char_id,
                        guild_id_str,
                        quest_data.get('template_id'),
                        quest_data.get('status', 'active'), # Should be 'active' if from this cache
                        json.dumps(quest_data.get('objectives_status', [])),
                        quest_data.get('start_time'),
                        quest_data.get('completion_time') 
                    ))
            
            # How to handle completed/failed quests for saving?
            # If a character completes/fails a quest, they are marked dirty.
            # The quest is removed from _active_quests.
            # If `character_quests` is meant to be the single source of truth for all states,
            # we need to explicitly insert/update 'completed' or 'failed' records here.
            # This simplified save_state currently doesn't do that robustly.
            # It primarily saves the _active_quests cache.

        if all_quests_to_save:
            upsert_sql = """
                INSERT OR REPLACE INTO character_quests 
                (quest_id, character_id, guild_id, template_id, status, objectives_status, start_time, completion_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) 
            """
            try:
                await self._db_adapter.execute_many(upsert_sql, all_quests_to_save)
                print(f"QuestManager: Successfully saved/updated {len(all_quests_to_save)} quest instances for guild {guild_id_str}.")
            except Exception as e:
                print(f"QuestManager: DB error saving quest states for guild {guild_id_str}: {e}")
                traceback.print_exc()
                return # Don't clear dirty flags if save failed

        self._dirty_quests.pop(guild_id_str, None) # Clear dirty set for the guild after attempting save

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Rebuilds any runtime caches if necessary (e.g., mapping quest givers to quests)."""
        print(f"QuestManager: Rebuilding runtime caches for guild {str(guild_id)} (Placeholder).")
        pass


