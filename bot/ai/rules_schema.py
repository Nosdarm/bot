"""
Defines Pydantic models for game rule structures.

These models are used by the AIResponseValidator to check if AI-generated game content
(like NPCs, quests, items) conforms to predefined game balance rules, valid types,
value ranges, etc. They are typically loaded from a configuration source (e.g., JSON file)
and passed to the validator during its initialization.
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class StatRange(BaseModel):
    """
    Represents a min-max range for a numerical statistic or value.
    """
    min: int
    max: int

class RoleStatRules(BaseModel):
    """
    Defines specific stat ranges for a particular character role.
    The keys of the 'stats' dictionary are stat names (e.g., "strength").
    """
    stats: Dict[str, StatRange] = Field(default_factory=dict, description="Maps stat names to their allowed StatRange.")

class CharacterStatRules(BaseModel):
    """
    Container for all rules related to character statistics.
    """
    valid_stats: List[str] = Field(default_factory=list, description="A list of all permissible stat names in the game.")
    stat_ranges_by_role: Dict[str, RoleStatRules] = Field(default_factory=dict, description="Maps role names (e.g., 'warrior') to their specific RoleStatRules.")

class SkillRules(BaseModel):
    """
    Container for all rules related to character skills.
    """
    valid_skills: List[str] = Field(default_factory=list, description="A list of all permissible skill names.")
    skill_stat_map: Dict[str, str] = Field(default_factory=dict, description="Maps skill names to the primary character stat they are associated with (e.g., 'combat' -> 'strength').")
    skill_value_ranges: StatRange # General min-max range applicable to all skill values.

class ItemPriceDetail(BaseModel):
    """
    Represents a min-max price range for an item, typically based on rarity or sub-type.
    """
    min: int
    max: int

class ItemPriceCategory(BaseModel):
    """
    Defines price details for different categories of items, usually by rarity.
    Example: {"common": ItemPriceDetail(min=5, max=50), "rare": ItemPriceDetail(min=51, max=200)}
    """
    prices: Dict[str, ItemPriceDetail] = Field(default_factory=dict, description="Maps rarity strings (e.g., 'common', 'rare') or sub-types to their ItemPriceDetail.")

class ItemRules(BaseModel):
    """
    Container for all rules related to items.
    """
    price_ranges_by_type: Dict[str, ItemPriceCategory] = Field(default_factory=dict, description="Maps item types (e.g., 'weapon', 'potion') to their ItemPriceCategory, which then defines prices by rarity/sub-type.")
    valid_item_types: List[str] = Field(default_factory=list, description="A list of all permissible item type names.")
    # Future: Could add valid_properties_by_type: Dict[str, List[str]] here

class FactionRules(BaseModel):
    """
    Container for rules related to factions.
    """
    valid_faction_ids: List[str] = Field(default_factory=list, description="A list of all valid faction identifiers.")

class QuestRewardRules(BaseModel):
    """
    Defines rules for quest rewards.
    """
    xp_reward_range: Optional[StatRange] = Field(default=None, description="Optional min-max range for experience point (XP) rewards for quests.")
    # Future: Could add rules for item reward counts, types, etc.

class QuestRules(BaseModel):
    """
    Container for rules related to quests.
    """
    reward_rules: Optional[QuestRewardRules] = Field(default=None, description="Specific rules governing quest rewards.")
    # Future: Could add rules for max prerequisites, number of stages, objective complexity etc.

class GameRules(BaseModel):
    """
    The top-level Pydantic model that aggregates all specific game rule categories.
    This model is loaded by the AIResponseValidator to guide its validation processes.
    """
    character_stats_rules: CharacterStatRules
    skill_rules: SkillRules
    item_rules: ItemRules
    faction_rules: Optional[FactionRules] = Field(default=None, description="Rules related to game factions.")
    quest_rules: Optional[QuestRules] = Field(default=None, description="Rules related to quests.")
    # Other game rule categories can be added here as new fields.
    # Example: class MagicSystemRules(BaseModel): ...
    # magic_system_rules: Optional[MagicSystemRules] = None
