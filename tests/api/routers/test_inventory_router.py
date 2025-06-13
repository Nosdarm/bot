import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4, UUID
from datetime import datetime

from fastapi import HTTPException, status, Response # Added Response for 204 check
from sqlalchemy.exc import IntegrityError

# Modules to test
from bot.api.routers import inventory_router
from bot.api.schemas.inventory_schemas import NewCharacterItemCreate, NewCharacterItemRead, InventoryItemRead
from bot.api.schemas.item_schemas import NewItemRead # For constructing nested item data
from bot.database.models import NewCharacterItem, NewItem, Character as CharacterModel # ORM models

# Common test data
CHAR_ID_1 = "char_test_123"
ITEM_ID_1 = uuid4()
ITEM_ID_2 = uuid4()
CHAR_ITEM_ID_1 = uuid4()
NOW = datetime.utcnow()

@pytest.fixture
def mock_db_session():
    # This can be used if we were mocking db.get directly, but patching get_character_orm is preferred.
    session = AsyncMock()
    # session.get = AsyncMock() # Example if we wanted to mock db.get
    return session

@pytest.fixture
def mock_character_orm():
    return CharacterModel(id=CHAR_ID_1, player_id="player1", guild_id="guild1", name_i18n={"en": "Test Character"})

@pytest.fixture
def mock_item_orm_1():
    return NewItem(id=ITEM_ID_1, name="Test Item 1", item_type="consumable", item_metadata={"effect": "heal"}, created_at=NOW, updated_at=NOW)

@pytest.fixture
def mock_item_orm_2():
    return NewItem(id=ITEM_ID_2, name="Test Item 2", item_type="weapon", item_metadata={"damage": "1d6"}, created_at=NOW, updated_at=NOW)

# --- Tests for get_character_inventory_endpoint ---
@pytest.mark.asyncio
async def test_get_character_inventory_success(mock_db_session, mock_character_orm, mock_item_orm_1, mocker):
    mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=mock_character_orm)

    mock_char_items_orm = [
        NewCharacterItem(id=CHAR_ITEM_ID_1, character_id=CHAR_ID_1, item_id=ITEM_ID_1, quantity=5, created_at=NOW, updated_at=NOW, item=mock_item_orm_1)
    ]
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.get_character_inventory', return_value=mock_char_items_orm)

    result = await inventory_router.get_character_inventory_endpoint(character_id=CHAR_ID_1, db=mock_db_session)

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], InventoryItemRead)
    assert result[0].item.id == ITEM_ID_1
    assert result[0].item.name == "Test Item 1"
    assert result[0].quantity == 5
    inventory_router.get_character_orm.assert_called_once_with(mock_db_session, CHAR_ID_1)
    inventory_router.inventory_crud.get_character_inventory.assert_called_once_with(db=mock_db_session, character_id=CHAR_ID_1)

@pytest.mark.asyncio
async def test_get_character_inventory_char_not_found(mock_db_session, mocker):
    mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=None)
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.get_character_inventory') # To avoid it being called

    with pytest.raises(HTTPException) as exc_info:
        await inventory_router.get_character_inventory_endpoint(character_id=CHAR_ID_1, db=mock_db_session)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Character not found" in exc_info.value.detail
    inventory_router.inventory_crud.get_character_inventory.assert_not_called()

# --- Tests for add_item_to_inventory_endpoint ---
@pytest.mark.asyncio
async def test_add_item_to_inventory_success(mock_db_session, mock_item_orm_1, mocker):
    item_add_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=2)

    mock_added_char_item = NewCharacterItem(
        id=CHAR_ITEM_ID_1, character_id=CHAR_ID_1, item_id=ITEM_ID_1, quantity=2,
        created_at=NOW, updated_at=NOW, item=mock_item_orm_1 # item should be populated by CRUD
    )
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.add_item_to_character_inventory', return_value=mock_added_char_item)

    result = await inventory_router.add_item_to_inventory_endpoint(character_id=CHAR_ID_1, item_add_data=item_add_data, db=mock_db_session)

    assert isinstance(result, NewCharacterItemRead)
    assert result.id == CHAR_ITEM_ID_1
    assert result.item_id == ITEM_ID_1
    assert result.quantity == 2
    assert result.item.name == mock_item_orm_1.name
    inventory_router.inventory_crud.add_item_to_character_inventory.assert_called_once_with(
        db=mock_db_session, character_id=CHAR_ID_1, item_id=ITEM_ID_1, quantity=2
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("error_message, expected_detail, expected_status", [
    ("Character not found", "Character not found", status.HTTP_404_NOT_FOUND),
    ("Item template not found", "Item template not found", status.HTTP_404_NOT_FOUND),
    ("Quantity to add must be positive", "Quantity to add must be positive", status.HTTP_400_BAD_REQUEST),
    ("Some other value error", "Some other value error", status.HTTP_400_BAD_REQUEST),
])
async def test_add_item_to_inventory_value_errors(error_message, expected_detail, expected_status, mock_db_session, mocker):
    item_add_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=1)
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.add_item_to_character_inventory', side_effect=ValueError(error_message))

    with pytest.raises(HTTPException) as exc_info:
        await inventory_router.add_item_to_inventory_endpoint(character_id=CHAR_ID_1, item_add_data=item_add_data, db=mock_db_session)

    assert exc_info.value.status_code == expected_status
    assert expected_detail in exc_info.value.detail

# --- Tests for remove_item_from_inventory_endpoint ---
@pytest.mark.asyncio
async def test_remove_item_from_inventory_partial_remove_success(mock_db_session, mock_item_orm_1, mocker):
    item_remove_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=1) # Schema used for item_id and quantity
    mock_response = AsyncMock(spec=Response) # Mock FastAPI Response for status_code check

    mock_updated_char_item = NewCharacterItem(
        id=CHAR_ITEM_ID_1, character_id=CHAR_ID_1, item_id=ITEM_ID_1, quantity=1, # Remaining quantity
        created_at=NOW, updated_at=NOW, item=mock_item_orm_1
    )
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.remove_item_from_character_inventory', return_value=mock_updated_char_item)

    result = await inventory_router.remove_item_from_inventory_endpoint(
        character_id=CHAR_ID_1, item_remove_data=item_remove_data, db=mock_db_session, response=mock_response
    )

    assert isinstance(result, NewCharacterItemRead)
    assert result.quantity == 1
    inventory_router.inventory_crud.remove_item_from_character_inventory.assert_called_once()
    mock_response.status_code = status.HTTP_200_OK # Default if not set to 204

@pytest.mark.asyncio
async def test_remove_item_from_inventory_full_remove_success(mock_db_session, mocker):
    item_remove_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=5)
    mock_response = AsyncMock(spec=Response)

    mocker.patch('bot.api.routers.inventory_router.inventory_crud.remove_item_from_character_inventory', return_value=None)

    result = await inventory_router.remove_item_from_inventory_endpoint(
        character_id=CHAR_ID_1, item_remove_data=item_remove_data, db=mock_db_session, response=mock_response
    )

    assert result is None
    inventory_router.inventory_crud.remove_item_from_character_inventory.assert_called_once()
    # Check if response.status_code was set to 204 by the endpoint
    assert mock_response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
@pytest.mark.parametrize("error_message, expected_detail, expected_status", [
    ("Item not found in character's inventory", "Item not found in inventory", status.HTTP_404_NOT_FOUND),
    ("Cannot remove more items than available", "Insufficient quantity to remove", status.HTTP_400_BAD_REQUEST),
    ("Quantity to remove must be positive", "Quantity to remove must be positive", status.HTTP_400_BAD_REQUEST),
    ("Some other value error for remove", "Some other value error for remove", status.HTTP_400_BAD_REQUEST),
    # Note: "Character not found" is usually handled by a direct check or by the CRUD if it implies non-existence of inventory.
    # If remove_item_from_character_inventory itself raises "Character not found", it would be caught here.
])
async def test_remove_item_from_inventory_value_errors(error_message, expected_detail, expected_status, mock_db_session, mocker):
    item_remove_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=1)
    mock_response = AsyncMock(spec=Response)
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.remove_item_from_character_inventory', side_effect=ValueError(error_message))

    with pytest.raises(HTTPException) as exc_info:
        await inventory_router.remove_item_from_inventory_endpoint(
            character_id=CHAR_ID_1, item_remove_data=item_remove_data, db=mock_db_session, response=mock_response
        )

    assert exc_info.value.status_code == expected_status
    assert expected_detail in exc_info.value.detail
