# bot/command_modules/inventory_cmds.py
import discord
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING, cast, Dict, Any # Added cast, Dict, Any
import traceback # For error logging

# Corrected imports
from bot.bot_core import RPGBot
if TYPE_CHECKING:
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


@app_commands.command(name="equip", description="Equip an item from your inventory.")
@app_commands.describe(item_name="The name of the item you want to equip.")
async def cmd_equip(interaction: Interaction, item_name: str):
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client)

    if not bot.game_manager or \
       not bot.game_manager.character_manager or \
       not bot.game_manager.item_manager or \
       not bot.game_manager.rule_engine:
        await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
        return

    char_manager: "CharacterManager" = bot.game_manager.character_manager
    item_manager: "ItemManager" = bot.game_manager.item_manager
    rule_engine: "RuleEngine" = bot.game_manager.rule_engine
    guild_id_str = str(interaction.guild_id)
    discord_user_id_int = interaction.user.id

    try:
        character: Optional[CharacterModel] = await char_manager.get_character_by_discord_id(
            guild_id=guild_id_str, discord_user_id=discord_user_id_int
        )
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        language = character.selected_language or "en"

        # 1. Find the item instance ID in inventory based on name
        item_to_equip_instance_id: Optional[str] = None
        item_to_equip_template_id: Optional[str] = None
        item_to_equip_template_data: Optional[Dict[str, Any]] = None

        # Ensure character.inventory is a list (it should be List[Dict[str, Any]])
        if not isinstance(character.inventory, list):
            character.inventory = [] # Should not happen if initialized correctly

        for item_entry in character.inventory:
            entry_item_id: Optional[str] = None
            if isinstance(item_entry, dict): # Expected structure {'item_id': template_id, 'quantity': x}
                entry_item_id = item_entry.get('item_id')
            elif isinstance(item_entry, str): # Fallback if inventory stores only template_ids
                entry_item_id = item_entry

            if not entry_item_id: continue

            # Assuming entry_item_id is template_id as per pickup logic's current state
            current_item_template_id = entry_item_id
            template_data = item_manager.get_item_template(current_item_template_id)
            if template_data:
                name_i18n = template_data.get('name_i18n', {})
                name_en = name_i18n.get('en', template_data.get('name', '')).lower()
                name_lang = name_i18n.get(language, name_en).lower()
                if item_name.lower() == name_en or item_name.lower() == name_lang:
                    # For equipping, we need an *instance ID*.
                    # This part is tricky because inventory stores template_ids.
                    # We'll assume for now that the first found match of a template is what we equip.
                    # A proper system would need unique instance IDs in inventory.
                    # For this implementation, we'll use the template_id as if it's the instance_id for equip purposes.
                    item_to_equip_instance_id = current_item_template_id # This is actually template_id
                    item_to_equip_template_id = current_item_template_id
                    item_to_equip_template_data = template_data
                    break

        if not item_to_equip_instance_id or not item_to_equip_template_data:
            await interaction.followup.send(f"You don't have '{item_name}' in your inventory.", ephemeral=True)
            return

        # 2. Determine item's equipment slot(s)
        item_properties = item_to_equip_template_data.get('properties', {})
        if not isinstance(item_properties, dict): item_properties = {}

        slot = item_properties.get('slot') # e.g., "weapon", "armor_chest", "ring"
        if not slot or not isinstance(slot, str): # slot can also be a list for two-handed, etc.
            if isinstance(slot, list) and slot: # Takes multiple slots
                # For simplicity, we'll use the first slot in the list as the primary slot
                # and assume CharacterModel.equipped_items can handle list of slots or composite slots
                pass # slot is already a list
            else:
                await interaction.followup.send(f"The item '{item_name}' is not equippable (no slot defined).", ephemeral=True)
                return

        # 3. Update character's equipped items
        # Assume character.equipped_items is Dict[str, Optional[str]] -> slot_name: item_instance_id
        if not hasattr(character, 'equipped_items') or not isinstance(character.equipped_items, dict):
            character.equipped_items = {} # Initialize if not present

        # Unequip item currently in the target slot(s)
        unequipped_items_feedback = []
        slots_to_occupy = [slot] if isinstance(slot, str) else slot # slot can be a list e.g. ["main_hand", "off_hand"]

        for s in slots_to_occupy:
            if character.equipped_items.get(s):
                previously_equipped_item_id = character.equipped_items[s]
                # No need to add back to inventory, as it was never removed for equip.
                # Just update effects.
                prev_item_template = item_manager.get_item_template(previously_equipped_item_id) # Assuming ID is template ID
                if prev_item_template:
                    await rule_engine.apply_equipment_effects(character, prev_item_template, equipping=False, guild_id=guild_id_str)
                    prev_item_name_i18n = prev_item_template.get('name_i18n', {})
                    prev_item_name = prev_item_name_i18n.get(language, prev_item_name_i18n.get('en', "Unknown Item"))
                    unequipped_items_feedback.append(prev_item_name)
                character.equipped_items[s] = None # Clear the slot

        # Equip the new item
        for s in slots_to_occupy:
            character.equipped_items[s] = item_to_equip_instance_id # Store template_id as instance_id due to inventory structure

        # 4. Trigger recalculation of Effective_Stats
        await rule_engine.apply_equipment_effects(character, item_to_equip_template_data, equipping=True, guild_id=guild_id_str)

        char_manager.mark_character_dirty(guild_id_str, character.id)
        await char_manager.save_character(character, guild_id_str)

        # 5. User Feedback
        equipped_item_name_display = item_to_equip_template_data.get('name_i18n', {}).get(language, item_name)
        feedback_message = f"You equipped **{equipped_item_name_display}**."
        if unequipped_items_feedback:
            feedback_message += f"\n(Unequipped: {', '.join(unequipped_items_feedback)})"

        await interaction.followup.send(feedback_message, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"An error occurred while equipping the item: {e}", ephemeral=True)
        traceback.print_exc()

@app_commands.command(name="unequip", description="Unequip an item.")
@app_commands.describe(slot_or_item_name="The equipment slot (e.g., 'weapon', 'head') or item name to unequip.")
async def cmd_unequip(interaction: Interaction, slot_or_item_name: str):
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client)

    if not bot.game_manager or \
       not bot.game_manager.character_manager or \
       not bot.game_manager.item_manager or \
       not bot.game_manager.rule_engine:
        await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
        return

    char_manager: "CharacterManager" = bot.game_manager.character_manager
    item_manager: "ItemManager" = bot.game_manager.item_manager
    rule_engine: "RuleEngine" = bot.game_manager.rule_engine
    guild_id_str = str(interaction.guild_id)
    discord_user_id_int = interaction.user.id

    try:
        character: Optional[CharacterModel] = await char_manager.get_character_by_discord_id(
            guild_id=guild_id_str, discord_user_id=discord_user_id_int
        )
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        language = character.selected_language or "en"

        if not hasattr(character, 'equipped_items') or not isinstance(character.equipped_items, dict) or not character.equipped_items:
            character.equipped_items = {} # Initialize if not present
            await interaction.followup.send("You have nothing equipped.", ephemeral=True)
            return

        item_to_unequip_instance_id: Optional[str] = None
        slot_to_clear: Optional[str] = None # The actual slot key to clear

        # Try to match slot_or_item_name as a slot first
        normalized_input = slot_or_item_name.lower()
        possible_slots = list(character.equipped_items.keys()) # TODO: Get valid slots from game rules/config instead

        for s_key in possible_slots:
            if normalized_input == s_key.lower(): # Matched a slot name directly
                item_to_unequip_instance_id = character.equipped_items.get(s_key)
                slot_to_clear = s_key
                break

        # If not matched as a slot, try to match as an item name among equipped items
        if not item_to_unequip_instance_id:
            for s_key, equipped_item_id in character.equipped_items.items():
                if not equipped_item_id: continue # Slot is empty
                # Assuming equipped_item_id is a template_id due to inventory structure
                template_data = item_manager.get_item_template(equipped_item_id)
                if template_data:
                    name_i18n = template_data.get('name_i18n', {})
                    name_en = name_i18n.get('en', template_data.get('name', '')).lower()
                    name_lang = name_i18n.get(language, name_en).lower()
                    if normalized_input == name_en or normalized_input == name_lang:
                        item_to_unequip_instance_id = equipped_item_id
                        slot_to_clear = s_key
                        break

        if not item_to_unequip_instance_id or not slot_to_clear:
            await interaction.followup.send(f"Couldn't find '{slot_or_item_name}' equipped or as a valid slot with an item.", ephemeral=True)
            return

        item_template_data = item_manager.get_item_template(item_to_unequip_instance_id)
        if not item_template_data:
             # This case implies inconsistent data, as an equipped item should have a valid template
            await interaction.followup.send(f"Error: The equipped item data for '{slot_or_item_name}' is corrupted. Removing from slot.", ephemeral=True)
            character.equipped_items[slot_to_clear] = None
            # No stat recalculation here as we don't know what its effects were.
        else:
            # Apply un-equip effects
            await rule_engine.apply_equipment_effects(character, item_template_data, equipping=False, guild_id=guild_id_str)
            character.equipped_items[slot_to_clear] = None # Clear the slot

            # If item takes multiple slots (e.g. two-handed), clear all its slots
            item_slots_property = item_template_data.get('properties', {}).get('slot')
            if isinstance(item_slots_property, list):
                for s_prop in item_slots_property:
                    if s_prop in character.equipped_items and character.equipped_items[s_prop] == item_to_unequip_instance_id:
                        character.equipped_items[s_prop] = None


        char_manager.mark_character_dirty(guild_id_str, character.id)
        await char_manager.save_character(character, guild_id_str)

        unequipped_item_name_display = "the item"
        if item_template_data:
            unequipped_item_name_display = item_template_data.get('name_i18n', {}).get(language, item_template_data.get('name', "The item"))

        await interaction.followup.send(f"You unequipped **{unequipped_item_name_display}** from slot '{slot_to_clear}'.", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"An error occurred while unequipping: {e}", ephemeral=True)
        traceback.print_exc()
