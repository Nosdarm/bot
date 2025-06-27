import discord
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast, Dict, Any, List
import logging
import json

from bot.utils.i18n_utils import get_localized_string, DEFAULT_BOT_LANGUAGE # Import DEFAULT_BOT_LANGUAGE
from bot.services.nlu_data_service import NLUDataService
from bot.nlu.player_action_parser import parse_player_action, PlayerActionData
from bot.ai.rules_schema import CoreGameRulesConfig

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager, EquipResult, ItemInstance # Added ItemInstance
    from bot.game.managers.location_manager import LocationManager
    from bot.game.models.character import Character as CharacterModel
    from bot.game.rules.rule_engine import RuleEngine
    from bot.database.models import Item as DBItemModel # For PydanticItem in ItemManager returns

class InventoryCog(commands.Cog, name="Inventory"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    async def _get_language(self, interaction: Interaction, character: Optional[CharacterModel] = None, guild_id_str: Optional[str]=None) -> str:
        if character and hasattr(character, 'selected_language') and character.selected_language and isinstance(character.selected_language, str):
            return character.selected_language
        if interaction.locale:
            return str(interaction.locale)

        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if game_mngr and guild_id_str and hasattr(game_mngr, 'get_rule') and callable(getattr(game_mngr, 'get_rule')):
            get_rule_method = getattr(game_mngr, 'get_rule')
            guild_lang_result = await get_rule_method(guild_id_str, "default_language", DEFAULT_BOT_LANGUAGE)
            if guild_lang_result and isinstance(guild_lang_result, str):
                return guild_lang_result
        return DEFAULT_BOT_LANGUAGE

    @app_commands.command(name="inventory", description="View your character's inventory.")
    async def cmd_inventory(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)

        char_manager: Optional["CharacterManager"] = None
        item_mgr: Optional["ItemManager"] = None

        if game_mngr:
            char_manager = cast("CharacterManager", getattr(game_mngr, 'character_manager', None))
            item_mgr = cast("ItemManager", getattr(game_mngr, 'item_manager', None))

        if not game_mngr or not char_manager or not item_mgr:
            early_lang = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_localized_string(key="inventory_error_services_not_init", lang=early_lang, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True)
            return

        character = await char_manager.get_character_by_discord_id(guild_id_str, interaction.user.id)
        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True)
            return

        char_name_i18n = getattr(character, 'name_i18n', {})
        char_name_display = char_name_i18n.get(language, char_name_i18n.get(DEFAULT_BOT_LANGUAGE, character.id if hasattr(character, 'id') else "Unknown Character"))


        inventory_list_data: List[Dict[str, Any]] = []
        inv_attr = getattr(character, 'inventory', [])
        if isinstance(inv_attr, str):
            try: inventory_list_data = json.loads(inv_attr)
            except json.JSONDecodeError: logging.warning(f"Invalid inventory JSON for char {character.id if hasattr(character, 'id') else 'UNKNOWN_ID'}")
        elif isinstance(inv_attr, list): inventory_list_data = inv_attr

        empty_inv_msg = get_localized_string(key="inventory_empty_message", lang=language, default_lang=DEFAULT_BOT_LANGUAGE).format(character_name=char_name_display)
        if not inventory_list_data:
            await interaction.followup.send(empty_inv_msg, ephemeral=True); return

        embed_title = get_localized_string(key="inventory_title", lang=language, default_lang=DEFAULT_BOT_LANGUAGE).format(character_name=char_name_display)
        embed = discord.Embed(title=embed_title, color=discord.Color.dark_gold())
        description_lines = []

        unknown_item_entry = get_localized_string(key="inventory_item_unknown_entry", lang=language, default_lang=DEFAULT_BOT_LANGUAGE)
        unknown_item_name = get_localized_string(key="inventory_item_unknown_name", lang=language, default_lang=DEFAULT_BOT_LANGUAGE)
        template_id_label_text = get_localized_string(key="inventory_item_template_id_label", lang=language, default_lang=DEFAULT_BOT_LANGUAGE)

        for item_entry in inventory_list_data:
            item_tpl_id: Optional[str] = None; qty: float = 1.0
            if isinstance(item_entry, dict):
                item_tpl_id_val = item_entry.get('item_id', item_entry.get('template_id'))
                item_tpl_id = str(item_tpl_id_val) if item_tpl_id_val is not None else None
                try: qty = float(item_entry.get('quantity', 1.0))
                except (ValueError, TypeError): qty = 1.0
            elif isinstance(item_entry, str): item_tpl_id = item_entry
            else: description_lines.append(unknown_item_entry); continue

            if not item_tpl_id or item_tpl_id == 'None': description_lines.append(unknown_item_entry); continue

            item_tpl_data = item_mgr.get_item_template(item_tpl_id)
            item_name = f"{unknown_item_name} ({template_id_label_text}: {item_tpl_id[:6]}...)"
            icon = '📦'
            if item_tpl_data:
                name_i18n_dict = item_tpl_data.get('name_i18n', {})
                item_name = name_i18n_dict.get(language, name_i18n_dict.get(DEFAULT_BOT_LANGUAGE, item_tpl_data.get('name', item_name)))
                icon = item_tpl_data.get('icon', icon)
            description_lines.append(f"{icon} **{item_name}** (x{int(qty) if qty.is_integer() else qty})")

        embed.description = "\n".join(description_lines) if description_lines else empty_inv_msg
        await interaction.followup.send(embed=embed, ephemeral=True)


    @app_commands.command(name="pickup", description="Pick up an item from your current location.")
    @app_commands.describe(item_name="The name of the item you want to pick up.")
    async def cmd_pickup(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)

        char_manager: Optional["CharacterManager"] = None
        item_mgr: Optional["ItemManager"] = None
        # loc_manager: Optional["LocationManager"] = None # Not directly used in this simplified version, but good for full context

        if game_mngr:
            char_manager = cast("CharacterManager", getattr(game_mngr, 'character_manager', None))
            item_mgr = cast("ItemManager", getattr(game_mngr, 'item_manager', None))
            # loc_manager = cast("LocationManager", getattr(game_mngr, 'location_manager', None))

        if not game_mngr or not char_manager or not item_mgr: # Removed loc_manager from essential check for now
            early_lang = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_localized_string(key="inventory_error_services_not_init", lang=early_lang, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)
        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service unavailable.", ephemeral=True); return

        character = await char_manager.get_character_by_discord_id(guild_id_str, interaction.user.id)
        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        char_location_id = getattr(character, 'location_id', None)
        if not char_location_id:
            await interaction.followup.send(get_localized_string(key="pickup_error_char_not_in_location", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        items_in_loc_models: List["ItemInstance"] = await item_mgr.get_items_in_location_async(guild_id_str, str(char_location_id))

        action_data: Optional[PlayerActionData] = await parse_player_action(
            text_input=item_name,
            language=language,
            guild_id=guild_id_str,
            nlu_data_service=nlu_data_service,
            # game_log_manager=None, # Explicitly pass None if not available/needed by this path in parser
            # character_id_str=character.id if hasattr(character, 'id') else None
        )
        nlu_item_tpl_id: Optional[str] = None; nlu_item_name: str = item_name
        if action_data and action_data.get('entities'):
            item_entity = next((e for e in action_data['entities'] if e.get('type') == 'item' and e.get('id')), None)
            if item_entity:
                nlu_item_tpl_id = str(item_entity['id'])
                nlu_item_name = str(item_entity.get('name', item_name))

        if not nlu_item_tpl_id:
            await interaction.followup.send(get_localized_string(key="pickup_error_item_not_understood", lang=language, default_lang=DEFAULT_BOT_LANGUAGE).format(item_name=item_name), ephemeral=True); return

        item_to_pickup_model: Optional["ItemInstance"] = next((i for i in items_in_loc_models if hasattr(i, 'template_id') and i.template_id == nlu_item_tpl_id), None)

        if not item_to_pickup_model or not hasattr(item_to_pickup_model, 'id'):
            await interaction.followup.send(get_localized_string(key="pickup_error_item_not_seen_here_nlu", lang=language, default_lang=DEFAULT_BOT_LANGUAGE).format(item_name_nlu=nlu_item_name), ephemeral=True); return

        item_instance_id = str(item_to_pickup_model.id)
        quantity_to_pickup = float(getattr(item_to_pickup_model, 'quantity', 1.0))
        char_id = getattr(character, 'id', None)
        if not char_id:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character_id", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return


        pickup_success = await item_mgr.transfer_item_world_to_character(guild_id_str, str(char_id), item_instance_id, int(quantity_to_pickup))

        if pickup_success:
            msg = get_localized_string(key="pickup_success_message", lang=language, default_lang=DEFAULT_BOT_LANGUAGE).format(user_mention=interaction.user.mention, item_name_display=nlu_item_name, quantity=int(quantity_to_pickup))
            await interaction.followup.send(msg, ephemeral=False)
        else:
            await interaction.followup.send(get_localized_string(key="pickup_error_failed", lang=language, default_lang=DEFAULT_BOT_LANGUAGE).format(item_name=nlu_item_name), ephemeral=True)


    @app_commands.command(name="equip", description="Equip an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to equip.", slot_preference="Optional: preferred slot (e.g., 'main_hand', 'off_hand')")
    async def cmd_equip(self, interaction: Interaction, item_name: str, slot_preference: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)

        char_manager: Optional["CharacterManager"] = None
        item_mgr: Optional["ItemManager"] = None
        rl_engine: Optional["RuleEngine"] = None

        if game_mngr:
            char_manager = cast("CharacterManager", getattr(game_mngr, 'character_manager', None))
            item_mgr = cast("ItemManager", getattr(game_mngr, 'item_manager', None))
            rl_engine = cast("RuleEngine", getattr(game_mngr, 'rule_engine', None))

        if not game_mngr or not char_manager or not item_mgr or not rl_engine:
            early_lang = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_localized_string(key="inventory_error_services_not_init", lang=early_lang, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)
        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service unavailable.", ephemeral=True); return

        rules_config: Optional[CoreGameRulesConfig] = None
        if hasattr(rl_engine, 'get_core_rules_config_for_guild') and callable(getattr(rl_engine, 'get_core_rules_config_for_guild')):
            rules_config = await rl_engine.get_core_rules_config_for_guild(guild_id_str)

        if not rules_config:
            await interaction.followup.send("Error: Game rules not loaded.", ephemeral=True); return

        character = await char_manager.get_character_by_discord_id(guild_id_str, interaction.user.id)
        language = await self._get_language(interaction, character, guild_id_str)
        if not character:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        char_id = getattr(character, 'id', None)
        if not char_id:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character_id", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        action_data: Optional[PlayerActionData] = await parse_player_action(
            text_input=item_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
        )
        nlu_item_tpl_id: Optional[str] = None
        if action_data and action_data.get('entities'):
            item_entity = next((e for e in action_data['entities'] if e.get('type') == 'item' and e.get('id')), None)
            if item_entity: nlu_item_tpl_id = str(item_entity['id'])

        if not nlu_item_tpl_id:
            await interaction.followup.send(get_localized_string(key="equip_error_item_not_understood", lang=language, default_lang=DEFAULT_BOT_LANGUAGE).format(item_name=item_name), ephemeral=True); return

        equip_result: EquipResult = await item_mgr.equip_item(str(char_id), guild_id_str, nlu_item_tpl_id, rules_config, slot_preference)
        await interaction.followup.send(equip_result['message'], ephemeral=not equip_result['success'])


    @app_commands.command(name="unequip", description="Unequip an item.")
    @app_commands.describe(slot_or_item_name="The equipment slot (e.g. 'main_hand') or item name to unequip.")
    async def cmd_unequip(self, interaction: Interaction, slot_or_item_name: str):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)

        char_manager: Optional["CharacterManager"] = None
        item_mgr: Optional["ItemManager"] = None
        rl_engine: Optional["RuleEngine"] = None

        if game_mngr:
            char_manager = cast("CharacterManager", getattr(game_mngr, 'character_manager', None))
            item_mgr = cast("ItemManager", getattr(game_mngr, 'item_manager', None))
            rl_engine = cast("RuleEngine", getattr(game_mngr, 'rule_engine', None))


        if not game_mngr or not char_manager or not item_mgr or not rl_engine:
            early_lang = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_localized_string(key="inventory_error_services_not_init", lang=early_lang, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)
        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service unavailable.", ephemeral=True); return

        rules_config: Optional[CoreGameRulesConfig] = None
        if hasattr(rl_engine, 'get_core_rules_config_for_guild') and callable(getattr(rl_engine, 'get_core_rules_config_for_guild')):
            rules_config = await rl_engine.get_core_rules_config_for_guild(guild_id_str)

        if not rules_config:
            await interaction.followup.send("Error: Game rules not loaded.", ephemeral=True); return

        character = await char_manager.get_character_by_discord_id(guild_id_str, interaction.user.id)
        language = await self._get_language(interaction, character, guild_id_str)
        if not character:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        char_id = getattr(character, 'id', None)
        if not char_id:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character_id", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return


        slot_to_unequip: Optional[str] = None; item_template_id_to_unequip: Optional[str] = None # Defined here
        normalized_input = slot_or_item_name.lower().replace(" ", "_")

        current_equipment_slots: Dict[str, Any] = {}
        if rules_config and hasattr(rules_config, 'equipment_slots') and isinstance(rules_config.equipment_slots, dict):
            current_equipment_slots = rules_config.equipment_slots

        if current_equipment_slots and normalized_input in current_equipment_slots:
            slot_to_unequip = normalized_input
        else:
            action_data: Optional[PlayerActionData] = await parse_player_action(
                text_input=slot_or_item_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
            )
            if action_data and action_data.get('entities'):
                item_entity = next((e for e in action_data['entities'] if e.get('type') == 'item' and e.get('id')), None)
                if item_entity: item_template_id_to_unequip = str(item_entity['id'])
            if not item_template_id_to_unequip: # Check after attempting NLU
                await interaction.followup.send(get_localized_string(key="unequip_error_not_understood", lang=language, default_lang=DEFAULT_BOT_LANGUAGE).format(name=slot_or_item_name), ephemeral=True); return

        unequip_result: EquipResult = await item_mgr.unequip_item(str(char_id), guild_id_str, rules_config, item_template_id_to_unequip, slot_to_unequip)
        await interaction.followup.send(unequip_result['message'], ephemeral=not unequip_result['success'])


    @app_commands.command(name="drop", description="Drop an item from your inventory to the ground.")
    @app_commands.describe(item_name="The name of the item you want to drop.")
    async def cmd_drop(self, interaction: Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)

        char_manager: Optional["CharacterManager"] = None
        item_mgr: Optional["ItemManager"] = None
        # loc_manager: Optional["LocationManager"] = None # For placing item in world

        if game_mngr:
            char_manager = cast("CharacterManager", getattr(game_mngr, 'character_manager', None))
            item_mgr = cast("ItemManager", getattr(game_mngr, 'item_manager', None))
            # loc_manager = cast("LocationManager", getattr(game_mngr, 'location_manager', None))

        if not game_mngr or not char_manager or not item_mgr : # Removed loc_manager for now
            early_lang = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_localized_string(key="inventory_error_services_not_init", lang=early_lang, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)
        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service unavailable.", ephemeral=True); return

        character = await char_manager.get_character_by_discord_id(guild_id_str, interaction.user.id)
        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        char_id = getattr(character, 'id', None)
        char_location_id = getattr(character, 'location_id', None)

        if not char_id or not char_location_id:
            await interaction.followup.send(get_localized_string(key="drop_error_character_details_missing", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        action_data: Optional[PlayerActionData] = await parse_player_action(
            text_input=item_name, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
        )
        nlu_item_tpl_id: Optional[str] = None; nlu_item_name_display: str = item_name
        if action_data and action_data.get('entities'):
            item_entity = next((e for e in action_data['entities'] if e.get('type') == 'item' and e.get('id')), None)
            if item_entity:
                nlu_item_tpl_id = str(item_entity['id'])
                nlu_item_name_display = str(item_entity.get('name', item_name))

        if not nlu_item_tpl_id:
            error_msg_format = get_localized_string(key="drop_error_item_not_understood", lang=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(error_msg_format.format(item_name=item_name), ephemeral=True); return

        # Placeholder for quantity, assuming 1 for now. NLU could enhance this.
        quantity_to_drop = 1

        drop_success = await item_mgr.transfer_item_character_to_world(guild_id_str, str(char_id), nlu_item_tpl_id, quantity_to_drop, str(char_location_id))

        if drop_success:
            msg_format = get_localized_string(key="drop_success_message", lang=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(msg_format.format(user_mention=interaction.user.mention, item_name_display=nlu_item_name_display, quantity=quantity_to_drop), ephemeral=False)
        else:
            msg_format = get_localized_string(key="drop_error_failed", lang=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(msg_format.format(item_name=nlu_item_name_display), ephemeral=True)


    @app_commands.command(name="use", description="Use an item from your inventory.")
    @app_commands.describe(item_name="The name of the item you want to use.", target_name="Optional: the name of the target (e.g., another character).")
    async def cmd_use_item(self, interaction: Interaction, item_name: str, target_name: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id) if interaction.guild_id else ""
        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)

        char_manager: Optional["CharacterManager"] = None
        item_mgr: Optional["ItemManager"] = None
        rl_engine: Optional["RuleEngine"] = None
        # loc_manager: Optional["LocationManager"] = None # For target resolution

        if game_mngr:
            char_manager = cast("CharacterManager", getattr(game_mngr, 'character_manager', None))
            item_mgr = cast("ItemManager", getattr(game_mngr, 'item_manager', None))
            rl_engine = cast("RuleEngine", getattr(game_mngr, 'rule_engine', None))
            # loc_manager = cast("LocationManager", getattr(game_mngr, 'location_manager', None))

        if not game_mngr or not char_manager or not item_mgr or not rl_engine:
            early_lang = str(interaction.locale) if interaction.locale else DEFAULT_BOT_LANGUAGE
            await interaction.followup.send(get_localized_string(key="inventory_error_services_not_init", lang=early_lang, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        nlu_data_service: Optional["NLUDataService"] = getattr(self.bot, "nlu_data_service", None)
        if not nlu_data_service:
            await interaction.followup.send("Error: NLU service unavailable.", ephemeral=True); return

        rules_config: Optional[CoreGameRulesConfig] = None
        if hasattr(rl_engine, 'get_core_rules_config_for_guild') and callable(getattr(rl_engine, 'get_core_rules_config_for_guild')):
            rules_config = await rl_engine.get_core_rules_config_for_guild(guild_id_str)

        if not rules_config:
            await interaction.followup.send("Error: Game rules not loaded for guild.", ephemeral=True); return

        character = await char_manager.get_character_by_discord_id(guild_id_str, interaction.user.id)
        language = await self._get_language(interaction, character, guild_id_str)

        if not character:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        char_id = getattr(character, 'id', None)
        if not char_id:
            await interaction.followup.send(get_localized_string(key="inventory_error_no_character_id", lang=language, default_lang=DEFAULT_BOT_LANGUAGE), ephemeral=True); return

        # Parse item and target from input
        # For simplicity, assume item_name is primary NLU focus for item_id
        # Target resolution would be more complex (NPC, another player, self)

        action_text_for_item = item_name
        if target_name:
            action_text_for_item += f" on {target_name}" # Basic concatenation for NLU

        action_data: Optional[PlayerActionData] = await parse_player_action(
            text_input=action_text_for_item, language=language, guild_id=guild_id_str, nlu_data_service=nlu_data_service
        )

        nlu_item_tpl_id: Optional[str] = None
        nlu_target_id: Optional[str] = None
        nlu_target_type: Optional[str] = None # e.g., "character", "npc"

        if action_data and action_data.get('entities'):
            for entity in action_data['entities']:
                entity_id_val = entity.get('id')
                if entity_id_val is None: continue

                if entity.get('type') == 'item' and not nlu_item_tpl_id:
                    nlu_item_tpl_id = str(entity_id_val)
                elif entity.get('type') in ['character', 'npc'] and not nlu_target_id: # Prioritize first non-item entity as target
                    nlu_target_id = str(entity_id_val)
                    nlu_target_type = str(entity.get('type'))

        if not nlu_item_tpl_id:
            msg_format = get_localized_string(key="use_error_item_not_understood", lang=language, default_lang=DEFAULT_BOT_LANGUAGE)
            await interaction.followup.send(msg_format.format(item_name=item_name), ephemeral=True); return

        # If no target identified by NLU but target_name was provided, could try a direct name lookup here (future enhancement)
        # For now, if NLU doesn't find a target, it's None.
        # If target_name is provided but NLU doesn't identify it, it means NLU couldn't match it to a known entity.

        use_result = await item_mgr.use_item(
            character_user=interaction.user, # Pass discord.User
            character_id=str(char_id),
            guild_id=guild_id_str,
            item_template_id=nlu_item_tpl_id,
            rules_config=rules_config,
            target_entity_id=nlu_target_id,
            target_entity_type=nlu_target_type
        )

        response_message = use_result.get("message", get_localized_string(key="use_error_generic", lang=language, default_lang=DEFAULT_BOT_LANGUAGE))
        is_successful_use = use_result.get("success", False)

        await interaction.followup.send(response_message, ephemeral=not is_successful_use)


async def setup(bot: "RPGBot"):
    await bot.add_cog(InventoryCog(bot))
    logging.info("InventoryCog loaded.")
