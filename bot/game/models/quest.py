from __future__ import annotations
import uuid
import json
from typing import Dict, Any, List, Optional, Union # Added Union
from bot.game.models.base_model import BaseModel
from bot.game.models.quest_step import QuestStep # Import QuestStep
from bot.utils.i18n_utils import get_i18n_text
# Import logger for warnings
import logging
logger = logging.getLogger(__name__)

class Quest(BaseModel):
    """
    Represents a quest in the game.
    """
    def __init__(self,
                 id: Optional[str] = None,
                 name_i18n: Optional[Dict[str, str]] = None,
                 description_i18n: Optional[Dict[str, str]] = None,
                 selected_language: Optional[str] = "en",
                 status: str = "available",
                 influence_level: str = "local",
                 prerequisites: Optional[List[str]] = None,
                 connections: Optional[Dict[str, List[str]]] = None,
                 steps_data: Optional[List[Dict[str, Any]]] = None,
                 steps_json_str: Optional[str] = None,
                 rewards: Optional[Dict[str, Any]] = None,
                 npc_involvement: Optional[Dict[str, str]] = None,
                 guild_id: str = "",
                 quest_giver_details_i18n: Optional[Dict[str, str]] = None,
                 consequences_summary_i18n: Optional[Dict[str, str]] = None,
                 name: Optional[str] = None,
                 description: Optional[str] = None,
                 title_i18n: Optional[Dict[str, str]] = None,
                 rewards_json_str: Optional[str] = None,
                 prerequisites_json_str: Optional[str] = None,
                 consequences_json_str: Optional[str] = "{}",
                 ai_prompt_context_json_str: Optional[str] = None,
                 is_ai_generated: bool = False
                 ):
        super().__init__(id)
        self._parsed_steps: Optional[List[QuestStep]] = None # Cache for parsed steps

        # Handle name_i18n
        if name_i18n is not None:
            self.name_i18n = name_i18n
        elif title_i18n is not None:
            self.name_i18n = title_i18n
        elif name is not None:
            self.name_i18n = {"en": name}
        else:
            self.name_i18n = {"en": "Unnamed Quest"}

        # Handle description_i18n
        if description_i18n is not None:
            self.description_i18n = description_i18n
        elif description is not None:
            self.description_i18n = {"en": description}
        else:
            self.description_i18n = {"en": ""}

        self.status = status
        self.influence_level = influence_level
        self.prerequisites = prerequisites if prerequisites is not None else []
        self.prerequisites_json_str = prerequisites_json_str if prerequisites_json_str is not None else "{}"
        self.connections = connections if connections is not None else {}
        self.guild_id = guild_id
        self.quest_giver_details_i18n = quest_giver_details_i18n if quest_giver_details_i18n is not None else {"en": "", "ru": ""}
        self.consequences_summary_i18n = consequences_summary_i18n if consequences_summary_i18n is not None else {"en": "", "ru": ""}
        
        if steps_data is not None:
            # Ensure step_order is present if using QuestStep.from_dict later
            for idx, step_d in enumerate(steps_data):
                step_d.setdefault('step_order', idx)
            self.steps_json: str = json.dumps(steps_data)
        elif steps_json_str is not None:
            self.steps_json: str = steps_json_str
        else:
            self.steps_json: str = "[]" # Default to empty JSON array for a list of steps

        self.rewards = rewards if rewards is not None else {}
        self.npc_involvement = npc_involvement if npc_involvement is not None else {}
        self.is_ai_generated = is_ai_generated
        self.rewards_json_str = rewards_json_str if rewards_json_str is not None else "{}"
        self.consequences_json_str = consequences_json_str # Already defaults to "{}" in params
        self.ai_prompt_context_json_str = ai_prompt_context_json_str if ai_prompt_context_json_str is not None else "{}"
        self.consequences: Dict[str, Any] = {}
        self.selected_language = selected_language if selected_language else "en"

    @property
    def steps(self) -> List[QuestStep]:
        """Parses steps_json into a list of QuestStep objects on demand and caches the result."""
        if self._parsed_steps is None:
            self._parsed_steps = []
            if not self.steps_json or self.steps_json == "{}": # Check for empty object string too
                # If it was "{}" due to old default, treat as empty list
                logger.warning(f"Quest '{self.id}' steps_json was empty object '{{}}', treating as empty list '[]'.")
            elif self.steps_json != "[]": # Avoid parsing if it's explicitly an empty list string
                try:
                    steps_data_list = json.loads(self.steps_json)
                    if not isinstance(steps_data_list, list):
                        logger.error(f"Quest '{self.id}' steps_json did not decode to a list: {type(steps_data_list)}. Data: {self.steps_json}")
                        # Attempt to wrap if it's a single dict object, which might be an error from older data
                        if isinstance(steps_data_list, dict) and steps_data_list: # Non-empty dict
                             logger.warning(f"Quest '{self.id}' steps_json was a dict, wrapping in a list. Data: {steps_data_list}")
                             steps_data_list = [steps_data_list]
                        else: # Not a list and not a non-empty dict we can auto-correct
                            steps_data_list = [] # Fallback to empty list

                    for idx, step_data in enumerate(steps_data_list):
                        if not isinstance(step_data, dict):
                            logger.error(f"Quest '{self.id}', step data at index {idx} is not a dict: {step_data}. Skipping.")
                            continue
                        # Ensure step_order is present for QuestStep, default from list index if missing
                        step_data.setdefault('step_order', idx)
                        # QuestStep.from_dict expects all fields, provide defaults if partial data
                        # This is simplified; QuestStep.from_dict should handle defaults for its own fields.
                        self._parsed_steps.append(QuestStep.from_dict(step_data))
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse steps_json for quest '{self.id}': {e}. Data: {self.steps_json}")
                    # Keep self._parsed_steps as empty list
                except Exception as e: # Catch other potential errors during QuestStep creation
                    logger.error(f"Error creating QuestStep objects for quest '{self.id}': {e}. Data: {self.steps_json}")

        return self._parsed_steps

    def _get_current_lang(self) -> str:
        return self.selected_language or "en"

    def _get_i18n_data_for_quest(self) -> Dict[str, Any]:
        return {
            "name_i18n": self.name_i18n,
            "description_i18n": self.description_i18n,
            "quest_giver_details_i18n": self.quest_giver_details_i18n,
            "consequences_summary_i18n": self.consequences_summary_i18n,
            "id": self.id
        }

    @property
    def name(self) -> str:
        return get_i18n_text(self._get_i18n_data_for_quest(), "name", self._get_current_lang(), "en")

    @property
    def description(self) -> str:
        return get_i18n_text(self._get_i18n_data_for_quest(), "description", self._get_current_lang(), "en")

    @property
    def quest_giver_details(self) -> str:
        return get_i18n_text(self._get_i18n_data_for_quest(), "quest_giver_details", self._get_current_lang(), "en")

    @property
    def consequences_summary(self) -> str:
        return get_i18n_text(self._get_i18n_data_for_quest(), "consequences_summary", self._get_current_lang(), "en")

    def get_step_by_order(self, step_order: int) -> Optional[QuestStep]:
        """Helper to get a step by its order/index."""
        for step in self.steps: # Accesses the property, which handles parsing
            if step.step_order == step_order:
                return step
        return None

    def get_step_title(self, step_order: int) -> str:
        step = self.get_step_by_order(step_order)
        if not step:
            return f"Step with order {step_order} not found"
        # QuestStep.title_i18n is Dict[str, str]
        return get_i18n_text({"title_i18n": step.title_i18n}, "title", self._get_current_lang(), "en")

    def get_step_description(self, step_order: int) -> str:
        step = self.get_step_by_order(step_order)
        if not step:
            return f"Step with order {step_order} not found"
        # QuestStep.description_i18n is Dict[str, str]
        return get_i18n_text({"description_i18n": step.description_i18n}, "description", self._get_current_lang(), "en")

    def get_step_requirements_description(self, step_order: int) -> str:
        # Assuming QuestStep does not have 'requirements_description_i18n' directly
        # This method might need to be re-evaluated based on QuestStep's actual fields
        # For now, let's assume it's a placeholder or QuestStep needs this field.
        # If QuestStep.required_mechanics_json or abstract_goal_json should be used, this needs custom logic.
        step = self.get_step_by_order(step_order)
        if not step:
            return f"Step with order {step_order} not found for requirements description"
        # Placeholder:
        return f"Requirements description for step {step_order} (not implemented in QuestStep i18n)"


    def get_step_alternative_solutions(self, step_order: int) -> str:
        # Similar to requirements_description, assuming this is not a direct i18n field in QuestStep
        step = self.get_step_by_order(step_order)
        if not step:
            return f"Step with order {step_order} not found for alternative solutions"
        # Placeholder:
        return f"Alternative solutions for step {step_order} (not implemented in QuestStep i18n)"

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "name_i18n": self.name_i18n,
            "description_i18n": self.description_i18n,
            "selected_language": self.selected_language,
            "status": self.status,
            "influence_level": self.influence_level,
            "prerequisites": self.prerequisites,
            "prerequisites_json_str": self.prerequisites_json_str,
            "connections": self.connections,
            "steps_json": self.steps_json,
            "rewards": self.rewards,
            "rewards_json_str": self.rewards_json_str,
            "npc_involvement": self.npc_involvement,
            "quest_giver_details_i18n": self.quest_giver_details_i18n,
            "consequences_summary_i18n": self.consequences_summary_i18n,
            "guild_id": self.guild_id,
            "is_ai_generated": self.is_ai_generated,
            "consequences_json_str": self.consequences_json_str,
            "ai_prompt_context_json_str": self.ai_prompt_context_json_str,
            "name": self.name,
            "description": self.description,
            "quest_giver_details": self.quest_giver_details,
            "consequences_summary": self.consequences_summary,
        })
        data.pop("stages", None)
        data.pop("stages_json_str", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Quest:
        quest_id = data.get('id')
        data_copy = data.copy()

        name_i18n_val = data_copy.pop("name_i18n", None)
        if name_i18n_val is None:
            title_i18n_val = data_copy.pop("title_i18n", None)
            if title_i18n_val is not None: name_i18n_val = title_i18n_val
            elif "name" in data_copy: name_i18n_val = {"en": data_copy.pop("name")}

        description_i18n_val = data_copy.pop("description_i18n", None)
        if description_i18n_val is None and "description" in data_copy:
            description_i18n_val = {"en": data_copy.pop("description")}
        
        steps_data_val = data_copy.pop("steps_data", None)
        steps_json_str_val = data_copy.pop("steps_json", data_copy.pop("steps_json_str", data_copy.pop("stages_json_str", None)))

        old_stages_dict = data_copy.pop("stages", None)
        if steps_data_val is None and steps_json_str_val is None and old_stages_dict is not None:
            if isinstance(old_stages_dict, dict): # Old format Dict[str, Dict]
                 # Convert old stages dict (id -> data) to list of dicts (steps_data)
                steps_data_val = []
                for stage_id, stage_content in old_stages_dict.items():
                    if isinstance(stage_content, dict):
                        if 'id' not in stage_content: stage_content['id'] = stage_id
                        # Ensure step_order is present, default based on iteration if not found
                        stage_content.setdefault('step_order', len(steps_data_val))
                        steps_data_val.append(stage_content)
                    else: # Log malformed stage content
                        logger.warning(f"Malformed stage content for id '{stage_id}' in quest '{quest_id}': {stage_content}")
            elif isinstance(old_stages_dict, str): # It was actually a JSON string
                steps_json_str_val = old_stages_dict


        rewards_json_str_val = data_copy.pop("rewards_json_str", data_copy.pop("rewards_json", None))
        if isinstance(data_copy.get("rewards"), str):
            rewards_json_str_val = data_copy.pop("rewards")

        prerequisites_val = data_copy.get("prerequisites")
        prerequisites_json_str_val = data_copy.pop("prerequisites_json_str", data_copy.pop("prerequisites_json", None))
        if isinstance(prerequisites_val, str):
            prerequisites_json_str_val = data_copy.pop("prerequisites")
            prerequisites_val = None

        consequences_json_str_val = data_copy.pop("consequences_json_str", data_copy.pop("consequences_json", data_copy.pop("consequences_str", None))) # Added consequences_str
        if isinstance(data_copy.get("consequences"), str):
            consequences_json_str_val = data_copy.pop("consequences")

        # Ensure consequences_json_str_val is not None before passing to __init__
        # as __init__ expects str, not None for this parameter.
        if consequences_json_str_val is None: consequences_json_str_val = "{}"


        quest_obj = cls(
            id=quest_id,
            name_i18n=name_i18n_val,
            description_i18n=description_i18n_val,
            status=data_copy.get("status", "available"),
            influence_level=data_copy.get("influence_level", "local"),
            prerequisites=prerequisites_val if prerequisites_val and not prerequisites_json_str_val else None,
            prerequisites_json_str=prerequisites_json_str_val, # Default in __init__
            connections=data_copy.get("connections", {}),
            steps_data=steps_data_val,
            steps_json_str=steps_json_str_val, # Default to "[]" in __init__ if both are None
            rewards=data_copy.get("rewards") if not rewards_json_str_val and isinstance(data_copy.get("rewards"), dict) else {},
            rewards_json_str=rewards_json_str_val, # Default in __init__
            npc_involvement=data_copy.get("npc_involvement", {}),
            guild_id=data_copy.get("guild_id", ""),
            quest_giver_details_i18n=data_copy.get("quest_giver_details_i18n") or {"en": "", "ru": ""},
            consequences_summary_i18n=data_copy.get("consequences_summary_i18n") or {"en": "", "ru": ""},
            consequences_json_str=consequences_json_str_val, # Default in __init__
            ai_prompt_context_json_str=data_copy.pop("ai_prompt_context_json_str", data_copy.pop("ai_prompt_context_json", None)), # Default in __init__
            is_ai_generated=data_copy.get("is_ai_generated", False),
            selected_language=data_copy.get("selected_language", "en")
        )

        if "consequences" in data_copy and not consequences_json_str_val and isinstance(data_copy["consequences"], dict):
            # This was for a parsed 'consequences' dict. With 'consequences_json_str' being primary,
            # this direct assignment to self.consequences might be less relevant or handled by a property.
            # For now, Quest.__init__ initializes self.consequences = {}
            # If needed, parse from consequences_json_str on demand via a property.
            pass # quest_obj.consequences = data_copy["consequences"]

        return quest_obj