from __future__ import annotations
import uuid
from typing import Dict, Any, List, Optional
from bot.game.models.base_model import BaseModel

class Quest(BaseModel):
    """
    Represents a quest in the game.
    """
    def __init__(self,
                 id: Optional[str] = None,
                 name_i18n: Optional[Dict[str, str]] = None,
                 description_i18n: Optional[Dict[str, str]] = None,
                 status: str = "available",
                 influence_level: str = "local",
                 prerequisites: Optional[List[str]] = None,
                 connections: Optional[Dict[str, List[str]]] = None,
                 stages: Optional[Dict[str, Any]] = None, # Will be processed for i18n
                 rewards: Optional[Dict[str, Any]] = None,
                 npc_involvement: Optional[Dict[str, str]] = None,
                 guild_id: str = "",
                 quest_giver_details_i18n: Optional[Dict[str, str]] = None,
                 consequences_summary_i18n: Optional[Dict[str, str]] = None,
                 # For backward compatibility
                 name: Optional[str] = None,
                 description: Optional[str] = None,
                 # New fields for generated_quests mapping and type distinction
                 title_i18n: Optional[Dict[str, str]] = None, # Alias for name_i18n from generated_quests
                 stages_json_str: Optional[str] = None, # Raw JSON strings for deferred parsing
                 rewards_json_str: Optional[str] = None,
                 prerequisites_json_str: Optional[str] = None,
                 consequences_json_str: Optional[str] = None,
                 ai_prompt_context_json_str: Optional[str] = None,
                 is_ai_generated: bool = False
                 ):
        super().__init__(id)

        # Handle name_i18n (priority: name_i18n, title_i18n, name, default)
        if name_i18n is not None:
            self.name_i18n = name_i18n
        elif title_i18n is not None: # específico para generated_quests
            self.name_i18n = title_i18n
        elif name is not None: # compatibilidad hacia atrás
            self.name_i18n = {"en": name}
        else:
            self.name_i18n = {"en": "Unnamed Quest"}

        # Handle description_i18n (priority: description_i18n, description, default)
        if description_i18n is not None:
            self.description_i18n = description_i18n
        elif description is not None: # compatibilidad hacia atrás
            self.description_i18n = {"en": description}
        else:
            self.description_i18n = {"en": ""}

        self.status = status
        self.influence_level = influence_level
        self.prerequisites = prerequisites if prerequisites is not None else []
        self.connections = connections if connections is not None else {}
        self.guild_id = guild_id # Set guild_id early

        self.quest_giver_details_i18n = quest_giver_details_i18n if quest_giver_details_i18n is not None else {"en": "", "ru": ""}
        self.consequences_summary_i18n = consequences_summary_i18n if consequences_summary_i18n is not None else {"en": "", "ru": ""}
        
        # Process stages for i18n
        processed_stages = {}
        if stages:
            for stage_id, stage_data in stages.items():
                new_stage_data = stage_data.copy()
                # Internationalize 'title'
                if 'title' in new_stage_data and 'title_i18n' not in new_stage_data:
                    new_stage_data['title_i18n'] = {"en": new_stage_data.pop('title'), "ru": new_stage_data.get('title', '')}
                elif 'title' in new_stage_data and 'title_i18n' in new_stage_data:
                    new_stage_data.pop('title')
                new_stage_data.setdefault('title_i18n', {"en": "", "ru": ""})
                
                # Internationalize 'description' (of stage)
                if 'description' in new_stage_data and 'description_i18n' not in new_stage_data:
                    new_stage_data['description_i18n'] = {"en": new_stage_data.pop('description'), "ru": new_stage_data.get('description', '')}
                elif 'description' in new_stage_data and 'description_i18n' in new_stage_data:
                    new_stage_data.pop('description')
                new_stage_data.setdefault('description_i18n', {"en": "", "ru": ""})

                # NEW: Internationalize 'requirements_description' for stage
                if 'requirements_description' in new_stage_data and 'requirements_description_i18n' not in new_stage_data:
                    new_stage_data['requirements_description_i18n'] = {"en": new_stage_data.pop('requirements_description'), "ru": new_stage_data.get('requirements_description', '')}
                elif 'requirements_description' in new_stage_data and 'requirements_description_i18n' in new_stage_data:
                    new_stage_data.pop('requirements_description')
                new_stage_data.setdefault('requirements_description_i18n', {"en": "", "ru": ""})

                # NEW: Internationalize 'alternative_solutions' for stage
                if 'alternative_solutions' in new_stage_data and 'alternative_solutions_i18n' not in new_stage_data:
                    new_stage_data['alternative_solutions_i18n'] = {"en": new_stage_data.pop('alternative_solutions'), "ru": new_stage_data.get('alternative_solutions', '')}
                elif 'alternative_solutions' in new_stage_data and 'alternative_solutions_i18n' in new_stage_data:
                    new_stage_data.pop('alternative_solutions')
                new_stage_data.setdefault('alternative_solutions_i18n', {"en": "", "ru": ""})
                
                # Ensure other expected AI fields for stages default if not present
                new_stage_data.setdefault('objective_type', "")
                new_stage_data.setdefault('target', None)
                new_stage_data.setdefault('quantity', 0)
                new_stage_data.setdefault('skill_check', None)

                processed_stages[stage_id] = new_stage_data
        self.stages = processed_stages
        
        self.rewards = rewards if rewards is not None else {}
        self.npc_involvement = npc_involvement if npc_involvement is not None else {}
        self.is_ai_generated = is_ai_generated # Store the flag

        # Store raw JSON strings if provided, to be parsed by manager or on demand
        # This allows Quest model to be a data container without direct json.loads dependency here.
        self.stages_json_str = stages_json_str
        self.rewards_json_str = rewards_json_str
        self.prerequisites_json_str = prerequisites_json_str
        self.consequences_json_str = consequences_json_str
        self.ai_prompt_context_json_str = ai_prompt_context_json_str

        # Add a 'consequences' field for generated quests, distinct from 'connections'
        self.consequences: Dict[str, Any] = {} # Parsed from consequences_json_str by manager if needed


    @property
    def name(self) -> str:
        """Provides a plain text name for the quest, derived from name_i18n."""
        # Assuming a default language preference can be accessed, e.g., from settings or a global context.
        # For simplicity, using 'en' or the first available language.
        default_lang = "en" # This could be configurable
        if self.name_i18n:
            return self.name_i18n.get(default_lang, next(iter(self.name_i18n.values()), str(self.id)))
        return str(self.id) # Fallback to ID if name_i18n is empty or not set

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the Quest object to a dictionary."""
        data = super().to_dict() # Gets 'id'
        data.update({
            "name_i18n": self.name_i18n,
            "description_i18n": self.description_i18n,
            "status": self.status,
            "influence_level": self.influence_level,
            "prerequisites": self.prerequisites, # This is List[str] for standard quests
            "connections": self.connections,    # This is Dict for standard quests
            "stages": self.stages, # Assumes stages are already in i18n format internally
            "rewards": self.rewards,
            "npc_involvement": self.npc_involvement,
            "quest_giver_details_i18n": self.quest_giver_details_i18n,
            "consequences_summary_i18n": self.consequences_summary_i18n,
            "guild_id": self.guild_id,
            "is_ai_generated": self.is_ai_generated,
            # Include raw JSON strings if they need to be persisted and were the source
            "stages_json_str": self.stages_json_str,
            "rewards_json_str": self.rewards_json_str,
            "prerequisites_json_str": self.prerequisites_json_str, # For generated quests
            "consequences_json_str": self.consequences_json_str, # For generated quests
            "ai_prompt_context_json_str": self.ai_prompt_context_json_str,
            "consequences": self.consequences, # Parsed consequences for generated quests
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Quest:
        """Deserializes a dictionary into a Quest object."""
        quest_id = data.get('id')
        if quest_id is None:
             quest_id = str(uuid.uuid4())
        
        data_copy = data.copy() # Work with a copy to pass to cls

        # Handle backward compatibility for name and description at top level
        # also consider title_i18n from generated_quests
        name_i18n_val = data_copy.get("name_i18n")
        if name_i18n_val is None:
            title_i18n_val = data_copy.get("title_i18n") # from generated_quests
            if title_i18n_val is not None:
                name_i18n_val = title_i18n_val
            elif "name" in data_copy: # old plain name
                name_i18n_val = {"en": data_copy.pop("name")}

        description_i18n_val = data_copy.get("description_i18n")
        if description_i18n_val is None and "description" in data_copy:
            description_i18n_val = {"en": data_copy.pop("description")}


        # For stages, the __init__ method will handle the internal i18n conversion.
        # We just pass the stages data as is from the input dictionary.
        # If stages in `data_copy` contain old 'title' or 'description', __init__ will convert them.
        
        # Remove old fields if new ones are present to avoid passing both to __init__
        if "name" in data_copy and name_i18n_val is not None: data_copy.pop("name", None)
        if "title_i18n" in data_copy: data_copy.pop("title_i18n", None)
        if "description" in data_copy and description_i18n_val is not None: data_copy.pop("description", None)

        # Extract raw JSON strings if present
        stages_json_str = data_copy.pop("stages_json_str", data_copy.pop("stages_json", None))
        rewards_json_str = data_copy.pop("rewards_json_str", data_copy.pop("rewards_json", None))
        prerequisites_json_str = data_copy.pop("prerequisites_json_str", data_copy.pop("prerequisites_json", None))
        consequences_json_str = data_copy.pop("consequences_json_str", data_copy.pop("consequences_json", None))
        ai_prompt_context_json_str = data_copy.pop("ai_prompt_context_json_str", data_copy.pop("ai_prompt_context_json", None))

        # If stages/rewards etc. are passed as already parsed dicts/lists (e.g. from campaign data)
        # and not as _json_str, they will be used by __init__.
        # If they are passed as _json_str, __init__ will store them, and manager can parse them later.
        # For clarity, ensure that if `stages` is a string, it's treated as `stages_json_str`.
        if isinstance(data_copy.get("stages"), str):
            stages_json_str = data_copy.pop("stages")
        if isinstance(data_copy.get("rewards"), str):
            rewards_json_str = data_copy.pop("rewards")
        if isinstance(data_copy.get("prerequisites"), str): # prerequisites can be List[str] or JSON string
            prerequisites_json_str = data_copy.pop("prerequisites")
        if isinstance(data_copy.get("consequences"), str):
            consequences_json_str = data_copy.pop("consequences")


        quest_obj = cls(
            id=quest_id,
            name_i18n=name_i18n_val,
            description_i18n=description_i18n_val,
            status=data_copy.get("status", "available"),
            influence_level=data_copy.get("influence_level", "local"),
            prerequisites=data_copy.get("prerequisites") if not prerequisites_json_str else None, # Prefer parsed
            connections=data_copy.get("connections", {}),
            stages=data_copy.get("stages") if not stages_json_str else None, # Prefer parsed
            rewards=data_copy.get("rewards") if not rewards_json_str else None, # Prefer parsed
            npc_involvement=data_copy.get("npc_involvement", {}),
            guild_id=data_copy.get("guild_id", ""),
            quest_giver_details_i18n=data_copy.get("quest_giver_details_i18n", {"en": "", "ru": ""}) or {"en": "", "ru": ""},
            consequences_summary_i18n=data_copy.get("consequences_summary_i18n", {"en": "", "ru": ""}) or {"en": "", "ru": ""},
            is_ai_generated=data_copy.get("is_ai_generated", False),
            # Pass raw JSON strings
            stages_json_str=stages_json_str,
            rewards_json_str=rewards_json_str,
            prerequisites_json_str=prerequisites_json_str,
            consequences_json_str=consequences_json_str,
            ai_prompt_context_json_str=ai_prompt_context_json_str
        )

        # If consequences were passed as a parsed dict (not json string)
        if "consequences" in data_copy and not consequences_json_str and isinstance(data_copy["consequences"], dict):
            quest_obj.consequences = data_copy["consequences"]

        return quest_obj

# Example usage (optional, for testing)
# if __name__ == '__main__':
    # Create a sample quest (OLD __main__ REMOVED as per typical model file structure)
    # ... (old __main__ content would be here if kept) ...
        "description": "An ancient artifact has been lost, and it's up to you to find it.", # Old format
        "guild_id": "guild_123",
        "stages": {
            "stage_1": {
                "title": "Find Clues", # Old format
                "description": "Search the old library for clues.", # Old format
                "objectives": [{"type": "interact", "target": "npc_librarian"}]
            },
            "stage_2": {
                "title_i18n": {"en": "Retrieve the Artifact", "ru": "Добудьте Артефакт"}, # New format
                "description_i18n": {"en": "The artifact is in the dragon's lair.", "ru": "Артефакт в логове дракона."},
                "objectives": [{"type": "defeat_enemy", "enemy_id": "dragon_boss"}]
            }
        },
        "rewards": {"experience": 100, "items": ["rare_sword_id"]},
        "npc_involvement": {"giver": "npc_elder_1", "target_location": "dungeon_of_shadows"}
    }
    quest1 = Quest.from_dict(quest_data)
    quest1.status = "active"
    assert quest1.name_i18n == {"en": "The Lost Artifact"}
    assert quest1.description_i18n == {"en": "An ancient artifact has been lost, and it's up to you to find it."}
    assert quest1.stages["stage_1"]["title_i18n"] == {"en": "Find Clues"}
    assert quest1.stages["stage_1"]["description_i18n"] == {"en": "Search the old library for clues."}
    assert "title" not in quest1.stages["stage_1"] # Old key should be removed
    assert quest1.stages["stage_2"]["title_i18n"] == {"en": "Retrieve the Artifact", "ru": "Добудьте Артефакт"}
    quest1.prerequisites.append("previous_quest_completed")

    print("Quest 1 ID:", quest1.id)
    print("Quest 1 Dict:", quest1.to_dict())
    print("Quest 1 Stage 1 Title i18n:", quest1.stages["stage_1"]["title_i18n"])


    # Create another quest with minimal data to test defaults (using new i18n fields directly)
    quest2_data = {
        "id": "fixed_quest_id_002",
        "name_i18n": {"en": "Simple Task", "ru": "Простое Задание"},
        "guild_id": "guild_456"
    }
    quest2 = Quest.from_dict(quest2_data)
    print("\nQuest 2 ID:", quest2.id)
    print("Quest 2 Name i18n:", quest2.name_i18n)
    print("Quest 2 Description i18n (default):", quest2.description_i18n)
    print("Quest 2 Dict:", quest2.to_dict())

    # Test creation with no data (should use all defaults)
    # For Quest(), need to provide guild_id if it's required by logic, but not by __init__ default
    quest3 = Quest(guild_id="guild_789") 
    print("\nQuest 3 ID:", quest3.id)
    print("Quest 3 Name i18n (default):", quest3.name_i18n)
    print("Quest 3 Dict:", quest3.to_dict())
    # quest3.guild_id = "guild_789" # Set if not passed in init and required elsewhere
    # print("Quest 3 Dict (after guild_id):", quest3.to_dict())

    # Test creation with explicit None for optional fields (using old field names for from_dict conversion)
    quest4_data = {
        "name": "Test None Quest", # Old format
        "guild_id": "guild_abc",
        "prerequisites": None,
        "connections": None,
        "stages": None, # Will become {}
        "rewards": None, # Will become {}
        "npc_involvement": None, # Will become {}
    }
    quest4 = Quest.from_dict(quest4_data)
    print("\nQuest 4 ID:", quest4.id)
    assert quest4.name_i18n == {"en": "Test None Quest"}
    assert quest4.stages == {}
    print("Quest 4 Dict:", quest4.to_dict())

    # Verifying BaseModel's id creation
    base_instance = BaseModel()
    print(f"\nBaseModel instance ID: {base_instance.id}")
    base_instance_with_id = BaseModel(id="custom_id_base")
    print(f"BaseModel instance with custom ID: {base_instance_with_id.id}")

    quest_instance_no_id = Quest(guild_id="test_guild")
    print(f"Quest instance (no id provided) ID: {quest_instance_no_id.id}")
    quest_instance_with_id = Quest(id="custom_id_quest", guild_id="test_guild")
    print(f"Quest instance (id provided) ID: {quest_instance_with_id.id}")

    # Checking from_dict behavior with an ID present in the dictionary
    quest_from_dict_with_id = Quest.from_dict({"id": "existing_id_123", "name": "From Dict With ID", "guild_id": "test_guild"})
    print(f"Quest from_dict (id in data) ID: {quest_from_dict_with_id.id}, Name: {quest_from_dict_with_id.name}")

    # Checking from_dict behavior without an ID in the dictionary
    quest_from_dict_no_id = Quest.from_dict({"name": "From Dict No ID", "guild_id": "test_guild"})
    print(f"Quest from_dict (no id in data) ID: {quest_from_dict_no_id.id}, Name: {quest_from_dict_no_id.name}")


