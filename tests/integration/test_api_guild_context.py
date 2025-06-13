import pytest
import pytest_asyncio
import os
import asyncio

from typing import AsyncGenerator, Dict, Any, Iterator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text, delete

from bot.api.main import app  # Main FastAPI application
from bot.database.models import Base, RulesConfig, Player, GeneratedFaction, Location # Add other models as needed
from bot.game.guild_initializer import DEFAULT_RULES_CONFIG_ID # Assuming this is the ID used
# For default location checks
from bot.game.guild_initializer import DEFAULT_START_LOCATION_ID # This is a template_id, actual ID is dynamic
# The actual ID of the default location is dynamic, so we'll use static_name or name_i18n for querying
DEFAULT_LOCATION_STATIC_NAME_FORMAT = "internal_starting_crossroads_{}" # Used to form the static_name
DEFAULT_LOCATION_EN_NAME = "Quiet Crossroads"
DEFAULT_FACTION_EN_NAME = "Neutral Observers"


# --- Test Database Configuration ---
# Use environment variables for database configuration, fallback to a default test DSN
# Example: postgresql+asyncpg://testuser:testpass@localhost:5432/test_kvelin_rpg_bot
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test123@localhost:5432/test_kvelin_rpg_bot")
# For local testing without a PG server, one might fallback to SQLite, but integration tests should ideally match prod DB.
# TEST_DATABASE_URL = "sqlite+aiosqlite_memory:///:memory:"

# --- Fixtures ---

@pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    # This is important for pytest-asyncio with session-scoped fixtures
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Creates a test database engine and handles table creation/dropping for the session."""
    # Set environment variable to trigger migrations on DB init by PostgresAdapter
    original_migrate_on_init = os.getenv("MIGRATE_ON_INIT")
    os.environ["MIGRATE_ON_INIT"] = "true"

    engine = create_async_engine(TEST_DATABASE_URL) # echo=True for SQL debugging

    async with engine.begin() as conn:
        # print("Dropping all tables before test session...") # Manual drop if needed
        # await conn.run_sync(Base.metadata.drop_all)
        print("Creating all tables for test session...")
        await conn.run_sync(Base.metadata.create_all) # Create tables if they don't exist

    yield engine # Provide the engine to other fixtures

    # Teardown: Drop all tables after the test session
    # This is commented out to allow inspection of the DB after tests.
    # For fully isolated tests, uncomment this.
    # async with engine.begin() as conn:
    #     print("Dropping all tables after test session...")
    #     await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()

    # Restore original MIGRATE_ON_INIT value
    if original_migrate_on_init is None:
        del os.environ["MIGRATE_ON_INIT"]
    else:
        os.environ["MIGRATE_ON_INIT"] = original_migrate_on_init


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional database session for each test function."""
    async_session_local = sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_local() as session:
        # Begin a transaction
        await session.begin_nested() # or session.begin() if not using nested transactions

        yield session

        # Rollback the transaction to ensure test isolation
        await session.rollback()
        await session.close()


@pytest.fixture(scope="function")
def client(db_session: AsyncSession) -> Iterator[TestClient]:
    """Provides a TestClient instance for making API requests."""
    # Override the app's DB dependency to use the test session
    # This requires your FastAPI app to have a way to override dependencies,
    # e.g., using `app.dependency_overrides`.
    # For now, assuming the app will pick up the test DB via environment or direct patching if needed.
    # If your app uses `Depends(get_db_session)`, you'd override `get_db_session`.
    # This setup assumes the app's DB connection will use the TEST_DATABASE_URL implicitly
    # or that the DBService within the app is patched/configured for tests.
    # A more robust way is to override dependency in app:
    # from bot.api.dependencies import get_db_session # Assuming this is your dependency
    # async def override_get_db_session():
    #     yield db_session
    # app.dependency_overrides[get_db_session] = override_get_db_session

    # For this test, we'll assume the test database URL is picked up by the app's DBService
    # when it initializes, possibly through environment variables or a test configuration.
    # This is simpler if the DBService uses TEST_DATABASE_URL when MIGRATE_ON_INIT is true.

    with TestClient(app) as c:
        yield c

    # if get_db_session in app.dependency_overrides: # Clean up override
    #    del app.dependency_overrides[get_db_session]


# --- Test Data ---
TEST_GUILD_ID_ALPHA = "guild_alpha_123"
TEST_GUILD_ID_BETA = "guild_beta_456"
NEW_GUILD_ID = "new_guild_789"

PLAYER_DATA_ALPHA_1 = {"discord_id": "1111", "name_i18n": {"en": "PlayerAlpha1"}, "guild_id": TEST_GUILD_ID_ALPHA, "current_location_id": "some_loc_alpha"}
PLAYER_DATA_BETA_1 = {"discord_id": "2222", "name_i18n": {"en": "PlayerBeta1"}, "guild_id": TEST_GUILD_ID_BETA, "current_location_id": "some_loc_beta"}


# --- Helper Functions ---
async def _ensure_guild_initialized(client: TestClient, guild_id: str):
    """Helper to initialize a guild via API if not already done."""
    # Check if already initialized (e.g., by trying to get its config)
    response = client.get(f"/api/v1/guilds/{guild_id}/config/")
    if response.status_code == 404 or response.status_code == 200 and not response.json().get("config_data"): # 404 if RulesConfig doesn't exist yet
        init_response = client.post(f"/api/v1/guilds/{guild_id}/initialize")
        if init_response.status_code != 200:
            pytest.fail(f"Failed to initialize guild {guild_id} for testing: {init_response.text}")
        print(f"Helper: Guild {guild_id} initialized for test.")
    elif response.status_code == 200:
        print(f"Helper: Guild {guild_id} appears to be already initialized.")
    else:
         pytest.fail(f"Helper: Unexpected status {response.status_code} when checking guild {guild_id} init state: {response.text}")


# --- Test Classes ---

@pytest.mark.asyncio
class TestGuildContext:

    async def test_guild_initialization_api(self, client: TestClient, db_session: AsyncSession):
        """Test the /initialize endpoint for a new guild."""
        response = client.post(f"/api/v1/guilds/{NEW_GUILD_ID}/initialize")
        assert response.status_code == 200
        assert "successfully initialized" in response.json()["message"].lower()

        # Verify DB records
        rules_cfg = await db_session.get(RulesConfig, NEW_GUILD_ID)
        assert rules_cfg is not None
        assert "default_language" in rules_cfg.config_data

        expected_loc_static_name = DEFAULT_LOCATION_STATIC_NAME_FORMAT.format(NEW_GUILD_ID)
        loc_stmt = select(Location).where(Location.guild_id == NEW_GUILD_ID, Location.static_name == expected_loc_static_name)
        loc_res = await db_session.execute(loc_stmt)
        loc = loc_res.scalar_one_or_none()
        assert loc is not None
        assert loc.name_i18n.get("en") == DEFAULT_LOCATION_EN_NAME

        faction_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == NEW_GUILD_ID, GeneratedFaction.name_i18n['en'].astext == DEFAULT_FACTION_EN_NAME)
        faction_res = await db_session.execute(faction_stmt)
        faction = faction_res.scalar_one_or_none()
        assert faction is not None

    async def test_initialize_existing_guild_api_no_force(self, client: TestClient, db_session: AsyncSession):
        """Test re-initializing an existing guild via API without force."""
        await _ensure_guild_initialized(client, TEST_GUILD_ID_ALPHA) # Ensure it's initialized once

        response = client.post(f"/api/v1/guilds/{TEST_GUILD_ID_ALPHA}/initialize") # No force
        assert response.status_code == 200 # Or a specific status code for "already initialized"
        assert "already initialized" in response.json()["message"].lower() or "skipped" in response.json()["message"].lower()

    async def test_initialize_existing_guild_api_with_force(self, client: TestClient, db_session: AsyncSession):
        """Test re-initializing an existing guild via API with force."""
        await _ensure_guild_initialized(client, TEST_GUILD_ID_ALPHA)

        # Optionally, make a change to verify it gets reset
        rules_cfg_before = await db_session.get(RulesConfig, TEST_GUILD_ID_ALPHA)
        original_lang = rules_cfg_before.config_data.get("default_language")
        modified_data = rules_cfg_before.config_data.copy()
        modified_data["default_language"] = "xx"
        rules_cfg_before.config_data = modified_data
        db_session.add(rules_cfg_before) # For SQLAlchemy 2.0 ORM objects
        await db_session.commit()

        response = client.post(f"/api/v1/guilds/{TEST_GUILD_ID_ALPHA}/initialize?force_reinitialize=true")
        assert response.status_code == 200
        json_response = response.json()
        assert "successfully re-initialized" in json_response["message"].lower() or "successfully initialized" in json_response["message"].lower()

        rules_cfg_after = await db_session.get(RulesConfig, TEST_GUILD_ID_ALPHA)
        assert rules_cfg_after.config_data.get("default_language") == "en" # Should reset to 'en'
        assert rules_cfg_after.config_data.get("default_language") == original_lang # Check it reset to original default


    async def test_create_player_and_check_isolation(self, client: TestClient, db_session: AsyncSession):
        """Create a player in one guild, verify it's retrievable for that guild but not for another."""
        await _ensure_guild_initialized(client, TEST_GUILD_ID_ALPHA)
        await _ensure_guild_initialized(client, TEST_GUILD_ID_BETA)

        # Create player in Guild Alpha
        player_alpha_payload = {"discord_id": "useralpha001", "name_i18n": {"en": "Player Alpha One"}}
        response_alpha_create = client.post(f"/api/v1/guilds/{TEST_GUILD_ID_ALPHA}/players/", json=player_alpha_payload)
        assert response_alpha_create.status_code == 201 # Assuming 201 Created
        player_alpha_created_data = response_alpha_create.json()
        player_alpha_id = player_alpha_created_data.get("id")
        assert player_alpha_id is not None

        # Verify player in Guild Alpha
        response_alpha_get = client.get(f"/api/v1/guilds/{TEST_GUILD_ID_ALPHA}/players/{player_alpha_id}")
        assert response_alpha_get.status_code == 200
        assert response_alpha_get.json()["id"] == player_alpha_id
        assert response_alpha_get.json()["name_i18n"]["en"] == "Player Alpha One"

        # Verify player is NOT in Guild Beta with Guild Alpha's player ID
        response_beta_get_alpha_player = client.get(f"/api/v1/guilds/{TEST_GUILD_ID_BETA}/players/{player_alpha_id}")
        assert response_beta_get_alpha_player.status_code == 404 # Not Found

        # Verify player is NOT in Guild Alpha using a different guild's player ID (if one existed)
        # This part is less about isolation and more about correct ID lookup.
        # For now, the check above (alpha player in beta guild) is the core isolation test.

    async def test_player_endpoint_invalid_guild_id(self, client: TestClient):
        """Test player endpoint behavior with a non-existent or malformed guild_id."""
        non_existent_guild_id = "guild_does_not_exist_xyz"
        player_payload = {"discord_id": "userinvalid001", "name_i18n": {"en": "Player Invalid"}}

        response_create = client.post(f"/api/v1/guilds/{non_existent_guild_id}/players/", json=player_payload)
        # Depending on API design, this might be 404 (guild not found) or 422 (if guild_id format is invalid)
        # or even 201 if the API auto-initializes guilds on first use (less likely for this test's purpose).
        # Let's assume it should be 404 if the guild context is strict.
        # If initialize_new_guild is called by a dependency for missing guilds, this might pass or fail differently.
        # For this test, we assume no auto-initialization from player endpoint.
        assert response_create.status_code == 404 # Or 422 if path validation is stricter for format

        response_get_list = client.get(f"/api/v1/guilds/{non_existent_guild_id}/players/")
        assert response_get_list.status_code == 404 # Or 422

        response_get_specific = client.get(f"/api/v1/guilds/{non_existent_guild_id}/players/some_player_id")
        assert response_get_specific.status_code == 404 # Or 422

    async def test_update_rules_config_and_check_isolation(self, client: TestClient, db_session: AsyncSession):
        """Update config for one guild, verify changes, and confirm another guild's config remains default/separate."""
        await _ensure_guild_initialized(client, TEST_GUILD_ID_ALPHA)
        await _ensure_guild_initialized(client, TEST_GUILD_ID_BETA)

        # Get initial config for Beta to compare later
        response_beta_initial_config = client.get(f"/api/v1/guilds/{TEST_GUILD_ID_BETA}/config/")
        assert response_beta_initial_config.status_code == 200
        beta_initial_config_data = response_beta_initial_config.json()["config_data"]

        # Update config for Alpha
        alpha_new_config_payload = {"config_data": {"default_language": "la", "command_prefixes": ["$", "%"]}}
        response_alpha_update = client.put(f"/api/v1/guilds/{TEST_GUILD_ID_ALPHA}/config/", json=alpha_new_config_payload)
        assert response_alpha_update.status_code == 200
        alpha_updated_config_data = response_alpha_update.json()["config_data"]
        assert alpha_updated_config_data["default_language"] == "la"
        assert "$" in alpha_updated_config_data["command_prefixes"]

        # Verify Alpha's config is indeed updated
        response_alpha_get_updated = client.get(f"/api/v1/guilds/{TEST_GUILD_ID_ALPHA}/config/")
        assert response_alpha_get_updated.status_code == 200
        assert response_alpha_get_updated.json()["config_data"]["default_language"] == "la"

        # Verify Beta's config has not changed
        response_beta_get_after = client.get(f"/api/v1/guilds/{TEST_GUILD_ID_BETA}/config/")
        assert response_beta_get_after.status_code == 200
        beta_config_data_after = response_beta_get_after.json()["config_data"]
        assert beta_config_data_after == beta_initial_config_data
        assert beta_config_data_after["default_language"] == "en" # Default from initializer

    async def test_rules_config_endpoint_invalid_guild_id(self, client: TestClient):
        """Test RulesConfig endpoint behavior with a non-existent guild_id."""
        non_existent_guild_id = "guild_does_not_exist_xyz"

        response_get = client.get(f"/api/v1/guilds/{non_existent_guild_id}/config/")
        assert response_get.status_code == 404 # Assuming 404 if guild/config not found

        config_payload = {"config_data": {"default_language": "es"}}
        response_put = client.put(f"/api/v1/guilds/{non_existent_guild_id}/config/", json=config_payload)
        # This might be 404 (if guild must exist) or could be 200/201 if it creates the config.
        # For strict guild context, 404 is expected if the guild itself is unknown.
        # If `initialize_new_guild` is a dependency that auto-creates, then it might be 200.
        # Let's assume 404 for now.
        assert response_put.status_code == 404
