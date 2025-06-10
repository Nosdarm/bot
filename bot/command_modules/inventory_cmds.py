import discord
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast, Dict, Any, List
import traceback
import json # Added for potential JSON operations if inventory items are complex

from bot.utils.i18n_utils import get_i18n_text # Import for localization

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.models.character import Character as CharacterModel
    from bot.game.rules.rule_engine import RuleEngine

DEFAULT_BOT_LANGUAGE = "en"

class InventoryCog(commands.Cog, name="Inventory"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="inventory", description="View your character's inventory.")
    async def cmd_inventory(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        # Determine language early for potential early error messages, though character is needed first.
        # Placeholder language for now, will be refined once character is fetched.
        # This initial language is for the service init error, if it occurs before char fetch.
        # However, the current structure fetches char first, so this is more of a fallback.
        interaction_language = interaction.locale.language if interaction.locale else DEFAULT_BOT_LANGUAGE


        if not self.bot.game_manager or not self.bot.game_manager.character_manager or not self.bot.game_manager.item_manager:
            error_services_not_init = get_i18n_text(None, "inventory_error_services_not_init", interaction_language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Error: Core game services are not fully initialized.")
            await interaction.followup.send(error_services_not_init, ephemeral=True)
            return

        character_manager: "CharacterManager" = self.bot.game_manager.character_manager
        item_manager: "ItemManager" = self.bot.game_manager.item_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )

        # Language for this specific interaction, AFTER character is fetched
        language = DEFAULT_BOT_LANGUAGE # Default if character or selected_language is None
        if character and character.selected_language:
            language = character.selected_language
        elif interaction.locale: # Fallback to interaction locale if character has no preference
            language = interaction.locale.language

        if not character:
            error_no_character = get_i18n_text(None, "inventory_error_no_character", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You need to create a character first! Use `/start_new_character`.")
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        char_name_display = character.name_i18n.get(language, character.name_i18n.get(DEFAULT_BOT_LANGUAGE, character.id)) if hasattr(character, 'name_i18n') and isinstance(character.name_i18n, dict) else getattr(character, 'name', character.id)

        inventory_list_json = getattr(character, 'inventory', "[]")
        inventory_list_data: List[Dict[str, Any]] = []
        if isinstance(inventory_list_json, str):
            try:
                inventory_list_data = json.loads(inventory_list_json)
            except json.JSONDecodeError:
                inventory_list_data = [] # Default to empty if malformed
        elif isinstance(inventory_list_json, list): # Already a list (older format or direct object)
            inventory_list_data = inventory_list_json

        empty_inv_template = get_i18n_text(None, "inventory_empty_message", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="{character_name}'s inventory is empty.")
        if not inventory_list_data:
            await interaction.followup.send(empty_inv_template.format(character_name=char_name_display), ephemeral=True)
            return

        inventory_title_template = get_i18n_text(None, "inventory_title", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="{character_name}'s Inventory")
        embed = discord.Embed(title=inventory_title_template.format(character_name=char_name_display), color=discord.Color.dark_gold())
        description_lines = []

        # Localized strings for item fallbacks
        unknown_item_entry_text = get_i18n_text(None, "inventory_item_unknown_entry", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="❓ An unknown item entry (missing ID in inventory record)")
        unknown_item_label = get_i18n_text(None, "inventory_item_unknown_name", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Unknown Item")
        template_id_label = get_i18n_text(None, "inventory_item_template_id_label", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Template ID")

        for item_entry in inventory_list_data:
            item_template_id_from_inv: Optional[str] = None
            quantity: int = 1

            if isinstance(item_entry, dict):
                item_template_id_from_inv = item_entry.get('item_id') or item_entry.get('template_id') # Accommodate both
                quantity = item_entry.get('quantity', 1)
            elif isinstance(item_entry, str):
                item_template_id_from_inv = item_entry

            if not item_template_id_from_inv:
                description_lines.append(unknown_item_entry_text)
                continue

            item_template_data = item_manager.get_item_template(guild_id_str, item_template_id_from_inv) # Pass guild_id

            item_name_display = f"{unknown_item_label} ({template_id_label}: {item_template_id_from_inv[:6]}...)"
            icon = '📦' # Default icon

            if item_template_data: # item_template_data is a dict
                name_i18n = item_template_data.get('name_i18n', {})
                # Fallback chain for item name: specified lang -> default bot lang (en) -> template's simple name -> original fallback
                item_name_display = name_i18n.get(language, name_i18n.get(DEFAULT_BOT_LANGUAGE, item_template_data.get('name', item_name_display)))
                icon = item_template_data.get('icon', icon) # Use template icon if available

            description_lines.append(f"{icon} **{item_name_display}** (x{quantity})")

        if description_lines:
            embed.description = "\n".join(description_lines)
        else:
            # This case should ideally be caught by the earlier check of `if not inventory_list_data:`
            embed.description = empty_inv_template.format(character_name=char_name_display)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @app_commands.command(name="pickup", description="Pick up an item from your current location.")
    @app_commands.describe(item_name="The name of the item you want to pick up.")
    async def cmd_pickup(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)

        interaction_language_pickup = interaction.locale.language if interaction.locale else DEFAULT_BOT_LANGUAGE

        if not self.bot.game_manager or not self.bot.game_manager.character_manager or            not self.bot.game_manager.item_manager or not self.bot.game_manager.location_manager:
            error_services_not_init_pickup = get_i18n_text(None, "inventory_error_services_not_init", interaction_language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Error: Core game services are not fully initialized.")
            await interaction.followup.send(error_services_not_init_pickup, ephemeral=True)
            return

        character_manager: "CharacterManager" = self.bot.game_manager.character_manager
        item_manager: "ItemManager" = self.bot.game_manager.item_manager
        location_manager: "LocationManager" = self.bot.game_manager.location_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        # Determine language for this interaction
        language_pickup = DEFAULT_BOT_LANGUAGE
        if character and character.selected_language:
            language_pickup = character.selected_language
        elif interaction.locale:
            language_pickup = interaction.locale.language

        if not character:
            error_no_character_pickup = get_i18n_text(None, "inventory_error_no_character", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You need to create a character first! Use `/start_new_character`.")
            await interaction.followup.send(error_no_character_pickup, ephemeral=True)
            return

        current_location_id = getattr(character, 'current_location_id', None) # Correct attribute
        if not current_location_id:
            # TODO: Localize "Error: Your character is not in a location."
            error_char_not_in_location = get_i18n_text(None, "pickup_error_char_not_in_location", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Error: Your character is not in a location.")
            await interaction.followup.send(error_char_not_in_location, ephemeral=True)
            return

        items_in_location = await item_manager.get_items_in_location_async(guild_id_str, current_location_id)

        item_to_pickup_instance_data: Optional[Dict[str, Any]] = None

        for instance_data in items_in_location:
            template_id = instance_data.get('template_id')
            if not template_id: continue
            template_data = item_manager.get_item_template(guild_id_str, template_id) # Pass guild_id
            if template_data:
                name_i18n = template_data.get('name_i18n', {})
                name_default_lang = name_i18n.get(DEFAULT_BOT_LANGUAGE, template_data.get('name', '')).lower()
                name_char_lang = name_i18n.get(language_pickup, name_default_lang).lower()
                if item_name.lower() == name_default_lang or item_name.lower() == name_char_lang:
                    item_to_pickup_instance_data = instance_data
                    break

        if not item_to_pickup_instance_data:
            # TODO: Localize "You don't see '{item_name}' here."
            error_item_not_seen = get_i18n_text(None, "pickup_error_item_not_seen", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You don't see '{item_name}' here.")
            await interaction.followup.send(error_item_not_seen.format(item_name=item_name), ephemeral=True)
            return

        item_instance_id = item_to_pickup_instance_data.get('id')
        item_template_id_for_inv = item_to_pickup_instance_data.get('template_id')
        quantity_to_pickup = float(item_to_pickup_instance_data.get('quantity', 1.0))

        pickup_success = await item_manager.transfer_item_world_to_character(
            guild_id=guild_id_str,
            item_instance_id=item_instance_id,
            character_id=character.id,
            quantity_to_transfer=quantity_to_pickup
        )

        if pickup_success:
            picked_item_template = item_manager.get_item_template(guild_id_str, item_template_id_for_inv) # Pass guild_id
            item_name_display = item_name # Fallback
            if picked_item_template:
                 item_name_display = picked_item_template.get('name_i18n',{}).get(language_pickup, picked_item_template.get('name', item_name))

            # TODO: Localize "{user_mention} picked up {item_name_display} (x{quantity})."
            success_pickup_message = get_i18n_text(None, "pickup_success_message", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="{user_mention} picked up {item_name_display} (x{quantity}).")
            await interaction.followup.send(success_pickup_message.format(user_mention=interaction.user.mention, item_name_display=item_name_display, quantity=int(quantity_to_pickup)), ephemeral=False)
        else:
            # TODO: Localize "Failed to pick up '{item_name}'. It might have been taken or an error occurred."
            error_pickup_failed = get_i18n_text(None, "pickup_error_failed", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Failed to pick up '{item_name}'. It might have been taken or an error occurred.")
            await interaction.followup.send(error_pickup_failed.format(item_name=item_name), ephemeral=True)


    @app_commands.command(name="equip", description="Equip an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to equip.")
    async def cmd_equip(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        # Determine language for this interaction
        language_equip = interaction.locale.language if interaction.locale else DEFAULT_BOT_LANGUAGE
        # TODO: Fetch character to get character.selected_language if preferred over interaction.locale

        if not self.bot.game_manager or not self.bot.game_manager.character_manager or            not self.bot.game_manager.item_manager or not self.bot.game_manager.rule_engine:
            error_services_not_init_equip = get_i18n_text(None, "inventory_error_services_not_init", language_equip, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Error: Core game services not initialized.")
            await interaction.followup.send(error_services_not_init_equip, ephemeral=True)
            return
        # TODO: Localize "Equip command for '{item_name}' would be handled here. (Refactor placeholder)"
        equip_placeholder_text = get_i18n_text(None, "equip_placeholder_message", language_equip, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Equip command for '{item_name}' would be handled here. (Refactor placeholder)")
        await interaction.followup.send(equip_placeholder_text.format(item_name=item_name), ephemeral=True)


    @app_commands.command(name="unequip", description="Unequip an item.")
    @app_commands.describe(slot_or_item_name="The equipment slot or item name to unequip.")
    async def cmd_unequip(self, interaction: Interaction, slot_or_item_name: str):
        await interaction.response.defer(ephemeral=True)
        # Determine language for this interaction
        language_unequip = interaction.locale.language if interaction.locale else DEFAULT_BOT_LANGUAGE
        # TODO: Fetch character to get character.selected_language

        if not self.bot.game_manager or not self.bot.game_manager.character_manager or            not self.bot.game_manager.item_manager or not self.bot.game_manager.rule_engine:
            error_services_not_init_unequip = get_i18n_text(None, "inventory_error_services_not_init", language_unequip, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Error: Core game services not initialized.")
            await interaction.followup.send(error_services_not_init_unequip, ephemeral=True)
            return
        # TODO: Localize "Unequip command for '{slot_or_item_name}' would be handled here. (Refactor placeholder)"
        unequip_placeholder_text = get_i18n_text(None, "unequip_placeholder_message", language_unequip, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Unequip command for '{slot_or_item_name}' would be handled here. (Refactor placeholder)")
        await interaction.followup.send(unequip_placeholder_text.format(slot_or_item_name=slot_or_item_name), ephemeral=True)

    @app_commands.command(name="drop", description="Drop an item from your inventory to the ground.")
    @app_commands.describe(item_name="The name of the item you want to drop.")
    async def cmd_drop(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)

        # Language for initial error messages if character/locale not available yet
        interaction_language_drop = interaction.locale.language if interaction.locale else DEFAULT_BOT_LANGUAGE

        if not self.bot.game_manager or \
           not self.bot.game_manager.character_manager or \
           not self.bot.game_manager.item_manager or \
           not self.bot.game_manager.location_manager:
            error_services_not_init_drop = get_i18n_text(None, "inventory_error_services_not_init", interaction_language_drop, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Error: Core game services are not fully initialized.")
            await interaction.followup.send(error_services_not_init_drop, ephemeral=True)
            return

        character_manager: "CharacterManager" = self.bot.game_manager.character_manager
        item_manager: "ItemManager" = self.bot.game_manager.item_manager
        # location_manager: "LocationManager" = self.bot.game_manager.location_manager # Not directly used for now, but good to have if needed for location checks

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        # Determine language for this interaction
        language = DEFAULT_BOT_LANGUAGE
        if character and character.selected_language:
            language = character.selected_language
        elif interaction.locale:
            language = interaction.locale.language

        if not character:
            error_no_character_drop = get_i18n_text(None, "inventory_error_no_character", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You need to create a character first! Use `/start_new_character`.")
            await interaction.followup.send(error_no_character_drop, ephemeral=True)
            return

        current_location_id = getattr(character, 'current_location_id', None)
        if not current_location_id:
            error_char_not_in_location_drop = get_i18n_text(None, "drop_error_char_not_in_location", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Error: Your character is not in a location to drop items.")
            await interaction.followup.send(error_char_not_in_location_drop, ephemeral=True)
            return

        inventory_list_json = getattr(character, 'inventory', "[]")
        character_inventory_data: List[Dict[str, Any]] = []
        if isinstance(inventory_list_json, str):
            try:
                character_inventory_data = json.loads(inventory_list_json)
            except json.JSONDecodeError:
                character_inventory_data = []
        elif isinstance(inventory_list_json, list):
            character_inventory_data = inventory_list_json

        if not character_inventory_data:
            # This uses the same key as cmd_inventory for empty inventory
            char_name_display_drop = character.name_i18n.get(language, character.name_i18n.get(DEFAULT_BOT_LANGUAGE, character.id)) if hasattr(character, 'name_i18n') and isinstance(character.name_i18n, dict) else getattr(character, 'name', character.id)
            empty_inv_template_drop = get_i18n_text(None, "inventory_empty_message", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="{character_name}'s inventory is empty.")
            await interaction.followup.send(empty_inv_template_drop.format(character_name=char_name_display_drop), ephemeral=True)
            return

        item_template_id_to_drop: Optional[str] = None
        # item_instance_id_to_drop: Optional[str] = None # If inventory tracks instance IDs
        # quantity_in_inventory: int = 0 # Not strictly needed if always dropping 1

        for item_entry in character_inventory_data:
            current_item_template_id: Optional[str] = None
            if isinstance(item_entry, dict):
                current_item_template_id = item_entry.get('item_id') or item_entry.get('template_id')
            elif isinstance(item_entry, str): # Older format, just template_id string
                current_item_template_id = item_entry

            if not current_item_template_id:
                continue

            item_template_data = item_manager.get_item_template(guild_id_str, current_item_template_id)
            if item_template_data:
                name_i18n = item_template_data.get('name_i18n', {})
                name_default_lang = name_i18n.get(DEFAULT_BOT_LANGUAGE, item_template_data.get('name', '')).lower()
                name_char_lang = name_i18n.get(language, name_default_lang).lower()

                if item_name.lower() == name_default_lang or item_name.lower() == name_char_lang:
                    item_template_id_to_drop = current_item_template_id
                    # quantity_in_inventory = item_entry.get('quantity', 1) if isinstance(item_entry, dict) else 1
                    # If inventory tracks instance IDs, capture here:
                    # item_instance_id_to_drop = item_entry.get('instance_id')
                    break

        if not item_template_id_to_drop:
            error_item_not_in_inventory = get_i18n_text(None, "drop_error_item_not_found", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You don't have '{item_name}' in your inventory.")
            await interaction.followup.send(error_item_not_in_inventory.format(item_name=item_name), ephemeral=True)
            return

        quantity_to_drop = 1 # For now, always drop 1

        # 1. Remove item from character's inventory
        # CharacterManager.remove_item_from_inventory(guild_id, character_id, item_template_id, quantity)
        # This method needs to exist and correctly handle quantity update or item removal from list.
        # Let's assume it returns True on success, False on failure (e.g. item not found after all, or quantity issue)
        # The remove_item_from_inventory in DBService did not return boolean, but adapter.execute might give info.
        # For simplicity, let's assume CharacterManager's version will update the character object and mark it dirty.
        # A more robust way would be for CharacterManager to return success/failure.
        # For now, we'll assume it succeeds if no exception.

        # The CharacterManager might need a method that takes character object and updates it,
        # or CharacterModel itself has methods to manage inventory and then CM saves it.
        # Let's assume CharacterManager has a high-level remove that fetches, updates, and saves.
        # Or, as planned, `character_manager.remove_item_from_inventory` in `db_service` which works by IDs.

        # We need the CharacterManager's remove method that operates on the character object or its ID
        # and handles the list manipulation for `character.inventory`.
        # The one in DBService is low-level. A CharacterManager method would be:
        # `character_manager.update_inventory_remove_item(character, item_template_id_to_drop, quantity_to_drop)`
        # This is not yet defined.

        # Alternative: Modify character inventory directly and save
        # This is generally not good practice if CharacterManager is meant to abstract state changes.
        # However, if CharacterManager's role is just CRUD and caching, direct mod might be expected.
        # The `remove_item_from_inventory` in `db_service.py` is for the 'inventory' table, not 'players.inventory' JSON list.
        # So, we need to manipulate `character.inventory` list directly or add a new CM method.

        # Let's proceed with direct manipulation for now, assuming CharacterManager will save the updated character object.
        # This is a simplification for this subtask.

        original_inventory = list(character_inventory_data) # Make a copy
        updated_inventory = []
        item_removed_from_list = False
        for item_entry in original_inventory:
            current_item_template_id = item_entry.get('item_id') or item_entry.get('template_id')
            if current_item_template_id == item_template_id_to_drop and not item_removed_from_list:
                current_quantity = item_entry.get('quantity', 1)
                if current_quantity > quantity_to_drop:
                    updated_inventory.append({**item_entry, 'quantity': current_quantity - quantity_to_drop})
                    item_removed_from_list = True
                elif current_quantity == quantity_to_drop:
                    item_removed_from_list = True # Item entry removed
                else: # Not enough quantity (should not happen if we only drop 1 and item was found)
                    updated_inventory.append(item_entry)
            else:
                updated_inventory.append(item_entry)

        if not item_removed_from_list: # Should not happen if item was matched
            error_generic_drop_fail = get_i18n_text(None, "drop_error_generic_fail", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Failed to drop '{item_name}'. An unexpected error occurred with your inventory.")
            await interaction.followup.send(error_generic_drop_fail.format(item_name=item_name), ephemeral=True)
            return

        character.inventory = json.dumps(updated_inventory) # Update character object
        character_manager.mark_dirty(character.id, guild_id_str) # Mark for saving
        # Consider if character_manager.save_character(character) should be explicit here or handled by a game loop tick.
        # For immediate effect, an explicit save or update call might be needed.
        # Let's assume mark_dirty is sufficient for now or a save method is called by CM internally.
        # A direct call like: `await character_manager.save_character_inventory(character.id, guild_id_str, updated_inventory)` might be cleaner.
        # For now, relying on existing CM structure.

        # 2. Create item instance in the world at the character's location
        # `item_manager.create_item_instance` returns Optional[str] (instance_id) or None on failure
        new_item_instance_id_in_world = await item_manager.create_item_instance(
            template_id=item_template_id_to_drop,
            guild_id=guild_id_str,
            quantity=quantity_to_drop,
            location_id=current_location_id
        )

        if new_item_instance_id_in_world:
            # Fetch item name for display
            dropped_item_template_data = item_manager.get_item_template(guild_id_str, item_template_id_to_drop)
            item_name_display = item_name # Fallback
            if dropped_item_template_data:
                item_name_display = dropped_item_template_data.get('name_i18n', {}).get(language, dropped_item_template_data.get('name', item_name))

            success_drop_message_template = get_i18n_text(None, "drop_success_message", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="{user_mention} dropped {item_name_display} (x{quantity}).")
            await interaction.followup.send(success_drop_message_template.format(user_mention=interaction.user.mention, item_name_display=item_name_display, quantity=quantity_to_drop), ephemeral=False) # Public message
        else:
            # Rollback inventory change? This is complex.
            # For now, log error and inform user of partial failure.
            # This indicates item removed from inventory but failed to appear on ground.
            # TODO: Implement rollback or a more transactional approach in ItemManager/CharacterManager.
            character.inventory = json.dumps(original_inventory) # Attempt to restore inventory
            character_manager.mark_dirty(character.id, guild_id_str)

            error_drop_fail_world = get_i18n_text(None, "drop_error_fail_world_spawn", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You removed '{item_name}' from your inventory, but it failed to appear on the ground. Your inventory has been restored. Please try again.")
            await interaction.followup.send(error_drop_fail_world.format(item_name=item_name), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InventoryCog(bot)) # type: ignore
    print("InventoryCog loaded.")
