# bot/api/schemas/rule_config_schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class RuleConfigData(BaseModel):
    """
    Defines the structure of the JSON data stored in RulesConfig.config_data.
    All fields are optional to allow for partial updates and to use defaults
    if not explicitly set.
    """
    experience_rate: Optional[float] = Field(1.0, description="Multiplier for experience points earned.")
    loot_drop_chance: Optional[float] = Field(0.5, description="Base chance for loot drops (0.0 to 1.0).")
    combat_difficulty_modifier: Optional[float] = Field(1.0, description="Modifier for combat difficulty.")

    default_language: Optional[str] = Field("en", description="Default language for the guild (e.g., 'en', 'ru').")
    command_prefixes: Optional[List[str]] = Field(default_factory=lambda: ["!"], description="Command prefixes for bot commands in the guild.")

    # Placeholder for more detailed, structured rule categories based on issue description
    # "параметры прокачки, генерации, вероятность успеха, параметры торговли и боёв"

    leveling_parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Parameters related to character leveling and progression."
    )
    generation_parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Parameters for procedural generation (e.g., maps, NPCs, quests)."
    )
    success_probabilities: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Probabilities for various actions succeeding (e.g., crafting, persuasion)."
    )
    trade_parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Parameters governing trade and economy."
    )
    combat_parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Detailed parameters for combat mechanics."
    )

    # Example of a more specific, typed sub-model if desired for better validation:
    # class CombatSpecifics(BaseModel):
    #     allow_friendly_fire: bool = False
    #     turn_time_limit_seconds: Optional[int] = None
    # combat_parameters: Optional[CombatSpecifics] = Field(default_factory=CombatSpecifics)


class RuleConfigUpdate(BaseModel):
    """
    Schema for updating RuleConfig. Allows partial updates to config_data.
    The entire config_data structure is provided, but Pydantic will only
    update fields that are explicitly passed in the request if the fields
    in RuleConfigData are Optional.
    Alternatively, for true PATCH semantics, each field of RuleConfigData
    would need to be individually optional in this update model.
    This current approach updates the whole 'config_data' blob, but
    the content of that blob can be partial if RuleConfigData fields are optional.
    A more granular update would involve a model where each key of RuleConfigData is optional.

    For simplicity, we'll expect the client to send the complete desired state of 'config_data',
    and the fields within RuleConfigData being optional will allow defaults to be used if not provided.
    If a client wants to update only one sub-field of config_data, they must fetch the current config_data,
    modify it, then send the whole updated config_data structure.
    This is effectively a PUT on the config_data field.
    """
    config_data: RuleConfigData = Field(..., description="The new configuration data for the guild.")


class RuleConfigResponse(BaseModel):
    guild_id: str = Field(..., description="The ID of the guild.")
    config_data: RuleConfigData = Field(..., description="The configuration data for the guild.")

    class Config:
        orm_mode = True
