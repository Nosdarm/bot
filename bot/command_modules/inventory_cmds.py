import discord
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast, Dict, Any, List
import traceback
import json # Added for potential JSON operations if inventory items are complex

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.models.character import Character as CharacterModel
    from bot.game.rules.rule_engine import RuleEngine

class InventoryCog(commands.Cog, name="Inventory"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="inventory", description="View your character's inventory.")
    async def cmd_inventory(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.bot.game_manager or not self.bot.game_manager.character_manager or not self.bot.game_manager.item_manager:
            await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
            return

        character_manager: "CharacterManager" = self.bot.game_manager.character_manager
        item_manager: "ItemManager" = self.bot.game_manager.item_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = await character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start_new_character`.", ephemeral=True)
            return

        language = character.selected_language or "en"
        char_name_display = character.name_i18n.get(language, character.name_i18n.get('en', character.id)) if hasattr(character, 'name_i18n') and isinstance(character.name_i18n, dict) else getattr(character, 'name', character.id)


        inventory_list_json = getattr(character, 'inventory', "[]")
        inventory_list_data: List[Dict[str, Any]] = []
        if isinstance(inventory_list_json, str):
            try:
                inventory_list_data = json.loads(inventory_list_json)
            except json.JSONDecodeError:
                inventory_list_data = [] # Default to empty if malformed
        elif isinstance(inventory_list_json, list): # Already a list (older format or direct object)
            inventory_list_data = inventory_list_json

        if not inventory_list_data:
            await interaction.followup.send(f"{char_name_display}'s inventory is empty.", ephemeral=True)
            return

        embed = discord.Embed(title=f"{char_name_display}'s Inventory", color=discord.Color.dark_gold())
        description_lines = []

        for item_entry in inventory_list_data:
            item_template_id_from_inv: Optional[str] = None
            quantity: int = 1

            if isinstance(item_entry, dict):
                item_template_id_from_inv = item_entry.get('item_id') or item_entry.get('template_id') # Accommodate both
                quantity = item_entry.get('quantity', 1)
            elif isinstance(item_entry, str):
                item_template_id_from_inv = item_entry

            if not item_template_id_from_inv:
                description_lines.append("❓ An unknown item entry (missing ID in inventory record)")
                continue

            item_template_data = item_manager.get_item_template(guild_id_str, item_template_id_from_inv) # Pass guild_id

            item_name_display = f"Unknown Item (Template ID: {item_template_id_from_inv[:6]}...)"
            icon = '📦'

            if item_template_data: # item_template_data is a dict
                name_i18n = item_template_data.get('name_i18n', {})
                item_name_display = name_i18n.get(language, name_i18n.get('en', item_template_data.get('name', item_name_display)))
                icon = item_template_data.get('icon', icon)

            description_lines.append(f"{icon} **{item_name_display}** (x{quantity})")

        if description_lines:
            embed.description = "\n".join(description_lines)
        else:
            embed.description = f"{char_name_display}'s inventory is empty." # Should be caught by earlier check
        await interaction.followup.send(embed=embed, ephemeral=True)


    @app_commands.command(name="pickup", description="Pick up an item from your current location.")
    @app_commands.describe(item_name="The name of the item you want to pick up.")
    async def cmd_pickup(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        if not self.bot.game_manager or not self.bot.game_manager.character_manager or            not self.bot.game_manager.item_manager or not self.bot.game_manager.location_manager:
            await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
            return

        character_manager: "CharacterManager" = self.bot.game_manager.character_manager
        item_manager: "ItemManager" = self.bot.game_manager.item_manager
        location_manager: "LocationManager" = self.bot.game_manager.location_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start_new_character`.", ephemeral=True)
            return

        current_location_id = getattr(character, 'current_location_id', None) # Correct attribute
        if not current_location_id:
            await interaction.followup.send("Error: Your character is not in a location.", ephemeral=True)
            return

        language = character.selected_language or "en"
        items_in_location = await item_manager.get_items_in_location_async(guild_id_str, current_location_id)

        item_to_pickup_instance_data: Optional[Dict[str, Any]] = None

        for instance_data in items_in_location:
            template_id = instance_data.get('template_id')
            if not template_id: continue
            template_data = item_manager.get_item_template(guild_id_str, template_id) # Pass guild_id
            if template_data:
                name_i18n = template_data.get('name_i18n', {})
                name_en = name_i18n.get('en', template_data.get('name', '')).lower()
                name_lang = name_i18n.get(language, name_en).lower()
                if item_name.lower() == name_en or item_name.lower() == name_lang:
                    item_to_pickup_instance_data = instance_data
                    break

        if not item_to_pickup_instance_data:
            await interaction.followup.send(f"You don't see '{item_name}' here.", ephemeral=True)
            return

        item_instance_id = item_to_pickup_instance_data.get('id')
        item_template_id_for_inv = item_to_pickup_instance_data.get('template_id')
        quantity_to_pickup = float(item_to_pickup_instance_data.get('quantity', 1.0))

        pickup_success = await item_manager.transfer_item_world_to_character(
            guild_id=guild_id_str,
            item_instance_id=item_instance_id, # type: ignore
            character_id=character.id, # type: ignore
            quantity_to_transfer=quantity_to_pickup
        )

        if pickup_success:
            picked_item_template = item_manager.get_item_template(guild_id_str, item_template_id_for_inv) # Pass guild_id
            item_name_display = item_name
            if picked_item_template:
                 item_name_display = picked_item_template.get('name_i18n',{}).get(language, picked_item_template.get('name', item_name))

            await interaction.followup.send(f"{interaction.user.mention} picked up {item_name_display} (x{int(quantity_to_pickup)}).", ephemeral=False)
        else:
            await interaction.followup.send(f"Failed to pick up '{item_name}'. It might have been taken or an error occurred.", ephemeral=True)


    @app_commands.command(name="equip", description="Equip an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to equip.")
    async def cmd_equip(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        if not self.bot.game_manager or not self.bot.game_manager.character_manager or            not self.bot.game_manager.item_manager or not self.bot.game_manager.rule_engine:
            await interaction.followup.send("Error: Core game services not initialized.", ephemeral=True)
            return
        await interaction.followup.send(f"Equip command for '{item_name}' would be handled here. (Refactor placeholder)", ephemeral=True)


    @app_commands.command(name="unequip", description="Unequip an item.")
    @app_commands.describe(slot_or_item_name="The equipment slot or item name to unequip.")
    async def cmd_unequip(self, interaction: Interaction, slot_or_item_name: str):
        await interaction.response.defer(ephemeral=True)
        if not self.bot.game_manager or not self.bot.game_manager.character_manager or            not self.bot.game_manager.item_manager or not self.bot.game_manager.rule_engine:
            await interaction.followup.send("Error: Core game services not initialized.", ephemeral=True)
            return
        await interaction.followup.send(f"Unequip command for '{slot_or_item_name}' would be handled here. (Refactor placeholder)", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InventoryCog(bot)) # type: ignore
    print("InventoryCog loaded.")
