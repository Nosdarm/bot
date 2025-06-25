import pytest
import pytest_asyncio
import os
from typing import AsyncGenerator
import uuid # For generating unique IDs
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from bot.database.models import (
    Base, Player, Location, RulesConfig, GeneratedFaction, GeneratedQuest,
    MobileGroup, PlayerNpcMemory, QuestStepTable, Relationship, NPC, Questline, GuildConfig
) # Updated QuestStep to QuestStepTable, Added GuildConfig

# --- Test Database Configuration ---
# Fallback to SQLite in-memory for environments where PostgreSQL is not available
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

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
                is_active=True
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
            guild_id=UNIQUE_GUILD_ID_1, is_active=True
        )
        db_session.add(player1)
        await db_session.commit() # Commit to ensure it's in DB for unique check

        # Attempt to create a second player with the same discord_id and guild_id
        with pytest.raises(IntegrityError):
            player2_same_guild = Player(
                id=player_id_2, discord_id=DISCORD_ID_1, name_i18n={"en": "Player 2 Same Guild"},
                guild_id=UNIQUE_GUILD_ID_1, is_active=True
            )
            db_session.add(player2_same_guild)
            await db_session.flush() # Check constraint

        await db_session.rollback() # Rollback the failed attempt explicitly

        # Verify that creating a player with same discord_id but DIFFERENT guild_id is allowed
        player_id_3 = str(uuid.uuid4())
        player3_diff_guild = Player(
            id=player_id_3, discord_id=DISCORD_ID_1, name_i18n={"en": "Player 3 Diff Guild"},
            guild_id=UNIQUE_GUILD_ID_2, is_active=True
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
                key="default_language", value="en" # Corrected
            )
            db_session.add(new_rules_config)
            await db_session.flush()

    async def test_rules_config_guild_id_primary_key(self, db_session: AsyncSession):
        """Attempt to create duplicate RulesConfig entries for the same guild_id, assert IntegrityError."""
        # Create first RulesConfig
        rules_config1 = RulesConfig(
            guild_id=UNIQUE_GUILD_ID_1,
            key="default_language", value="en" # Corrected
        )
        db_session.add(rules_config1)
        await db_session.commit()

        # Attempt to create a second RulesConfig with the same guild_id and key
        with pytest.raises(IntegrityError): # Should fail due to uq_guild_rule_key
            rules_config2_same_guild_key = RulesConfig(
                guild_id=UNIQUE_GUILD_ID_1, # Same guild_id
                key="default_language", value="fr" # Same key
            )
            db_session.add(rules_config2_same_guild_key)
            await db_session.flush() # Check constraint

        await db_session.rollback()

        # Verify that creating RulesConfig for a DIFFERENT guild_id is allowed
        rules_config3_diff_guild = RulesConfig(
            guild_id=UNIQUE_GUILD_ID_2,
            key="default_language", value="es" # Corrected
        )
        db_session.add(rules_config3_diff_guild)
        await db_session.commit() # Should succeed
        assert rules_config3_diff_guild.guild_id == UNIQUE_GUILD_ID_2


# --- Tests for GeneratedFaction ---
@pytest.mark.asyncio
class TestGeneratedFactionModel:
    async def test_create_read_update_delete_faction(self, db_session: AsyncSession):
        faction_id = str(uuid.uuid4())
        guild_id = UNIQUE_GUILD_ID_1

        # Create
        new_faction = GeneratedFaction(
            id=faction_id,
            guild_id=guild_id,
            name_i18n={"en": "Test Faction"},
            description_i18n={"en": "A test faction"}
        )
        db_session.add(new_faction)
        await db_session.commit()
        await db_session.refresh(new_faction)

        assert new_faction.id == faction_id
        assert new_faction.name_i18n["en"] == "Test Faction"

        # Read
        retrieved_faction = await db_session.get(GeneratedFaction, faction_id)
        assert retrieved_faction is not None
        assert retrieved_faction.guild_id == guild_id

        # Update
        retrieved_faction.description_i18n = {"en": "Updated description"}
        db_session.add(retrieved_faction)
        await db_session.commit()
        await db_session.refresh(retrieved_faction)
        assert retrieved_faction.description_i18n["en"] == "Updated description"

        # Delete
        await db_session.delete(retrieved_faction)
        await db_session.commit()
        deleted_faction = await db_session.get(GeneratedFaction, faction_id)
        assert deleted_faction is None

    async def test_faction_guild_id_not_nullable(self, db_session: AsyncSession):
        faction_id = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            new_faction = GeneratedFaction(
                id=faction_id,
                guild_id=None, # Should fail
                name_i18n={"en": "Test Faction"}
            )
            db_session.add(new_faction)
            await db_session.flush()


# --- Tests for GeneratedQuest ---
@pytest.mark.asyncio
class TestGeneratedQuestModel:
    async def test_create_read_update_delete_quest(self, db_session: AsyncSession):
        quest_id = str(uuid.uuid4())
        guild_id = UNIQUE_GUILD_ID_1

        # Create
        new_quest = GeneratedQuest(
            id=quest_id,
            guild_id=guild_id,
            title_i18n={"en": "Test Quest"}, # Corrected from name_i18n
            description_i18n={"en": "A test quest"}
        )
        db_session.add(new_quest)
        await db_session.commit()
        await db_session.refresh(new_quest)
        assert new_quest.id == quest_id

        # Read
        retrieved_quest = await db_session.get(GeneratedQuest, quest_id)
        assert retrieved_quest is not None

        # Update
        retrieved_quest.name_i18n = {"en": "Updated Test Quest"}
        db_session.add(retrieved_quest)
        await db_session.commit()
        await db_session.refresh(retrieved_quest)
        assert retrieved_quest.name_i18n["en"] == "Updated Test Quest"

        # Delete
        await db_session.delete(retrieved_quest)
        await db_session.commit()
        assert await db_session.get(GeneratedQuest, quest_id) is None

    async def test_quest_guild_id_not_nullable(self, db_session: AsyncSession):
        quest_id = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            new_quest = GeneratedQuest(id=quest_id, guild_id=None, title_i18n={"en": "Test Quest"}) # Corrected
            db_session.add(new_quest)
            await db_session.flush()


# --- Tests for MobileGroup ---
@pytest.mark.asyncio
class TestMobileGroupModel:
    async def test_create_read_update_delete_mobile_group(self, db_session: AsyncSession):
        group_id = str(uuid.uuid4())
        guild_id = UNIQUE_GUILD_ID_1
        new_group = MobileGroup(id=group_id, guild_id=guild_id, name_i18n={"en": "Test Group"})
        db_session.add(new_group)
        await db_session.commit()
        await db_session.refresh(new_group)
        assert new_group.id == group_id

        retrieved_group = await db_session.get(MobileGroup, group_id)
        assert retrieved_group is not None
        retrieved_group.name_i18n = {"en": "Updated Group Name"}
        db_session.add(retrieved_group)
        await db_session.commit()
        await db_session.refresh(retrieved_group)
        assert retrieved_group.name_i18n["en"] == "Updated Group Name"

        await db_session.delete(retrieved_group)
        await db_session.commit()
        assert await db_session.get(MobileGroup, group_id) is None

    async def test_mobile_group_guild_id_not_nullable(self, db_session: AsyncSession):
        group_id = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            new_group = MobileGroup(id=group_id, guild_id=None, name_i18n={"en": "Test Group"})
            db_session.add(new_group)
            await db_session.flush()


# --- Tests for PlayerNpcMemory ---
@pytest.mark.asyncio
class TestPlayerNpcMemoryModel:
    # Helper to create a Player and NPC for FK constraints
    async def _setup_player_npc(self, db_session: AsyncSession, guild_id: str):
        player_id = str(uuid.uuid4())
        npc_id = str(uuid.uuid4())

        test_player = Player(id=player_id, discord_id=str(uuid.uuid4()), name_i18n={"en": "Test Player FK"}, guild_id=guild_id, level=1, xp=0, gold=0)
        db_session.add(test_player)

        # Assuming Location is needed for NPC or use a simplified NPC if not.
        # For this test, let's assume NPC doesn't strictly need a location or it's nullable.
        test_npc = NPC(id=npc_id, name_i18n={"en": "Test NPC FK"}, guild_id=guild_id)
        db_session.add(test_npc)

        await db_session.commit()
        return player_id, npc_id

    async def test_create_read_delete_player_npc_memory(self, db_session: AsyncSession):
        memory_id = str(uuid.uuid4())
        guild_id = UNIQUE_GUILD_ID_1
        player_id, npc_id = await self._setup_player_npc(db_session, guild_id)

        new_memory = PlayerNpcMemory(
            id=memory_id,
            guild_id=guild_id,
            player_id=player_id,
            npc_id=npc_id,
            memory_details_i18n={"en": "Met this NPC."}
        )
        db_session.add(new_memory)
        await db_session.commit()
        await db_session.refresh(new_memory)
        assert new_memory.id == memory_id

        retrieved_memory = await db_session.get(PlayerNpcMemory, memory_id)
        assert retrieved_memory is not None
        assert retrieved_memory.player_id == player_id

        await db_session.delete(retrieved_memory)
        await db_session.commit()
        assert await db_session.get(PlayerNpcMemory, memory_id) is None

    async def test_player_npc_memory_guild_id_not_nullable(self, db_session: AsyncSession):
        memory_id = str(uuid.uuid4())
        player_id, npc_id = await self._setup_player_npc(db_session, UNIQUE_GUILD_ID_1)
        with pytest.raises(IntegrityError):
            new_memory = PlayerNpcMemory(id=memory_id, guild_id=None, player_id=player_id, npc_id=npc_id)
            db_session.add(new_memory)
            await db_session.flush()

    async def test_player_npc_memory_player_id_fk_constraint(self, db_session: AsyncSession):
        memory_id = str(uuid.uuid4())
        _, npc_id = await self._setup_player_npc(db_session, UNIQUE_GUILD_ID_1) # We only need npc_id
        with pytest.raises(IntegrityError): # Foreign key violation
            new_memory = PlayerNpcMemory(
                id=memory_id, guild_id=UNIQUE_GUILD_ID_1,
                player_id=str(uuid.uuid4()), # Non-existent player_id
                npc_id=npc_id
            )
            db_session.add(new_memory)
            await db_session.flush()

    async def test_player_npc_memory_npc_id_fk_constraint(self, db_session: AsyncSession):
        memory_id = str(uuid.uuid4())
        player_id, _ = await self._setup_player_npc(db_session, UNIQUE_GUILD_ID_1) # We only need player_id
        with pytest.raises(IntegrityError): # Foreign key violation
            new_memory = PlayerNpcMemory(
                id=memory_id, guild_id=UNIQUE_GUILD_ID_1,
                player_id=player_id,
                npc_id=str(uuid.uuid4()) # Non-existent npc_id
            )
            db_session.add(new_memory)
            await db_session.flush()


# --- Tests for QuestStepTable (formerly QuestStep) ---
@pytest.mark.asyncio
class TestQuestStepTableModel: # Renamed class
    async def _setup_dependencies(self, db_session: AsyncSession, guild_id: str):
        # QuestStepTable depends on GuildConfig (via guild_id FK) and Quests (via quest_id FK)

        # Ensure GuildConfig exists
        guild_config = GuildConfig(guild_id=guild_id, bot_language="en")
        db_session.add(guild_config)

        # Create a Quest
        from bot.database.models import QuestTable # Import QuestTable (formerly Quests)
        quest_id = str(uuid.uuid4())
        test_quest = QuestTable(id=quest_id, guild_id=guild_id, name_i18n={"en": "Test Quest for Steps"})
        db_session.add(test_quest)

        await db_session.commit()
        return quest_id

    async def test_create_read_delete_quest_step(self, db_session: AsyncSession):
        step_id = str(uuid.uuid4())
        guild_id = UNIQUE_GUILD_ID_1
        quest_id = await self._setup_dependencies(db_session, guild_id)

        new_step = QuestStepTable( # Use QuestStepTable
            id=step_id,
            guild_id=guild_id,
            quest_id=quest_id, # Changed from questline_id
            title_i18n={"en": "Step 1"}, # Using new field 'title_i18n'
            description_i18n={"en": "Complete task A."}
        )
        db_session.add(new_step)
        await db_session.commit()
        await db_session.refresh(new_step)
        assert new_step.id == step_id

        retrieved_step = await db_session.get(QuestStepTable, step_id) # Use QuestStepTable
        assert retrieved_step is not None
        assert retrieved_step.quest_id == quest_id

        await db_session.delete(retrieved_step)
        await db_session.commit()
        assert await db_session.get(QuestStepTable, step_id) is None # Use QuestStepTable

    async def test_quest_step_guild_id_not_nullable(self, db_session: AsyncSession):
        step_id = str(uuid.uuid4())
        quest_id = await self._setup_dependencies(db_session, UNIQUE_GUILD_ID_1)
        with pytest.raises(IntegrityError):
            new_step = QuestStepTable(id=step_id, guild_id=None, quest_id=quest_id, title_i18n={"en": "Step Fail"}) # Use QuestStepTable
            db_session.add(new_step)
            await db_session.flush()

    async def test_quest_step_quest_id_fk_constraint(self, db_session: AsyncSession): # Changed from questline_id
        step_id = str(uuid.uuid4())
        # No need to call _setup_dependencies if we are testing with a non-existent quest_id
        # Ensure GuildConfig exists for the guild_id we are using
        guild_config = GuildConfig(guild_id=UNIQUE_GUILD_ID_1, bot_language="en")
        db_session.add(guild_config)
        await db_session.commit()

        with pytest.raises(IntegrityError):
            new_step = QuestStepTable( # Use QuestStepTable
                id=step_id, guild_id=UNIQUE_GUILD_ID_1,
                quest_id=str(uuid.uuid4()), # Non-existent quest_id
                title_i18n={"en": "Step Fail FK"}
            )
            db_session.add(new_step)
            await db_session.flush()


# --- Tests for Relationship ---
@pytest.mark.asyncio
class TestRelationshipModel:
    async def test_create_read_delete_relationship(self, db_session: AsyncSession):
        rel_id = str(uuid.uuid4())
        guild_id = UNIQUE_GUILD_ID_1
        entity1_id = str(uuid.uuid4()) # These can be any string for this model
        entity2_id = str(uuid.uuid4())

        new_rel = Relationship(
            id=rel_id,
            guild_id=guild_id,
            entity1_id=entity1_id, entity1_type="player",
            entity2_id=entity2_id, entity2_type="npc",
            type="friendly", # Corrected
            value=50, # Corrected
            details_json={"status_en": "Good", "status_ru": "Хорошо"} # Optional, example
        )
        db_session.add(new_rel)
        await db_session.commit()
        await db_session.refresh(new_rel)
        assert new_rel.id == rel_id

        retrieved_rel = await db_session.get(Relationship, rel_id)
        assert retrieved_rel is not None
        assert retrieved_rel.entity1_type == "player"

        await db_session.delete(retrieved_rel)
        await db_session.commit()
        assert await db_session.get(Relationship, rel_id) is None

    async def test_relationship_guild_id_not_nullable(self, db_session: AsyncSession):
        rel_id = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            new_rel = Relationship(
                id=rel_id, guild_id=None,
                entity1_id="e1", entity1_type="t1",
                entity2_id="e2", entity2_type="t2"
            )
            db_session.add(new_rel)
            await db_session.flush()

    async def test_relationship_entity_fields_not_nullable(self, db_session: AsyncSession):
        common_args = {"id": str(uuid.uuid4()), "guild_id": UNIQUE_GUILD_ID_1}
        fields_to_test = ["entity1_id", "entity1_type", "entity2_id", "entity2_type"]

        base_data = {
            "entity1_id": "e1_val", "entity1_type": "player",
            "entity2_id": "e2_val", "entity2_type": "npc",
            "type": "neutral", "value": 0 # Corrected
        }

        for field in fields_to_test:
            with pytest.raises(IntegrityError, match=f".*constraint failed.*{field}"): # Check for specific field if DB supports named constraints in error
                data = base_data.copy()
                data[field] = None # Set the current field to None
                # Need to ensure other nullable fields are handled or not relevant for the specific constraint
                # For example, if entity1_id is part of a composite key or other constraint being violated

                # It's safer to test one None at a time for fields defined as nullable=False in the model
                rel = Relationship(**common_args, **data)
                db_session.add(rel)
                await db_session.flush()
                await db_session.rollback() # rollback this specific attempt
