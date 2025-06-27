import pytest
import uuid
import json # Added for json operations
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select # Keep for potential direct session use if needed
from unittest.mock import MagicMock

from bot.database.models.pending_generation import PendingGeneration, GenerationType, PendingStatus
from bot.database.pending_generation_crud import PendingGenerationCRUD
from bot.database.models.guild_config import GuildConfig
from bot.services.db_service import DBService # For spec in MagicMock

@pytest.fixture
async def test_guild(db_session: AsyncSession) -> GuildConfig:
    """Creates a GuildConfig entry and returns it."""
    guild_id = f"crud_test_guild_{str(uuid.uuid4())[:8]}"
    # Assuming GuildConfig can be initialized with guild_id and other fields are optional or have defaults
    guild_config = GuildConfig(guild_id=guild_id, bot_language="en")
    db_session.add(guild_config)
    await db_session.commit()
    await db_session.refresh(guild_config)
    return guild_config

@pytest.fixture
def crud() -> PendingGenerationCRUD:
    # Provide a mock with a spec if DBService methods are called directly by CRUD,
    # otherwise, if CRUD only uses the session, a simple MagicMock might suffice.
    # For safety, using spec=DBService.
    mock_db_service_instance = MagicMock(spec=DBService)
    return PendingGenerationCRUD(db_service=mock_db_service_instance)


@pytest.mark.asyncio
async def test_create_pending_generation(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id
    request_params_dict = {"npc_idea": "brave knight"}
    parsed_data_dict = {"name_i18n": {"en": "Sir Reginald"}}
    data = {
        "guild_id": guild_id,
        "request_type": GenerationType.NPC_PROFILE, # Use Enum member
        "status": PendingStatus.PENDING_MODERATION, # Use Enum member
        "request_params_json": json.dumps(request_params_dict), # Store as JSON string
        "raw_ai_output_text": "{\"name_i18n\": {\"en\": \"Sir Reginald\"}}",
        "parsed_data_json": parsed_data_dict, # Store as dict, SQLAlchemy should handle JSON conversion
        "created_by_user_id": "user123"
    }

    record = await crud.create_pending_generation(session=db_session, **data)
    await db_session.commit()

    assert record is not None
    assert record.id is not None
    assert record.guild_id == guild_id
    assert record.request_type == GenerationType.NPC_PROFILE
    assert record.status == PendingStatus.PENDING_MODERATION

    # Assuming request_params_json is stored as a string in DB
    assert record.request_params_json == json.dumps(request_params_dict)

    # Assuming parsed_data_json is stored as JSON in DB and retrieved as dict
    assert record.parsed_data_json == parsed_data_dict

    assert record.created_by_user_id == "user123"
    assert record.created_at is not None

@pytest.mark.asyncio
async def test_get_pending_generation_by_id_found(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id
    created_record = await crud.create_pending_generation(
        session=db_session, guild_id=guild_id, request_type=GenerationType.ITEM_PROFILE, status=PendingStatus.PENDING_MODERATION
    )
    await db_session.commit()
    assert created_record is not None and created_record.id is not None

    fetched_record = await crud.get_pending_generation_by_id(session=db_session, record_id=str(created_record.id), guild_id=guild_id)
    assert fetched_record is not None
    assert fetched_record.id == created_record.id

    fetched_no_guild_filter = await crud.get_pending_generation_by_id(session=db_session, record_id=str(created_record.id))
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
    # Ensure other_guild_id also has a GuildConfig for FK if necessary, or test setup implies it's not strictly enforced here.
    # For this test, we assume the guild_id filter in get_pending_generation_by_id is the primary focus.

    created_record = await crud.create_pending_generation(
        session=db_session, guild_id=guild_id, request_type=GenerationType.QUEST_FULL, status=PendingStatus.PENDING_MODERATION
    )
    await db_session.commit()
    assert created_record is not None and created_record.id is not None

    fetched_record = await crud.get_pending_generation_by_id(session=db_session, record_id=str(created_record.id), guild_id=other_guild_id)
    assert fetched_record is None


@pytest.mark.asyncio
async def test_update_pending_generation_status(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id
    record = await crud.create_pending_generation(
        session=db_session, guild_id=guild_id, request_type=GenerationType.LOCATION_DETAILS, status=PendingStatus.PENDING_MODERATION
    )
    await db_session.commit()
    assert record is not None and record.id is not None

    moderator_id = "mod456"
    notes = "Looks good!"
    updated_record = await crud.update_pending_generation_status(
        session=db_session, record_id=str(record.id), new_status=PendingStatus.APPROVED,
        guild_id=guild_id, moderated_by_user_id=moderator_id, moderator_notes=notes
    )
    await db_session.commit()
    assert updated_record is not None
    await db_session.refresh(updated_record) # Refresh to get latest state from DB

    assert updated_record.status == PendingStatus.APPROVED
    assert updated_record.moderated_by_user_id == moderator_id
    assert updated_record.moderator_notes == notes
    assert updated_record.moderated_at is not None

    new_issues_list_of_dicts = [{"loc": ["name"], "type": "value_error", "msg": "Too generic"}]
    updated_again = await crud.update_pending_generation_status(
        session=db_session, record_id=str(record.id), new_status=PendingStatus.FAILED_VALIDATION,
        guild_id=guild_id, validation_issues_json=new_issues_list_of_dicts # Pass as list of dicts
    )
    await db_session.commit()
    assert updated_again is not None
    await db_session.refresh(updated_again)

    assert updated_again.status == PendingStatus.FAILED_VALIDATION
    # Assuming validation_issues_json is stored as JSON and retrieved as dict/list
    assert updated_again.validation_issues_json == new_issues_list_of_dicts


@pytest.mark.asyncio
async def test_get_pending_reviews_for_guild(db_session: AsyncSession, crud: PendingGenerationCRUD, test_guild: GuildConfig):
    guild_id = test_guild.guild_id

    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.ITEM_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await crud.create_pending_generation(session=db_session, guild_id=guild_id, request_type=GenerationType.QUEST_FULL, status=PendingStatus.APPROVED)

    other_guild_id_str = f"other_g_{str(uuid.uuid4())[:4]}"
    other_guild = GuildConfig(guild_id=other_guild_id_str, bot_language="fr")
    db_session.add(other_guild)
    await db_session.flush() # Ensure other_guild exists before creating pending gen for it
    await crud.create_pending_generation(session=db_session, guild_id=other_guild.guild_id, request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION)
    await db_session.commit()

    pending_reviews = await crud.get_pending_reviews_for_guild(session=db_session, guild_id=guild_id, limit=5)
    assert len(pending_reviews) == 2
    for record_item in pending_reviews:
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

    assert pg1 is not None and pg1.id is not None
    assert pg2 is not None and pg2.id is not None
    assert pg3 is not None and pg3.id is not None


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
