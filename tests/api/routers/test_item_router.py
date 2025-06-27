import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4, UUID
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError # For simulating DB errors
from sqlalchemy.orm import Session # For type hinting db session

# Modules to test
from bot.api.routers import item_router
from bot.api.schemas.item_schemas import NewItemCreate, NewItemRead, NewItemUpdate
from bot.database.models.item_related import NewItem # ORM model for mock returns

# Common test data
ITEM_ID_1 = uuid4()
ITEM_ID_2 = uuid4()
GUILD_ID_EXISTING = "guild_test_123"
NOW = datetime.utcnow()

@pytest.fixture
def mock_db_session() -> MagicMock: # Return type hint
    return AsyncMock(spec=Session)

# --- Tests for create_item_endpoint ---
@pytest.mark.asyncio
async def test_create_item_endpoint_success(mock_db_session: MagicMock, mocker: MagicMock):
    item_create_data = NewItemCreate(name="Great Sword", item_type="weapon", description="A hefty blade.", item_metadata={"damage": "2d6"}, guild_id=GUILD_ID_EXISTING)

    # Expected ORM object returned by CRUD
    mock_orm_item = NewItem(
        id=ITEM_ID_1,
        name=item_create_data.name,
        item_type=item_create_data.item_type,
        description=item_create_data.description,
        item_metadata=item_create_data.item_metadata,
        guild_id=GUILD_ID_EXISTING,
        created_at=NOW,
        updated_at=NOW
    )

    # Patch the CRUD function
    mock_create_new_item = mocker.patch('bot.api.routers.item_router.item_crud.create_new_item', return_value=mock_orm_item)

    result = await item_router.create_item_endpoint(item=item_create_data, db=mock_db_session)

    assert isinstance(result, NewItemRead)
    assert result.id == ITEM_ID_1
    assert result.name == item_create_data.name
    assert result.item_metadata == item_create_data.item_metadata
    assert result.guild_id == GUILD_ID_EXISTING
    mock_create_new_item.assert_called_once_with(db=mock_db_session, item=item_create_data)

@pytest.mark.asyncio
async def test_create_item_endpoint_name_conflict(mock_db_session: MagicMock, mocker: MagicMock):
    item_create_data = NewItemCreate(name="Existing Sword", item_type="weapon", guild_id=GUILD_ID_EXISTING)
    # Simulate IntegrityError for unique constraint violation (guild_id, name)
    # The actual error might be wrapped, so we check the base IntegrityError
    mocker.patch('bot.api.routers.item_router.item_crud.create_new_item', side_effect=IntegrityError("mocked integrity error", params=None, orig=Exception("unique constraint failed")))


    with pytest.raises(HTTPException) as exc_info:
        await item_router.create_item_endpoint(item=item_create_data, db=mock_db_session)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Item with this name already exists" in exc_info.value.detail

# --- Tests for read_items_endpoint ---
@pytest.mark.asyncio
async def test_read_items_endpoint_success(mock_db_session: MagicMock, mocker: MagicMock):
    mock_orm_items = [
        NewItem(id=ITEM_ID_1, name="Sword", item_type="weapon", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW),
        NewItem(id=ITEM_ID_2, name="Shield", item_type="armor", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW),
    ]
    mock_get_new_items = mocker.patch('bot.api.routers.item_router.item_crud.get_new_items', return_value=mock_orm_items)

    result = await item_router.read_items_endpoint(guild_id=GUILD_ID_EXISTING, skip=0, limit=10, db=mock_db_session)

    assert isinstance(result, list)
    assert len(result) == 2
    assert isinstance(result[0], NewItemRead)
    assert result[0].id == ITEM_ID_1
    assert result[0].guild_id == GUILD_ID_EXISTING
    assert result[1].name == "Shield"
    mock_get_new_items.assert_called_once_with(db=mock_db_session, guild_id=GUILD_ID_EXISTING, skip=0, limit=10)

# --- Tests for read_item_endpoint ---
@pytest.mark.asyncio
async def test_read_item_endpoint_success(mock_db_session: MagicMock, mocker: MagicMock):
    mock_orm_item = NewItem(id=ITEM_ID_1, name="Detailed Sword", item_type="weapon", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW)
    mock_get_new_item = mocker.patch('bot.api.routers.item_router.item_crud.get_new_item', return_value=mock_orm_item)

    result = await item_router.read_item_endpoint(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, db=mock_db_session)

    assert isinstance(result, NewItemRead)
    assert result.id == ITEM_ID_1
    assert result.name == "Detailed Sword"
    assert result.guild_id == GUILD_ID_EXISTING
    mock_get_new_item.assert_called_once_with(db=mock_db_session, item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING)

@pytest.mark.asyncio
async def test_read_item_endpoint_not_found(mock_db_session: MagicMock, mocker: MagicMock):
    mocker.patch('bot.api.routers.item_router.item_crud.get_new_item', return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await item_router.read_item_endpoint(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, db=mock_db_session)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Item not found" in exc_info.value.detail

# --- Tests for update_item_endpoint (covers PUT and PATCH due to shared CRUD logic) ---
@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint_func", [item_router.update_item_endpoint, item_router.patch_item_endpoint])
async def test_update_patch_item_endpoint_success(endpoint_func, mock_db_session: MagicMock, mocker: MagicMock):
    item_update_data = NewItemUpdate(name="Renamed Sword", description="Now sharper.")
    mock_updated_orm_item = NewItem(
        id=ITEM_ID_1,
        name="Renamed Sword",
        description="Now sharper.",
        item_type="weapon", # Assuming original type
        guild_id=GUILD_ID_EXISTING,
        created_at=NOW,
        updated_at=datetime.utcnow()
    )
    mock_update_new_item = mocker.patch('bot.api.routers.item_router.item_crud.update_new_item', return_value=mock_updated_orm_item)

    result = await endpoint_func(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, item=item_update_data, db=mock_db_session)

    assert isinstance(result, NewItemRead)
    assert result.id == ITEM_ID_1
    assert result.name == "Renamed Sword"
    assert result.guild_id == GUILD_ID_EXISTING
    mock_update_new_item.assert_called_with(db=mock_db_session, item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, item_update=item_update_data)

@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint_func", [item_router.update_item_endpoint, item_router.patch_item_endpoint])
async def test_update_patch_item_endpoint_not_found(endpoint_func, mock_db_session: MagicMock, mocker: MagicMock):
    item_update_data = NewItemUpdate(name="NonExistent Sword")
    mocker.patch('bot.api.routers.item_router.item_crud.update_new_item', return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await endpoint_func(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, item=item_update_data, db=mock_db_session)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Item not found" in exc_info.value.detail

@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint_func", [item_router.update_item_endpoint, item_router.patch_item_endpoint])
async def test_update_patch_item_endpoint_name_conflict(endpoint_func, mock_db_session: MagicMock, mocker: MagicMock):
    item_update_data = NewItemUpdate(name="Conflicting Name Sword")
    mocker.patch('bot.api.routers.item_router.item_crud.update_new_item', side_effect=IntegrityError("mocked integrity error", params=None, orig=Exception("unique constraint failed")))

    with pytest.raises(HTTPException) as exc_info:
        await endpoint_func(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, item=item_update_data, db=mock_db_session)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Another item with this name already exists" in exc_info.value.detail

# --- Tests for delete_item_endpoint ---
@pytest.mark.asyncio
async def test_delete_item_endpoint_success(mock_db_session: MagicMock, mocker: MagicMock):
    mock_deleted_orm_item = NewItem(id=ITEM_ID_1, name="Deleted Sword", item_type="weapon", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW)
    mock_delete_new_item = mocker.patch('bot.api.routers.item_router.item_crud.delete_new_item', return_value=mock_deleted_orm_item)

    result = await item_router.delete_item_endpoint(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, db=mock_db_session)

    assert isinstance(result, NewItemRead)
    assert result.id == ITEM_ID_1
    assert result.name == "Deleted Sword"
    assert result.guild_id == GUILD_ID_EXISTING
    mock_delete_new_item.assert_called_once_with(db=mock_db_session, item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING)

@pytest.mark.asyncio
async def test_delete_item_endpoint_not_found(mock_db_session: MagicMock, mocker: MagicMock):
    mocker.patch('bot.api.routers.item_router.item_crud.delete_new_item', return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await item_router.delete_item_endpoint(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, db=mock_db_session)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    # The detail message in the router is "Item not found or already deleted"
    assert "Item not found" in exc_info.value.detail

@pytest.mark.asyncio
async def test_delete_item_endpoint_in_inventory(mock_db_session: MagicMock, mocker: MagicMock):
    mocker.patch('bot.api.routers.item_router.item_crud.delete_new_item', side_effect=ValueError("Item cannot be deleted as it is currently in a character's inventory"))

    with pytest.raises(HTTPException) as exc_info:
        await item_router.delete_item_endpoint(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, db=mock_db_session)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Item cannot be deleted as it is currently in a character's inventory" in exc_info.value.detail

@pytest.mark.asyncio
async def test_delete_item_endpoint_other_value_error(mock_db_session: MagicMock, mocker: MagicMock):
    mocker.patch('bot.api.routers.item_router.item_crud.delete_new_item', side_effect=ValueError("Some other value error"))

    with pytest.raises(HTTPException) as exc_info:
        await item_router.delete_item_endpoint(item_id=ITEM_ID_1, guild_id=GUILD_ID_EXISTING, db=mock_db_session)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Some other value error" in exc_info.value.detail
