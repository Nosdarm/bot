from pydantic import BaseModel, field_validator, Field
from typing import Optional, Dict, Any, List

class ResolveConflictRequest(BaseModel):
    """Request model for manually resolving a pending conflict."""
    outcome_type: str = Field(description="The chosen outcome type for resolving the conflict.")
    parameters: Optional[Dict[str, Any]] = Field(description="Optional parameters specific to the chosen outcome type.", default=None)

class EditNpcRequest(BaseModel):
    """Request model for editing an NPC's attribute."""
    attribute: str = Field(description="The attribute of the NPC to edit (e.g., 'name_i18n.en', 'stats.hp', 'location_id').")
    value: Any = Field(description="The new value for the attribute. Type depends on the attribute being edited.")

class EditCharacterRequest(BaseModel):
    """Request model for editing a player character's attribute."""
    attribute: str = Field(description="The attribute of the character to edit (e.g., 'level', 'stats.strength', 'location_id').")
    value: Any = Field(description="The new value for the attribute. Type depends on the attribute.")

class EditItemRequest(BaseModel):
    """Request model for editing an item instance's attribute."""
    attribute: str = Field(description="The attribute of the item instance to edit (e.g., 'quantity', 'state_variables.charges').")
    value: Any = Field(description="The new value for the attribute.")

class LaunchEventRequest(BaseModel):
    """Request model for manually launching a game event from a template."""
    template_id: str = Field(description="The ID of the event template to use.")
    location_id: Optional[str] = Field(description="Optional ID of the location where the event should occur.", default=None)
    channel_id: Optional[str] = Field(description="Optional Discord channel ID to associate with the event or send notifications to.", default=None)
    player_ids: Optional[List[str]] = Field(description="Optional list of player character IDs to directly involve in the event.", default=None)

class SetRuleRequest(BaseModel):
    """Request model for setting a specific game rule value for a guild."""
    rule_key: str = Field(description="Dot-separated path to the rule (e.g., 'economy_rules.multiplier', 'combat.max_rounds').")
    value: Any = Field(description="The new value for the rule. Can be a string, number, boolean, list, or dict.")

class RunSimulationRequest(BaseModel):
    """Request model for running a game simulation."""
    simulation_type: str = Field(description="Type of simulation to run.")
    params: Dict[str, Any] = Field(description="Parameters specific to the chosen simulation type.")
    language: Optional[str] = Field(description="Language code for the formatted report output.", default='en')

    @field_validator('simulation_type')
    def simulation_type_must_be_valid(cls, value: str) -> str:
        """Validates that the simulation_type is one of the allowed values."""
        allowed_types = ["battle", "quest", "action_consequence"]
        if value not in allowed_types:
            raise ValueError(f"simulation_type must be one of {allowed_types}")
        return value

class SimulationReportResponse(BaseModel):
    """Response model for a simulation run, including formatted and raw reports."""
    report_id: str = Field(description="Unique ID generated for this simulation report.")
    simulation_type: str = Field(description="Type of simulation that was run.")
    formatted_report: str = Field(description="Human-readable formatted report of the simulation outcome.")
    raw_report: Dict[str, Any] = Field(description="Raw, structured data of the simulation outcome.")

class CompareReportsRequest(BaseModel):
    """Request model for comparing two simulation reports."""
    report_id_1: str = Field(description="ID of the first simulation report for comparison.")
    report_id_2: str = Field(description="ID of the second simulation report for comparison.")
    language: Optional[str] = Field(description="Language code for the formatted comparison report.", default='en')

class CompareReportsResponse(BaseModel):
    """Response model for the comparison of two simulation reports."""
    report_id_1: str = Field(description="ID of the first report.")
    report_id_2: str = Field(description="ID of the second report.")
    simulation_type_1: Optional[str] = Field(description="Simulation type of the first report.", default=None)
    simulation_type_2: Optional[str] = Field(description="Simulation type of the second report.", default=None)
    comparison_details: Dict[str, Any] = Field(description="Structured data detailing the comparison metrics and differences.")
    formatted_comparison: str = Field(description="Human-readable formatted string summarizing the comparison.")
    error: Optional[str] = Field(description="Error message if comparison could not be performed (e.g., type mismatch, report not found).", default=None)

# Models for Monitoring and Visualization API Endpoints

class LogEntryItem(BaseModel):
    """Represents a single game log entry for monitoring."""
    timestamp: str = Field(description="Timestamp of the log entry in ISO format.")
    event_type: str = Field(description="Type of the event logged.")
    message: str = Field(description="Formatted or raw message of the log entry.")
    details: Optional[Dict[str, Any]] = Field(description="Optional structured details of the log entry.", default=None)

class EventLogResponse(BaseModel):
    """Response model for a list of game log entries."""
    logs: List[LogEntryItem] = Field(description="List of log entries.")
    total_logs: int = Field(description="Total number of logs matching the filter criteria (for pagination).")

class BasicLocationInfo(BaseModel):
    """Basic information about a game location, used in lists."""
    id: str = Field(description="Unique ID of the location.")
    name: str = Field(description="Localized name of the location.")

class LocationNpcInfo(BaseModel):
    """Information about an NPC present in a location."""
    id: str = Field(description="Unique ID of the NPC.")
    name: str = Field(description="Localized name of the NPC.")

class LocationCharacterInfo(BaseModel):
    """Information about a player character present in a location."""
    id: str = Field(description="Unique ID of the character.")
    name: str = Field(description="Localized name of the character.")
    discord_user_id: Optional[str] = Field(description="Discord User ID of the player controlling the character.", default=None)

class LocationEventInfo(BaseModel):
    """Information about an active game event in a location."""
    id: str = Field(description="Unique ID of the active event instance.")
    name: Optional[str] = Field(description="Localized name of the event, if available.", default=None)
    template_id: str = Field(description="ID of the event template this instance is based on.")

class LocationDetailsResponse(BaseModel):
    """Detailed information about a specific game location."""
    id: str = Field(description="Unique ID of the location.")
    name: str = Field(description="Localized name of the location.")
    description: str = Field(description="A sun-dappled clearing in the woods.")
    exits: Dict[str, str] = Field(description="Available exits from this location, mapping direction to target location name and ID.")
    npcs: List[LocationNpcInfo] = Field(description="List of NPCs currently in this location.", default_factory=list)
    characters: List[LocationCharacterInfo] = Field(description="List of player characters currently in this location.", default_factory=list)
    events: List[LocationEventInfo] = Field(description="List of active game events in this location.", default_factory=list)

class AllLocationsResponse(BaseModel):
    """Response model for a list of all game locations."""
    locations: List[BasicLocationInfo] = Field(description="List of basic information for all locations in the guild.")

class NpcDetails(BaseModel):
    """Detailed information about a specific NPC."""
    id: str = Field(description="Unique ID of the NPC.")
    name: str = Field(description="Localized name of the NPC.")
    location_id: Optional[str] = Field(description="ID of the NPC's current location.", default=None)
    location_name: Optional[str] = Field(description="Localized name of the NPC's current location.", default=None)
    hp: Optional[float] = Field(description="Current health points of the NPC.", default=None)
    max_health: Optional[float] = Field(description="Maximum health points of the NPC.", default=None)

class NpcListResponse(BaseModel):
    """Response model for a list of NPCs."""
    npcs: List[NpcDetails] = Field(description="List of NPC details.")

class PlayerStatsResponse(BaseModel):
    """Detailed statistics and information for a player character."""
    id: str = Field(description="Unique ID of the character.")
    name: str = Field(description="Localized name of the character.")
    discord_user_id: Optional[str] = Field(description="Discord User ID of the player.", default=None)
    level: int = Field(description="Character's current level.")
    experience: int = Field(description="Character's current experience points.")
    unspent_xp: int = Field(description="Experience points available for spending.")
    hp: float = Field(description="Current health points.")
    max_health: float = Field(description="Maximum health points.")
    character_class: Optional[str] = Field(description="Localized name of the character's class.", default=None)
    language: Optional[str] = Field(description="Selected language for the character.", default=None)
    location_id: Optional[str] = Field(description="ID of the character's current location.", default=None)
    location_name: Optional[str] = Field(description="Localized name of the character's current location.", default=None)
    stats: Dict[str, Any] = Field(description="Base statistics of the character.")
    effective_stats: Optional[Dict[str, Any]] = Field(description="Effective statistics after considering equipment, status effects, etc.", default=None)



