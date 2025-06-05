from bot.utils.validation_utils import is_uuid_format
from typing import List, Dict, Any, Optional
from discord import Message
# import traceback # For debugging if needed

async def handle_npc_talk_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Initiates a dialogue with an NPC. Usage: {prefix}npc talk <npc_id_or_name> [initial_message]"""
    send_callback = context.get('send_to_command_channel')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    channel_id = message.channel.id # Using message's channel for dialogue
    command_prefix = context.get('command_prefix', '/')

    if not send_callback: return
    if not guild_id:
        await send_callback("NPC commands can only be used on a server.")
        return
    if not author_id_str:
        await send_callback("Could not identify your user ID.")
        return

    if not args:
        await send_callback(f"Usage: {command_prefix}npc talk <npc_id_or_name> [initial_message]")
        return

    npc_identifier = args[0]
    initiator_message = " ".join(args[1:]) if len(args) > 1 else None

    char_manager = context.get('character_manager')
    npc_manager = context.get('npc_manager')
    dialogue_manager = context.get('dialogue_manager')
    location_manager = context.get('location_manager')

    if not all([char_manager, npc_manager, dialogue_manager, location_manager]):
        await send_callback("Error: Required game systems for NPC interaction are unavailable.")
        print("InteractionCommands: Missing one or more managers for handle_npc_talk_command.")
        return

    try:
        player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
        if not player_char:
            await send_callback(f"You need an active character. Use `{command_prefix}character create <name>`.")
            return

        target_npc = npc_manager.get_npc(guild_id, npc_identifier)
        if not target_npc:
            if hasattr(npc_manager, 'get_npc_by_name'):
                target_npc = npc_manager.get_npc_by_name(guild_id, npc_identifier)
            if not target_npc:
                await send_callback(f"NPC '{npc_identifier}' not found.")
                return

        npc_name = getattr(target_npc, 'name', npc_identifier)
        if hasattr(target_npc, 'name_i18n') and isinstance(target_npc.name_i18n, dict):
             npc_name = target_npc.name_i18n.get(context.get('bot_language', 'en'), npc_identifier)


        player_loc_id = getattr(player_char, 'current_location_id', None)
        npc_loc_id = getattr(target_npc, 'location_id', None)

        if player_loc_id != npc_loc_id:
            player_loc_name = location_manager.get_location_name(guild_id, player_loc_id, context.get('bot_language', 'en')) if player_loc_id else "an unknown place"
            npc_loc_name = location_manager.get_location_name(guild_id, npc_loc_id, context.get('bot_language', 'en')) if npc_loc_id else "an unknown place"
            await send_callback(f"{npc_name} is not here. You are in {player_loc_name}, and they are in {npc_loc_name}.")
            return

        dialogue_template_id = getattr(target_npc, 'dialogue_template_id', 'generic_convo')
        if not dialogue_manager.get_dialogue_template(guild_id, dialogue_template_id):
            if dialogue_manager.get_dialogue_template(guild_id, 'generic_convo'):
                dialogue_template_id = 'generic_convo'
            else:
                await send_callback(f"Sorry, no way to start a conversation with {npc_name} (missing dialogue templates).")
                return

        dialogue_id = await dialogue_manager.start_dialogue(
            guild_id=guild_id,
            template_id=dialogue_template_id,
            participant1_id=player_char.id,
            participant2_id=target_npc.id,
            channel_id=channel_id,
            initiator_message=initiator_message,
            **context
        )
        if not dialogue_id:
            await send_callback(f"Could not start a conversation with {npc_name}. They might be busy.")
    except ValueError:
        await send_callback("Invalid user ID format.")
    except Exception as e:
        print(f"InteractionCommands: Error in handle_npc_talk_command with '{npc_identifier}': {e}")
        await send_callback(f"An unexpected error occurred while trying to talk to NPC.")


async def handle_buy_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Allows the player to buy an item. Usage: {prefix}buy <item_template_id> [quantity]"""
    send_callback = context.get('send_to_command_channel')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    command_prefix = context.get('command_prefix', '/')

    if not send_callback: return
    if not guild_id:
        await send_callback("The /buy command can only be used on a server.")
        return
    if not author_id_str:
        await send_callback("Could not identify your user ID.")
        return
    if not args:
        await send_callback(f"Usage: {command_prefix}buy <item_template_id> [quantity (default 1)]")
        return

    item_template_id_to_buy = args[0]
    quantity_to_buy = 1
    if len(args) > 1:
        try:
            quantity_to_buy = int(args[1])
            if quantity_to_buy <= 0:
                await send_callback("Quantity must be a positive number.")
                return
        except ValueError:
            await send_callback("Invalid quantity. Must be a number.")
            return

    char_manager = context.get('character_manager')
    eco_manager = context.get('economy_manager')
    item_manager = context.get('item_manager')

    if not all([char_manager, eco_manager, item_manager]):
        await send_callback("Error: Required game systems for buying are unavailable.")
        print("InteractionCommands: Missing managers for handle_buy_command.")
        return

    try:
        player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
        if not player_char:
            await send_callback(f"You do not have an active character. Use `{command_prefix}character create <name>`.")
            return

        character_id = player_char.id
        current_location_id = getattr(player_char, 'current_location_id', None)
        if not current_location_id:
            await send_callback("Your character isn't in a location to buy items.")
            return

        created_item_ids = await eco_manager.buy_item(
            guild_id=guild_id,
            buyer_entity_id=character_id,
            buyer_entity_type="Character",
            location_id=current_location_id,
            item_template_id=item_template_id_to_buy,
            count=quantity_to_buy,
            **context
        )

        if created_item_ids:
            item_template = item_manager.get_item_template(guild_id, item_template_id_to_buy)
            item_name_i18n = getattr(item_template, 'name_i18n', {}) if item_template else {}
            item_name = item_name_i18n.get(context.get('bot_language', 'en'), item_template_id_to_buy) if isinstance(item_name_i18n, dict) else item_template_id_to_buy


            if len(created_item_ids) == quantity_to_buy:
                await send_callback(f"🛍️ You successfully bought {quantity_to_buy}x {item_name}!")
            elif created_item_ids:
                await send_callback(f"🛍️ You managed to buy {len(created_item_ids)}x {item_name} (requested {quantity_to_buy}).")

    except ValueError:
        await send_callback("Invalid user ID format.")
    except Exception as e:
        print(f"InteractionCommands: Error in handle_buy_command for item '{item_template_id_to_buy}': {e}")
        await send_callback(f"An error occurred while trying to buy the item: {e}")


async def handle_craft_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Allows the player to craft an item. Usage: {prefix}craft <recipe_id> [quantity]"""
    send_callback = context.get('send_to_command_channel')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    command_prefix = context.get('command_prefix', '/')

    if not send_callback: return
    if not guild_id:
        await send_callback("The /craft command can only be used on a server.")
        return
    if not author_id_str:
        await send_callback("Could not identify your user ID.")
        return
    if not args:
        await send_callback(f"Usage: {command_prefix}craft <recipe_id> [quantity (default 1)]")
        return

    recipe_id_to_craft = args[0]
    quantity_to_craft = 1
    if len(args) > 1:
        try:
            quantity_to_craft = int(args[1])
            if quantity_to_craft <= 0:
                await send_callback("Quantity must be a positive number.")
                return
        except ValueError:
            await send_callback("Invalid quantity. Must be a number.")
            return

    char_manager = context.get('character_manager')
    craft_manager = context.get('crafting_manager')

    if not char_manager or not craft_manager:
        await send_callback("Error: Required game systems for crafting are unavailable.")
        print("InteractionCommands: Missing managers for handle_craft_command.")
        return

    try:
        player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
        if not player_char:
            await send_callback(f"You do not have an active character. Use `{command_prefix}character create <name>`.")
            return

        result = await craft_manager.add_recipe_to_craft_queue(
            guild_id=guild_id,
            entity_id=player_char.id,
            entity_type="Character",
            recipe_id=recipe_id_to_craft,
            quantity=quantity_to_craft,
            context=context
        )
        if result and result.get("success"):
            await send_callback(f"🛠️ {result.get('message', 'Crafting started!')}")
        else:
            error_message = result.get('message', "Could not start crafting.") if result else "Could not start crafting."
            await send_callback(f"⚠️ {error_message}")

    except ValueError:
        await send_callback("Invalid user ID format.")
    except Exception as e:
        print(f"InteractionCommands: Error in handle_craft_command for recipe '{recipe_id_to_craft}': {e}")
        await send_callback(f"An error occurred while trying to craft: {e}")
