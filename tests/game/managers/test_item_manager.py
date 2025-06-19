import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game.managers.item_manager import ItemManager
from bot.database.models import Item as SQLAlchemyItem
from bot.ai.rules_schema import CoreGameRulesConfig, ItemDefinition # For mock template data
from sqlalchemy.ext.asyncio import AsyncSession # For type hinting mock_session

@pytest.fixture
def mock_rule_engine():
    mock = MagicMock(spec=CoreGameRulesConfig) # Use spec for stricter mocking
    mock.rules_config_data = CoreGameRulesConfig(
        item_definitions={
            "test_sword": ItemDefinition(
                name_i18n={"en": "Test Sword", "ru": "Тестовый Меч"},
                description_i18n={"en": "A trusty test sword.", "ru": "Надежный тестовый меч."},
                item_type="weapon",
                base_value=10,
                properties={"damage": "1d6 slashing"},
                equipable_slot_id="weapon_hand"
            ),
            "another_item": ItemDefinition(
                name_i18n={"en": "Another Item"},
                description_i18n={"en": "Just another item."},
                item_type="misc",
                base_value=1
            )
        },
        item_effects={},
        status_effects={},
        equipment_slots=[], # Ensure all required fields of CoreGameRulesConfig are present
        character_classes={},
        npc_archetypes={},
        skill_definitions={},
        ability_definitions={},
        faction_definitions={},
        stat_definitions={},
        game_balance={}
    )
    return mock

@pytest.fixture
def item_manager_fixture(mock_rule_engine: MagicMock): # Renamed to avoid conflict
    # ItemManager constructor takes many optional args.
    # _load_item_templates runs on init. Ensure settings mock if it relies on it.
    # For create_item_instance, only rule_engine (for get_item_template) is directly needed from its own methods.
    mock_settings = {"item_templates": {}}
    return ItemManager(rule_engine=mock_rule_engine, settings=mock_settings)


@pytest.mark.asyncio
async def test_create_item_instance_success(item_manager_fixture: ItemManager):
    # Arrange
    guild_id = "test_guild"
    template_id = "test_sword"
    quantity = 2
    location_id = "loc_123"
    owner_id = "owner_456"
    owner_type = "character"
    initial_state = {"custom_effect": "glowing"}
    mock_session = AsyncMock(spec=AsyncSession)

    # Act
    item_instance = await item_manager_fixture.create_item_instance(
        guild_id, template_id,
        owner_id=owner_id, owner_type=owner_type, location_id=location_id,
        quantity=quantity, initial_state=initial_state, session=mock_session
    )

    # Assert
    assert item_instance is not None
    assert isinstance(item_instance, SQLAlchemyItem)
    mock_session.add.assert_called_once_with(item_instance)

    assert item_instance.template_id == template_id
    assert item_instance.guild_id == guild_id
    assert item_instance.location_id == location_id
    assert item_instance.owner_id == owner_id
    assert item_instance.owner_type == owner_type
    assert item_instance.quantity == int(quantity)
    assert item_instance.state_variables == initial_state
    assert item_instance.is_temporary is False

    template_data = item_manager_fixture.get_item_template(template_id)
    assert item_instance.name_i18n == template_data["name_i18n"]
    assert item_instance.description_i18n == template_data["description_i18n"]
    assert item_instance.properties == template_data["properties"]
    assert item_instance.value == template_data["base_value"]

    assert isinstance(item_instance.id, str)

@pytest.mark.asyncio
async def test_create_item_instance_template_not_found(item_manager_fixture: ItemManager):
    # Arrange
    mock_session = AsyncMock(spec=AsyncSession)

    # Act
    item_instance = await item_manager_fixture.create_item_instance(
        "test_guild", "non_existent_template", session=mock_session
    )

    # Assert
    assert item_instance is None
    mock_session.add.assert_not_called()

@pytest.mark.asyncio
async def test_create_item_instance_non_positive_quantity(item_manager_fixture: ItemManager):
    # Arrange
    mock_session = AsyncMock(spec=AsyncSession)

    # Act zero quantity
    item_instance_zero = await item_manager_fixture.create_item_instance(
        "test_guild", "test_sword", quantity=0, session=mock_session
    )
    # Act negative quantity
    item_instance_neg = await item_manager_fixture.create_item_instance(
        "test_guild", "test_sword", quantity=-1, session=mock_session
    )

    # Assert
    assert item_instance_zero is None
    assert item_instance_neg is None
    mock_session.add.assert_not_called()

@pytest.mark.asyncio
async def test_create_item_instance_session_not_provided(item_manager_fixture: ItemManager):
    # Arrange (No session passed)

    # Act
    item_instance = await item_manager_fixture.create_item_instance(
        "test_guild", "test_sword", session=None
    )

    # Assert
    assert item_instance is None
    # (Optional: Check logs for error message, requires log capturing setup for tests)

@pytest.mark.asyncio
async def test_create_item_instance_default_state_and_quantity(item_manager_fixture: ItemManager):
    # Arrange
    guild_id = "test_guild"
    template_id = "another_item"
    mock_session = AsyncMock(spec=AsyncSession)

    # Act (quantity and initial_state are defaulted by method if not passed, though create_item_instance requires them)
    # The create_item_instance method has defaults for quantity and initial_state in its signature.
    item_instance = await item_manager_fixture.create_item_instance(
        guild_id=guild_id, template_id=template_id, session=mock_session
        # quantity, initial_state, owner_id etc. will use defaults from method signature
    )

    # Assert
    assert item_instance is not None
    assert isinstance(item_instance, SQLAlchemyItem)
    mock_session.add.assert_called_once_with(item_instance)

    assert item_instance.quantity == 1 # Default quantity from method signature
    assert item_instance.state_variables == {} # Default initial_state from method signature becomes {}
    assert item_instance.is_temporary is False # Default from method signature

