import pytest
from pydantic import ValidationError
from typing import Dict, Any, List

from bot.ai.ai_data_models import (
    GeneratedLocationContent,
    POIModel,
    ConnectionModel,
    GeneratedNpcProfile,
    GeneratedNpcInventoryItem,
    GeneratedNpcFactionAffiliation,
    GeneratedNpcRelationship,
    validate_i18n_field # For testing context
)

# --- Helper Functions for Test Data ---

def get_valid_i18n_dict(text: str = "Test") -> Dict[str, str]:
    return {"en": f"{text} EN", "ru": f"{text} RU"}

def get_valid_poi_model_data(poi_id: str = "poi_1") -> Dict[str, Any]:
    return {
        "poi_id": poi_id,
        "name_i18n": get_valid_i18n_dict(f"{poi_id} Name"),
        "description_i18n": get_valid_i18n_dict(f"{poi_id} Description"),
        "contained_item_ids": ["item_template_1"],
        "npc_ids": ["npc_static_id_1"]
    }

def get_valid_connection_model_data(to_location_id: str = "loc_2") -> Dict[str, Any]:
    return {
        "to_location_id": to_location_id,
        "path_description_i18n": get_valid_i18n_dict(f"Path to {to_location_id}"),
        "travel_time_hours": 2
    }

def get_valid_npc_inventory_item_data(item_template_id: str = "sword_common") -> Dict[str, Any]:
    return {"item_template_id": item_template_id, "quantity": 1}

def get_valid_npc_faction_affiliation_data(faction_id: str = "empire") -> Dict[str, Any]:
    return {"faction_id": faction_id, "rank_i18n": get_valid_i18n_dict("Legionnaire")}

def get_valid_npc_relationship_data(target_entity_id: str = "npc_friend_1") -> Dict[str, Any]:
    return {"target_entity_id": target_entity_id, "relationship_type": "FRIENDLY", "strength": 80}


def get_valid_generated_npc_profile_data(template_id: str = "npc_guard_template") -> Dict[str, Any]:
    return {
        "template_id": template_id,
        "name_i18n": get_valid_i18n_dict("Guard"),
        "role_i18n": get_valid_i18n_dict("City Guard"),
        "archetype": "guard",
        "backstory_i18n": get_valid_i18n_dict("Guard backstory"),
        "personality_i18n": get_valid_i18n_dict("Stern but fair"),
        "motivation_i18n": get_valid_i18n_dict("Protect the city"),
        "visual_description_i18n": get_valid_i18n_dict("Tall and imposing"),
        "dialogue_hints_i18n": get_valid_i18n_dict("Speaks formally"),
        "stats": {"strength": 12, "dexterity": 10},
        "skills": {"one_handed_sword": 3, "block": 2},
        "abilities": ["power_attack"],
        "spells": [],
        "inventory": [get_valid_npc_inventory_item_data()],
        "faction_affiliations": [get_valid_npc_faction_affiliation_data()],
        "relationships": [get_valid_npc_relationship_data()],
        "is_trader": False,
        "currency_gold": 50
    }

def get_valid_generated_location_content_data(location_name: str = "Test Location") -> Dict[str, Any]:
    return {
        "template_id": "test_loc_template_001",
        "name_i18n": get_valid_i18n_dict(location_name),
        "atmospheric_description_i18n": get_valid_i18n_dict(f"{location_name} Atmosphere"),
        "points_of_interest": [POIModel(**get_valid_poi_model_data("poi_main"))],
        "connections": [ConnectionModel(**get_valid_connection_model_data("neighbor_loc_1"))],
        "possible_events_i18n": [get_valid_i18n_dict("A merchant passes by")],
        "required_access_items_ids": ["key_to_city"],
        # New fields
        "static_id": f"static_{location_name.lower().replace(' ', '_')}",
        "location_type_key": "city_district",
        "coordinates_json": {"x": 100, "y": 200, "plane": "material"},
        "initial_npcs_json": [GeneratedNpcProfile(**get_valid_generated_npc_profile_data("npc_guard_01"))],
        "initial_items_json": [
            {"template_id": "healing_potion", "quantity": 2, "target_poi_id": "poi_main"},
            {"template_id": "gold_coins", "quantity": 100}
        ],
        "generated_details_json": {"en": {"flora": "Mostly hardy shrubs", "fauna": "City rats and pigeons"}},
        "ai_metadata_json": {"prompt_version": "1.2", "model_used": "gpt-4-turbo"}
    }

# --- Test Cases for GeneratedLocationContent ---

@pytest.fixture
def validation_context_en_only():
    return {"target_languages": ["en"]}

@pytest.fixture
def validation_context_en_ru():
    return {"target_languages": ["en", "ru"]}

def test_generated_location_content_successful_validation(validation_context_en_ru):
    data = get_valid_generated_location_content_data()
    # Pydantic models for nested lists are already part of the data construction
    loc_content = GeneratedLocationContent.model_validate(data, context=validation_context_en_ru)

    assert loc_content.template_id == data["template_id"]
    assert loc_content.name_i18n["en"] == data["name_i18n"]["en"]
    assert loc_content.static_id == data["static_id"]
    assert loc_content.location_type_key == data["location_type_key"]
    assert loc_content.coordinates_json["x"] == 100
    assert len(loc_content.initial_npcs_json) == 1
    assert loc_content.initial_npcs_json[0].template_id == "npc_guard_01"
    assert len(loc_content.initial_items_json) == 2
    assert loc_content.initial_items_json[0]["template_id"] == "healing_potion"
    assert loc_content.generated_details_json["en"]["flora"] == "Mostly hardy shrubs"
    assert loc_content.ai_metadata_json["model_used"] == "gpt-4-turbo"
    assert len(loc_content.points_of_interest) == 1
    assert loc_content.points_of_interest[0].poi_id == "poi_main"
    assert len(loc_content.connections) == 1
    assert loc_content.connections[0].to_location_id == "neighbor_loc_1"

def test_generated_location_content_missing_required_fields(validation_context_en_ru):
    required_fields = ["name_i18n", "atmospheric_description_i18n", "location_type_key"]
    for field in required_fields:
        data = get_valid_generated_location_content_data()
        del data[field]
        with pytest.raises(ValidationError, match=f"Field required.*{field}"):
             GeneratedLocationContent.model_validate(data, context=validation_context_en_ru)

    # template_id is also required by the model definition, but not in the prompt's list
    data = get_valid_generated_location_content_data()
    del data["template_id"]
    with pytest.raises(ValidationError, match="Field required.*template_id"):
        GeneratedLocationContent.model_validate(data, context=validation_context_en_ru)


def test_generated_location_content_i18n_validation(validation_context_en_ru):
    data = get_valid_generated_location_content_data()
    data["name_i18n"] = {"fr": "French Name Only"} # Missing 'en' and 'ru'

    with pytest.raises(ValidationError) as exc_info:
        GeneratedLocationContent.model_validate(data, context=validation_context_en_ru)

    # Example check, details might vary based on your validator's exact messages
    assert "name_i18n" in str(exc_info.value)
    assert "missing required language(s): en, ru" in str(exc_info.value).lower()


def test_generated_location_content_i18n_validation_en_only_context_copies_to_en(validation_context_en_only):
    data = get_valid_generated_location_content_data()
    data["name_i18n"] = {"ru": "Russian Name Only"} # Missing 'en'

    # validate_i18n_field should copy from 'ru' to 'en' if 'en' is missing and context is 'en'
    loc_content = GeneratedLocationContent.model_validate(data, context=validation_context_en_only)
    assert loc_content.name_i18n["en"] == "Russian Name Only"
    assert loc_content.name_i18n["ru"] == "Russian Name Only"


def test_generated_location_content_new_fields_accepted(validation_context_en_ru):
    data = {
        "template_id": "minimal_template",
        "name_i18n": get_valid_i18n_dict("Minimal"),
        "atmospheric_description_i18n": get_valid_i18n_dict("Minimal Atmosphere"),
        # Required new field
        "location_type_key": "ruin_exterior",
        # Optional new fields
        "static_id": "minimal_static_001",
        "coordinates_json": {"x": 0, "y": 0},
        "initial_npcs_json": [], # Empty list is valid
        "initial_items_json": [{"template_id": "rock", "quantity": 1}], # Valid item
        "generated_details_json": {"en": {"weather": "always raining"}},
        "ai_metadata_json": {"source": "test_case"}
    }
    loc_content = GeneratedLocationContent.model_validate(data, context=validation_context_en_ru)
    assert loc_content.static_id == "minimal_static_001"
    assert loc_content.location_type_key == "ruin_exterior"
    assert loc_content.coordinates_json == {"x": 0, "y": 0}
    assert loc_content.initial_npcs_json == []
    assert len(loc_content.initial_items_json) == 1
    assert loc_content.initial_items_json[0]["template_id"] == "rock"
    assert loc_content.generated_details_json["en"]["weather"] == "always raining"
    assert loc_content.ai_metadata_json["source"] == "test_case"

def test_poi_model_validation():
    valid_data = get_valid_poi_model_data()
    poi = POIModel(**valid_data)
    assert poi.poi_id == valid_data["poi_id"]
    assert poi.contained_item_ids == ["item_template_1"] # Existing field
    assert poi.contained_item_instance_ids is None # New field defaults to None

    # Test with new field
    valid_data_with_instance_ids = {
        "poi_id": "poi_2",
        "name_i18n": get_valid_i18n_dict("POI 2 Name"),
        "description_i18n": get_valid_i18n_dict("POI 2 Description"),
        "contained_item_ids": ["item_template_2"], # Still accepted
        "contained_item_instance_ids": ["item_instance_uuid_001", "item_instance_uuid_002"],
        "npc_ids": []
    }
    poi_with_instances = POIModel(**valid_data_with_instance_ids)
    assert poi_with_instances.poi_id == "poi_2"
    assert poi_with_instances.contained_item_ids == ["item_template_2"]
    assert poi_with_instances.contained_item_instance_ids == ["item_instance_uuid_001", "item_instance_uuid_002"]

    # Test validation error if new field is not a list of strings (if provided)
    invalid_data_instance_ids = valid_data_with_instance_ids.copy()
    invalid_data_instance_ids["contained_item_instance_ids"] = "not_a_list"
    with pytest.raises(ValidationError) as excinfo_instance:
        POIModel(**invalid_data_instance_ids)
    assert "list[str]" in str(excinfo_instance.value).lower()

    invalid_data_instance_ids_list_type = valid_data_with_instance_ids.copy()
    invalid_data_instance_ids_list_type["contained_item_instance_ids"] = [123, "abc"] # Contains non-string
    with pytest.raises(ValidationError) as excinfo_instance_list_type:
        POIModel(**invalid_data_instance_ids_list_type)
    assert "str_type" in str(excinfo_instance_list_type.value).lower()


    with pytest.raises(ValidationError):
        POIModel(**{"name_i18n": {}, "description_i18n": {}}) # Missing poi_id

def test_connection_model_validation():
    valid_data = get_valid_connection_model_data()
    conn = ConnectionModel(**valid_data)
    assert conn.to_location_id == valid_data["to_location_id"]

    with pytest.raises(ValidationError):
        ConnectionModel(**{"path_description_i18n": {}}) # Missing to_location_id

def test_generated_npc_profile_validation():
    # Basic check, more detailed tests would be in a dedicated NPC model test suite
    valid_data = get_valid_generated_npc_profile_data()
    npc_profile = GeneratedNpcProfile(**valid_data)
    assert npc_profile.template_id == valid_data["template_id"]
    assert npc_profile.stats["strength"] == 12
    assert len(npc_profile.inventory) == 1
    assert npc_profile.inventory[0].item_template_id == "sword_common"

# Example test for optional fields being None
def test_generated_location_content_optional_fields_as_none(validation_context_en_ru):
    data = {
        "template_id": "optional_test",
        "name_i18n": get_valid_i18n_dict("Optional Fields Test"),
        "atmospheric_description_i18n": get_valid_i18n_dict("Atmosphere for Optional"),
        "location_type_key": "test_type",
        # All other fields are optional or have defaults in Pydantic model if not required by logic
        "static_id": None,
        "points_of_interest": None,
        "connections": None,
        "possible_events_i18n": None,
        "required_access_items_ids": None,
        "coordinates_json": None,
        "initial_npcs_json": None,
        "initial_items_json": None,
        "generated_details_json": None,
        "ai_metadata_json": None,
    }
    loc_content = GeneratedLocationContent.model_validate(data, context=validation_context_en_ru)
    assert loc_content.static_id is None
    assert loc_content.points_of_interest is None # Will be None as per Pydantic
    assert loc_content.initial_npcs_json is None
    assert loc_content.generated_details_json is None
    # etc. for all optional fields
```
