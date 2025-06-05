from bot.utils.validation_utils import is_uuid_format
from typing import List, Dict, Any, Optional
from discord import Message
# Assuming is_uuid_format might be needed if any of these commands take UUIDs for targets.
# For now, it's not directly used by the moved logic but kept for potential future use.

async def handle_move_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Перемещает персонажа. Usage: {prefix}move <location_id>"""
    send_callback = context['send_to_command_channel']
    char_action_processor = context.get('character_action_processor')
    char_manager = context.get('character_manager')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    command_prefix = context.get('command_prefix', '/')

    if not char_action_processor or not char_manager or not guild_id or not author_id_str:
        await send_callback("Error: Required systems for movement are unavailable.")
        print("ActionCommands: Missing managers/processors for handle_move_command.")
        return

    if not args:
        await send_callback(f"Usage: {command_prefix}move <destination>")
        return

    destination_input = args[0]

    try:
        # get_character_by_discord_id is sync in CharacterManager
        player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
        if not player_char:
            await send_callback(f"You do not have an active character. Use `{command_prefix}character create <name>`.")
            return

        action_data = {"destination": destination_input}
        # process_action in CharacterActionProcessor is async
        result = await char_action_processor.process_action(
            character_id=player_char.id,
            action_type="move",
            action_data=action_data,
            context=context
        )
        # CharacterActionProcessor is expected to send messages.
        if not result or not result.get("success"):
            print(f"ActionCommands: handle_move_command result: {result}")

    except ValueError:
        await send_callback("Invalid user ID format.")
    except Exception as e:
        print(f"ActionCommands: Error in handle_move_command for destination '{destination_input}': {e}")
        # import traceback; traceback.print_exc() # For debugging
        await send_callback(f"An error occurred while trying to move: {e}")

async def handle_fight_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Initiates combat with a target NPC. Usage: {prefix}fight <target_npc_id_or_name>"""
    send_callback = context.get('send_to_command_channel')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    channel_id = message.channel.id
    command_prefix = context.get('command_prefix', '/')

    if not send_callback: return
    if not guild_id:
        await send_callback("The /fight command can only be used on a server.")
        return
    if not author_id_str:
        await send_callback("Could not identify your user ID.")
        return
    if not args:
        await send_callback(f"Usage: {command_prefix}fight <target_npc_id_or_name>")
        return

    target_identifier = args[0]
    char_manager = context.get('character_manager')
    npc_manager = context.get('npc_manager')
    loc_manager = context.get('location_manager')
    combat_manager = context.get('combat_manager')
    rule_engine = context.get('rule_engine')

    if not all([char_manager, npc_manager, loc_manager, combat_manager, rule_engine]):
        await send_callback("Error: Required game systems for combat are unavailable.")
        print("ActionCommands: Missing one or more managers for handle_fight_command.")
        return

    try:
        player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
        if not player_char:
            await send_callback(f"You do not have an active character. Use `{command_prefix}character create <name>`.")
            return

        character_id = player_char.id
        current_location_id = getattr(player_char, 'current_location_id', None)
        if not current_location_id:
            await send_callback("Your character isn't in a location where combat can occur.")
            return

        target_npc = npc_manager.get_npc(guild_id, target_identifier)
        if not target_npc:
            if hasattr(npc_manager, 'get_npc_by_name'):
                target_npc = npc_manager.get_npc_by_name(guild_id, target_identifier)
            if not target_npc:
                await send_callback(f"NPC '{target_identifier}' not found.")
                return

        target_npc_id = target_npc.id
        target_npc_name = getattr(target_npc, 'name', target_identifier)
        npc_location_id = getattr(target_npc, 'location_id', None)

        if npc_location_id != current_location_id:
            player_loc_name = loc_manager.get_location_name(guild_id, current_location_id) if current_location_id else "an unknown place"
            npc_loc_name = loc_manager.get_location_name(guild_id, npc_location_id) if npc_location_id else "an unknown place"
            await send_callback(f"{target_npc_name} is not here. You are in {player_loc_name}, and they are in {npc_loc_name}.")
            return

        if combat_manager.get_combat_by_participant_id(guild_id, character_id):
            await send_callback("You are already in combat!")
            return
        if combat_manager.get_combat_by_participant_id(guild_id, target_npc_id):
            await send_callback(f"{target_npc_name} is already in combat with someone else.")
            return

        participant_ids = [(character_id, "Character"), (target_npc_id, "NPC")]
        new_combat_instance = await combat_manager.start_combat(
            guild_id=guild_id,
            location_id=current_location_id,
            participant_ids=participant_ids,
            channel_id=channel_id,
            **context
        )
        if not new_combat_instance:
            await send_callback(f"Could not start combat with {target_npc_name}. They might be too powerful, or something went wrong.")
        # CombatManager.start_combat is expected to send the initial combat message.
    except ValueError:
        await send_callback("Invalid user ID format.")
    except Exception as e:
        print(f"ActionCommands: Error in handle_fight_command against '{target_identifier}': {e}")
        await send_callback(f"An error occurred while trying to initiate combat: {e}")

async def handle_hide_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Allows the player to attempt to hide in their current location. Usage: {prefix}hide"""
    send_callback = context.get('send_to_command_channel')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    command_prefix = context.get('command_prefix', '/')

    if not send_callback: return
    if not guild_id:
        await send_callback("The /hide command can only be used on a server.")
        return
    if not author_id_str:
        await send_callback("Could not identify your user ID.")
        return

    char_manager = context.get('character_manager')
    char_action_processor = context.get('character_action_processor')

    if not char_manager or not char_action_processor:
        await send_callback("Error: Required game systems are unavailable.")
        print("ActionCommands: Missing managers/processors for handle_hide_command.")
        return

    try:
        player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
        if not player_char:
            await send_callback(f"You do not have an active character. Use `{command_prefix}character create <name>`.")
            return

        # process_hide_action is async
        success = await char_action_processor.process_hide_action(
            character_id=player_char.id,
            context=context
        )
        if not success:
             print(f"ActionCommands: process_hide_action returned False for char {player_char.id}")
    except ValueError:
        await send_callback("Invalid user ID format.")
    except Exception as e:
        print(f"ActionCommands: Error in handle_hide_command: {e}")
        await send_callback(f"An error occurred while trying to hide: {e}")

async def handle_steal_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Allows the player to attempt to steal from a target NPC. Usage: {prefix}steal <target_npc_id_or_name>"""
    send_callback = context.get('send_to_command_channel')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    command_prefix = context.get('command_prefix', '/')

    if not send_callback: return
    if not guild_id:
        await send_callback("The /steal command can only be used on a server.")
        return
    if not author_id_str:
        await send_callback("Could not identify your user ID.")
        return
    if not args:
        await send_callback(f"Usage: {command_prefix}steal <target_npc_id_or_name>")
        return

    target_identifier = args[0]
    char_manager = context.get('character_manager')
    npc_manager = context.get('npc_manager')
    char_action_processor = context.get('character_action_processor')
    loc_manager = context.get('location_manager')

    if not all([char_manager, npc_manager, char_action_processor, loc_manager]):
        await send_callback("Error: Required game systems are unavailable.")
        print("ActionCommands: Missing managers/processors for handle_steal_command.")
        return

    try:
        player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
        if not player_char:
            await send_callback(f"You do not have an active character. Use `{command_prefix}character create <name>`.")
            return

        target_npc = npc_manager.get_npc(guild_id, target_identifier)
        if not target_npc:
            if hasattr(npc_manager, 'get_npc_by_name'):
                target_npc = npc_manager.get_npc_by_name(guild_id, target_identifier)
            if not target_npc:
                await send_callback(f"NPC '{target_identifier}' not found.")
                return

        target_npc_name = getattr(target_npc, 'name', target_identifier)
        player_loc_id = getattr(player_char, 'current_location_id', None)
        target_loc_id = getattr(target_npc, 'location_id', None)

        if not player_loc_id:
            await send_callback("You don't seem to be in any location.")
            return
        if player_loc_id != target_loc_id:
            await send_callback(f"{target_npc_name} is not in your current location.")
            return

        # process_steal_action is async
        success = await char_action_processor.process_steal_action(
            character_id=player_char.id,
            target_id=target_npc.id,
            target_type="NPC",
            context=context
        )
        if not success:
            print(f"ActionCommands: process_steal_action returned False for char {player_char.id} target {target_npc.id}")

    except ValueError:
        await send_callback("Invalid user ID format.")
    except Exception as e:
        print(f"ActionCommands: Error in handle_steal_command for target '{target_identifier}': {e}")
        await send_callback(f"An error occurred while trying to steal: {e}")

async def handle_use_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Allows the player to use an item from their inventory, optionally on a target. Usage: {prefix}use <item_instance_id> [target_id]"""
    send_callback = context.get('send_to_command_channel')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    command_prefix = context.get('command_prefix', '/')

    if not send_callback: return
    if not guild_id:
        await send_callback("The /use command can only be used on a server.")
        return
    if not author_id_str:
        await send_callback("Could not identify your user ID.")
        return
    if not args:
        await send_callback(f"Usage: {command_prefix}use <item_instance_id> [target_id]")
        return

    item_instance_id = args[0]
    target_id: Optional[str] = args[1] if len(args) > 1 else None
    target_type: Optional[str] = None

    char_manager = context.get('character_manager')
    char_action_processor = context.get('character_action_processor')
    npc_manager = context.get('npc_manager')

    if not all([char_manager, char_action_processor, npc_manager]):
        await send_callback("Error: Required game systems are unavailable.")
        print("ActionCommands: Missing managers/processors for handle_use_command.")
        return

    try:
        player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
        if not player_char:
            await send_callback(f"You do not have an active character. Use `{command_prefix}character create <name>`.")
            return
        character_id = player_char.id

        if target_id:
            if target_id.lower() == "self" or target_id == character_id:
                target_id = character_id
                target_type = "Character"
            elif npc_manager.get_npc(guild_id, target_id):
                target_type = "NPC"
            elif char_manager.get_character(guild_id, target_id):
                target_type = "Character"
            else:
                print(f"ActionCommands: Target '{target_id}' for /use not identified as self, NPC, or Character.")

        # process_use_item_action is async
        success = await char_action_processor.process_use_item_action(
            character_id=character_id,
            item_instance_id=item_instance_id,
            target_id=target_id,
            target_type=target_type,
            context=context
        )
        if not success:
            print(f"ActionCommands: process_use_item_action returned False for char {character_id} item {item_instance_id}")

    except ValueError:
        await send_callback("Invalid user ID format.")
    except Exception as e:
        print(f"ActionCommands: Error in handle_use_command for item '{item_instance_id}': {e}")
        await send_callback(f"An error occurred while trying to use the item: {e}")
