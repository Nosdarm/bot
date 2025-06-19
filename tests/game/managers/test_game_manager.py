import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.game.managers.game_manager import GameManager
from bot.ai.rules_schema import CoreGameRulesConfig # For spec and mock attribute
from typing import Dict, Optional

# Minimal setup for GameManager for these specific tests
# We primarily need to control game_manager.rule_engine
@pytest.fixture
def mock_rule_engine_fixture():
    return AsyncMock(name="MockRuleEngine")

@pytest.fixture
def game_manager_fixture(mock_rule_engine_fixture: AsyncMock):
    # GameManager constructor takes discord_client and settings.
    # Provide minimal mocks for those if they are accessed during these tests,
    # though for get_location_type_i18n_map, only rule_engine is directly used.
    mock_discord_client = MagicMock()
    mock_settings = {}

    manager = GameManager(discord_client=mock_discord_client, settings=mock_settings)
    manager.rule_engine = mock_rule_engine_fixture
    # Other manager initializations are skipped as they are not relevant for this method's test
    return manager

@pytest.mark.asyncio
async def test_get_location_type_i18n_map_known_key(
    game_manager_fixture: GameManager,
    mock_rule_engine_fixture: AsyncMock
):
    # Arrange
    guild_id = "test_guild"
    type_key = "forest"
    expected_map = {"en": "Forest", "ru": "Лес"}

    mock_rules_config = MagicMock(spec=CoreGameRulesConfig)
    mock_rules_config.location_type_definitions = {type_key: expected_map}

    mock_rule_engine_fixture.get_rules_config = AsyncMock(return_value=mock_rules_config)

    # Act
    result = await game_manager_fixture.get_location_type_i18n_map(guild_id, type_key)

    # Assert
    assert result == expected_map
    mock_rule_engine_fixture.get_rules_config.assert_called_once_with(guild_id)

@pytest.mark.asyncio
async def test_get_location_type_i18n_map_unknown_key(
    game_manager_fixture: GameManager,
    mock_rule_engine_fixture: AsyncMock
):
    # Arrange
    guild_id = "test_guild"
    known_type_key = "forest"
    unknown_type_key = "desert"
    sample_definitions = {known_type_key: {"en": "Forest", "ru": "Лес"}}

    mock_rules_config = MagicMock(spec=CoreGameRulesConfig)
    mock_rules_config.location_type_definitions = sample_definitions

    mock_rule_engine_fixture.get_rules_config = AsyncMock(return_value=mock_rules_config)

    # Act
    result = await game_manager_fixture.get_location_type_i18n_map(guild_id, unknown_type_key)

    # Assert
    assert result is None
    mock_rule_engine_fixture.get_rules_config.assert_called_once_with(guild_id)

@pytest.mark.asyncio
async def test_get_location_type_i18n_map_definitions_missing(
    game_manager_fixture: GameManager,
    mock_rule_engine_fixture: AsyncMock
):
    # Arrange
    guild_id = "test_guild"
    type_key = "forest"

    mock_rules_config = MagicMock(spec=CoreGameRulesConfig)
    mock_rules_config.location_type_definitions = None # Definitions attribute is None

    mock_rule_engine_fixture.get_rules_config = AsyncMock(return_value=mock_rules_config)

    # Act
    result = await game_manager_fixture.get_location_type_i18n_map(guild_id, type_key)

    # Assert
    assert result is None
    mock_rule_engine_fixture.get_rules_config.assert_called_once_with(guild_id)

@pytest.mark.asyncio
async def test_get_location_type_i18n_map_rules_config_not_loaded(
    game_manager_fixture: GameManager,
    mock_rule_engine_fixture: AsyncMock
):
    # Arrange
    guild_id = "test_guild"
    type_key = "forest"

    mock_rule_engine_fixture.get_rules_config = AsyncMock(return_value=None) # Rules config itself is None

    # Act
    result = await game_manager_fixture.get_location_type_i18n_map(guild_id, type_key)

    # Assert
    assert result is None
    mock_rule_engine_fixture.get_rules_config.assert_called_once_with(guild_id)

@pytest.mark.asyncio
async def test_get_location_type_i18n_map_rule_engine_not_available(
    game_manager_fixture: GameManager
):
    # Arrange
    guild_id = "test_guild"
    type_key = "forest"
    game_manager_fixture.rule_engine = None # RuleEngine is not available

    # Act
    result = await game_manager_fixture.get_location_type_i18n_map(guild_id, type_key)

    # Assert
    assert result is None
```
