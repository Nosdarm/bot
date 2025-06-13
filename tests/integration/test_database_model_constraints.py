import pytest
import pytest_asyncio
import os
from typing import AsyncGenerator
import uuid # For generating unique IDs

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from bot.database.models import Base, Player, Location, RulesConfig # Add other models as needed

# --- Test Database Configuration ---
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test123@localhost:5432/test_kvelin_rpg_bot_constraints")

# --- Fixtures ---

@pytest_asyncio.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Creates a test database engine and handles table creation/dropping for the session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False) # Disable echo for constraint tests unless debugging

    async with engine.begin() as conn:
        # print("Dropping all tables before constraint test session...")
        # await conn.run_sync(Base.metadata.drop_all) # Optional: Ensure clean slate
        print("Creating all tables for constraint test session...")
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Teardown: Drop all tables after the test session (optional, for manual inspection leave commented)
    # async with engine.begin() as conn:
    #     print("Dropping all tables after constraint test session...")
    #     await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional database session for each test function."""
    async_session_local = sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_local() as session:
        await session.begin_nested()
        yield session
        await session.rollback() # Rollback after each test to ensure isolation
        await session.close()


# --- Test Data ---
UNIQUE_GUILD_ID_1 = str(uuid.uuid4()) # Ensure unique guild IDs for each test run if needed
UNIQUE_GUILD_ID_2 = str(uuid.uuid4())
DISCORD_ID_1 = "discord_user_1"
DISCORD_ID_2 = "discord_user_2"

# --- Test Cases ---

@pytest.mark.asyncio
class TestPlayerModelConstraints:

    async def test_player_guild_id_not_nullable(self, db_session: AsyncSession):
        """Attempt to create a Player with guild_id=None, assert IntegrityError."""
        player_id = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            new_player = Player(
                id=player_id,
                discord_id=DISCORD_ID_1,
                name_i18n={"en": "Test Player"},
                guild_id=None, # This should violate NOT NULL constraint
                # Add other required fields with default or valid values
                level=1,
                xp=0,
                unspent_xp=0,
                gold=0,
                is_active=True,
                # Ensure all NOT NULL fields without defaults are provided
            )
            db_session.add(new_player)
            await db_session.flush() # Use flush to check constraints before commit

    async def test_player_discord_id_guild_id_unique(self, db_session: AsyncSession):
        """Test the unique constraint for (discord_id, guild_id)."""
        player_id_1 = str(uuid.uuid4())
        player_id_2 = str(uuid.uuid4())

        # Create first player
        player1 = Player(
            id=player_id_1, discord_id=DISCORD_ID_1, name_i18n={"en": "Player 1"},
            guild_id=UNIQUE_GUILD_ID_1, level=1, xp=0, unspent_xp=0, gold=0, is_active=True
        )
        db_session.add(player1)
        await db_session.commit() # Commit to ensure it's in DB for unique check

        # Attempt to create a second player with the same discord_id and guild_id
        with pytest.raises(IntegrityError):
            player2_same_guild = Player(
                id=player_id_2, discord_id=DISCORD_ID_1, name_i18n={"en": "Player 2 Same Guild"},
                guild_id=UNIQUE_GUILD_ID_1, level=1, xp=0, unspent_xp=0, gold=0, is_active=True
            )
            db_session.add(player2_same_guild)
            await db_session.flush() # Check constraint

        await db_session.rollback() # Rollback the failed attempt explicitly

        # Verify that creating a player with same discord_id but DIFFERENT guild_id is allowed
        player_id_3 = str(uuid.uuid4())
        player3_diff_guild = Player(
            id=player_id_3, discord_id=DISCORD_ID_1, name_i18n={"en": "Player 3 Diff Guild"},
            guild_id=UNIQUE_GUILD_ID_2, level=1, xp=0, unspent_xp=0, gold=0, is_active=True
        )
        db_session.add(player3_diff_guild)
        await db_session.commit() # Should succeed
        assert player3_diff_guild.id is not None


@pytest.mark.asyncio
class TestLocationModelConstraints:

    async def test_location_guild_id_not_nullable(self, db_session: AsyncSession):
        """Attempt to create a Location with guild_id=None, assert IntegrityError."""
        location_id = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            new_location = Location(
                id=location_id,
                name_i18n={"en": "Test Location"},
                descriptions_i18n={"en": "A place"},
                type_i18n={"en": "Generic"}, # Assuming type_i18n is NOT NULL
                guild_id=None, # This should violate NOT NULL constraint
                is_active=True
                # Provide other NOT NULL fields if any
            )
            db_session.add(new_location)
            await db_session.flush()


@pytest.mark.asyncio
class TestRulesConfigModelConstraints:

    async def test_rules_config_guild_id_not_nullable(self, db_session: AsyncSession):
        """Attempt to create RulesConfig with guild_id=None, assert IntegrityError."""
        # RulesConfig's guild_id is its primary key, so it inherently cannot be None.
        # SQLAlchemy might raise a different error before even hitting the DB if PK is None.
        # Let's test by trying to commit it.
        with pytest.raises(Exception): # Could be IntegrityError or other SA error for None PK
            new_rules_config = RulesConfig(
                guild_id=None, # Primary Key, cannot be None
                config_data={"default_language": "en"}
            )
            db_session.add(new_rules_config)
            await db_session.flush()

    async def test_rules_config_guild_id_primary_key(self, db_session: AsyncSession):
        """Attempt to create duplicate RulesConfig entries for the same guild_id, assert IntegrityError."""
        # Create first RulesConfig
        rules_config1 = RulesConfig(
            guild_id=UNIQUE_GUILD_ID_1,
            config_data={"default_language": "en"}
        )
        db_session.add(rules_config1)
        await db_session.commit()

        # Attempt to create a second RulesConfig with the same guild_id
        with pytest.raises(IntegrityError):
            rules_config2_same_guild = RulesConfig(
                guild_id=UNIQUE_GUILD_ID_1, # Same guild_id
                config_data={"default_language": "fr"}
            )
            db_session.add(rules_config2_same_guild)
            await db_session.flush() # Check constraint

        await db_session.rollback()

        # Verify that creating RulesConfig for a DIFFERENT guild_id is allowed
        rules_config3_diff_guild = RulesConfig(
            guild_id=UNIQUE_GUILD_ID_2,
            config_data={"default_language": "es"}
        )
        db_session.add(rules_config3_diff_guild)
        await db_session.commit() # Should succeed
        assert rules_config3_diff_guild.guild_id == UNIQUE_GUILD_ID_2
