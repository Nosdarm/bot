import pytest
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch, ANY as UANY # Renamed to avoid conflict with TypingAny
from typing import Dict, Any as TypingAny, List, Optional, cast

from bot.game.managers.status_manager import StatusManager, ApplyStatusResult
from bot.database.models import Character as CharacterDbModel # Corrected import
from bot.database.models import Player as PlayerDbModel # Corrected import
from bot.services.db_service import DBService
from bot.game.managers.character_manager import CharacterManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.ai.rules_schema import CoreGameRulesConfig, StatusEffectDefinition, XPRule, StatModifierRule # Added XPRule, StatModifierRule
from sqlalchemy.ext.asyncio import AsyncSession # Added import

# --- Fixtures ---

@pytest.fixture
def mock_db_service_for_status() -> DBService:
    service = AsyncMock(spec=DBService)
    mock_session_instance = AsyncMock(name="MockSessionForStatus", spec=AsyncSession)
    mock_session_instance.get = AsyncMock()
    mock_session_instance.add = MagicMock()
    mock_session_instance.commit = AsyncMock()
    mock_session_instance.rollback = AsyncMock()
    mock_session_instance.flush = AsyncMock()

    async_transaction_context_manager = AsyncMock()
    async_transaction_context_manager.__aenter__.return_value = mock_session_instance
    async_transaction_context_manager.__aexit__ = AsyncMock(return_value=None)
    # Ensure begin and begin_nested return the async context manager mock
    mock_session_instance.begin = MagicMock(return_value=async_transaction_context_manager)
    mock_session_instance.begin_nested = MagicMock(return_value=async_transaction_context_manager)


    async_session_cm_outer = AsyncMock(name="OuterSessionContextManager")
    async_session_cm_outer.__aenter__.return_value = mock_session_instance
    async_session_cm_outer.__aexit__ = AsyncMock(return_value=None)
    service.get_session = MagicMock(return_value=async_session_cm_outer)
    return service

@pytest.fixture
def mock_character_manager_for_status() -> CharacterManager:
    manager = AsyncMock(spec=CharacterManager)
    # Mock internal methods that StatusManager might call
    manager._recalculate_and_store_effective_stats = AsyncMock(name="_recalculate_and_store_effective_stats_mock")
    manager._game_log_manager = AsyncMock(spec=GameLogManager, name="GameLogManagerOnCharManagerMock")
    manager._game_log_manager.log_event = AsyncMock(name="log_event_on_gamelog_mock") # Ensure log_event is AsyncMock
    return manager

@pytest.fixture
def mock_rule_engine_for_status() -> RuleEngine:
    engine = AsyncMock(spec=RuleEngine)
    # Correctly initialize XPRule with its defined fields
    mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={})

    # Correctly initialize StatusEffectDefinition with its fields
    # Assuming StatModifierRule and GrantedAbilityOrSkill are also simple or can be mocked
    mock_stat_modifier = StatModifierRule(stat_name="hp", bonus_type="flat", value=-1)

    engine.rules_config_data = CoreGameRulesConfig(
        status_effects={
            "poisoned": StatusEffectDefinition(id="poisoned", name_i18n={"en": "Poisoned"}, description_i18n={"en": "Taking damage over time."}, default_duration_turns=3, stat_modifiers=[mock_stat_modifier], grants_abilities_or_skills=[]),
            "blessed": StatusEffectDefinition(id="blessed", name_i18n={"en": "Blessed"}, description_i18n={"en": "Positive aura."}, default_duration_turns=5, stat_modifiers=[], grants_abilities_or_skills=[])
        },
        checks={}, damage_types={}, xp_rules=mock_xp_rules, loot_tables={},
        action_conflicts=[], location_interactions={}, base_stats={},
        equipment_slots={}, item_effects={}, relation_rules=[], relationship_influence_rules=[]
    )
    return engine

@pytest.fixture
def mock_time_manager_for_status() -> TimeManager:
    manager = AsyncMock(spec=TimeManager)
    manager.get_current_turn = MagicMock(return_value=100)
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
    sm._load_status_templates() # This should populate from mock_rule_engine_for_status.rules_config_data
    return sm

@pytest.fixture
def mock_character_db_instance() -> CharacterDbModel:
    char = MagicMock(spec=CharacterDbModel)
    char.id = "char_status_target_1"
    char.guild_id = "guild_status_test"
    char.player_id = "player_for_char_status_1"
    char.current_location_id = "loc_char_status"
    char.status_effects_json = json.dumps([])
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
    guild_id = str(mock_character_db_instance.guild_id)
    char_id = str(mock_character_db_instance.id)
    status_key = "poisoned"
    duration = 3
    source_id = "goblin_shaman"
    source_type = "NPC"

    mock_session = await mock_db_service_for_status.get_session().__aenter__() # type: ignore # __aenter__ is part of AsyncMock
    mock_session.get.side_effect = [mock_character_db_instance, mock_player_db_instance]

    result = await status_manager.apply_status_to_character(
        guild_id, char_id, status_key, duration_turns=duration,
        source_id=source_id, source_type=source_type, session=mock_session
    )

    assert result.applied is True
    assert result.status_key == status_key
    assert result.status_name == "Poisoned" # From mock_rule_engine_for_status
    assert result.duration_turns == duration
    assert result.instance_id is not None

    status_effects_list: List[Dict[str, TypingAny]] = json.loads(cast(str, mock_character_db_instance.status_effects_json))
    assert len(status_effects_list) == 1
    applied_effect = status_effects_list[0]
    assert applied_effect["status_id"] == status_key
    assert applied_effect["duration_turns"] == duration
    assert applied_effect["applied_at_turn"] == 100 # From mock_time_manager_for_status
    assert applied_effect["source_id"] == source_id
    assert applied_effect["instance_id"] == result.instance_id

    mock_flag_modified.assert_called_once_with(mock_character_db_instance, "status_effects_json")
    mock_session.add.assert_called_with(mock_character_db_instance) # type: ignore # add is MagicMock

    assert status_manager._character_manager is not None
    recalc_method = cast(AsyncMock, status_manager._character_manager._recalculate_and_store_effective_stats)
    recalc_method.assert_awaited_once_with(
        guild_id, char_id, char_model=mock_character_db_instance, session_for_db=mock_session
    )

    assert status_manager._character_manager._game_log_manager is not None
    log_event_mock = cast(AsyncMock, status_manager._character_manager._game_log_manager.log_event)
    log_event_mock.assert_awaited_once()

    log_args_list = log_event_mock.call_args_list
    assert len(log_args_list) > 0
    log_args_kwargs = log_args_list[0].kwargs

    assert log_args_kwargs['guild_id'] == guild_id
    assert log_args_kwargs['event_type'] == "STATUS_APPLIED"
    assert log_args_kwargs['details']['status_id'] == status_key

    cast(MagicMock, mock_session.begin_nested).assert_called_once() # begin_nested is MagicMock
    cast(AsyncMock, mock_session.commit).assert_not_called() # commit is AsyncMock

@pytest.mark.asyncio
async def test_apply_status_character_not_found(status_manager: StatusManager, mock_db_service_for_status: DBService):
    guild_id = "guild_char_not_found"
    char_id = "unknown_char"

    mock_session = await mock_db_service_for_status.get_session().__aenter__() # type: ignore
    cast(AsyncMock, mock_session.get).return_value = None # get is AsyncMock

    result = await status_manager.apply_status_to_character(guild_id, char_id, "poisoned", session=mock_session)

    assert result.applied is False
    assert result.message is not None and "not found" in result.message.lower()
    assert status_manager._character_manager is not None
    cast(AsyncMock, status_manager._character_manager._recalculate_and_store_effective_stats).assert_not_awaited()

@pytest.mark.asyncio
async def test_apply_status_definition_not_found(status_manager: StatusManager, mock_character_db_instance: CharacterDbModel, mock_db_service_for_status: DBService):
    guild_id = str(mock_character_db_instance.guild_id)
    char_id = str(mock_character_db_instance.id)

    mock_session = await mock_db_service_for_status.get_session().__aenter__() # type: ignore
    cast(AsyncMock, mock_session.get).return_value = mock_character_db_instance # get is AsyncMock

    result = await status_manager.apply_status_to_character(guild_id, char_id, "unknown_status_effect", session=mock_session)

    assert result.applied is False
    assert result.message is not None
    # Message might be "Status definition for 'unknown_status_effect' not found in RuleEngine."
    assert "definition for 'unknown_status_effect' not found" in result.message.lower()


@pytest.mark.asyncio
@patch('bot.game.managers.status_manager.flag_modified')
async def test_apply_status_uses_own_session_if_none_provided(
    mock_flag_modified: MagicMock,
    status_manager: StatusManager,
    mock_character_db_instance: CharacterDbModel,
    mock_player_db_instance: PlayerDbModel,
    mock_db_service_for_status: DBService # This is the one that provides the session
):
    guild_id = str(mock_character_db_instance.guild_id)
    char_id = str(mock_character_db_instance.id)
    status_key = "blessed"

    # Configure the mock session provided by mock_db_service_for_status
    # when get_session is called by the SUT (status_manager)
    mock_session_instance_from_sut = cast(AsyncMock, await mock_db_service_for_status.get_session().__aenter__()) # type: ignore
    mock_session_instance_from_sut.get.side_effect = [mock_character_db_instance, mock_player_db_instance]

    result = await status_manager.apply_status_to_character(guild_id, char_id, status_key) # session=None

    assert result.applied is True
    cast(MagicMock, mock_db_service_for_status.get_session).assert_called_once() # get_session is MagicMock

    # These assertions are on the session instance that was entered by the SUT
    cast(MagicMock, mock_session_instance_from_sut.begin).assert_called_once()
    mock_flag_modified.assert_called_once()
    cast(MagicMock, mock_session_instance_from_sut.add).assert_called_once()
    # Commit should be called by the SUT's own session management
    cast(AsyncMock, mock_session_instance_from_sut.commit).assert_awaited_once()
