import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from bot.models.pending_generation import PendingGeneration, GenerationType, PendingStatus
from bot.persistence.pending_generation_crud import PendingGenerationCRUD
from bot.database.models import GuildConfig # For creating a valid guild_id FK target

# Assumes db_session fixture is available from conftest.py providing a real session
# to a test PostgreSQL database.

@pytest.fixture
async def test_guild(db_session: AsyncSession) -> GuildConfig:
    """Creates a GuildConfig entry and returns it."""
    guild_id = f"crud_test_guild_{str(uuid.uuid4())[:8]}"
    guild_config = GuildConfig(guild_id=guild_id, bot_language="en")
    db_session.add(guild_config)
    await db_session.commit()
    await db_session.refresh(guild_config)
    return guild_config

@pytest.fixture
def crud(mock_db_service_with_session_factory) -> PendingGenerationCRUD: # Assuming db_service is needed for CRUD init
    # mock_db_service_with_session_factory should provide a DBService instance
    # whose get_session_factory() is correctly set up for tests if CRUD needs it.
    # If PendingGenerationCRUD does not use its self.db_service internally for sessions,
    # then a simpler mock or even None might suffice if session is always passed to methods.
    # The current PendingGenerationCRUD __init__ takes db_service but doesn't use it in methods.
    # So, a simple MagicMock could work.
    return PendingGenerationCRUD(db_service=MagicMock())


@pytest.mark.asyncio
async def test_create_pending_generation(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id
    data = {
        "guild_id": guild_id,
        "request_type": GenerationType.NPC_PROFILE,
        "status": PendingStatus.PENDING_MODERATION,
        "request_params_json": {"npc_idea": "brave knight"},
        "raw_ai_output_text": "{\"name_i18n\": {\"en\": \"Sir Reginald\"}}",
        "parsed_data_json": {"name_i18n": {"en": "Sir Reginald"}},
        "created_by_user_id": "user123"
    }

    record = await crud.create_pending_generation(session=db_session, **data)
    await db_session.commit()

    assert record is not None
    assert record.id is not None
    assert record.guild_id == guild_id
    assert record.request_type == GenerationType.NPC_PROFILE
    assert record.status == PendingStatus.PENDING_MODERATION
    assert record.request_params_json == {"npc_idea": "brave knight"}
    assert record.created_by_user_id == "user123"
    assert record.created_at is not None

@pytest.mark.asyncio
async def test_get_pending_generation_by_id_found(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id
    created_record = await crud.create_pending_generation(
        session=db_session, guild_id=guild_id, request_type=GenerationType.ITEM_PROFILE, status=PendingStatus.PENDING_MODERATION
    )
    await db_session.commit()

    fetched_record = await crud.get_pending_generation_by_id(session=db_session, record_id=created_record.id, guild_id=guild_id)
    assert fetched_record is not None
    assert fetched_record.id == created_record.id

    # Test fetching without guild_id (should still find it if ID is unique)
    fetched_no_guild_filter = await crud.get_pending_generation_by_id(session=db_session, record_id=created_record.id)
    assert fetched_no_guild_filter is not None
    assert fetched_no_guild_filter.id == created_record.id


@pytest.mark.asyncio
async def test_get_pending_generation_by_id_not_found(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    non_existent_id = str(uuid.uuid4())
    fetched_record = await crud.get_pending_generation_by_id(session=db_session, record_id=non_existent_id, guild_id=test_guild.guild_id)
    assert fetched_record is None

@pytest.mark.asyncio
async def test_get_pending_generation_by_id_wrong_guild(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id
    other_guild_id = f"other_guild_{str(uuid.uuid4())[:4]}"
    # Setup for other_guild_id (needed for FK if we were creating a record in it)
    # For this test, we only need to ensure the created_record is not found for other_guild_id

    created_record = await crud.create_pending_generation(
        session=db_session, guild_id=guild_id, request_type=GenerationType.QUEST_FULL, status=PendingStatus.PENDING_MODERATION
    )
    await db_session.commit()

    fetched_record = await crud.get_pending_generation_by_id(session=db_session, record_id=created_record.id, guild_id=other_guild_id)
    assert fetched_record is None


@pytest.mark.asyncio
async def test_update_pending_generation_status(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id
    record = await crud.create_pending_generation(
        session=db_session, guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS, status=PendingStatus.PENDING_MODERATION
    )
    await db_session.commit()

    moderator_id = "mod456"
    notes = "Looks good!"
    updated_record = await crud.update_pending_generation_status(
        session=db_session, record_id=record.id, new_status=PendingStatus.APPROVED,
        guild_id=guild_id, moderated_by_user_id=moderator_id, moderator_notes=notes
    )
    await db_session.commit()
    await db_session.refresh(updated_record) # Ensure all fields are up-to-date from DB

    assert updated_record is not None
    assert updated_record.status == PendingStatus.APPROVED
    assert updated_record.moderated_by_user_id == moderator_id
    assert updated_record.moderator_notes == notes
    assert updated_record.moderated_at is not None

    # Test updating validation issues
    new_issues = [{"loc": ["name"], "type": "value_error", "msg": "Too generic"}]
    updated_again = await crud.update_pending_generation_status(
        session=db_session, record_id=record.id, new_status=PendingStatus.FAILED_VALIDATION,
        guild_id=guild_id, validation_issues_json=new_issues
    )
    await db_session.commit()
    await db_session.refresh(updated_again)

    assert updated_again.status == PendingStatus.FAILED_VALIDATION
    assert updated_again.validation_issues_json == new_issues


@pytest.mark.asyncio
async def test_get_pending_reviews_for_guild(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id

    # Create some records
    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.ITEM_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.QUEST_FULL, status=PendingStatus.APPROVED) # Different status
    # Create for another guild
    other_guild = GuildConfig(guild_id=f"other_g_{str(uuid.uuid4())[:4]}", bot_language="fr")
    db_session.add(other_guild)
    await db_session.flush()
    await crud.create_pending_generation(session=db_session, guild_id=other_guild.guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await db_session.commit()

    pending_reviews = await crud.get_pending_reviews_for_guild(session=db_session, guild_id=guild_id, limit=5)
    assert len(pending_reviews) == 2
    for record in pending_reviews:
        assert record.guild_id == guild_id
        assert record.status == PendingStatus.PENDING_MODERATION

    empty_reviews = await crud.get_pending_reviews_for_guild(session=db_session, guild_id=guild_id, status=PendingStatus.APPLIED)
    assert len(empty_reviews) == 0

@pytest.mark.asyncio
async def test_get_all_for_guild_by_type_and_status(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id

    pg1 = await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    pg2 = await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.APPROVED)
    pg3 = await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.ITEM_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await db_session.commit()

    # Get all NPC profiles for the guild
    npc_profiles = await crud.get_all_for_guild_by_type_and_status(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE)
    assert len(npc_profiles) == 2
    assert {pg1.id, pg2.id} == {r.id for r in npc_profiles}

    # Get all pending moderation for the guild
    pending_mod = await crud.get_all_for_guild_by_type_and_status(session=db_session, guild_id=guild_id, status=PendingStatus.PENDING_MODERATION)
    assert len(pending_mod) == 2
    assert {pg1.id, pg3.id} == {r.id for r in pending_mod}

    # Get specific type and status
    npc_pending = await crud.get_all_for_guild_by_type_and_status(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    assert len(npc_pending) == 1
    assert npc_pending[0].id == pg1.id

    # Get all for guild (no filters)
    all_for_guild = await crud.get_all_for_guild_by_type_and_status(session=db_session, guild_id=guild_id)
    assert len(all_for_guild) == 3


# Note: This conftest.py content is typically in tests/conftest.py
# For this example, it's assumed these fixtures are available.
# If they are not, the tests will fail to find `db_session` and `mock_db_service_with_session_factory`.
# `mock_db_service_with_session_factory` is not a standard fixture from previous examples;
# if `PendingGenerationCRUD` does not use self.db_service for session creation, a simpler mock for its init is fine.
# The current CRUD implementation passes the session directly to each method.

print("DEBUG: tests/persistence/test_pending_generation_crud.py created.")
