# tests/commands/test_general_cmds.py
import pytest
from unittest.mock import AsyncMock, MagicMock
import discord # For discord.Interaction

from bot.command_modules.general_cmds import GeneralCog

# Mock RPGBot class for type hinting and attribute access
class MockRPGBot:
    def __init__(self):
        self.latency = 0.12345 # Example latency, 123.45 ms
        # Add other attributes if the cog or command uses them

@pytest.fixture
def mock_bot_for_general_cmds():
    return MockRPGBot()

@pytest.fixture
def general_cog(mock_bot_for_general_cmds):
    return GeneralCog(bot=mock_bot_for_general_cmds) # type: ignore

@pytest.fixture
def mock_interaction_general():
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.User)
    interaction.user.name = "TestUser"
    interaction.user.id = "user123"
    interaction.guild_id = "guild123"
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    return interaction

@pytest.mark.asyncio
async def test_ping_command(general_cog: GeneralCog, mock_interaction_general: discord.Interaction, mock_bot_for_general_cmds: MockRPGBot):
    # Set a specific latency on the mock bot instance used by the cog
    mock_bot_for_general_cmds.latency = 0.025 # 25ms

    # The callback for an app command is cog_ récent_holder.command_name.callback(self_or_cog_instance, interaction, **kwargs)
    # For a non-grouped command in a cog, it's usually:
    # await cog_instance.command_name.callback(cog_instance, interaction, ...)
    # The name in @app_commands.command(name="ping") is "ping", but the method is cmd_ping.
    # The callback should be referenced via the command itself if possible, or directly via method.
    # However, discord.py's app command structure means the callback is on the command object itself,
    # which is attached to the cog. For simplicity, we can directly call the method here
    # as if it were invoked by the command handler.

    # If `cmd_ping` is the method:
    await general_cog.cmd_ping.callback(general_cog, mock_interaction_general) # type: ignore

    expected_latency_ms = mock_bot_for_general_cmds.latency * 1000
    expected_message = f"Pong! Задержка: {expected_latency_ms:.2f} мс."

    mock_interaction_general.response.send_message.assert_awaited_once_with(
        expected_message,
        ephemeral=True
    )

# TODO: Add tests for other general commands like /lang if they are in this cog
# The /lang command test would be more involved, similar to /settings set language tests,
# requiring mocking of GameManager, CharacterManager, DB sessions, and Player objects.
# For this subtask, focusing on /ping.
