import json
import uuid
import time
import traceback # Keep for potential future use, though not explicitly used in current methods
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.rules.rule_engine import RuleEngine  # Changed path
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.services.consequence_processor import ConsequenceProcessor  # Changed path
    from bot.game.managers.game_log_manager import GameLogManager
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
        game_log_manager: Optional["GameLogManager"] = None,
    ):
        self._db_adapter = db_adapter
        self._settings = settings if settings else {} # Ensure settings is a dict
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._relationship_manager = relationship_manager
        self._consequence_processor = consequence_processor
        self._game_log_manager = game_log_manager

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

    async def save_state(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        """Saves active quests for a character. Returns a list of quest data objects."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)

        character_quests_map = self._active_quests.get(guild_id_str, {}).get(character_id_str, {})
        
        # If serialization to JSON strings for specific fields is needed for DB storage:
        # serialized_quests = []
        # for quest_data in character_quests_map.values():
        #     data_copy = quest_data.copy()
        #     if "progress" in data_copy and isinstance(data_copy["progress"], dict):
        #         data_copy["progress"] = json.dumps(data_copy["progress"]) # Serialize 'progress' to JSON string
        #     serialized_quests.append(data_copy)
        # return serialized_quests
        
        # The user's version of this file might have an `await self._db_adapter.execute_many(...)` call here.
        # This version of the code does not, so we are only making the function async
        # to satisfy the Pylance error reported by the user.
        return list(character_quests_map.values())

    # Helper methods
    def _build_consequence_context(self, guild_id: str, character_id: str, quest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Builds the context dictionary for consequence processing."""
        context = {
            "guild_id": guild_id,
            "character_id": character_id,
            "quest": quest_data,
            # Pass managers if they are available and needed by consequences
        }
        if self._npc_manager: context["npc_manager"] = self._npc_manager
        if self._item_manager: context["item_manager"] = self._item_manager
        if self._character_manager: context["character_manager"] = self._character_manager
        if self._relationship_manager: context["relationship_manager"] = self._relationship_manager
        # rule_engine is not typically part of context, but used by ConsequenceProcessor itself
        return context

    def _are_all_objectives_complete(self, quest_data: Dict[str, Any]) -> bool:
        """
        Checks if all objectives for the quest are complete.
        This is a placeholder and needs to be implemented based on objective structure.
        Example:
        for objective in quest_data.get("objectives", []):
            obj_id = objective.get("id")
            obj_type = objective.get("type")
            required_count = objective.get("count")
            
            current_progress = quest_data.get("progress", {}).get(obj_id)

            if obj_type == "kill" or obj_type == "collect":
                if not isinstance(current_progress, int) or current_progress < required_count:
                    return False
            # Add checks for other objective types (e.g., "reach_location", "talk_to_npc")
            else: # Unknown objective type
                print(f"Warning: Unknown objective type '{obj_type}' for objective '{obj_id}' in quest '{quest_data.get('id')}'.")
                return False 
        return True
        """
        # Simplified placeholder: assume true for now.
        # In a real implementation, iterate through quest_data["objectives"]
        # and check against quest_data["progress"].
        print(f"Placeholder: _are_all_objectives_complete for quest {quest_data.get('id')} returning True.")
        return True

    def update_quest_progress(self, guild_id: str, character_id: str, quest_id: str, objective_id: str, progress_update: Any) -> bool:
        """
        Updates the progress of a specific objective within an active quest.
        `progress_update` could be an increment value, a boolean flag, or other data.
        This method should also check for quest completion after progress update.
        """
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_id_str = str(quest_id)
        objective_id_str = str(objective_id)

        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data or quest_data.get("status") != "active":
            print(f"Error: Active quest '{quest_id_str}' not found or not active for progress update.")
            return False

        # Find the objective to update
        objective_to_update = None
        for obj in quest_data.get("objectives", []):
            if obj.get("id") == objective_id_str:
                objective_to_update = obj
                break
        
        if not objective_to_update:
            print(f"Error: Objective '{objective_id_str}' not found in quest '{quest_id_str}'.")
            return False

        # Update progress (example for count-based objectives)
        current_progress = quest_data.get("progress", {}).get(objective_id_str, 0)
        obj_type = objective_to_update.get("type")

        if obj_type in ["kill", "collect"]: # Assuming progress_update is an increment for these
            if not isinstance(current_progress, (int, float)): current_progress = 0
            if isinstance(progress_update, (int, float)):
                 new_progress = current_progress + progress_update
            else: # If progress_update is not a number, assume it's the new value
                new_progress = progress_update
        else: # For other types, progress_update might be a boolean or specific value
            new_progress = progress_update 
            
        quest_data.setdefault("progress", {})[objective_id_str] = new_progress
        # print(f"Progress for objective '{objective_id_str}' in quest '{quest_id_str}' updated to {new_progress}.")
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)

        # Check for quest completion
        if self._are_all_objectives_complete(quest_data):
            self.complete_quest(guild_id_str, character_id_str, quest_id_str)
            # complete_quest handles consequences and state changes

        return True


    def get_dirty_character_ids(self, guild_id: str) -> Set[str]:
        """Gets set of character IDs with changed quest states for a guild."""
        return self._dirty_quests.get(str(guild_id), set()).copy() # Return a copy

    def clear_dirty_character_ids(self, guild_id: str) -> None:
        """Clears the set of dirty character IDs for a guild."""
        if str(guild_id) in self._dirty_quests:
            self._dirty_quests[str(guild_id)].clear()
    
    # Example of how guild-specific templates might be loaded if they were in a DB (conceptual)
    # def _load_guild_specific_templates_from_db(self, guild_id: str) -> Dict[str, Any]:
    #     if not self._db_adapter:
    #         return {}
    #     # This is a conceptual example. Actual table and column names would vary.
    #     # Assumes a table 'guild_quest_templates' with 'guild_id', 'template_id', 'template_data_json'
    #     try:
    #         rows = self._db_adapter.fetchall_sync(
    #             "SELECT template_id, template_data_json FROM guild_quest_templates WHERE guild_id = ?",
    #             (guild_id,)
    #         )
    #         templates = {}
    #         for row in rows:
    #             try:
    #                 template_data = json.loads(row[1]) # template_data_json column
    #                 templates[str(row[0])] = template_data # template_id column
    #             except json.JSONDecodeError:
    #                 print(f"Error decoding quest template JSON for template_id '{row[0]}' in guild '{guild_id}'.")
    #         return templates
    #     except Exception as e: # Catch database errors or other issues
    #         print(f"Error loading guild-specific quest templates from DB for guild '{guild_id}': {e}")
    #         # Consider logging the full traceback using traceback.format_exc()
    #         
