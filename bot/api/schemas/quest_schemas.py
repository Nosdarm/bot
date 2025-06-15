from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

class PlayerEventPayloadSchema(BaseModel):
    guild_id: str = Field(..., description="The ID of the guild where the event occurs.")
    character_id: str = Field(..., description="The ID of the character triggering or involved in the event.")
    event_data: Dict[str, Any] = Field(..., description="A dictionary containing details of the event (e.g., event_type, parameters).")

class QuestStepSchema(BaseModel):
    id: str
    quest_id: str
    guild_id: str
    title_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    requirements_i18n: Optional[Dict[str, str]] = None
    # required_mechanics_json: str # Not usually exposed directly as raw JSON
    # abstract_goal_json: str    # Not usually exposed directly as raw JSON
    # conditions_json: str       # Not usually exposed directly as raw JSON
    step_order: int
    status: str
    # assignee_type: Optional[str] = None # Usually implicit by character_id context
    # assignee_id: Optional[str] = None   # Usually implicit
    # consequences_json: str     # Not usually exposed directly
    # linked_location_id: Optional[str] = None # Could be exposed if useful
    # linked_npc_id: Optional[str] = None      # Could be exposed
    # linked_item_id: Optional[str] = None     # Could be exposed
    # linked_guild_event_id: Optional[str] = None # Could be exposed

    class Config:
        from_attributes = True # Changed from orm_mode for Pydantic v2

class AIQuestGenerationRequestSchema(BaseModel):
    guild_id: str = Field(..., description="The guild ID for which to generate the quest.")
    quest_idea: str = Field(..., description="The core idea, theme, or trigger for the quest.")
    triggering_entity_id: Optional[str] = Field(None, description="Optional ID of an entity (e.g., NPC, item) that triggered this quest idea.")
    target_character_id: Optional[str] = Field(None, description="Optional ID of the character for whom the quest context should be primarily focused.")

class QuestSchema(BaseModel):
    id: str
    guild_id: str
    name_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    status: str
    # influence_level: Optional[str] = None # Expose if needed
    # prerequisites_json_str: Optional[str] = None # Not usually exposed
    # connections_json: Optional[Dict[str, List[str]]] = None # Expose if needed
    # rewards_json_str: Optional[str] = None # Not usually exposed
    # npc_involvement_json: Optional[Dict[str, str]] = None # Expose if needed
    # quest_giver_details_i18n: Optional[Dict[str, str]] = None # Expose if needed
    # consequences_summary_i18n: Optional[Dict[str, str]] = None # Expose if needed
    is_ai_generated: bool
    steps: List[QuestStepSchema]

    class Config:
        from_attributes = True # Changed from orm_mode for Pydantic v2
