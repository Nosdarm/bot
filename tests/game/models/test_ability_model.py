import pytest
from bot.game.models.ability import Ability

def test_ability_from_dict_with_static_id():
    data = {
        "id": "ability_instance_1",
        "static_id": "fireball_v1",
        "name_i18n": {"en": "Fireball"},
        "description_i18n": {"en": "Hurls a fiery ball."},
        "type": "combat_spell"
    }
    ability = Ability.from_dict(data)
    assert ability.id == "ability_instance_1"
    assert ability.static_id == "fireball_v1"
    assert ability.name_i18n["en"] == "Fireball"

def test_ability_from_dict_without_static_id():
    data = {
        "id": "ability_instance_2",
        "name_i18n": {"en": "Minor Heal"},
        "description_i18n": {"en": "Heals a minor amount."},
        "type": "healing_spell"
    }
    ability = Ability.from_dict(data)
    assert ability.id == "ability_instance_2"
    assert ability.static_id is None
    assert ability.name_i18n["en"] == "Minor Heal"

def test_ability_from_dict_minimal_required():
    data = {
        "id": "ability_instance_3",
        "name_i18n": {"en": "Punch"},
        "description_i18n": {"en": "A simple punch."},
        "type": "basic_attack"
    }
    ability = Ability.from_dict(data)
    assert ability.id == "ability_instance_3"
    assert ability.static_id is None # Optional, so defaults to None
    assert ability.type == "basic_attack"

def test_ability_from_dict_handles_extra_fields_gracefully():
    # The current from_dict passes all of data_copy to cls(**data_copy)
    # Dataclasses ignore extra fields in the constructor by default.
    data = {
        "id": "ability_instance_4",
        "name_i18n": {"en": "Advanced Ability"},
        "description_i18n": {"en": "Does advanced things."},
        "type": "advanced",
        "static_id": "adv_001",
        "extra_field_not_in_model": "should_be_ignored"
    }
    ability = Ability.from_dict(data)
    assert ability.static_id == "adv_001"
    assert not hasattr(ability, "extra_field_not_in_model")

def test_ability_to_dict_includes_static_id():
    ability = Ability(
        id="ability_instance_1",
        static_id="fireball_v1_dict",
        name_i18n={"en": "Fireball"},
        description_i18n={"en": "Hurls a fiery ball."},
        type="combat_spell"
    )
    data = ability.to_dict()
    assert data["id"] == "ability_instance_1"
    assert data["static_id"] == "fireball_v1_dict"
    assert data["name_i18n"]["en"] == "Fireball"

def test_ability_to_dict_handles_none_static_id():
    ability = Ability(
        id="ability_instance_2",
        # static_id is None by default if not provided
        name_i18n={"en": "Minor Heal"},
        description_i18n={"en": "Heals a minor amount."},
        type="healing_spell"
    )
    data = ability.to_dict()
    assert data["id"] == "ability_instance_2"
    assert data["static_id"] is None
    assert data["name_i18n"]["en"] == "Minor Heal"

def test_ability_to_dict_all_fields():
    # Test with more fields to ensure they are also present
    details = {
        "id": "complex_ability_1",
        "static_id": "complex_static_001",
        "name_i18n": {"en": "Complex Ability", "ru": "Комплексная Способность"},
        "description_i18n": {"en": "This ability has many fields.", "ru": "Эта способность имеет много полей."},
        "type": "utility",
        "activation_type": "action",
        "resource_cost": {"mana": 10},
        "cooldown": 2.0,
        "range": "30m",
        "target_type": "single_ally",
        "effects": [{"type": "heal", "amount": 20}],
        "requirements": {"level": 5},
        "acquisition_methods": ["learned"],
        "icon": "✨",
        "sfx_on_activation": "heal_sound",
        "sfx_on_trigger": None
    }
    ability = Ability(**details)
    data = ability.to_dict()

    # Check a few key fields plus static_id
    assert data["static_id"] == "complex_static_001"
    assert data["type"] == "utility"
    assert data["resource_cost"] == {"mana": 10}
    assert data["effects"][0]["amount"] == 20
    assert len(data.keys()) == len(details.keys()) # Ensure all expected keys are there
    for key in details:
        assert data[key] == details[key]
