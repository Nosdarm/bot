from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List

@dataclass
class Spell:
    id: str
    name_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    level: int
    mana_cost: int
    casting_time: float # in seconds
    cooldown: float # in seconds
    range: str # e.g., "self", "touch", "10m", or a numeric value
    target_type: str # e.g., "single_enemy", "single_ally", "self", "area"
    
    effects: List[Dict[str, Any]] # List of effects, e.g., {"type": "damage", "amount": "1d6", "damage_type": "fire"}
    
    school: Optional[str] = None
    area_of_effect: Optional[Dict[str, Any]] = None # e.g., {"shape": "radius", "size": 5} if target_type is "area"
    requirements: Optional[Dict[str, Any]] = None # e.g., {"min_intelligence": 10, "required_item_id": "magic_staff"}
    icon: Optional[str] = None # Emoji or path to an icon image
    sfx_cast: Optional[str] = None # Sound effect key for casting
    sfx_impact: Optional[str] = None # Sound effect key for impact (if applicable)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Spell":
        """Creates a Spell instance from a dictionary (typically from JSON)."""
        # Dataclasses automatically handle the conversion of fields,
        # including Optional types and List/Dict types, as long as the
        # input data structure matches the field definitions.
        
        # Handle backward compatibility for name and description
        data_copy = data.copy()
        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {"en": data_copy.pop("name")}
        elif "name" in data_copy and "name_i18n" in data_copy: # If both exist, prefer _i18n
            data_copy.pop("name")

        if "description" in data_copy and "description_i18n" not in data_copy:
            data_copy["description_i18n"] = {"en": data_copy.pop("description")}
        elif "description" in data_copy and "description_i18n" in data_copy: # If both exist, prefer _i18n
            data_copy.pop("description")
            
        # For example, if 'school' is missing in 'data', it will be None.
        # If 'effects' is provided, it will be List[Dict[str, Any]].
        return cls(**data_copy)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the Spell instance to a dictionary for serialization."""
        # A simple way to convert a dataclass to a dict is using dataclasses.asdict.
        # However, for explicit control or if there are specific serialization needs
        # (e.g., converting enums to strings, date formatting), a manual method is better.
        # For this model, a direct field-to-key mapping is sufficient.
        return {
            "id": self.id,
            "name_i18n": self.name_i18n,
            "description_i18n": self.description_i18n,
            "school": self.school,
            "level": self.level,
            "mana_cost": self.mana_cost,
            "casting_time": self.casting_time,
            "cooldown": self.cooldown,
            "range": self.range,
            "target_type": self.target_type,
            "area_of_effect": self.area_of_effect,
            "effects": self.effects,
            "requirements": self.requirements,
            "icon": self.icon,
            "sfx_cast": self.sfx_cast,
            "sfx_impact": self.sfx_impact,
        }

if __name__ == "__main__":
    # Example Usage (primarily for testing the model definition)
    example_spell_data_firebolt = {
        "id": "firebolt_v1",
        "name_i18n": {"en": "Firebolt", "ru": "Огненная стрела"},
        "description_i18n": {"en": "Hurls a small bolt of fire at a target.", "ru": "Бросает небольшой сгусток огня в цель."},
        "school": "evocation",
        "level": 1,
        "mana_cost": 5,
        "casting_time": 0.5,
        "cooldown": 1,
        "range": "30m", 
        "target_type": "single_enemy",
        "effects": [
            { "type": "damage", "amount": "1d8", "damage_type": "fire" }
        ],
        "requirements": { "min_intelligence": 10 },
        "icon": "🔥",
        "sfx_cast": "spell_fire_cast_01",
        "sfx_impact": "spell_fire_impact_01"
        # area_of_effect is missing, will be None
    }

    example_spell_data_mage_armor = {
        "id": "mage_armor_v1",
        "name": "Mage Armor", # Old format for testing backward compatibility
        "description": "Surrounds the caster with a protective magical field.", # Old format
        "school": "abjuration",
        "level": 1,
        "mana_cost": 10,
        "casting_time": 1.0,
        "cooldown": 0,
        "range": "self",
        "target_type": "self",
        "effects": [
            { "type": "apply_status_effect", "status_effect_id": "status_mage_armor", "duration_seconds": 3600 }
        ],
        "icon": "🛡️",
        "sfx_cast": "spell_buff_cast_01"
        # requirements and area_of_effect are missing, will be None
    }
    
    spell1 = Spell.from_dict(example_spell_data_firebolt)
    spell2 = Spell.from_dict(example_spell_data_mage_armor)

    print(f"Created spell: {spell1.name_i18n['en']} (ID: {spell1.id})")
    print(f"Mana cost: {spell1.mana_cost}, School: {spell1.school}")
    print(f"Effects: {spell1.effects}")
    print(f"Area of Effect: {spell1.area_of_effect}") # Should be None
    print(f"Requirements: {spell1.requirements}") # Should be {'min_intelligence': 10}

    print(f"\nCreated spell: {spell2.name_i18n['en']} (ID: {spell2.id})")
    assert spell2.name_i18n == {"en": "Mage Armor"}
    assert spell2.description_i18n == {"en": "Surrounds the caster with a protective magical field."}
    print(f"Target: {spell2.target_type}, Range: {spell2.range}")
    print(f"Effects: {spell2.effects}")
    print(f"Area of Effect: {spell2.area_of_effect}") # Should be None
    print(f"Requirements: {spell2.requirements}") # Should be None
    
    # Test case with explicit None for an optional field and explicit AoE
    example_spell_data_custom = {
        "id": "custom_spell_v1",
        "name_i18n": {"en": "Custom Spell"},
        "description_i18n": {"en": "A spell with some fields explicitly set to None."},
        "level": 3,
        "mana_cost": 15,
        "casting_time": 1.5,
        "cooldown": 2,
        "range": "50m",
        "target_type": "area",
        "effects": [{"type": "control", "effect_type": "stun", "duration": 5}],
        "school": None, # Explicitly None
        "area_of_effect": {"shape": "cone", "length": 10}, # Explicit AoE
        "icon": None # Explicitly None
        # requirements, sfx_cast, sfx_impact are missing, will be None
    }
    spell3 = Spell.from_dict(example_spell_data_custom)
    print(f"\nCreated spell: {spell3.name_i18n['en']} (ID: {spell3.id})")
    print(f"School: {spell3.school}") # Should be None
    print(f"Icon: {spell3.icon}") # Should be None
    print(f"Area of Effect: {spell3.area_of_effect}") # Should be {'shape': 'cone', 'length': 10}
    print(f"Requirements: {spell3.requirements}") # Should be None
    print(f"SFX Cast: {spell3.sfx_cast}") # Should be None
    print(f"SFX Impact: {spell3.sfx_impact}") # Should be None

    # Verify to_dict output for one spell
    # print("\nSpell 1 to_dict output:")
    # import json
    # print(json.dumps(spell1.to_dict(), indent=4))
