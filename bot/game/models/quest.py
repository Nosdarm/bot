from __future__ import annotations
import uuid
import json
from typing import Dict, Any, List, Optional # Union might be unused
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
                 guild_id: str, # MOVED: Made required and placed before optionals
                 id: Optional[str] = None,
                 name_i18n: Optional[Dict[str, str]] = None,
                 description_i18n: Optional[Dict[str, str]] = None,
                 selected_language: Optional[str] = "en",
                 status: str = "available",
                 influence_level: str = "local",
                 prerequisites: Optional[List[str]] = None,
                 connections: Optional[Dict[str, List[str]]] = None,
                 steps: Optional[List['QuestStep']] = None,
                 rewards: Optional[Dict[str, Any]] = None,
                 npc_involvement: Optional[Dict[str, str]] = None,
                 # guild_id: str, # Original position commented out
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
        # self._parsed_steps: Optional[List[QuestStep]] = None # REMOVED Cache for parsed steps

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
        
        self.steps: List['QuestStep'] = steps if steps is not None else [] # ADDED

        self.rewards = rewards if rewards is not None else {}
        self.npc_involvement = npc_involvement if npc_involvement is not None else {}
        self.is_ai_generated = is_ai_generated
        self.rewards_json_str = rewards_json_str if rewards_json_str is not None else "{}"
        self.consequences_json_str = consequences_json_str # Already defaults to "{}" in params
        self.ai_prompt_context_json_str = ai_prompt_context_json_str if ai_prompt_context_json_str is not None else "{}"
        self.consequences: Dict[str, Any] = {}
        self.selected_language = selected_language if selected_language else "en"

    # REMOVED @property def steps(self) and self._parsed_steps cache

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
            "steps": [step.to_dict() for step in self.steps], # MODIFIED
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
        guild_id_val = data_copy.pop("guild_id") # MODIFIED: Made mandatory

        name_i18n_val = data_copy.pop("name_i18n", None)
        if name_i18n_val is None:
            title_i18n_val = data_copy.pop("title_i18n", None)
            if title_i18n_val is not None: name_i18n_val = title_i18n_val
            elif "name" in data_copy: name_i18n_val = {"en": data_copy.pop("name")}

        description_i18n_val = data_copy.pop("description_i18n", None)
        if description_i18n_val is None and "description" in data_copy:
            description_i18n_val = {"en": data_copy.pop("description")}
        
        # REMOVED steps_data_val and steps_json_str_val related logic for cls() call

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
            # steps_data and steps_json_str REMOVED from here
            rewards=data_copy.get("rewards") if not rewards_json_str_val and isinstance(data_copy.get("rewards"), dict) else {},
            rewards_json_str=rewards_json_str_val, # Default in __init__
            npc_involvement=data_copy.get("npc_involvement", {}),
            guild_id=guild_id_val, # MODIFIED
            quest_giver_details_i18n=data_copy.get("quest_giver_details_i18n") or {"en": "", "ru": ""},
            consequences_summary_i18n=data_copy.get("consequences_summary_i18n") or {"en": "", "ru": ""},
            consequences_json_str=consequences_json_str_val, # Default in __init__
            ai_prompt_context_json_str=data_copy.pop("ai_prompt_context_json_str", data_copy.pop("ai_prompt_context_json", None)), # Default in __init__
            is_ai_generated=data_copy.get("is_ai_generated", False),
            selected_language=data_copy.get("selected_language", "en")
            # steps parameter is not passed here, will be set below
        )

        parsed_steps_list = []
        # Prioritize direct 'steps' list if available
        steps_list_data = data_copy.pop('steps', None)
        if isinstance(steps_list_data, list):
            for step_dict_data in steps_list_data:
                if isinstance(step_dict_data, dict):
                    step_dict_data['quest_id'] = quest_obj.id
                    if 'guild_id' not in step_dict_data: # Ensure guild_id for step
                        step_dict_data['guild_id'] = quest_obj.guild_id
                    parsed_steps_list.append(QuestStep.from_dict(step_dict_data))
                else:
                    logger.warning(f"Step data is not a dict: {step_dict_data} for quest {quest_obj.id}")
        else: # Fallback for backward compatibility with steps_json/steps_json_str
            legacy_steps_json_str = data_copy.pop('steps_json', data_copy.pop('steps_json_str', data_copy.pop('stages_json_str', None)))
            # Backward compatibility for 'stages' which might have been an old list of dicts or json string
            if legacy_steps_json_str is None:
                old_stages_data = data_copy.pop("stages", None)
                if isinstance(old_stages_data, list): # if stages was List[Dict]
                    legacy_steps_json_str = json.dumps(old_stages_data)
                elif isinstance(old_stages_data, str): # if stages was json string
                     legacy_steps_json_str = old_stages_data
                elif isinstance(old_stages_data, dict): # if stages was Dict[str, Dict]
                    converted_stages = []
                    for stage_id, stage_content in old_stages_data.items():
                        if isinstance(stage_content, dict):
                            if 'id' not in stage_content: stage_content['id'] = stage_id
                            stage_content.setdefault('step_order', len(converted_stages))
                            converted_stages.append(stage_content)
                        else:
                            logger.warning(f"Malformed stage content during old 'stages' dict conversion for id '{stage_id}' in quest '{quest_obj.id}': {stage_content}")
                    if converted_stages:
                        legacy_steps_json_str = json.dumps(converted_stages)


            if legacy_steps_json_str and legacy_steps_json_str not in ("[]", "{}"):
                try:
                    steps_data_from_json = json.loads(legacy_steps_json_str)
                    if isinstance(steps_data_from_json, list):
                        for step_dict_data_json in steps_data_from_json:
                            if isinstance(step_dict_data_json, dict):
                                step_dict_data_json['quest_id'] = quest_obj.id
                                if 'guild_id' not in step_dict_data_json: # Ensure guild_id for step
                                    step_dict_data_json['guild_id'] = quest_obj.guild_id
                                parsed_steps_list.append(QuestStep.from_dict(step_dict_data_json))
                            else:
                                logger.warning(f"Step data from JSON is not a dict: {step_dict_data_json} for quest {quest_obj.id}")
                    else:
                        logger.warning(f"Parsed legacy_steps_json_str was not a list for quest {quest_obj.id}: {steps_data_from_json}")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse legacy_steps_json_str for quest '{quest_obj.id}': {e}. Data: {legacy_steps_json_str}")
        quest_obj.steps = parsed_steps_list

        if "consequences" in data_copy and not consequences_json_str_val and isinstance(data_copy["consequences"], dict):
            # This was for a parsed 'consequences' dict. With 'consequences_json_str' being primary,
            # this direct assignment to self.consequences might be less relevant or handled by a property.
            # For now, Quest.__init__ initializes self.consequences = {}
            # If needed, parse from consequences_json_str on demand via a property.
            pass # quest_obj.consequences = data_copy["consequences"]

        return quest_obj
