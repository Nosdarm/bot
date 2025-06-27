import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from unittest.mock import MagicMock # Added for MagicMock

from bot.database.models.pending_generation import PendingGeneration, GenerationType, PendingStatus # Corrected import path
from bot.database.pending_generation_crud import PendingGenerationCRUD # Corrected import path
from bot.database.models.guild_config import GuildConfig # Corrected import path

@pytest.fixture
async def test_guild(db_session: AsyncSession) -> GuildConfig:
    """Creates a GuildConfig entry and returns it."""
    guild_id = f"crud_test_guild_{str(uuid.uuid4())[:8]}"
    guild_config = GuildConfig(guild_id=guild_id, bot_language="en") # type: ignore[call-arg] # If guild_id is only arg
    db_session.add(guild_config)
    await db_session.commit()
    await db_session.refresh(guild_config)
    return guild_config

@pytest.fixture
def crud() -> PendingGenerationCRUD: # Removed mock_db_service_with_session_factory as it's not used by CRUD
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
    # Ensure request_params_json is compared correctly, it might be a string or dict
    if isinstance(record.request_params_json, str):
        import json
        assert json.loads(record.request_params_json) == {"npc_idea": "brave knight"}
    else:
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
    assert created_record.id is not None # Ensure ID is set

    fetched_record = await crud.get_pending_generation_by_id(session=db_session, record_id=str(created_record.id), guild_id=guild_id) # Ensure record_id is str
    assert fetched_record is not None
    assert fetched_record.id == created_record.id

    fetched_no_guild_filter = await crud.get_pending_generation_by_id(session=db_session, record_id=str(created_record.id)) # Ensure record_id is str
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

    created_record = await crud.create_pending_generation(
        session=db_session, guild_id=guild_id, request_type=GenerationType.QUEST_FULL, status=PendingStatus.PENDING_MODERATION
    )
    await db_session.commit()
    assert created_record.id is not None # Ensure ID is set

    fetched_record = await crud.get_pending_generation_by_id(session=db_session, record_id=str(created_record.id), guild_id=other_guild_id) # Ensure record_id is str
    assert fetched_record is None


@pytest.mark.asyncio
async def test_update_pending_generation_status(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id
    record = await crud.create_pending_generation(
        session=db_session, guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS, status=PendingStatus.PENDING_MODERATION
    )
    await db_session.commit()
    assert record.id is not None # Ensure ID is set

    moderator_id = "mod456"
    notes = "Looks good!"
    updated_record = await crud.update_pending_generation_status(
        session=db_session, record_id=str(record.id), new_status=PendingStatus.APPROVED, # Ensure record_id is str
        guild_id=guild_id, moderated_by_user_id=moderator_id, moderator_notes=notes
    )
    await db_session.commit()
    assert updated_record is not None # Check update returned something
    await db_session.refresh(updated_record)

    assert updated_record.status == PendingStatus.APPROVED
    assert updated_record.moderated_by_user_id == moderator_id
    assert updated_record.moderator_notes == notes
    assert updated_record.moderated_at is not None

    new_issues = [{"loc": ["name"], "type": "value_error", "msg": "Too generic"}]
    updated_again = await crud.update_pending_generation_status(
        session=db_session, record_id=str(record.id), new_status=PendingStatus.FAILED_VALIDATION, # Ensure record_id is str
        guild_id=guild_id, validation_issues_json=new_issues
    )
    await db_session.commit()
    assert updated_again is not None # Check update returned something
    await db_session.refresh(updated_again)

    assert updated_again.status == PendingStatus.FAILED_VALIDATION
    # Ensure validation_issues_json is compared correctly, it might be a string or dict
    if isinstance(updated_again.validation_issues_json, str):
        import json
        assert json.loads(updated_again.validation_issues_json) == new_issues
    else:
        assert updated_again.validation_issues_json == new_issues


@pytest.mark.asyncio
async def test_get_pending_reviews_for_guild(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id

    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.ITEM_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.QUEST_FULL, status=PendingStatus.APPROVED)

    other_guild_id_str = f"other_g_{str(uuid.uuid4())[:4]}"
    other_guild = GuildConfig(guild_id=other_guild_id_str, bot_language="fr") # type: ignore[call-arg]
    db_session.add(other_guild)
    await db_session.flush()
    await crud.create_pending_generation(session=db_session, guild_id=other_guild.guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await db_session.commit()

    pending_reviews = await crud.get_pending_reviews_for_guild(session=db_session, guild_id=guild_id, limit=5)
    assert len(pending_reviews) == 2
    for record_item in pending_reviews: # Changed record to record_item
        assert record_item.guild_id == guild_id
        assert record_item.status == PendingStatus.PENDING_MODERATION

    empty_reviews = await crud.get_pending_reviews_for_guild(session=db_session, guild_id=guild_id, status=PendingStatus.APPLIED)
    assert len(empty_reviews) == 0

@pytest.mark.asyncio
async def test_get_all_for_guild_by_type_and_status(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id

    pg1 = await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    pg2 = await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.APPROVED)
    pg3 = await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.ITEM_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await db_session.commit()

    npc_profiles = await crud.get_all_for_guild_by_type_and_status(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE)
    assert len(npc_profiles) == 2
    assert {pg1.id, pg2.id} == {r.id for r in npc_profiles}

    pending_mod = await crud.get_all_for_guild_by_type_and_status(session=db_session, guild_id=guild_id, status=PendingStatus.PENDING_MODERATION)
    assert len(pending_mod) == 2
    assert {pg1.id, pg3.id} == {r.id for r in pending_mod}

    npc_pending = await crud.get_all_for_guild_by_type_and_status(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    assert len(npc_pending) == 1
    assert npc_pending[0].id == pg1.id

    all_for_guild = await crud.get_all_for_guild_by_type_and_status(session=db_session, guild_id=guild_id)
    assert len(all_for_guild) == 3

# Removed print statement as it's not needed for tests
