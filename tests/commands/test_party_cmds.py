import unittest
from unittest.mock import MagicMock, AsyncMock, patch

import discord

# Assuming your party commands are in a cog or a module like this:
# Adjust the import path to where your PartyCommands class or functions are located.
from bot.command_modules.party_cmds import PartyCog

# Models (primarily for type hinting or if manager methods return them directly)
from bot.game.models.character import Character
from bot.game.models.character import Character as Player
from bot.game.models.party import Party

# Managers
from bot.game.managers.game_manager import GameManager
from bot.game.managers.party_manager import PartyManager
from bot.game.exceptions import CharacterAlreadyInPartyError, CharacterNotInPartyError, NotPartyLeaderError, PartyFullError
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
        self.bot.game_manager = self.mock_game_manager # Ensure bot instance has game_manager

        # Instantiate the cog with mocked dependencies
        self.cog = PartyCog(bot=self.bot)

        # Mock interaction object
        self.interaction = AsyncMock(spec=discord.Interaction)
        self.interaction.user = MagicMock(spec=discord.Member)
        self.interaction.user.id = "user_discord_id_123" # Use string for discord_id
        self.interaction.user.name = "TestUser"
        self.interaction.guild = MagicMock(spec=discord.Guild)
        self.interaction.guild.id = "guild_discord_id_67890" # Use string for guild_id
        self.interaction.guild_id = self.interaction.guild.id # Ensure guild_id is directly set
        self.interaction.channel = MagicMock(spec=discord.TextChannel)
        self.interaction.response = AsyncMock(spec=discord.InteractionResponse)
        self.interaction.followup = AsyncMock(spec=discord.Webhook) # For deferred responses


        # Mock Player (SQLAlchemy model)
        self.mock_player_account = MagicMock(spec=Player)
        self.mock_player_account.id = "player_db_id_1"
        self.mock_player_account.discord_id = self.interaction.user.id
        self.mock_player_account.guild_id = self.interaction.guild.id
        self.mock_player_account.active_character_id = "char_active_1"
        self.mock_player_account.selected_language = "en"

        # Mock Character (SQLAlchemy model, returned by CharacterManager.get_character)
        self.mock_player_character_db = MagicMock(spec=Character) # This is DB Character
        self.mock_player_character_db.id = "char_active_1"
        self.mock_player_character_db.name_i18n = {"en": "PlayerChar"}
        self.mock_player_character_db.current_party_id = None # Default: not in a party
        self.mock_player_character_db.current_location_id = "location_A"
        self.mock_player_character_db.guild_id = self.interaction.guild.id

        # Setup GameManager mocks
        self.mock_game_manager.get_player_model_by_discord_id = AsyncMock(return_value=self.mock_player_account)
        self.mock_game_manager.get_rule = AsyncMock(return_value="en") # Default lang for party name

        # Setup CharacterManager mocks
        self.mock_character_manager.get_character = AsyncMock(return_value=self.mock_player_character_db)
        self.mock_character_manager.save_character_field = AsyncMock(return_value=True)

        self._reset_party_manager_mocks()

    def _reset_party_manager_mocks(self):
        # PartyManager methods now often return Pydantic Party or raise specific errors
        self.mock_party_manager.create_party = AsyncMock(
            return_value=Party(id="new_party_123", name_i18n={"en": "Test Party"}, player_ids_list=[self.mock_player_character_db.id] if self.mock_player_character_db else [])
        )
        self.mock_party_manager.get_party = AsyncMock(return_value=None) # Default: party not found
        self.mock_party_manager.join_party = AsyncMock(return_value=True)
        self.mock_party_manager.leave_party = AsyncMock(return_value=True)
        self.mock_party_manager.disband_party = AsyncMock(return_value=True)
        self.mock_party_manager.get_party_members = AsyncMock(return_value=[self.mock_player_character_db] if self.mock_player_character_db else []) # Returns list of Pydantic/DB Characters

    async def test_party_create_successful(self):
        self._reset_party_manager_mocks()
        # Ensure character is not in a party initially
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = None
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db

        party_name_param = "The Valiant Few" # Renamed to avoid conflict
        expected_party_name_i18n = {"en": party_name_param}
        # Ensure the mock create_party returns the correct party name for this test
        self.mock_party_manager.create_party = AsyncMock(
            return_value=Party(id="new_party_valiant", name_i18n=expected_party_name_i18n, player_ids_list=[self.mock_player_character_db.id] if self.mock_player_character_db else [])
        )

        # Access callback correctly
        command_callback = self.cog.cmd_party_create.callback # type: ignore
        await command_callback(self.cog, self.interaction, name=party_name_param)


        self.mock_game_manager.get_player_model_by_discord_id.assert_awaited_once_with(
            guild_id=str(self.interaction.guild.id), discord_id=str(self.interaction.user.id)
        )
        self.mock_party_manager.create_party.assert_awaited_once_with(
            guild_id=str(self.interaction.guild.id),
            leader_character_id=self.mock_player_character_db.id if self.mock_player_character_db else None,
            party_name_i18n=expected_party_name_i18n
        )
        self.interaction.followup.send.assert_awaited_once()
        self.assertIn(f"Группа '{party_name_param}'", self.interaction.followup.send.call_args[0][0])
        self.assertIn("успешно создана!", self.interaction.followup.send.call_args[0][0])

    async def test_party_create_already_in_party(self):
        self._reset_party_manager_mocks()
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = "existing_party_id"
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db
        self.mock_party_manager.create_party.side_effect = CharacterAlreadyInPartyError("Already in party")

        command_callback = self.cog.cmd_party_create.callback # type: ignore
        await command_callback(self.cog, self.interaction, name="New Party")

        self.interaction.followup.send.assert_awaited_once_with("Вы уже состоите в группе. Сначала покиньте текущую группу.", ephemeral=True)

    async def test_party_create_no_active_character(self):
        self._reset_party_manager_mocks()
        if self.mock_player_account:
            self.mock_player_account.active_character_id = None
        self.mock_game_manager.get_player_model_by_discord_id.return_value = self.mock_player_account

        command_callback = self.cog.cmd_party_create.callback # type: ignore
        await command_callback(self.cog, self.interaction, name="A Party")


        self.interaction.followup.send.assert_awaited_once_with(
            "У вас должен быть активный персонаж для создания группы. Используйте `/character select` или `/character create`.",
            ephemeral=True
        )
        self.mock_party_manager.create_party.assert_not_called()


    async def test_party_join_successful(self):
        self._reset_party_manager_mocks()
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = None
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db

        target_party_identifier_param = "PartyToJoinID" # Renamed
        mock_target_party_db = MagicMock(spec=Party)
        mock_target_party_db.id = target_party_identifier_param
        mock_target_party_db.name_i18n = {"en": "Party To Join"}
        mock_target_party_db.current_location_id = "location_A"
        if self.mock_player_character_db:
            self.mock_player_character_db.current_location_id = "location_A"

        self.mock_party_manager.get_party.return_value = mock_target_party_db
        self.mock_party_manager.join_party.return_value = True

        command_callback = self.cog.cmd_party_join.callback # type: ignore
        await command_callback(self.cog, self.interaction, identifier=target_party_identifier_param)

        self.mock_party_manager.get_party.assert_awaited_once_with(str(self.interaction.guild.id), target_party_identifier_param)
        self.mock_party_manager.join_party.assert_awaited_once_with(
            guild_id=str(self.interaction.guild.id),
            character_id=self.mock_player_character_db.id if self.mock_player_character_db else None,
            party_id=mock_target_party_db.id
        )
        self.interaction.followup.send.assert_awaited_once()
        self.assertIn(f"Вы успешно присоединились к группе '{mock_target_party_db.name_i18n['en']}'", self.interaction.followup.send.call_args[0][0])

    async def test_party_join_different_location_fail(self):
        self._reset_party_manager_mocks()
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = None
            self.mock_player_character_db.current_location_id = "location_A"
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db

        target_party_identifier_param = "FarAwayParty" # Renamed
        mock_target_party_db = MagicMock(spec=Party)
        mock_target_party_db.id = target_party_identifier_param
        mock_target_party_db.name_i18n = {"en": "Far Away Party"}
        mock_target_party_db.current_location_id = "location_B"
        self.mock_party_manager.get_party.return_value = mock_target_party_db

        async def get_loc_instance_side_effect(guild_id, loc_id):
            if loc_id == "location_A": return MagicMock(name_i18n={"en": "Player's Spot"})
            if loc_id == "location_B": return MagicMock(name_i18n={"en": "Party's Hideout"})
            return None
        self.mock_location_manager.get_location_instance = AsyncMock(side_effect=get_loc_instance_side_effect)

        command_callback = self.cog.cmd_party_join.callback # type: ignore
        await command_callback(self.cog, self.interaction, identifier=target_party_identifier_param)

        self.interaction.followup.send.assert_awaited_once()
        response_text = self.interaction.followup.send.call_args[0][0]
        self.assertIn("Вы должны находиться в той же локации, что и группа.", response_text)
        self.assertIn("Вы: 'Player's Spot'", response_text)
        self.assertIn("Группа: 'Party's Hideout'", response_text)
        self.mock_party_manager.join_party.assert_not_called()


    async def test_party_join_party_full(self):
        self._reset_party_manager_mocks()
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = None
            self.mock_player_character_db.current_location_id = "location_A"
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db

        target_party_identifier_param = "FullHouseParty" # Renamed
        mock_target_party_db = MagicMock(spec=Party)
        mock_target_party_db.id = target_party_identifier_param
        mock_target_party_db.name_i18n = {"en": "Full House Party"}
        mock_target_party_db.current_location_id = "location_A"
        self.mock_party_manager.get_party.return_value = mock_target_party_db

        self.mock_party_manager.join_party.side_effect = PartyFullError("Party is full.")

        command_callback = self.cog.cmd_party_join.callback # type: ignore
        await command_callback(self.cog, self.interaction, identifier=target_party_identifier_param)
        self.interaction.followup.send.assert_awaited_once_with("Группа уже заполнена.", ephemeral=True)


    async def test_party_leave_successful(self):
        self._reset_party_manager_mocks()
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = "current_party_id"
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db
        self.mock_party_manager.leave_party.return_value = True

        command_callback = self.cog.cmd_party_leave.callback # type: ignore
        await command_callback(self.cog, self.interaction)


        self.mock_party_manager.leave_party.assert_awaited_once_with(
            guild_id=str(self.interaction.guild.id),
            character_id=self.mock_player_character_db.id if self.mock_player_character_db else None
        )
        self.interaction.followup.send.assert_awaited_once_with("Вы успешно покинули группу.", ephemeral=False)

    async def test_party_leave_not_in_party(self):
        self._reset_party_manager_mocks()
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = None
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db
        self.mock_party_manager.leave_party.side_effect = CharacterNotInPartyError("Not in party")

        command_callback = self.cog.cmd_party_leave.callback # type: ignore
        await command_callback(self.cog, self.interaction)
        self.interaction.followup.send.assert_awaited_once_with("Вы не состоите в какой-либо группе.", ephemeral=True)


    async def test_party_disband_successful(self):
        self._reset_party_manager_mocks()
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = "party_to_disband_id"
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db
        self.mock_party_manager.disband_party.return_value = True

        command_callback = self.cog.cmd_party_disband.callback # type: ignore
        await command_callback(self.cog, self.interaction)


        self.mock_party_manager.disband_party.assert_awaited_once_with(
            guild_id=str(self.interaction.guild.id),
            party_id="party_to_disband_id",
            disbanding_character_id=self.mock_player_character_db.id if self.mock_player_character_db else None
        )
        self.interaction.followup.send.assert_awaited_once()
        self.assertIn("Группа (ID: `party_to_disband_id`) успешно распущена.", self.interaction.followup.send.call_args[0][0])

    async def test_party_disband_not_leader(self):
        self._reset_party_manager_mocks()
        if self.mock_player_character_db:
            self.mock_player_character_db.current_party_id = "party_id_not_leader"
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db
        self.mock_party_manager.disband_party.side_effect = NotPartyLeaderError("Not leader")

        command_callback = self.cog.cmd_party_disband.callback # type: ignore
        await command_callback(self.cog, self.interaction)
        self.interaction.followup.send.assert_awaited_once_with("Только лидер группы может ее распустить.", ephemeral=True)

    # TODO: Add tests for /party view command
    # This will involve mocking get_party, get_party_members, get_character (for leader/members), get_location_instance

    async def test_party_view_current_party_success(self):
        self._reset_party_manager_mocks()
        party_id = "current_party_view_id"
        self.mock_player_character_db.current_party_id = party_id
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db

        mock_party_to_view = MagicMock(spec=Party) # Assuming PartyManager returns Pydantic/DB model
        mock_party_to_view.id = party_id
        mock_party_to_view.name_i18n = {"en": "My Current Crew"}
        mock_party_to_view.leader_id = self.mock_player_character_db.id
        mock_party_to_view.current_location_id = "loc_party_view"
        mock_party_to_view.player_ids_list = [self.mock_player_character_db.id] # Simulate as list if that's what model has

        self.mock_party_manager.get_party.return_value = mock_party_to_view

        # Mock leader character details (same as current player for this test)
        self.mock_character_manager.get_character.side_effect = lambda gid, char_id: self.mock_player_character_db if char_id == self.mock_player_character_db.id else None

        # Mock party members (just the leader for simplicity here)
        self.mock_player_character_db.character_class = "TestClass" # Add character_class mock
        self.mock_party_manager.get_party_members.return_value = [self.mock_player_character_db]

        # Mock location name
        mock_location_obj = MagicMock()
        mock_location_obj.name_i18n = {"en": "Party Hangout"}
        # Ensure get_location_instance is an AsyncMock for this test and returns an awaitable result or a direct MagicMock
        self.mock_location_manager.get_location_instance = AsyncMock(return_value=mock_location_obj)


        await self.cog.cmd_party_view.callback(self.cog, self.interaction, target=None)

        self.mock_party_manager.get_party.assert_awaited_once_with(str(self.interaction.guild.id), party_id)
        self.interaction.followup.send.assert_awaited_once()
        args, kwargs = self.interaction.followup.send.call_args
        self.assertIsInstance(kwargs.get('embed'), discord.Embed)
        embed = kwargs['embed']
        self.assertEqual(embed.title, "Информация о группе: My Current Crew")
        # Add more assertions for embed fields if needed

    async def test_party_view_target_not_found(self):
        self._reset_party_manager_mocks()
        self.mock_character_manager.get_character.return_value = self.mock_player_character_db
        self.mock_party_manager.get_party.return_value = None # Target party ID not found

        # Mock CharacterManager.get_character_by_name to also return None (no character found by name)
        self.mock_character_manager.get_character_by_name = AsyncMock(return_value=None)

        # Mock PartyManager's cache for name lookup to be empty or not match
        self.mock_party_manager._parties_cache = {str(self.interaction.guild.id): {}}


        target_identifier = "NonExistentParty123"
        await self.cog.cmd_party_view.callback(self.cog, self.interaction, target=target_identifier)

        self.interaction.followup.send.assert_awaited_once_with(
            f"Не удалось найти группу по указателю: '{target_identifier}'.",
            ephemeral=True
        )

if __name__ == '__main__':
    unittest.main()


if __name__ == '__main__':
    unittest.main()
