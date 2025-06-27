import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from typing import cast, Optional, Dict, Any as TypingAny # Renamed Any to TypingAny
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

# Models involved
from bot.database.models import Player # Corrected import
from bot.database.models import Character as DBCharacter # Corrected import path
from bot.game.exceptions import CharacterAlreadyExistsError


# Cog to test
from bot.command_modules.game_setup_cmds import GameSetupCog

# Import RPGBot for type hinting in fixtures if necessary, or use commands.Bot
from bot.bot_core import RPGBot
from bot.game.managers.game_manager import GameManager # For spec
from bot.database import crud_utils # For DBService spec


# --- Fixtures ---
@pytest.fixture
def mock_rpg_bot_with_game_manager_for_setup(mock_rpg_bot: RPGBot) -> RPGBot:
    mock_rpg_bot.game_manager = AsyncMock(spec=GameManager)

    # Mock db_service
    db_service_mock = AsyncMock(spec=crud_utils.DBService)
    mock_session_context = AsyncMock()
    mock_session_instance = AsyncMock()
    mock_session_context.__aenter__.return_value = mock_session_instance
    mock_session_context.__aexit__.return_value = None
    db_service_mock.get_session = MagicMock(return_value=mock_session_context)
    mock_rpg_bot.game_manager.db_service = db_service_mock

    # Mock character_manager
    mock_rpg_bot.game_manager.character_manager = AsyncMock()
    mock_rpg_bot.game_manager.character_manager.create_new_character = AsyncMock() # Specific method mock

    # Mock get_rule (often on game_manager or rule_engine)
    mock_rpg_bot.game_manager.get_rule = AsyncMock()

    return mock_rpg_bot

@pytest.fixture
async def game_setup_cog(mock_rpg_bot_with_game_manager_for_setup: RPGBot) -> GameSetupCog:
    # Patch is_master_role decorator to bypass actual role check during tests
    # This assumes is_master_role is used in game_setup_cmds, if not, it can be removed.
    # For /start, it's usually not a master command.
    # with patch('bot.utils.decorators.is_master_role', return_value=lambda func: func):
    cog = GameSetupCog(mock_rpg_bot_with_game_manager_for_setup)
    return cog

# --- Tests for GameSetupCog Commands ---

@pytest.mark.asyncio
async def test_start_new_character_new_player_and_character(
    game_setup_cog: GameSetupCog,
    mock_interaction: discord.Interaction,
    mock_rpg_bot_with_game_manager_for_setup: RPGBot # Use the specific fixture
):
    game_mngr = cast(AsyncMock, mock_rpg_bot_with_game_manager_for_setup.game_manager)
    mock_session = game_mngr.db_service.get_session.return_value.__aenter__.return_value


    character_name_arg = "Valerius"
    player_language_arg = "en"
    guild_id_str = str(mock_interaction.guild_id)
    discord_id_str = str(mock_interaction.user.id)
    user_display_name = mock_interaction.user.display_name

    # --- Mocking GameManager and DBService behavior ---
    # 1. Player does not exist initially
    mock_player_select_result = AsyncMock()
    mock_player_select_result.scalars.return_value.first.return_value = None

    created_player_id = str(uuid.uuid4())
    created_player_mock = Player(
        id=created_player_id, discord_id=discord_id_str, guild_id=guild_id_str,
        name_i18n={"en": user_display_name, player_language_arg: user_display_name},
        selected_language=player_language_arg, is_active=True
    )

    created_character_id = str(uuid.uuid4())
    created_character_mock = DBCharacter(
        id=created_character_id, player_id=created_player_mock.id, guild_id=guild_id_str,
        name_i18n={"en": character_name_arg, player_language_arg: character_name_arg}
    )
    game_mngr.character_manager.create_new_character.return_value = created_character_mock

    def get_rule_side_effect(gid: str, rule_key: str, default: TypingAny) -> TypingAny:
        if rule_key == "default_language": return player_language_arg
        if rule_key == "starting_location_id": return "start_loc_id_from_rule"
        return default
    game_mngr.get_rule.side_effect = get_rule_side_effect

    with patch('bot.command_modules.game_setup_cmds.create_entity', new_callable=AsyncMock, return_value=created_player_mock) as mock_create_player_entity, \
         patch.object(mock_session, 'execute', side_effect=[mock_player_select_result, AsyncMock()]) as mock_execute_calls:
        await game_setup_cog.cmd_start_new_character.callback(game_setup_cog, mock_interaction, character_name_arg, player_language_arg) # type: ignore

    assert mock_execute_calls.call_count >= 1

    mock_create_player_entity.assert_awaited_once()
    created_player_data = mock_create_player_entity.call_args.args[2]
    assert created_player_data['discord_id'] == discord_id_str
    assert created_player_data['guild_id'] == guild_id_str
    assert created_player_data['selected_language'] == player_language_arg

    game_mngr.character_manager.create_new_character.assert_awaited_once_with(
        guild_id=guild_id_str,
        player_id=created_player_id,
        character_name=character_name_arg,
        language=player_language_arg,
        initial_location_id="start_loc_id_from_rule"
    )

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once()
    success_message_args = cast(AsyncMock, mock_interaction.followup.send).call_args.args[0]
    char_name_for_assertion = created_character_mock.name_i18n.get(player_language_arg, character_name_arg) if created_character_mock.name_i18n else character_name_arg
    assert f"Персонаж '{char_name_for_assertion}' успешно создан" in success_message_args


@pytest.mark.asyncio
async def test_start_new_character_existing_player_new_character(
    game_setup_cog: GameSetupCog,
    mock_interaction: discord.Interaction,
    mock_rpg_bot_with_game_manager_for_setup: RPGBot
):
    game_mngr = cast(AsyncMock, mock_rpg_bot_with_game_manager_for_setup.game_manager)
    mock_session = game_mngr.db_service.get_session.return_value.__aenter__.return_value

    character_name_arg = "Valerius Secundus"
    player_language_arg = "ru"
    guild_id_str = str(mock_interaction.guild_id)
    discord_id_str = str(mock_interaction.user.id)
    existing_player_id = str(uuid.uuid4())

    existing_player_mock = Player(
        id=existing_player_id, discord_id=discord_id_str, guild_id=guild_id_str, selected_language="en"
    )
    mock_player_select_result = AsyncMock()
    mock_player_select_result.scalars.return_value.first.return_value = existing_player_mock

    created_character_mock = DBCharacter(
        id=str(uuid.uuid4()), player_id=existing_player_mock.id, guild_id=guild_id_str, name_i18n={"ru": character_name_arg}
    )
    game_mngr.character_manager.create_new_character.return_value = created_character_mock

    def get_rule_side_effect_existing(gid: str, rule_key: str, default: TypingAny) -> TypingAny:
        if rule_key == "default_language": return player_language_arg # This might be overwritten by player's selected_language
        if rule_key == "starting_location_id": return "start_loc_existing_player"
        return default
    game_mngr.get_rule.side_effect = get_rule_side_effect_existing


    with patch('bot.command_modules.game_setup_cmds.create_entity', new_callable=AsyncMock) as mock_create_player_entity, \
         patch.object(mock_session, 'execute', return_value=mock_player_select_result):
        await game_setup_cog.cmd_start_new_character.callback(game_setup_cog, mock_interaction, character_name_arg, player_language_arg) # type: ignore

    mock_create_player_entity.assert_not_awaited()

    game_mngr.character_manager.create_new_character.assert_awaited_once_with(
        guild_id=guild_id_str,
        player_id=existing_player_id,
        character_name=character_name_arg,
        language=player_language_arg,
        initial_location_id="start_loc_existing_player"
    )
    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once()


@pytest.mark.asyncio
async def test_start_new_character_character_already_exists_error(
    game_setup_cog: GameSetupCog,
    mock_interaction: discord.Interaction,
    mock_rpg_bot_with_game_manager_for_setup: RPGBot
):
    game_mngr = cast(AsyncMock, mock_rpg_bot_with_game_manager_for_setup.game_manager)
    mock_session = game_mngr.db_service.get_session.return_value.__aenter__.return_value
    character_name_arg = "Existing Character Name"

    existing_player_mock = Player(id=str(uuid.uuid4()), discord_id=str(mock_interaction.user.id), guild_id=str(mock_interaction.guild_id))
    mock_player_select_result = AsyncMock()
    mock_player_select_result.scalars.return_value.first.return_value = existing_player_mock

    game_mngr.character_manager.create_new_character.side_effect = CharacterAlreadyExistsError("Test already exists")

    with patch.object(mock_session, 'execute', return_value=mock_player_select_result):
        await game_setup_cog.cmd_start_new_character.callback(game_setup_cog, mock_interaction, character_name_arg, "en") # type: ignore

    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once_with(
        "У вас уже есть персонаж в этой игре. Вы не можете создать еще одного.",
        ephemeral=True
    )

@pytest.mark.asyncio
async def test_start_new_character_player_creation_fails_gracefully(
    game_setup_cog: GameSetupCog,
    mock_interaction: discord.Interaction,
    mock_rpg_bot_with_game_manager_for_setup: RPGBot
):
    game_mngr = cast(AsyncMock, mock_rpg_bot_with_game_manager_for_setup.game_manager)
    mock_session = game_mngr.db_service.get_session.return_value.__aenter__.return_value
    character_name_arg = "WontBeCreated"

    mock_player_select_result = AsyncMock()
    mock_player_select_result.scalars.return_value.first.return_value = None

    with patch('bot.command_modules.game_setup_cmds.create_entity', new_callable=AsyncMock, return_value=None) as mock_create_player_entity, \
         patch.object(mock_session, 'execute', return_value=mock_player_select_result):
        await game_setup_cog.cmd_start_new_character.callback(game_setup_cog, mock_interaction, character_name_arg, "en") # type: ignore

    mock_create_player_entity.assert_awaited_once()
    game_mngr.character_manager.create_new_character.assert_not_awaited()
    cast(AsyncMock, mock_interaction.followup.send).assert_awaited_once_with(
        "There was an issue creating your player profile. Please try again.",
        ephemeral=True
    )

print("DEBUG: tests/commands/test_game_setup_cmds.py overwritten with Pyright fixes.")
