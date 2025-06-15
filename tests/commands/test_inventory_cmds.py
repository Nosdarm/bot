import unittest
from unittest.mock import MagicMock, AsyncMock, patch

import discord

# Assuming your inventory commands are in a cog or a module like this:
# Adjust the import path to where your InventoryCommands class or functions are located.
from bot.command_modules.inventory_cmds import InventoryCog

# Models
from bot.game.models.character import Character
from bot.game.models.item import Item # Item instance model
# ItemTemplate is typically a dict, handled by ItemManager

# Managers & RuleEngine
from bot.game.managers.game_manager import GameManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.item_manager import ItemManager
from bot.game.rules.rule_engine import RuleEngine


class TestInventoryCommands(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.bot = MagicMock() # Mock bot instance if your cog needs it

        # Mock GameManager and its sub-managers
        self.mock_game_manager = MagicMock()
        self.mock_character_manager = MagicMock()
        self.mock_item_manager = MagicMock()
        self.mock_rule_engine = MagicMock()

        # Assign mocked managers to the mock_game_manager instance
        self.mock_game_manager.character_manager = self.mock_character_manager
        self.mock_game_manager.item_manager = self.mock_item_manager
        self.mock_game_manager.rule_engine = self.mock_rule_engine

        # Instantiate the cog with mocked dependencies
        self.cog = InventoryCog(bot=self.bot) # Pass only bot, as InventoryCog expects

        # Mock interaction object
        self.interaction = AsyncMock(spec=discord.Interaction)
        self.interaction.user = MagicMock(spec=discord.Member)
        self.interaction.user.id = 12345
        self.interaction.user.name = "TestUser"
        self.interaction.guild = MagicMock(spec=discord.Guild)
        self.interaction.guild.id = 67890
        self.interaction.channel = MagicMock(spec=discord.TextChannel)
        self.interaction.response = AsyncMock(spec=discord.InteractionResponse)

        # Common character mock
        self.mock_player_char = MagicMock()
        self.mock_player_char.id = "char_12345"
        self.mock_player_char.name = "PlayerChar"
        # Mock equipped_items as a dictionary: {slot_name: item_id}
        self.mock_player_char.equipped_items = {}
        # Mock inventory as a list of item IDs or item objects, depending on CharacterManager
        self.mock_player_char.inventory = []

        self.mock_character_manager.get_character = AsyncMock(return_value=self.mock_player_char)

        self._reset_manager_mocks()

    def _reset_manager_mocks(self):
        self.mock_character_manager.get_character = AsyncMock(return_value=self.mock_player_char)
        self.mock_character_manager.equip_item = AsyncMock(return_value=True) # Assume returns bool for success
        self.mock_character_manager.unequip_item = AsyncMock(return_value=MagicMock(id="item_id_unequipped")) # Assume returns unequipped item object/dict

        self.mock_item_manager.get_item_instance_by_name_or_id_for_owner = AsyncMock(return_value=None)
        self.mock_item_manager.get_item_template = AsyncMock(return_value=None)

        self.mock_rule_engine.apply_equipment_effects = AsyncMock()
        self.mock_rule_engine.calculate_effective_stats = AsyncMock(return_value={}) # Return empty stats dict

    async def test_equip_item_successful(self):
        self._reset_manager_mocks()
        item_name_or_id = "sword_of_testing"

        mock_item_instance = MagicMock(id="item_sword_123", template_id="template_sword", name="Sword of Testing")
        self.mock_item_manager.get_item_instance_by_name_or_id_for_owner.return_value = mock_item_instance

        mock_item_template = MagicMock(id="template_sword", name="Sword Template", type="weapon", properties={"slot": "main_hand"})
        self.mock_item_manager.get_item_template.return_value = mock_item_template

        # Assume player's inventory contains the item ID
        self.mock_player_char.inventory = [mock_item_instance.id]
        self.mock_player_char.equipped_items = {} # Ensure slot is empty

        await self.cog.equip.callback(self.cog, self.interaction, item_name=item_name_or_id)

        self.mock_character_manager.get_character.assert_called_once_with(str(self.interaction.guild.id), str(self.interaction.user.id))
        self.mock_item_manager.get_item_instance_by_name_or_id_for_owner.assert_called_once_with(
            str(self.interaction.guild.id), self.mock_player_char.id, item_name_or_id
        )
        self.mock_item_manager.get_item_template.assert_called_once_with(mock_item_instance.template_id)
        self.mock_character_manager.equip_item.assert_called_once_with(
            str(self.interaction.guild.id), self.mock_player_char.id, mock_item_instance.id, "main_hand"
        )
        # RuleEngine might be called inside CharacterManager.equip_item, or directly by command.
        # RuleEngine.apply_equipment_effects is likely called within CharacterManager.equip_item
        # or immediately after by the command if equip_item returns success.
        # If called by CharacterManager, this test might not see it directly unless we inspect CharacterManager's calls.
        # For now, assume it's part of the equip sequence and CharacterManager handles it.
        # If the command itself calls it:
        # self.mock_rule_engine.calculate_effective_stats.assert_called_with(self.mock_player_char)

        self.interaction.response.send_message.assert_called_once_with(f"Equipped {mock_item_instance.name} to main_hand slot.")

    async def test_equip_item_to_armor_slot(self):
        self._reset_manager_mocks()
        item_name_or_id = "leather_jerkin"

        mock_item_instance = MagicMock(id="item_armor_123", template_id="template_armor", name="Leather Jerkin")
        self.mock_item_manager.get_item_instance_by_name_or_id_for_owner.return_value = mock_item_instance

        mock_item_template = MagicMock(id="template_armor", name="Armor Template", type="armor", properties={"slot": "body_armor"})
        self.mock_item_manager.get_item_template.return_value = mock_item_template

        self.mock_player_char.inventory = [mock_item_instance.id]
        self.mock_player_char.equipped_items = {}

        await self.cog.equip.callback(self.cog, self.interaction, item_name=item_name_or_id)

        self.mock_character_manager.equip_item.assert_called_once_with(
            str(self.interaction.guild.id), self.mock_player_char.id, mock_item_instance.id, "body_armor"
        )
        self.interaction.response.send_message.assert_called_once_with(f"Equipped {mock_item_instance.name} to body_armor slot.")


    async def test_equip_item_not_found_in_inventory(self):
        self._reset_manager_mocks()
        item_name_or_id = "ghost_sword"
        self.mock_item_manager.get_item_instance_by_name_or_id_for_owner.return_value = None # Item not found

        await self.cog.equip.callback(self.cog, self.interaction, item_name=item_name_or_id)

        self.mock_character_manager.equip_item.assert_not_called()
        self.interaction.response.send_message.assert_called_once_with(f"Item '{item_name_or_id}' not found in your inventory.", ephemeral=True)

    async def test_equip_item_not_equippable(self):
        self._reset_manager_mocks()
        item_name_or_id = "rock_of_ages"
        mock_item_instance = MagicMock(id="item_rock_123", template_id="template_rock", name="Rock of Ages")
        self.mock_item_manager.get_item_instance_by_name_or_id_for_owner.return_value = mock_item_instance

        mock_item_template = MagicMock(id="template_rock", name="Rock Template", type="misc", properties={}) # No "slot"
        self.mock_item_manager.get_item_template.return_value = mock_item_template
        self.mock_player_char.inventory = [mock_item_instance.id]

        await self.cog.equip.callback(self.cog, self.interaction, item_name=item_name_or_id)

        self.mock_character_manager.equip_item.assert_not_called()
        self.interaction.response.send_message.assert_called_once_with(f"Item '{mock_item_instance.name}' is not equippable.", ephemeral=True)

    async def test_equip_item_slot_occupied(self):
        self._reset_manager_mocks()
        item_name_or_id = "another_sword"
        mock_item_instance = MagicMock(id="item_sword_456", template_id="template_sword_adv", name="Another Sword")
        self.mock_item_manager.get_item_instance_by_name_or_id_for_owner.return_value = mock_item_instance

        mock_item_template = MagicMock(id="template_sword_adv", name="Adv Sword Template", type="weapon", properties={"slot": "main_hand"})
        self.mock_item_manager.get_item_template.return_value = mock_item_template

        self.mock_player_char.inventory = [mock_item_instance.id]
        # Simulate CharacterManager.equip_item returning False because slot is occupied
        self.mock_character_manager.equip_item.return_value = False
        # If CharacterManager.equip_item raises a specific exception for slot occupied:
        # self.mock_character_manager.equip_item.side_effect = SlotOccupiedError("Main hand is full.")


        await self.cog.equip.callback(self.cog, self.interaction, item_name=item_name_or_id)

        self.mock_character_manager.equip_item.assert_called_once() # Attempt to equip is made
        self.interaction.response.send_message.assert_called_once()
        self.assertIn("could not equip", self.interaction.response.send_message.call_args[0][0].lower())
        # Add more specific message check if CharacterManager provides detailed failure reasons that commands use.


    async def test_unequip_item_successful(self):
        self._reset_manager_mocks()
        slot_to_unequip = "main_hand"

        # Mock CharacterManager.unequip_item to return the ID of the unequipped item
        # Or the item object itself if that's what it does
        unequipped_item_mock = MagicMock(id="item_sword_123", name="Sword of Testing")
        self.mock_character_manager.unequip_item.return_value = unequipped_item_mock

        # Player has something equipped in main_hand
        self.mock_player_char.equipped_items = {"main_hand": "item_sword_123"}


        await self.cog.unequip.callback(self.cog, self.interaction, slot=slot_to_unequip)

        self.mock_character_manager.get_character.assert_called_once_with(str(self.interaction.guild.id), str(self.interaction.user.id))
        self.mock_character_manager.unequip_item.assert_called_once_with(
            str(self.interaction.guild.id), self.mock_player_char.id, slot_to_unequip
        )
        # RuleEngine might be called inside CharacterManager.unequip_item, or directly by command.
        # RuleEngine.apply_equipment_effects is likely called within CharacterManager.unequip_item
        # or immediately after by the command.
        # If the command itself calls it:
        # self.mock_rule_engine.calculate_effective_stats.assert_called_with(self.mock_player_char)

        self.interaction.response.send_message.assert_called_once_with(f"Unequipped {unequipped_item_mock.name} from {slot_to_unequip}.")

    async def test_unequip_item_from_armor_slot(self):
        self._reset_manager_mocks()
        slot_to_unequip = "body_armor"

        unequipped_item_mock = MagicMock(id="item_armor_123", name="Leather Jerkin")
        self.mock_character_manager.unequip_item.return_value = unequipped_item_mock
        self.mock_player_char.equipped_items = {"body_armor": "item_armor_123"}

        await self.cog.unequip.callback(self.cog, self.interaction, slot=slot_to_unequip)

        self.mock_character_manager.unequip_item.assert_called_once_with(
            str(self.interaction.guild.id), self.mock_player_char.id, slot_to_unequip
        )
        self.interaction.response.send_message.assert_called_once_with(f"Unequipped {unequipped_item_mock.name} from {slot_to_unequip}.")


    async def test_unequip_item_slot_empty(self):
        self._reset_manager_mocks()
        slot_to_unequip = "off_hand"

        self.mock_character_manager.unequip_item.return_value = None # Slot was empty
        self.mock_player_char.equipped_items = {"main_hand": "item_sword_123"} # off_hand is empty


        await self.cog.unequip.callback(self.cog, self.interaction, slot=slot_to_unequip)

        self.mock_character_manager.unequip_item.assert_called_once()
        self.interaction.response.send_message.assert_called_once_with(f"No item equipped in slot '{slot_to_unequip}'.", ephemeral=True)

    async def test_unequip_item_invalid_slot(self):
        self._reset_manager_mocks()
        invalid_slot_name = "nonexistent_slot"

        # CharacterManager.unequip_item might raise an error for an invalid slot,
        # or return None/False. Let's assume it returns None if slot doesn't exist conceptually.
        self.mock_character_manager.unequip_item.side_effect = ValueError("Invalid slot name") # Or return None
        # If it returns None, the command logic needs to differentiate "empty" from "invalid slot".
        # For this test, let's assume the command itself validates slot names against a predefined list
        # or CharacterManager raises an error that the command catches.
        # If command does validation:
        # We would need to mock the valid slots list/config the command uses.
        # For now, let's assume CharacterManager handles it and the command relays a generic failure.

        # For a more direct test of the command's own validation (if any):
        # with patch.object(self.cog, '_get_valid_slots_for_character_type', return_value=["main_hand", "off_hand", "armor"]):
        #    await self.cog.unequip.callback(self.cog, self.interaction, slot=invalid_slot_name)
        # This depends on how the command gets valid slots.

        # Assuming the command tries to call CharacterManager and it fails:
        await self.cog.unequip.callback(self.cog, self.interaction, slot=invalid_slot_name)

        self.interaction.response.send_message.assert_called_once()
        # The message might vary depending on how the error is handled.
        self.assertIn("invalid slot", self.interaction.response.send_message.call_args[0][0].lower())


if __name__ == '__main__':
    unittest.main()
