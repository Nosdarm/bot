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
    # Ensure all fields expected by AbilityPydanticModel are provided,
    # or that they have defaults in the model definition.
    # Based on bot/game/models/ability.py, 'effects' and 'resource_cost' default to empty.
    return AbilityPydanticModel(
        id="ab_fireball",
        static_id="fireball_spell",
        name_i18n={"en": "Fireball", "ru": "Огненный Шар"},
        description_i18n={"en": "Hurls a fiery orb.", "ru": "Мечет огненный шар."},
        # effect_i18n is not a field in AbilityPydanticModel, it uses 'effects' list
        # cost is not a field, it's 'resource_cost'
        resource_cost={"stamina": 10}, # Changed from cost to resource_cost
        requirements={},
        type="activated_spell_damage",
        effects=[{"type": "deal_damage", "damage_type": "fire", "amount": "2d6"}], # Example effect
        cooldown=5.0
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

    sample_character_pydantic.known_abilities = []
    mock_character_manager.get_character.return_value = sample_character_pydantic
    ability_manager.get_ability = AsyncMock(return_value=sample_ability_pydantic) # type: ignore[method-assign]

    # Ensure check_ability_learning_requirements is an AsyncMock if it's awaitable
    # For now, assuming it's synchronous or its mock setup handles async if needed.
    mock_rule_engine.check_ability_learning_requirements.return_value = (True, "Can learn")


    success = await ability_manager.learn_ability(guild_id, char_id, ability_id, discord_user_id=sample_character_pydantic.player_id) # Added discord_user_id

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
    ability_manager.get_ability = AsyncMock(return_value=sample_ability_pydantic) # type: ignore[method-assign]

    # Ensure process_ability_effects is an AsyncMock if it's awaitable
    mock_rule_engine.process_ability_effects = AsyncMock(return_value={"damage_done": 10})


    initial_stamina = sample_character_pydantic.stats["stamina"]
    cost_stamina = sample_ability_pydantic.resource_cost["stamina"] # Corrected from .cost

    result = await ability_manager.activate_ability(guild_id, char_id, ability_id)

    assert result["success"] is True
    assert result["outcomes"] == {"damage_done": 10}

    # Ensure stats is a dict before modification attempt
    char_stats = getattr(sample_character_pydantic, 'stats', None)
    assert isinstance(char_stats, dict), "Character stats should be a dictionary."
    if isinstance(char_stats, dict): # Redundant due to assert but good for type checker
        self.assertEqual(char_stats["stamina"], initial_stamina - cost_stamina)

    char_cooldowns = getattr(sample_character_pydantic, 'ability_cooldowns', None)
    assert isinstance(char_cooldowns, dict), "Character ability_cooldowns should be a dictionary."
    if isinstance(char_cooldowns, dict): # Redundant but good for type checker
        self.assertIn(ability_id, char_cooldowns)
        self.assertGreater(char_cooldowns[ability_id], time.time()) # Cooldown is set


    mock_character_manager.mark_character_dirty.assert_any_call(guild_id, char_id)

    # Ensure process_ability_effects is an AsyncMock before asserting await
    assert isinstance(mock_rule_engine.process_ability_effects, AsyncMock)
    mock_rule_engine.process_ability_effects.assert_awaited_once_with(
        caster=sample_character_pydantic, ability=sample_ability_pydantic, target_entity=None, guild_id=guild_id, context=ANY
    )

    # Ensure _game_log_manager and its log_event are AsyncMocks
    game_log_mock = getattr(mock_character_manager, '_game_log_manager', None)
    assert isinstance(game_log_mock, AsyncMock)
    log_event_mock = getattr(game_log_mock, 'log_event', None)
    assert isinstance(log_event_mock, AsyncMock)
    log_event_mock.assert_awaited_once()

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

    # Ensure ability_cooldowns is a dict before assignment
    setattr(sample_character_pydantic, 'ability_cooldowns', {ability_id: time.time() + 30})

    mock_character_manager.get_character.return_value = sample_character_pydantic
    ability_manager.get_ability = AsyncMock(return_value=sample_ability_pydantic) # type: ignore[method-assign]

    result = await ability_manager.activate_ability(guild_id, char_id, ability_id)

    assert result["success"] is False
    assert "on cooldown" in result["message"]

    # Ensure process_ability_effects is an AsyncMock before asserting not_awaited
    assert isinstance(ability_manager._rule_engine.process_ability_effects, AsyncMock)
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

    # Ensure stats is a dict before modification
    char_stats = getattr(sample_character_pydantic, 'stats', {})
    if not isinstance(char_stats, dict): char_stats = {} # Should not happen with Pydantic model
    char_stats["stamina"] = 5
    setattr(sample_character_pydantic, 'stats', char_stats)

    mock_character_manager.get_character.return_value = sample_character_pydantic
    ability_manager.get_ability = AsyncMock(return_value=sample_ability_pydantic) # type: ignore[method-assign]

    result = await ability_manager.activate_ability(guild_id, char_id, ability_id)

    assert result["success"] is False
    assert "Not enough stamina" in result["message"]

    assert isinstance(ability_manager._rule_engine.process_ability_effects, AsyncMock)
    ability_manager._rule_engine.process_ability_effects.assert_not_awaited()

print("DEBUG: tests/game/managers/test_ability_manager.py created.")
