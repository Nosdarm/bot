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
        interaction_language = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE


        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_manager or not game_mngr.item_manager:
            error_services_not_init = get_i18n_text(guild_id=None, text_key="inventory_error_services_not_init", lang_or_locale=interaction_language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_services_not_init, ephemeral=True)
            return

        character_manager: "CharacterManager" = game_mngr.character_manager
        item_manager: "ItemManager" = game_mngr.item_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = await character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )

        # Language for this specific interaction, AFTER character is fetched
        language = DEFAULT_BOT_LANGUAGE # Default if character or selected_language is None
        if character and character.selected_language:
            language = character.selected_language
        elif interaction.locale: # Fallback to interaction locale if character has no preference
            language = str(interaction.locale)

        if not character:
            error_no_character = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
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

        empty_inv_template = get_i18n_text(guild_id=guild_id_str, text_key="inventory_empty_message", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
        if not inventory_list_data:
            await interaction.followup.send(empty_inv_template.format(character_name=char_name_display), ephemeral=True)
            return

        inventory_title_template = get_i18n_text(guild_id=guild_id_str, text_key="inventory_title", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
        embed = discord.Embed(title=inventory_title_template.format(character_name=char_name_display), color=discord.Color.dark_gold())
        description_lines = []

        # Localized strings for item fallbacks
        unknown_item_entry_text = get_i18n_text(guild_id=guild_id_str, text_key="inventory_item_unknown_entry", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
        unknown_item_label = get_i18n_text(guild_id=guild_id_str, text_key="inventory_item_unknown_name", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
        template_id_label = get_i18n_text(guild_id=guild_id_str, text_key="inventory_item_template_id_label", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)

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

        interaction_language_pickup = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE
        guild_id_str = str(interaction.guild_id) # Define early for i18n calls

        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_manager or not game_mngr.item_manager or not game_mngr.location_manager:
            error_services_not_init_pickup = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_services_not_init", lang_or_locale=interaction_language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_services_not_init_pickup, ephemeral=True)
            return

        character_manager: "CharacterManager" = game_mngr.character_manager
        item_manager: "ItemManager" = game_mngr.item_manager
        location_manager: "LocationManager" = game_mngr.location_manager
        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)

        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        language_pickup = DEFAULT_BOT_LANGUAGE
        if character and character.selected_language:
            language_pickup = character.selected_language
        elif interaction.locale:
            language_pickup = str(interaction.locale)

        if not character:
            error_no_character_pickup = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character_pickup, ephemeral=True)
            return

        current_location_id = getattr(character, 'current_location_id', None)
        if not current_location_id:
            error_char_not_in_location = get_i18n_text(guild_id=guild_id_str, text_key="pickup_error_char_not_in_location", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_char_not_in_location, ephemeral=True)
            return

        items_in_location = await item_manager.get_items_in_location_async(guild_id_str, current_location_id)
        item_to_pickup_instance_data: Optional[Dict[str, Any]] = None
        nlu_identified_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name # Fallback to original input

        # 1. NLU Processing
        if not nlu_data_service: # nlu_data_service is Optional now
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
            error_item_not_understood = get_i18n_text(guild_id=guild_id_str, text_key="pickup_error_item_not_understood", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_item_not_understood.format(item_name=item_name), ephemeral=True)
            return

        # 2. Find the item instance in the location matching the NLU-identified template_id
        if items_in_location is None: items_in_location = []

        for instance_data in items_in_location:
            if isinstance(instance_data, dict) and instance_data.get('template_id') == nlu_identified_template_id:
                item_to_pickup_instance_data = instance_data
                break

        if not item_to_pickup_instance_data:
            error_item_not_seen_here = get_i18n_text(guild_id=guild_id_str, text_key="pickup_error_item_not_seen_here_nlu", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_item_not_seen_here.format(item_name_nlu=nlu_item_name_in_text), ephemeral=True)
            return

        # 3. Proceed with pickup logic using item_to_pickup_instance_data
        item_instance_id = item_to_pickup_instance_data.get('id')
        quantity_to_pickup = float(item_to_pickup_instance_data.get('quantity', 1.0))

        # Ensure character ID is a string
        char_id_str = str(character.id) if character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for pickup.", ephemeral=True); return


        pickup_success = await item_manager.transfer_item_world_to_character(
            guild_id=guild_id_str,
            item_instance_id=str(item_instance_id) if item_instance_id else "",
            character_id=char_id_str,
            quantity_to_transfer=quantity_to_pickup
        )

        if pickup_success:
            success_pickup_message = get_i18n_text(guild_id=guild_id_str, text_key="pickup_success_message", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(success_pickup_message.format(user_mention=interaction.user.mention, item_name_display=nlu_item_name_in_text, quantity=int(quantity_to_pickup)), ephemeral=False)
        else:
            error_pickup_failed = get_i18n_text(guild_id=guild_id_str, text_key="pickup_error_failed", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_pickup_failed.format(item_name=nlu_item_name_in_text), ephemeral=True)


    @app_commands.command(name="equip", description="Equip an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to equip.", slot_preference="Optional: preferred slot (e.g., 'main_hand', 'off_hand')")
    async def cmd_equip(self, interaction: Interaction, item_name: str, slot_preference: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_manager or not game_mngr.item_manager or not game_mngr.rule_engine:
            await interaction.followup.send("Error: Core game services not fully initialized for equip.", ephemeral=True); return

        character_manager: "CharacterManager" = game_mngr.character_manager
        item_manager: "ItemManager" = game_mngr.item_manager
        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None) # type: ignore[attr-defined]

        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service not available for equip.", ephemeral=True); return

        if not game_mngr.rule_engine.rules_config_data: # type: ignore[attr-defined]
            await interaction.followup.send("Error: Game rules not loaded.", ephemeral=True)
            return
        rules_config: CoreGameRulesConfig = game_mngr.rule_engine.rules_config_data # type: ignore[attr-defined]


        character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
        language = character.selected_language if character and character.selected_language else (str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE)

        if not character:
            error_no_character = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        char_id_str = str(character.id) if character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for equip.", ephemeral=True); return

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
            msg_not_understood = get_i18n_text(guild_id=guild_id_str, text_key="equip_error_item_not_understood", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(msg_not_understood.format(item_name=item_name), ephemeral=True)
            return

        equip_result = await item_manager.equip_item(
            character_id=char_id_str,
            guild_id=guild_id_str,
            item_template_id_to_equip=nlu_identified_template_id,
            rules_config=rules_config, # This is CoreGameRulesConfig, ensure item_manager expects this type
            slot_id_preference=slot_preference
        )

        response_message = equip_result['message']
        await interaction.followup.send(response_message, ephemeral=not equip_result['success'])


    @app_commands.command(name="unequip", description="Unequip an item.")
    @app_commands.describe(slot_or_item_name="The equipment slot (e.g. 'main_hand') or item name to unequip.")
    async def cmd_unequip(self, interaction: Interaction, slot_or_item_name: str):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_manager or not game_mngr.item_manager or not game_mngr.rule_engine:
            await interaction.followup.send("Error: Core game services not fully initialized for unequip.", ephemeral=True); return

        character_manager: "CharacterManager" = game_mngr.character_manager
        item_manager: "ItemManager" = game_mngr.item_manager
        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None) # type: ignore[attr-defined]

        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service not available for unequip.", ephemeral=True); return

        if not game_mngr.rule_engine.rules_config_data: # type: ignore[attr-defined]
            await interaction.followup.send("Error: Game rules not loaded.", ephemeral=True)
            return
        rules_config: CoreGameRulesConfig = game_mngr.rule_engine.rules_config_data # type: ignore[attr-defined]

        character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
        language = character.selected_language if character and character.selected_language else (str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE)

        if not character:
            error_no_character = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        char_id_str = str(character.id) if character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for unequip.", ephemeral=True); return


        slot_to_unequip_directly: Optional[str] = None
        item_template_id_from_nlu: Optional[str] = None

        # Check if slot_or_item_name is a direct slot_id
        normalized_input = slot_or_item_name.lower().replace(" ", "_")
        if normalized_input in rules_config.equipment_slots: # equipment_slots is a dict
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
            if not item_template_id_from_nlu: # Only error if it wasn't a direct slot match either
                msg_not_understood = get_i18n_text(guild_id=guild_id_str, text_key="unequip_error_not_understood", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
                await interaction.followup.send(msg_not_understood.format(name=slot_or_item_name), ephemeral=True)
                return

        unequip_result = await item_manager.unequip_item(
            character_id=char_id_str,
            guild_id=guild_id_str,
            rules_config=rules_config, # This is CoreGameRulesConfig
            item_template_id_to_unequip=item_template_id_from_nlu, # Can be None if slot_to_unequip_directly is set
            slot_id_to_unequip=slot_to_unequip_directly # Can be None if item_template_id_from_nlu is set
        )

        response_message = unequip_result['message']
        await interaction.followup.send(response_message, ephemeral=not unequip_result['success'])

    @app_commands.command(name="drop", description="Drop an item from your inventory to the ground.")
    @app_commands.describe(item_name="The name of the item you want to drop.")
    async def cmd_drop(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)

        # Language for initial error messages if character/locale not available yet
        interaction_language_drop = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE
        guild_id_str = str(interaction.guild_id) # Define early for i18n

        game_mngr = self.bot.game_manager
        if not game_mngr or \
           not game_mngr.character_manager or \
           not game_mngr.item_manager or \
           not game_mngr.location_manager:
            error_services_not_init_drop = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_services_not_init", lang_or_locale=interaction_language_drop, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_services_not_init_drop, ephemeral=True)
            return

        character_manager: "CharacterManager" = game_mngr.character_manager
        item_manager: "ItemManager" = game_mngr.item_manager
        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)
        # location_manager: "LocationManager" = game_mngr.location_manager # Not directly used here

        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        # Determine language for this interaction
        language = DEFAULT_BOT_LANGUAGE
        if character and character.selected_language:
            language = character.selected_language
        elif interaction.locale:
            language = str(interaction.locale)

        if not character:
            error_no_character_drop = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character_drop, ephemeral=True)
            return

        char_id_str = str(character.id) if character.id is not None else ""
        if not char_id_str: # Should not happen if character was found
            await interaction.followup.send("Error: Character ID is missing for drop.", ephemeral=True); return


        current_location_id = getattr(character, 'current_location_id', None)
        if not current_location_id:
            error_char_not_in_location_drop = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_char_not_in_location", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_char_not_in_location_drop, ephemeral=True)
            return

        inventory_list_json = getattr(character, 'inventory', "[]")
        character_inventory_data: List[Dict[str, Any]] = []
        if isinstance(inventory_list_json, str):
            try:
                loaded_data = json.loads(inventory_list_json)
                if isinstance(loaded_data, list): character_inventory_data = loaded_data
            except json.JSONDecodeError:
                character_inventory_data = []
        elif isinstance(inventory_list_json, list):
            character_inventory_data = inventory_list_json

        if not character_inventory_data:
            char_name_display_drop = character.name_i18n.get(language, character.name_i18n.get(DEFAULT_BOT_LANGUAGE, character.id)) if hasattr(character, 'name_i18n') and isinstance(character.name_i18n, dict) else getattr(character, 'name', character.id)
            empty_inv_template_drop = get_i18n_text(guild_id=guild_id_str, text_key="inventory_empty_message", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(empty_inv_template_drop.format(character_name=char_name_display_drop), ephemeral=True)
            return

        nlu_identified_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name

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
            error_item_not_understood_drop = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_item_not_understood", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_item_not_understood_drop.format(item_name=item_name), ephemeral=True)
            return

        item_entry_to_drop: Optional[Dict[str, Any]] = None
        for entry in character_inventory_data:
            current_template_id = entry.get('item_id') or entry.get('template_id')
            if current_template_id == nlu_identified_template_id:
                item_entry_to_drop = entry
                break

        if not item_entry_to_drop:
            error_item_not_in_inventory = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_item_not_found_nlu", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_item_not_in_inventory.format(item_name_nlu=nlu_item_name_in_text), ephemeral=True)
            return

        item_template_id_to_drop = nlu_identified_template_id
        quantity_to_drop = 1

        original_inventory = list(character_inventory_data)
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
                    item_removed_from_list = True
                else:
                    updated_inventory.append(item_entry)
            else:
                updated_inventory.append(item_entry)

        if not item_removed_from_list:
            error_generic_drop_fail = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_generic_fail", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_generic_drop_fail.format(item_name=item_name), ephemeral=True)
            return

        character.inventory = updated_inventory # type: ignore[assignment]
        if hasattr(character_manager, "mark_dirty"):
            character_manager.mark_dirty(char_id_str, guild_id_str)
        else:
            logging.warning(f"CharacterManager for guild {guild_id_str} missing 'mark_dirty'. Inventory change might not persist without explicit save.")
            # Fallback: attempt to save directly if a method exists, or log the issue.
            if hasattr(character_manager, "save_character_inventory") and callable(getattr(character_manager, "save_character_inventory")):
                await character_manager.save_character_inventory(char_id_str, guild_id_str, updated_inventory) # type: ignore[attr-defined]
            elif hasattr(character_manager, "update_character_field") and callable(getattr(character_manager, "update_character_field")):
                 await character_manager.update_character_field(char_id_str, guild_id_str, "inventory", updated_inventory) # type: ignore[attr-defined]


        new_item_instance_id_in_world = await item_manager.create_item_instance(
            template_id=item_template_id_to_drop,
            guild_id=guild_id_str,
            quantity=quantity_to_drop,
            location_id=current_location_id
        )

        if new_item_instance_id_in_world:
            success_drop_message_template = get_i18n_text(guild_id=guild_id_str, text_key="drop_success_message", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(success_drop_message_template.format(user_mention=interaction.user.mention, item_name_display=nlu_item_name_in_text, quantity=quantity_to_drop), ephemeral=False)
        else:
            character.inventory = original_inventory # type: ignore[assignment]
            if hasattr(character_manager, "mark_dirty"):
                 character_manager.mark_dirty(char_id_str, guild_id_str)
            # Potentially re-save original inventory if rollback is critical and mark_dirty isn't enough
            error_drop_fail_world = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_fail_world_spawn", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_drop_fail_world.format(item_name=nlu_item_name_in_text), ephemeral=True)

    @app_commands.command(name="use", description="Use an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to use.", target_name="Optional: the name of the target (e.g., another character).")
    async def cmd_use_item(self, interaction: Interaction, item_name: str, target_name: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        # --- Service and Data Initialization ---
        game_mngr = self.bot.game_manager
        if not game_mngr or \
           not game_mngr.character_manager or \
           not game_mngr.item_manager or \
           not game_mngr.rule_engine:
            # Simplified error message for brevity
            await interaction.followup.send("Error: Core game services are not fully initialized for use command.", ephemeral=True)
            return

        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None) # type: ignore[attr-defined]
        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service is not available for use command.", ephemeral=True)
            return

        character_manager: "CharacterManager" = game_mngr.character_manager
        item_manager: "ItemManager" = game_mngr.item_manager

        current_rules_config: Optional[CoreGameRulesConfig] = None
        if game_mngr.rule_engine: # rule_engine itself can be None
            current_rules_config = getattr(game_mngr.rule_engine, 'rules_config_data', None)

        if not current_rules_config:
             await interaction.followup.send("Error: Game rules config not loaded.", ephemeral=True); return
        rules_config: CoreGameRulesConfig = current_rules_config # Now it's confirmed not None


        character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
        language = character.selected_language if character and character.selected_language else \
                   (str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE)

        if not character:
            error_no_character = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        char_id_str = str(character.id) if character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for use command.", ephemeral=True); return


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
            msg_item_not_understood = get_i18n_text(guild_id=guild_id_str, text_key="use_error_item_not_understood", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(msg_item_not_understood.format(item_name=item_name), ephemeral=True)
            return

        nlu_target_id: Optional[str] = None
        nlu_target_type: Optional[str] = None

        if target_name:
            target_action_data = await parse_player_action(
                text=target_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
            )
            if target_action_data and target_action_data['entities']:
                for entity_type_priority in ["npc", "player", "location_feature", "item"]:
                    target_entity = next((e for e in target_action_data['entities'] if e['type'] == entity_type_priority), None)
                    if target_entity:
                        nlu_target_id = target_entity['id']
                        nlu_target_type = target_entity['type']
                        break
            if not nlu_target_id:
                logging.warning(f"NLU could not identify a specific game entity for target name: {target_name} in guild {guild_id_str}")


        use_result = await item_manager.use_item(
            character_user=interaction.user,
            character_id=char_id_str,
            guild_id=guild_id_str,
            item_template_id=nlu_identified_item_template_id,
            rules_config=rules_config,
            target_entity_id=nlu_target_id,
            target_entity_type=nlu_target_type
        )

        response_message = use_result['message']
        await interaction.followup.send(response_message, ephemeral=not use_result['success'])


async def setup(bot: commands.Bot):
    await bot.add_cog(InventoryCog(bot)) # type: ignore
    print("InventoryCog loaded.")
