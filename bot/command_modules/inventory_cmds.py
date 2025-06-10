import discord
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast, Dict, Any, List
import traceback
import json # Added for potential JSON operations if inventory items are complex

from bot.utils.i18n_utils import get_i18n_text # Import for localization
# For NLU integration
from bot.services.nlu_data_service import NLUDataService
from bot.nlu.player_action_parser import parse_player_action
from bot.ai.rules_schema import CoreGameRulesConfig

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
        # NLU Services
        nlu_data_service: "NLUDataService" = self.bot.nlu_data_service
        # player_action_parser is a function, not a class instance on bot usually
        # So we call it directly: from bot.nlu.player_action_parser import parse_player_action

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
        nlu_identified_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name # Fallback to original input

        # 1. NLU Processing
        if not nlu_data_service:
            # This should ideally not happen if bot initializes services correctly
            await interaction.followup.send("Error: NLU service is not available.", ephemeral=True)
            return

        action_data = await parse_player_action(
            text=item_name,
            language=language_pickup,
            guild_id=guild_id_str,
            nlu_data_service=nlu_data_service
            # game_log_manager can be passed if needed: self.bot.game_log_manager
        )

        if action_data and action_data['intent'] and action_data['entities']:
            # For pickup, we expect an item entity.
            # The intent might be generic like "interact" or more specific.
            # For now, let's prioritize item entities if intent is somewhat related or ambiguous.
            # A more robust system might check if intent is "pickup" or similar.
            for entity in action_data['entities']:
                if entity['type'] == 'item':
                    nlu_identified_template_id = entity['id']
                    nlu_item_name_in_text = entity['name'] # Name as recognized in text by NLU
                    break

        if not nlu_identified_template_id:
            # NLU didn't clearly identify a known item, or the intent was not about an item.
            # Fallback to trying to match the raw item_name string if desired, or send "not understood".
            # For this refactor, we'll prioritize NLU. If NLU fails, we say item not found/understood.
            error_item_not_understood = get_i18n_text(None, "pickup_error_item_not_understood", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="I'm not sure what item ('{item_name}') you mean.")
            await interaction.followup.send(error_item_not_understood.format(item_name=item_name), ephemeral=True)
            return

        # 2. Find the item instance in the location matching the NLU-identified template_id
        for instance_data in items_in_location:
            if instance_data.get('template_id') == nlu_identified_template_id:
                item_to_pickup_instance_data = instance_data
                break # Pick the first matching instance

        if not item_to_pickup_instance_data:
            error_item_not_seen_here = get_i18n_text(None, "pickup_error_item_not_seen_here_nlu", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You identified '{item_name_nlu}', but it doesn't seem to be here.")
            await interaction.followup.send(error_item_not_seen_here.format(item_name_nlu=nlu_item_name_in_text), ephemeral=True)
            return

        # 3. Proceed with pickup logic using item_to_pickup_instance_data
        item_instance_id = item_to_pickup_instance_data.get('id')
        # nlu_identified_template_id is already the template_id for inventory
        quantity_to_pickup = float(item_to_pickup_instance_data.get('quantity', 1.0))

        pickup_success = await item_manager.transfer_item_world_to_character(
            guild_id=guild_id_str,
            item_instance_id=item_instance_id, # This is the ID of the item *instance* on the ground
            character_id=character.id,
            quantity_to_transfer=quantity_to_pickup
        )

        if pickup_success:
            # Use nlu_item_name_in_text or fetch template name again for confirmation message
            # nlu_item_name_in_text is good as it's what the player said/NLU confirmed.
            success_pickup_message = get_i18n_text(None, "pickup_success_message", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="{user_mention} picked up {item_name_display} (x{quantity}).")
            await interaction.followup.send(success_pickup_message.format(user_mention=interaction.user.mention, item_name_display=nlu_item_name_in_text, quantity=int(quantity_to_pickup)), ephemeral=False)
        else:
            error_pickup_failed = get_i18n_text(None, "pickup_error_failed", language_pickup, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Failed to pick up '{item_name}'. It might have been taken or an error occurred.")
            await interaction.followup.send(error_pickup_failed.format(item_name=nlu_item_name_in_text), ephemeral=True)


    @app_commands.command(name="equip", description="Equip an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to equip.", slot_preference="Optional: preferred slot (e.g., 'main_hand', 'off_hand')")
    async def cmd_equip(self, interaction: Interaction, item_name: str, slot_preference: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        # Assume services are initialized. Error checking can be added if necessary.
        character_manager: "CharacterManager" = self.bot.game_manager.character_manager
        item_manager: "ItemManager" = self.bot.game_manager.item_manager
        nlu_data_service: "NLUDataService" = self.bot.nlu_data_service
        # Assuming CoreGameRulesConfig is accessible via rule_engine
        if not self.bot.game_manager.rule_engine or not self.bot.game_manager.rule_engine.rules_config_data:
            await interaction.followup.send("Error: Game rules not loaded.", ephemeral=True)
            return
        rules_config: CoreGameRulesConfig = self.bot.game_manager.rule_engine.rules_config_data


        character = character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
        language = character.selected_language if character and character.selected_language else (interaction.locale.language if interaction.locale else DEFAULT_BOT_LANGUAGE)

        if not character:
            error_no_character = get_i18n_text(None, "inventory_error_no_character", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You need to create a character first! Use `/start_new_character`.")
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        action_data = await parse_player_action(
            text=item_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
        )

        nlu_identified_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name

        if action_data and action_data['entities']:
            for entity in action_data['entities']:
                if entity['type'] == 'item':
                    nlu_identified_template_id = entity['id']
                    nlu_item_name_in_text = entity['name']
                    break

        if not nlu_identified_template_id:
            msg_not_understood = get_i18n_text(None, "equip_error_item_not_understood", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="I'm not sure which item ('{item_name}') you want to equip.")
            await interaction.followup.send(msg_not_understood.format(item_name=item_name), ephemeral=True)
            return

        equip_result = await item_manager.equip_item(
            character_id=character.id,
            guild_id=guild_id_str,
            item_template_id_to_equip=nlu_identified_template_id,
            rules_config=rules_config,
            slot_id_preference=slot_preference
        )

        response_message = equip_result['message'] # Use message from item_manager
        # Potentially localize manager messages if they are keys, or ensure manager produces localized text.
        # For now, assuming manager messages are user-facing.
        await interaction.followup.send(response_message, ephemeral=not equip_result['success'])


    @app_commands.command(name="unequip", description="Unequip an item.")
    @app_commands.describe(slot_or_item_name="The equipment slot (e.g. 'main_hand') or item name to unequip.")
    async def cmd_unequip(self, interaction: Interaction, slot_or_item_name: str):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        character_manager: "CharacterManager" = self.bot.game_manager.character_manager
        item_manager: "ItemManager" = self.bot.game_manager.item_manager
        nlu_data_service: "NLUDataService" = self.bot.nlu_data_service
        if not self.bot.game_manager.rule_engine or not self.bot.game_manager.rule_engine.rules_config_data:
            await interaction.followup.send("Error: Game rules not loaded.", ephemeral=True)
            return
        rules_config: CoreGameRulesConfig = self.bot.game_manager.rule_engine.rules_config_data

        character = character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
        language = character.selected_language if character and character.selected_language else (interaction.locale.language if interaction.locale else DEFAULT_BOT_LANGUAGE)

        if not character:
            error_no_character = get_i18n_text(None, "inventory_error_no_character", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You need to create a character first! Use `/start_new_character`.")
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        slot_to_unequip_directly: Optional[str] = None
        item_template_id_from_nlu: Optional[str] = None

        # Check if slot_or_item_name is a direct slot_id
        normalized_input = slot_or_item_name.lower().replace(" ", "_")
        if normalized_input in rules_config.equipment_slots:
            slot_to_unequip_directly = normalized_input
        else:
            # Try NLU for item name
            action_data = await parse_player_action(
                text=slot_or_item_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
            )
            if action_data and action_data['entities']:
                for entity in action_data['entities']:
                    if entity['type'] == 'item':
                        item_template_id_from_nlu = entity['id']
                        break
            if not item_template_id_from_nlu:
                msg_not_understood = get_i18n_text(None, "unequip_error_not_understood", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Could not identify '{name}' as an item or an equipment slot.")
                await interaction.followup.send(msg_not_understood.format(name=slot_or_item_name), ephemeral=True)
                return

        unequip_result = await item_manager.unequip_item(
            character_id=character.id,
            guild_id=guild_id_str,
            rules_config=rules_config,
            item_template_id_to_unequip=item_template_id_from_nlu,
            slot_id_to_unequip=slot_to_unequip_directly
        )

        response_message = unequip_result['message']
        await interaction.followup.send(response_message, ephemeral=not unequip_result['success'])

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
        nlu_data_service: "NLUDataService" = self.bot.nlu_data_service
        # location_manager: "LocationManager" = self.bot.game_manager.location_manager

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

        nlu_identified_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name # Fallback

        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service is not available for drop command.", ephemeral=True)
            return

        action_data = await parse_player_action(
            text=item_name,
            language=language,
            guild_id=guild_id_str,
            nlu_data_service=nlu_data_service
        )

        if action_data and action_data['entities']:
            for entity in action_data['entities']:
                if entity['type'] == 'item':
                    nlu_identified_template_id = entity['id']
                    nlu_item_name_in_text = entity['name']
                    break

        if not nlu_identified_template_id:
            error_item_not_understood_drop = get_i18n_text(None, "drop_error_item_not_understood", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="I'm not sure which item ('{item_name}') you want to drop from your inventory.")
            await interaction.followup.send(error_item_not_understood_drop.format(item_name=item_name), ephemeral=True)
            return

        # Check if the NLU-identified item is in the character's inventory
        item_entry_to_drop: Optional[Dict[str, Any]] = None
        for entry in character_inventory_data:
            current_template_id = entry.get('item_id') or entry.get('template_id')
            if current_template_id == nlu_identified_template_id:
                item_entry_to_drop = entry
                break

        if not item_entry_to_drop:
            error_item_not_in_inventory = get_i18n_text(None, "drop_error_item_not_found_nlu", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You don't have '{item_name_nlu}' in your inventory.")
            await interaction.followup.send(error_item_not_in_inventory.format(item_name_nlu=nlu_item_name_in_text), ephemeral=True)
            return

        item_template_id_to_drop = nlu_identified_template_id # Confirmed item template ID
        quantity_to_drop = 1 # For now, always drop 1

        # 1. Remove item from character's inventory (using direct list manipulation for now)
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
        # For now, relying on existing CM structure and direct character object modification.

        # 2. Create item instance in the world at the character's location
        new_item_instance_id_in_world = await item_manager.create_item_instance(
            template_id=item_template_id_to_drop, # This is the NLU identified template_id
            guild_id=guild_id_str,
            quantity=quantity_to_drop,
            location_id=current_location_id
        )

        if new_item_instance_id_in_world:
            success_drop_message_template = get_i18n_text(None, "drop_success_message", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="{user_mention} dropped {item_name_display} (x{quantity}).")
            # Use nlu_item_name_in_text for consistency with what player typed and NLU confirmed
            await interaction.followup.send(success_drop_message_template.format(user_mention=interaction.user.mention, item_name_display=nlu_item_name_in_text, quantity=quantity_to_drop), ephemeral=False)
        else:
            # Rollback inventory change
            character.inventory = json.dumps(original_inventory)
            character_manager.mark_dirty(character.id, guild_id_str)
            # No need to save character explicitly if mark_dirty handles it via a game loop or CharacterManager persistence strategy.

            error_drop_fail_world = get_i18n_text(None, "drop_error_fail_world_spawn", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You removed '{item_name}' from your inventory, but it failed to appear on the ground. Your inventory has been restored. Please try again.")
            await interaction.followup.send(error_drop_fail_world.format(item_name=nlu_item_name_in_text), ephemeral=True)

    @app_commands.command(name="use", description="Use an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to use.", target_name="Optional: the name of the target (e.g., another character).")
    async def cmd_use_item(self, interaction: Interaction, item_name: str, target_name: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        # --- Service and Data Initialization ---
        if not self.bot.game_manager or \
           not self.bot.game_manager.character_manager or \
           not self.bot.game_manager.item_manager or \
           not self.bot.game_manager.rule_engine or \
           not self.bot.nlu_data_service:
            # Simplified error message for brevity
            await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
            return

        character_manager: "CharacterManager" = self.bot.game_manager.character_manager
        item_manager: "ItemManager" = self.bot.game_manager.item_manager
        nlu_data_service: "NLUDataService" = self.bot.nlu_data_service
        rules_config: CoreGameRulesConfig = self.bot.game_manager.rule_engine.rules_config_data

        character = character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
        language = character.selected_language if character and character.selected_language else \
                   (interaction.locale.language if interaction.locale else DEFAULT_BOT_LANGUAGE)

        if not character:
            error_no_character = get_i18n_text(None, "inventory_error_no_character", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="You need to create a character first! Use `/start_new_character`.")
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        # --- NLU Processing for Item ---
        # For "use item on target", the NLU text should ideally be the full phrase if parser supports it.
        # For now, NLU for item_name, and target_name is separate.
        action_text_for_item = item_name
        item_action_data = await parse_player_action(
            text=action_text_for_item, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
        )

        nlu_identified_item_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name

        if item_action_data and item_action_data['entities']:
            for entity in item_action_data['entities']:
                if entity['type'] == 'item':
                    nlu_identified_item_template_id = entity['id']
                    nlu_item_name_in_text = entity['name']
                    break

        if not nlu_identified_item_template_id:
            msg_item_not_understood = get_i18n_text(None, "use_error_item_not_understood", language, default_lang=DEFAULT_BOT_LANGUAGE, default_text="I'm not sure which item ('{item_name}') you want to use.")
            await interaction.followup.send(msg_item_not_understood.format(item_name=item_name), ephemeral=True)
            return

        # --- NLU Processing for Target (Optional) ---
        nlu_target_id: Optional[str] = None
        nlu_target_type: Optional[str] = None
        # nlu_target_name_in_text: str = target_name if target_name else ""

        if target_name:
            # Here, we could parse "target_name" alone or parse "use item_name on target_name"
            # Assuming simpler parsing for now: parse target_name separately.
            target_action_data = await parse_player_action(
                text=target_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
            )
            if target_action_data and target_action_data['entities']:
                # Prioritize NPC, then Player for targeting. Could be more sophisticated.
                for entity_type_priority in ["npc", "player", "location_feature", "item"]: # Example priority
                    target_entity = next((e for e in target_action_data['entities'] if e['type'] == entity_type_priority), None)
                    if target_entity:
                        nlu_target_id = target_entity['id']
                        nlu_target_type = target_entity['type']
                        # nlu_target_name_in_text = target_entity['name']
                        break

            if not nlu_target_id: # NLU couldn't identify a specific game entity for the target name
                # This might be okay if the item doesn't require a known entity target (e.g. area effect at a point)
                # Or it might be an error if the item's target_policy is "requires_target" (handled by item_manager.use_item)
                print(f"Warning: NLU could not identify a specific game entity for target name: {target_name}")
                # For now, we'll pass None and let use_item validate based on target_policy.
                # A more user-friendly approach would be to error here if target_name was provided but not resolved.
                # However, some items might be "use item on <raw_text_target_name>" if target is not a DB entity.

        # --- Call ItemManager ---
        use_result = await item_manager.use_item(
            character_id=character.id,
            guild_id=guild_id_str,
            item_template_id=nlu_identified_item_template_id,
            rules_config=rules_config,
            target_entity_id=nlu_target_id,
            target_entity_type=nlu_target_type
        )

        response_message = use_result['message']
        # Assuming manager messages are user-facing. Localize if they are keys.
        await interaction.followup.send(response_message, ephemeral=not use_result['success'])


async def setup(bot: commands.Bot):
    await bot.add_cog(InventoryCog(bot)) # type: ignore
    print("InventoryCog loaded.")
