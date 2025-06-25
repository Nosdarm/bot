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

# --- Tests for /master_set_rule ---
@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role', return_value=lambda func: func) # Bypass decorator
async def test_master_set_rule_success_new_rule(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock # Used by db_service.adapter
):
    bot_instance = gm_app_cog.bot
    game_mngr = bot_instance.game_manager
    db_service = bot_instance.db_service # This is the mock_db_service from mock_rpg_bot

    guild_id_str = str(mock_interaction.guild_id)
    rule_key = "economy.trade_markup_percentage"
    value_json_str = "15.5" # Example float value
    expected_parsed_value = 15.5

    # Mock DBService adapter behavior for RuleConfig
    # 1. Initial fetch of rules_config (to get current dict)
    #    - In cmd_master_set_rule, it uses game_mngr.rule_engine if available,
    #      else direct db.adapter.fetchone. Let's mock the direct path first.
    #    - If RuleEngine is used, mock game_mngr.rule_engine.get_raw_rules_config_dict_for_guild
    #      and game_mngr.rule_engine.save_rules_config_for_guild_from_dict

    # Assume RuleEngine path is taken and it returns an empty dict (new config)
    game_mngr.rule_engine.get_raw_rules_config_dict_for_guild = AsyncMock(return_value={})
    game_mngr.rule_engine.save_rules_config_for_guild_from_dict = AsyncMock()
    game_mngr.rule_engine.load_rules_config_for_guild = AsyncMock() # For reloading cache

    # Mock game_log_manager
    game_mngr.game_log_manager.log_event = AsyncMock()

    await gm_app_cog.cmd_master_set_rule.callback(gm_app_cog, mock_interaction, rule_key=rule_key, value_json=value_json_str)

    game_mngr.rule_engine.get_raw_rules_config_dict_for_guild.assert_awaited_once_with(guild_id_str)

    # Check that save_rules_config_for_guild_from_dict was called with the updated dict
    game_mngr.rule_engine.save_rules_config_for_guild_from_dict.assert_awaited_once()
    saved_config_arg = game_mngr.rule_engine.save_rules_config_for_guild_from_dict.call_args[0][1]

    # Traverse the dict based on rule_key
    keys = rule_key.split('.')
    current_level = saved_config_arg
    for k_part in keys[:-1]:
        assert k_part in current_level
        current_level = current_level[k_part]
    assert keys[-1] in current_level
    assert current_level[keys[-1]] == expected_parsed_value # Type conversion happened

    game_mngr.rule_engine.load_rules_config_for_guild.assert_awaited_once_with(guild_id_str) # Cache reloaded
    game_mngr.game_log_manager.log_event.assert_awaited_once() # Logged

    mock_interaction.followup.send.assert_awaited_once()
    assert f"Правило '{rule_key}' установлено на '{expected_parsed_value}'" in mock_interaction.followup.send.call_args[0][0]

@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role', return_value=lambda func: func)
async def test_master_set_rule_update_existing_typed(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    guild_id_str = str(mock_interaction.guild_id)
    rule_key = "player.max_hp_on_start"
    value_json_str = "\"100\"" # Int value, but passed as JSON string containing a string
    expected_parsed_value = 100 # Should be converted to int based on existing type

    existing_config = {"player": {"max_hp_on_start": 50}} # Current value is int

    game_mngr.rule_engine.get_raw_rules_config_dict_for_guild = AsyncMock(return_value=existing_config)
    game_mngr.rule_engine.save_rules_config_for_guild_from_dict = AsyncMock()
    game_mngr.rule_engine.load_rules_config_for_guild = AsyncMock()
    game_mngr.game_log_manager.log_event = AsyncMock()

    await gm_app_cog.cmd_master_set_rule.callback(gm_app_cog, mock_interaction, rule_key=rule_key, value_json=value_json_str)

    saved_config_arg = game_mngr.rule_engine.save_rules_config_for_guild_from_dict.call_args[0][1]
    assert saved_config_arg["player"]["max_hp_on_start"] == expected_parsed_value # Check type conversion
    mock_interaction.followup.send.assert_awaited_once()
    assert f"Правило '{rule_key}' установлено на '{expected_parsed_value}'" in mock_interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role', return_value=lambda func: func)
async def test_master_set_rule_invalid_json_value(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    game_mngr.rule_engine.get_raw_rules_config_dict_for_guild = AsyncMock(return_value={}) # No existing config needed for this test path

    await gm_app_cog.cmd_master_set_rule.callback(gm_app_cog, mock_interaction, rule_key="any.key", value_json="not_a_valid_json")

    mock_interaction.followup.send.assert_awaited_once()
    assert "Ошибка JSON: `not_a_valid_json`" in mock_interaction.followup.send.call_args[0][0]
    game_mngr.rule_engine.save_rules_config_for_guild_from_dict.assert_not_called()

# print("DEBUG: tests/commands/test_gm_app_cmds.py created.") # Removed print from previous merge
