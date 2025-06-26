import pytest
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game.managers.status_manager import StatusManager, ApplyStatusResult
from bot.database.models import Character as CharacterDbModel, Player as PlayerDbModel
from bot.services.db_service import DBService
from bot.game.managers.character_manager import CharacterManager
from bot.game.rules.rule_engine import RuleEngine # Corrected path
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.ai.rules_schema import CoreGameRulesConfig, StatusEffectDefinition # For status templates

# --- Fixtures ---

@pytest.fixture
def mock_db_service_for_status():
    service = AsyncMock(spec=DBService)
    # Mock the get_session context manager
    mock_session_instance = AsyncMock(name="MockSessionForStatus")
    mock_session_instance.get = AsyncMock() # For session.get(Character, ...)
    mock_session_instance.add = MagicMock()
    mock_session_instance.commit = AsyncMock() # Should only be called if manager creates session
    mock_session_instance.rollback = AsyncMock()
    mock_session_instance.flush = AsyncMock()

    # Mock session.begin() to be an async context manager itself
    async_transaction_context_manager = AsyncMock()
    async_transaction_context_manager.__aenter__.return_value = mock_session_instance # Yields the session
    async_transaction_context_manager.__aexit__ = AsyncMock(return_value=None)
    mock_session_instance.begin = MagicMock(return_value=async_transaction_context_manager)
    mock_session_instance.begin_nested = MagicMock(return_value=async_transaction_context_manager) # for when session is passed in

    async_session_context_manager_outer = AsyncMock()
    async_session_context_manager_outer.__aenter__.return_value = mock_session_instance
    async_session_context_manager_outer.__aexit__ = AsyncMock(return_value=None)
    service.get_session.return_value = async_session_context_manager_outer
    return service

@pytest.fixture
def mock_character_manager_for_status():
    manager = AsyncMock(spec=CharacterManager)
    manager._recalculate_and_store_effective_stats = AsyncMock()
    # Mock _game_log_manager as an attribute of CharacterManager instance
    manager._game_log_manager = AsyncMock(spec=GameLogManager)
    return manager

@pytest.fixture
def mock_rule_engine_for_status():
    engine = AsyncMock(spec=RuleEngine)
    # Setup rules_config_data and its status_effects attribute
    engine.rules_config_data = CoreGameRulesConfig(status_effects={
        "poisoned": StatusEffectDefinition(id="poisoned", name_i18n={"en": "Poisoned"}, description_i18n={"en": "Taking damage over time."}, default_duration_turns=3, effects=[]),
        "blessed": StatusEffectDefinition(id="blessed", name_i18n={"en": "Blessed"}, description_i18n={"en": "Positive aura."}, default_duration_turns=5, effects=[])
    })
    return engine

@pytest.fixture
def mock_time_manager_for_status():
    manager = AsyncMock(spec=TimeManager)
    manager.get_current_turn.return_value = 100 # Example current turn
    return manager

@pytest.fixture
def status_manager(
    mock_db_service_for_status: DBService,
    mock_character_manager_for_status: CharacterManager,
    mock_rule_engine_for_status: RuleEngine,
    mock_time_manager_for_status: TimeManager
) -> StatusManager:
    # Ensure settings are passed, even if empty, to avoid NoneType errors if accessed
    sm = StatusManager(
        db_service=mock_db_service_for_status,
        settings={},
        rule_engine=mock_rule_engine_for_status,
        time_manager=mock_time_manager_for_status,
        character_manager=mock_character_manager_for_status,
        # npc_manager, combat_manager, party_manager can be default None if not used by apply_status
    )
    # Call _load_status_templates manually if it relies on rule_engine being fully set up
    # or if rules_config_data is populated after StatusManager init in a real scenario.
    # Here, rule_engine mock has rules_config_data at init time.
    sm._load_status_templates() # Ensure templates are loaded from the mocked rule_engine
    return sm

@pytest.fixture
def mock_character_db_instance() -> CharacterDbModel:
    char = MagicMock(spec=CharacterDbModel)
    char.id = "char_status_target_1"
    char.guild_id = "guild_status_test"
    char.player_id = "player_for_char_status_1"
    char.current_location_id = "loc_char_status"
    char.status_effects_json = [] # Start with no statuses
    return char

@pytest.fixture
def mock_player_db_instance() -> PlayerDbModel:
    player = MagicMock(spec=PlayerDbModel)
    player.id = "player_for_char_status_1"
    player.selected_language = "en"
    return player

# --- Tests for StatusManager.apply_status_to_character ---

@pytest.mark.asyncio
@patch('bot.game.managers.status_manager.flag_modified') # Patch where it's used
async def test_apply_status_success_new_status(
    mock_flag_modified: MagicMock,
    status_manager: StatusManager,
    mock_character_db_instance: CharacterDbModel,
    mock_player_db_instance: PlayerDbModel,
    mock_db_service_for_status: DBService # To access the session mock
):
    guild_id = mock_character_db_instance.guild_id
    char_id = mock_character_db_instance.id
    status_key = "poisoned"
    duration = 3
    source_id = "goblin_shaman"
    source_type = "NPC"

    mock_session = mock_db_service_for_status.get_session.return_value.__aenter__.return_value
    mock_session.get.side_effect = [mock_character_db_instance, mock_player_db_instance] # First get Character, then Player

    result = await status_manager.apply_status_to_character(
        guild_id, char_id, status_key, duration_turns=duration,
        source_id=source_id, source_type=source_type, session=mock_session
    )

    assert result.applied is True
    assert result.status_key == status_key
    assert result.status_name == "Poisoned" # From mock_rule_engine template
    assert result.duration_turns == duration
    assert result.instance_id is not None

    assert len(mock_character_db_instance.status_effects_json) == 1
    applied_effect = mock_character_db_instance.status_effects_json[0]
    assert applied_effect["status_id"] == status_key
    assert applied_effect["duration_turns"] == duration
    assert applied_effect["applied_at_turn"] == 100 # From mock_time_manager
    assert applied_effect["source_id"] == source_id
    assert applied_effect["instance_id"] == result.instance_id

    mock_flag_modified.assert_called_once_with(mock_character_db_instance, "status_effects_json")
    mock_session.add.assert_called_with(mock_character_db_instance)

    status_manager._character_manager._recalculate_and_store_effective_stats.assert_awaited_once_with(
        guild_id, char_id, char_model=mock_character_db_instance, session_for_db=mock_session
    )
    status_manager._character_manager._game_log_manager.log_event.assert_awaited_once()
    log_args = status_manager._character_manager._game_log_manager.log_event.call_args.kwargs
    assert log_args['guild_id'] == guild_id
    assert log_args['event_type'] == "STATUS_APPLIED"
    assert log_args['details']['status_id'] == status_key

    # Check that the passed session's transaction context was used (begin_nested)
    # and commit was NOT called by apply_status itself
    mock_session.begin_nested.assert_called_once()
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_apply_status_character_not_found(status_manager: StatusManager, mock_db_service_for_status: DBService):
    guild_id = "guild_char_not_found"
    char_id = "unknown_char"

    mock_session = mock_db_service_for_status.get_session.return_value.__aenter__.return_value
    mock_session.get.return_value = None # Character not found

    result = await status_manager.apply_status_to_character(guild_id, char_id, "poisoned", session=mock_session)

    assert result.applied is False
    assert "not found" in result.message.lower()
    status_manager._character_manager._recalculate_and_store_effective_stats.assert_not_awaited()

@pytest.mark.asyncio
async def test_apply_status_definition_not_found(status_manager: StatusManager, mock_character_db_instance: CharacterDbModel, mock_db_service_for_status: DBService):
    guild_id = mock_character_db_instance.guild_id
    char_id = mock_character_db_instance.id

    mock_session = mock_db_service_for_status.get_session.return_value.__aenter__.return_value
    mock_session.get.return_value = mock_character_db_instance # Character found

    result = await status_manager.apply_status_to_character(guild_id, char_id, "unknown_status_effect", session=mock_session)

    assert result.applied is False
    assert "definition for 'unknown_status_effect' not found" in result.message.lower()


@pytest.mark.asyncio
@patch('bot.game.managers.status_manager.flag_modified')
async def test_apply_status_uses_own_session_if_none_provided(
    mock_flag_modified: MagicMock,
    status_manager: StatusManager,
    mock_character_db_instance: CharacterDbModel,
    mock_player_db_instance: PlayerDbModel,
    mock_db_service_for_status: DBService # To access the session mock
):
    guild_id = mock_character_db_instance.guild_id
    char_id = mock_character_db_instance.id
    status_key = "blessed"

    # get_session returns a context manager that yields mock_session_instance
    mock_session_instance = mock_db_service_for_status.get_session.return_value.__aenter__.return_value
    mock_session_instance.get.side_effect = [mock_character_db_instance, mock_player_db_instance]

    # Act: Call without providing a session
    result = await status_manager.apply_status_to_character(guild_id, char_id, status_key)

    assert result.applied is True
    # Check that the session created by StatusManager itself was used and committed
    mock_db_service_for_status.get_session.assert_called_once() # Called to create a session

    # The session instance's begin() should have been called by the context manager from get_session()
    mock_session_instance.begin.assert_called_once()
    # Commit should be called by the __aexit__ of that context manager if no error
    # This is hard to test directly without deeper mocking of the context manager returned by get_session.
    # However, if flag_modified and add were called, and no exception, it implies commit path was taken.
    mock_flag_modified.assert_called_once()
    mock_session_instance.add.assert_called_once()

    # To be more precise, mock the __aexit__ of the context manager returned by get_session
    # to check if it was called without an exception type, implying commit.
    # For now, assume successful flow leads to commit if no error.

print("DEBUG: tests/game/managers/test_status_manager.py created.")
