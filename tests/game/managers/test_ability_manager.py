import uuid
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Models and Services to test/mock
from bot.game.managers.ability_manager import AbilityManager
from bot.game.models.ability import Ability as AbilityPydanticModel
from bot.database.models import Ability as AbilityDbModel

from bot.services.db_service import DBService
from bot.game.managers.character_manager import CharacterManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.models.character import Character as CharacterPydanticModel # Pydantic model for character


@pytest.fixture
def mock_db_service():
    service = AsyncMock(spec=DBService)
    service.get_session = AsyncMock() # This will be the context manager
    # Mock the __aenter__ and __aexit__ for the context manager
    mock_session_instance = AsyncMock(name="MockSession")
    mock_session_instance.execute = AsyncMock()
    mock_session_instance.scalars = MagicMock() # Needs to be sync for .first() / .all()

    # Configure get_session to return an async context manager that yields mock_session_instance
    async_context_manager = AsyncMock()
    async_context_manager.__aenter__.return_value = mock_session_instance
    async_context_manager.__aexit__.return_value = None # Or AsyncMock(return_value=None) if it's awaitable
    service.get_session.return_value = async_context_manager

    return service

@pytest.fixture
def mock_character_manager():
    manager = AsyncMock(spec=CharacterManager)
    manager.get_character = AsyncMock()
    manager.mark_character_dirty = AsyncMock()
    # Mock _game_log_manager attribute if activate_ability accesses it via character_manager
    manager._game_log_manager = AsyncMock(spec=GameLogManager)
    manager._game_log_manager.log_event = AsyncMock()
    return manager

@pytest.fixture
def mock_rule_engine():
    engine = AsyncMock(spec=RuleEngine)
    engine.check_ability_learning_requirements = AsyncMock()
    engine.process_ability_effects = AsyncMock()
    return engine

@pytest.fixture
def mock_status_manager():
    return AsyncMock(spec=StatusManager)

@pytest.fixture
def ability_manager(
    mock_character_manager: CharacterManager,
    mock_rule_engine: RuleEngine,
    mock_status_manager: StatusManager,
    mock_db_service: DBService
) -> AbilityManager:
    return AbilityManager(
        settings={},
        character_manager=mock_character_manager,
        rule_engine=mock_rule_engine,
        status_manager=mock_status_manager,
        db_service=mock_db_service
    )

@pytest.fixture
def sample_ability_pydantic() -> AbilityPydanticModel:
    return AbilityPydanticModel(
        id="ab_fireball",
        static_id="fireball_spell",
        name_i18n={"en": "Fireball", "ru": "Огненный Шар"},
        description_i18n={"en": "Hurls a fiery orb.", "ru": "Мечет огненный шар."},
        effect_i18n={"en": "Deals fire damage.", "ru": "Наносит урон огнем."},
        cost={"stamina": 10},
        requirements={},
        type="activated_spell_damage", # Example activatable type
        cooldown=5.0 # 5 second cooldown
    )

@pytest.fixture
def sample_character_pydantic(sample_ability_pydantic: AbilityPydanticModel) -> CharacterPydanticModel:
    return CharacterPydanticModel(
        id="char_mage_1",
        player_id="player1",
        guild_id="guild_ab_test",
        name_i18n={"en": "Test Mage"},
        stats={"stamina": 50},
        known_abilities=[sample_ability_pydantic.id], # Knows the ability
        ability_cooldowns={} # No cooldowns initially
    )

# --- Tests for load_ability_templates ---
@pytest.mark.asyncio
async def test_load_ability_templates_success(ability_manager: AbilityManager):
    guild_id = "g1"
    campaign_data = {
        "ability_templates": [
            {"id": "ab1", "static_id": "strike", "name_i18n": {"en": "Strike"}, "description_i18n": {"en":"A basic strike"}, "effect_i18n": {"en":"Deals damage"}, "type":"activated_attack"},
            {"id": "ab2", "static_id": "heal", "name_i18n": {"en": "Heal"}, "description_i18n": {"en":"Heals target"}, "effect_i18n": {"en":"Restores HP"}, "type":"activated_utility_heal"}
        ]
    }
    await ability_manager.load_ability_templates(guild_id, campaign_data)
    assert len(ability_manager._ability_templates[guild_id]) == 2
    assert "ab1" in ability_manager._ability_templates[guild_id]
    assert ability_manager._ability_templates[guild_id]["ab1"].name_i18n["en"] == "Strike"

# --- Tests for get_ability ---
@pytest.mark.asyncio
async def test_get_ability_from_cache_by_id(ability_manager: AbilityManager, sample_ability_pydantic: AbilityPydanticModel):
    guild_id = "g_cache"
    ability_manager._ability_templates[guild_id] = {sample_ability_pydantic.id: sample_ability_pydantic}

    fetched_ability = await ability_manager.get_ability(guild_id, sample_ability_pydantic.id)
    assert fetched_ability == sample_ability_pydantic
    ability_manager._db_service.get_session.assert_not_called() # Should not hit DB

@pytest.mark.asyncio
async def test_get_ability_from_db_by_static_id(ability_manager: AbilityManager, mock_db_service: AsyncMock, sample_ability_pydantic: AbilityPydanticModel):
    guild_id = "g_db_static"
    static_id_to_find = "fireball_spell_db"

    mock_db_ability = AbilityDbModel(
        id=str(uuid.uuid4()), static_id=static_id_to_find, guild_id=guild_id,
        name_i18n={"en": "DB Fireball"}, description_i18n={"en":"Desc"}, effect_i18n={"en":"Effect"}, type_i18n={"en":"spell"}
    )
    # Mock DB response for static_id query
    mock_session = mock_db_service.get_session.return_value.__aenter__.return_value
    mock_session.execute.return_value.scalars.return_value.first.side_effect = [
        None, # First call (by ID) returns None
        mock_db_ability # Second call (by static_id) returns the DB model
    ]

    fetched_ability = await ability_manager.get_ability(guild_id, static_id_to_find)

    assert fetched_ability is not None
    assert fetched_ability.static_id == static_id_to_find
    assert fetched_ability.name_i18n["en"] == "DB Fireball"
    assert mock_session.execute.call_count == 2 # Called for ID, then for static_id
    # Check if it's added to cache
    assert ability_manager._ability_templates[guild_id][fetched_ability.id] == fetched_ability


# --- Tests for learn_ability ---
@pytest.mark.asyncio
async def test_learn_ability_success(
    ability_manager: AbilityManager,
    mock_character_manager: AsyncMock,
    mock_rule_engine: AsyncMock,
    sample_character_pydantic: CharacterPydanticModel,
    sample_ability_pydantic: AbilityPydanticModel
):
    guild_id = sample_character_pydantic.guild_id
    char_id = sample_character_pydantic.id
    ability_id = sample_ability_pydantic.id

    sample_character_pydantic.known_abilities = [] # Ensure char doesn't know it yet
    mock_character_manager.get_character.return_value = sample_character_pydantic
    # get_ability will be called; ensure it returns the sample ability
    ability_manager.get_ability = AsyncMock(return_value=sample_ability_pydantic)
    mock_rule_engine.check_ability_learning_requirements.return_value = (True, "Can learn")

    success = await ability_manager.learn_ability(guild_id, char_id, ability_id)

    assert success is True
    assert ability_id in sample_character_pydantic.known_abilities
    mock_character_manager.mark_character_dirty.assert_awaited_once_with(guild_id, char_id)

# --- Tests for activate_ability ---
@pytest.mark.asyncio
async def test_activate_ability_success(
    ability_manager: AbilityManager,
    mock_character_manager: AsyncMock,
    mock_rule_engine: AsyncMock,
    sample_character_pydantic: CharacterPydanticModel,
    sample_ability_pydantic: AbilityPydanticModel
):
    guild_id = sample_character_pydantic.guild_id
    char_id = sample_character_pydantic.id
    ability_id = sample_ability_pydantic.id

    mock_character_manager.get_character.return_value = sample_character_pydantic
    ability_manager.get_ability = AsyncMock(return_value=sample_ability_pydantic)
    mock_rule_engine.process_ability_effects.return_value = {"damage_done": 10}

    initial_stamina = sample_character_pydantic.stats["stamina"]
    cost_stamina = sample_ability_pydantic.cost["stamina"]

    result = await ability_manager.activate_ability(guild_id, char_id, ability_id)

    assert result["success"] is True
    assert result["outcomes"] == {"damage_done": 10}
    assert sample_character_pydantic.stats["stamina"] == initial_stamina - cost_stamina
    assert ability_id in sample_character_pydantic.ability_cooldowns
    assert sample_character_pydantic.ability_cooldowns[ability_id] > time.time() # Cooldown is set

    mock_character_manager.mark_character_dirty.assert_any_call(guild_id, char_id) # Called for resource and cooldown
    mock_rule_engine.process_ability_effects.assert_awaited_once_with(
        caster=sample_character_pydantic, ability=sample_ability_pydantic, target_entity=None, guild_id=guild_id
    )
    mock_character_manager._game_log_manager.log_event.assert_awaited_once() # Check logging

@pytest.mark.asyncio
async def test_activate_ability_on_cooldown(
    ability_manager: AbilityManager,
    mock_character_manager: AsyncMock,
    sample_character_pydantic: CharacterPydanticModel,
    sample_ability_pydantic: AbilityPydanticModel
):
    guild_id = sample_character_pydantic.guild_id
    char_id = sample_character_pydantic.id
    ability_id = sample_ability_pydantic.id

    sample_character_pydantic.ability_cooldowns = {ability_id: time.time() + 30} # On cooldown
    mock_character_manager.get_character.return_value = sample_character_pydantic
    ability_manager.get_ability = AsyncMock(return_value=sample_ability_pydantic)

    result = await ability_manager.activate_ability(guild_id, char_id, ability_id)

    assert result["success"] is False
    assert "on cooldown" in result["message"]
    ability_manager._rule_engine.process_ability_effects.assert_not_awaited()

@pytest.mark.asyncio
async def test_activate_ability_insufficient_resources(
    ability_manager: AbilityManager,
    mock_character_manager: AsyncMock,
    sample_character_pydantic: CharacterPydanticModel,
    sample_ability_pydantic: AbilityPydanticModel
):
    guild_id = sample_character_pydantic.guild_id
    char_id = sample_character_pydantic.id
    ability_id = sample_ability_pydantic.id

    sample_character_pydantic.stats["stamina"] = 5 # Less than cost of 10
    mock_character_manager.get_character.return_value = sample_character_pydantic
    ability_manager.get_ability = AsyncMock(return_value=sample_ability_pydantic)

    result = await ability_manager.activate_ability(guild_id, char_id, ability_id)

    assert result["success"] is False
    assert "Not enough stamina" in result["message"]
    ability_manager._rule_engine.process_ability_effects.assert_not_awaited()

print("DEBUG: tests/game/managers/test_ability_manager.py created.")
