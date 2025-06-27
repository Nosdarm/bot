from pydantic import BaseModel, field_validator, Field
from typing import Optional, Dict, Any, List

class ResolveConflictRequest(BaseModel):
    """Request model for manually resolving a pending conflict."""
    outcome_type: str = Field(..., description="The chosen outcome type for resolving the conflict.", example="player_wins_battle")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Optional parameters specific to the chosen outcome type.", example={"loot_awarded": "gold_coins", "xp_gained": 100})

class EditNpcRequest(BaseModel):
    """Request model for editing an NPC's attribute."""
    attribute: str = Field(..., description="The attribute of the NPC to edit (e.g., 'name_i18n.en', 'stats.hp', 'location_id').", example="stats.hp")
    value: Any = Field(..., description="The new value for the attribute. Type depends on the attribute being edited.", example=150)

class EditCharacterRequest(BaseModel):
    """Request model for editing a player character's attribute."""
    attribute: str = Field(..., description="The attribute of the character to edit (e.g., 'level', 'stats.strength', 'location_id').", example="level")
    value: Any = Field(..., description="The new value for the attribute. Type depends on the attribute.", example=5)

class EditItemRequest(BaseModel):
    """Request model for editing an item instance's attribute."""
    attribute: str = Field(..., description="The attribute of the item instance to edit (e.g., 'quantity', 'state_variables.charges').", example="quantity")
    value: Any = Field(..., description="The new value for the attribute.", example=10)

class LaunchEventRequest(BaseModel):
    """Request model for manually launching a game event from a template."""
    template_id: str = Field(..., description="The ID of the event template to use.", example="event_template_001")
    location_id: Optional[str] = Field(None, description="Optional ID of the location where the event should occur.", example="location_forest_entrance")
    channel_id: Optional[str] = Field(None, description="Optional Discord channel ID to associate with the event or send notifications to.", example="123456789012345678")
    player_ids: Optional[List[str]] = Field(None, description="Optional list of player character IDs to directly involve in the event.", example=["char_player_1", "char_player_2"])

class SetRuleRequest(BaseModel):
    """Request model for setting a specific game rule value for a guild."""
    rule_key: str = Field(..., description="Dot-separated path to the rule (e.g., 'economy_rules.vendor_sell_multiplier', 'combat.max_rounds').", example="combat.max_rounds")
    value: Any = Field(..., description="The new value for the rule. Can be a string, number, boolean, list, or dict.", example=20)

class RunSimulationRequest(BaseModel):
    """Request model for running a game simulation."""
    simulation_type: str = Field(..., description="Type of simulation to run.", example="battle")
    params: Dict[str, Any] = Field(..., description="Parameters specific to the chosen simulation type.", example={"participants_setup": [], "max_rounds": 30})
    language: Optional[str] = Field(default='en', description="Language code for the formatted report output.", example="en")

    @field_validator('simulation_type')
    def simulation_type_must_be_valid(cls, value: str) -> str:
        """Validates that the simulation_type is one of the allowed values."""
        allowed_types = ["battle", "quest", "action_consequence"]
        if value not in allowed_types:
            raise ValueError(f"simulation_type must be one of {allowed_types}")
        return value

class SimulationReportResponse(BaseModel):
    """Response model for a simulation run, including formatted and raw reports."""
    report_id: str = Field(..., description="Unique ID generated for this simulation report.", example="sim_report_uuid_123")
    simulation_type: str = Field(..., description="Type of simulation that was run.", example="battle")
    formatted_report: str = Field(..., description="Human-readable formatted report of the simulation outcome.", example="**Battle Report**\nWinner: Team A...")
    raw_report: Dict[str, Any] = Field(..., description="Raw, structured data of the simulation outcome.", example={"winning_team": "Team A", "rounds": 15})

class CompareReportsRequest(BaseModel):
    """Request model for comparing two simulation reports."""
    report_id_1: str = Field(..., description="ID of the first simulation report for comparison.", example="sim_report_uuid_123")
    report_id_2: str = Field(..., description="ID of the second simulation report for comparison.", example="sim_report_uuid_456")
    language: Optional[str] = Field(default='en', description="Language code for the formatted comparison report.", example="en")

class CompareReportsResponse(BaseModel):
    """Response model for the comparison of two simulation reports."""
    report_id_1: str = Field(..., description="ID of the first report.", example="sim_report_uuid_123")
    report_id_2: str = Field(..., description="ID of the second report.", example="sim_report_uuid_456")
    simulation_type_1: Optional[str] = Field(None, description="Simulation type of the first report.", example="battle")
    simulation_type_2: Optional[str] = Field(None, description="Simulation type of the second report.", example="battle")
    comparison_details: Dict[str, Any] = Field(..., description="Structured data detailing the comparison metrics and differences.")
    formatted_comparison: str = Field(..., description="Human-readable formatted string summarizing the comparison.")
    error: Optional[str] = Field(None, description="Error message if comparison could not be performed (e.g., type mismatch, report not found).")

# Models for Monitoring and Visualization API Endpoints

class LogEntryItem(BaseModel):
    """Represents a single game log entry for monitoring."""
    timestamp: str = Field(..., description="Timestamp of the log entry in ISO format.", example="2023-10-27T10:30:00Z")
    event_type: str = Field(..., description="Type of the event logged.", example="PLAYER_MOVE")
    message: str = Field(..., description="Formatted or raw message of the log entry.", example="Player 'Hero' moved to Forest.")
    details: Optional[Dict[str, Any]] = Field(None, description="Optional structured details of the log entry.")

class EventLogResponse(BaseModel):
    """Response model for a list of game log entries."""
    logs: List[LogEntryItem] = Field(..., description="List of log entries.")
    total_logs: int = Field(..., description="Total number of logs matching the filter criteria (for pagination).", example=150)

class BasicLocationInfo(BaseModel):
    """Basic information about a game location, used in lists."""
    id: str = Field(..., description="Unique ID of the location.", example="loc_forest")
    name: str = Field(..., description="Localized name of the location.", example="Dark Forest")

class LocationNpcInfo(BaseModel):
    """Information about an NPC present in a location."""
    id: str = Field(..., description="Unique ID of the NPC.", example="npc_goblin_1")
    name: str = Field(..., description="Localized name of the NPC.", example="Grizelda the Goblin")

class LocationCharacterInfo(BaseModel):
    """Information about a player character present in a location."""
    id: str = Field(..., description="Unique ID of the character.", example="char_player_hero")
    name: str = Field(..., description="Localized name of the character.", example="HeroPlayer")
    discord_user_id: Optional[str] = Field(None, description="Discord User ID of the player controlling the character.", example="123456789098765432")

class LocationEventInfo(BaseModel):
    """Information about an active game event in a location."""
    id: str = Field(..., description="Unique ID of the active event instance.", example="event_instance_abc")
    name: Optional[str] = Field(None, description="Localized name of the event, if available.", example="Goblin Ambush")
    template_id: str = Field(..., description="ID of the event template this instance is based on.", example="event_tpl_goblin_ambush")

class LocationDetailsResponse(BaseModel):
    """Detailed information about a specific game location."""
    id: str = Field(..., description="Unique ID of the location.", example="loc_forest_clearing")
    name: str = Field(..., description="Localized name of the location.", example="Forest Clearing")
    description: str = Field(..., description="Localized description of the location.", example="A sun-dappled clearing in the woods.")
    exits: Dict[str, str] = Field(..., description="Available exits from this location, mapping direction to target location name and ID.", example={"north": "Dark Cave (`loc_cave_entrance`)", "east": "River Bend (`loc_river_bend`)"})
    npcs: List[LocationNpcInfo] = Field(default_factory=list, description="List of NPCs currently in this location.")
    characters: List[LocationCharacterInfo] = Field(default_factory=list, description="List of player characters currently in this location.")
    events: List[LocationEventInfo] = Field(default_factory=list, description="List of active game events in this location.")

class AllLocationsResponse(BaseModel):
    """Response model for a list of all game locations."""
    locations: List[BasicLocationInfo] = Field(..., description="List of basic information for all locations in the guild.")

class NpcDetails(BaseModel):
    """Detailed information about a specific NPC."""
    id: str = Field(..., description="Unique ID of the NPC.", example="npc_old_wizard")
    name: str = Field(..., description="Localized name of the NPC.", example="Elminster")
    location_id: Optional[str] = Field(None, description="ID of the NPC's current location.", example="loc_tower_top")
    location_name: Optional[str] = Field(None, description="Localized name of the NPC's current location.", example="Wizard's Tower - Top Floor")
    hp: Optional[float] = Field(None, description="Current health points of the NPC.", example=80.0)
    max_health: Optional[float] = Field(None, description="Maximum health points of the NPC.", example=100.0)

class NpcListResponse(BaseModel):
    """Response model for a list of NPCs."""
    npcs: List[NpcDetails] = Field(..., description="List of NPC details.")

class PlayerStatsResponse(BaseModel):
    """Detailed statistics and information for a player character."""
    id: str = Field(..., description="Unique ID of the character.", example="char_player_rogue")
    name: str = Field(..., description="Localized name of the character.", example="ShadowBlade")
    discord_user_id: Optional[str] = Field(None, description="Discord User ID of the player.", example="987654321012345678")
    level: int = Field(..., description="Character's current level.", example=7)
    experience: int = Field(..., description="Character's current experience points.", example=7500)
    unspent_xp: int = Field(..., description="Experience points available for spending.", example=500)
    hp: float = Field(..., description="Current health points.", example=95.0)
    max_health: float = Field(..., description="Maximum health points.", example=120.0)
    character_class: Optional[str] = Field(None, description="Localized name of the character's class.", example="Rogue")
    language: Optional[str] = Field(None, description="Selected language for the character.", example="en")
    location_id: Optional[str] = Field(None, description="ID of the character's current location.", example="loc_thieves_guild")
    location_name: Optional[str] = Field(None, description="Localized name of the character's current location.", example="Thieves' Guild - Back Alley")
    stats: Dict[str, Any] = Field(..., description="Base statistics of the character.", example={"strength": 12, "dexterity": 18, "intelligence": 14})
    effective_stats: Optional[Dict[str, Any]] = Field(None, description="Effective statistics after considering equipment, status effects, etc.", example={"strength": 14, "dexterity": 20, "attack_power": 55})
