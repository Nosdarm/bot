import pytest
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands # For app_commands.Choice if needed later
from discord.ext import commands

# Models involved
from bot.database.models.world_related import Location as DBLocation

# Cog to test
from bot.cogs.master_commands import MasterCog

# Import RPGBot for type hinting in fixtures
from bot.bot_core import RPGBot


# --- Fixtures ---
# Assuming mock_rpg_bot, mock_interaction, mock_db_session are available from a shared conftest
# For MasterCog, it uses self.bot.get_game_manager()
# The game_manager then has db_service, which has get_session_factory

@pytest.fixture
async def master_cog(mock_rpg_bot: RPGBot):
    # Mock the cog_check for is_master_role to always pass for these tests
    # We are unit testing the command logic, not the permission system here.
    # The cog_check itself on MasterCog is an async method.
    MasterCog.cog_check = AsyncMock(return_value=True) # type: ignore

    cog = MasterCog(mock_rpg_bot)
    return cog

@pytest.fixture
def mock_location_db_1(mock_interaction: discord.Interaction) -> DBLocation:
    return DBLocation(
        id="loc_db_1",
        guild_id=str(mock_interaction.guild_id),
        name_i18n={"en": "Source Location Alpha"},
        descriptions_i18n={"en": "A starting place."},
        type_i18n={"en":"Town"},
        neighbor_locations_json=[] # Start with no connections
    )

@pytest.fixture
def mock_location_db_2(mock_interaction: discord.Interaction) -> DBLocation:
    return DBLocation(
        id="loc_db_2",
        guild_id=str(mock_interaction.guild_id),
        name_i18n={"en": "Target Location Beta"},
        descriptions_i18n={"en": "A destination."},
        type_i18n={"en":"Forest"},
        neighbor_locations_json=[]
    )

# --- Tests for MasterCog Commands ---

# Tests for /master_add_location_connection
@pytest.mark.asyncio
async def test_master_add_location_connection_success(
    master_cog: MasterCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock, # Session mock from conftest
    mock_location_db_1: DBLocation,
    mock_location_db_2: DBLocation
):
    bot_instance = master_cog.bot
    game_mngr = bot_instance.game_manager # This is an AsyncMock

    # Configure the mock session factory on db_service to return our mock_session context manager
    mock_session_context_manager = AsyncMock()
    mock_session_context_manager.__aenter__.return_value = mock_db_session
    mock_session_context_manager.__aexit__ = AsyncMock(return_value=None)
    game_mngr.db_service.get_session_factory.return_value = lambda: mock_session_context_manager

    # Mock session.get for locations
    async def mock_session_get_side_effect(model_cls, pk_value):
        if model_cls == DBLocation:
            if pk_value == mock_location_db_1.id: return mock_location_db_1
            if pk_value == mock_location_db_2.id: return mock_location_db_2
        return None
    mock_db_session.get = AsyncMock(side_effect=mock_session_get_side_effect)
    mock_db_session.commit = AsyncMock() # To check if it's called

    connection_details = {
        "direction_i18n": {"en": "North", "ru": "Север"},
        "path_description_i18n": {"en": "A dusty path.", "ru": "Пыльная тропа."},
        "travel_time_hours": 2
    }
    connection_details_json_str = json.dumps(connection_details)

    await master_cog.master_add_location_connection.callback(
        master_cog, mock_interaction,
        source_location_id=mock_location_db_1.id,
        target_location_id=mock_location_db_2.id,
        connection_details_json=connection_details_json_str
    )

    # Assertions
    mock_db_session.get.assert_any_call(DBLocation, mock_location_db_1.id)
    mock_db_session.get.assert_any_call(DBLocation, mock_location_db_2.id)

    assert mock_location_db_1.neighbor_locations_json is not None
    assert len(mock_location_db_1.neighbor_locations_json) == 1
    new_conn = mock_location_db_1.neighbor_locations_json[0]
    assert new_conn["to_location_id"] == mock_location_db_2.id
    assert new_conn["direction_i18n"]["en"] == "North"
    assert new_conn["travel_time_hours"] == 2

    # Check that flag_modified was called (indirectly, by checking session.add or if the object is dirty)
    # For this test, we'll check commit, assuming merge/add happened.
    mock_db_session.commit.assert_awaited_once()

    mock_interaction.followup.send.assert_awaited_once()
    assert "Successfully added new connection" in mock_interaction.followup.send.call_args[0][0]


@pytest.mark.asyncio
async def test_master_add_location_connection_source_not_found(
    master_cog: MasterCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock
):
    game_mngr = master_cog.bot.game_manager
    mock_session_context_manager = AsyncMock()
    mock_session_context_manager.__aenter__.return_value = mock_db_session
    mock_session_context_manager.__aexit__ = AsyncMock(return_value=None)
    game_mngr.db_service.get_session_factory.return_value = lambda: mock_session_context_manager

    mock_db_session.get.return_value = None # Source location not found

    await master_cog.master_add_location_connection.callback(
        master_cog, mock_interaction,
        source_location_id="unknown_loc_1", target_location_id="loc_db_2",
        connection_details_json=json.dumps({"direction_i18n": {"en":"N"}, "path_description_i18n": {"en":"P"}})
    )
    mock_interaction.followup.send.assert_awaited_once_with("Source location with ID 'unknown_loc_1' not found or not in this guild.")
    mock_db_session.commit.assert_not_awaited()

# TODO: Add more tests for master_add_location_connection (target_not_found, invalid_json, already_exists, to_self)
# TODO: Add tests for master_modify_location_connection
# TODO: Add tests for master_remove_location_connection

# Placeholder for future /master add_location and /master remove_location tests
# These commands are not yet in MasterCog.py
# @pytest.mark.asyncio
# async def test_master_add_location_success(master_cog, mock_interaction, mock_db_session): ...
# @pytest.mark.asyncio
# async def test_master_remove_location_success(master_cog, mock_interaction, mock_db_session): ...

print("DEBUG: tests/cogs/test_master_commands.py created.")
