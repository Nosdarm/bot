import pytest
import json
import uuid
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import cast, List, Dict, Any, Callable, Awaitable # Added Callable, Awaitable

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.ext.asyncio import AsyncSession # For session type hint

# Models involved
from bot.database.models.world_related import Location as DBLocation
from bot.services.db_service import DBService # For spec

# Cog to test
from bot.cogs.master_commands import MasterCog

# Import RPGBot for type hinting in fixtures
from bot.bot_core import RPGBot


# --- Fixtures ---
@pytest.fixture
def mock_rpg_bot_mc(event_loop: asyncio.AbstractEventLoop) -> RPGBot: # Added event_loop
    bot = AsyncMock(spec=RPGBot)
    bot.loop = event_loop # Assign loop for discord.py components if needed by cog

    # Mock game_manager and its nested db_service and session factory
    mock_gm = AsyncMock(spec=GameManager)
    mock_db_svc = AsyncMock(spec=DBService)

    # This factory, when called, returns an async context manager for the session
    mock_session_context_mgr_factory = lambda: AsyncMock( # type: ignore[misc]
        __aenter__=AsyncMock(return_value=AsyncMock(spec=AsyncSession)), # This is the session
        __aexit__=AsyncMock(return_value=None)
    )
    mock_db_svc.get_session_factory = MagicMock(return_value=mock_session_context_mgr_factory)

    mock_gm.db_service = mock_db_svc
    bot.game_manager = mock_gm
    bot.get_game_manager = MagicMock(return_value=mock_gm) # If cog uses this getter
    return bot

@pytest.fixture
async def master_cog_fixture(mock_rpg_bot_mc: RPGBot) -> MasterCog: # Renamed fixture
    MasterCog.cog_check = AsyncMock(return_value=True) # type: ignore
    cog = MasterCog(mock_rpg_bot_mc)
    return cog

@pytest.fixture
def mock_location_db_1_mc(mock_interaction: discord.Interaction) -> DBLocation: # Renamed fixture
    return DBLocation(
        id="loc_db_1_mc", # Unique ID for this test suite
        guild_id=str(mock_interaction.guild_id),
        name_i18n='{"en": "Source Location Alpha"}', # Store as JSON strings if DB model expects that
        descriptions_i18n='{"en": "A starting place."}',
        type_i18n='{"en":"Town"}',
        neighbor_locations_json='[]'
    )

@pytest.fixture
def mock_location_db_2_mc(mock_interaction: discord.Interaction) -> DBLocation: # Renamed fixture
    return DBLocation(
        id="loc_db_2_mc", # Unique ID
        guild_id=str(mock_interaction.guild_id),
        name_i18n='{"en": "Target Location Beta"}',
        descriptions_i18n='{"en": "A destination."}',
        type_i18n='{"en":"Forest"}',
        neighbor_locations_json='[]'
    )

# --- Tests for MasterCog Commands ---

@pytest.mark.asyncio
async def test_master_add_location_connection_success(
    master_cog_fixture: MasterCog, # Use renamed fixture
    mock_interaction: discord.Interaction,
    mock_location_db_1_mc: DBLocation, # Use renamed fixture
    mock_location_db_2_mc: DBLocation  # Use renamed fixture
):
    bot_instance = master_cog_fixture.bot
    game_mngr = cast(AsyncMock, bot_instance.game_manager)
    db_service_mock = cast(AsyncMock, game_mngr.db_service)

    # The session factory is already mocked to return an async context manager
    # whose __aenter__ returns a session mock. We get that session mock here.
    session_mock = await db_service_mock.get_session_factory().__aenter__()
    session_mock.commit = AsyncMock() # Ensure commit is AsyncMock

    async def mock_session_get_side_effect(model_cls: Any, pk_value: Any) -> Any:
        if model_cls == DBLocation:
            if pk_value == mock_location_db_1_mc.id: return mock_location_db_1_mc
            if pk_value == mock_location_db_2_mc.id: return mock_location_db_2_mc
        return None
    session_mock.get = AsyncMock(side_effect=mock_session_get_side_effect)

    # Ensure followup.send is an AsyncMock
    mock_interaction.followup.send = AsyncMock()


    connection_details = {
        "direction_i18n": {"en": "North", "ru": "Север"},
        "path_description_i18n": {"en": "A dusty path.", "ru": "Пыльная тропа."},
        "travel_time_hours": 2
    }
    connection_details_json_str = json.dumps(connection_details)

    # Call the command callback correctly
    command: app_commands.Command[MasterCog, ..., Any] = master_cog_fixture.master_add_location_connection
    await command.callback(
        master_cog_fixture, mock_interaction,
        source_location_id=mock_location_db_1_mc.id, # Pass as string
        target_location_id=mock_location_db_2_mc.id,   # Pass as string
        connection_details_json=connection_details_json_str
    )

    session_mock.get.assert_any_call(DBLocation, mock_location_db_1_mc.id)
    session_mock.get.assert_any_call(DBLocation, mock_location_db_2_mc.id)

    # neighbor_locations_json is stored as a string; parse it for assertion
    source_loc_neighbors_list = json.loads(cast(str, mock_location_db_1_mc.neighbor_locations_json))

    assert isinstance(source_loc_neighbors_list, list)
    assert len(source_loc_neighbors_list) == 1
    new_conn = source_loc_neighbors_list[0]
    assert new_conn["to_location_id"] == mock_location_db_2_mc.id
    assert new_conn["direction_i18n"]["en"] == "North"
    assert new_conn["travel_time_hours"] == 2

    session_mock.commit.assert_awaited_once()
    mock_interaction.followup.send.assert_awaited_once()
    # Check type of first arg of call_args
    args, _ = mock_interaction.followup.send.call_args
    assert "Successfully added new connection" in args[0]


@pytest.mark.asyncio
async def test_master_add_location_connection_source_not_found(
    master_cog_fixture: MasterCog, # Use renamed
    mock_interaction: discord.Interaction
):
    bot_instance = master_cog_fixture.bot
    game_mngr = cast(AsyncMock, bot_instance.game_manager)
    db_service_mock = cast(AsyncMock, game_mngr.db_service)
    session_mock = await db_service_mock.get_session_factory().__aenter__()
    session_mock.commit = AsyncMock()
    session_mock.get = AsyncMock(return_value=None) # Source location not found
    mock_interaction.followup.send = AsyncMock()


    command: app_commands.Command[MasterCog, ..., Any] = master_cog_fixture.master_add_location_connection
    await command.callback(
        master_cog_fixture, mock_interaction,
        source_location_id="unknown_loc_1", target_location_id="loc_db_2_mc",
        connection_details_json=json.dumps({"direction_i18n": {"en":"N"}, "path_description_i18n": {"en":"P"}})
    )
    mock_interaction.followup.send.assert_awaited_once_with("Source location with ID 'unknown_loc_1' not found or not in this guild.")
    session_mock.commit.assert_not_awaited()

logger.info("DEBUG: tests/cogs/test_master_commands.py loaded.") # Use logger
