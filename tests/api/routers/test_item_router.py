import pytest
import pytest_asyncio # Required for async fixtures
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4, UUID
from datetime import datetime
from typing import AsyncIterator # Required for async fixture typing

from httpx import AsyncClient # For making API calls
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession # For type hinting test_engine session

# Modules to test
from bot.api.main import app # FastAPI app instance
# Schemas and ORM model
from bot.api.schemas.item_schemas import NewItemCreate, NewItemRead, NewItemUpdate
from bot.database.models.item_related import NewItem as ORMNewItem # ORM model
from bot.database.base import Base # Corrected path For DB setup

# Common test data
ITEM_ID_1 = uuid4()
ITEM_ID_2 = uuid4()
GUILD_ID_EXISTING = "guild_test_123"
NOW = datetime.utcnow() # Note: utcnow() is deprecated, consider datetime.now(timezone.utc)

# Fixture for AsyncClient and isolated DB for each test function
@pytest_asyncio.fixture(scope="function")
async def client(test_engine_instance) -> AsyncIterator[AsyncClient]: # Depends on a test_engine
    """
    Provides an AsyncClient for making API requests to the FastAPI app.
    Ensures a clean database state for each test by dropping and creating tables.
    """
    async with test_engine_instance.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest_asyncio.fixture(scope="session") # Changed to session scope for efficiency
async def test_engine_instance():
    """
    Provides a SQLAlchemy async engine instance for tests.
    This should ideally use a separate test database configuration.
    For now, it mimics what test_character_api.py might use or what's generally available.
    NOTE: This fixture is simplified. A real setup would handle test DB creation/deletion.
    The `sslmode` issue previously encountered suggests this engine might be configured
    to hit a Postgres DB. The conftest.py forces DATABASE_TYPE=sqlite for the app,
    but this fixture might be creating a direct Postgres engine for test setup if not careful.
    For these item router tests, if they are pure unit tests mocking CRUD, the engine type
    might not matter as much as long as session objects can be mocked or created.
    However, for consistency and to avoid sslmode issues if this were hitting Postgres,
    it should ideally use the same (potentially SQLite) setup or a properly configured
    Postgres test DB URL without sslmode issues.
    """
    from bot.services.db_service import DBService # Import here to respect conftest env vars
    # DBService will pick up DATABASE_TYPE="sqlite" and TEST_DATABASE_URL from conftest
    db_service = DBService()
    await db_service.initialize_database() # Ensures tables are created if using SQLite in-memory based on models

    # The adapter's engine is what FastAPI app would use.
    # For tests that might do direct DB setup OUTSIDE client calls, they'd need this engine.
    # However, these tests are refactored to use client, so direct engine use in tests minimized.
    yield db_service.adapter._engine # Provide the engine from the (likely SQLite) adapter

    await db_service.close()


# --- Tests for create_item_endpoint ---
@pytest.mark.asyncio
async def test_create_item_endpoint_success(client: AsyncClient, mocker: MagicMock):
    item_create_data = NewItemCreate(name="Great Sword", item_type="weapon", description="A hefty blade.", item_metadata={"damage": "2d6"}, guild_id=GUILD_ID_EXISTING)
    mock_orm_item = ORMNewItem(
        id=ITEM_ID_1, name=item_create_data.name, item_type=item_create_data.item_type,
        description=item_create_data.description, item_metadata=item_create_data.item_metadata,
        guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW
    )
    mock_crud_create = mocker.patch('bot.api.routers.item_router.item_crud.create_new_item', return_value=mock_orm_item)

    response = await client.post(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/", json=item_create_data.model_dump())

    assert response.status_code == status.HTTP_201_CREATED
    result_data = response.json()

    assert result_data['id'] == str(ITEM_ID_1)
    assert result_data['name'] == item_create_data.name
    assert result_data['item_metadata'] == item_create_data.item_metadata
    assert result_data['guild_id'] == GUILD_ID_EXISTING # Assuming guild_id is part of NewItemRead
    mock_crud_create.assert_called_once()
    # db session is injected by FastAPI, item is the payload
    assert mock_crud_create.call_args[1]['item'] == item_create_data


@pytest.mark.asyncio
async def test_create_item_endpoint_name_conflict(client: AsyncClient, mocker: MagicMock):
    item_create_data = NewItemCreate(name="Existing Sword", item_type="weapon", guild_id=GUILD_ID_EXISTING)
    mocker.patch('bot.api.routers.item_router.item_crud.create_new_item', side_effect=IntegrityError("mocked integrity error", params=None, orig=Exception("unique constraint failed")))

    response = await client.post(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/", json=item_create_data.model_dump())

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Item with this name already exists" in response.json()["detail"]

# --- Tests for read_items_endpoint ---
@pytest.mark.asyncio
async def test_read_items_endpoint_success(client: AsyncClient, mocker: MagicMock):
    mock_orm_items = [
        ORMNewItem(id=ITEM_ID_1, name="Sword", item_type="weapon", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW),
        ORMNewItem(id=ITEM_ID_2, name="Shield", item_type="armor", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW),
    ]
    mock_get_new_items = mocker.patch('bot.api.routers.item_router.item_crud.get_new_items', return_value=mock_orm_items)

    # Assuming item_router is mounted under /api/v1/guilds/{guild_id}/items
    response = await client.get(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/?skip=0&limit=10")

    assert response.status_code == status.HTTP_200_OK
    result_data = response.json()
    assert isinstance(result_data, list)
    assert len(result_data) == 2
    assert result_data[0]['id'] == str(ITEM_ID_1)
    # NewItemRead might not have guild_id if it's implicit from the path, check schema
    # For now, assuming it does for direct comparison if returned by API
    if 'guild_id' in result_data[0]:
      assert result_data[0]['guild_id'] == GUILD_ID_EXISTING
    assert result_data[1]['name'] == "Shield"

    mock_get_new_items.assert_called_once()
    call_args = mock_get_new_items.call_args[1]
    assert call_args['guild_id'] == GUILD_ID_EXISTING
    assert call_args['skip'] == 0
    assert call_args['limit'] == 10

# --- Tests for read_item_endpoint ---
@pytest.mark.asyncio
async def test_read_item_endpoint_success(client: AsyncClient, mocker: MagicMock):
    mock_orm_item = ORMNewItem(id=ITEM_ID_1, name="Detailed Sword", item_type="weapon", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW)
    mock_get_new_item = mocker.patch('bot.api.routers.item_router.item_crud.get_new_item', return_value=mock_orm_item)

    response = await client.get(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}")

    assert response.status_code == status.HTTP_200_OK
    result_data = response.json()
    assert result_data['id'] == str(ITEM_ID_1)
    assert result_data['name'] == "Detailed Sword"
    if 'guild_id' in result_data: # guild_id might not be in NewItemRead if it's a path param
        assert result_data['guild_id'] == GUILD_ID_EXISTING

    mock_get_new_item.assert_called_once()
    call_args = mock_get_new_item.call_args[1]
    assert call_args['item_id'] == ITEM_ID_1
    assert call_args['guild_id'] == GUILD_ID_EXISTING

@pytest.mark.asyncio
async def test_read_item_endpoint_not_found(client: AsyncClient, mocker: MagicMock):
    mocker.patch('bot.api.routers.item_router.item_crud.get_new_item', return_value=None)
    response = await client.get(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Item not found" in response.json()["detail"]

# --- Tests for update_item_endpoint (covers PUT and PATCH due to shared CRUD logic) ---
@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PUT", "PATCH"])
async def test_update_patch_item_endpoint_success(method: str, client: AsyncClient, mocker: MagicMock):
    item_update_data = NewItemUpdate(name="Renamed Sword", description="Now sharper.")
    mock_updated_orm_item = ORMNewItem(
        id=ITEM_ID_1, name="Renamed Sword", description="Now sharper.",
        item_type="weapon", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=datetime.utcnow()
    )
    mock_crud_update = mocker.patch('bot.api.routers.item_router.item_crud.update_new_item', return_value=mock_updated_orm_item)

    url = f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}"
    if method == "PUT":
        response = await client.put(url, json=item_update_data.model_dump(exclude_unset=False))
    else: # PATCH
        response = await client.patch(url, json=item_update_data.model_dump(exclude_unset=True))

    assert response.status_code == status.HTTP_200_OK
    result_data = response.json()
    assert result_data['id'] == str(ITEM_ID_1)
    assert result_data['name'] == "Renamed Sword"
    if 'guild_id' in result_data:
      assert result_data['guild_id'] == GUILD_ID_EXISTING

    mock_crud_update.assert_called_once()
    call_args = mock_crud_update.call_args[1]
    assert call_args['item_id'] == ITEM_ID_1
    assert call_args['guild_id'] == GUILD_ID_EXISTING
    assert call_args['item_update'] == item_update_data

@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PUT", "PATCH"])
async def test_update_patch_item_endpoint_not_found(method: str, client: AsyncClient, mocker: MagicMock):
    item_update_data = NewItemUpdate(name="NonExistent Sword")
    mocker.patch('bot.api.routers.item_router.item_crud.update_new_item', return_value=None)

    url = f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}"
    if method == "PUT":
        response = await client.put(url, json=item_update_data.model_dump(exclude_unset=False))
    else: # PATCH
        response = await client.patch(url, json=item_update_data.model_dump(exclude_unset=True))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Item not found" in response.json()["detail"]

@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PUT", "PATCH"])
async def test_update_patch_item_endpoint_name_conflict(method: str, client: AsyncClient, mocker: MagicMock):
    item_update_data = NewItemUpdate(name="Conflicting Name Sword")
    mocker.patch('bot.api.routers.item_router.item_crud.update_new_item', side_effect=IntegrityError("mocked integrity error", params=None, orig=Exception("unique constraint failed")))

    url = f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}"
    if method == "PUT":
        response = await client.put(url, json=item_update_data.model_dump(exclude_unset=False))
    else: # PATCH
        response = await client.patch(url, json=item_update_data.model_dump(exclude_unset=True))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    detail = response.json()["detail"]
    assert "Another item with this name already exists" in detail or "other integrity violation" in detail


# --- Tests for delete_item_endpoint ---
@pytest.mark.asyncio
async def test_delete_item_endpoint_success(client: AsyncClient, mocker: MagicMock):
    mock_deleted_orm_item = ORMNewItem(id=ITEM_ID_1, name="Deleted Sword", item_type="weapon", guild_id=GUILD_ID_EXISTING, created_at=NOW, updated_at=NOW)
    mock_crud_delete = mocker.patch('bot.api.routers.item_router.item_crud.delete_new_item', return_value=mock_deleted_orm_item)

    response = await client.delete(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}")

    assert response.status_code == status.HTTP_200_OK # Endpoint returns deleted item
    result_data = response.json()
    assert result_data['id'] == str(ITEM_ID_1)
    assert result_data['name'] == "Deleted Sword"
    if 'guild_id' in result_data:
      assert result_data['guild_id'] == GUILD_ID_EXISTING

    mock_crud_delete.assert_called_once()
    call_args = mock_crud_delete.call_args[1]
    assert call_args['item_id'] == ITEM_ID_1
    assert call_args['guild_id'] == GUILD_ID_EXISTING

@pytest.mark.asyncio
async def test_delete_item_endpoint_not_found(client: AsyncClient, mocker: MagicMock):
    mocker.patch('bot.api.routers.item_router.item_crud.delete_new_item', return_value=None)
    response = await client.delete(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Item not found or already deleted" in response.json()["detail"]

@pytest.mark.asyncio
async def test_delete_item_endpoint_in_inventory(client: AsyncClient, mocker: MagicMock):
    mocker.patch('bot.api.routers.item_router.item_crud.delete_new_item', side_effect=ValueError("Item cannot be deleted as it is currently in a character's inventory"))
    response = await client.delete(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Item cannot be deleted as it is currently in a character's inventory" in response.json()["detail"]

@pytest.mark.asyncio
async def test_delete_item_endpoint_other_value_error(client: AsyncClient, mocker: MagicMock):
    mocker.patch('bot.api.routers.item_router.item_crud.delete_new_item', side_effect=ValueError("Some other value error"))
    response = await client.delete(f"/api/v1/guilds/{GUILD_ID_EXISTING}/items/{ITEM_ID_1}")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Some other value error" in response.json()["detail"]

# Fixture to provide a test_engine similar to other API tests
# This ensures that the DBService used by the app (and thus get_db_session)
# is configured correctly for tests (e.g., using SQLite in-memory).
# Note: test_engine_instance is defined above now at module scope
# This is a placeholder if a more specific engine setup for items is ever needed.
# For now, the global test_engine_instance should suffice.
@pytest_asyncio.fixture(scope="function")
async def item_test_db_session(test_engine_instance):
    async with AsyncSession(test_engine_instance) as session:
        yield session
        await session.rollback() # Ensure clean state if any direct DB ops were done (though unlikely now)
