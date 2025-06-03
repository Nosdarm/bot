# bot/game/managers/quest_manager.py

from __future__ import annotations
import traceback
import json # Added for serializing objectives_status
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING # Added Set for _dirty_quests

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.services.consequence_processor import ConsequenceProcessor
    from bot.game.managers.character_manager import CharacterManager 
    # Add other manager imports if they become direct dependencies of QuestManager

class QuestManager:
import json
import uuid
import time 
import traceback
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

# Assuming the Quest model is defined in bot.game.models.quest
from bot.game.models.quest import Quest 

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.relationship_manager import RelationshipManager # Added
    # from bot.services.campaign_loader import CampaignLoader # If directly used for campaign_data type hint

print("DEBUG: quest_manager.py module loading...")

class QuestManager:
    """
    Manages quests: loading templates, creating instances, persistence, and lifecycle.
    Works on a per-guild basis.
    """
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,
        consequence_processor: Optional[ConsequenceProcessor] = None,
        character_manager: Optional[CharacterManager] = None,
        # Add other managers passed from GameManager context if needed directly
        **kwargs: Any 
    ):
        self._db_adapter = db_adapter
        self._settings = settings if settings is not None else {}
        self._consequence_processor = consequence_processor
        self._character_manager = character_manager # Example, if needed for quest logic

        # Per-guild caches
        self._quest_templates: Dict[str, Dict[str, Dict[str, Any]]] = {} # {guild_id: {template_id: data}}
        self._active_quests: Dict[str, Dict[str, Dict[str, Any]]] = {} # {guild_id: {character_id: {quest_id: data}}}
        self._completed_quests: Dict[str, Dict[str, List[str]]] = {} # {guild_id: {character_id: [quest_template_id]}}
        
        self._dirty_quests: Dict[str, Set[str]] = {} # {guild_id: set_of_character_ids_with_dirty_quests}
        
    def __init__(self, 
                 db_adapter: Optional["SqliteAdapter"], 
                 settings: Optional[Dict[str, Any]], 
                 npc_manager: Optional["NpcManager"] = None, 
                 character_manager: Optional["CharacterManager"] = None, 
                 item_manager: Optional["ItemManager"] = None, 
                 rule_engine: Optional["RuleEngine"] = None,
                 relationship_manager: Optional["RelationshipManager"] = None): # Added
        print("Initializing QuestManager...")
        self._db_adapter: Optional["SqliteAdapter"] = db_adapter
        self._settings: Optional[Dict[str, Any]] = settings
        self._npc_manager: Optional["NpcManager"] = npc_manager
        self._character_manager: Optional["CharacterManager"] = character_manager
        self._item_manager: Optional["ItemManager"] = item_manager
        self._rule_engine: Optional["RuleEngine"] = rule_engine
        self._relationship_manager: Optional["RelationshipManager"] = relationship_manager # Added

        self._quest_templates: Dict[str, Dict[str, Any]] = {}  # guild_id -> template_id -> template_data
        self._active_quests: Dict[str, Dict[str, Quest]] = {}    # guild_id -> quest_id -> Quest object
        
        self._dirty_quests: Dict[str, Set[str]] = {}
        self._deleted_quest_ids: Dict[str, Set[str]] = {}
        print("QuestManager initialized.")

    def load_quest_templates(self, guild_id: str, campaign_data: Optional[Dict[str, Any]] = None) -> None:
        guild_id_str = str(guild_id)
        print(f"QuestManager: Loading quest templates for guild {guild_id_str}...")
        self._quest_templates.pop(guild_id_str, None)
        guild_templates_cache = self._quest_templates.setdefault(guild_id_str, {})

        loaded_from_campaign = False
        if campaign_data and "quest_templates" in campaign_data:
            templates_list: List[Dict[str, Any]] = campaign_data.get("quest_templates", [])
        self._quest_templates.pop(guild_id_str, None) 
        guild_templates_cache = self._quest_templates.setdefault(guild_id_str, {})

        # As per prompt, look for "quests" key in campaign_data, which is a list of dicts.
        # The previous subtask for CampaignLoader used "quest_templates" as the key.
        # Using "quests" here as specified for this subtask.
        if campaign_data and "quests" in campaign_data: 
            templates_list: List[Dict[str, Any]] = campaign_data.get("quests", [])
            if isinstance(templates_list, list):
                for template_dict in templates_list:
                    if isinstance(template_dict, dict) and "id" in template_dict:
                        tpl_id = str(template_dict["id"])
                        # Basic validation/defaulting for a quest template
                        template_dict.setdefault('name', f"Unnamed Quest ({tpl_id})")
                        template_dict.setdefault('description', "No description.")
                        template_dict.setdefault('prerequisites', [])
                        template_dict.setdefault('objectives', []) # e.g., [{"type": "fetch", "item_id": "X", "quantity": Y, "completed": False}]
                        template_dict.setdefault('rewards', []) # Handled by ConsequenceProcessor
                        template_dict.setdefault('consequences', []) # For broader impact beyond rewards
                        guild_templates_cache[tpl_id] = template_dict
                if guild_templates_cache:
                    print(f"QuestManager: Loaded {len(guild_templates_cache)} quest templates from campaign_data for guild {guild_id_str}.")
                loaded_from_campaign = True
            else:
                print(f"QuestManager: Warning: 'quest_templates' in campaign_data is not a list for guild {guild_id_str}.")

        if not loaded_from_campaign:
            # Fallback to settings if not loaded from campaign_data
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            templates_data_from_settings = guild_settings.get('quest_templates')
            if isinstance(templates_data_from_settings, dict):
                 for tpl_id, data in templates_data_from_settings.items():
                      if tpl_id and isinstance(data, dict):
                           data.setdefault('id', str(tpl_id))
                           data.setdefault('name', f"Unnamed Quest ({tpl_id})")
                           data.setdefault('description', "No description.")
                           # ... add other defaults as above ...
                           guild_templates_cache[str(tpl_id)] = data
                 if guild_templates_cache:
                    print(f"QuestManager: Loaded {len(guild_templates_cache)} quest templates from settings for guild {guild_id_str}.")
            
            if not guild_templates_cache:
                 print(f"QuestManager: No 'quest_templates' found in campaign_data or settings for guild {guild_id_str}.")


    def get_quest_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        return self._quest_templates.get(str(guild_id), {}).get(str(template_id))

    async def list_quests_for_character(self, character_id: str, guild_id: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Lists active and available quests for a character."""
        # This is a placeholder. A real implementation would:
        # 1. Get active quests for character_id from self._active_quests.
        # 2. Iterate all self._quest_templates for the guild.
        # 3. For each template, check prerequisites against the character (using RuleEngine).
        # 4. Check if the quest is not already completed by the character (self._completed_quests).
        # 5. Compile and return a list of quest summaries.
        print(f"QuestManager: Listing quests for character {character_id} in guild {guild_id} (Placeholder).")
        active_char_quests = self._active_quests.get(str(guild_id), {}).get(str(character_id), {})
        
        # For demonstration, returning active quests only
        return list(active_char_quests.values())


    async def start_quest(self, character_id: str, quest_template_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
        """Starts a quest for a character if prerequisites are met."""
        # Placeholder logic:
        # 1. Get quest template.
        # 2. Check if already active or completed.
        # 3. Check prerequisites using RuleEngine from context.
        # 4. If all good, create an active quest instance in self._active_quests.
        #    An active quest instance might copy template data and add runtime state (e.g., objective progress).
        # 5. Mark dirty.
        guild_id_str, char_id_str, template_id_str = str(guild_id), str(character_id), str(quest_template_id)
        print(f"QuestManager: Attempting to start quest '{template_id_str}' for char {char_id_str} in guild {guild_id_str} (Placeholder).")
        
        template = self.get_quest_template(guild_id_str, template_id_str)
        if not template:
            print(f"QuestManager: Template {template_id_str} not found.")
            return False
            
        # TODO: Add real checks (prerequisites, already active/completed)
        # For now, assume it can be started.
        
        new_quest_id = f"active_{template_id_str}_{char_id_str}" # Simplistic ID for active quest
        active_quest_instance = {
            "id": new_quest_id,
            "template_id": template_id_str,
            "character_id": char_id_str,
            "guild_id": guild_id_str,
            "status": "active",
            "objectives_status": [{**obj, 'completed': False} for obj in template.get('objectives', [])], # Copy objectives
            "start_time": context.get('time_manager').get_current_game_time(guild_id_str) if context.get('time_manager') else None
        }
        
        guild_active_quests = self._active_quests.setdefault(guild_id_str, {})
        char_quests = guild_active_quests.setdefault(char_id_str, {})
        char_quests[new_quest_id] = active_quest_instance
        
        self._dirty_quests.setdefault(guild_id_str, set()).add(char_id_str)
        print(f"QuestManager: Quest '{new_quest_id}' started for character {char_id_str}.")
        return True

    async def complete_quest(
        self, 
        character_id: str, 
        quest_id: str, # This would be the ID of the active quest instance
        guild_id: str, 
        context: Dict[str, Any]
    ) -> bool:
        """
        Completes a quest for a character, checks objectives, and processes consequences.
        """
        guild_id_str, char_id_str = str(guild_id), str(character_id)
        print(f"QuestManager: Attempting to complete quest '{quest_id}' for char {char_id_str} in guild {guild_id_str}.")

        active_char_quests = self._active_quests.get(guild_id_str, {}).get(char_id_str, {})
        active_quest_data = active_char_quests.get(quest_id)

        if not active_quest_data:
            print(f"QuestManager: Active quest '{quest_id}' not found for character {char_id_str}.")
            return False # Quest not active or doesn't exist

        # TODO: Objective Checking
        # For now, assume objectives are met if command is called.
        # In a real system, iterate active_quest_data['objectives_status']
        # and verify each is 'completed: True'. This might involve RuleEngine checks
        # (e.g., has_item, target_defeated).
        all_objectives_met = True 
        for obj_status in active_quest_data.get('objectives_status', []):
            if not obj_status.get('completed', False):
                all_objectives_met = False
                print(f"QuestManager: Objective '{obj_status.get('description','Unnamed Objective')}' for quest '{quest_id}' not met.")
                break # Found an incomplete objective
        
        if not all_objectives_met:
             print(f"QuestManager: Cannot complete quest '{quest_id}', not all objectives met.")
             # Optionally send feedback to user via context's send_callback_factory
             return False

        if self._consequence_processor:
            quest_template_id = active_quest_data.get('template_id')
            quest_template_data = self.get_quest_template(guild_id_str, quest_template_id)
            
            if not quest_template_data:
                print(f"QuestManager: CRITICAL - Quest template '{quest_template_id}' not found for active quest '{quest_id}'. Cannot process consequences.")
                return False

            # The ConsequenceProcessor will handle rewards and other outcomes based on the quest_template_data
            summary = await self._consequence_processor.process_consequences(
                character_id=char_id_str,
                quest_id=quest_id, 
                quest_data=quest_template_data, # Pass the template data which defines consequences
                guild_id=guild_id_str,
                context=context
            )
            print(f"QuestManager: Consequences for quest '{quest_id}' processed. Summary: {summary}")
            # TODO: Send summary to player via context's send_callback_factory
        else:
            print("QuestManager: ConsequenceProcessor not available. Cannot process quest rewards/consequences.")
            # Potentially still mark quest as complete but without rewards, or fail completion.
            # For now, let's assume consequences are critical for completion.
            return False 

        # Move from active to completed
        active_quest_data['status'] = 'completed'
        active_quest_data['completion_time'] = context.get('time_manager').get_current_game_time(guild_id_str) if context.get('time_manager') else None
        
        # Add to completed list (stores template_id to prevent re-taking unique quests)
        char_completed_quests = self._completed_quests.setdefault(guild_id_str, {}).setdefault(char_id_str, [])
        if active_quest_data.get('template_id') not in char_completed_quests: # Avoid duplicates if logic allows
            char_completed_quests.append(active_quest_data.get('template_id'))

        # Remove from active quests
        if quest_id in active_char_quests: # Check before deleting
            del active_char_quests[quest_id]
        
        self._dirty_quests.setdefault(guild_id_str, set()).add(char_id_str)
        print(f"QuestManager: Quest '{quest_id}' completed for character {char_id_str} and moved to completed.")
        return True

    async def fail_quest(self, character_id: str, quest_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
        """Fails an active quest for a character."""
        # Placeholder logic:
        # 1. Find active quest.
        # 2. Set status to 'failed'.
        # 3. Optionally, trigger failure consequences via ConsequenceProcessor.
        # 4. Move to a failed quest log or just remove from active.
        # 5. Mark dirty.
        print(f"QuestManager: Failing quest '{quest_id}' for char {character_id} in guild {guild_id} (Placeholder).")
        
        guild_id_str, char_id_str = str(guild_id), str(character_id)
        active_char_quests = self._active_quests.get(guild_id_str, {}).get(char_id_str, {})
        active_quest_data = active_char_quests.get(quest_id)

        if not active_quest_data:
            print(f"QuestManager: Active quest '{quest_id}' not found for character {char_id_str} to fail.")
            return False

        active_quest_data['status'] = 'failed'
        active_quest_data['failure_time'] = context.get('time_manager').get_current_game_time(guild_id_str) if context.get('time_manager') else None
        
        # Optionally, handle failure consequences if defined in quest_template_data.get('failure_consequences', [])
        # Similar to complete_quest, but using a different set of consequences.
        # For now, just marking as failed.

        # Remove from active quests (or move to a separate 'failed_quests' structure if needed for persistence)
        if quest_id in active_char_quests: # Check before deleting
            del active_char_quests[quest_id]
            
        self._dirty_quests.setdefault(guild_id_str, set()).add(char_id_str)
        print(f"QuestManager: Quest '{quest_id}' failed for character {char_id_str}.")
        return True


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Loads quest states for a guild from the database."""
        guild_id_str = str(guild_id)
        print(f"QuestManager: Loading quest state for guild {guild_id_str}...")
        if not self._db_adapter:
            print(f"QuestManager: DB adapter missing for guild {guild_id_str}. Cannot load quest state.")
            return

        self.load_quest_templates(guild_id_str, kwargs.get('campaign_data'))

        # Reset caches for the guild
        self._active_quests[guild_id_str] = {}
        self._completed_quests[guild_id_str] = {}
        self._dirty_quests.pop(guild_id_str, None)

        # Example query (adjust table/column names as per your actual DB schema for quests)
        # This assumes a 'character_quests' table storing individual quest progression
        query = "SELECT character_id, quest_id, template_id, status, objectives_status, start_time, completion_time FROM character_quests WHERE guild_id = ?"
        try:
            rows = await self._db_adapter.fetchall(query, (guild_id_str,))
        except Exception as e:
            print(f"QuestManager: DB error fetching quest states for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return

        loaded_active_count = 0
        for row_data in rows:
            try:
                data = dict(row_data)
                char_id = str(data['character_id'])
                quest_instance_id = str(data['quest_id']) # This is the active quest instance ID
                
                # Deserialize JSON fields
                data['objectives_status'] = json.loads(data.get('objectives_status') or '[]') if isinstance(data.get('objectives_status'), str) else (data.get('objectives_status') or [])

                if data['status'] == 'active':
                    guild_active = self._active_quests.setdefault(guild_id_str, {})
                    char_quests = guild_active.setdefault(char_id, {})
                    char_quests[quest_instance_id] = data
                    loaded_active_count += 1
                elif data['status'] == 'completed':
                    char_completed = self._completed_quests.setdefault(guild_id_str, {}).setdefault(char_id, [])
                    if data['template_id'] not in char_completed: # Store template_id of completed quests
                        char_completed.append(str(data['template_id']))
                # Handle 'failed' status if you track it separately
            except Exception as e:
                print(f"QuestManager: Error loading quest instance {data.get('quest_id', 'N/A')} for char {data.get('character_id', 'N/A')}: {e}")
                traceback.print_exc()
        
        print(f"QuestManager: Loaded {loaded_active_count} active quest instances for guild {guild_id_str}.")


    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Saves quest states for a guild to the database."""
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

```
                        template_dict.setdefault('name', f"Unnamed Quest ({tpl_id})")
                        template_dict.setdefault('stages', {}) 
                        guild_templates_cache[tpl_id] = template_dict
                print(f"QuestManager: Loaded {len(guild_templates_cache)} quest templates from campaign_data for guild {guild_id_str}.")
            else:
                print(f"QuestManager: Warning: 'quests' in campaign_data is not a list for guild {guild_id_str}.")
        else:
            print(f"QuestManager: No 'quests' key found in campaign_data for guild {guild_id_str} or campaign_data not provided.")

    def get_quest_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        return self._quest_templates.get(guild_id_str, {}).get(str(template_id))

    def get_quest(self, guild_id: str, quest_id: str) -> Optional[Quest]:
        guild_id_str = str(guild_id)
        return self._active_quests.get(guild_id_str, {}).get(str(quest_id))

    def get_active_quests_for_character(self, guild_id: str, character_id: str, character_manager: Optional["CharacterManager"]) -> List[Quest]:
        guild_id_str, char_id_str = str(guild_id), str(character_id)
        active_char_quests: List[Quest] = []
        
        char_mgr = character_manager or self._character_manager
        if not char_mgr:
            print(f"QuestManager: CharacterManager not available for get_active_quests_for_character (guild {guild_id_str}).")
            return active_char_quests

        character = char_mgr.get_character(guild_id_str, char_id_str)
        if character and hasattr(character, 'active_quests') and isinstance(character.active_quests, list):
            guild_quests_cache = self._active_quests.get(guild_id_str, {})
            for quest_id in character.active_quests:
                quest = guild_quests_cache.get(str(quest_id))
                if quest and quest.status == "active": 
                    active_char_quests.append(quest)
        return active_char_quests

    async def create_quest_from_template(self, guild_id: str, template_id: str, 
                                         assigned_to_character_id: Optional[str] = None, 
                                         initial_state_vars: Optional[Dict[str, Any]] = None) -> Optional[Quest]:
        guild_id_str, template_id_str = str(guild_id), str(template_id)
        quest_tpl = self.get_quest_template(guild_id_str, template_id_str)
        if not quest_tpl:
            print(f"QuestManager: Template '{template_id_str}' not found for guild {guild_id_str}.")
            return None

        quest_id = str(uuid.uuid4())
        status = "active" if assigned_to_character_id else "available"

        data = {
            'id': quest_id,
            # 'template_id': template_id_str, # Quest model doesn't have template_id
            'guild_id': guild_id_str,
            'name': quest_tpl.get('name', f"Quest {quest_id[:8]}"),
            'description': quest_tpl.get('description', ""),
            'status': status,
            'influence_level': quest_tpl.get('influence_level', 'local'),
            'prerequisites': list(quest_tpl.get('prerequisites', [])),
            'connections': dict(quest_tpl.get('connections', {})),
            'stages': dict(quest_tpl.get('stages', {})), 
            'rewards': dict(quest_tpl.get('rewards', {})),
            'npc_involvement': dict(quest_tpl.get('npc_involvement', {})),
            'assigner_id': quest_tpl.get('assigner_id'), 
            # 'state_variables': initial_state_vars or quest_tpl.get('initial_state_variables', {}).copy(), # Not in Quest model
        }
        
        try:
            quest = Quest.from_dict(data)
        except Exception as e:
            print(f"QuestManager: Error creating Quest object from dict: {e}, data: {data}"); traceback.print_exc()
            return None

        self._active_quests.setdefault(guild_id_str, {})[quest.id] = quest
        self.mark_quest_dirty(guild_id_str, quest.id)
        
        if assigned_to_character_id and self._character_manager:
             char = self._character_manager.get_character(guild_id_str, str(assigned_to_character_id))
             if char and hasattr(char, 'active_quests'):
                 if char.active_quests is None: char.active_quests = [] # Ensure list
                 if quest.id not in char.active_quests:
                     char.active_quests.append(quest.id)
                     self._character_manager.mark_character_dirty(guild_id_str, char.id)

        print(f"QuestManager: Quest '{quest.id}' ({quest.name}) created for guild {guild_id_str}.")
        return quest

    async def start_quest(self, guild_id: str, quest_id: str, character_id: str, character_manager: Optional["CharacterManager"]) -> bool:
        guild_id_str, quest_id_str, char_id_str = str(guild_id), str(quest_id), str(character_id)
        quest = self.get_quest(guild_id_str, quest_id_str)
        if not quest or quest.status != "available":
            print(f"QuestManager: Quest {quest_id_str} not found or not 'available' to start for guild {guild_id_str}.")
            return False
            
        quest.status = "active"
        
        char_mgr = character_manager or self._character_manager
        if char_mgr:
            char = char_mgr.get_character(guild_id_str, char_id_str)
            if char and hasattr(char, 'active_quests'):
                if char.active_quests is None: char.active_quests = []
                if quest.id not in char.active_quests:
                    char.active_quests.append(quest.id)
                    char_mgr.mark_character_dirty(guild_id_str, char.id)
            else:
                print(f"QuestManager: Character {char_id_str} not found for starting quest {quest_id_str} in guild {guild_id_str}.")
        
        self.mark_quest_dirty(guild_id_str, quest.id)
        print(f"QuestManager: Quest {quest.id} started for character {char_id_str} in guild {guild_id_str}.")
        return True

    async def complete_quest(self, guild_id: str, quest_id: str, character_id: str, character_manager: Optional["CharacterManager"], success: bool = True) -> bool:
        print("DEBUG: Entered complete_quest method")
        guild_id_str, quest_id_str, char_id_str = str(guild_id), str(quest_id), str(character_id)
        quest = self.get_quest(guild_id_str, quest_id_str)
        if not quest or quest.status != "active":
            print(f"QuestManager: Quest {quest_id_str} not found or not 'active' for completion for guild {guild_id_str}.")
            return False

        quest.status = "completed_success" if success else "completed_failure"
        
        char_mgr = character_manager or self._character_manager
        if char_mgr:
            char = char_mgr.get_character(guild_id_str, char_id_str)
            if char and hasattr(char, 'active_quests') and isinstance(char.active_quests, list):
                if quest.id in char.active_quests:
                    char.active_quests.remove(quest.id)
                    char_mgr.mark_character_dirty(guild_id_str, char.id)
        
        self.mark_quest_dirty(guild_id_str, quest.id)
        print(f"QuestManager: Quest {quest.id} status set to '{quest.status}' for character {char_id_str} in guild {guild_id_str}.")

        # --- CONSEQUENCE AND REWARD LOGIC ---
        # Process Connections
        connection_key = 'on_success' if success else 'on_failure'
        action_strings = quest.connections.get(connection_key, [])
        
        if action_strings:
            print(f"QuestManager: Processing '{connection_key}' connections for quest {quest.id}...")
            for action_string in action_strings:
                try:
                    if action_string.startswith("QUEST_AVAIL_TPL_"):
                        next_quest_template_id = action_string.replace("QUEST_AVAIL_TPL_", "")
                        print(f"QuestManager: Triggering follow-up quest template '{next_quest_template_id}' for quest {quest.id}.")
                        # Note: This makes the quest available. Assigning it might be a separate step or rule.
                        await self.create_quest_from_template(guild_id_str, next_quest_template_id)
                    
                    elif action_string.startswith("NPC_STATEVAR_"):
                        parts = action_string.replace("NPC_STATEVAR_", "").split('_')
                        if len(parts) >= 4: # npc_id_varName_operation_value
                            npc_id, var_name, operation = parts[0], parts[1], parts[2].lower()
                            value_str = "_".join(parts[3:]) # Value might contain underscores

                            if self._npc_manager:
                                npc = self._npc_manager.get_npc(guild_id_str, npc_id)
                                if npc:
                                    if operation == "set":
                                        # Attempt to convert value to int/float if possible, else string
                                        try: npc.state_variables[var_name] = int(value_str)
                                        except ValueError:
                                            try: npc.state_variables[var_name] = float(value_str)
                                            except ValueError: npc.state_variables[var_name] = value_str
                                        print(f"QuestManager: NPC {npc_id} statevar '{var_name}' set to '{value_str}'.")
                                    elif operation == "increment":
                                        current_val = npc.state_variables.get(var_name, 0)
                                        try:
                                            increment_by = int(value_str)
                                            npc.state_variables[var_name] = int(current_val) + increment_by
                                            print(f"QuestManager: NPC {npc_id} statevar '{var_name}' incremented by {increment_by} to {npc.state_variables[var_name]}.")
                                        except ValueError:
                                            print(f"QuestManager: Invalid increment value '{value_str}' for NPC {npc_id} statevar '{var_name}'.")
                                    else:
                                        print(f"QuestManager: Unknown NPC_STATEVAR operation '{operation}' for NPC {npc_id}.")
                                    self._npc_manager.mark_npc_dirty(guild_id_str, npc_id)
                                else:
                                    print(f"QuestManager: NPC {npc_id} not found for STATEVAR change.")
                            else:
                                print("QuestManager: NPCManager not available for STATEVAR change.")
                        else:
                            print(f"QuestManager: Invalid NPC_STATEVAR string format: {action_string}")
                    # Add more parsers for other connection types here (e.g., relationship changes)

                except Exception as e:
                    print(f"QuestManager: Error processing connection string '{action_string}' for quest {quest.id}: {e}")
                    traceback.print_exc()

        # Distribute Rewards (only on success)
        if success and quest.rewards:
            print(f"QuestManager: Distributing rewards for successful quest {quest.id}...")
            char_to_reward = char_mgr.get_character(guild_id_str, char_id_str) if char_mgr else None
            if char_to_reward:
                # Experience
                exp_reward = quest.rewards.get('experience')
                if exp_reward is not None:
                    try:
                        exp_amount = int(exp_reward)
                        if hasattr(char_to_reward, 'experience'):
                            char_to_reward.experience += exp_amount
                            print(f"QuestManager: Awarded {exp_amount} XP to character {char_id_str}.")
                            if char_mgr: char_mgr.mark_character_dirty(guild_id_str, char_id_str)
                    except ValueError:
                        print(f"QuestManager: Invalid experience reward value '{exp_reward}' for quest {quest.id}.")

                # Items
                item_rewards = quest.rewards.get('items', [])
                if item_rewards and self._item_manager:
                    for item_reward_entry in item_rewards:
                        item_template_id: Optional[str] = None
                        quantity: int = 1
                        if isinstance(item_reward_entry, dict):
                            item_template_id = item_reward_entry.get('template_id')
                            quantity = int(item_reward_entry.get('quantity', 1))
                        elif isinstance(item_reward_entry, str): # Just template_id string
                            item_template_id = item_reward_entry
                        
                        if item_template_id:
                            try:
                                print(f"QuestManager: Attempting to create item '{item_template_id}' (x{quantity}) for char {char_id_str}.")
                                # Assuming ItemManager.create_item_from_template handles adding to character's inventory logic
                                # or at least sets ownership correctly.
                                await self._item_manager.create_item_from_template(
                                    guild_id=guild_id_str,
                                    item_template_id=item_template_id,
                                    owner_id=char_id_str,
                                    owner_type="character",
                                    quantity=quantity
                                )
                                print(f"QuestManager: Item '{item_template_id}' (x{quantity}) reward processed for char {char_id_str}.")
                            except Exception as e:
                                print(f"QuestManager: Error creating item reward '{item_template_id}' for quest {quest.id}: {e}")
                                traceback.print_exc()
                
                # Currency (Placeholder)
                currency_reward = quest.rewards.get('currency')
                if currency_reward is not None:
                    print(f"QuestManager: Currency reward found ({currency_reward}) for quest {quest.id}, but currency system not implemented.")
            else:
                print(f"QuestManager: Character {char_id_str} not found for distributing rewards for quest {quest.id}.")
        
        return True

    async def fail_quest(self, guild_id: str, quest_id: str, character_id: str, character_manager: Optional["CharacterManager"]) -> bool:
        return await self.complete_quest(guild_id, quest_id, character_id, character_manager, success=False)

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        print(f"QuestManager: Loading quests for guild {guild_id_str} from DB...")
        if not self._db_adapter: print(f"QuestManager: DB adapter missing for {guild_id_str}."); return
        
        campaign_data = kwargs.get('campaign_data') 
        self.load_quest_templates(guild_id_str, campaign_data)

        self._active_quests[guild_id_str] = {}
        self._dirty_quests.pop(guild_id_str, None)
        self._deleted_quest_ids.pop(guild_id_str, None)

        query = """SELECT id, name, description, status, influence_level, prerequisites, 
                          connections, stages, rewards, npc_involvement, guild_id
                          -- template_id, created_at, updated_at are not in Quest model constructor
                   FROM quests WHERE guild_id = ?"""
        try: rows = await self._db_adapter.fetchall(query, (guild_id_str,))
        except Exception as e: print(f"QuestManager: DB error fetching quests for {guild_id_str}: {e}"); traceback.print_exc(); return
        
        loaded_count = 0
        guild_quests_cache = self._active_quests[guild_id_str]
        for row in rows:
            try:
                data = dict(row)
                for field in ['prerequisites', 'connections', 'stages', 'rewards', 'npc_involvement']:
                    if data.get(field) and isinstance(data[field], str):
                        try: data[field] = json.loads(data[field])
                        except json.JSONDecodeError: 
                            print(f"QuestManager: Warning - Failed to parse JSON for field '{field}' in quest {data.get('id')}. Defaulting."); 
                            data[field] = [] if field in ['prerequisites'] else {}
                    elif data.get(field) is None: 
                         data[field] = [] if field in ['prerequisites'] else {}
                
                quest = Quest.from_dict(data)
                guild_quests_cache[quest.id] = quest
                loaded_count += 1
            except Exception as e:
                print(f"QuestManager: Error loading quest {data.get('id', 'N/A')} for guild {guild_id_str}: {e}"); traceback.print_exc()
        print(f"QuestManager: Loaded {loaded_count} quests for guild {guild_id_str}.")

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if not self._db_adapter: print(f"QuestManager: DB adapter missing for {guild_id_str}."); return

        ids_to_delete = list(self._deleted_quest_ids.get(guild_id_str, set()))
        if ids_to_delete:
            placeholders = ','.join(['?'] * len(ids_to_delete))
            delete_sql = f"DELETE FROM quests WHERE guild_id = ? AND id IN ({placeholders})"
            try:
                await self._db_adapter.execute(delete_sql, (guild_id_str, *ids_to_delete))
                self._deleted_quest_ids.pop(guild_id_str, None)
            except Exception as e: print(f"QuestManager: Error deleting quests for {guild_id_str}: {e}")

        dirty_ids = list(self._dirty_quests.get(guild_id_str, set()))
        quests_to_save_data = []
        successfully_prepared_ids = set()
        guild_quests_cache = self._active_quests.get(guild_id_str, {})

        for q_id in dirty_ids:
            quest = guild_quests_cache.get(q_id)
            if quest and str(getattr(quest, 'guild_id', None)) == guild_id_str:
                try:
                    quest_dict = quest.to_dict()
                    # Ensure all fields for SQL are present
                    data_tuple = (
                        quest_dict['id'], quest_dict['name'], quest_dict['description'],
                        quest_dict['status'], quest_dict['influence_level'],
                        json.dumps(quest_dict.get('prerequisites', [])), 
                        json.dumps(quest_dict.get('connections', {})),
                        json.dumps(quest_dict.get('stages', {})), 
                        json.dumps(quest_dict.get('rewards', {})),
                        json.dumps(quest_dict.get('npc_involvement', {})), 
                        guild_id_str,
                        # created_at is not in the tuple, should be handled by DB default
                        # updated_at is handled by DB `strftime`
                    )
                    quests_to_save_data.append(data_tuple)
                    successfully_prepared_ids.add(q_id)
                except Exception as e: print(f"QuestManager: Error preparing quest {q_id} for save: {e}")
        
        if quests_to_save_data:
            upsert_sql = """ 
                INSERT OR REPLACE INTO quests 
                (id, name, description, status, influence_level, prerequisites, connections, 
                 stages, rewards, npc_involvement, guild_id, updated_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            """ # 12 placeholders
            try:
                await self._db_adapter.execute_many(upsert_sql, quests_to_save_data)
                if guild_id_str in self._dirty_quests:
                    self._dirty_quests[guild_id_str].difference_update(successfully_prepared_ids)
                    if not self._dirty_quests[guild_id_str]: del self._dirty_quests[guild_id_str]
            except Exception as e: print(f"QuestManager: Error upserting quests for {guild_id_str}: {e}")
        print(f"QuestManager: Save state complete for guild {guild_id_str}.")


    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        print(f"QuestManager: Rebuilding runtime caches for guild {guild_id_str} (currently no complex caches to rebuild).")
        print(f"QuestManager: Rebuild runtime caches complete for guild {guild_id_str}.")

    def mark_quest_dirty(self, guild_id: str, quest_id: str) -> None:
        guild_id_str, quest_id_str = str(guild_id), str(quest_id)
        if guild_id_str in self._active_quests and quest_id_str in self._active_quests[guild_id_str]:
            self._dirty_quests.setdefault(guild_id_str, set()).add(quest_id_str)

print("DEBUG: QuestManager module defined.")
