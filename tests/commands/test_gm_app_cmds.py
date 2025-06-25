import pytest
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import discord
from discord import app_commands # For app_commands.Choice if needed later
from discord.ext import commands

# Models involved
from bot.models.pending_generation import PendingGeneration, GenerationType, PendingStatus

# Cog to test
from bot.command_modules.gm_app_cmds import GMAppCog

# Import RPGBot for type hinting in fixtures
from bot.bot_core import RPGBot


# --- Fixtures ---
# Assuming mock_rpg_bot, mock_interaction, mock_db_session are available from a shared conftest

@pytest.fixture
async def gm_app_cog(mock_rpg_bot: RPGBot): # Use the specific RPGBot type
    # Mock the is_master_role decorator to always pass for these tests
    # This is a simple way; a more complex setup might involve setting up roles on mock_interaction.user
    with patch('bot.utils.decorators.is_master_role', return_value=lambda func: func):
        cog = GMAppCog(mock_rpg_bot)
        # No need to explicitly add_cog if we are calling methods directly via cog instance
        # and not relying on bot's command dispatch.
    return cog

# --- Tests for GMAppCog Commands ---

# Tests for /master review_ai
@pytest.mark.asyncio
async def test_master_review_ai_list_pending_and_failed(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    bot_instance = gm_app_cog.bot
    game_mngr = bot_instance.game_manager # This is an AsyncMock from mock_rpg_bot fixture

    guild_id_str = str(mock_interaction.guild_id)

    mock_pending_record1 = PendingGeneration(
        id=str(uuid.uuid4()), guild_id=guild_id_str, request_type=GenerationType.NPC_PROFILE,
        status=PendingStatus.PENDING_MODERATION, created_at=datetime.now(timezone.utc), created_by_user_id="user1"
    )
    mock_failed_record2 = PendingGeneration(
        id=str(uuid.uuid4()), guild_id=guild_id_str, request_type=GenerationType.ITEM_PROFILE,
        status=PendingStatus.FAILED_VALIDATION, created_at=datetime.now(timezone.utc), created_by_user_id="user2"
    )
    game_mngr.db_service.get_entities_by_conditions.return_value = [mock_pending_record1, mock_failed_record2]

    await gm_app_cog.cmd_master_review_ai.callback(gm_app_cog, mock_interaction, pending_id=None)

    game_mngr.db_service.get_entities_by_conditions.assert_awaited_once()
    call_kwargs = game_mngr.db_service.get_entities_by_conditions.call_args.kwargs
    assert call_kwargs['conditions']['guild_id'] == guild_id_str
    assert call_kwargs['conditions']['status']['in_'] == ["pending_moderation", "failed_validation"]

    mock_interaction.followup.send.assert_awaited_once()
    args, kwargs = mock_interaction.followup.send.call_args
    assert 'embed' in kwargs
    embed = kwargs['embed']
    assert len(embed.fields) == 2
    assert f"ID: `{mock_pending_record1.id}`" == embed.fields[0].name
    assert "🟠 PENDING_MODERATION" in embed.fields[0].value
    assert f"ID: `{mock_failed_record2.id}`" == embed.fields[1].name
    assert "🔴 FAILED_VALIDATION" in embed.fields[1].value

@pytest.mark.asyncio
async def test_master_review_ai_list_empty(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    game_mngr.db_service.get_entities_by_conditions.return_value = [] # No records

    await gm_app_cog.cmd_master_review_ai.callback(gm_app_cog, mock_interaction, pending_id=None)

    mock_interaction.followup.send.assert_awaited_once_with(
        "Нет записей AI генераций, ожидающих модерации или с ошибками валидации.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_master_review_ai_specific_id_found(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    guild_id_str = str(mock_interaction.guild_id)
    record_id = str(uuid.uuid4())

    mock_record = PendingGeneration(
        id=record_id, guild_id=guild_id_str, request_type=GenerationType.LOCATION_DETAILS,
        status=PendingStatus.PENDING_MODERATION, created_at=datetime.now(timezone.utc),
        created_by_user_id="user_test",
        request_params_json={"theme": "dark forest"},
        raw_ai_output_text="{\"name_i18n\": {\"en\": \"Dark Wood\"}}",
        parsed_data_json={"name_i18n": {"en": "Dark Wood"}},
        validation_issues_json=[{"loc": ["desc"], "msg": "Too short", "type": "value_error"}]
    )
    game_mngr.db_service.get_entity_by_pk.return_value = mock_record

    await gm_app_cog.cmd_master_review_ai.callback(gm_app_cog, mock_interaction, pending_id=record_id)

    game_mngr.db_service.get_entity_by_pk.assert_awaited_once_with(
        PendingGeneration, pk_value=record_id, guild_id=guild_id_str
    )
    mock_interaction.followup.send.assert_awaited_once()
    args, kwargs = mock_interaction.followup.send.call_args
    embed = kwargs['embed']
    assert embed.title == f"Детали AI Генерации: {record_id}"
    assert any(field.name == "Raw AI Output (сниппет)" and "Dark Wood" in field.value for field in embed.fields)
    assert any(field.name == "Ошибки Валидации" and "Too short" in field.value for field in embed.fields)

@pytest.mark.asyncio
async def test_master_review_ai_specific_id_not_found(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    record_id = str(uuid.uuid4())
    game_mngr.db_service.get_entity_by_pk.return_value = None # Not found

    await gm_app_cog.cmd_master_review_ai.callback(gm_app_cog, mock_interaction, pending_id=record_id)

    mock_interaction.followup.send.assert_awaited_once_with(
        f"Запись с ID `{record_id}` не найдена.", ephemeral=True
    )

# --- Tests for /master approve_ai ---
@pytest.mark.asyncio
async def test_master_approve_ai_success_and_applied(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    guild_id_str = str(mock_interaction.guild_id)
    pending_id = str(uuid.uuid4())

    mock_record = PendingGeneration(
        id=pending_id, guild_id=guild_id_str, request_type=GenerationType.NPC_PROFILE,
        status=PendingStatus.PENDING_MODERATION
    )
    game_mngr.db_service.get_entity_by_pk.return_value = mock_record
    game_mngr.db_service.update_entity_by_pk.return_value = True # DB update successful
    game_mngr.apply_approved_generation = AsyncMock(return_value=True) # Application successful

    await gm_app_cog.cmd_master_approve_ai.callback(gm_app_cog, mock_interaction, pending_id=pending_id)

    game_mngr.db_service.update_entity_by_pk.assert_awaited_once()
    update_args_kwargs = game_mngr.db_service.update_entity_by_pk.call_args.kwargs
    assert update_args_kwargs['pk_value'] == pending_id
    assert update_args_kwargs['updates']['status'] == "approved"
    assert update_args_kwargs['updates']['moderated_by_user_id'] == str(mock_interaction.user.id)

    game_mngr.apply_approved_generation.assert_awaited_once_with(pending_gen_id=pending_id, guild_id=guild_id_str)

    mock_interaction.followup.send.assert_awaited_once_with(
        f"✅ AI Content ID `{pending_id}` (Type: {mock_record.request_type}) approved and successfully applied.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_master_approve_ai_application_fails(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    pending_id = str(uuid.uuid4())
    mock_record = PendingGeneration(id=pending_id, guild_id=str(mock_interaction.guild_id), request_type="test_type", status=PendingStatus.PENDING_MODERATION)

    # Mock get_entity_by_pk to return the record twice: once for the initial check, once after apply_approved_generation
    game_mngr.db_service.get_entity_by_pk.side_effect = [
        mock_record, # First call returns the record in PENDING_MODERATION
        PendingGeneration(id=pending_id, guild_id=str(mock_interaction.guild_id), request_type="test_type", status=PendingStatus.APPLICATION_FAILED) # Second call after apply failed
    ]
    game_mngr.db_service.update_entity_by_pk.return_value = True
    game_mngr.apply_approved_generation = AsyncMock(return_value=False) # Application fails

    await gm_app_cog.cmd_master_approve_ai.callback(gm_app_cog, mock_interaction, pending_id=pending_id)

    mock_interaction.followup.send.assert_awaited_once_with(
        f"⚠️ AI Content ID `{pending_id}` (Type: {mock_record.request_type}) was approved, but application failed or is pending further logic. Status: {PendingStatus.APPLICATION_FAILED}. Check logs or use `/master review_ai id:{pending_id}`.",
        ephemeral=True
    )

# --- Tests for /master reject_ai ---
@pytest.mark.asyncio
async def test_master_reject_ai_success(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    pending_id = str(uuid.uuid4())
    reason = "Not a good fit for the game."
    mock_record = PendingGeneration(
        id=pending_id, guild_id=str(mock_interaction.guild_id),
        request_type=GenerationType.QUEST_FULL, status=PendingStatus.PENDING_MODERATION
    )
    game_mngr.db_service.get_entity_by_pk.return_value = mock_record
    game_mngr.db_service.update_entity_by_pk.return_value = True
    game_mngr.get_rule = AsyncMock(return_value="en") # For moderator_notes_i18n default lang

    await gm_app_cog.cmd_master_reject_ai.callback(gm_app_cog, mock_interaction, pending_id=pending_id, reason=reason)

    update_args_kwargs = game_mngr.db_service.update_entity_by_pk.call_args.kwargs
    assert update_args_kwargs['updates']['status'] == "rejected"
    assert update_args_kwargs['updates']['moderator_notes_i18n']['rejection_reason']['en'] == reason

    mock_interaction.followup.send.assert_awaited_once_with(
       f"🚫 AI Content ID `{pending_id}` (Type: {mock_record.request_type}) has been rejected. Reason: {reason}", ephemeral=True
    )

# --- Tests for /master edit_ai ---
@pytest.mark.asyncio
@patch('bot.command_modules.gm_app_cmds.parse_and_validate_ai_response', new_callable=AsyncMock) # Patch the global import
async def test_master_edit_ai_success_valid_new_data(
    mock_parse_validate: AsyncMock,
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    pending_id = str(uuid.uuid4())
    original_data_str = "{\"name_i18n\": {\"en\": \"Old Name\"}}"
    new_data_str = "{\"name_i18n\": {\"en\": \"New Valid Name\", \"ru\": \"Новое Имя\"}}"
    new_parsed_data_dict = json.loads(new_data_str)

    mock_record = PendingGeneration(
        id=pending_id, guild_id=str(mock_interaction.guild_id), request_type=GenerationType.NPC_PROFILE,
        status=PendingStatus.FAILED_VALIDATION, parsed_data_json=json.loads(original_data_str),
        moderator_notes_i18n=None # Start with no notes
    )
    game_mngr.db_service.get_entity_by_pk.return_value = mock_record
    mock_parse_validate.return_value = (new_parsed_data_dict, None) # No validation issues after edit
    game_mngr.db_service.update_entity_by_pk.return_value = True

    await gm_app_cog.cmd_master_edit_ai.callback(gm_app_cog, mock_interaction, pending_id=pending_id, json_data=new_data_str)

    mock_parse_validate.assert_awaited_once_with(
        raw_ai_output_text=new_data_str, guild_id=str(mock_interaction.guild_id),
        request_type=mock_record.request_type, game_manager=game_mngr
    )
    update_args_kwargs = game_mngr.db_service.update_entity_by_pk.call_args.kwargs
    assert update_args_kwargs['updates']['status'] == "pending_moderation"
    assert update_args_kwargs['updates']['parsed_data_json'] == new_parsed_data_dict
    assert update_args_kwargs['updates']['validation_issues_json'] is None
    assert "edit_history" in update_args_kwargs['updates']['moderator_notes_i18n']
    assert len(update_args_kwargs['updates']['moderator_notes_i18n']['edit_history']) == 1

    mock_interaction.followup.send.assert_awaited_once()
    assert f"⚙️ AI Content ID `{pending_id}`" in mock_interaction.followup.send.call_args[0][0]
    assert "New validation status: pending_moderation" in mock_interaction.followup.send.call_args[0][0]

print("DEBUG: tests/commands/test_gm_app_cmds.py created.")
