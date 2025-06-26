import discord
from discord import app_commands, Interaction, Locale
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast, Dict, Any, List
import logging # Use logging instead of traceback
import json

from bot.utils.i18n_utils import get_i18n_text
from bot.services.nlu_data_service import NLUDataService
from bot.nlu.player_action_parser import parse_player_action
from bot.ai.rules_schema import CoreGameRulesConfig

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager # Added for game_mngr type hint
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.models.character import Character as CharacterModel
    from bot.game.rules.rule_engine import RuleEngine

DEFAULT_BOT_LANGUAGE = "en"

class InventoryCog(commands.Cog, name="Inventory"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    async def _get_language(self, interaction: Interaction, character: Optional["CharacterModel"] = None, guild_id: Optional[str]=None) -> str:
        """Determines the language to use for responses."""
        if character and hasattr(character, 'selected_language') and character.selected_language:
            return character.selected_language
        if interaction.locale and isinstance(interaction.locale, Locale): # interaction.locale can be discord.Locale
            return str(interaction.locale)

        # Fallback to bot's default or guild default if character/interaction locale not set
        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if game_mngr and guild_id and hasattr(game_mngr, 'get_default_bot_language') and callable(getattr(game_mngr, 'get_default_bot_language')):
            guild_lang = await getattr(game_mngr, 'get_default_bot_language')(guild_id)
            if guild_lang:
                return guild_lang
        return DEFAULT_BOT_LANGUAGE


    @app_commands.command(name="inventory", description="View your character's inventory.")
    async def cmd_inventory(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""

        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if not game_mngr or not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'item_manager') or not game_mngr.item_manager:
            # Determine language for early error message
            early_lang = str(interaction.locale) if interaction.locale and isinstance(interaction.locale, Locale) else DEFAULT_BOT_LANGUAGE
            error_services_not_init = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_services_not_init", lang_or_locale=early_lang, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_services_not_init, ephemeral=True)
            return

        character_manager = cast("CharacterManager", game_mngr.character_manager)
        item_manager = cast("ItemManager", game_mngr.item_manager)
        discord_user_id_int = interaction.user.id

        character: Optional["CharacterModel"] = None
        if hasattr(character_manager, 'get_character_by_discord_id') and callable(getattr(character_manager, 'get_character_by_discord_id')):
            character = await character_manager.get_character_by_discord_id(
                guild_id=guild_id_str,
                discord_user_id=discord_user_id_int
            )
        else:
            logging.warning(f"CharacterManager for guild {guild_id_str} missing 'get_character_by_discord_id'.")


        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            error_no_character = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        char_id_val = getattr(character, 'id', 'UNKNOWN_CHAR_ID') # Ensure char_id_val is defined
        char_name_display = getattr(character, 'name', char_id_val)
        if hasattr(character, 'name_i18n') and isinstance(character.name_i18n, dict):
            char_name_display = character.name_i18n.get(language, character.name_i18n.get(DEFAULT_BOT_LANGUAGE, char_name_display))

        inventory_list_json = getattr(character, 'inventory', "[]") # inventory is expected to be List[Dict] or JSON string
        inventory_list_data: List[Dict[str, Any]] = []
        if isinstance(inventory_list_json, str):
            try:
                loaded_data = json.loads(inventory_list_json)
                if isinstance(loaded_data, list):
                    inventory_list_data = loaded_data
                else:
                    logging.warning(f"Character {char_id_val} inventory JSON string did not parse to a list: {inventory_list_json}")
            except json.JSONDecodeError:
                logging.warning(f"Character {char_id_val} inventory JSON string invalid: {inventory_list_json}")
        elif isinstance(inventory_list_json, list): # If it's already a list of dicts
            inventory_list_data = inventory_list_json
        else:
            logging.warning(f"Character {char_id_val} inventory attribute is neither a string nor a list: {type(inventory_list_json)}")


        empty_inv_template = get_i18n_text(guild_id=guild_id_str, text_key="inventory_empty_message", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
        if not inventory_list_data:
            await interaction.followup.send(empty_inv_template.format(character_name=char_name_display), ephemeral=True)
            return

        inventory_title_template = get_i18n_text(guild_id=guild_id_str, text_key="inventory_title", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
        embed = discord.Embed(title=inventory_title_template.format(character_name=char_name_display), color=discord.Color.dark_gold())
        description_lines = []

        unknown_item_entry_text = get_i18n_text(guild_id=guild_id_str, text_key="inventory_item_unknown_entry", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
        unknown_item_label = get_i18n_text(guild_id=guild_id_str, text_key="inventory_item_unknown_name", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
        template_id_label = get_i18n_text(guild_id=guild_id_str, text_key="inventory_item_template_id_label", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)

        for item_entry in inventory_list_data:
            item_template_id_from_inv: Optional[str] = None
            quantity: float = 1.0

            if isinstance(item_entry, dict):
                item_template_id_from_inv = str(item_entry.get('item_id')) or str(item_entry.get('template_id'))
                try:
                    quantity = float(item_entry.get('quantity', 1.0))
                except (ValueError, TypeError):
                    quantity = 1.0 # Default if conversion fails
            elif isinstance(item_entry, str): # Should not happen with correct model
                item_template_id_from_inv = item_entry
            else: # Log if item_entry is not a dict or str
                logging.warning(f"Unexpected item_entry format in inventory for char {char_id_val}: {item_entry}")
                description_lines.append(unknown_item_entry_text); continue


            if not item_template_id_from_inv:
                description_lines.append(unknown_item_entry_text)
                continue

            item_template_data: Optional[Dict[str, Any]] = None
            if hasattr(item_manager, 'get_item_template') and callable(getattr(item_manager, 'get_item_template')):
                item_template_data = await item_manager.get_item_template(guild_id_str, item_template_id_from_inv)

            item_name_display = f"{unknown_item_label} ({template_id_label}: {item_template_id_from_inv[:6]}...)"
            icon = '📦'

            if item_template_data and isinstance(item_template_data, dict):
                name_i18n = item_template_data.get('name_i18n')
                item_name_display = name_i18n.get(language, name_i18n.get(DEFAULT_BOT_LANGUAGE, item_template_data.get('name', item_name_display))) if isinstance(name_i18n, dict) else item_template_data.get('name', item_name_display)
                icon = item_template_data.get('icon', icon)

            description_lines.append(f"{icon} **{item_name_display}** (x{int(quantity) if quantity.is_integer() else quantity})")


        if description_lines:
            embed.description = "\n".join(description_lines)
        else: # Should be caught by the earlier check, but defensive.
            embed.description = empty_inv_template.format(character_name=char_name_display)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @app_commands.command(name="pickup", description="Pick up an item from your current location.")
    @app_commands.describe(item_name="The name of the item you want to pick up.")
    async def cmd_pickup(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""

        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if not game_mngr or not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'item_manager') or not game_mngr.item_manager or \
           not hasattr(game_mngr, 'location_manager') or not game_mngr.location_manager:
            early_lang_pickup = str(interaction.locale) if interaction.locale and isinstance(interaction.locale, Locale) else DEFAULT_BOT_LANGUAGE
            error_services_not_init_pickup = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_services_not_init", lang_or_locale=early_lang_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_services_not_init_pickup, ephemeral=True)
            return

        character_manager = cast("CharacterManager", game_mngr.character_manager)
        item_manager = cast("ItemManager", game_mngr.item_manager)
        # location_manager = cast("LocationManager", game_mngr.location_manager) # Used via character.current_location_id
        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)

        discord_user_id_int = interaction.user.id
        character: Optional["CharacterModel"] = None
        if hasattr(character_manager, 'get_character_by_discord_id') and callable(getattr(character_manager, 'get_character_by_discord_id')):
            character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        language_pickup = await self._get_language(interaction, character, guild_id_str)

        if not character:
            error_no_character_pickup = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character_pickup, ephemeral=True)
            return

        current_location_id = getattr(character, 'current_location_id', None)
        if not current_location_id:
            error_char_not_in_location = get_i18n_text(guild_id=guild_id_str, text_key="pickup_error_char_not_in_location", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_char_not_in_location, ephemeral=True)
            return

        items_in_location: Optional[List[Dict[str, Any]]] = None
        if hasattr(item_manager, 'get_items_in_location_async') and callable(getattr(item_manager, 'get_items_in_location_async')):
            items_in_location = await item_manager.get_items_in_location_async(guild_id_str, str(current_location_id))

        item_to_pickup_instance_data: Optional[Dict[str, Any]] = None
        nlu_identified_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name

        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service is not available.", ephemeral=True)
            return

        action_data = await parse_player_action(
            text=item_name,
            language=language_pickup,
            guild_id=guild_id_str,
            nlu_data_service=nlu_data_service
        )

        if action_data and action_data.get('entities'):
            for entity in action_data['entities']:
                if entity.get('type') == 'item' and entity.get('id'):
                    nlu_identified_template_id = str(entity['id'])
                    nlu_item_name_in_text = str(entity.get('name', item_name))
                    break

        if not nlu_identified_template_id:
            error_item_not_understood = get_i18n_text(guild_id=guild_id_str, text_key="pickup_error_item_not_understood", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_item_not_understood.format(item_name=item_name), ephemeral=True)
            return

        if items_in_location is None: items_in_location = [] # Ensure it's a list

        for instance_data in items_in_location:
            if isinstance(instance_data, dict) and str(instance_data.get('template_id')) == nlu_identified_template_id:
                item_to_pickup_instance_data = instance_data
                break

        if not item_to_pickup_instance_data:
            error_item_not_seen_here = get_i18n_text(guild_id=guild_id_str, text_key="pickup_error_item_not_seen_here_nlu", lang_or_locale=language_pickup, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_item_not_seen_here.format(item_name_nlu=nlu_item_name_in_text), ephemeral=True)
            return

        item_instance_id_val = item_to_pickup_instance_data.get('id')
        item_instance_id = str(item_instance_id_val) if item_instance_id_val is not None else None

        quantity_to_pickup = 1.0 # Default to 1
        try:
            quantity_to_pickup = float(item_to_pickup_instance_data.get('quantity', 1.0))
        except (ValueError, TypeError):
            logging.warning(f"Invalid quantity in item instance data {item_instance_id} for pickup: {item_to_pickup_instance_data.get('quantity')}")


        char_id_str = str(character.id) if hasattr(character, 'id') and character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for pickup.", ephemeral=True); return

        pickup_success = False
        if item_instance_id and hasattr(item_manager, 'transfer_item_world_to_character') and callable(getattr(item_manager, 'transfer_item_world_to_character')):
            pickup_success = await item_manager.transfer_item_world_to_character(
                guild_id=guild_id_str,
                item_instance_id=item_instance_id,
                character_id=char_id_str,
                quantity_to_transfer=quantity_to_pickup # type: ignore[arg-type] # Pyright might complain if quantity_to_transfer expects int
            )
        elif not item_instance_id:
            logging.error(f"Item instance data missing 'id' for pickup: {item_to_pickup_instance_data} in guild {guild_id_str}")
        else:
            logging.warning(f"ItemManager missing 'transfer_item_world_to_character' for guild {guild_id_str}")


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

        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        discord_user_id_int = interaction.user.id

        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if not game_mngr or not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'item_manager') or not game_mngr.item_manager or \
           not hasattr(game_mngr, 'rule_engine') or not game_mngr.rule_engine:
            early_lang_equip = str(interaction.locale) if interaction.locale and isinstance(interaction.locale, Locale) else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_i18n_text(guild_id_str, "inventory_error_services_not_init", early_lang_equip, DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        character_manager = cast("CharacterManager", game_mngr.character_manager)
        item_manager = cast("ItemManager", game_mngr.item_manager)
        rule_engine = cast("RuleEngine", game_mngr.rule_engine)
        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)

        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service not available for equip.", ephemeral=True); return

        rules_config_data_val: Optional[CoreGameRulesConfig] = getattr(rule_engine, 'rules_config_data', None)
        if not rules_config_data_val:
            await interaction.followup.send("Error: Game rules not loaded.", ephemeral=True); return
        rules_config: CoreGameRulesConfig = rules_config_data_val


        character: Optional["CharacterModel"] = None
        if hasattr(character_manager, 'get_character_by_discord_id') and callable(getattr(character_manager, 'get_character_by_discord_id')):
            character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            error_no_character = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        char_id_str = str(character.id) if hasattr(character, 'id') and character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for equip.", ephemeral=True); return

        action_data = await parse_player_action(
            text=item_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
        )

        nlu_identified_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name

        if action_data and action_data.get('entities'):
            for entity in action_data['entities']:
                if entity.get('type') == 'item' and entity.get('id'):
                    nlu_identified_template_id = str(entity['id'])
                    nlu_item_name_in_text = str(entity.get('name', item_name))
                    break

        if not nlu_identified_template_id:
            msg_not_understood = get_i18n_text(guild_id=guild_id_str, text_key="equip_error_item_not_understood", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(msg_not_understood.format(item_name=item_name), ephemeral=True)
            return

        equip_result: Dict[str, Any] = {"success": False, "message": "Equip method not found."} # Default
        if hasattr(item_manager, 'equip_item') and callable(getattr(item_manager, 'equip_item')):
            equip_result = await item_manager.equip_item(
                character_id=char_id_str,
                guild_id=guild_id_str,
                item_template_id_to_equip=nlu_identified_template_id,
                rules_config=rules_config,
                slot_id_preference=slot_preference
            )
        else:
            logging.warning(f"ItemManager missing 'equip_item' for guild {guild_id_str}")


        response_message = equip_result.get('message', "An unknown error occurred during equip.")
        await interaction.followup.send(response_message, ephemeral=not equip_result.get('success', False))


    @app_commands.command(name="unequip", description="Unequip an item.")
    @app_commands.describe(slot_or_item_name="The equipment slot (e.g. 'main_hand') or item name to unequip.")
    async def cmd_unequip(self, interaction: Interaction, slot_or_item_name: str):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        discord_user_id_int = interaction.user.id

        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if not game_mngr or not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'item_manager') or not game_mngr.item_manager or \
           not hasattr(game_mngr, 'rule_engine') or not game_mngr.rule_engine:
            early_lang_unequip = str(interaction.locale) if interaction.locale and isinstance(interaction.locale, Locale) else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_i18n_text(guild_id_str, "inventory_error_services_not_init", early_lang_unequip, DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        character_manager = cast("CharacterManager", game_mngr.character_manager)
        item_manager = cast("ItemManager", game_mngr.item_manager)
        rule_engine = cast("RuleEngine", game_mngr.rule_engine)
        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)

        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service not available for unequip.", ephemeral=True); return

        rules_config_data_val: Optional[CoreGameRulesConfig] = getattr(rule_engine, 'rules_config_data', None)
        if not rules_config_data_val:
            await interaction.followup.send("Error: Game rules not loaded.", ephemeral=True); return
        rules_config: CoreGameRulesConfig = rules_config_data_val

        character: Optional["CharacterModel"] = None
        if hasattr(character_manager, 'get_character_by_discord_id') and callable(getattr(character_manager, 'get_character_by_discord_id')):
            character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            error_no_character = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        char_id_str = str(character.id) if hasattr(character, 'id') and character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for unequip.", ephemeral=True); return


        slot_to_unequip_directly: Optional[str] = None
        item_template_id_from_nlu: Optional[str] = None

        normalized_input = slot_or_item_name.lower().replace(" ", "_")
        if rules_config.equipment_slots and normalized_input in rules_config.equipment_slots:
            slot_to_unequip_directly = normalized_input
        else:
            action_data = await parse_player_action(
                text=slot_or_item_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
            )
            if action_data and action_data.get('entities'):
                for entity in action_data['entities']:
                    if entity.get('type') == 'item' and entity.get('id'):
                        item_template_id_from_nlu = str(entity['id'])
                        break
            if not item_template_id_from_nlu: # If still not found after NLU, it's an error
                msg_not_understood = get_i18n_text(guild_id=guild_id_str, text_key="unequip_error_not_understood", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
                await interaction.followup.send(msg_not_understood.format(name=slot_or_item_name), ephemeral=True)
                return

        unequip_result: Dict[str, Any] = {"success": False, "message": "Unequip method not found."} # Default
        if hasattr(item_manager, 'unequip_item') and callable(getattr(item_manager, 'unequip_item')):
            unequip_result = await item_manager.unequip_item(
                character_id=char_id_str,
                guild_id=guild_id_str,
                rules_config=rules_config,
                item_template_id_to_unequip=item_template_id_from_nlu, # type: ignore[arg-type] # Pyright may complain if method expects str
                slot_id_to_unequip=slot_to_unequip_directly
            )
        else:
            logging.warning(f"ItemManager missing 'unequip_item' for guild {guild_id_str}")

        response_message = unequip_result.get('message', "An unknown error occurred during unequip.")
        await interaction.followup.send(response_message, ephemeral=not unequip_result.get('success', False))

    @app_commands.command(name="drop", description="Drop an item from your inventory to the ground.")
    @app_commands.describe(item_name="The name of the item you want to drop.")
    async def cmd_drop(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""

        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if not game_mngr or \
           not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'item_manager') or not game_mngr.item_manager or \
           not hasattr(game_mngr, 'location_manager') or not game_mngr.location_manager:
            early_lang_drop = str(interaction.locale) if interaction.locale and isinstance(interaction.locale, Locale) else DEFAULT_BOT_LANGUAGE
            error_services_not_init_drop = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_services_not_init", lang_or_locale=early_lang_drop, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_services_not_init_drop, ephemeral=True)
            return

        character_manager = cast("CharacterManager", game_mngr.character_manager)
        item_manager = cast("ItemManager", game_mngr.item_manager)
        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)

        discord_user_id_int = interaction.user.id
        character: Optional["CharacterModel"] = None
        if hasattr(character_manager, 'get_character_by_discord_id') and callable(getattr(character_manager, 'get_character_by_discord_id')):
            character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            error_no_character_drop = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character_drop, ephemeral=True)
            return

        char_id_str = str(character.id) if hasattr(character, 'id') and character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for drop.", ephemeral=True); return


        current_location_id_val = getattr(character, 'current_location_id', None)
        if not current_location_id_val:
            error_char_not_in_location_drop = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_char_not_in_location", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_char_not_in_location_drop, ephemeral=True)
            return
        current_location_id = str(current_location_id_val)


        inventory_list_json = getattr(character, 'inventory', "[]")
        character_inventory_data: List[Dict[str, Any]] = []
        if isinstance(inventory_list_json, str):
            try:
                loaded_data = json.loads(inventory_list_json)
                if isinstance(loaded_data, list): character_inventory_data = loaded_data
            except json.JSONDecodeError: character_inventory_data = []
        elif isinstance(inventory_list_json, list): character_inventory_data = inventory_list_json

        if not character_inventory_data:
            char_name_display_drop = getattr(character, 'name', char_id_str)
            if hasattr(character, 'name_i18n') and isinstance(character.name_i18n, dict):
                char_name_display_drop = character.name_i18n.get(language, character.name_i18n.get(DEFAULT_BOT_LANGUAGE, char_name_display_drop))
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

        if action_data and action_data.get('entities'):
            for entity in action_data['entities']:
                if entity.get('type') == 'item' and entity.get('id'):
                    nlu_identified_template_id = str(entity['id'])
                    nlu_item_name_in_text = str(entity.get('name',item_name))
                    break

        if not nlu_identified_template_id:
            error_item_not_understood_drop = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_item_not_understood", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_item_not_understood_drop.format(item_name=item_name), ephemeral=True)
            return

        item_entry_to_drop: Optional[Dict[str, Any]] = None
        for entry in character_inventory_data:
            current_template_id = str(entry.get('item_id')) or str(entry.get('template_id'))
            if current_template_id == nlu_identified_template_id:
                item_entry_to_drop = entry
                break

        if not item_entry_to_drop:
            error_item_not_in_inventory = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_item_not_found_nlu", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_item_not_in_inventory.format(item_name_nlu=nlu_item_name_in_text), ephemeral=True)
            return

        item_template_id_to_drop = nlu_identified_template_id # Known to be str here
        quantity_to_drop = 1.0

        original_inventory = list(character_inventory_data) # Deep copy for potential rollback
        updated_inventory: List[Dict[str, Any]] = []
        item_removed_from_list = False
        for item_entry_dict in original_inventory:
            if not isinstance(item_entry_dict, dict): continue # Skip non-dict entries
            current_item_template_id = str(item_entry_dict.get('item_id')) or str(item_entry_dict.get('template_id'))
            if current_item_template_id == item_template_id_to_drop and not item_removed_from_list:
                current_quantity = 1.0
                try: current_quantity = float(item_entry_dict.get('quantity', 1.0))
                except (ValueError, TypeError): pass

                if current_quantity > quantity_to_drop:
                    updated_inventory.append({**item_entry_dict, 'quantity': current_quantity - quantity_to_drop})
                    item_removed_from_list = True
                elif current_quantity == quantity_to_drop:
                    item_removed_from_list = True # Item completely removed, do not append
                else: # Not enough quantity, should not happen if logic is for single drop
                    updated_inventory.append(item_entry_dict) # Keep as is
            else:
                updated_inventory.append(item_entry_dict)

        if not item_removed_from_list:
            error_generic_drop_fail = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_generic_fail", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_generic_drop_fail.format(item_name=nlu_item_name_in_text), ephemeral=True)
            return

        # Save updated inventory to character
        setattr(character, 'inventory', updated_inventory)
        if hasattr(character_manager, "mark_dirty") and callable(getattr(character_manager, "mark_dirty")):
            await getattr(character_manager, "mark_dirty")(char_id_str, guild_id_str)
        elif hasattr(character_manager, "update_character_field") and callable(getattr(character_manager, "update_character_field")):
            logging.warning(f"CharacterManager for guild {guild_id_str} missing 'mark_dirty'. Using 'update_character_field' for inventory.")
            await getattr(character_manager, "update_character_field")(char_id_str, guild_id_str, "inventory", updated_inventory)
        else:
            logging.error(f"CharacterManager for guild {guild_id_str} missing methods to persist inventory change for drop.")
            # Consider rolling back inventory if persistence is critical and failed.

        new_item_instance_id_in_world: Optional[str] = None
        if hasattr(item_manager, 'create_item_instance') and callable(getattr(item_manager, 'create_item_instance')):
            new_item_instance_id_in_world = await item_manager.create_item_instance(
                template_id=item_template_id_to_drop,
                guild_id=guild_id_str,
                quantity=quantity_to_drop,
                location_id=current_location_id
            )

        if new_item_instance_id_in_world:
            success_drop_message_template = get_i18n_text(guild_id=guild_id_str, text_key="drop_success_message", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(success_drop_message_template.format(user_mention=interaction.user.mention, item_name_display=nlu_item_name_in_text, quantity=int(quantity_to_drop)), ephemeral=False)
        else:
            # Rollback inventory change if item creation in world failed
            setattr(character, 'inventory', original_inventory)
            if hasattr(character_manager, "mark_dirty") and callable(getattr(character_manager, "mark_dirty")):
                 await getattr(character_manager, "mark_dirty")(char_id_str, guild_id_str)
            elif hasattr(character_manager, "update_character_field") and callable(getattr(character_manager, "update_character_field")):
                 await getattr(character_manager, "update_character_field")(char_id_str, guild_id_str, "inventory", original_inventory)

            error_drop_fail_world = get_i18n_text(guild_id=guild_id_str, text_key="drop_error_fail_world_spawn", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_drop_fail_world.format(item_name=nlu_item_name_in_text), ephemeral=True)

    @app_commands.command(name="use", description="Use an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to use.", target_name="Optional: the name of the target (e.g., another character).")
    async def cmd_use_item(self, interaction: Interaction, item_name: str, target_name: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        discord_user_id_int = interaction.user.id

        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if not game_mngr or \
           not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'item_manager') or not game_mngr.item_manager or \
           not hasattr(game_mngr, 'rule_engine') or not game_mngr.rule_engine:
            early_lang_use = str(interaction.locale) if interaction.locale and isinstance(interaction.locale, Locale) else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_i18n_text(guild_id_str, "inventory_error_services_not_init", early_lang_use, DEFAULT_BOT_LANGUAGE), ephemeral=True)
            return

        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)
        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service is not available for use command.", ephemeral=True)
            return

        character_manager = cast("CharacterManager", game_mngr.character_manager)
        item_manager = cast("ItemManager", game_mngr.item_manager)
        rule_engine = cast("RuleEngine", game_mngr.rule_engine)


        current_rules_config_val: Optional[CoreGameRulesConfig] = getattr(rule_engine, 'rules_config_data', None)
        if not current_rules_config_val:
             await interaction.followup.send("Error: Game rules config not loaded.", ephemeral=True); return
        rules_config: CoreGameRulesConfig = current_rules_config_val


        character: Optional["CharacterModel"] = None
        if hasattr(character_manager, 'get_character_by_discord_id') and callable(getattr(character_manager, 'get_character_by_discord_id')):
            character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)

        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            error_no_character = get_i18n_text(guild_id=guild_id_str, text_key="inventory_error_no_character", lang_or_locale=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_no_character, ephemeral=True)
            return

        char_id_str = str(character.id) if hasattr(character, 'id') and character.id is not None else ""
        if not char_id_str:
            await interaction.followup.send("Error: Character ID is missing for use command.", ephemeral=True); return


        action_text_for_item = item_name
        item_action_data = await parse_player_action(
            text=action_text_for_item, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
        )

        nlu_identified_item_template_id: Optional[str] = None
        nlu_item_name_in_text: str = item_name

        if item_action_data and item_action_data.get('entities'):
            for entity in item_action_data['entities']:
                if entity.get('type') == 'item' and entity.get('id'):
                    nlu_identified_item_template_id = str(entity['id'])
                    nlu_item_name_in_text = str(entity.get('name', item_name))
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
            if target_action_data and target_action_data.get('entities'):
                for entity_type_priority in ["npc", "player", "location_feature", "item"]: # player is an alias for character
                    target_entity = next((e for e in target_action_data['entities'] if e.get('type') == entity_type_priority), None)
                    if target_entity and target_entity.get('id'):
                        nlu_target_id = str(target_entity['id'])
                        nlu_target_type = str(target_entity['type'])
                        break
            if not nlu_target_id:
                logging.warning(f"NLU could not identify a specific game entity for target name: {target_name} in guild {guild_id_str}")


        use_result: Dict[str, Any] = {"success": False, "message": "Use item method not found."} # Default
        if hasattr(item_manager, 'use_item') and callable(getattr(item_manager, 'use_item')):
            use_result = await item_manager.use_item(
                character_user=interaction.user,
                character_id=char_id_str,
                guild_id=guild_id_str,
                item_template_id=nlu_identified_item_template_id,
                rules_config=rules_config,
                target_entity_id=nlu_target_id, # Optional
                target_entity_type=nlu_target_type # Optional
            )
        else:
            logging.warning(f"ItemManager missing 'use_item' for guild {guild_id_str}")

        response_message = use_result.get('message', "An unknown error occurred while using the item.")
        await interaction.followup.send(response_message, ephemeral=not use_result.get('success', False))


async def setup(bot: "RPGBot"): # Changed commands.Bot to RPGBot for consistency
    await bot.add_cog(InventoryCog(bot))
    logging.info("InventoryCog loaded.") # Use logging
