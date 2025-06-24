import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel # For local ItemDefinition
from typing import Dict, Any, Optional, List # For local ItemDefinition

from bot.game.managers.item_manager import ItemManager
from bot.database.models import Item as SQLAlchemyItem
# ItemDefinition will be defined locally for this test file
from bot.ai.rules_schema import CoreGameRulesConfig # Only need CoreGameRulesConfig for the spec
from sqlalchemy.ext.asyncio import AsyncSession # For type hinting mock_session

# Local Pydantic model for ItemDefinition, as it's not in rules_schema.py
class ItemDefinition(BaseModel):
    name_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    item_type: str
    base_value: int
    properties: Optional[Dict[str, Any]] = None
    equipable_slot_id: Optional[str] = None
    # Add any other fields that ItemManager.get_item_template is expected to return

# Mock item templates data
MOCK_ITEM_TEMPLATES = {
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
}

@pytest.fixture
def mock_rule_engine():
    # CoreGameRulesConfig might not be the place for item_definitions.
    # The ItemManager's get_item_template method is what needs mocking/patching.
    # This fixture can still provide a mock CoreGameRulesConfig if other parts of ItemManager use it.
    mock = MagicMock(spec=CoreGameRulesConfig)
    # Simulate that CoreGameRulesConfig might have some item related rules, but not full definitions.
    mock.item_effects = {}
    mock.status_effects = {}
    mock.equipment_slots = {}
    # Ensure all required fields for CoreGameRulesConfig if its constructor is called by ItemManager
    # For this test, the actual content of CoreGameRulesConfig might not be critical if we patch get_item_template.
    return mock

@pytest.fixture
def item_manager_fixture(mock_rule_engine: MagicMock):
    mock_settings = {"item_templates": {}} # ItemManager might use this for initial load

    # Create an instance of the real ItemManager
    manager = ItemManager(rule_engine=mock_rule_engine, settings=mock_settings)

    # Patch the get_item_template method of this instance
    def mock_get_item_template(template_id: str):
        template = MOCK_ITEM_TEMPLATES.get(template_id)
        return template.model_dump() if template else None # Return as dict, like templates might be stored

    manager.get_item_template = MagicMock(side_effect=mock_get_item_template)
    return manager


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

