import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import AsyncIterator, Dict, Any
import uuid

from bot.main import app # Import your FastAPI app instance
from bot.database.models import Player, Character as DBCharacter, Base # Renamed to DBCharacter
from bot.api.schemas.character_schemas import CharacterRead

# Use the same test database setup as other integration tests
from tests.integration.test_database_model_constraints import test_engine # Reuse engine fixture

@pytest_asyncio.fixture(scope="function")
async def client(test_engine) -> AsyncIterator[AsyncClient]:
    """Provides an AsyncClient for making API requests to the FastAPI app, with a clean database."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

# Test data
TEST_GUILD_ID_CHAR_API = str(uuid.uuid4())
OTHER_GUILD_ID_CHAR_API = str(uuid.uuid4())

# Helper to create a player directly in DB for character tests
async def _ensure_player(db_session: AsyncSession, guild_id: str, discord_id_suffix: str) -> Player:
    discord_id = f"char_test_player_{discord_id_suffix}_{str(uuid.uuid4())[:4]}"
    player = await db_session.execute(select(Player).where(Player.discord_id == discord_id, Player.guild_id == guild_id))
    db_player = player.scalars().first()
    if not db_player:
        db_player = Player(
            id=str(uuid.uuid4()), guild_id=guild_id, discord_id=discord_id,
            name_i18n={"en": f"CharTestPlayer {discord_id_suffix}"},
            level=1, xp=0, gold=0, is_active=True
        )
        db_session.add(db_player)
        await db_session.commit()
        await db_session.refresh(db_player)
    return db_player

@pytest.mark.asyncio
class TestCharacterAPI:

    async def _create_character_direct_db(
        self, db_session: AsyncSession, player_id: str, guild_id: str, name_en: str = "Test Char DB"
    ) -> DBCharacter:
        """Helper to create a character directly in DB."""
        char_id = str(uuid.uuid4())
        db_char = DBCharacter(
            id=char_id, player_id=player_id, guild_id=guild_id,
            name_i18n={"en": name_en, "ru": f"Тест {name_en}"},
            class_i18n={"en": "Warrior", "ru": "Воин"},
            description_i18n={"en": "A brave warrior.", "ru": "Храбрый воин."},
            level=1, xp=0
        )
        db_session.add(db_char)
        await db_session.commit()
        await db_session.refresh(db_char)
        return db_char

    async def test_create_character_success(self, client: AsyncClient, test_engine):
        async with AsyncSession(test_engine) as session:
            player = await _ensure_player(session, TEST_GUILD_ID_CHAR_API, "create_char")

        char_data = {
            "player_id": player.id, # From CharacterCreate schema
            "guild_id": TEST_GUILD_ID_CHAR_API, # From CharacterCreate schema
            "name_i18n": {"en": "API Char", "ru": "АПИ Персонаж"},
            "class_i18n": {"en": "Mage", "ru": "Маг"},
            "description_i18n": {"en": "Wise mage", "ru": "Мудрый маг"},
            "level": 1,
            "xp": 0 # schema uses 'experience', model uses 'xp'. Router handles this.
        }
        # Character router is /guilds/{guild_id}/players/{player_id}/characters/
        response = await client.post(
            f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/players/{player.id}/characters/",
            json=char_data
        )

        assert response.status_code == 201
        created_char = response.json()
        assert created_char["name_i18n"]["en"] == "API Char"
        assert created_char["guild_id"] == TEST_GUILD_ID_CHAR_API
        assert created_char["player_id"] == player.id
        assert "id" in created_char

    async def test_get_character_success(self, client: AsyncClient, test_engine):
        async with AsyncSession(test_engine) as session:
            player = await _ensure_player(session, TEST_GUILD_ID_CHAR_API, "get_char")
            character = await self._create_character_direct_db(session, player.id, TEST_GUILD_ID_CHAR_API, "Get Me Char")
            char_id = character.id

        response = await client.get(f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/characters/{char_id}")
        assert response.status_code == 200
        retrieved_char = response.json()
        assert retrieved_char["id"] == char_id
        assert retrieved_char["name_i18n"]["en"] == "Get Me Char"
        assert retrieved_char["class_i18n"]["en"] == "Warrior"

    async def test_get_character_not_found(self, client: AsyncClient):
        non_existent_char_id = str(uuid.uuid4())
        response = await client.get(f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/characters/{non_existent_char_id}")
        assert response.status_code == 404

    async def test_get_characters_for_player(self, client: AsyncClient, test_engine):
        async with AsyncSession(test_engine) as session:
            player = await _ensure_player(session, TEST_GUILD_ID_CHAR_API, "list_chars")
            await self._create_character_direct_db(session, player.id, TEST_GUILD_ID_CHAR_API, "Char 1 For List")
            await self._create_character_direct_db(session, player.id, TEST_GUILD_ID_CHAR_API, "Char 2 For List")
            # Create a char for another player or guild to ensure filtering works
            other_player = await _ensure_player(session, OTHER_GUILD_ID_CHAR_API, "other_list")
            await self._create_character_direct_db(session, other_player.id, OTHER_GUILD_ID_CHAR_API, "Other Char")

        response = await client.get(f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/players/{player.id}/characters/")
        assert response.status_code == 200
        characters = response.json()
        assert len(characters) == 2
        assert characters[0]["player_id"] == player.id
        assert characters[1]["player_id"] == player.id
        assert characters[0]["guild_id"] == TEST_GUILD_ID_CHAR_API

    async def test_update_character_success(self, client: AsyncClient, test_engine):
        async with AsyncSession(test_engine) as session:
            player = await _ensure_player(session, TEST_GUILD_ID_CHAR_API, "update_char")
            character = await self._create_character_direct_db(session, player.id, TEST_GUILD_ID_CHAR_API, "Update Me Char")
            char_id = character.id

        update_payload = {
            "name_i18n": {"en": "Updated Char Name", "ru": "Обновленное Имя Персонажа"},
            "level": 5,
            "xp": 5500 # schema 'experience'
        }
        response = await client.put(
            f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/characters/{char_id}",
            json=update_payload
        )
        assert response.status_code == 200
        updated_char = response.json()
        assert updated_char["name_i18n"]["en"] == "Updated Char Name"
        assert updated_char["level"] == 5
        assert updated_char["xp"] == 5500 # DB field is xp, schema field is experience, router handles mapping

    async def test_update_character_not_found(self, client: AsyncClient):
        non_existent_char_id = str(uuid.uuid4())
        update_payload = {"name_i18n": {"en": "Ghost Char Name"}}
        response = await client.put(
            f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/characters/{non_existent_char_id}",
            json=update_payload
        )
        assert response.status_code == 404

    async def test_delete_character_success(self, client: AsyncClient, test_engine):
        async with AsyncSession(test_engine) as session:
            player = await _ensure_player(session, TEST_GUILD_ID_CHAR_API, "delete_char")
            character = await self._create_character_direct_db(session, player.id, TEST_GUILD_ID_CHAR_API, "Delete Me Char")
            char_id = character.id

        response = await client.delete(f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/characters/{char_id}")
        assert response.status_code == 204

        # Verify character is deleted
        response_get = await client.get(f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/characters/{char_id}")
        assert response_get.status_code == 404

    async def test_delete_character_not_found(self, client: AsyncClient):
        non_existent_char_id = str(uuid.uuid4())
        response = await client.delete(f"/api/v1/guilds/{TEST_GUILD_ID_CHAR_API}/characters/{non_existent_char_id}")
        assert response.status_code == 404

```
