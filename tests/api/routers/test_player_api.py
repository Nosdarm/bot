import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import AsyncIterator, Dict, Any
import uuid

from bot.main import app # Import your FastAPI app instance
from bot.database.models import Player, Base
from bot.api.schemas.player_schemas import PlayerRead

# Use the same test database setup as other integration tests
from tests.integration.test_database_model_constraints import test_engine # Reuse engine fixture

@pytest_asyncio.fixture(scope="function")
async def client(test_engine) -> AsyncIterator[AsyncClient]:
    """Provides an AsyncClient for making API requests to the FastAPI app, with a clean database."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all) # Ensure clean tables for each test function
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

# Test data
TEST_GUILD_ID_API = str(uuid.uuid4())
OTHER_GUILD_ID_API = str(uuid.uuid4())

@pytest.mark.asyncio
class TestPlayerAPI:

    async def _create_player_direct_db(self, db_session: AsyncSession, guild_id: str, discord_id: str, name: str = "Test Player DB") -> Player:
        """Helper to create a player directly in DB for setup."""
        player_id = str(uuid.uuid4())
        db_player = Player(
            id=player_id,
            guild_id=guild_id,
            discord_id=discord_id,
            name_i18n={"en": name},
            level=1, xp=0, gold=0, is_active=True
        )
        db_session.add(db_player)
        await db_session.commit()
        await db_session.refresh(db_player)
        return db_player

    async def test_create_player_success(self, client: AsyncClient):
        discord_id = f"discord_user_{str(uuid.uuid4())[:8]}"
        player_data = {
            "discord_id": discord_id,
            "guild_id": TEST_GUILD_ID_API, # This field is in PlayerCreate schema
            "name_i18n": {"en": "API Test Player", "ru": "API Тестовый Игрок"},
            "selected_language": "en"
        }
        # The Player router is mounted under /guilds/{guild_id}/players
        response = await client.post(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/", json=player_data)

        assert response.status_code == 201
        created_player = response.json()
        assert created_player["discord_id"] == discord_id
        assert created_player["guild_id"] == TEST_GUILD_ID_API
        assert created_player["name_i18n"]["en"] == "API Test Player"
        assert "id" in created_player

    async def test_create_player_duplicate_discord_id_in_guild(self, client: AsyncClient, test_engine):
        discord_id = f"discord_user_dup_{str(uuid.uuid4())[:8]}"
        # Create first player via API
        player_data_1 = {
            "discord_id": discord_id, "guild_id": TEST_GUILD_ID_API,
            "name_i18n": {"en": "First Player"}
        }
        response1 = await client.post(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/", json=player_data_1)
        assert response1.status_code == 201

        # Attempt to create second player with same discord_id in same guild
        player_data_2 = {
            "discord_id": discord_id, "guild_id": TEST_GUILD_ID_API,
            "name_i18n": {"en": "Second Player Same Discord"}
        }
        response2 = await client.post(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/", json=player_data_2)
        assert response2.status_code == 409 # Conflict

    async def test_create_player_same_discord_id_different_guild(self, client: AsyncClient):
        discord_id = f"discord_user_diffguild_{str(uuid.uuid4())[:8]}"
        player_data_g1 = {
            "discord_id": discord_id, "guild_id": TEST_GUILD_ID_API,
            "name_i18n": {"en": "Player Guild 1"}
        }
        response_g1 = await client.post(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/", json=player_data_g1)
        assert response_g1.status_code == 201

        player_data_g2 = {
            "discord_id": discord_id, "guild_id": OTHER_GUILD_ID_API,
            "name_i18n": {"en": "Player Guild 2"}
        }
        response_g2 = await client.post(f"/api/v1/guilds/{OTHER_GUILD_ID_API}/players/", json=player_data_g2)
        assert response_g2.status_code == 201 # Should succeed

    async def test_get_player_success(self, client: AsyncClient, test_engine):
        # Setup: Create a player directly in DB to get a known ID
        async with AsyncSession(test_engine) as session:
            player = await self._create_player_direct_db(session, TEST_GUILD_ID_API, f"get_user_{str(uuid.uuid4())[:4]}")
            player_id = player.id

        response = await client.get(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/{player_id}")
        assert response.status_code == 200
        retrieved_player = response.json()
        assert retrieved_player["id"] == player_id
        assert retrieved_player["guild_id"] == TEST_GUILD_ID_API

    async def test_get_player_not_found(self, client: AsyncClient):
        non_existent_player_id = str(uuid.uuid4())
        response = await client.get(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/{non_existent_player_id}")
        assert response.status_code == 404

    async def test_get_player_wrong_guild(self, client: AsyncClient, test_engine):
        async with AsyncSession(test_engine) as session:
            player = await self._create_player_direct_db(session, TEST_GUILD_ID_API, f"wrong_guild_user_{str(uuid.uuid4())[:4]}")
            player_id = player.id

        response = await client.get(f"/api/v1/guilds/{OTHER_GUILD_ID_API}/players/{player_id}") # Attempt to get from other guild
        assert response.status_code == 404 # Should not be found in OTHER_GUILD_ID_API

    async def test_update_player_success(self, client: AsyncClient, test_engine):
        async with AsyncSession(test_engine) as session:
            player = await self._create_player_direct_db(session, TEST_GUILD_ID_API, f"update_user_{str(uuid.uuid4())[:4]}")
            player_id = player.id

        update_payload = {
            "name_i18n": {"en": "Updated Player Name", "ru": "Обновленное Имя"},
            "selected_language": "ru"
        }
        response = await client.put(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/{player_id}", json=update_payload)
        assert response.status_code == 200
        updated_player = response.json()
        assert updated_player["name_i18n"]["en"] == "Updated Player Name"
        assert updated_player["selected_language"] == "ru"

    async def test_update_player_not_found(self, client: AsyncClient):
        non_existent_player_id = str(uuid.uuid4())
        update_payload = {"name_i18n": {"en": "Ghost Name"}}
        response = await client.put(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/{non_existent_player_id}", json=update_payload)
        assert response.status_code == 404

    async def test_delete_player_success(self, client: AsyncClient, test_engine):
        async with AsyncSession(test_engine) as session:
            player = await self._create_player_direct_db(session, TEST_GUILD_ID_API, f"delete_user_{str(uuid.uuid4())[:4]}")
            player_id = player.id

        response = await client.delete(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/{player_id}")
        assert response.status_code == 204

        # Verify player is deleted (or marked inactive if soft delete was intended by API)
        # The current API impl does hard delete.
        response_get = await client.get(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/{player_id}")
        assert response_get.status_code == 404

    async def test_delete_player_not_found(self, client: AsyncClient):
        non_existent_player_id = str(uuid.uuid4())
        response = await client.delete(f"/api/v1/guilds/{TEST_GUILD_ID_API}/players/{non_existent_player_id}")
        assert response.status_code == 404

```
