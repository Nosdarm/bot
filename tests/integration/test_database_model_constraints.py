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
    MobileGroup, PlayerNpcMemory, QuestStepTable, Relationship, NPC, Questline, GuildConfig,
    # Added newly relevant models for guild_id checks
    UserSettings, WorldState, LocationTemplate, GeneratedLocation, Character, Party, GeneratedNpc, GlobalNpc,
    ItemTemplate, Item, Inventory, ItemProperty, Shop, Currency, QuestTable as DBQuestTable, # Renamed to avoid pytest conflict
    Combat, Ability, Spell, Skill, Status, CraftingRecipe, CraftingQueue,
    Timer, Event, PendingConflict, StoryLog,
    RPGCharacter, NewItem, NewCharacterItem # Models that were modified
)
from bot.database.models.dialogue_model import Dialogue # Import Dialogue separately
from bot.models.pending_generation import PendingGeneration # Import PendingGeneration separately


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
# Ensure these are unique for each test session if tests run in parallel or don't clean up fully.
# The current fixture setup (rollback per function, create_all per session) should handle this.
UNIQUE_GUILD_ID_1 = str(uuid.uuid4())
UNIQUE_GUILD_ID_2 = str(uuid.uuid4())
NON_EXISTENT_GUILD_ID = str(uuid.uuid4()) # For FK tests
DISCORD_ID_1 = "discord_user_1"
DISCORD_ID_2 = "discord_user_2"

# Helper fixture to ensure GuildConfig exists for FK tests
@pytest_asyncio.fixture(scope="function")
async def ensure_guild_configs(db_session: AsyncSession):
    gc1 = GuildConfig(guild_id=UNIQUE_GUILD_ID_1, bot_language="en")
    gc2 = GuildConfig(guild_id=UNIQUE_GUILD_ID_2, bot_language="ru")
    db_session.add_all([gc1, gc2])
    await db_session.commit()
    return UNIQUE_GUILD_ID_1, UNIQUE_GUILD_ID_2


# --- Generic Guild ID Constraint Test Functions ---

async def _test_guild_id_not_nullable(db_session: AsyncSession, model_class, defaults: dict):
    """Generic test for guild_id NOT NULL constraint."""
    with pytest.raises(IntegrityError, match=r".*(violates not-null constraint|NOT NULL constraint failed).*guild_id"):
        instance_data = defaults.copy()
        instance_data['guild_id'] = None
        instance = model_class(**instance_data)
        db_session.add(instance)
        await db_session.flush()

async def _test_guild_id_foreign_key(db_session: AsyncSession, model_class, defaults: dict):
    """Generic test for guild_id FOREIGN KEY constraint."""
    with pytest.raises(IntegrityError, match=r".*(foreign key constraint|FOREIGN KEY constraint failed).*guild_configs"):
        instance_data = defaults.copy()
        instance_data['guild_id'] = NON_EXISTENT_GUILD_ID # Assumes this guild_id does not exist
        instance = model_class(**instance_data)
        db_session.add(instance)
        await db_session.flush()

# --- Test Classes for Each Model (or groups of models) ---

@pytest.mark.asyncio
class TestPlayerModelConstraints:
    MODEL_DEFAULTS = {
        "id": lambda: str(uuid.uuid4()),
        "discord_id": lambda: str(uuid.uuid4()), # Make unique per call
        "name_i18n": {"en": "Test Player"},
        "is_active": True
    }

    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Player, {
            **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })

    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Player, {
            **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })

    async def test_player_discord_id_guild_id_unique(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        player_id_1 = self.MODEL_DEFAULTS["id"]()
        discord_id_shared = self.MODEL_DEFAULTS["discord_id"]()

        player1 = Player(
            id=player_id_1, discord_id=discord_id_shared,
            name_i18n=self.MODEL_DEFAULTS["name_i18n"],
            guild_id=guild1_id, is_active=True
        )
        db_session.add(player1)
        await db_session.commit()

        with pytest.raises(IntegrityError, match=r".*(unique constraint|UNIQUE constraint failed).*uq_player_discord_guild"):
            player2_same_guild = Player(
                id=self.MODEL_DEFAULTS["id"](), discord_id=discord_id_shared,
                name_i18n={"en": "Player 2 Same Guild"},
                guild_id=guild1_id, is_active=True
            )
            db_session.add(player2_same_guild)
            await db_session.flush()


@pytest.mark.asyncio
class TestLocationModelConstraints:
    MODEL_DEFAULTS = {
        "id": lambda: str(uuid.uuid4()),
        "name_i18n": {"en": "Test Location"},
        "descriptions_i18n": {"en": "A place"},
        "type_i18n": {"en": "Generic"},
        "is_active": True
    }
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Location, {
             **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Location, {
            **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })
    async def test_location_guild_static_id_unique(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        static_id_shared = "shared_static_loc"
        loc1_data = {**{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "guild_id": guild1_id, "static_id": static_id_shared}
        loc1 = Location(**loc1_data)
        db_session.add(loc1)
        await db_session.commit()

        with pytest.raises(IntegrityError, match=r".*(unique constraint|UNIQUE constraint failed).*uq_location_guild_static_id"):
            loc2_data = {**{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "id": str(uuid.uuid4()), "guild_id": guild1_id, "static_id": static_id_shared}
            loc2 = Location(**loc2_data)
            db_session.add(loc2)
            await db_session.flush()

    async def test_location_i18n_fields_storage(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        loc_id = str(uuid.uuid4())
        name_i18n_data = {"en": "The Tavern", "ru": "Таверна"}
        descriptions_i18n_data = {"en": "A cozy place.", "ru": "Уютное место."}
        type_i18n_data = {"en": "Building", "ru": "Здание"}

        new_loc = Location(
            id=loc_id,
            guild_id=guild1_id,
            name_i18n=name_i18n_data,
            descriptions_i18n=descriptions_i18n_data,
            type_i18n=type_i18n_data,
            is_active=True
        )
        db_session.add(new_loc)
        await db_session.commit()

        retrieved_loc = await db_session.get(Location, loc_id)
        assert retrieved_loc is not None
        assert retrieved_loc.name_i18n == name_i18n_data
        assert retrieved_loc.descriptions_i18n == descriptions_i18n_data
        assert retrieved_loc.type_i18n == type_i18n_data
        assert retrieved_loc.guild_id == guild1_id


@pytest.mark.asyncio
class TestRulesConfigModelConstraints:
    MODEL_DEFAULTS = {
        "id": lambda: str(uuid.uuid4()),
        "key": "test_rule",
        "value": {"en": "test_value"}
    }
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, RulesConfig, {
             **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, RulesConfig, {
            **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })
    async def test_rules_config_guild_id_key_unique(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        key_shared = "shared_rule_key"
        rule1 = RulesConfig(**{**{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "guild_id": guild1_id, "key": key_shared})
        db_session.add(rule1)
        await db_session.commit()

        with pytest.raises(IntegrityError, match=r".*(unique constraint|UNIQUE constraint failed).*uq_guild_rule_key"):
            rule2 = RulesConfig(**{**{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "id": str(uuid.uuid4()), "guild_id": guild1_id, "key": key_shared})
            db_session.add(rule2)
            await db_session.flush()

# --- Tests for RPGCharacter (modified model) ---
@pytest.mark.asyncio
class TestRPGCharacterModelConstraints:
    MODEL_DEFAULTS = {
        "id": lambda: uuid.uuid4(), # Uses UUID
        "name": "Test RPGChar",
        "class_name": "Warrior",
        "level": 1,
        "health": 100,
        "mana": 50
    }
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, RPGCharacter, {
             **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, RPGCharacter, {
            **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })

# --- Tests for NewItem (modified model) ---
@pytest.mark.asyncio
class TestNewItemModelConstraints:
    MODEL_DEFAULTS = {
        "id": lambda: uuid.uuid4(), # Uses UUID
        "name": "Test NewItem",
        "item_type": "Weapon"
    }
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, NewItem, {
             **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, NewItem, {
            **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}
        })
    async def test_new_item_guild_name_unique(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        name_shared = "Shared NewItem Name"
        item1 = NewItem(**{**{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "guild_id": guild1_id, "name": name_shared})
        db_session.add(item1)
        await db_session.commit()

        with pytest.raises(IntegrityError, match=r".*(unique constraint|UNIQUE constraint failed).*uq_new_item_guild_name"):
            item2 = NewItem(**{**{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "id": uuid.uuid4(), "guild_id": guild1_id, "name": name_shared})
            db_session.add(item2)
            await db_session.flush()


# --- Tests for NewCharacterItem (modified model) ---
@pytest.mark.asyncio
class TestNewCharacterItemModelConstraints:
    # Helper to create Character and NewItem for FKs
    async def _setup_char_item_deps(self, db_session: AsyncSession, guild_id: str):
        char_id = str(uuid.uuid4())
        # Need a Player for Character's FK
        player_id = str(uuid.uuid4())
        temp_player = Player(id=player_id, discord_id=str(uuid.uuid4()), guild_id=guild_id, name_i18n={"en":"Temp Player for CharItem"})
        db_session.add(temp_player)
        await db_session.flush()

        test_char = Character(id=char_id, player_id=player_id, guild_id=guild_id, name_i18n={"en": "Char for NewItemLink"})
        db_session.add(test_char)

        new_item_id = uuid.uuid4()
        test_new_item = NewItem(id=new_item_id, name="Dep NewItem", item_type="Misc", guild_id=guild_id)
        db_session.add(test_new_item)
        await db_session.commit()
        return char_id, new_item_id

    MODEL_DEFAULTS = {
        "id": lambda: uuid.uuid4(), # Uses UUID
        "quantity": 1
    }
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        char_id, item_id = await self._setup_char_item_deps(db_session, guild1_id)
        await _test_guild_id_not_nullable(db_session, NewCharacterItem, {
             **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "character_id": char_id, "item_id": item_id
        })
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        char_id, item_id = await self._setup_char_item_deps(db_session, guild1_id)
        await _test_guild_id_foreign_key(db_session, NewCharacterItem, {
            **{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "character_id": char_id, "item_id": item_id
        })

# --- Add similar test classes for other models ---
# Example for WorldState (includes unique guild_id check)
@pytest.mark.asyncio
class TestWorldStateModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "global_narrative_state_i18n": {}, "current_era_i18n": {}, "custom_flags": {}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, WorldState, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, WorldState, self.MODEL_DEFAULTS)
    async def test_world_state_guild_id_unique(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        ws1 = WorldState(**{**self.MODEL_DEFAULTS, "guild_id": guild1_id, "id": str(uuid.uuid4())})
        db_session.add(ws1)
        await db_session.commit()
        with pytest.raises(IntegrityError, match=r".*(unique constraint|UNIQUE constraint failed).*world_states_guild_id_key"): # Adjust match if key name differs
            ws2 = WorldState(**{**self.MODEL_DEFAULTS, "guild_id": guild1_id, "id": str(uuid.uuid4())})
            db_session.add(ws2)
            await db_session.flush()

# --- Test classes for models with guild_id and static_id unique constraints ---
# Ability, Status
@pytest.mark.asyncio
class TestAbilityModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Test Ability"}, "description_i18n": {"en":"Desc"}, "effect_i18n": {}, "type_i18n":{}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Ability, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Ability, self.MODEL_DEFAULTS)
    async def test_ability_guild_static_id_unique(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        static_id_shared = "shared_ability_static"
        ab1 = Ability(**{**self.MODEL_DEFAULTS, "guild_id": guild1_id, "static_id": static_id_shared})
        db_session.add(ab1)
        await db_session.commit()
        with pytest.raises(IntegrityError, match=r".*(unique constraint|UNIQUE constraint failed).*uq_ability_guild_static_id"):
            ab2 = Ability(**{**self.MODEL_DEFAULTS, "id": str(uuid.uuid4()), "guild_id": guild1_id, "static_id": static_id_shared})
            db_session.add(ab2)
            await db_session.flush()

# TODO: Add similar test classes for:
# UserSettings, GeneratedLocation, LocationTemplate, Character, Party, NPC, GeneratedNpc, GlobalNpc,
# ItemTemplate, Item, Inventory (check uq_player_item_inventory with guild_id context), ItemProperty,
# Shop, Currency, DBQuestTable (QuestTable), GeneratedQuest (already has some), Questline, QuestStepTable (already has some),
# Combat, Spell, Skill, Status (similar to Ability), CraftingRecipe, CraftingQueue (PK includes guild_id),
# Timer, Event, PendingConflict, StoryLog, Dialogue, PendingGeneration.

# For models where guild_id is part of a multi-column unique constraint (e.g. Relationship),
# those specific unique constraint tests (like test_rules_config_guild_id_key_unique) are good.

# The generic tests _test_guild_id_not_nullable and _test_guild_id_foreign_key can be applied to most.

# --- UserSettings ---
@pytest.mark.asyncio
class TestUserSettingsModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: None, "user_id": lambda: str(uuid.uuid4()), "language_code": "en"} # id is autoincrement
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        # Need a player for UserSettings FK to players table
        guild1_id, _ = ensure_guild_configs
        player_id = str(uuid.uuid4())
        p = Player(id=player_id, discord_id=self.MODEL_DEFAULTS["user_id"](), guild_id=guild1_id, name_i18n={"en":"PlayerForUserSettings"})
        db_session.add(p)
        await db_session.commit()
        await _test_guild_id_not_nullable(db_session, UserSettings, {**self.MODEL_DEFAULTS, "user_id": p.discord_id})

    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        player_id = str(uuid.uuid4())
        p = Player(id=player_id, discord_id=self.MODEL_DEFAULTS["user_id"](), guild_id=guild1_id, name_i18n={"en":"PlayerForUserSettingsFK"})
        db_session.add(p)
        await db_session.commit()
        await _test_guild_id_foreign_key(db_session, UserSettings, {**self.MODEL_DEFAULTS, "user_id": p.discord_id})

# --- GeneratedLocation ---
@pytest.mark.asyncio
class TestGeneratedLocationModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en": "GenLoc"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, GeneratedLocation, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, GeneratedLocation, self.MODEL_DEFAULTS)

# --- LocationTemplate ---
@pytest.mark.asyncio
class TestLocationTemplateModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name": lambda: f"Template_{str(uuid.uuid4())[:4]}"}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, LocationTemplate, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, LocationTemplate, self.MODEL_DEFAULTS)

# --- Character ---
@pytest.mark.asyncio
class TestCharacterModelConstraints:
    async def _setup_player_for_char(self, db_session: AsyncSession, guild_id: str):
        player_id = str(uuid.uuid4())
        p = Player(id=player_id, discord_id=str(uuid.uuid4()), guild_id=guild_id, name_i18n={"en":"PlayerForChar"})
        db_session.add(p)
        await db_session.commit()
        return player_id

    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"CharName"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        player_id = await self._setup_player_for_char(db_session, guild1_id)
        await _test_guild_id_not_nullable(db_session, Character, {**self.MODEL_DEFAULTS, "player_id": player_id})
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        player_id = await self._setup_player_for_char(db_session, guild1_id)
        await _test_guild_id_foreign_key(db_session, Character, {**self.MODEL_DEFAULTS, "player_id": player_id})

# --- Party ---
@pytest.mark.asyncio
class TestPartyModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"The Crew"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Party, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Party, self.MODEL_DEFAULTS)

# --- NPC ---
@pytest.mark.asyncio
class TestNPCModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Old Man Willow"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, NPC, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, NPC, self.MODEL_DEFAULTS)

# --- GeneratedNpc ---
@pytest.mark.asyncio
class TestGeneratedNpcModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"AI NPC"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, GeneratedNpc, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, GeneratedNpc, self.MODEL_DEFAULTS)

# --- GlobalNpc ---
@pytest.mark.asyncio
class TestGlobalNpcModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Wandering Trader"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, GlobalNpc, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, GlobalNpc, self.MODEL_DEFAULTS)

# --- ItemTemplate ---
@pytest.mark.asyncio
class TestItemTemplateModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Iron Sword Blueprint"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, ItemTemplate, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, ItemTemplate, self.MODEL_DEFAULTS)

# --- Item ---
@pytest.mark.asyncio
class TestItemModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Rusty Dagger"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Item, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Item, self.MODEL_DEFAULTS)

# --- Inventory ---
@pytest.mark.asyncio
class TestInventoryModelConstraints:
    async def _setup_inv_deps(self, db_session: AsyncSession, guild_id: str):
        player_id = str(uuid.uuid4())
        p = Player(id=player_id, discord_id=str(uuid.uuid4()), guild_id=guild_id, name_i18n={"en":"PlayerForInv"})
        db_session.add(p)
        item_id = str(uuid.uuid4())
        i = Item(id=item_id, guild_id=guild_id, name_i18n={"en":"ItemForInv"})
        db_session.add(i)
        await db_session.commit()
        return player_id, item_id

    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "quantity": 1}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        player_id, item_id = await self._setup_inv_deps(db_session, guild1_id)
        await _test_guild_id_not_nullable(db_session, Inventory, {**self.MODEL_DEFAULTS, "player_id": player_id, "item_id": item_id})
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        player_id, item_id = await self._setup_inv_deps(db_session, guild1_id)
        await _test_guild_id_foreign_key(db_session, Inventory, {**self.MODEL_DEFAULTS, "player_id": player_id, "item_id": item_id})
    # uq_player_item_inventory is on (player_id, item_id) - guild_id is implicitly checked by player_id's guild context.

# --- ItemProperty ---
@pytest.mark.asyncio
class TestItemPropertyModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en": "Shiny"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, ItemProperty, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, ItemProperty, self.MODEL_DEFAULTS)

# --- Shop ---
@pytest.mark.asyncio
class TestShopModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en": "General Store"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Shop, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Shop, self.MODEL_DEFAULTS)

# --- Currency ---
@pytest.mark.asyncio
class TestCurrencyModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en": "Gold Coin"}, "exchange_rate_to_standard": 1.0}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Currency, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Currency, self.MODEL_DEFAULTS)

# --- DBQuestTable (QuestTable) ---
@pytest.mark.asyncio
class TestDBQuestTableModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en": "The Main Quest"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, DBQuestTable, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, DBQuestTable, self.MODEL_DEFAULTS)

# --- Questline ---
@pytest.mark.asyncio
class TestQuestlineModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en": "The Dragon Saga"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Questline, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Questline, self.MODEL_DEFAULTS)

# --- Combat ---
@pytest.mark.asyncio
class TestCombatModelConstraints:
    async def _setup_combat_deps(self, db_session: AsyncSession, guild_id: str):
        loc_id = str(uuid.uuid4())
        loc = Location(id=loc_id, guild_id=guild_id, name_i18n={"en":"Battlefield"}, descriptions_i18n={"en":"Desc"}, type_i18n={"en":"CombatZone"})
        db_session.add(loc)
        await db_session.commit()
        return loc_id

    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "status": "ongoing", "participants": []}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        loc_id = await self._setup_combat_deps(db_session, guild1_id)
        await _test_guild_id_not_nullable(db_session, Combat, {**self.MODEL_DEFAULTS, "location_id": loc_id})
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        loc_id = await self._setup_combat_deps(db_session, guild1_id)
        await _test_guild_id_foreign_key(db_session, Combat, {**self.MODEL_DEFAULTS, "location_id": loc_id})

# --- Spell ---
@pytest.mark.asyncio
class TestSpellModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Fireball"}, "description_i18n": {"en":"Boom"}, "effect_i18n": {}, "type_i18n":{}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Spell, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Spell, self.MODEL_DEFAULTS)

# --- Skill ---
@pytest.mark.asyncio
class TestSkillModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Lockpicking"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Skill, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Skill, self.MODEL_DEFAULTS)

# --- Status ---
@pytest.mark.asyncio
class TestStatusModelConstraints: # Similar to Ability
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name": "Poisoned", "status_type": "ailment", "target_id": "dummy_char", "target_type": "character", "static_id": lambda: f"status_{str(uuid.uuid4())[:4]}"}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Status, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Status, self.MODEL_DEFAULTS)
    async def test_status_guild_static_id_unique(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        static_id_shared = self.MODEL_DEFAULTS["static_id"]()
        s1_data = {**{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "guild_id": guild1_id, "static_id": static_id_shared}
        s1 = Status(**s1_data)
        db_session.add(s1)
        await db_session.commit()
        with pytest.raises(IntegrityError, match=r".*(unique constraint|UNIQUE constraint failed).*uq_status_guild_static_id"):
            s2_data = {**{k: v() if callable(v) else v for k,v in self.MODEL_DEFAULTS.items()}, "id": str(uuid.uuid4()), "guild_id": guild1_id, "static_id": static_id_shared}
            s2 = Status(**s2_data)
            db_session.add(s2)
            await db_session.flush()

# --- CraftingRecipe ---
@pytest.mark.asyncio
class TestCraftingRecipeModelConstraints:
    async def _setup_crafting_deps(self, db_session: AsyncSession, guild_id: str):
        item_template_id = str(uuid.uuid4())
        it = ItemTemplate(id=item_template_id, guild_id=guild_id, name_i18n={"en":"Output Item Template"})
        db_session.add(it)
        await db_session.commit()
        return item_template_id

    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Health Potion Recipe"}, "ingredients_json": [], "output_quantity": 1}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        out_id = await self._setup_crafting_deps(db_session, guild1_id)
        await _test_guild_id_not_nullable(db_session, CraftingRecipe, {**self.MODEL_DEFAULTS, "output_item_template_id": out_id})
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        out_id = await self._setup_crafting_deps(db_session, guild1_id)
        await _test_guild_id_foreign_key(db_session, CraftingRecipe, {**self.MODEL_DEFAULTS, "output_item_template_id": out_id})


# --- Timer ---
@pytest.mark.asyncio
class TestTimerModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "type": "test_timer", "ends_at": 12345.67}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Timer, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Timer, self.MODEL_DEFAULTS)

# --- Event ---
@pytest.mark.asyncio
class TestEventModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en":"Festival of Stars"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Event, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Event, self.MODEL_DEFAULTS)

# --- PendingConflict ---
@pytest.mark.asyncio
class TestPendingConflictModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "conflict_data_json": {"details": "some conflict"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, PendingConflict, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, PendingConflict, self.MODEL_DEFAULTS)

# --- StoryLog ---
@pytest.mark.asyncio
class TestStoryLogModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "event_type": "player_move"}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, StoryLog, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, StoryLog, self.MODEL_DEFAULTS)

# --- Dialogue ---
@pytest.mark.asyncio
class TestDialogueModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "participants": {}, "is_active": True}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Dialogue, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Dialogue, self.MODEL_DEFAULTS)

# --- PendingGeneration ---
@pytest.mark.asyncio
class TestPendingGenerationModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "request_type": "location_description", "status": "pending_generation"} # Using string for enum for simplicity in defaults
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        # Need to import GenerationType and PendingStatus for actual model instantiation
        from bot.models.pending_generation import GenerationType, PendingStatus
        defaults_with_enum = self.MODEL_DEFAULTS.copy()
        defaults_with_enum["request_type"] = GenerationType.LOCATION_DESCRIPTION
        defaults_with_enum["status"] = PendingStatus.PENDING_GENERATION
        await _test_guild_id_not_nullable(db_session, PendingGeneration, defaults_with_enum)

    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        from bot.models.pending_generation import GenerationType, PendingStatus
        defaults_with_enum = self.MODEL_DEFAULTS.copy()
        defaults_with_enum["request_type"] = GenerationType.LOCATION_DESCRIPTION
        defaults_with_enum["status"] = PendingStatus.PENDING_GENERATION
        await _test_guild_id_foreign_key(db_session, PendingGeneration, defaults_with_enum)

# The existing tests for GeneratedFaction, GeneratedQuest, MobileGroup, PlayerNpcMemory, QuestStepTable, Relationship
# already perform CRUD operations which would fail if basic guild_id FKs were violated after ensure_guild_configs.
# We can augment them or trust that their existing structure implicitly tests some of this.
# For explicit NOT NULL and FK checks, the generic helpers are good.
# Adding a few more explicit ones for clarity:

@pytest.mark.asyncio
class TestGeneratedFactionConstraints: # Existing class, add specific guild_id tests
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en": "Test Faction"}, "description_i18n": {"en":"Desc"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, GeneratedFaction, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, GeneratedFaction, self.MODEL_DEFAULTS)

@pytest.mark.asyncio
class TestGeneratedQuestConstraints: # Existing class, add specific guild_id tests
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "title_i18n": {"en": "Test Quest"}, "description_i18n": {"en":"Desc"}}
    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, GeneratedQuest, self.MODEL_DEFAULTS)
    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, GeneratedQuest, self.MODEL_DEFAULTS)

# --- Party ---
@pytest.mark.asyncio
class TestPartyModelConstraints:
    MODEL_DEFAULTS = {"id": lambda: str(uuid.uuid4()), "name_i18n": {"en": "The Awesome Party"}}

    async def test_guild_id_not_nullable(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_not_nullable(db_session, Party, self.MODEL_DEFAULTS)

    async def test_guild_id_foreign_key(self, db_session: AsyncSession, ensure_guild_configs):
        await _test_guild_id_foreign_key(db_session, Party, self.MODEL_DEFAULTS)

    async def test_party_player_ids_json_storage(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        party_id = str(uuid.uuid4())
        player_ids_data = [str(uuid.uuid4()), str(uuid.uuid4())]

        new_party = Party(
            id=party_id,
            guild_id=guild1_id,
            name_i18n={"en": "JSON Party"},
            player_ids_json=player_ids_data # SQLAlchemy JsonVariant should handle list directly
        )
        db_session.add(new_party)
        await db_session.commit()

        retrieved_party = await db_session.get(Party, party_id)
        assert retrieved_party is not None
        assert retrieved_party.player_ids_json == player_ids_data

# --- Character (additional test for collected_actions_json) ---
@pytest.mark.asyncio
class TestCharacterModelJsonFields: # New class to avoid conflict with existing TestCharacterModelConstraints if any
    async def _setup_player_for_char(self, db_session: AsyncSession, guild_id: str):
        player_id = str(uuid.uuid4())
        p = Player(id=player_id, discord_id=str(uuid.uuid4()), guild_id=guild_id, name_i18n={"en":"PlayerForCharJson"})
        db_session.add(p)
        await db_session.commit()
        return player_id

    async def test_character_collected_actions_json_storage(self, db_session: AsyncSession, ensure_guild_configs):
        guild1_id, _ = ensure_guild_configs
        player_id = await self._setup_player_for_char(db_session, guild1_id)
        char_id = str(uuid.uuid4())
        actions_data = [{"action": "look", "target": "door"}, {"action": "move", "direction": "north"}]

        new_char = Character(
            id=char_id,
            player_id=player_id,
            guild_id=guild1_id,
            name_i18n={"en": "CharWithActions"},
            collected_actions_json=actions_data # SQLAlchemy JsonVariant should handle list of dicts
        )
        db_session.add(new_char)
        await db_session.commit()

        retrieved_char = await db_session.get(Character, char_id)
        assert retrieved_char is not None
        assert retrieved_char.collected_actions_json == actions_data
