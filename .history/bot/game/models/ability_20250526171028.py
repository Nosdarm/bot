from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List

@dataclass
class Ability:
    id: str
    name: str
    description: str
    type: str  # e.g., "passive_stat_modifier", "passive_conditional_trigger", "activated_combat", "activated_utility", "innate_racial"
    
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
        if not all(k in data for k in ["id", "name", "description", "type"]):
            raise ValueError("Missing required fields (id, name, description, type) in ability data.")

        # Ensure correct types for fields that might be missing or have defaults
        data_copy = data.copy() # Work on a copy
        data_copy['resource_cost'] = data.get('resource_cost', {})
        data_copy['effects'] = data.get('effects', [])
        data_copy['requirements'] = data.get('requirements', {})
        data_copy['acquisition_methods'] = data.get('acquisition_methods', [])
        
        # Optional fields default to None if not present, which dataclass handles.
        # No specific handling needed for Optional[str], Optional[float] unless type conversion is required.

        return cls(**data_copy)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the Ability instance to a dictionary for serialization."""
        # Using dataclasses.asdict would be simpler if no custom logic needed.
        # For now, manual conversion for clarity and future custom needs.
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
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
        "name": "Toughness I",
        "description": "Increases maximum health by 10.", # Changed from % to flat for simpler example
        "type": "passive_stat_modifier",
        "effects": [
            { "type": "modify_stat", "stat": "max_health", "modifier_type": "flat", "amount": 10 }
        ],
        "requirements": { "level": 1 },
        "icon": "❤️"
    }

    example_activated_ability_data = {
        "id": "power_attack_martial",
        "name": "Power Attack",
        "description": "Make a melee attack with increased force.",
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

    print(f"Created ability: {ability1.name} (Type: {ability1.type})")
    print(f"Effects: {ability1.effects}")
    print(ability1.to_dict())

    print(f"\nCreated ability: {ability2.name} (Type: {ability2.type})")
    print(f"Resource Cost: {ability2.resource_cost}, Effects: {ability2.effects}")
    print(ability2.to_dict())

    # Example for an innate ability
    example_innate_ability_data = {
        "id": "racial_elf_darkvision",
        "name": "Darkvision (Elf)",
        "description": "Can see in dim light as if it were bright light, and in darkness as if it were dim light.",
        "type": "innate_racial",
        "effects": [ { "type": "grant_flag", "flag": "darkvision" } ],
        "acquisition_methods": ["racial_elf"]
    }
    ability3 = Ability.from_dict(example_innate_ability_data)
    print(f"\nCreated ability: {ability3.name} (Type: {ability3.type})")
    print(f"Acquisition: {ability3.acquisition_methods}, Effects: {ability3.effects}")

    # Test missing optional fields
    example_minimal_ability = {
        "id": "minimal_passive",
        "name": "Minimal Passive",
        "description": "A very basic passive.",
        "type": "passive_generic"
        # All optional fields are missing
    }
    ability4 = Ability.from_dict(example_minimal_ability)
    print(f"\nCreated minimal ability: {ability4.name}")
    print(f"Cooldown: {ability4.cooldown}, Resource Cost: {ability4.resource_cost}, Effects: {ability4.effects}")
    assert ability4.cooldown is None
    assert ability4.resource_cost == {}
    assert ability4.effects == []
    assert ability4.requirements == {}
    assert ability4.acquisition_methods == []
    print("Minimal ability test passed.")
