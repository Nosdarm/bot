# bot/command_modules/inventory_cmds.py
import discord
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING, cast, Dict, Any # Added cast, Dict, Any
import traceback # For error logging

# Corrected imports
if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    # from bot.services.db_service import DBService # No longer directly used by commands
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager # Potentially for context
    from bot.game.models.character import Character as CharacterModel
    # Item model might not be directly used if ItemManager returns dicts
    # from bot.game.models.item import Item

# TEST_GUILD_IDS can be removed if not used in decorators
# TEST_GUILD_IDS = []

@app_commands.command(name="inventory", description="View your character's inventory.")
async def cmd_inventory(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client) # Used cast

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
            item_instance_data = item_manager.get_item_instance(guild_id_str, item_id)
            item_template_data = None
            item_name_display = f"Unknown Item (ID: {item_id[:6]}...)"
            icon = '📦'

            if item_instance_data:
                template_id = item_instance_data.get('template_id')
                if template_id:
                    item_template_data = item_manager.get_item_template(template_id)

            if item_template_data:
                name_i18n = item_template_data.get('name_i18n', {})
                item_name_display = name_i18n.get(language, name_i18n.get('en', item_template_data.get('name', item_name_display)))
                icon = item_template_data.get('icon', icon)

            description_lines.append(f"{icon} **{item_name_display}** (x{quantity})")

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
    bot = cast(RPGBot, interaction.client) # Used cast

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
        items_in_location = item_manager.get_items_in_location(
            guild_id=guild_id_str,
            location_id=character.location_id
        )
        item_to_pickup_data: Optional[Dict[str, Any]] = None
        found_item_template_data: Optional[Dict[str, Any]] = None

        for instance_data_from_loc in items_in_location:
            temp_id = instance_data_from_loc.get('template_id')
            if not temp_id: continue
            template_data_from_loc = item_manager.get_item_template(temp_id)
            if template_data_from_loc:
                name_i18n = template_data_from_loc.get('name_i18n', {})
                # Default to 'name' field if 'en' in name_i18n is missing or name_i18n itself is missing
                name_en = name_i18n.get('en', template_data_from_loc.get('name', '')).lower()
                name_lang = name_i18n.get(language, name_en).lower()

                if item_name.lower() == name_en or item_name.lower() == name_lang:
                    item_to_pickup_data = instance_data_from_loc
                    found_item_template_data = template_data_from_loc
                    break

        if not item_to_pickup_data or not found_item_template_data:
            await interaction.followup.send(f"You don't see '{item_name}' here.", ephemeral=True)
            return

        item_instance_id = item_to_pickup_data.get('id')
        item_template_id = item_to_pickup_data.get('template_id') # This is the actual template_id
        quantity_to_pickup = item_to_pickup_data.get('quantity', 1.0) # ItemManager stores quantity as float

        # Get display name from found_item_template_data
        item_name_display_i18n = found_item_template_data.get('name_i18n', {})
        item_name_display = item_name_display_i18n.get(language, item_name_display_i18n.get('en', item_name))


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
        # remove_item_instance takes guild_id, item_id
        removed_from_world = await item_manager.remove_item_instance(guild_id_str, item_instance_id)

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
