# bot/game/managers/quest_manager.py

from __future__ import annotations
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

        # As per prompt, look for "quests" key in campaign_data, which is a list of dicts.
        # The previous subtask for CampaignLoader used "quest_templates" as the key.
        # Using "quests" here as specified for this subtask.
        if campaign_data and "quests" in campaign_data: 
            templates_list: List[Dict[str, Any]] = campaign_data.get("quests", [])
            if isinstance(templates_list, list):
                for template_dict in templates_list:
                    if isinstance(template_dict, dict) and "id" in template_dict:
                        tpl_id = str(template_dict["id"])
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
