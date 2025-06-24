from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List

@dataclass
class Ability:
    id: str
    name_i18n: Dict[str, str] # e.g., {"en": "Name", "ru": "Имя"}
    description_i18n: Dict[str, str] # e.g., {"en": "Description", "ru": "Описание"}
    type: str  # e.g., "passive_stat_modifier", "passive_conditional_trigger", "activated_combat", "activated_utility", "innate_racial"
    static_id: Optional[str] = None # Static identifier, e.g. "fireball_spell", unique per guild in DB
    
    activation_type: Optional[str] = None # If type is "activated_*", e.g., "action", "bonus_action", "reaction", "free"
    resource_cost: Dict[str, Any] = field(default_factory=dict) # e.g., {"stamina": 10, "action_points": 1} or {"uses_per_day": 3}
    cooldown: Optional[float] = None # In seconds or game turns
    range: Optional[str] = None # String (e.g. "self", "touch", "10m") or int for activated abilities
    target_type: Optional[str] = None # e.g., "single_enemy", "single_ally", "self", "area_of_effect" for activated abilities
    
    effects: List[Dict[str, Any]] = field(default_factory=list)
    # Examples:
    # Passives: [{"type": "modify_stat", "stat": "max_health", "modifier_type": "percentage_base", "amount": 0.10}]
    # Activated: [{"type": "deal_weapon_damage_modifier", "multiplier": 1.5}, {"type": "apply_status_effect", "status_effect_id": "stunned"}]
    
    requirements: Dict[str, Any] = field(default_factory=dict) # e.g., {"min_strength": 13, "level": 5, "required_skill": "two_handed"}
    acquisition_methods: List[str] = field(default_factory=list) # Documentation: e.g., "racial", "class_feature_lvl_2"
    icon: Optional[str] = None # Emoji or path to an icon image
    sfx_on_activation: Optional[str] = None # Sound effect key for using an activated ability
    sfx_on_trigger: Optional[str] = None # Sound effect key for a passive ability triggering

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Ability":
        """Creates an Ability instance from a dictionary."""
        # Basic validation for required fields
        if not all(k in data for k in ["id", "type"]) or (("name" not in data or "description" not in data) and ("name_i18n" not in data or "description_i18n" not in data)):
            raise ValueError("Missing required fields in ability data. Need 'id', 'type', and either ('name', 'description') or ('name_i18n', 'description_i18n').")

        data_copy = data.copy()

        # Handle backward compatibility for name and description
        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {"en": data_copy.pop("name")}
        elif "name" in data_copy and "name_i18n" in data_copy: # if both exist, prefer _i18n
            data_copy.pop("name")

        if "description" in data_copy and "description_i18n" not in data_copy:
            data_copy["description_i18n"] = {"en": data_copy.pop("description")}
        elif "description" in data_copy and "description_i18n" in data_copy: # if both exist, prefer _i18n
            data_copy.pop("description")
            
        # Ensure correct types for fields that might be missing or have defaults
        data_copy['resource_cost'] = data.get('resource_cost', {})
        data_copy['effects'] = data.get('effects', [])
        data_copy['requirements'] = data.get('requirements', {})
        data_copy['acquisition_methods'] = data.get('acquisition_methods', [])
        data_copy['static_id'] = data.get('static_id') # Added for static_id
        
        # Optional fields default to None if not present, which dataclass handles.
        # No specific handling needed for Optional[str], Optional[float] unless type conversion is required.

        return cls(**data_copy)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the Ability instance to a dictionary for serialization."""
        # Using dataclasses.asdict would be simpler if no custom logic needed.
        # For now, manual conversion for clarity and future custom needs.
        return {
            "id": self.id,
            "static_id": self.static_id,
            "name_i18n": self.name_i18n,
            "description_i18n": self.description_i18n,
            "type": self.type,
            "activation_type": self.activation_type,
            "resource_cost": self.resource_cost,
            "cooldown": self.cooldown,
            "range": self.range,
            "target_type": self.target_type,
            "effects": self.effects,
            "requirements": self.requirements,
            "acquisition_methods": self.acquisition_methods,
            "icon": self.icon,
            "sfx_on_activation": self.sfx_on_activation,
            "sfx_on_trigger": self.sfx_on_trigger,
        }

if __name__ == "__main__":
    # Example Usage
    example_passive_ability_data = {
        "id": "passive_toughness_1",
        "name_i18n": {"en": "Toughness I", "ru": "Стойкость I"},
        "description_i18n": {"en": "Increases maximum health by 10.", "ru": "Увеличивает максимальное здоровье на 10."},
        "type": "passive_stat_modifier",
        "effects": [
            { "type": "modify_stat", "stat": "max_health", "modifier_type": "flat", "amount": 10 }
        ],
        "requirements": { "level": 1 },
        "icon": "❤️"
    }

    example_activated_ability_data = {
        "id": "power_attack_martial",
        "name_i18n": {"en": "Power Attack", "ru": "Мощная Атака"},
        "description_i18n": {"en": "Make a melee attack with increased force.", "ru": "Совершите рукопашную атаку с увеличенной силой."},
        "type": "activated_combat",
        "activation_type": "action",
        "resource_cost": { "stamina": 15 },
        "effects": [
            { "type": "modify_outgoing_damage", "damage_multiplier": 1.5, "accuracy_penalty": -5 }
        ],
        "requirements": { "min_strength": 13 },
        "icon": "⚔️",
        "sfx_on_activation": "sfx_power_attack_swing"
    }

    ability1 = Ability.from_dict(example_passive_ability_data)
    ability2 = Ability.from_dict(example_activated_ability_data)

    print(f"Created ability: {ability1.name_i18n['en']} (Type: {ability1.type})")
    print(f"Effects: {ability1.effects}")
    print(ability1.to_dict())

    print(f"\nCreated ability: {ability2.name_i18n['en']} (Type: {ability2.type})")
    print(f"Resource Cost: {ability2.resource_cost}, Effects: {ability2.effects}")
    print(ability2.to_dict())

    # Example for an innate ability using old format for backward compatibility
    example_innate_ability_data_old_format = {
        "id": "racial_elf_darkvision",
        "name": "Darkvision (Elf)", # Old format
        "description": "Can see in dim light as if it were bright light, and in darkness as if it were dim light.", # Old format
        "type": "innate_racial",
        "effects": [ { "type": "grant_flag", "flag": "darkvision" } ],
        "acquisition_methods": ["racial_elf"]
    }
    ability3 = Ability.from_dict(example_innate_ability_data_old_format)
    print(f"\nCreated ability (from old format): {ability3.name_i18n['en']} (Type: {ability3.type})")
    assert ability3.name_i18n == {"en": "Darkvision (Elf)"}
    assert ability3.description_i18n == {"en": "Can see in dim light as if it were bright light, and in darkness as if it were dim light."}
    print(f"Acquisition: {ability3.acquisition_methods}, Effects: {ability3.effects}")

    # Test missing optional fields & new i18n fields
    example_minimal_ability_i18n = {
        "id": "minimal_passive_i18n",
        "name_i18n": {"en": "Minimal Passive", "ru": "Минимальный Пассивный"},
        "description_i18n": {"en": "A very basic passive.", "ru": "Очень простой пассивный."},
        "type": "passive_generic"
        # All optional fields are missing
    }
    ability4 = Ability.from_dict(example_minimal_ability_i18n)
    print(f"\nCreated minimal ability: {ability4.name_i18n['en']}")
    print(f"Cooldown: {ability4.cooldown}, Resource Cost: {ability4.resource_cost}, Effects: {ability4.effects}")
    assert ability4.cooldown is None
    assert ability4.resource_cost == {}
    assert ability4.effects == []
    assert ability4.requirements == {}
    assert ability4.acquisition_methods == []
    print("Minimal ability test passed.")
