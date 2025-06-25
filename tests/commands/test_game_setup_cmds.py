import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands # For app_commands.Choice if needed later
from discord.ext import commands

# Models involved
from bot.database.models import Player, Character as DBCharacter # Renamed to avoid pytest fixture conflict
from bot.game.exceptions import CharacterAlreadyExistsError


# Cog to test
from bot.command_modules.game_setup_cmds import GameSetupCog

# Import RPGBot for type hinting in fixtures if necessary, or use commands.Bot
from bot.bot_core import RPGBot


# --- Fixtures ---
# Assuming mock_rpg_bot, mock_interaction, mock_db_session are available from a shared conftest
# or defined similarly to tests/core/test_bot_events_and_basic_commands.py

@pytest.fixture
async def game_setup_cog(mock_rpg_bot: RPGBot): # Use the specific RPGBot type
    cog = GameSetupCog(mock_rpg_bot)
    # await mock_rpg_bot.add_cog(cog) # Not strictly necessary for direct method calls if tree not used
    return cog

# --- Tests for GameSetupCog Commands ---

@pytest.mark.asyncio
async def test_start_new_character_new_player_and_character(
    game_setup_cog: GameSetupCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock # Session mock from conftest
):
    bot_instance = game_setup_cog.bot
    game_mngr = bot_instance.game_manager # This is already an AsyncMock from mock_rpg_bot

    character_name_arg = "Valerius"
    player_language_arg = "en"
    guild_id_str = str(mock_interaction.guild_id)
    discord_id_str = str(mock_interaction.user.id)
    user_display_name = mock_interaction.user.display_name

    # --- Mocking GameManager and DBService behavior ---
    # 1. Player does not exist initially
    game_mngr.db_service.get_session.return_value.__aenter__.return_value = mock_db_session
    # `get_entity_by_attributes` is called inside `/start` to check for existing player.
    # We need to mock the global crud_utils.get_entity_by_attributes if it's directly imported by game_setup_cmds
    # or mock the method on db_service if it wraps it.
    # The command directly uses `select(Player)` then `session.execute`, so we mock `session.execute`

    mock_player_select_result = AsyncMock()
    mock_player_select_result.scalars.return_value.first.return_value = None # No existing player

    # Mock for Player creation via crud_utils.create_entity
    created_player_mock = Player(
        id=str(uuid.uuid4()),
        discord_id=discord_id_str,
        guild_id=guild_id_str,
        name_i18n={"en": user_display_name, player_language_arg: user_display_name},
        selected_language=player_language_arg,
        is_active=True
    )

    # Mock for Character creation
    created_character_mock = DBCharacter(
        id=str(uuid.uuid4()),
        player_id=created_player_mock.id,
        guild_id=guild_id_str,
        name_i18n={"en": character_name_arg, player_language_arg: character_name_arg}
        # Other fields would be set by CharacterManager
    )
    game_mngr.character_manager.create_new_character.return_value = created_character_mock

    # Mock rules for default language and starting location
    game_mngr.get_rule.side_effect = lambda gid, rule_key, default: {
        "default_language": player_language_arg,
        "starting_location_id": "start_loc_id_from_rule"
    }.get(rule_key, default)

    # Patch crud_utils.create_entity specifically for Player creation within the command
    # The command does: new_player_record = await create_entity(session, Player, player_data)
    # So we need to mock `create_entity` in the context of `game_setup_cmds` module
    with patch('bot.command_modules.game_setup_cmds.create_entity', new_callable=AsyncMock, return_value=created_player_mock) as mock_create_player_entity, \
         patch.object(mock_db_session, 'execute', side_effect=[mock_player_select_result, AsyncMock()]) as mock_execute_calls: # First execute for player check, then others
        # Act
        await game_setup_cog.cmd_start_new_character(mock_interaction, character_name_arg, player_language_arg)

    # --- Assertions ---
    # 1. Check for existing player was made
    # `mock_execute_calls.call_args_list[0]` should be the select Player statement
    assert mock_execute_calls.call_count >= 1 # At least the select for player

    # 2. Player was created
    mock_create_player_entity.assert_awaited_once()
    created_player_data = mock_create_player_entity.call_args[0][2] # data dict
    assert created_player_data['discord_id'] == discord_id_str
    assert created_player_data['guild_id'] == guild_id_str
    assert created_player_data['selected_language'] == player_language_arg

    # 3. Character was created
    game_mngr.character_manager.create_new_character.assert_awaited_once_with(
        guild_id=guild_id_str,
        user_id=mock_interaction.user.id, # discord_user_id
        character_name=character_name_arg,
        language=player_language_arg
    )

    # 4. Success message sent
    mock_interaction.followup.send.assert_awaited_once()
    # Check parts of the success message
    success_message_args = mock_interaction.followup.send.call_args[0][0]
    assert f"Персонаж '{character_name_arg}' успешно создан" in success_message_args or \
           f"Персонаж '{created_character_mock.name_i18n.get(player_language_arg, character_name_arg)}' успешно создан" in success_message_args


@pytest.mark.asyncio
async def test_start_new_character_existing_player_new_character(
    game_setup_cog: GameSetupCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock
):
    bot_instance = game_setup_cog.bot
    game_mngr = bot_instance.game_manager

    character_name_arg = "Valerius Secundus"
    player_language_arg = "ru"
    guild_id_str = str(mock_interaction.guild_id)
    discord_id_str = str(mock_interaction.user.id)

    # 1. Player already exists
    existing_player_mock = Player(
        id=str(uuid.uuid4()),
        discord_id=discord_id_str,
        guild_id=guild_id_str,
        selected_language="en" # Existing language
    )
    mock_player_select_result = AsyncMock()
    mock_player_select_result.scalars.return_value.first.return_value = existing_player_mock

    # Mock Character creation
    created_character_mock = DBCharacter(
        id=str(uuid.uuid4()),
        player_id=existing_player_mock.id,
        guild_id=guild_id_str,
        name_i18n={"ru": character_name_arg}
    )
    game_mngr.character_manager.create_new_character.return_value = created_character_mock

    game_mngr.get_rule.side_effect = lambda gid, rule_key, default: player_language_arg if rule_key == "default_language" else default

    with patch('bot.command_modules.game_setup_cmds.create_entity', new_callable=AsyncMock) as mock_create_player_entity, \
         patch.object(mock_db_session, 'execute', return_value=mock_player_select_result): # Only player select needed here
        # Act
        await game_setup_cog.cmd_start_new_character(mock_interaction, character_name_arg, player_language_arg)

    # Assertions
    mock_create_player_entity.assert_not_awaited() # Player should NOT be created

    game_mngr.character_manager.create_new_character.assert_awaited_once_with(
        guild_id=guild_id_str,
        user_id=mock_interaction.user.id,
        character_name=character_name_arg,
        language=player_language_arg # Language for character messages
    )
    mock_interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_new_character_character_already_exists_error(
    game_setup_cog: GameSetupCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock
):
    bot_instance = game_setup_cog.bot
    game_mngr = bot_instance.game_manager
    character_name_arg = "Existing Character Name"

    existing_player_mock = Player(id=str(uuid.uuid4()), discord_id=str(mock_interaction.user.id), guild_id=str(mock_interaction.guild_id))
    mock_player_select_result = AsyncMock()
    mock_player_select_result.scalars.return_value.first.return_value = existing_player_mock

    game_mngr.character_manager.create_new_character.side_effect = CharacterAlreadyExistsError("Test already exists")

    with patch.object(mock_db_session, 'execute', return_value=mock_player_select_result):
        await game_setup_cog.cmd_start_new_character(mock_interaction, character_name_arg, "en")

    mock_interaction.followup.send.assert_awaited_once_with(
        "У вас уже есть персонаж в этой игре. Вы не можете создать еще одного.",
        ephemeral=True
    )

@pytest.mark.asyncio
async def test_start_new_character_player_creation_fails_gracefully(
    game_setup_cog: GameSetupCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock
):
    bot_instance = game_setup_cog.bot
    game_mngr = bot_instance.game_manager
    character_name_arg = "WontBeCreated"

    mock_player_select_result = AsyncMock()
    mock_player_select_result.scalars.return_value.first.return_value = None # No player

    with patch('bot.command_modules.game_setup_cmds.create_entity', new_callable=AsyncMock, return_value=None) as mock_create_player_entity, \
         patch.object(mock_db_session, 'execute', return_value=mock_player_select_result):
        # Act
        await game_setup_cog.cmd_start_new_character(mock_interaction, character_name_arg, "en")

    mock_create_player_entity.assert_awaited_once() # Attempt to create player
    game_mngr.character_manager.create_new_character.assert_not_awaited() # Character creation should not be reached
    mock_interaction.followup.send.assert_awaited_once_with(
        "There was an issue creating your player profile. Please try again.",
        ephemeral=True
    )

print("DEBUG: tests/commands/test_game_setup_cmds.py created.")
