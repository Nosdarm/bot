import pytest
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, List, Optional # Added List, Optional

from bot.game.managers.status_manager import StatusManager, ApplyStatusResult
from bot.database.models.character import Character as CharacterDbModel # Corrected import path
from bot.database.models.player import Player as PlayerDbModel # Corrected import path
from bot.services.db_service import DBService
from bot.game.managers.character_manager import CharacterManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.ai.rules_schema import CoreGameRulesConfig, StatusEffectDefinition

# --- Fixtures ---

@pytest.fixture
def mock_db_service_for_status() -> DBService: # Added return type
    service = AsyncMock(spec=DBService)
    mock_session_instance = AsyncMock(name="MockSessionForStatus", spec=AsyncSession) # Added spec
    mock_session_instance.get = AsyncMock()
    mock_session_instance.add = MagicMock()
    mock_session_instance.commit = AsyncMock()
    mock_session_instance.rollback = AsyncMock()
    mock_session_instance.flush = AsyncMock()

    async_transaction_context_manager = AsyncMock()
    async_transaction_context_manager.__aenter__.return_value = mock_session_instance
    async_transaction_context_manager.__aexit__ = AsyncMock(return_value=None)
    mock_session_instance.begin = MagicMock(return_value=async_transaction_context_manager)
    mock_session_instance.begin_nested = MagicMock(return_value=async_transaction_context_manager)

    async_session_context_manager_outer = AsyncMock()
    async_session_context_manager_outer.__aenter__.return_value = mock_session_instance
    async_session_context_manager_outer.__aexit__ = AsyncMock(return_value=None)
    service.get_session = MagicMock(return_value=async_session_context_manager_outer) # Use MagicMock for get_session
    return service

@pytest.fixture
def mock_character_manager_for_status() -> CharacterManager: # Added return type
    manager = AsyncMock(spec=CharacterManager)
    manager._recalculate_and_store_effective_stats = AsyncMock()
    manager._game_log_manager = AsyncMock(spec=GameLogManager)
    return manager

@pytest.fixture
def mock_rule_engine_for_status() -> RuleEngine: # Added return type
    engine = AsyncMock(spec=RuleEngine)
    # Ensure CoreGameRulesConfig is initialized with all required fields or use MagicMock if complex
    mock_xp_rules = MagicMock() # Example if XPRules is complex
    engine.rules_config_data = CoreGameRulesConfig(
        status_effects={
            "poisoned": StatusEffectDefinition(id="poisoned", name_i18n={"en": "Poisoned"}, description_i18n={"en": "Taking damage over time."}, default_duration_turns=3, effects=[]), # Added type to effects
            "blessed": StatusEffectDefinition(id="blessed", name_i18n={"en": "Blessed"}, description_i18n={"en": "Positive aura."}, default_duration_turns=5, effects=[]) # Added type to effects
        },
        checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
        action_conflicts=[], location_interactions={}, base_stats={},
        equipment_slots={}, item_effects={}, relation_rules=[], relationship_influence_rules=[]
    )
    return engine

@pytest.fixture
def mock_time_manager_for_status() -> TimeManager: # Added return type
    manager = AsyncMock(spec=TimeManager)
    manager.get_current_turn = MagicMock(return_value=100) # Made get_current_turn MagicMock as it's sync
    return manager

@pytest.fixture
def status_manager(
    mock_db_service_for_status: DBService,
    mock_character_manager_for_status: CharacterManager,
    mock_rule_engine_for_status: RuleEngine,
    mock_time_manager_for_status: TimeManager
) -> StatusManager:
    sm = StatusManager(
        db_service=mock_db_service_for_status,
        settings={},
        rule_engine=mock_rule_engine_for_status,
        time_manager=mock_time_manager_for_status,
        character_manager=mock_character_manager_for_status,
    )
    sm._load_status_templates()
    return sm

@pytest.fixture
def mock_character_db_instance() -> CharacterDbModel:
    char = MagicMock(spec=CharacterDbModel)
    char.id = "char_status_target_1"
    char.guild_id = "guild_status_test"
    char.player_id = "player_for_char_status_1"
    char.current_location_id = "loc_char_status"
    char.status_effects_json = json.dumps([]) # Ensure it's a JSON string
    return char

@pytest.fixture
def mock_player_db_instance() -> PlayerDbModel:
    player = MagicMock(spec=PlayerDbModel)
    player.id = "player_for_char_status_1"
    player.selected_language = "en"
    return player

# --- Tests for StatusManager.apply_status_to_character ---

@pytest.mark.asyncio
@patch('bot.game.managers.status_manager.flag_modified')
async def test_apply_status_success_new_status(
    mock_flag_modified: MagicMock,
    status_manager: StatusManager,
    mock_character_db_instance: CharacterDbModel,
    mock_player_db_instance: PlayerDbModel,
    mock_db_service_for_status: DBService
):
    guild_id = str(mock_character_db_instance.guild_id) # Ensure string
    char_id = str(mock_character_db_instance.id) # Ensure string
    status_key = "poisoned"
    duration = 3
    source_id = "goblin_shaman"
    source_type = "NPC"

    mock_session = await mock_db_service_for_status.get_session().__aenter__() # Get the session instance
    mock_session.get.side_effect = [mock_character_db_instance, mock_player_db_instance]

    result = await status_manager.apply_status_to_character(
        guild_id, char_id, status_key, duration_turns=duration,
        source_id=source_id, source_type=source_type, session=mock_session
    )

    assert result.applied is True
    assert result.status_key == status_key
    assert result.status_name == "Poisoned"
    assert result.duration_turns == duration
    assert result.instance_id is not None

    # status_effects_json is a string, parse it
    status_effects_list = json.loads(str(mock_character_db_instance.status_effects_json))
    assert len(status_effects_list) == 1
    applied_effect = status_effects_list[0]
    assert applied_effect["status_id"] == status_key
    assert applied_effect["duration_turns"] == duration
    assert applied_effect["applied_at_turn"] == 100
    assert applied_effect["source_id"] == source_id
    assert applied_effect["instance_id"] == result.instance_id

    mock_flag_modified.assert_called_once_with(mock_character_db_instance, "status_effects_json")
    mock_session.add.assert_called_with(mock_character_db_instance)

    assert status_manager._character_manager is not None # Ensure manager is not None
    cast(AsyncMock, status_manager._character_manager._recalculate_and_store_effective_stats).assert_awaited_once_with(
        guild_id, char_id, char_model=mock_character_db_instance, session_for_db=mock_session
    )
    assert status_manager._character_manager._game_log_manager is not None # Ensure manager is not None
    cast(AsyncMock, status_manager._character_manager._game_log_manager.log_event).assert_awaited_once()

    log_args_list = cast(AsyncMock, status_manager._character_manager._game_log_manager.log_event).call_args_list
    assert len(log_args_list) > 0
    log_args = log_args_list[0].kwargs # Use the first call's kwargs

    assert log_args['guild_id'] == guild_id
    assert log_args['event_type'] == "STATUS_APPLIED"
    assert log_args['details']['status_id'] == status_key

    mock_session.begin_nested.assert_called_once()
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_apply_status_character_not_found(status_manager: StatusManager, mock_db_service_for_status: DBService):
    guild_id = "guild_char_not_found"
    char_id = "unknown_char"

    mock_session = await mock_db_service_for_status.get_session().__aenter__()
    mock_session.get.return_value = None

    result = await status_manager.apply_status_to_character(guild_id, char_id, "poisoned", session=mock_session)

    assert result.applied is False
    assert result.message is not None and "not found" in result.message.lower()
    assert status_manager._character_manager is not None
    cast(AsyncMock, status_manager._character_manager._recalculate_and_store_effective_stats).assert_not_awaited()

@pytest.mark.asyncio
async def test_apply_status_definition_not_found(status_manager: StatusManager, mock_character_db_instance: CharacterDbModel, mock_db_service_for_status: DBService):
    guild_id = str(mock_character_db_instance.guild_id) # Ensure string
    char_id = str(mock_character_db_instance.id) # Ensure string

    mock_session = await mock_db_service_for_status.get_session().__aenter__()
    mock_session.get.return_value = mock_character_db_instance

    result = await status_manager.apply_status_to_character(guild_id, char_id, "unknown_status_effect", session=mock_session)

    assert result.applied is False
    assert result.message is not None and "definition for 'unknown_status_effect' not found" in result.message.lower()


@pytest.mark.asyncio
@patch('bot.game.managers.status_manager.flag_modified')
async def test_apply_status_uses_own_session_if_none_provided(
    mock_flag_modified: MagicMock,
    status_manager: StatusManager,
    mock_character_db_instance: CharacterDbModel,
    mock_player_db_instance: PlayerDbModel,
    mock_db_service_for_status: DBService
):
    guild_id = str(mock_character_db_instance.guild_id) # Ensure string
    char_id = str(mock_character_db_instance.id) # Ensure string
    status_key = "blessed"

    mock_session_instance = await mock_db_service_for_status.get_session().__aenter__()
    mock_session_instance.get.side_effect = [mock_character_db_instance, mock_player_db_instance]

    result = await status_manager.apply_status_to_character(guild_id, char_id, status_key)

    assert result.applied is True
    cast(MagicMock, mock_db_service_for_status.get_session).assert_called_once()

    mock_session_instance.begin.assert_called_once()
    mock_flag_modified.assert_called_once()
    mock_session_instance.add.assert_called_once()

# Removed print statement
