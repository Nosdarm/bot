import pytest
import asyncio
import os
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy import text # For raw SQL execution if needed for checks

from bot.database.sqlite_adapter import SqliteAdapter
from bot.database.models import Base, Player, Location, Party

# Alembic imports for programmatic control
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

TEST_DB_PATH = "test_game.db"
ALEMBIC_INI_PATH = "alembic.ini" # Assuming alembic.ini is in the project root

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="function")
async def test_adapter():
    """
    Fixture to set up and tear down a test database for each test function.
    - Creates a new SQLite file.
    - Applies Alembic migrations to set up the schema.
    - Yields the SqliteAdapter instance.
    - Cleans up the database file after the test.
    """
    # Ensure a clean state
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    if os.path.exists(f"{TEST_DB_PATH}-journal"): # remove journal file if exists
        os.remove(f"{TEST_DB_PATH}-journal")


    adapter = SqliteAdapter(db_path=TEST_DB_PATH)
    await adapter.connect() # This establishes the aiosqlite connection and SQLAlchemy session

    # Configure Alembic programmatically
    alembic_cfg = AlembicConfig(ALEMBIC_INI_PATH)

    # Override sqlalchemy.url to point to the test database
    # The path should be relative to the project root where alembic.ini is, or absolute
    # Assuming TEST_DB_PATH is relative to current working directory (project root)
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{TEST_DB_PATH}")

    # Apply migrations
    # Running alembic upgrade head in a separate thread to avoid event loop conflicts
    # as Alembic commands are typically synchronous.
    # For aiosqlite, env.py is already set up for async.
    await asyncio.to_thread(alembic_command.upgrade, alembic_cfg, "head")

    yield adapter

    # Teardown
    await adapter.close()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    if os.path.exists(f"{TEST_DB_PATH}-journal"):
        os.remove(f"{TEST_DB_PATH}-journal")

@pytest.mark.asyncio
async def test_connection_and_schema(test_adapter: SqliteAdapter):
    """Verify connection, SQLAlchemy session, and table existence."""
    assert test_adapter._conn is not None, "aiosqlite connection should be established."

    session = test_adapter.get_db()
    assert session is not None, "SQLAlchemy session should be available."

    # Check if tables exist by querying sqlite_master or by checking metadata
    expected_tables = Base.metadata.tables.keys()
    assert len(expected_tables) > 0, "No tables defined in Base.metadata."

    async with test_adapter._engine.connect() as conn: # Use the SQLAlchemy engine
        for table_name in expected_tables:
            # Check if table exists in the database
            result = await conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';"))
            row = result.fetchone()
            assert row is not None, f"Table '{table_name}' should exist in the database."
            assert row[0] == table_name, f"Table name mismatch for '{table_name}'."

@pytest.mark.asyncio
async def test_crud_player(test_adapter: SqliteAdapter):
    """Test Create, Read, Update, Delete operations for the Player model."""
    session = test_adapter.get_db()
    assert session is not None

    # Create
    new_player = Player(id="player1", name="Test Player", level=5, xp=1000, gold=50)
    test_adapter.add_object(new_player)

    # Read
    retrieved_player = session.query(Player).filter_by(id="player1").first()
    assert retrieved_player is not None
    assert retrieved_player.name == "Test Player"
    assert retrieved_player.level == 5
    assert retrieved_player.gold == 50

    # Update
    retrieved_player.level = 6
    retrieved_player.gold = 75
    # For SQLAlchemy, simply committing the session after changes is enough if the object is managed.
    # add_object might do this, or we might need a dedicated update_object or direct session.commit()
    session.commit()

    updated_player = session.query(Player).filter_by(id="player1").first()
    assert updated_player is not None
    assert updated_player.level == 6
    assert updated_player.gold == 75

    # Delete
    test_adapter.delete_object(updated_player)
    deleted_player = session.query(Player).filter_by(id="player1").first()
    assert deleted_player is None

@pytest.mark.asyncio
async def test_crud_location(test_adapter: SqliteAdapter):
    """Test Create, Read, Update, Delete operations for the Location model."""
    session = test_adapter.get_db()
    assert session is not None

    # Create
    new_location = Location(id="loc1", static_name="Test Location", descriptions_i18n={"en": "A place for testing."})
    test_adapter.add_object(new_location)

    # Read
    retrieved_location = session.query(Location).filter_by(id="loc1").first()
    assert retrieved_location is not None
    assert retrieved_location.static_name == "Test Location"
    assert retrieved_location.descriptions_i18n == {"en": "A place for testing."}

    # Update
    retrieved_location.static_name = "Updated Test Location"
    session.commit()

    updated_location = session.query(Location).filter_by(id="loc1").first()
    assert updated_location is not None
    assert updated_location.static_name == "Updated Test Location"

    # Delete
    test_adapter.delete_object(updated_location)
    deleted_location = session.query(Location).filter_by(id="loc1").first()
    assert deleted_location is None

@pytest.mark.asyncio
async def test_crud_party(test_adapter: SqliteAdapter):
    """Test Create, Read, Update, Delete operations for the Party model."""
    session = test_adapter.get_db()
    assert session is not None

    # Create
    new_party = Party(id="party1", player_ids=["player1", "player2"], turn_status="active")
    test_adapter.add_object(new_party)

    # Read
    retrieved_party = session.query(Party).filter_by(id="party1").first()
    assert retrieved_party is not None
    assert retrieved_party.player_ids == ["player1", "player2"]
    assert retrieved_party.turn_status == "active"

    # Update
    retrieved_party.turn_status = "inactive"
    session.commit()

    updated_party = session.query(Party).filter_by(id="party1").first()
    assert updated_party is not None
    assert updated_party.turn_status == "inactive"

    # Delete
    test_adapter.delete_object(updated_party)
    deleted_party = session.query(Party).filter_by(id="party1").first()
    assert deleted_party is None

@pytest.mark.asyncio
async def test_player_location_relationship(test_adapter: SqliteAdapter):
    """Test relationship between Player and Location."""
    session = test_adapter.get_db()
    assert session is not None

    # Create related objects
    test_location = Location(id="loc_rel_1", static_name="Relationship Test Location")
    test_player = Player(id="player_rel_1", name="Rel Player", location=test_location)

    # Adding player should also handle location if cascade is set up,
    # or add them separately if not. Current models imply separate adds.
    test_adapter.add_object(test_location)
    test_adapter.add_object(test_player)

    # Read and verify relationship
    retrieved_player = session.query(Player).filter_by(id="player_rel_1").first()
    assert retrieved_player is not None
    assert retrieved_player.location is not None
    assert retrieved_player.location.id == "loc_rel_1"
    assert retrieved_player.location.static_name == "Relationship Test Location"
    assert retrieved_player.current_location_id == "loc_rel_1"


@pytest.mark.asyncio
async def test_party_location_relationship(test_adapter: SqliteAdapter):
    """Test relationship between Party and Location."""
    session = test_adapter.get_db()
    assert session is not None

    test_location = Location(id="loc_rel_2", static_name="Party Location")
    test_party = Party(id="party_rel_1", location=test_location)

    test_adapter.add_object(test_location)
    test_adapter.add_object(test_party)

    retrieved_party = session.query(Party).filter_by(id="party_rel_1").first()
    assert retrieved_party is not None
    assert retrieved_party.location is not None
    assert retrieved_party.location.id == "loc_rel_2"
    assert retrieved_party.current_location_id == "loc_rel_2"


@pytest.mark.asyncio
async def test_player_party_relationship(test_adapter: SqliteAdapter):
    """Test relationship between Player and Party."""
    session = test_adapter.get_db()
    assert session is not None

    test_party = Party(id="party_rel_2", turn_status="testing_player_relation")
    test_player = Player(id="player_rel_2", name="Party Member Player", party=test_party)

    test_adapter.add_object(test_party)
    test_adapter.add_object(test_player)

    retrieved_player = session.query(Player).filter_by(id="player_rel_2").first()
    assert retrieved_player is not None
    assert retrieved_player.party is not None
    assert retrieved_player.party.id == "party_rel_2"
    assert retrieved_player.current_party_id == "party_rel_2"

    # Also check from party side if a players relationship was defined (it's not in current models)
    # retrieved_party = session.query(Party).options(selectinload(Party.players_relationship)).filter_by(id="party_rel_2").first()
    # assert retrieved_party is not None
    # assert any(p.id == "player_rel_2" for p in retrieved_party.players_relationship)

# To run these tests:
# Ensure pytest and pytest-asyncio are installed:
# pip install pytest pytest-asyncio
# Then run:
# pytest tests/database/test_orm_integration.py
