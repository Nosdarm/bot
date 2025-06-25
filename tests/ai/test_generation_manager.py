import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

# Models and Enums
from bot.ai.generation_manager import AIGenerationManager
from bot.models.pending_generation import PendingGeneration, GenerationType, PendingStatus
from bot.ai.ai_data_models import (
    GeneratedLocationContent, # Used for type hinting if we deserialize
    POIModel,
    ConnectionModel,
    GeneratedNpcProfile,
    ValidationIssue, # Added import
)
from bot.database.models.world_related import Location as DBLocation
from bot.database.models.character_related import NPC as DBNPC # Corrected import path

# Helper to create valid GeneratedLocationContent data (as dict) for tests
def get_valid_parsed_location_data(
    static_id="test_static_loc_1",
    loc_name="Haunted Forest",
    num_npcs=1,
    num_items=1,
    with_poi_item=True,
    existing_loc_id: str = None # If simulating update, this would be the ID of existing
) -> dict:
    base_data = {
        "template_id": "forest_template_01",
        "name_i18n": {"en": loc_name, "ru": f"{loc_name}_ru"},
        "atmospheric_description_i18n": {"en": "A spooky forest.", "ru": "Spooky forest ru"},
        "location_type_key": "forest_haunted",
        "static_id": static_id,
        "coordinates_json": {"x": 10, "y": 20},
        "points_of_interest": [
            # POIModel(...).model_dump() ensures it's a dict, matching parsed_data_json
            POIModel(poi_id="poi_1", name_i18n={"en": "Old Shack", "ru":"Old Shack RU"}, description_i18n={"en":"A rundown shack.","ru":"Shack RU"}).model_dump()
        ],
        "connections": [
            ConnectionModel(to_location_id="neighbor_forest", path_description_i18n={"en":"Path to neighbor","ru":"Path RU"}, travel_time_hours=1).model_dump()
        ],
        "initial_npcs_json": [],
        "initial_items_json": [],
        "generated_details_json": {"en": {"weather": "foggy"}},
        "ai_metadata_json": {"model": "test_model"}
    }
    if num_npcs > 0:
        for i in range(num_npcs):
            npc_factions = [
                {"faction_id": f"faction_{i}_a", "rank_i18n": {"en": "Member"}},
            ]
            if i % 2 == 0: # Add a second faction for even numbered NPCs for variety
                npc_factions.append({"faction_id": f"faction_{i}_b", "rank_i18n": {"en": "Ally"}})

            npc_inventory = [
                {"item_template_id": f"sword_{i}", "quantity": 1},
                {"item_template_id": f"potion_health_{i}", "quantity": i + 1}
            ]

            npc_dict = {
                "template_id":f"npc_template_{i}",
                "name_i18n":{"en": f"NPC_{i}", "ru":f"НПС_{i}"},
                "role_i18n":{"en":"Test Role","ru":"Тестовая Роль"},
                "archetype":f"test_archetype_{i}",
                "backstory_i18n":{"en":"A long story","ru":"Длинная история"},
                "personality_i18n":{"en":"Unique","ru":"Уникальная"},
                "motivation_i18n":{"en":"Test","ru":"Тест"},
                "visual_description_i18n":{"en":"Visually distinct","ru":"Отличительная внешность"},
                "dialogue_hints_i18n":{"en":"Says things","ru":"Говорит вещи"},
                "stats":{"strength": 10 + i, "dexterity": 8 + i},
                "skills":{"heavy_armor": i, "persuasion": i + 1},
                "abilities": [f"ability_{i}_1", f"ability_{i}_2"],
                "faction_affiliations": npc_factions,
                "inventory": npc_inventory
            }
            base_data["initial_npcs_json"].append(npc_dict)

    if num_items > 0:
        if with_poi_item and base_data["points_of_interest"]:
            base_data["initial_items_json"].append(
                {"template_id": "poi_item_1", "quantity": 1, "target_poi_id": "poi_1"}
            )
        base_data["initial_items_json"].append(
            {"template_id": "general_loot_item_1", "quantity": 2}
        )
    return base_data


@pytest.fixture
def mock_session_context():
    # This context manager mock will be returned by the factory
    mock_ctx = AsyncMock(name="mock_session_context")
    mock_session_obj = AsyncMock(name="mock_session")
    mock_ctx.__aenter__.return_value = mock_session_obj
    mock_ctx.__aexit__ = AsyncMock(return_value=None, name="mock_session_context_exit")
    return mock_ctx

@pytest.fixture
def mock_db_service(mock_session_context: AsyncMock):
    mock = AsyncMock(name="mock_db_service")
    # The factory, when called, returns the context manager mock
    mock.get_session_factory = MagicMock(return_value=lambda: mock_session_context)
    return mock

@pytest.fixture
def mock_game_manager():
    gm = MagicMock(name="mock_game_manager")
    gm.npc_manager = AsyncMock(name="mock_npc_manager")
    return gm

@pytest.fixture
def mock_pending_gen_crud_fixture(): # Renamed to avoid conflict
    return AsyncMock(name="mock_pending_gen_crud")

@pytest.fixture
def ai_generation_manager_fixture(mock_db_service: AsyncMock, mock_game_manager: MagicMock, mock_pending_gen_crud_fixture: AsyncMock):
    manager = AIGenerationManager(
        db_service=mock_db_service,
        prompt_context_collector=MagicMock(),
        multilingual_prompt_generator=MagicMock(),
        ai_response_validator=MagicMock(),
        game_manager=mock_game_manager
    )
    manager.pending_generation_crud = mock_pending_gen_crud_fixture
    return manager


@pytest.mark.asyncio
async def test_process_location_success_new_with_npcs_items(
    ai_generation_manager_fixture: AIGenerationManager,
    mock_pending_gen_crud_fixture: AsyncMock,
    mock_game_manager: MagicMock,
    mock_db_service: AsyncMock,
    mock_session_context: AsyncMock # Get the context mock to access the session
):
    # Arrange
    guild_id = "test_guild_1"
    pending_gen_id = str(uuid.uuid4())
    moderator_id = "mod_user_1"

    parsed_loc_data = get_valid_parsed_location_data(static_id="new_loc_static_1", num_npcs=1, num_items=1)

    mock_pending_generation = PendingGeneration(
        id=pending_gen_id, guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS,
        status=PendingStatus.APPROVED, parsed_data_json=parsed_loc_data, moderator_notes=None
    )
    mock_pending_gen_crud_fixture.get_pending_generation_by_id.return_value = mock_pending_generation

    mock_session = mock_session_context.__aenter__() # Get the session object

    mock_select_result = AsyncMock()
    mock_select_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_select_result

    mock_created_npc_id = str(uuid.uuid4())
    mock_created_npc = DBNPC(id=mock_created_npc_id, template_id="goblin_warrior_0", name_i18n={"en":"Gruk_0"})
    mock_game_manager.npc_manager.spawn_npc_in_location.return_value = mock_created_npc

    # Mock ItemManager.create_item_instance
    mock_poi_item_instance = MagicMock(spec=DBLocation) # Spec helps mock behave like the object
    mock_poi_item_instance.id = "poi_item_instance_uuid_001"
    mock_general_loot_item_instance = MagicMock(spec=DBLocation)
    mock_general_loot_item_instance.id = "general_item_instance_uuid_002"

    # Configure create_item_instance to return different values based on template_id or other args if needed
    # For this test, assume specific calls for specific items if template_ids are unique in test data
    mock_game_manager.item_manager = AsyncMock(name="mock_item_manager") # Ensure it's an AsyncMock
    mock_game_manager.item_manager.create_item_instance = AsyncMock(
        side_effect=[mock_poi_item_instance, mock_general_loot_item_instance] # Returns in order of calls
    )

    persisted_objects = {}

    async def side_effect_merge(obj_to_merge, **kwargs):
        nonlocal persisted_objects
        current_id = getattr(obj_to_merge, 'id', None)
        model_cls = type(obj_to_merge)

        if isinstance(obj_to_merge, DBLocation):
            if not current_id:
                current_id = str(uuid.uuid4())
                obj_to_merge.id = current_id
            persisted_objects[(model_cls, current_id)] = obj_to_merge
        return obj_to_merge
    mock_session.merge = AsyncMock(side_effect=side_effect_merge)

    async def side_effect_get(model_cls, entity_id, **kwargs):
        return persisted_objects.get((model_cls, entity_id))
    mock_session.get = AsyncMock(side_effect=side_effect_get)

    # Act
    with patch('bot.ai.generation_manager.GuildTransaction', lambda _, __: mock_db_service.get_session_factory()()):
        result = await ai_generation_manager_fixture.process_approved_generation(
            pending_gen_id, guild_id, moderator_id
        )

    # Assert
    assert result is True
    mock_pending_gen_crud_fixture.update_pending_generation_status.assert_called_once_with(
        mock_session, pending_gen_id, PendingStatus.APPLIED, guild_id,
        moderator_user_id=moderator_id, moderator_notes=None
    )

    merged_location_obj = None
    for (obj_type, obj_id), obj in persisted_objects.items():
        if obj_type == DBLocation:
            merged_location_obj = obj
            break

    assert merged_location_obj is not None
    assert merged_location_obj.static_id == "new_loc_static_1"
    assert merged_location_obj.name_i18n["en"] == "Haunted Forest"
    assert mock_pending_generation.entity_id == merged_location_obj.id

    mock_game_manager.npc_manager.spawn_npc_in_location.assert_called_once()
    spawn_call_args = mock_game_manager.npc_manager.spawn_npc_in_location.call_args
    assert spawn_call_args.kwargs['location_id'] == merged_location_obj.id
    assert spawn_call_args.kwargs['npc_template_id'] == "goblin_warrior_0"
    initial_state_arg = spawn_call_args.kwargs['initial_state']
    assert "skills_data" in initial_state_arg and initial_state_arg["skills_data"] == {"heavy_armor": 0, "persuasion": 1} # Based on i=0
    assert "abilities_data" in initial_state_arg and initial_state_arg["abilities_data"] == ["ability_0_1", "ability_0_2"]

    # Assert faction data in initial_state_arg
    expected_primary_faction_id = parsed_loc_data["initial_npcs_json"][0]["faction_affiliations"][0]["faction_id"]
    assert "faction_id" in initial_state_arg and initial_state_arg["faction_id"] == expected_primary_faction_id
    assert "faction_details_list" in initial_state_arg
    assert len(initial_state_arg["faction_details_list"]) == len(parsed_loc_data["initial_npcs_json"][0]["faction_affiliations"])
    assert initial_state_arg["faction_details_list"][0]["faction_id"] == expected_primary_faction_id

    # Assert inventory data in initial_state_arg
    assert "inventory" in initial_state_arg
    assert len(initial_state_arg["inventory"]) == len(parsed_loc_data["initial_npcs_json"][0]["inventory"])
    assert initial_state_arg["inventory"][0]["item_template_id"] == "sword_0"

    assert merged_location_obj.npc_ids == [mock_created_npc_id]

    assert len(merged_location_obj.points_of_interest_json) == 1
    poi_data_after_processing = merged_location_obj.points_of_interest_json[0]

    # Assert new field is populated for PoI item
    assert "contained_item_instance_ids" in poi_data_after_processing
    assert mock_poi_item_instance.id in poi_data_after_processing["contained_item_instance_ids"]

    # Assert old field is NOT populated by new logic for PoI item
    # If the test data for POIModel initially had contained_item_ids, it might still be there.
    # The important part is that new item instances don't add to it.
    # For this test, parsed_loc_data["points_of_interest"][0] did not have "contained_item_ids"
    # so we expect it to be absent or None if the model defaults it.
    # The current POIModel in ai_data_models.py defaults contained_item_ids to None.
    # If it was [] by default in the model dump, then this would be assert "poi_item_1" not in ...
    assert poi_data_after_processing.get("contained_item_ids") is None

    # Assert general loot item was created via item_manager call
    # And that initial_ai_loot (old way) is not populated by new items
    assert "initial_ai_loot" not in merged_location_obj.inventory or \
           not any(d["template_id"] == "general_loot_item_1" for d in merged_location_obj.inventory.get("initial_ai_loot", []))

    # Check calls to create_item_instance
    assert mock_game_manager.item_manager.create_item_instance.call_count == 2
    calls = mock_game_manager.item_manager.create_item_instance.call_args_list

    # PoI item call
    poi_item_call_args = calls[0].kwargs
    assert poi_item_call_args['template_id'] == "poi_item_1"
    assert poi_item_call_args['location_id'] == merged_location_obj.id
    assert poi_item_call_args['owner_type'] == "location"
    assert poi_item_call_args['owner_id'] == merged_location_obj.id
    assert poi_item_call_args['initial_state'] == {"is_in_poi_id": "poi_1"}
    assert poi_item_call_args['session'] == mock_session

    # General loot item call
    general_item_call_args = calls[1].kwargs
    assert general_item_call_args['template_id'] == "general_loot_item_1"
    assert general_item_call_args['location_id'] == merged_location_obj.id
    assert general_item_call_args['owner_type'] == "location"
    assert general_item_call_args['owner_id'] == merged_location_obj.id
    assert general_item_call_args['session'] == mock_session
    # initial_state might be None or {} depending on implementation if not provided by caller
    # current generation_manager passes initial_state only for PoI items.

    # Assert neighbor_locations_json
    assert isinstance(merged_location_obj.neighbor_locations_json, list)
    assert len(merged_location_obj.neighbor_locations_json) == 1
    first_connection = merged_location_obj.neighbor_locations_json[0]
    assert first_connection["to_location_id"] == "neighbor_forest"
    assert isinstance(first_connection["path_description_i18n"], dict)
    assert first_connection["path_description_i18n"]["en"] == "Path to neighbor"
    assert first_connection["travel_time_hours"] == 1

    mock_session_context.__aexit__.assert_called_once_with(None, None, None)


@pytest.mark.asyncio
async def test_process_location_success_update_existing(
    ai_generation_manager_fixture: AIGenerationManager,
    mock_pending_gen_crud_fixture: AsyncMock,
    mock_db_service: AsyncMock,
    mock_session_context: AsyncMock
):
    # Arrange
    guild_id = "test_guild_1"
    pending_gen_id = str(uuid.uuid4())
    moderator_id = "mod_user_1"
    existing_loc_id = str(uuid.uuid4())
    existing_static_id = "existing_static_loc_id"

    parsed_loc_data = get_valid_parsed_location_data(
        static_id=existing_static_id, loc_name="Renovated Haunted Forest", num_npcs=0, num_items=0
    )

    mock_pending_generation = PendingGeneration(
        id=pending_gen_id, guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS,
        status=PendingStatus.APPROVED, parsed_data_json=parsed_loc_data, moderator_notes=None
    )
    mock_pending_gen_crud_fixture.get_pending_generation_by_id.return_value = mock_pending_generation

    mock_session = mock_session_context.__aenter__()

    existing_db_location = DBLocation(
        id=existing_loc_id, guild_id=guild_id, static_id=existing_static_id,
        name_i18n={"en": "Original Haunted Forest"},
            template_id="forest_template_01",
            type_i18n={"en": "Haunted Forest", "_key": "forest_haunted"}, # Corrected: use type_i18n
        descriptions_i18n={"en": "Old spooky forest."}
    )
    mock_select_result = AsyncMock()
    mock_select_result.scalars.return_value.first.return_value = existing_db_location
    mock_session.execute.return_value = mock_select_result

    persisted_objects = {(DBLocation, existing_loc_id): existing_db_location}

    async def side_effect_merge(obj_to_merge, **kwargs):
        persisted_objects[(type(obj_to_merge), obj_to_merge.id)] = obj_to_merge
        return obj_to_merge
    mock_session.merge = AsyncMock(side_effect=side_effect_merge)

    async def side_effect_get(model_cls, entity_id, **kwargs):
        return persisted_objects.get((model_cls, entity_id))
    mock_session.get = AsyncMock(side_effect=side_effect_get)

    # Act
    with patch('bot.ai.generation_manager.GuildTransaction', lambda _, __: mock_db_service.get_session_factory()()): # type: ignore
        result = await ai_generation_manager_fixture.process_approved_generation(
            pending_gen_id, guild_id, moderator_id
        )

    # Assert
    assert result is True
    mock_pending_gen_crud_fixture.update_pending_generation_status.assert_called_with( # type: ignore
        mock_session, pending_gen_id, PendingStatus.APPLIED, guild_id,
        moderator_user_id=moderator_id, moderator_notes=None
    )

    merged_location_obj = persisted_objects.get((DBLocation, existing_loc_id))
    assert merged_location_obj is not None
    assert merged_location_obj.id == existing_loc_id # type: ignore
    assert merged_location_obj.name_i18n["en"] == "Renovated Haunted Forest" # type: ignore
    assert mock_pending_generation.entity_id == existing_loc_id
    mock_session_context.__aexit__.assert_called_once_with(None, None, None) # type: ignore


@pytest.mark.asyncio
async def test_process_location_failure_npc_spawn_preserves_notes(
    ai_generation_manager_fixture: AIGenerationManager,
    mock_pending_gen_crud_fixture: AsyncMock,
    mock_game_manager: MagicMock,
    mock_db_service: AsyncMock,
    mock_session_context: AsyncMock
):
    # Arrange
    guild_id = "test_guild_1"
    pending_gen_id = str(uuid.uuid4())
    moderator_id = "mod_user_1"
    initial_mod_notes = "Pre-existing notes."

    parsed_loc_data = get_valid_parsed_location_data(num_npcs=1)

    mock_pending_generation = PendingGeneration(
        id=pending_gen_id, guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS,
        status=PendingStatus.APPROVED, parsed_data_json=parsed_loc_data, moderator_notes=initial_mod_notes
    )
    mock_pending_gen_crud_fixture.get_pending_generation_by_id.return_value = mock_pending_generation # type: ignore

    mock_session = mock_session_context.__aenter__() # type: ignore
    mock_select_result = AsyncMock()
    mock_select_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_select_result

    mock_game_manager.npc_manager.spawn_npc_in_location.return_value = None # Simulate NPC spawn failure

    persisted_objects = {}
    async def side_effect_merge(obj_to_merge, **kwargs):
        if isinstance(obj_to_merge, DBLocation):
            if not obj_to_merge.id: obj_to_merge.id = str(uuid.uuid4()) # type: ignore
            persisted_objects[(DBLocation, obj_to_merge.id)] = obj_to_merge # type: ignore
        return obj_to_merge
    mock_session.merge = AsyncMock(side_effect=side_effect_merge)
    async def side_effect_get(model_cls, entity_id, **kwargs):
        return persisted_objects.get((model_cls, entity_id))
    mock_session.get = AsyncMock(side_effect=side_effect_get)

    # Act
    with patch('bot.ai.generation_manager.GuildTransaction', lambda _, __: mock_db_service.get_session_factory()()): # type: ignore
        result = await ai_generation_manager_fixture.process_approved_generation(
            pending_gen_id, guild_id, moderator_id
        )

    # Assert
    assert result is False
    update_call = mock_pending_gen_crud_fixture.update_pending_generation_status.call_args # type: ignore
    assert update_call.args[2] == PendingStatus.APPLICATION_FAILED

    expected_notes_fragment = "Failed to spawn NPC" # Part of the error message
    assert initial_mod_notes in update_call.kwargs['moderator_notes']
    assert expected_notes_fragment in update_call.kwargs['moderator_notes']

    mock_session_context.__aexit__.assert_called_once_with(None, None, None) # type: ignore


@pytest.mark.asyncio
async def test_process_location_failure_parsing(
    ai_generation_manager_fixture: AIGenerationManager,
    mock_pending_gen_crud_fixture: AsyncMock,
    mock_db_service: AsyncMock,
    mock_session_context: AsyncMock
):
    # Arrange
    guild_id = "test_guild_1"
    pending_gen_id = str(uuid.uuid4())
    moderator_id = "mod_user_1"

    malformed_parsed_data = get_valid_parsed_location_data()
    malformed_parsed_data["name_i18n"] = "This should be a dict" # type: ignore

    mock_pending_generation = PendingGeneration(
        id=pending_gen_id, guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS,
        status=PendingStatus.APPROVED, parsed_data_json=malformed_parsed_data
    )
    mock_pending_gen_crud_fixture.get_pending_generation_by_id.return_value = mock_pending_generation # type: ignore
    mock_session = mock_session_context.__aenter__() # type: ignore

    # Act
    with patch('bot.ai.generation_manager.GuildTransaction', lambda _, __: mock_db_service.get_session_factory()()): # type: ignore
        result = await ai_generation_manager_fixture.process_approved_generation(
            pending_gen_id, guild_id, moderator_id
        )

    # Assert
    assert result is False
    update_call = mock_pending_gen_crud_fixture.update_pending_generation_status.call_args # type: ignore
    assert update_call.args[0] == mock_session # Ensure it's called with the correct session
    assert update_call.args[2] == PendingStatus.APPLICATION_FAILED
    assert "Failed to parse AI data" in update_call.kwargs['moderator_notes']
    mock_session_context.__aexit__.assert_called_once_with(None, None, None) # type: ignore


@pytest.mark.asyncio
async def test_request_content_generation_success_pending_moderation(
    ai_generation_manager_fixture: AIGenerationManager,
    mock_pending_gen_crud_fixture: AsyncMock, # Already a fixture
    mock_game_manager: MagicMock # Already a fixture
):
    guild_id = "test_req_guild"
    user_id = "user_req_1"
    req_type = GenerationType.NPC_PROFILE
    context_params = {"character_id": "char1", "location_id": "loc1"}
    prompt_params = {"specific_task_instruction": "Create a friendly merchant."}

    # Mock dependencies of request_content_generation
    mock_generation_context = MagicMock() # Simplified for this test
    ai_generation_manager_fixture.prompt_context_collector.get_full_context = AsyncMock(return_value=mock_generation_context)

    mock_final_prompt_str = "Final prompt for AI"
    ai_generation_manager_fixture.multilingual_prompt_generator.prepare_ai_prompt = AsyncMock(return_value=mock_final_prompt_str)

    # Simulate successful validation
    mock_parsed_data = {"name_i18n": {"en": "Generated Merchant"}}
    ai_generation_manager_fixture.ai_response_validator.parse_and_validate_ai_response = AsyncMock(return_value=(mock_parsed_data, None))

    # Mock get_rule for target_languages
    mock_game_manager.get_rule = AsyncMock(return_value="en") # Default lang

    # Mock NotificationService
    mock_game_manager.notification_service = AsyncMock()
    mock_game_manager.db_service.get_entity_by_pk = AsyncMock(return_value=MagicMock(notification_channel_id="12345"))


    created_pg_record = PendingGeneration(
        id=str(uuid.uuid4()), guild_id=guild_id, request_type=req_type, status=PendingStatus.PENDING_MODERATION,
        request_params_json=context_params, raw_ai_output_text="Simulated AI output", parsed_data_json=mock_parsed_data,
        created_by_user_id=user_id
    )
    mock_pending_gen_crud_fixture.create_pending_generation = AsyncMock(return_value=created_pg_record)

    # Act
    result_record = await ai_generation_manager_fixture.request_content_generation(
        guild_id, req_type, context_params, prompt_params, user_id
    )

    # Assert
    assert result_record is not None
    assert result_record.status == PendingStatus.PENDING_MODERATION

    ai_generation_manager_fixture.prompt_context_collector.get_full_context.assert_awaited_once_with(
        guild_id=guild_id, character_id="char1", location_id="loc1", target_entity_id=None, target_entity_type=None, event_id=None
    )
    ai_generation_manager_fixture.multilingual_prompt_generator.prepare_ai_prompt.assert_awaited_once()
    ai_generation_manager_fixture.ai_response_validator.parse_and_validate_ai_response.assert_awaited_once()

    mock_pending_gen_crud_fixture.create_pending_generation.assert_awaited_once()
    create_call_args = mock_pending_gen_crud_fixture.create_pending_generation.call_args
    assert create_call_args.kwargs['guild_id'] == guild_id
    assert create_call_args.kwargs['request_type'] == req_type
    assert create_call_args.kwargs['status'] == PendingStatus.PENDING_MODERATION
    assert create_call_args.kwargs['parsed_data_json'] == mock_parsed_data

    mock_game_manager.notification_service.send_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_content_generation_failed_validation(
    ai_generation_manager_fixture: AIGenerationManager,
    mock_pending_gen_crud_fixture: AsyncMock,
    mock_game_manager: MagicMock
):
    guild_id = "test_req_fail_guild"
    req_type = GenerationType.ITEM_PROFILE
    # ... (similar setup for context_params, prompt_params)

    # Simulate validation failure
    validation_issues = [ValidationIssue(loc=["name"], type="value_error", msg="Too short")]
    ai_generation_manager_fixture.ai_response_validator.parse_and_validate_ai_response = AsyncMock(
        return_value=({"name_i18n": "X"}, validation_issues) # Parsed data, but with issues
    )
    mock_game_manager.get_rule = AsyncMock(return_value="en") # Default lang

    created_pg_record_failed = PendingGeneration(
        id=str(uuid.uuid4()), guild_id=guild_id, request_type=req_type, status=PendingStatus.FAILED_VALIDATION,
        validation_issues_json=[vi.model_dump() for vi in validation_issues]
    )
    mock_pending_gen_crud_fixture.create_pending_generation = AsyncMock(return_value=created_pg_record_failed)


    # Act
    result_record = await ai_generation_manager_fixture.request_content_generation(
        guild_id, req_type, {}, {}, None
    )

    # Assert
    assert result_record is not None
    assert result_record.status == PendingStatus.FAILED_VALIDATION
    mock_pending_gen_crud_fixture.create_pending_generation.assert_awaited_once()
    create_call_args = mock_pending_gen_crud_fixture.create_pending_generation.call_args
    assert create_call_args.kwargs['status'] == PendingStatus.FAILED_VALIDATION
    assert create_call_args.kwargs['validation_issues_json'] == [vi.model_dump() for vi in validation_issues]

    if hasattr(mock_game_manager, 'notification_service'): # Check if attribute exists
        mock_game_manager.notification_service.send_notification.assert_not_called()

