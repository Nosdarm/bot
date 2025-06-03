from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class StatRange(BaseModel):
    min: int
    max: int

class RoleStatRules(BaseModel):
    stats: Dict[str, StatRange] = Field(default_factory=dict)

class CharacterStatRules(BaseModel):
    valid_stats: List[str] = Field(default_factory=list)
    stat_ranges_by_role: Dict[str, RoleStatRules] = Field(default_factory=dict)

class SkillRules(BaseModel):
    valid_skills: List[str] = Field(default_factory=list)
    skill_stat_map: Dict[str, str] = Field(default_factory=dict)
    skill_value_ranges: StatRange

class ItemPriceDetail(BaseModel):
    min: int
    max: int

class ItemPriceCategory(BaseModel):
    prices: Dict[str, ItemPriceDetail] = Field(default_factory=dict)

class ItemRules(BaseModel):
    price_ranges_by_type: Dict[str, ItemPriceCategory] = Field(default_factory=dict)
    valid_item_types: List[str] = Field(default_factory=list)

class FactionRules(BaseModel):
    valid_faction_ids: List[str] = Field(default_factory=list)

class QuestRewardRules(BaseModel):
    xp_reward_range: Optional[StatRange] = None
    # Could add rules for item reward counts, types, etc. later

class QuestRules(BaseModel):
    reward_rules: Optional[QuestRewardRules] = None
    # Could add rules for max prerequisites, stages, etc.

class GameRules(BaseModel):
    character_stats_rules: CharacterStatRules
    skill_rules: SkillRules
    item_rules: ItemRules
    faction_rules: Optional[FactionRules] = None
    quest_rules: Optional[QuestRules] = None
    # Other game rule categories can be added here
