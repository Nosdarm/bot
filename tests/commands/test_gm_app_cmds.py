import pytest
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch
from typing import cast, Optional, List, Dict, Any # Added Optional, List, Dict, Any
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
    with patch('bot.utils.decorators.is_master_role', return_value=lambda func: func):
        cog = GMAppCog(mock_rpg_bot)
    return cog

# --- Helper to create mock session ---
def get_mock_session_manager(game_mngr: Any) -> MagicMock:
    mock_session = AsyncMock()
    session_manager = MagicMock()
    session_manager.return_value.__aenter__.return_value = mock_session
    game_mngr.db_service.get_session = session_manager
    return mock_session


# --- Tests for GMAppCog Commands ---

# Tests for /master review_ai
@pytest.mark.asyncio
async def test_master_review_ai_list_pending_and_failed(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    guild_id_str = str(mock_interaction.guild_id)

    mock_pending_record1 = PendingGeneration(
        id=str(uuid.uuid4()), guild_id=guild_id_str, request_type=GenerationType.NPC_PROFILE,
        status=PendingStatus.PENDING_MODERATION, created_at=datetime.now(timezone.utc), created_by_user_id="user1"
    )
    mock_failed_record2 = PendingGeneration(
        id=str(uuid.uuid4()), guild_id=guild_id_str, request_type=GenerationType.ITEM_PROFILE,
        status=PendingStatus.FAILED_VALIDATION, created_at=datetime.now(timezone.utc), created_by_user_id="user2"
    )

    mock_session = get_mock_session_manager(game_mngr)

    with patch('bot.database.crud_utils.get_entities', new_callable=AsyncMock) as mock_get_entities:
        mock_get_entities.return_value = [mock_pending_record1, mock_failed_record2]

        await gm_app_cog.cmd_master_review_ai.callback(gm_app_cog, mock_interaction, pending_id=None)

        mock_get_entities.assert_awaited_once()
        call_args_actual = mock_get_entities.call_args
        assert call_args_actual.kwargs['db_session'] == mock_session
        assert call_args_actual.kwargs['model_class'] == PendingGeneration
        assert call_args_actual.kwargs['guild_id'] == guild_id_str

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once()
    args, kwargs = cast(AsyncMock, mock_interaction.followup.send).call_args
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
    mock_session = get_mock_session_manager(game_mngr)

    with patch('bot.database.crud_utils.get_entities', new_callable=AsyncMock) as mock_get_entities:
        mock_get_entities.return_value = []

        await gm_app_cog.cmd_master_review_ai.callback(gm_app_cog, mock_interaction, pending_id=None)
        mock_get_entities.assert_awaited_once()

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once_with(
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
        request_params_json={"theme": "dark forest"}, # type: ignore
        raw_ai_output_text="{\"name_i18n\": {\"en\": \"Dark Wood\"}}",
        parsed_data_json={"name_i18n": {"en": "Dark Wood"}}, # type: ignore
        validation_issues_json=[{"loc": ["desc"], "msg": "Too short", "type": "value_error"}] # type: ignore
    )
    mock_session = get_mock_session_manager(game_mngr)

    with patch('bot.database.crud_utils.get_entity_by_id', new_callable=AsyncMock) as mock_get_entity_by_id:
        mock_get_entity_by_id.return_value = mock_record

        await gm_app_cog.cmd_master_review_ai.callback(gm_app_cog, mock_interaction, pending_id=record_id)

        mock_get_entity_by_id.assert_awaited_once_with(
            db_session=mock_session,
            model_class=PendingGeneration,
            entity_id=record_id,
            guild_id=guild_id_str
        )
    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once()
    args, kwargs = cast(AsyncMock, mock_interaction.followup.send).call_args
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
    mock_session = get_mock_session_manager(game_mngr)

    with patch('bot.database.crud_utils.get_entity_by_id', new_callable=AsyncMock) as mock_get_entity_by_id:
        mock_get_entity_by_id.return_value = None

        await gm_app_cog.cmd_master_review_ai.callback(gm_app_cog, mock_interaction, pending_id=record_id)
        mock_get_entity_by_id.assert_awaited_once()

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once_with(
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
    pending_id_val = str(uuid.uuid4())

    mock_record = PendingGeneration(
        id=pending_id_val, guild_id=guild_id_str, request_type=GenerationType.NPC_PROFILE,
        status=PendingStatus.PENDING_MODERATION
    )
    mock_session = get_mock_session_manager(game_mngr)

    with patch('bot.database.crud_utils.get_entity_by_id', new_callable=AsyncMock) as mock_get_by_id, \
         patch('bot.database.crud_utils.update_entity', new_callable=AsyncMock) as mock_update_entity:

        mock_get_by_id.return_value = mock_record
        mock_update_entity.return_value = mock_record
        game_mngr.apply_approved_generation = AsyncMock(return_value=True)

        await gm_app_cog.cmd_master_approve_ai.callback(gm_app_cog, mock_interaction, pending_id=pending_id_val)

        mock_get_by_id.assert_any_call(
            db_session=mock_session, model_class=PendingGeneration, entity_id=pending_id_val, guild_id=guild_id_str
        )
        mock_update_entity.assert_awaited_once()
        update_call_args_actual = mock_update_entity.call_args
        assert update_call_args_actual.kwargs['db_session'] == mock_session
        assert update_call_args_actual.kwargs['entity_instance'] == mock_record

        updates_dict = update_call_args_actual.kwargs['data']
        assert updates_dict['status'] == PendingStatus.APPROVED
        assert updates_dict['moderated_by_user_id'] == str(mock_interaction.user.id)
        assert 'moderated_at' in updates_dict

    game_mngr.apply_approved_generation.assert_awaited_once_with(pending_gen_id=pending_id_val, guild_id=guild_id_str)
    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once_with(
        f"✅ AI Content ID `{pending_id_val}` (Type: {mock_record.request_type}) approved and successfully applied.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_master_approve_ai_application_fails(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    pending_id_val = str(uuid.uuid4())
    mock_record_initial = PendingGeneration(
        id=pending_id_val, guild_id=str(mock_interaction.guild_id),
        request_type=GenerationType.NPC_PROFILE, status=PendingStatus.PENDING_MODERATION
    )
    mock_record_after_fail = PendingGeneration(
        id=pending_id_val, guild_id=str(mock_interaction.guild_id),
        request_type=GenerationType.NPC_PROFILE, status=PendingStatus.APPLICATION_FAILED
    )
    mock_session = get_mock_session_manager(game_mngr)

    with patch('bot.database.crud_utils.get_entity_by_id', new_callable=AsyncMock) as mock_get_by_id, \
         patch('bot.database.crud_utils.update_entity', new_callable=AsyncMock) as mock_update_entity:

        mock_get_by_id.side_effect = [
            mock_record_initial,
            mock_record_initial,
            mock_record_after_fail
        ]
        mock_update_entity.return_value = mock_record_initial
        game_mngr.apply_approved_generation = AsyncMock(return_value=False)

        await gm_app_cog.cmd_master_approve_ai.callback(gm_app_cog, mock_interaction, pending_id=pending_id_val)

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once_with(
        f"⚠️ AI Content ID `{pending_id_val}` (Type: {mock_record_initial.request_type}) was approved, but application failed or is pending further logic. Status: {PendingStatus.APPLICATION_FAILED}. Check logs or use `/master review_ai id:{pending_id_val}`.",
        ephemeral=True
    )

# --- Tests for /master reject_ai ---
@pytest.mark.asyncio
async def test_master_reject_ai_success(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    pending_id_val = str(uuid.uuid4())
    reason = "Not a good fit for the game."
    mock_record = PendingGeneration(
        id=pending_id_val, guild_id=str(mock_interaction.guild_id),
        request_type=GenerationType.QUEST_FULL, status=PendingStatus.PENDING_MODERATION
    )
    mock_session = get_mock_session_manager(game_mngr)

    with patch('bot.database.crud_utils.get_entity_by_id', new_callable=AsyncMock) as mock_get_by_id, \
         patch('bot.database.crud_utils.update_entity', new_callable=AsyncMock) as mock_update_entity:

        mock_get_by_id.return_value = mock_record
        mock_update_entity.return_value = mock_record
        if hasattr(game_mngr, 'rule_engine') and game_mngr.rule_engine:
            game_mngr.rule_engine.get_rule = AsyncMock(return_value="en")
        elif hasattr(game_mngr, 'get_rule'):
             game_mngr.get_rule = AsyncMock(return_value="en")

        await gm_app_cog.cmd_master_reject_ai.callback(gm_app_cog, mock_interaction, pending_id=pending_id_val, reason=reason)

        mock_update_entity.assert_awaited_once()
        update_call_args_actual = mock_update_entity.call_args
        updates_dict = update_call_args_actual.kwargs['data']

        assert updates_dict['status'] == PendingStatus.REJECTED
        assert 'moderator_notes_i18n' in updates_dict
        assert updates_dict['moderator_notes_i18n']['rejection_reason']['en'] == reason

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once_with(
       f"🚫 AI Content ID `{pending_id_val}` (Type: {mock_record.request_type}) has been rejected. Reason: {reason}", ephemeral=True
    )

# --- Tests for /master edit_ai ---
@pytest.mark.asyncio
@patch('bot.command_modules.gm_app_cmds.parse_and_validate_ai_response', new_callable=AsyncMock)
async def test_master_edit_ai_success_valid_new_data(
    mock_parse_validate: AsyncMock,
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    pending_id_val = str(uuid.uuid4())
    original_data_str = "{\"name_i18n\": {\"en\": \"Old Name\"}}"
    new_data_str = "{\"name_i18n\": {\"en\": \"New Valid Name\", \"ru\": \"Новое Имя\"}}"
    new_parsed_data_dict = json.loads(new_data_str)

    mock_record = PendingGeneration(
        id=pending_id_val, guild_id=str(mock_interaction.guild_id), request_type=GenerationType.NPC_PROFILE,
        status=PendingStatus.FAILED_VALIDATION, parsed_data_json=json.loads(original_data_str), # type: ignore
        moderator_notes_i18n=None
    )
    mock_session = get_mock_session_manager(game_mngr)

    with patch('bot.database.crud_utils.get_entity_by_id', new_callable=AsyncMock) as mock_get_by_id, \
         patch('bot.database.crud_utils.update_entity', new_callable=AsyncMock) as mock_update_entity:

        mock_get_by_id.return_value = mock_record
        mock_parse_validate.return_value = (new_parsed_data_dict, None)
        mock_update_entity.return_value = mock_record

        await gm_app_cog.cmd_master_edit_ai.callback(gm_app_cog, mock_interaction, pending_id=pending_id_val, json_data=new_data_str)

    mock_parse_validate.assert_awaited_once_with(
        raw_ai_output_text=new_data_str, guild_id=str(mock_interaction.guild_id),
        request_type=mock_record.request_type, game_manager=game_mngr
    )
    mock_update_entity.assert_awaited_once()
    update_call_args_actual = mock_update_entity.call_args
    updates_dict = update_call_args_actual.kwargs['data']

    assert updates_dict['status'] == PendingStatus.PENDING_MODERATION
    assert updates_dict['parsed_data_json'] == new_parsed_data_dict
    assert updates_dict['validation_issues_json'] is None
    assert "edit_history" in updates_dict['moderator_notes_i18n']
    assert len(updates_dict['moderator_notes_i18n']['edit_history']) == 1

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once()
    args_sent, kwargs_sent = cast(AsyncMock, mock_interaction.followup.send).call_args
    assert f"⚙️ AI Content ID `{pending_id_val}`" in args_sent[0]
    assert f"New validation status: {PendingStatus.PENDING_MODERATION}" in args_sent[0]


# --- Tests for /master_set_rule ---
@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role', return_value=lambda func: func)
async def test_master_set_rule_success_new_rule(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock
):
    bot_instance = gm_app_cog.bot
    game_mngr = bot_instance.game_manager
    # db_service = bot_instance.db_service # Not used directly if rule_engine is primary

    guild_id_str = str(mock_interaction.guild_id)
    rule_key = "economy.trade_markup_percentage"
    value_json_str = "15.5"
    expected_parsed_value = 15.5

    game_mngr.rule_engine.get_raw_rules_config_dict_for_guild = AsyncMock(return_value={})
    game_mngr.rule_engine.save_rules_config_for_guild_from_dict = AsyncMock()
    game_mngr.rule_engine.load_rules_config_for_guild = AsyncMock()
    game_mngr.game_log_manager.log_event = AsyncMock()

    await gm_app_cog.cmd_master_set_rule.callback(gm_app_cog, mock_interaction, rule_key=rule_key, value_json=value_json_str)

    game_mngr.rule_engine.get_raw_rules_config_dict_for_guild.assert_awaited_once_with(guild_id_str)
    game_mngr.rule_engine.save_rules_config_for_guild_from_dict.assert_awaited_once()
    saved_config_arg = game_mngr.rule_engine.save_rules_config_for_guild_from_dict.call_args[0][1]

    keys = rule_key.split('.')
    current_level = saved_config_arg
    for k_part in keys[:-1]:
        assert k_part in current_level
        current_level = current_level[k_part]
    assert keys[-1] in current_level
    assert current_level[keys[-1]] == expected_parsed_value

    game_mngr.rule_engine.load_rules_config_for_guild.assert_awaited_once_with(guild_id_str)
    game_mngr.game_log_manager.log_event.assert_awaited_once()

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once()
    args_set_rule_new, _ = cast(AsyncMock, mock_interaction.followup.send).call_args
    assert f"Правило '{rule_key}' установлено на '{expected_parsed_value}'" in args_set_rule_new[0]

@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role', return_value=lambda func: func)
async def test_master_set_rule_update_existing_typed(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    guild_id_str = str(mock_interaction.guild_id)
    rule_key = "player.max_hp_on_start"
    value_json_str = "\"100\""
    expected_parsed_value = 100

    existing_config = {"player": {"max_hp_on_start": 50}}

    game_mngr.rule_engine.get_raw_rules_config_dict_for_guild = AsyncMock(return_value=existing_config)
    game_mngr.rule_engine.save_rules_config_for_guild_from_dict = AsyncMock()
    game_mngr.rule_engine.load_rules_config_for_guild = AsyncMock()
    game_mngr.game_log_manager.log_event = AsyncMock()

    await gm_app_cog.cmd_master_set_rule.callback(gm_app_cog, mock_interaction, rule_key=rule_key, value_json=value_json_str)

    saved_config_arg = game_mngr.rule_engine.save_rules_config_for_guild_from_dict.call_args[0][1]
    assert saved_config_arg["player"]["max_hp_on_start"] == expected_parsed_value
    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once()
    args_set_rule_update, _ = cast(AsyncMock, mock_interaction.followup.send).call_args
    assert f"Правило '{rule_key}' установлено на '{expected_parsed_value}'" in args_set_rule_update[0]


@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role', return_value=lambda func: func)
async def test_master_set_rule_invalid_json_value(
    gm_app_cog: GMAppCog,
    mock_interaction: discord.Interaction
):
    game_mngr = gm_app_cog.bot.game_manager
    game_mngr.rule_engine.get_raw_rules_config_dict_for_guild = AsyncMock(return_value={})

    await gm_app_cog.cmd_master_set_rule.callback(gm_app_cog, mock_interaction, rule_key="any.key", value_json="not_a_valid_json")

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once()
    args_set_rule_invalid, _ = cast(AsyncMock, mock_interaction.followup.send).call_args
    assert "Ошибка JSON: `not_a_valid_json`" in args_set_rule_invalid[0]
    game_mngr.rule_engine.save_rules_config_for_guild_from_dict.assert_not_called()

# print("DEBUG: tests/commands/test_gm_app_cmds.py created.") # Removed print from previous merge
