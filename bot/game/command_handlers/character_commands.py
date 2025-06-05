from bot.utils.validation_utils import is_uuid_format
from typing import List, Dict, Any, Optional
from discord import Message

async def handle_character_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """
    Управляет персонажами. Usage: {prefix}character <create|delete> [args]
    `{prefix}character create <name>`
    `{prefix}character delete [character_id_or_name (defaults to yours)]`
    """
    send_callback = context['send_to_command_channel']
    author_id = context['author_id']
    guild_id = context['guild_id']
    char_manager = context.get('character_manager')
    command_prefix = context.get('command_prefix', '/') # Get prefix from context

    if not char_manager:
        await send_callback("Character manager is not available.")
        return
    if not guild_id:
        await send_callback("Character commands can only be used in a server (guild).")
        return

    doc_string_template = context.get('command_docstrings', {}).get('character', "Используйте `{prefix}character <create|delete> ...`")
    # Format the docstring, ensuring the original from context is used if available,
    # otherwise use the handler's own docstring as a fallback template.
    if not doc_string_template or doc_string_template == "Используйте `{prefix}character <create|delete> ...`": # Fallback case
        doc_string_template = handle_character_command.__doc__

    doc_string = doc_string_template.format(prefix=command_prefix) if doc_string_template else "Используйте `{prefix}character <create|delete> ...`".format(prefix=command_prefix)


    if not args:
        await send_callback(f"Please specify a character action. Usage:\n{doc_string}")
        return

    subcommand = args[0].lower()
    char_args = args[1:]

    if subcommand == "create":
        if not char_args:
            await send_callback(f"Usage: {command_prefix}character create <name>")
            return
        name = char_args[0]
        creation_context = {**context, 'user_id': author_id}

        try:
            char_id = await char_manager.create_character(
                guild_id=guild_id,
                discord_id=int(author_id),
                name=name,
                **creation_context
            )
            if char_id:
                created_char = await char_manager.get_character(guild_id=guild_id, character_id=char_id)
                display_name = getattr(created_char, 'name', name)
                await send_callback(f"Character '{display_name}' (ID: {char_id}) created successfully for user {message.author.mention}!")
            else:
                await send_callback(f"Failed to create character '{name}'. It might already exist or creation failed.")
        except ValueError:
            await send_callback("Error: Invalid user ID format encountered.")
        except Exception as e:
            await send_callback(f"An error occurred while creating character '{name}': {e}")
            # import traceback # Consider if full traceback is desired here or just in main logs
            # traceback.print_exc()
            print(f"CharacterCommands: Error in handle_character_command (create): {e}")

    elif subcommand == "delete":
        character_to_delete_id_or_name = char_args[0] if char_args else author_id
        char_to_delete = None

        if is_uuid_format(character_to_delete_id_or_name):
            char_to_delete = await char_manager.get_character(guild_id, character_to_delete_id_or_name)
        elif character_to_delete_id_or_name == author_id: # Check if it's the author's ID string
            try:
                char_to_delete = await char_manager.get_character_by_discord_id(guild_id, int(author_id))
            except ValueError:
                await send_callback("Error: Invalid author ID format for deletion.")
                return
        else: # Deleting by name (requires GM or special handling not implemented here)
            await send_callback(f"Deleting characters by name requires GM permissions or is not supported in this way. Please use character ID or use `{command_prefix}character delete` to delete your own active character.")
            return

        if not char_to_delete:
            await send_callback(f"Character '{character_to_delete_id_or_name}' not found or you don't have permission to delete it.")
            return

        try:
            # Ensure char_to_delete has discord_user_id and it can be converted to int
            char_discord_id_attr = getattr(char_to_delete, 'discord_user_id', None)
            if char_discord_id_attr is None:
                await send_callback("Error: Character data is missing Discord user ID. Cannot confirm ownership.")
                return

            char_discord_id_int = int(char_discord_id_attr)
            author_discord_id_int = int(author_id) # author_id from context should be a string discord ID

            if char_discord_id_int != author_discord_id_int:
                # GM override could be added here if context['is_gm'] and char_args were used to specify a target
                await send_callback(f"You can only delete your own character. Character '{getattr(char_to_delete, 'name', 'Unknown')}' belongs to another user.")
                return
        except (ValueError, TypeError) as e:
            await send_callback(f"Error confirming character ownership due to data format issues: {e}")
            return

        try:
            deletion_context = context.copy()
            deleted_id = await char_manager.delete_character(guild_id, char_to_delete.id, **deletion_context)
            if deleted_id:
                await send_callback(f"Character '{getattr(char_to_delete, 'name', deleted_id)}' deleted successfully.")
            else:
                await send_callback(f"Failed to delete character '{getattr(char_to_delete, 'name', 'ID: '+character_to_delete_id_or_name)}'.")
        except Exception as e:
            await send_callback(f"An error occurred: {e}")
            print(f"CharacterCommands: Error in handle_character_command (delete): {e}")
    else:
        await send_callback(f"Unknown character subcommand: '{subcommand}'. Try 'create' or 'delete'. Usage:\n{doc_string}")

async def handle_status_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Показывает лист персонажа. Usage: {prefix}status [character_id_or_name]"""
    send_callback = context['send_to_command_channel']
    # Logic for displaying character status (potentially complex, involving CharacterViewService)
    # For now, acknowledge and state it's complex.
    # Actual implementation will use character_view_service from context.

    # Placeholder:
    # author_id = context['author_id']
    # guild_id = context['guild_id']
    # char_manager = context.get('character_manager')
    # char_view_service = context.get('character_view_service')
    # command_prefix = context.get('command_prefix', '/')

    # if not char_manager or not char_view_service:
    #     await send_callback("Character status system is currently unavailable.")
    #     return
    # if not guild_id:
    #     await send_callback("Character status can only be checked in a server (guild).")
    #     return

    # target_char_identifier = args[0] if args else author_id
    # try:
    #     # ... logic to find character (player_char) by target_char_identifier ...
    #     # player_char = await char_view_service.get_character_for_view(guild_id, target_char_identifier, author_id)
    #     # if not player_char:
    #     #     await send_callback(f"Character '{target_char_identifier}' not found or not accessible.")
    #     #     return
    #     # status_embed = await char_view_service.get_character_status_embed(player_char, context)
    #     # await send_callback(embed=status_embed)
    #     await send_callback(f"Status command for '{target_char_identifier if args else 'your character'}' would be displayed here. (Not yet fully implemented in this refactor step)")
    # except Exception as e:
    #     await send_callback(f"Error displaying status: {e}")
    #     print(f"CharacterCommands: Error in handle_status_command: {e}")
    await send_callback("Status command logic is complex and would be handled by CharacterViewService. (Refactor placeholder)")
    print(f"CharacterCommands: Processed status command for guild {context.get('guild_id')}.")
