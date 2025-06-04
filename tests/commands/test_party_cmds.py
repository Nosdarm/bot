import unittest
from unittest.mock import MagicMock, AsyncMock, patch

import discord

# Assuming your party commands are in a cog or a module like this:
# Adjust the import path to where your PartyCommands class or functions are located.
from bot.command_modules.party_cmds import PartyCommands

# Models (primarily for type hinting or if manager methods return them directly)
from bot.game.models.character import Character
from bot.game.models.party import Party

# Managers
from bot.game.managers.game_manager import GameManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager


class TestPartyCommands(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.bot = MagicMock() # Mock bot instance if your cog needs it

        # Mock GameManager and its sub-managers
        self.mock_game_manager = MagicMock()
        self.mock_party_manager = MagicMock()
        self.mock_character_manager = MagicMock()
        self.mock_location_manager = MagicMock()

        # Assign mocked managers to the mock_game_manager instance
        self.mock_game_manager.party_manager = self.mock_party_manager
        self.mock_game_manager.character_manager = self.mock_character_manager
        self.mock_game_manager.location_manager = self.mock_location_manager

        # Instantiate the cog with mocked dependencies
        self.cog = PartyCommands(bot=self.bot, game_manager=self.mock_game_manager)

        # Mock interaction object
        self.interaction = AsyncMock(spec=discord.Interaction)
        self.interaction.user = MagicMock(spec=discord.Member)
        self.interaction.user.id = 12345
        self.interaction.user.name = "TestUser"
        self.interaction.guild = MagicMock(spec=discord.Guild)
        self.interaction.guild.id = 67890
        self.interaction.channel = MagicMock(spec=discord.TextChannel) # or app_commands.AppCommandChannel
        self.interaction.response = AsyncMock(spec=discord.InteractionResponse)

        # Common character mock
        self.mock_player_character = MagicMock()
        self.mock_player_character.id = "char_12345"
        self.mock_player_character.name = "PlayerChar"
        self.mock_player_character.party_id = None # Default: not in a party
        self.mock_player_character.location_id = "location_A"

        self.mock_character_manager.get_character.return_value = self.mock_player_character

        # Reset mocks for managers that return values or have side effects per test
        self._reset_manager_mocks()

    def _reset_manager_mocks(self):
        # Reset relevant async mocks and return values
        self.mock_party_manager.create_party = AsyncMock(return_value="new_party_123") # Assume returns party_id
        self.mock_party_manager.get_party_by_member_id = AsyncMock(return_value=None) # Default: player not in party
        self.mock_party_manager.get_party = AsyncMock(return_value=None) # Default: party not found by ID/name
        self.mock_party_manager.add_member_to_party = AsyncMock(return_value=True)
        self.mock_party_manager.remove_member_from_party = AsyncMock(return_value=True)
        self.mock_party_manager.disband_party = AsyncMock(return_value=True)

        self.mock_character_manager.get_character = AsyncMock(return_value=self.mock_player_character)
        # self.mock_character_manager.update_character_party_id = AsyncMock() # If used directly

    async def test_party_create_successful(self):
        self._reset_manager_mocks()
        self.mock_party_manager.get_party_by_member_id.return_value = None # Not in a party

        party_name = "The Valiant Few"
        await self.cog.party_create.callback(self.cog, self.interaction, name=party_name)

        self.mock_character_manager.get_character.assert_called_once_with(
            str(self.interaction.guild.id), str(self.interaction.user.id)
        )
        self.mock_party_manager.get_party_by_member_id.assert_called_once_with(
            str(self.interaction.guild.id), self.mock_player_character.id
        )
        self.mock_party_manager.create_party.assert_called_once_with(
            guild_id=str(self.interaction.guild.id),
            leader_char_id=self.mock_player_character.id,
            party_name=party_name,
            leader_location_id=self.mock_player_character.location_id
        )
        self.interaction.response.send_message.assert_called_once()
        self.assertIn(f"Party '{party_name}' created", self.interaction.response.send_message.call_args[0][0].lower())

    async def test_party_create_already_in_party(self):
        self._reset_manager_mocks()
        self.mock_party_manager.get_party_by_member_id.return_value = MagicMock(id="existing_party_id") # Already in a party

        await self.cog.party_create.callback(self.cog, self.interaction, name="New Party")

        self.mock_party_manager.create_party.assert_not_called()
        self.interaction.response.send_message.assert_called_once_with("You are already in a party.", ephemeral=True)

    async def test_party_join_successful(self):
        self._reset_manager_mocks()
        self.mock_party_manager.get_party_by_member_id.return_value = None # Player not in a party

        target_party_id_or_name = "PartyToJoin"

        mock_target_party = MagicMock()
        mock_target_party.id = "party_to_join_id"
        mock_target_party.name = "Party To Join"
        mock_target_party.leader_id = "leader_char_id"
        mock_target_party.get_member_ids = MagicMock(return_value=["leader_char_id"])
        mock_target_party.location_id = "location_A" # Same location
        self.mock_party_manager.get_party.return_value = mock_target_party

        # Mock leader character for location check (if applicable by PartyManager.add_member_to_party)
        mock_leader_char = MagicMock()
        mock_leader_char.location_id = "location_A"
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=mock_leader_char)


        await self.cog.party_join.callback(self.cog, self.interaction, name_or_id=target_party_id_or_name)

        self.mock_party_manager.get_party.assert_called_once_with(str(self.interaction.guild.id), target_party_id_or_name)
        self.mock_party_manager.add_member_to_party.assert_called_once_with(
            guild_id=str(self.interaction.guild.id),
            party_id=mock_target_party.id,
            character_id=self.mock_player_character.id,
            character_location_id=self.mock_player_character.location_id
        )
        self.interaction.response.send_message.assert_called_once()
        self.assertIn(f"joined party '{mock_target_party.name}'", self.interaction.response.send_message.call_args[0][0].lower())

    async def test_party_join_different_location_fail(self):
        self._reset_manager_mocks()
        self.mock_party_manager.get_party_by_member_id.return_value = None

        target_party_id_or_name = "PartyToJoin"
        mock_target_party = MagicMock()
        mock_target_party.id = "party_to_join_id"
        mock_target_party.name = "Party To Join"
        mock_target_party.location_id = "location_B" # Different location
        self.mock_party_manager.get_party.return_value = mock_target_party

        # Simulate PartyManager.add_member_to_party returning False due to location mismatch
        self.mock_party_manager.add_member_to_party.return_value = False
        # And potentially setting a reason attribute or similar if your manager does that
        # For this test, we'll assume the command checks the return value and provides a generic message
        # or PartyManager's add_member logs/raises an error that the command catches.
        # Let's assume it returns a specific string message on failure from PartyManager for this test.
        self.mock_party_manager.add_member_to_party.side_effect = Exception("Cannot join party in a different location.")


        await self.cog.party_join.callback(self.cog, self.interaction, name_or_id=target_party_id_or_name)

        self.interaction.response.send_message.assert_called_once()
        response_text = self.interaction.response.send_message.call_args[0][0].lower()
        self.assertIn("could not join", response_text)
        # Check if the specific exception message is part of the response, if the command includes it
        # self.assertIn("different location", response_text) # This depends on specific error handling in command

    async def test_party_join_non_existent_party(self):
        self._reset_manager_mocks()
        self.mock_party_manager.get_party_by_member_id.return_value = None # Player not in a party
        self.mock_party_manager.get_party.return_value = None # Party not found

        await self.cog.party_join.callback(self.cog, self.interaction, name_or_id="GhostParty")

        self.mock_party_manager.get_party.assert_called_once_with(str(self.interaction.guild.id), "GhostParty")
        self.mock_party_manager.add_member_to_party.assert_not_called()
        self.interaction.response.send_message.assert_called_once_with("Party 'GhostParty' not found.", ephemeral=True)

    async def test_party_join_party_full(self):
        self._reset_manager_mocks()
        self.mock_party_manager.get_party_by_member_id.return_value = None

        target_party_name = "FullHouseParty"
        mock_target_party = MagicMock(id="full_party_id", name=target_party_name, location_id="location_A")
        self.mock_party_manager.get_party.return_value = mock_target_party

        # Simulate PartyManager.add_member_to_party failing due to party being full
        self.mock_party_manager.add_member_to_party.return_value = False
        # If your manager raises a specific error for full party:
        # from bot.game.managers.party_manager import PartyFullError # Assuming such an error exists
        # self.mock_party_manager.add_member_to_party.side_effect = PartyFullError("Party is full.")

        await self.cog.party_join.callback(self.cog, self.interaction, name_or_id=target_party_name)

        self.interaction.response.send_message.assert_called_once()
        # This message depends on how the command handles add_member_to_party returning False
        self.assertIn(f"could not join party '{target_party_name}'", self.interaction.response.send_message.call_args[0][0].lower())
        # If a specific error message is expected:
        # self.assertIn("party is full", self.interaction.response.send_message.call_args[0][0].lower())


    async def test_party_leave_successful(self):
        self._reset_manager_mocks()
        mock_current_party = MagicMock()
        mock_current_party.id = "current_party_id"
        mock_current_party.name = "My Current Party"
        self.mock_party_manager.get_party_by_member_id.return_value = mock_current_party
        self.mock_player_character.party_id = mock_current_party.id


        await self.cog.party_leave.callback(self.cog, self.interaction)

        self.mock_party_manager.remove_member_from_party.assert_called_once_with(
            guild_id=str(self.interaction.guild.id),
            party_id=mock_current_party.id,
            character_id=self.mock_player_character.id
        )
        self.interaction.response.send_message.assert_called_once_with(f"You have left party '{mock_current_party.name}'.")

    async def test_party_leave_not_in_party(self):
        self._reset_manager_mocks()
        self.mock_party_manager.get_party_by_member_id.return_value = None # Player not in any party
        self.mock_player_character.party_id = None

        await self.cog.party_leave.callback(self.cog, self.interaction)

        self.mock_party_manager.remove_member_from_party.assert_not_called()
        self.interaction.response.send_message.assert_called_once_with("You are not currently in a party.", ephemeral=True)


    async def test_party_disband_successful(self):
        self._reset_manager_mocks()
        mock_current_party = MagicMock()
        mock_current_party.id = "party_to_disband_id"
        mock_current_party.name = "Party To Disband"
        mock_current_party.leader_id = self.mock_player_character.id # Player is the leader
        self.mock_party_manager.get_party_by_member_id.return_value = mock_current_party
        self.mock_player_character.party_id = mock_current_party.id


        await self.cog.party_disband.callback(self.cog, self.interaction)

        self.mock_party_manager.disband_party.assert_called_once_with(
            guild_id=str(self.interaction.guild.id),
            party_id=mock_current_party.id,
            character_id=self.mock_player_character.id # Verifying leader
        )
        self.interaction.response.send_message.assert_called_once()
        self.assertIn(f"party '{mock_current_party.name}' has been disbanded", self.interaction.response.send_message.call_args[0][0].lower())

    async def test_party_disband_not_leader(self):
        self._reset_manager_mocks()
        mock_current_party = MagicMock()
        mock_current_party.id = "party_id"
        mock_current_party.name = "Some Party"
        mock_current_party.leader_id = "another_char_id" # Player is NOT the leader
        self.mock_party_manager.get_party_by_member_id.return_value = mock_current_party
        self.mock_player_character.party_id = mock_current_party.id

        # Simulate PartyManager.disband_party returning False or raising error if not leader
        self.mock_party_manager.disband_party.return_value = False
        # Or self.mock_party_manager.disband_party.side_effect = SomePermissionError("Not leader")


        await self.cog.party_disband.callback(self.cog, self.interaction)

        self.mock_party_manager.disband_party.assert_called_once_with(
            guild_id=str(self.interaction.guild.id),
            party_id=mock_current_party.id,
            character_id=self.mock_player_character.id
        )
        self.interaction.response.send_message.assert_called_once()
        # Check for a message indicating player is not the leader
        self.assertIn("only the party leader can disband the party", self.interaction.response.send_message.call_args[0][0].lower())


if __name__ == '__main__':
    unittest.main()
