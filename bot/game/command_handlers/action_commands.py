from bot.utils.validation_utils import is_uuid_format
from typing import List, Dict, Any, Optional, TYPE_CHECKING, cast
from discord import Message

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    # from bot.game.rules.rule_engine import RuleEngine # Not directly used in this file's logic after review

async def handle_move_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    send_callback = context.get('send_to_command_channel')
    if not send_callback or not callable(send_callback): return # Basic check

    char_action_proc: Optional["CharacterActionProcessor"] = cast(Optional["CharacterActionProcessor"], context.get('character_action_processor'))
    char_mgr: Optional["CharacterManager"] = cast(Optional["CharacterManager"], context.get('character_manager'))
    guild_id: Optional[str] = cast(Optional[str], context.get('guild_id'))
    author_id_str: Optional[str] = cast(Optional[str], context.get('author_id'))
    cmd_prefix: str = cast(str, context.get('command_prefix', '/'))

    if not char_action_proc or not char_mgr or not guild_id or not author_id_str:
        await send_callback("Error: Movement systems unavailable.")
        print("ActionCommands: Missing context for handle_move_command.")
        return

    if not args: await send_callback(f"Usage: {cmd_prefix}move <destination>"); return
    destination_input = args[0]

    try:
        author_id_int = int(author_id_str)
        player_char = await char_mgr.get_character_by_discord_id(guild_id, author_id_int) # Assume async
        if not player_char or not hasattr(player_char, 'id'):
            await send_callback(f"No active character. Use `{cmd_prefix}character create <name>`."); return

        action_data = {"destination": destination_input}
        if hasattr(char_action_proc, 'process_action') and callable(getattr(char_action_proc, 'process_action')):
            result = await char_action_proc.process_action(str(player_char.id), "move", action_data, context)
            if not result or not result.get("success"): print(f"ActionCommands: handle_move_command result: {result}")
        else: await send_callback("Error: Action processing unavailable."); print("ActionCommands: char_action_proc.process_action missing.")
    except ValueError: await send_callback("Invalid user ID.")
    except Exception as e: print(f"ActionCommands: Error in move '{destination_input}': {e}"); await send_callback(f"Error moving: {e}")

async def handle_fight_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    send_callback = context.get('send_to_command_channel')
    if not send_callback or not callable(send_callback): return

    guild_id: Optional[str] = cast(Optional[str], context.get('guild_id'))
    author_id_str: Optional[str] = cast(Optional[str], context.get('author_id'))
    channel_id = message.channel.id
    cmd_prefix: str = cast(str, context.get('command_prefix', '/'))

    if not guild_id: await send_callback("Use /fight on a server."); return
    if not author_id_str: await send_callback("Could not ID user."); return
    if not args: await send_callback(f"Usage: {cmd_prefix}fight <target>"); return
    target_identifier = args[0]

    char_mgr: Optional["CharacterManager"] = cast(Optional["CharacterManager"], context.get('character_manager'))
    npc_mgr: Optional["NpcManager"] = cast(Optional["NpcManager"], context.get('npc_manager'))
    loc_mgr: Optional["LocationManager"] = cast(Optional["LocationManager"], context.get('location_manager'))
    combat_mgr: Optional["CombatManager"] = cast(Optional["CombatManager"], context.get('combat_manager'))
    # rule_eng: Optional["RuleEngine"] = context.get('rule_engine') # Not directly used here

    if not all([char_mgr, npc_mgr, loc_mgr, combat_mgr]):
        await send_callback("Error: Combat systems unavailable."); print("ActionCommands: Missing managers for handle_fight_command."); return

    try:
        author_id_int = int(author_id_str)
        player_char = await char_mgr.get_character_by_discord_id(guild_id, author_id_int) # Assume async
        if not player_char or not hasattr(player_char, 'id'): await send_callback(f"No active character."); return

        char_id = str(player_char.id)
        current_loc_id = str(getattr(player_char, 'location_id', None)) # Was current_location_id
        if not current_loc_id: await send_callback("Character not in a location."); return

        target_npc = None
        if hasattr(npc_mgr, 'get_npc') and callable(getattr(npc_mgr, 'get_npc')):
            target_npc = await npc_mgr.get_npc(guild_id, target_identifier) # Assume async
        if not target_npc and hasattr(npc_mgr, 'get_npc_by_name') and callable(getattr(npc_mgr, 'get_npc_by_name')):
            target_npc = await npc_mgr.get_npc_by_name(guild_id, target_identifier) # Assume async
        if not target_npc or not hasattr(target_npc, 'id'): await send_callback(f"NPC '{target_identifier}' not found."); return

        target_npc_id = str(target_npc.id)
        target_npc_name = str(getattr(target_npc, 'name', target_identifier))
        npc_loc_id = str(getattr(target_npc, 'location_id', None))

        if npc_loc_id != current_loc_id:
            player_loc_name = "unknown"
            npc_loc_name = "unknown"
            if hasattr(loc_mgr, 'get_location_name') and callable(getattr(loc_mgr, 'get_location_name')):
                 player_loc_name = await loc_mgr.get_location_name(guild_id, current_loc_id) or player_loc_name # Assume async
                 npc_loc_name = await loc_mgr.get_location_name(guild_id, npc_loc_id) or npc_loc_name # Assume async
            await send_callback(f"{target_npc_name} not here. You: {player_loc_name}, Them: {npc_loc_name}."); return

        if hasattr(combat_mgr, 'get_combat_by_participant_id') and callable(getattr(combat_mgr, 'get_combat_by_participant_id')):
            if await combat_mgr.get_combat_by_participant_id(guild_id, char_id): # Assume async
                await send_callback("You are already in combat!"); return
            if await combat_mgr.get_combat_by_participant_id(guild_id, target_npc_id): # Assume async
                await send_callback(f"{target_npc_name} is already in combat."); return
        else: await send_callback("Combat check unavailable."); return


        participant_ids = [(char_id, "Character"), (target_npc_id, "NPC")]
        if hasattr(combat_mgr, 'start_combat') and callable(getattr(combat_mgr, 'start_combat')):
            new_combat = await combat_mgr.start_combat(guild_id, current_loc_id, participant_ids, channel_id, **context)
            if not new_combat: await send_callback(f"Could not start combat with {target_npc_name}.")
        else: await send_callback("Combat starting system unavailable."); return
    except ValueError: await send_callback("Invalid user ID.")
    except Exception as e: print(f"ActionCommands: Error in fight '{target_identifier}': {e}"); await send_callback(f"Error starting combat: {e}")


async def handle_hide_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    send_callback = context.get('send_to_command_channel')
    if not send_callback or not callable(send_callback): return
    guild_id: Optional[str] = cast(Optional[str], context.get('guild_id'))
    author_id_str: Optional[str] = cast(Optional[str], context.get('author_id'))
    cmd_prefix: str = cast(str, context.get('command_prefix', '/'))

    if not guild_id: await send_callback("Use /hide on a server."); return
    if not author_id_str: await send_callback("Could not ID user."); return

    char_mgr: Optional["CharacterManager"] = cast(Optional["CharacterManager"], context.get('character_manager'))
    char_action_proc: Optional["CharacterActionProcessor"] = cast(Optional["CharacterActionProcessor"], context.get('character_action_processor'))

    if not char_mgr or not char_action_proc or \
       not hasattr(char_action_proc, 'process_hide_action') or not callable(getattr(char_action_proc, 'process_hide_action')):
        await send_callback("Error: Hiding systems unavailable."); print("ActionCommands: Missing context for handle_hide_command."); return

    try:
        author_id_int = int(author_id_str)
        player_char = await char_mgr.get_character_by_discord_id(guild_id, author_id_int) # Assume async
        if not player_char or not hasattr(player_char, 'id'): await send_callback(f"No active character."); return

        success = await char_action_proc.process_hide_action(str(player_char.id), context)
        if not success: print(f"ActionCommands: process_hide_action False for char {player_char.id}")
    except ValueError: await send_callback("Invalid user ID.")
    except Exception as e: print(f"ActionCommands: Error in hide: {e}"); await send_callback(f"Error hiding: {e}")

async def handle_steal_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    send_callback = context.get('send_to_command_channel')
    if not send_callback or not callable(send_callback): return
    guild_id: Optional[str] = cast(Optional[str], context.get('guild_id'))
    author_id_str: Optional[str] = cast(Optional[str], context.get('author_id'))
    cmd_prefix: str = cast(str, context.get('command_prefix', '/'))

    if not guild_id: await send_callback("Use /steal on a server."); return
    if not author_id_str: await send_callback("Could not ID user."); return
    if not args: await send_callback(f"Usage: {cmd_prefix}steal <target>"); return
    target_identifier = args[0]

    char_mgr: Optional["CharacterManager"] = cast(Optional["CharacterManager"], context.get('character_manager'))
    npc_mgr: Optional["NpcManager"] = cast(Optional["NpcManager"], context.get('npc_manager'))
    char_action_proc: Optional["CharacterActionProcessor"] = cast(Optional["CharacterActionProcessor"], context.get('character_action_processor'))

    if not all([char_mgr, npc_mgr, char_action_proc]) or \
       not hasattr(char_action_proc, 'process_steal_action') or not callable(getattr(char_action_proc, 'process_steal_action')):
        await send_callback("Error: Stealing systems unavailable."); print("ActionCommands: Missing context for handle_steal_command."); return

    try:
        author_id_int = int(author_id_str)
        player_char = await char_mgr.get_character_by_discord_id(guild_id, author_id_int) # Assume async
        if not player_char or not hasattr(player_char, 'id'): await send_callback(f"No active character."); return

        target_npc = None
        if hasattr(npc_mgr, 'get_npc') and callable(getattr(npc_mgr, 'get_npc')):
            target_npc = await npc_mgr.get_npc(guild_id, target_identifier) # Assume async
        if not target_npc and hasattr(npc_mgr, 'get_npc_by_name') and callable(getattr(npc_mgr, 'get_npc_by_name')):
            target_npc = await npc_mgr.get_npc_by_name(guild_id, target_identifier) # Assume async
        if not target_npc or not hasattr(target_npc, 'id'): await send_callback(f"NPC '{target_identifier}' not found."); return

        target_npc_name = str(getattr(target_npc, 'name', target_identifier))
        player_loc_id = str(getattr(player_char, 'location_id', None))
        target_loc_id = str(getattr(target_npc, 'location_id', None))

        if not player_loc_id: await send_callback("You are not in a location."); return
        if player_loc_id != target_loc_id: await send_callback(f"{target_npc_name} is not here."); return

        success = await char_action_proc.process_steal_action(str(player_char.id), str(target_npc.id), "NPC", context)
        if not success: print(f"ActionCommands: process_steal_action False for char {player_char.id} target {target_npc.id}")
    except ValueError: await send_callback("Invalid user ID.")
    except Exception as e: print(f"ActionCommands: Error in steal '{target_identifier}': {e}"); await send_callback(f"Error stealing: {e}")

async def handle_use_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    send_callback = context.get('send_to_command_channel')
    if not send_callback or not callable(send_callback): return
    guild_id: Optional[str] = cast(Optional[str], context.get('guild_id'))
    author_id_str: Optional[str] = cast(Optional[str], context.get('author_id'))
    cmd_prefix: str = cast(str, context.get('command_prefix', '/'))

    if not guild_id: await send_callback("Use /use on a server."); return
    if not author_id_str: await send_callback("Could not ID user."); return
    if not args: await send_callback(f"Usage: {cmd_prefix}use <item_id> [target_id]"); return
    item_instance_id = args[0]
    target_id_param: Optional[str] = args[1] if len(args) > 1 else None

    char_mgr: Optional["CharacterManager"] = cast(Optional["CharacterManager"], context.get('character_manager'))
    char_action_proc: Optional["CharacterActionProcessor"] = cast(Optional["CharacterActionProcessor"], context.get('character_action_processor'))
    npc_mgr: Optional["NpcManager"] = cast(Optional["NpcManager"], context.get('npc_manager'))

    if not all([char_mgr, char_action_proc, npc_mgr]) or \
       not hasattr(char_action_proc, 'process_use_item_action') or not callable(getattr(char_action_proc, 'process_use_item_action')):
        await send_callback("Error: Item use systems unavailable."); print("ActionCommands: Missing context for handle_use_command."); return

    try:
        author_id_int = int(author_id_str)
        player_char = await char_mgr.get_character_by_discord_id(guild_id, author_id_int) # Assume async
        if not player_char or not hasattr(player_char, 'id'): await send_callback(f"No active character."); return
        char_id = str(player_char.id)

        final_target_id: Optional[str] = None
        final_target_type: Optional[str] = None
        if target_id_param:
            if target_id_param.lower() == "self" or target_id_param == char_id:
                final_target_id = char_id; final_target_type = "Character"
            elif hasattr(npc_mgr, 'get_npc') and callable(getattr(npc_mgr, 'get_npc')) and await npc_mgr.get_npc(guild_id, target_id_param): # Assume async
                final_target_id = target_id_param; final_target_type = "NPC"
            elif hasattr(char_mgr, 'get_character') and callable(getattr(char_mgr, 'get_character')) and await char_mgr.get_character(guild_id, target_id_param): # Assume async
                final_target_id = target_id_param; final_target_type = "Character"
            else: print(f"ActionCommands: Target '{target_id_param}' for /use not identified.")

        success = await char_action_proc.process_use_item_action(char_id, item_instance_id, final_target_id, final_target_type, context)
        if not success: print(f"ActionCommands: process_use_item_action False for char {char_id} item {item_instance_id}")
    except ValueError: await send_callback("Invalid user ID.")
    except Exception as e: print(f"ActionCommands: Error in use '{item_instance_id}': {e}"); await send_callback(f"Error using item: {e}")
