# bot/command_modules/inventory_cmds.py
import discord
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING
import traceback # For error logging

# Corrected imports
from bot.bot_core import RPGBot
if TYPE_CHECKING:
    # from bot.services.db_service import DBService # No longer directly used by commands
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager # Potentially for context
    from bot.game.models.character import Character as CharacterModel
    from bot.game.models.item import Item # Assuming Item model for item details

# TEST_GUILD_IDS can be removed if not used in decorators
# TEST_GUILD_IDS = []

@app_commands.command(name="inventory", description="View your character's inventory.")
async def cmd_inventory(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    bot: RPGBot = interaction.client

    try:
        if not bot.game_manager or \
           not bot.game_manager.character_manager or \
           not bot.game_manager.item_manager:
            await interaction.followup.send("Error: Core game services (Character or Item Manager) are not fully initialized.", ephemeral=True)
            return

        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        item_manager: 'ItemManager' = bot.game_manager.item_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional[CharacterModel] = await character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        language = character.selected_language or "en"
        char_name_display = character.name_i18n.get(language, character.name_i18n.get('en', 'Your'))

        if not character.inventory: # Assuming inventory is a list on CharacterModel
            await interaction.followup.send("Your inventory is empty.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{char_name_display}'s Inventory",
            color=discord.Color.dark_gold()
        )
        description_lines = []

        # Character.inventory is expected to be List[Dict[str, Any]] e.g. [{'item_id': 'uuid', 'quantity': 1}]
        # Or List[str] if items are not stackable / quantity is always 1.
        # Let's assume List[Dict[str, Any]] as per CharacterManager.add_item_to_inventory hints.

        for item_entry in character.inventory:
            item_id: Optional[str] = None
            quantity: int = 1 # Default quantity

            if isinstance(item_entry, dict):
                item_id = item_entry.get('item_id')
                quantity = item_entry.get('quantity', 1)
            elif isinstance(item_entry, str): # If inventory is just a list of item_ids
                item_id = item_entry

            if not item_id:
                description_lines.append("❓ An unknown item entry (missing ID)")
                continue

            # Fetch item details using ItemManager
            # Assuming item_manager.get_item_details returns an Item model or a dict with item data
            item_details: Optional[Item] = item_manager.get_item_details(item_id, guild_id=guild_id_str) # Pass guild_id if needed by ItemManager

            if item_details:
                item_name_display = item_details.name_i18n.get(language, item_details.name_i18n.get('en', 'Unknown Item'))
                icon = getattr(item_details, 'icon', '📦') # Assuming icon is an attribute on Item model
                description_lines.append(f"{icon} **{item_name_display}** (x{quantity})")
            else:
                description_lines.append(f"📦 An unknown item (ID: {item_id[:6]}...) (x{quantity})")

        if description_lines:
            embed.description = "\n".join(description_lines)
        else:
            embed.description = "Your inventory is empty." # Should have been caught by `if not character.inventory`

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"Error in /inventory command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while fetching your inventory.", ephemeral=True)


@app_commands.command(name="pickup", description="Pick up an item from your current location.")
@app_commands.describe(item_name="The name of the item you want to pick up.")
async def cmd_pickup(interaction: Interaction, item_name: str):
    await interaction.response.defer(ephemeral=True)
    bot: RPGBot = interaction.client

    try:
        if not bot.game_manager or \
           not bot.game_manager.character_manager or \
           not bot.game_manager.item_manager or \
           not bot.game_manager.location_manager: # LocationManager might be needed for context or item finding
            await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
            return

        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        item_manager: 'ItemManager' = bot.game_manager.item_manager
        # location_manager: 'LocationManager' = bot.game_manager.location_manager # Available if needed
        db_service_for_logging = bot.game_manager.db_service # Keep for logging for now

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional[CharacterModel] = await character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        if not character.location_id:
            await interaction.followup.send("Error: Your character doesn't seem to be in any location.", ephemeral=True)
            return

        language = character.selected_language or "en"
        char_name_display = character.name_i18n.get(language, character.name_i18n.get('en', 'Player'))


        # Find item in location using ItemManager
        # Assuming item_manager.get_item_by_name_or_id_in_location is NOT async (common for "get" methods)
        # And it returns an Item model instance or similar dict, which includes item_instance_id
        item_to_pickup = item_manager.get_item_by_name_or_id_in_location(
            name_or_id=item_name,
            location_id=character.location_id,
            guild_id=guild_id_str
        )

        if not item_to_pickup:
            await interaction.followup.send(f"You don't see '{item_name}' here.", ephemeral=True)
            return

        # Assuming item_to_pickup is an object/dict with attributes like:
        # id (item_instance_id), template_id (or item_id), quantity, name_i18n, icon
        item_instance_id = getattr(item_to_pickup, 'id', None)
        item_template_id = getattr(item_to_pickup, 'template_id', None) # Or 'item_id'
        quantity_to_pickup = getattr(item_to_pickup, 'quantity', 1)
        item_name_display = getattr(item_to_pickup, 'name_i18n', {}).get(language, getattr(item_to_pickup, 'name_i18n', {}).get('en',item_name))


        if not item_instance_id or not item_template_id:
            await interaction.followup.send(f"Error: The item '{item_name_display}' is malformed or missing critical data.", ephemeral=True)
            return

        # Process Pickup using ItemManager and CharacterManager
        # Option 1: High-level ItemManager call
        # success = await item_manager.transfer_item_world_to_character_inventory(
        #    item_instance_id=item_instance_id,
        #    character_id=character.id,
        #    guild_id=guild_id_str,
        #    quantity=quantity_to_pickup # if item is stackable and want to pick specific qty
        # )
        # Option 2: Lower-level calls (example, actual methods might differ)

        # Add to character inventory (via CharacterManager or directly on model then save)
        # This might be: await character_manager.add_item_to_inventory(character.id, item_template_id, quantity_to_pickup, guild_id_str)
        # For now, let's assume CharacterManager has a method.
        added_to_inventory = await character_manager.add_item_to_inventory(
            guild_id=guild_id_str,
            character_id=character.id,
            item_id=item_template_id, # This should be the template_id of the item
            quantity=quantity_to_pickup
        )

        if not added_to_inventory:
            await interaction.followup.send(f"Failed to add '{item_name_display}' to your inventory. Your inventory might be full or the item incompatible.", ephemeral=True)
            return

        # Remove from world (via ItemManager)
        # This method should take item_instance_id
        removed_from_world = await item_manager.remove_item_from_world(item_instance_id, guild_id_str)

        if removed_from_world:
            if db_service_for_logging: # Check if logging service is available
                try:
                    log_message = f"{char_name_display} picked up {item_name_display} (x{int(quantity_to_pickup)})."
                    # ... (logging code as before, ensure player_id is character.id) ...
                except Exception as log_e:
                    print(f"Error adding log entry for item pickup: {log_e}")

            await interaction.followup.send(f"{interaction.user.mention} picked up {item_name_display} (x{int(quantity_to_pickup)}).", ephemeral=False)
        else:
            # CRITICAL: Item added to inventory but not removed from world. Attempt to revert.
            print(f"CRITICAL: Item {item_instance_id} added to char {character.id} inventory BUT FAILED to delete from world location {character.location_id}.")
            # Attempt to remove from inventory
            reverted = await character_manager.remove_item_from_inventory(
                guild_id=guild_id_str,
                character_id=character.id,
                item_id=item_template_id,
                quantity=quantity_to_pickup
            )
            if reverted:
                await interaction.followup.send(f"Tried to pick up {item_name_display}, but it couldn't be removed from the location. The action was reverted.", ephemeral=True)
            else:
                await interaction.followup.send(f"ERROR: Picked up {item_name_display}, but it remains in the location AND could not be removed from your inventory. Please contact an admin!", ephemeral=True)
    except Exception as e:
        print(f"Error in /pickup command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to pick up the item.", ephemeral=True)