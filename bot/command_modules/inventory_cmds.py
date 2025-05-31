# bot/command_modules/inventory_cmds.py
import discord
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING
import traceback # For error logging

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.services.db_service import DBService

# Assuming TEST_GUILD_IDS might be populated from bot_core or settings eventually for testing.
TEST_GUILD_IDS = []

@app_commands.command(name="inventory", description="View your character's inventory.")
async def cmd_inventory(interaction: Interaction):
    """Displays the player's current inventory."""
    await interaction.response.defer(ephemeral=True) # Inventory is usually private

    try:
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service'):
            await interaction.followup.send("Error: The game systems are not fully initialized. Please try again later.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service

        if not db_service:
            await interaction.followup.send("Error: Database service is unavailable. Please contact an admin.", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        # 1. Get Player Information
        player_data = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if not player_data:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        player_id = player_data.get('id')
        if not player_id:
            await interaction.followup.send("Error: Could not retrieve your character ID. Please contact an admin.", ephemeral=True)
            return

        # 2. Get Inventory Details
        inventory_items = await db_service.get_player_inventory(player_id=player_id)

        # 3. Display Inventory Information
        if not inventory_items:
            await interaction.followup.send("Your inventory is empty.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{player_data.get('name', 'Your')} 's Inventory",
            color=discord.Color.dark_gold()
        )

        description_lines = []
        for item in inventory_items:
            # item_name = item.get('name', 'Unknown Item')
            # item_template_id = item.get('item_template_id', 'unknown_id')
            # Using name from item_templates join in get_player_inventory
            item_name = item.get('name', item.get('item_template_id', 'Unknown Item'))
            quantity = item.get('amount', 0)
            # icon = item.get('properties', {}).get('icon', '📦') # Assuming icon is in properties
            # For now, DBService.get_player_inventory joins with item_templates and should provide 'name', 'description', 'type', 'properties'
            # The 'icon' would be inside 'properties' if CampaignLoader put it there.
            # Let's assume properties is a dict.
            item_props = item.get('properties', {})
            icon = ""
            if isinstance(item_props, dict): # properties should be a dict after DBService deserializes it
                icon = item_props.get('icon', '📦')

            description_lines.append(f"{icon} **{item_name}** (x{quantity})")
            # For more detail, could add item description as value for a field:
            # embed.add_field(name=f"{icon} {item_name} (x{quantity})", value=item.get('description', 'No description.'), inline=False)

        if description_lines:
            embed.description = "\n".join(description_lines)
        else: # Should be caught by "if not inventory_items" but as a safeguard
            embed.description = "Your inventory is empty."

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"Error in /inventory command: {e}")
        traceback.print_exc()
        # Check if response has been sent, as defer might make is_done() True early
        # Followup is generally safer after defer.
        await interaction.followup.send("An unexpected error occurred while fetching your inventory. Please try again later.", ephemeral=True)

@app_commands.command(name="pickup", description="Pick up an item from your current location.")
@app_commands.describe(item_name="The name of the item you want to pick up.")
async def cmd_pickup(interaction: Interaction, item_name: str):
    """Allows a player to pick up an item from their current location."""
    await interaction.response.defer(ephemeral=True) # Default to ephemeral, can make public on success if desired

    try:
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service'):
            await interaction.followup.send("Error: The game systems are not fully initialized.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service
        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        # 1. Get Player Information
        player_data = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if not player_data:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        player_id = player_data.get('id')
        player_location_id = player_data.get('location_id')

        if not player_id or not player_location_id:
            await interaction.followup.send("Error: Could not retrieve your character or location data.", ephemeral=True)
            return

        # 2. Find Item in Location
        items_in_location = await db_service.get_item_instances_in_location(location_id=player_location_id, guild_id=guild_id)

        found_item_instance = None
        for item_instance in items_in_location:
            # get_item_instances_in_location already joins with item_templates for 'name'
            if item_instance.get('name', '').lower() == item_name.lower():
                found_item_instance = item_instance
                break

        if not found_item_instance:
            await interaction.followup.send(f"You don't see '{item_name}' here.", ephemeral=True)
            return

        item_instance_id = found_item_instance.get('item_instance_id')
        item_template_id = found_item_instance.get('template_id')
        quantity_to_pickup = found_item_instance.get('quantity', 1) # Assuming quantity is on item instance

        if not item_instance_id or not item_template_id:
            await interaction.followup.send(f"Error: The item '{item_name}' is malformed in the database.", ephemeral=True)
            return

        # 3. Process Pickup
        # a. Add to inventory
        await db_service.add_item_to_inventory(
            player_id=player_id,
            item_template_id=item_template_id,
            amount=int(quantity_to_pickup) # Ensure amount is int
        )

        # b. Remove from location
        deleted_from_world = await db_service.delete_item_instance(
            item_instance_id=item_instance_id,
            guild_id=guild_id
        )

        if deleted_from_world:
            # Log the successful pickup
            try:
                log_event_type = "PLAYER_PICKUP_ITEM"
                log_message = f"{player_data.get('name', 'Player')} picked up {found_item_instance.get('name', item_name)} (x{int(quantity_to_pickup)})."
                log_related_entities = {"item_template_id": item_template_id, "item_instance_id": item_instance_id}
                log_context_data = {
                    "player_id": player_id,
                    "item_template_id": item_template_id,
                    "quantity": int(quantity_to_pickup),
                    "original_item_instance_id": item_instance_id,
                    "original_location_id": player_location_id
                }
                await db_service.add_log_entry(
                    guild_id=guild_id,
                    event_type=log_event_type,
                    message=log_message,
                    player_id_column=player_id,
                    related_entities=log_related_entities,
                    context_data=log_context_data,
                    channel_id=interaction.channel_id if interaction.channel else None
                )
                print(f"Log entry added for item pickup: Player {player_id}, Item {item_template_id}, Instance {item_instance_id}")
            except Exception as log_e:
                print(f"Error adding log entry for item pickup: {log_e}")
                # Non-fatal, command already succeeded in game terms.

            # Success, make message public
            await interaction.followup.send(f"{interaction.user.mention} picked up {found_item_instance.get('name', item_name)} (x{int(quantity_to_pickup)}).", ephemeral=False)
        else:
            # Item was added to inventory, but failed to delete from world. This is a problem.
            # Attempt to remove from inventory to revert? (Complex, could also fail)
            # For now, log error and inform user of partial success/problem.
            print(f"CRITICAL: Item {item_instance_id} added to {player_id} inventory BUT FAILED to delete from location {player_location_id}.")
            await interaction.followup.send(f"You picked up {found_item_instance.get('name', item_name)}, but there was an issue removing it from the location. Please contact an admin.", ephemeral=True)

    except Exception as e:
        print(f"Error in /pickup command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to pick up the item.", ephemeral=True)