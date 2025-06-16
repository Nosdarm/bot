"""
Defines Pydantic models for game rule structures.

These models are used by the AIResponseValidator to check if AI-generated game content
(like NPCs, quests, items) conforms to predefined game balance rules, valid types,
value ranges, etc. They are typically loaded from a configuration source (e.g., JSON file)
and passed to the validator during its initialization.
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

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

# --- New Schemas for Core Game Mechanics Rules (RulesConfig DB Model) ---

class CheckDefinition(BaseModel):
    dice_formula: str = Field(..., description="Dice formula, e.g., '1d20', '2d6+STR'. Modifiers from stats here are usually conceptual; actual stat modifiers are added by CheckResolver.")
    base_dc: Optional[int] = Field(None, description="Base difficulty class for the check, if not contested or otherwise specified.")
    affected_by_stats: List[str] = Field(default_factory=list, description="List of stat/skill keys that modify this check, e.g., ['dexterity', 'perception_skill'].")
    crit_success_threshold: Optional[int] = Field(None, description="Roll value on the primary die (e.g., d20) at or above which is a critical success.")
    crit_fail_threshold: Optional[int] = Field(None, description="Roll value on the primary die at or below which is a critical fumble.")
    success_on_beat_dc: bool = Field(True, description="If True, result must be > DC. If False, result >= DC is success.")
    opposed_check_type: Optional[str] = Field(None, description="If this is a contested check, specifies the 'check_type' the target uses to oppose.")

class DamageTypeDefinition(BaseModel):
    # Example: resistances, vulnerabilities, special effects might be defined here later
    description: str = Field(..., description="Description of the damage type.")

class XPRule(BaseModel):
    # Example structure, can be expanded
    level_difference_modifier: Dict[str, float] = Field(default_factory=dict, description="Modifier for XP based on level difference, e.g., {'-5': 0.5, '0': 1.0, '+5': 1.5}")
    base_xp_per_challenge: Dict[str, int] = Field(default_factory=dict, description="Base XP for challenge ratings, e.g., {'easy': 50, 'medium': 100}")

class LootTableEntry(BaseModel):
    item_template_id: str
    quantity_dice: str = Field(default="1", description="Dice formula for quantity, e.g., '1', '1d4'.")
    weight: int = Field(default=1, description="Weight for weighted random selection.")
    # condition: Optional[str] # E.g. "player_level_gt_5" - for future expansion

class LootTableDefinition(BaseModel):
    id: str = Field(..., description="Unique ID for this loot table.")
    entries: List[LootTableEntry] = Field(default_factory=list)

class ActionConflictDefinition(BaseModel):
    type: str = Field(..., description="Unique type identifier for this conflict, e.g., 'simultaneous_move_to_limited_slot'.")
    description: str = Field(..., description="Explanation of the conflict.")
    involved_intent_pattern: List[str] = Field(..., description="List of intents that can trigger this conflict, e.g., ['move', 'pickup'].")
    resolution_type: str = Field(..., description="How to resolve: 'auto' (via a check) or 'manual' (GM/player choice).")
    auto_resolution_check_type: Optional[str] = Field(None, description="If resolution_type is 'auto', the check_type from 'checks' to use for resolution.")
    manual_resolution_options: Optional[List[str]] = Field(None, description="If resolution_type is 'manual', descriptive options for choice.")

class LocationInteractionOutcome(BaseModel):
    type: str = Field(..., description="Type of outcome, e.g., 'reveal_exit', 'grant_item', 'trigger_trap', 'update_state_var', 'display_message'.")
    # Specific fields for each type, e.g.:
    exit_id: Optional[str] = None
    item_template_id: Optional[str] = None
    quantity: Optional[int] = 1 # For grant_item
    trap_id: Optional[str] = None # References a trap definition (not yet in this schema)
    state_var_name: Optional[str] = None
    state_var_new_value: Optional[Any] = None
    message_i18n: Optional[Dict[str, str]] = None

class LocationInteractionDefinition(BaseModel):
    id: str = Field(..., description="Unique ID for this interaction point, e.g., 'lever_main_hall_west_wall'.")
    description_i18n: Dict[str, str] = Field(..., description="I18n description of the interactable object/point.")
    check_type: Optional[str] = Field(None, description="Optional check_type from 'checks' required to interact or succeed.")
    success_outcome: LocationInteractionOutcome
    failure_outcome: Optional[LocationInteractionOutcome] = None
    required_items: Optional[List[str]] = Field(None, description="List of item template IDs needed to attempt the interaction.")
    # cooldown_seconds: Optional[int] = None # For repeatable interactions
    # one_time_only: bool = True

class StatModifierRule(BaseModel):
    stat_name: str = Field(..., description="The name of the stat to be modified (e.g., 'strength', 'max_hp', 'attack_bonus', 'fire_resistance').")
    bonus_type: str = Field(..., description="Type of bonus, e.g., 'flat', 'multiplier', 'percentage_increase'.") # 'flat', 'multiplier', 'override'
    value: float = Field(..., description="Value of the modification.")
    duration_turns: Optional[int] = Field(None, description="For temporary effects, duration in game turns. None for permanent/until removed.")
    # conditions: Optional[List[str]] # E.g. "while_hp_above_50_percent" - for future expansion

class GrantedAbilityOrSkill(BaseModel):
    id: str = Field(..., description="ID of the ability or skill being granted (references Ability/Skill definitions).")
    type: str = Field(..., description="'ability' or 'skill'.")
    # level: Optional[int] = None # If skills/abilities have levels

class ItemEffectDefinition(BaseModel):
    description_i18n: Optional[Dict[str, str]] = Field(None, description="Optional i18n description of the combined effects.")
    stat_modifiers: List[StatModifierRule] = Field(default_factory=list)
    grants_abilities_or_skills: List[GrantedAbilityOrSkill] = Field(default_factory=list)
    # on_equip: Optional[List[Dict]] # For equipment specific triggers
    # on_use: Optional[List[Dict]] # For consumable specific triggers (e.g. healing amount)
    # visual_effect_id: Optional[str] # E.g. "glowing_aura"
    slot: Optional[str] = Field(None, description="If this effect is tied to an equippable item, specifies the slot ID it occupies, e.g., 'main_hand'.")
    # required_stats_to_equip: Optional[List[Dict[str, Any]]] # e.g. [{'stat_name': 'strength', 'min_value': 12}]

    # New fields for specific common item actions
    direct_health_effects: Optional[List['DirectHealthEffect']] = Field(None, description="Direct healing or damage effects.")
    apply_status_effects: Optional[List['ApplyStatusEffectRule']] = Field(None, description="Status effects to apply on use or equip.")
    learn_spells: Optional[List['LearnSpellRule']] = Field(None, description="Spells learned permanently by the user.")
    grant_resources: Optional[List['GrantResourceRule']] = Field(None, description="Resources granted to the user (e.g., mana, gold).")

    consumable: bool = Field(False, description="If true, the item is consumed after a single use.")
    target_policy: str = Field(default="self", description="Defines targeting rules: 'self', 'requires_target', 'no_target'.") # 'area_around_self', 'area_at_target'

class EffectProperty(BaseModel):
    effect_id: str = Field(..., description="The ID of the effect to apply, typically a key from CoreGameRulesConfig.item_effects.")
    # Add other potential fields if context suggests, e.g.:
    potency_modifier: float = Field(default=1.0, description="Modifier for the strength of this effect instance.")
    duration_modifier: float = Field(default=1.0, description="Modifier for the duration of this effect instance.")
    target_override: Optional[str] = Field(default=None, description="Override targeting policy for this specific effect instance.")

class DirectHealthEffect(BaseModel):
    amount: int = Field(..., description="Amount of health to change (positive for heal, negative for damage).")
    effect_type: str = Field(..., description="Type of health effect, e.g., 'heal', 'damage'.") # Could also be 'temp_hp'
    # damage_type: Optional[str] = None # If effect_type is 'damage', specify damage type from DamageTypeDefinition keys

class ApplyStatusEffectRule(BaseModel):
    status_effect_id: str = Field(..., description="ID of the status effect to apply (references a key in CoreGameRulesConfig.status_effects).")
    duration_turns: Optional[int] = Field(None, description="Overrides default duration if specified. Use 0 for instant, None for default/permanent as per status def.")
    target: str = Field(default="self", description="Target of the status effect: 'self' or 'target_entity'.") # Could expand to 'all_allies', 'all_enemies'

class LearnSpellRule(BaseModel):
    spell_id: str = Field(..., description="ID of the spell to be learned by the character.")

class GrantResourceRule(BaseModel):
    resource_name: str = Field(..., description="Name of the resource to grant, e.g., 'mana', 'gold', 'action_points'.")
    amount: int = Field(..., description="Amount of the resource to grant.")


class StatusEffectDefinition(BaseModel):
    id: str = Field(..., description="Unique ID for this status effect type (e.g., 'poisoned', 'blessed', 'strengthened').")
    name_i18n: Dict[str, str] = Field(..., description="Display name for the status effect.")
    description_i18n: Dict[str, str] = Field(..., description="Description of what the status effect does.")
    stat_modifiers: List[StatModifierRule] = Field(default_factory=list)
    grants_abilities_or_skills: List[GrantedAbilityOrSkill] = Field(default_factory=list)
    duration_type: str = Field(default="turns", description="'turns', 'permanent', 'until_condition_met'.") # e.g. 'turns', 'encounter', 'permanent_until_dispelled'
    default_duration_turns: Optional[int] = Field(None, description="Default duration in turns if applicable.")
    # tick_effect: Optional[Dict] # E.g. damage over time: {'type': 'damage', 'damage_type': 'poison', 'amount_dice': '1d4'}
    # on_apply_message_i18n: Optional[Dict[str, str]]
    # on_remove_message_i18n: Optional[Dict[str, str]]
    # is_positive_effect: bool = True

class EquipmentSlotDefinition(BaseModel):
    slot_id: str = Field(..., description="Unique identifier for the equipment slot, e.g., 'main_hand', 'armor_body'.")
    name_i18n: Dict[str, str] = Field(..., description="Display name for the slot.")
    compatible_item_types: List[str] = Field(default_factory=list, description="List of item types (e.g., 'weapon_sword', 'armor_heavy') compatible with this slot.")
    # max_items: int = Field(default=1, description="Max number of items this slot can hold (e.g., 2 for rings).")


class BaseStatDefinition(BaseModel):
    name_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    default_value: int = Field(default=10)
    min_value: int = Field(default=1)
    max_value: int = Field(default=20) # Max for typical player stats, can be higher for monsters

# --- Relationship Rules ---

class RelationChangeInstruction(BaseModel):
    entity1_ref: str = Field(..., description="Reference to the first entity involved in the relationship change (e.g., 'player_id', 'npc_id', 'faction_id_A').")
    entity1_type_ref: str = Field(..., description="Type of the first entity (e.g., 'player_type', 'npc_type', 'faction_type_A').")
    entity2_ref: str = Field(..., description="Reference to the second entity.")
    entity2_type_ref: str = Field(..., description="Type of the second entity.")
    relation_type: str = Field(..., description="Type of relationship (e.g., 'friendly', 'hostile', 'professional_respect').")
    update_type: str = Field(..., description="How the relationship strength is updated. Enum: 'add', 'subtract', 'set', 'multiply'.")
    magnitude_formula: str = Field(..., description="Formula to calculate the change magnitude (e.g., '10', 'event_data.get(\\'action_value\\', 0) * 0.5', 'current_strength * 0.1').")
    description: Optional[str] = Field(None, description="Optional description of this specific instruction.")
    name: Optional[str] = Field(None, description="Optional name for this instruction.")

class RelationChangeRule(BaseModel):
    name: str = Field(..., description="Unique name for the rule.")
    event_type: str = Field(..., description="The event that triggers this rule (e.g., 'quest_completed').")
    condition: Optional[str] = Field(None, description="A Python expression string to be evaluated against event_data (e.g., \"event_data.get('faction_id') == 'guild_of_mages'\").")
    changes: List[RelationChangeInstruction] = Field(..., description="A list of relationship changes to apply if the rule is triggered.")
    description: Optional[str] = Field(None, description="Optional description of the rule's purpose.")

class RelationshipInfluenceRule(BaseModel):
    name: str = Field(..., description="Unique name for this influence rule.")
    influence_type: str = Field(..., description="Type of game mechanic this rule influences (e.g., 'dialogue_skill_check', 'npc_targeting', 'dialogue_option_availability', 'price_adjustment').")
    condition: Optional[str] = Field(None, description="Optional condition for this rule to apply (e.g., \"target_entity_type == 'NPC'\"). Evaluated in context of the interaction.")
    threshold_type: Optional[str] = Field(None, description="Type of relationship strength threshold (e.g., 'min_strength', 'max_strength').")
    threshold_value: Optional[float] = Field(None, description="The value for the threshold_type.")
    bonus_malus_formula: Optional[str] = Field(None, description="Formula for calculating bonus or malus (e.g., '5', '-2', '0.1 * current_strength').")
    effect_description_i18n_key: Optional[str] = Field(None, description="I18n key for describing the effect to the player (e.g., 'feedback.relationship.dialogue_check_bonus').")
    effect_params_mapping: Optional[Dict[str, str]] = Field(None, description="Maps rule context variables to i18n parameter names (e.g., {\"npc_name\": \"npc.name\", \"bonus_amount_str\": \"calculated_bonus\"}).")
    availability_flag: Optional[bool] = Field(None, description="For dialogue options or similar features: True if this rule makes it available, False if it makes it unavailable.")
    failure_feedback_key: Optional[str] = Field(None, description="For dialogue options if unavailable due to this rule, an i18n key for feedback.")
    failure_feedback_params_mapping: Optional[Dict[str, str]] = Field(None, description="Parameters for the failure_feedback_key.")


# --- Economic Parameters Schemas ---

class ItemRarityDefinition(BaseModel):
    id: str
    name_i18n: Dict[str, str]
    color_code: Optional[str] = None
    price_modifier: float = Field(default=1.0, description="Multiplier for base item value based on this rarity.")
    drop_chance_modifier: Optional[float] = Field(default=None, description="Modifier for drop chances, if applicable.")

class ItemTypeDefinition(BaseModel):
    id: str
    name_i18n: Dict[str, str]
    base_value: Optional[int] = Field(default=None, description="Default base value for items of this type, before rarity or other modifiers.")
    compatible_slots: Optional[List[str]] = Field(default_factory=list, description="List of equipment slot IDs if items of this type are equippable.")
    properties_on_create: Optional[List[str]] = Field(default_factory=list, description="List of ItemProperty IDs to typically associate with new items of this type.")

class ShopInventoryItemRule(BaseModel):
    item_template_id: Optional[str] = None
    item_type_id: Optional[str] = None # Link to ItemTypeDefinition.id
    item_rarity_id_max: Optional[str] = None # Max rarity to stock for this type
    quantity_dice: str = Field(default="1") # e.g., "1", "1d4", "2d6"
    chance_to_stock: float = Field(default=1.0, ge=0, le=1.0)

class ShopRestockRule(BaseModel):
    restock_interval_hours: Optional[int] = Field(default=24)
    reset_inventory_to_defaults: bool = Field(default=False, description="If true, completely resets inventory based on rules. If false, only adds missing items.")
    individual_item_restock_chance: float = Field(default=0.75, ge=0, le=1.0, description="Chance for each defined item slot to restock if not resetting all.")

class ShopTypeDefaultSettings(BaseModel):
    shop_type_id: str # e.g., "general_store", "blacksmith", "alchemist"
    name_i18n: Dict[str, str]
    inventory_rules: List[ShopInventoryItemRule] = Field(default_factory=list)
    buy_markup: float = Field(default=1.2, description="Default markup when shop sells to player (e.g., 1.2 means 20% markup from item's calculated value).")
    sell_markdown: float = Field(default=0.8, description="Default markdown when shop buys from player (e.g., player gets 80% of item's calculated value).")
    restock_rules: Optional[ShopRestockRule] = None

# --- End Economic Parameters Schemas ---

class CoreGameRulesConfig(BaseModel):
    """
    Defines the structure for core game mechanics rules, stored in the RulesConfig DB model.
    This is distinct from GameRules which is for AI validation.
    """
    checks: Dict[str, CheckDefinition] = Field(default_factory=dict)
    damage_types: Dict[str, DamageTypeDefinition] = Field(default_factory=dict)
    xp_rules: Optional[XPRule] = None
    loot_tables: Dict[str, LootTableDefinition] = Field(default_factory=dict)
    action_conflicts: List[ActionConflictDefinition] = Field(default_factory=list)
    location_interactions: Dict[str, LocationInteractionDefinition] = Field(default_factory=dict)

    # New sections for effects and base stats
    base_stats: Dict[str, BaseStatDefinition] = Field(default_factory=dict, description="Definitions for base character stats like STR, DEX etc.")
    equipment_slots: Dict[str, EquipmentSlotDefinition] = Field(default_factory=dict, description="Defines available equipment slots on a character.")
    item_effects: Dict[str, ItemEffectDefinition] = Field(default_factory=dict, description="Reusable item effects, keyed by an effect ID or item template ID.")
    status_effects: Dict[str, StatusEffectDefinition] = Field(default_factory=dict, description="Definitions for status effects, keyed by status ID.")
    relation_rules: List[RelationChangeRule] = Field(default_factory=list, description="Rules defining how relationships change based on game events.")
    relationship_influence_rules: List[RelationshipInfluenceRule] = Field(default_factory=list, description="Rules defining how relationship strengths influence game mechanics.")


# --- Economic Parameters Schemas ---

class ItemRarityDefinition(BaseModel):
    id: str
    name_i18n: Dict[str, str]
    color_code: Optional[str] = None
    price_modifier: float = Field(default=1.0, description="Multiplier for base item value based on this rarity.")
    drop_chance_modifier: Optional[float] = Field(default=None, description="Modifier for drop chances, if applicable.")

class ItemTypeDefinition(BaseModel):
    id: str
    name_i18n: Dict[str, str]
    base_value: Optional[int] = Field(default=None, description="Default base value for items of this type, before rarity or other modifiers.")
    compatible_slots: Optional[List[str]] = Field(default_factory=list, description="List of equipment slot IDs if items of this type are equippable.")
    properties_on_create: Optional[List[str]] = Field(default_factory=list, description="List of ItemProperty IDs to typically associate with new items of this type.")

class ShopInventoryItemRule(BaseModel):
    item_template_id: Optional[str] = None
    item_type_id: Optional[str] = None # Link to ItemTypeDefinition.id
    item_rarity_id_max: Optional[str] = None # Max rarity to stock for this type
    quantity_dice: str = Field(default="1") # e.g., "1", "1d4", "2d6"
    chance_to_stock: float = Field(default=1.0, ge=0, le=1.0)

class ShopRestockRule(BaseModel):
    restock_interval_hours: Optional[int] = Field(default=24)
    reset_inventory_to_defaults: bool = Field(default=False, description="If true, completely resets inventory based on rules. If false, only adds missing items.")
    individual_item_restock_chance: float = Field(default=0.75, ge=0, le=1.0, description="Chance for each defined item slot to restock if not resetting all.")

class ShopTypeDefaultSettings(BaseModel):
    shop_type_id: str # e.g., "general_store", "blacksmith", "alchemist"
    name_i18n: Dict[str, str]
    inventory_rules: List[ShopInventoryItemRule] = Field(default_factory=list)
    buy_markup: float = Field(default=1.2, description="Default markup when shop sells to player (e.g., 1.2 means 20% markup from item's calculated value).")
    sell_markdown: float = Field(default=0.8, description="Default markdown when shop buys from player (e.g., player gets 80% of item's calculated value).")
    restock_rules: Optional[ShopRestockRule] = None

# --- End Economic Parameters Schemas ---

class CoreGameRulesConfig(BaseModel):
    """
    Defines the structure for core game mechanics rules, stored in the RulesConfig DB model.
    This is distinct from GameRules which is for AI validation.
    """
    checks: Dict[str, CheckDefinition] = Field(default_factory=dict)
    damage_types: Dict[str, DamageTypeDefinition] = Field(default_factory=dict)
    xp_rules: Optional[XPRule] = None
    loot_tables: Dict[str, LootTableDefinition] = Field(default_factory=dict)
    action_conflicts: List[ActionConflictDefinition] = Field(default_factory=list)
    location_interactions: Dict[str, LocationInteractionDefinition] = Field(default_factory=dict)

    # New sections for effects and base stats
    base_stats: Dict[str, BaseStatDefinition] = Field(default_factory=dict, description="Definitions for base character stats like STR, DEX etc.")
    equipment_slots: Dict[str, EquipmentSlotDefinition] = Field(default_factory=dict, description="Defines available equipment slots on a character.")
    item_effects: Dict[str, ItemEffectDefinition] = Field(default_factory=dict, description="Reusable item effects, keyed by an effect ID or item template ID.")
    status_effects: Dict[str, StatusEffectDefinition] = Field(default_factory=dict, description="Definitions for status effects, keyed by status ID.")
    relation_rules: List[RelationChangeRule] = Field(default_factory=list, description="Rules defining how relationships change based on game events.")
    relationship_influence_rules: List[RelationshipInfluenceRule] = Field(default_factory=list, description="Rules defining how relationship strengths influence game mechanics.")

    # Economic Parameters
    item_rarities: Dict[str, 'ItemRarityDefinition'] = Field(default_factory=dict, description="Definitions for item rarities.")
    item_types: Dict[str, 'ItemTypeDefinition'] = Field(default_factory=dict, description="Definitions for base item types.")
    shop_type_defaults: Dict[str, 'ShopTypeDefaultSettings'] = Field(default_factory=dict, description="Default settings for different types of shops.")
