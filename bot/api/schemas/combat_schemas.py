# bot/api/schemas/combat_schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal

# --- Participant Schemas ---
class CombatPosition(BaseModel):
    x: int
    y: int
    z: Optional[int] = 0 # Optional z-coordinate

class CombatParticipantStatusEffect(BaseModel):
    effect_id: str # ID of the status effect
    name_i18n: Dict[str, str] # e.g. {"en": "Poisoned"}
    duration_turns: Optional[int] = None
    # other relevant details like magnitude, source

class CombatParticipantData(BaseModel):
    entity_id: str = Field(..., description="ID of the character or NPC.")
    entity_type: Literal["character", "npc"] = Field(..., description="Type of the entity.")
    team_id: str = Field("default", description="Team identifier (e.g., 'A', 'B', 'player_team', 'enemy_team').")
    initiative: Optional[int] = Field(None, description="Calculated initiative for turn order.")
    current_hp: int = Field(..., description="Current health points of the participant.")
    max_hp: int = Field(..., description="Maximum health points of the participant.")
    status_effects: List[CombatParticipantStatusEffect] = Field(default_factory=list, description="List of active status effects.")
    initial_position: Optional[CombatPosition] = Field(None, description="Initial position of the participant on the combat map.")
    # Other stats relevant for combat display or logic could be included if needed (e.g., armor_class)

# --- Combat Encounter Schemas ---
class CombatEncounterBase(BaseModel):
    location_id: str = Field(..., description="ID of the location where the combat takes place.")
    participants_data: List[CombatParticipantData] = Field(..., min_items=1, description="List of participants involved in the combat.")
    initial_positions: Optional[Dict[str, CombatPosition]] = Field(None, description="Overall initial positions if not per-participant, keyed by entity_id.")
    combat_rules_snapshot: Optional[Dict[str, Any]] = Field(None, description="Snapshot of relevant game rules at the start of combat.")
    # state_variables from model can be here if API needs to set them initially

class CombatEncounterCreate(CombatEncounterBase):
    # guild_id will come from path parameter
    # id, status, current_round, turn_order, turn_log_structured will be set by server
    pass

class CombatTurnLogEntry(BaseModel): # For structured turn log
    round: int
    actor_entity_id: str
    action_description_i18n: Dict[str, str] # e.g., {"en": "Attacks Target X with Sword"}
    targets_info: Optional[List[Dict[str, Any]]] = None # e.g., [{"target_id": "Y", "effect": "10 damage"}]
    raw_action_details: Optional[Dict[str, Any]] = None # e.g., ability_id used, dice rolls

class CombatEncounterResponse(CombatEncounterBase):
    id: str = Field(..., description="Unique ID of the combat encounter.")
    guild_id: str = Field(..., description="Guild ID this combat belongs to.")
    status: str = Field(..., description="Current status of the combat (e.g., 'active', 'completed_victory_team_a').")
    current_round: int = Field(..., description="Current round number of the combat.")
    turn_order: List[str] = Field(default_factory=list, description="Ordered list of entity_ids indicating turn sequence.") # List of entity_ids
    current_turn_entity_id: Optional[str] = Field(None, description="Entity ID of the participant whose turn it currently is.")
    turn_log_structured: List[CombatTurnLogEntry] = Field(default_factory=list, description="Structured log of turns and actions taken.")
    combat_log_text: Optional[str] = Field(None, description="Human-readable summary log of the combat (from model's combat_log field).")

    # Overwrite participants_data for response to ensure it uses the defined schema
    participants_data: List[CombatParticipantData] = Field(..., description="Current state of participants.")


    class Config:
        orm_mode = True

# --- Combat Action Schemas ---
class CombatActionRequest(BaseModel):
    actor_entity_id: str = Field(..., description="ID of the character/NPC performing the action.")
    action_type: str = Field(..., description="Type of action (e.g., 'attack', 'ability', 'move', 'defend', 'item').")
    target_entity_id: Optional[str] = Field(None, description="ID of the primary target entity, if any.")
    ability_id: Optional[str] = Field(None, description="ID of the ability used, if action_type is 'ability'.")
    item_id: Optional[str] = Field(None, description="ID of the item used, if action_type is 'item'.")
    move_position: Optional[CombatPosition] = Field(None, description="Target position if action_type is 'move'.")
    additional_params: Optional[Dict[str, Any]] = Field(None, description="Other parameters for the action.")

class CombatActionEffect(BaseModel): # Similar to AbilityActivationEffect
    target_entity_id: Optional[str] = None
    effect_type: str # e.g., "damage", "heal", "status_applied"
    description_i18n: Dict[str, str]
    magnitude: Optional[Any] = None # e.g., amount of damage/healing, duration of status
    details: Optional[Dict[str, Any]] = None

class CombatActionResponse(BaseModel):
    success: bool
    message_i18n: Dict[str, str]
    action_log_entry: CombatTurnLogEntry # The log entry for this specific action
    effects: List[CombatActionEffect] = Field(default_factory=list)
    updated_combat_state: CombatEncounterResponse # The full combat state after the action

# --- Combat Resolution Schemas ---
class CombatResolutionRequest(BaseModel):
    outcome: Literal["victory_team_a", "victory_team_b", "draw", "gm_intervention", "aborted"] = Field(..., description="The outcome of the combat.")
    winning_team_id: Optional[str] = Field(None, description="ID of the winning team, if applicable.")
    reason_i18n: Optional[Dict[str, str]] = Field(None, description="Reason for combat resolution, especially for GM intervention or abort.")

# CombatResolutionResponse would likely be the final CombatEncounterResponse
