import pytest
from bot.game.models.status import Status

def test_status_from_dict_with_static_id():
    data = {
        "id": "status_instance_1",
        "static_id": "poisoned_effect_v1",
        "name": "Poisoned", # Assuming other fields like name are handled by kwargs
        "duration_turns": 5
    }
    status = Status.from_dict(data)
    assert status.id == "status_instance_1"
    assert status.static_id == "poisoned_effect_v1"
    assert status.name == "Poisoned"
    assert status.duration_turns == 5

def test_status_from_dict_missing_static_id_raises_value_error():
    data = {
        "id": "status_instance_2",
        "name": "Blessed",
        "duration_turns": 10
    }
    with pytest.raises(ValueError) as excinfo:
        Status.from_dict(data)
    assert "Missing required field 'static_id'" in str(excinfo.value)

def test_status_from_dict_missing_id_raises_value_error():
    # Based on the current implementation of Status.from_dict
    data = {
        "static_id": "cursed_effect_v1",
        "name": "Cursed",
    }
    with pytest.raises(ValueError) as excinfo:
        Status.from_dict(data)
    assert "Missing required field 'id'" in str(excinfo.value)

def test_status_to_dict_includes_static_id_and_other_fields():
    status = Status(
        id="status_instance_3",
        static_id="hasted_effect_v1",
        name="Hasted",
        speed_bonus=10,
        source="potion"
    )
    data = status.to_dict()
    assert data["id"] == "status_instance_3"
    assert data["static_id"] == "hasted_effect_v1"
    assert data["name"] == "Hasted"
    assert data["speed_bonus"] == 10
    assert data["source"] == "potion"

def test_status_to_dict_minimal():
    status = Status(
        id="status_instance_4",
        static_id="stunned_minimal"
    )
    data = status.to_dict()
    assert data["id"] == "status_instance_4"
    assert data["static_id"] == "stunned_minimal"
    # Check that only id and static_id are present if no other kwargs were passed
    # The current to_dict adds all items from __dict__
    expected_keys = {"id", "static_id"}
    assert set(data.keys()) == expected_keys

def test_status_instantiation_and_attributes():
    status = Status(id="s1", static_id="regen_s1", current_tick=0, max_duration=5)
    assert status.id == "s1"
    assert status.static_id == "regen_s1"
    assert status.current_tick == 0
    assert status.max_duration == 5

    out_dict = status.to_dict()
    assert out_dict["id"] == "s1"
    assert out_dict["static_id"] == "regen_s1"
    assert out_dict["current_tick"] == 0
    assert out_dict["max_duration"] == 5
