import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4, UUID
from datetime import datetime
from typing import AsyncIterator, List, Dict, Any

from httpx import AsyncClient
from fastapi import HTTPException, status, Response

# App and DB models/schemas
from bot.api.main import app
from bot.api.schemas.inventory_schemas import NewCharacterItemCreate, NewCharacterItemRead, InventoryItemRead
from bot.api.schemas.item_schemas import NewItemRead as ItemReadSchema # Renamed for clarity
from bot.database.models import NewCharacterItem as ORMCharacterItem, NewItem as ORMItem, Character as ORMCharacter
from bot.database.base import Base # Corrected path
from bot.database.item_crud import get_new_item # For mocking if needed by CharacterItem.item relationship

# Common test data
GUILD_ID_INV = "guild_inv_test_789"
CHAR_ID_1 = "char_inv_test_123"
ITEM_ID_1 = uuid4()
ITEM_ID_2 = uuid4()
CHAR_ITEM_ID_1 = uuid4()
NOW = datetime.utcnow()


@pytest_asyncio.fixture(scope="session")
async def test_engine_inventory_instance():
    from bot.services.db_service import DBService
    db_service = DBService()
    await db_service.initialize_database()
    yield db_service.adapter._engine
    await db_service.close()

@pytest_asyncio.fixture(scope="function")
async def client(test_engine_inventory_instance) -> AsyncIterator[AsyncClient]:
    async with test_engine_inventory_instance.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Need to ensure a character exists for most tests
    async with AsyncSession(test_engine_inventory_instance) as session:
        # Create a guild config if player/character creation depends on it
        # from bot.database.models.config_related import GuildConfig
        # guild_conf = GuildConfig(guild_id=GUILD_ID_INV, default_language="en")
        # session.add(guild_conf)

        # Create a player for the character
        from bot.database.models.character_related import Player
        player = Player(id=f"player_for_{CHAR_ID_1}", guild_id=GUILD_ID_INV, discord_id=f"discord_{CHAR_ID_1}", name_i18n={"en":"InvTestPlayer"})
        session.add(player)

        # Create the character directly for tests
        char = ORMCharacter(
            id=CHAR_ID_1, player_id=player.id, guild_id=GUILD_ID_INV,
            name_i18n={"en": "Inv Test Char"}, level=1, xp=0,
            character_class_i18n={"en": "Warrior"},
            stats_json='{}' # Ensure valid JSON or dict
        )
        session.add(char)
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.fixture
def mock_item_orm_1_for_inv() -> ORMItem: # Renamed to avoid conflict
    return ORMItem(
        id=ITEM_ID_1, name="Potion of Healing", item_type="consumable",
        guild_id=GUILD_ID_INV, # Item templates are guild-specific
        item_metadata={"effect": "heal", "amount": 20},
        created_at=NOW, updated_at=NOW
    )

# --- Tests for get_character_inventory_endpoint ---
@pytest.mark.asyncio
async def test_get_character_inventory_success(client: AsyncClient, mock_item_orm_1_for_inv: ORMItem, mocker: MagicMock):
    # Mock the ORM CharacterItem with its related Item
    mock_char_item_orm = ORMCharacterItem(
        id=CHAR_ITEM_ID_1, character_id=CHAR_ID_1, item_id=ITEM_ID_1,
        quantity=5, created_at=NOW, updated_at=NOW,
        item=mock_item_orm_1_for_inv # Preload relationship for the mock
    )
    # Patch the CRUD function that fetches from DB
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.get_character_inventory_orm', return_value=[mock_char_item_orm])
    # Patch get_character_orm because the endpoint uses it for validation
    mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=AsyncMock(spec=ORMCharacter, id=CHAR_ID_1))


    response = await client.get(f"/api/v1/guilds/{GUILD_ID_INV}/characters/{CHAR_ID_1}/inventory/")

    assert response.status_code == status.HTTP_200_OK
    result_data = response.json()
    assert isinstance(result_data, list)
    assert len(result_data) == 1

    # Check against InventoryItemRead schema structure
    inventory_item_read = result_data[0]
    assert inventory_item_read["item"]["id"] == str(ITEM_ID_1)
    assert inventory_item_read["item"]["name"] == "Potion of Healing"
    assert inventory_item_read["quantity"] == 5

@pytest.mark.asyncio
async def test_get_character_inventory_char_not_found(client: AsyncClient, mocker: MagicMock):
    mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=None)

    response = await client.get(f"/api/v1/guilds/{GUILD_ID_INV}/characters/{CHAR_ID_1}/inventory/")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Character not found" in response.json()["detail"]

# --- Tests for add_item_to_inventory_endpoint ---
@pytest.mark.asyncio
async def test_add_item_to_inventory_success(client: AsyncClient, mock_item_orm_1_for_inv: ORMItem, mocker: MagicMock):
    item_add_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=2)
    mock_added_char_item_orm = ORMCharacterItem(
        id=CHAR_ITEM_ID_1, character_id=CHAR_ID_1, item_id=ITEM_ID_1, quantity=2,
        created_at=NOW, updated_at=NOW, item=mock_item_orm_1_for_inv
    )
    mock_crud_add = mocker.patch('bot.api.routers.inventory_router.inventory_crud.add_item_to_character_inventory_orm', return_value=mock_added_char_item_orm)
    mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=AsyncMock(spec=ORMCharacter, id=CHAR_ID_1))


    response = await client.post(f"/api/v1/guilds/{GUILD_ID_INV}/characters/{CHAR_ID_1}/inventory/", json=item_add_data.model_dump())

    assert response.status_code == status.HTTP_200_OK # Changed from 201 as it returns existing/updated
    result_data = response.json()

    assert result_data['id'] == str(CHAR_ITEM_ID_1)
    assert result_data['item_id'] == str(ITEM_ID_1)
    assert result_data['quantity'] == 2
    assert result_data['item']['name'] == mock_item_orm_1_for_inv.name

    mock_crud_add.assert_called_once()
    call_args = mock_crud_add.call_args[1]
    assert call_args['character_id'] == CHAR_ID_1
    assert call_args['item_id'] == ITEM_ID_1
    assert call_args['quantity'] == 2

@pytest.mark.asyncio
@pytest.mark.parametrize("error_message, expected_detail, expected_status_code", [
    ("Character not found", "Character not found", status.HTTP_404_NOT_FOUND),
    ("Item template not found", "Item template not found", status.HTTP_404_NOT_FOUND),
    ("Quantity to add must be positive", "Quantity to add must be positive", status.HTTP_400_BAD_REQUEST),
])
async def test_add_item_to_inventory_value_errors(error_message: str, expected_detail: str, expected_status_code: int, client: AsyncClient, mocker: MagicMock):
    item_add_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=1)
    if "Character not found" in error_message:
        mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=None)
    else:
        mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=AsyncMock(spec=ORMCharacter, id=CHAR_ID_1))
        mocker.patch('bot.api.routers.inventory_router.inventory_crud.add_item_to_character_inventory_orm', side_effect=ValueError(error_message))

    response = await client.post(f"/api/v1/guilds/{GUILD_ID_INV}/characters/{CHAR_ID_1}/inventory/", json=item_add_data.model_dump())

    assert response.status_code == expected_status_code
    assert expected_detail in response.json()["detail"]

# --- Tests for remove_item_from_inventory_endpoint ---
@pytest.mark.asyncio
async def test_remove_item_from_inventory_partial_remove_success(client: AsyncClient, mock_item_orm_1_for_inv: ORMItem, mocker: MagicMock):
    item_remove_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=1)
    mock_updated_char_item_orm = ORMCharacterItem(
        id=CHAR_ITEM_ID_1, character_id=CHAR_ID_1, item_id=ITEM_ID_1, quantity=1, # Remaining
        created_at=NOW, updated_at=NOW, item=mock_item_orm_1_for_inv
    )
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.remove_item_from_character_inventory_orm', return_value=mock_updated_char_item_orm)
    mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=AsyncMock(spec=ORMCharacter, id=CHAR_ID_1))

    response = await client.request("DELETE", f"/api/v1/guilds/{GUILD_ID_INV}/characters/{CHAR_ID_1}/inventory/", json=item_remove_data.model_dump())

    assert response.status_code == status.HTTP_200_OK
    result_data = response.json()
    assert result_data['quantity'] == 1
    assert result_data['item_id'] == str(ITEM_ID_1)

@pytest.mark.asyncio
async def test_remove_item_from_inventory_full_remove_success(client: AsyncClient, mocker: MagicMock):
    item_remove_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=5) # Assuming 5 were there
    mocker.patch('bot.api.routers.inventory_router.inventory_crud.remove_item_from_character_inventory_orm', return_value=None) # None indicates full removal
    mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=AsyncMock(spec=ORMCharacter, id=CHAR_ID_1))

    response = await client.request("DELETE", f"/api/v1/guilds/{GUILD_ID_INV}/characters/{CHAR_ID_1}/inventory/", json=item_remove_data.model_dump())

    assert response.status_code == status.HTTP_204_NO_CONTENT

@pytest.mark.asyncio
@pytest.mark.parametrize("error_message, expected_detail, expected_status_code", [
    ("Character not found", "Character not found", status.HTTP_404_NOT_FOUND),
    ("Item not found in character's inventory", "Item not found in inventory", status.HTTP_404_NOT_FOUND),
    ("Cannot remove more items than available", "Insufficient quantity to remove", status.HTTP_400_BAD_REQUEST),
    ("Quantity to remove must be positive", "Quantity to remove must be positive", status.HTTP_400_BAD_REQUEST),
])
async def test_remove_item_from_inventory_value_errors(error_message: str, expected_detail: str, expected_status_code: int, client: AsyncClient, mocker: MagicMock):
    item_remove_data = NewCharacterItemCreate(item_id=ITEM_ID_1, quantity=1)
    if "Character not found" in error_message:
        mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=None)
    else:
        mocker.patch('bot.api.routers.inventory_router.get_character_orm', return_value=AsyncMock(spec=ORMCharacter, id=CHAR_ID_1))
        mocker.patch('bot.api.routers.inventory_router.inventory_crud.remove_item_from_character_inventory_orm', side_effect=ValueError(error_message))

    response = await client.request("DELETE", f"/api/v1/guilds/{GUILD_ID_INV}/characters/{CHAR_ID_1}/inventory/", json=item_remove_data.model_dump())

    assert response.status_code == expected_status_code
    assert expected_detail in response.json()["detail"]
