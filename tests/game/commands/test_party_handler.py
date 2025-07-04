import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Optional, List, Dict, Any # Added imports

from bot.game.command_handlers.party_handler import PartyCommandHandler
# Assuming models and managers are importable
from bot.game.models.character import Character 
from bot.game.models.party import Party
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.party_manager import PartyManager

# Helper to create a mock character object
def create_mock_char(char_id: str, name: str, guild_id: str, location_id: Optional[str], party_id: Optional[str]):
    char = MagicMock(spec=Character)
    char.id = char_id
    char.name = name
    char.guild_id = guild_id
    char.location_id = location_id
    char.party_id = party_id
    # Add other attributes if PartyHandler or its callees access them
    return char

# Helper to create a mock party object
def create_mock_party(party_id: str, name: str, guild_id: str, leader_id: str, member_ids: List[str], location_id: Optional[str]):
    party = MagicMock(spec=Party)
    party.id = party_id
    party.name = name
    party.guild_id = guild_id
    party.leader_id = leader_id
    party.player_ids_list = list(member_ids) # Ensure it's a list copy
    party.current_location_id = location_id
    # Add other attributes if PartyHandler or its callees access them
    return party

class TestPartyCommandHandler(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_char_manager = AsyncMock(spec=CharacterManager)
        self.mock_party_manager = AsyncMock(spec=PartyManager)
        self.mock_party_action_processor = AsyncMock() # Not used based on current plan, but part of PartyHandler init
        self.mock_settings = {'command_prefix': '/'}
        
        self.party_handler = PartyCommandHandler(
            character_manager=self.mock_char_manager,
            party_manager=self.mock_party_manager,
            party_action_processor=self.mock_party_action_processor, # Required by constructor
            settings=self.mock_settings
        )
        
        self.mock_send_callback = AsyncMock()
        self.guild_id = "test_guild"
        self.author_id = 123
        self.player_char_id = "player1"
        self.player_location = "loc1"

        self.context = {
            'send_to_command_channel': self.mock_send_callback,
            'guild_id': self.guild_id,
            'author_id': self.author_id,
            # Other context items can be added if necessary
        }

    async def test_handle_party_create_success(self):
        player_char = create_mock_char(self.player_char_id, "PlayerOne", self.guild_id, self.player_location, None)
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char
        
        created_party_id = "party1"
        # create_party in PartyManager should return the Party object
        mock_created_party = create_mock_party(created_party_id, f"Party of {player_char.name}", self.guild_id, self.player_char_id, [self.player_char_id], self.player_location)
        self.mock_party_manager.create_party.return_value = mock_created_party
        self.mock_char_manager.set_party_id.return_value = True

        await self.party_handler.handle(MagicMock(), ["create"], self.context)

        self.mock_party_manager.create_party.assert_called_once_with(
            leader_id=self.player_char_id,
            member_ids=[self.player_char_id],
            guild_id=self.guild_id,
            current_location_id=self.player_location,
            **self.context 
        )
        self.mock_char_manager.set_party_id.assert_called_once_with(
            guild_id=self.guild_id,
            character_id=self.player_char_id,
            party_id=created_party_id,
            **self.context
        )
        self.mock_send_callback.assert_called_with(f"🎉 Вы успешно создали новую партию! ID партии: `{created_party_id}`")

    async def test_handle_party_create_already_in_party(self):
        player_char = create_mock_char(self.player_char_id, "PlayerOne", self.guild_id, self.player_location, "existing_party_id")
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char

        await self.party_handler.handle(MagicMock(), ["create"], self.context)
        self.mock_send_callback.assert_called_with(f"❌ Вы уже состоите в партии (ID `{player_char.party_id}`). Сначала покиньте ее (`{self.mock_settings['command_prefix']}party leave`).")
        self.mock_party_manager.create_party.assert_not_called()

    async def test_handle_party_join_success(self):
        player_char = create_mock_char(self.player_char_id, "PlayerOne", self.guild_id, self.player_location, None)
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char

        target_party_id = "party_to_join"
        target_party = create_mock_party(target_party_id, "Target Party", self.guild_id, "leader2", ["leader2"], self.player_location)
        self.mock_party_manager.get_party.return_value = target_party
        
        # Assume add_member_to_party is the new method in PartyManager
        self.mock_party_manager.add_member_to_party.return_value = True 
        self.mock_char_manager.set_party_id.return_value = True

        await self.party_handler.handle(MagicMock(), ["join", target_party_id], self.context)

        self.mock_party_manager.get_party.assert_called_once_with(self.guild_id, target_party_id)
        self.mock_party_manager.add_member_to_party.assert_called_once_with(
            party_id=target_party_id,
            character_id=self.player_char_id,
            guild_id=self.guild_id,
            context=self.context
        )
        self.mock_char_manager.set_party_id.assert_called_once_with(
            self.guild_id, self.player_char_id, target_party_id, **self.context
        )
        self.mock_send_callback.assert_called_with(f"🎉 Вы успешно присоединились к партии `{target_party.name}`!")

    async def test_handle_party_join_different_location(self):
        player_char = create_mock_char(self.player_char_id, "PlayerOne", self.guild_id, "player_loc_A", None)
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char

        target_party_id = "party_to_join"
        target_party = create_mock_party(target_party_id, "Target Party", self.guild_id, "leader2", ["leader2"], "party_loc_B")
        self.mock_party_manager.get_party.return_value = target_party

        await self.party_handler.handle(MagicMock(), ["join", target_party_id], self.context)
        
        self.mock_send_callback.assert_called_with(f"❌ Вы должны находиться в той же локации, что и партия, чтобы присоединиться. Вы в `player_loc_A`, партия в `party_loc_B`.")
        self.mock_party_manager.add_member_to_party.assert_not_called()


    async def test_handle_party_leave_success(self):
        current_party_id = "party_to_leave"
        player_char = create_mock_char(self.player_char_id, "PlayerOne", self.guild_id, self.player_location, current_party_id)
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char

        party_obj = create_mock_party(current_party_id, "Leaving Party", self.guild_id, "other_leader", [self.player_char_id, "other_leader"], self.player_location)
        self.mock_party_manager.get_party.return_value = party_obj
        
        # Assume remove_member_from_party is the new method
        self.mock_party_manager.remove_member_from_party.return_value = True
        self.mock_char_manager.set_party_id.return_value = True

        await self.party_handler.handle(MagicMock(), ["leave"], self.context)

        self.mock_party_manager.remove_member_from_party.assert_called_once_with(
            party_id=current_party_id,
            character_id=self.player_char_id,
            guild_id=self.guild_id,
            context=self.context
        )
        self.mock_char_manager.set_party_id.assert_called_with( # May be called multiple times if remove_member also calls it
            self.guild_id, self.player_char_id, None, **self.context
        )
        self.mock_send_callback.assert_called_with(f"✅ Вы покинули партию `{party_obj.name}`.")

    async def test_handle_party_leave_leader_migration(self):
        current_party_id = "party_leader_leaves"
        other_member_id = "player2"
        player_char = create_mock_char(self.player_char_id, "LeaderChar", self.guild_id, self.player_location, current_party_id) # This player is the leader
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char
        
        party_obj = create_mock_party(current_party_id, "Leader Leaving Party", self.guild_id, self.player_char_id, [self.player_char_id, other_member_id], self.player_location)
        self.mock_party_manager.get_party.return_value = party_obj
        
        # Mock remove_member_from_party to simulate leader migration
        # It should return True, and PartyManager is responsible for changing leader in party_obj
        async def mock_remove_leader_and_migrate(party_id, character_id, guild_id, context):
            party_obj.player_ids_list.remove(character_id) # Simulate removal
            party_obj.leader_id = party_obj.player_ids_list[0] # Simulate migration
            return True
        self.mock_party_manager.remove_member_from_party.side_effect = mock_remove_leader_and_migrate
        
        await self.party_handler.handle(MagicMock(), ["leave"], self.context)
        
        self.mock_char_manager.set_party_id.assert_called_with(self.guild_id, self.player_char_id, None, **self.context)
        self.mock_send_callback.assert_called_with(f"✅ Вы покинули партию `{party_obj.name}`.")
        # Further assertions could be on PartyManager to ensure leader_id was changed in its internal state if needed

    async def test_handle_party_leave_last_member_disbands(self):
        current_party_id = "party_last_member_leaves"
        player_char = create_mock_char(self.player_char_id, "LastMember", self.guild_id, self.player_location, current_party_id)
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char

        party_obj = create_mock_party(current_party_id, "Last Member Party", self.guild_id, self.player_char_id, [self.player_char_id], self.player_location)
        self.mock_party_manager.get_party.return_value = party_obj

        # remove_member_from_party in PartyManager should detect this and call self.remove_party
        # For this test, we assume remove_member_from_party returns True after initiating disband.
        self.mock_party_manager.remove_member_from_party.return_value = True 
        
        await self.party_handler.handle(MagicMock(), ["leave"], self.context)

        self.mock_party_manager.remove_member_from_party.assert_called_once()
        # PartyManager.remove_party would then call char_manager.set_party_id for all members (which is just this one)
        self.mock_char_manager.set_party_id.assert_called_with(self.guild_id, self.player_char_id, None, **self.context)
        self.mock_send_callback.assert_called_with(f"✅ Вы покинули партию `{party_obj.name}`.")
        # We'd expect PartyManager.remove_party to be called internally by remove_member_from_party
        # This could be tested by adding a mock for party_manager.remove_party if we want to be very thorough here.

    async def test_handle_party_leave_different_location(self):
        current_party_id = "party_loc_leave_test"
        player_char = create_mock_char(self.player_char_id, "PlayerOne", self.guild_id, "player_loc_A", current_party_id)
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char

        party_obj = create_mock_party(current_party_id, "Test Party", self.guild_id, "leader_id", [self.player_char_id], "party_loc_B")
        self.mock_party_manager.get_party.return_value = party_obj

        await self.party_handler.handle(MagicMock(), ["leave"], self.context)
        
        self.mock_send_callback.assert_called_with(f"❌ Вы должны находиться в той же локации, что и партия, чтобы покинуть ее. Вы в `player_loc_A`, партия в `party_loc_B`.")
        self.mock_party_manager.remove_member_from_party.assert_not_called()


    async def test_handle_party_disband_success_by_leader(self):
        current_party_id = "party_to_disband"
        player_char = create_mock_char(self.player_char_id, "PartyLeader", self.guild_id, self.player_location, current_party_id) # This player is the leader
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char

        party_obj = create_mock_party(current_party_id, "Disbanding Party", self.guild_id, self.player_char_id, [self.player_char_id, "member2"], self.player_location)
        self.mock_party_manager.get_party.return_value = party_obj
        
        # remove_party in PartyManager is responsible for clearing party_id for all members
        self.mock_party_manager.remove_party.return_value = True # Assume disband is successful

        await self.party_handler.handle(MagicMock(), ["disband"], self.context)

        self.mock_party_manager.remove_party.assert_called_once_with(
            party_id=current_party_id,
            guild_id=self.guild_id,
            context=self.context
        )
        self.mock_send_callback.assert_called_with(f"✅ Партия `{party_obj.name}` успешно распущена.")

    async def test_handle_party_disband_not_leader(self):
        current_party_id = "party_to_disband"
        actual_leader_id = "actual_leader"
        player_char = create_mock_char(self.player_char_id, "NotTheLeader", self.guild_id, self.player_location, current_party_id)
        self.mock_char_manager.get_character_by_discord_id.return_value = player_char
        
        party_obj = create_mock_party(current_party_id, "Disbanding Party", self.guild_id, actual_leader_id, [self.player_char_id, actual_leader_id], self.player_location)
        self.mock_party_manager.get_party.return_value = party_obj

        await self.party_handler.handle(MagicMock(), ["disband"], self.context)

        self.mock_send_callback.assert_called_with("❌ Только лидер партии может ее распустить.")
        self.mock_party_manager.remove_party.assert_not_called()

if __name__ == '__main__':
    unittest.main()
