import json
from typing import List, Dict, Any, Optional
from discord import Message

# Assuming is_uuid_format and other utilities will be handled by CommandRouter or passed in context if complex
# For now, direct dependencies are on context elements.

async def handle_help_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Показывает список доступных команд или помощь по конкретной команде. Usage: {prefix}help [команда]"""
    send_callback = context['send_to_command_channel']
    command_prefix = context['command_prefix'] # Expect this in context

    # Accessing registered commands:
    # This is tricky. _command_registry was internal to CommandRouter.
    # The CommandRouter will need to pass the list of available commands via context,
    # or this help function needs a way to query them.
    # For now, let's assume 'registered_commands' (a list of command strings) is passed in context.
    # This will require CommandRouter to prepare this list.
    # Alternatively, CommandRouter's main help could list internal commands,
    # and delegate to other handlers for their specific help.
    # For a simpler first pass, let's assume CommandRouter provides 'all_command_keywords' in context.

    all_command_keywords = context.get('all_command_keywords', []) # Expect this in context
    # The PartyCommandHandler's help also needs to be integrated.
    # This might mean CommandRouter still orchestrates the main help, or this handler gets more complex.

    if not args:
        help_message = f"Доступные команды (префикс `{command_prefix}`):
"
        help_message += ", ".join([f"`{cmd}`" for cmd in sorted(all_command_keywords)])
        help_message += f"\nИспользуйте `{command_prefix}help <команда>` для подробностей."
        await send_callback(help_message)
    else:
        target_command = args[0].lower()
        # To get help for a specific command, the CommandRouter would still need to
        # find the docstring of the target command's handler.
        # This suggests that the main CommandRouter.route might still be responsible for
        # dispatching help requests to the appropriate new handlers if they are to provide their own detailed help.
        # Option 1: Each handler has a get_help(command_name) method.
        # Option 2: CommandRouter fetches docstrings from new handlers.
        # For now, let's keep it simple: this handler provides generic help.
        # Specific command help will be added iteratively.
        # We need a way to get the docstring of the *actual* handler for target_command.
        # This implies the CommandRouter would need to know which handler handles which command.

        # Placeholder for fetching specific command help - CommandRouter will need to enhance context for this
        specific_command_doc = context.get('command_docstrings', {}).get(target_command)

        if specific_command_doc:
            # Ensure prefix is formatted into the docstring
            formatted_doc = specific_command_doc.format(prefix=command_prefix)
            await send_callback(formatted_doc)
        elif target_command in all_command_keywords:
             await send_callback(f"Более подробная информация для команды `{target_command}` пока недоступна.")
        else:
            await send_callback(f"❓ Команда `{command_prefix}{target_command}` не найдена.")
    print(f"MetaCommands: Processed help command for guild {context.get('guild_id')}.")


async def handle_roll_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Rolls dice based on standard dice notation (e.g., /roll 2d6+3, /roll d20). Usage: {prefix}roll <notation>"""
    send_callback = context.get('send_to_command_channel')
    command_prefix = context.get('command_prefix', '/') # Get prefix from context

    if not send_callback:
        print("MetaCommands: Error: send_to_command_channel not found in context for handle_roll.")
        return

    if not args:
        await send_callback(f"Usage: {command_prefix}roll <dice_notation (e.g., 2d6+3, d20, 4dF)>")
        return

    roll_string = "".join(args)
    rule_engine = context.get('rule_engine')

    if not rule_engine:
        await send_callback("Error: RuleEngine not available for the roll command.")
        print("MetaCommands: Error: rule_engine not found in context for handle_roll.")
        return

    try:
        roll_result = await rule_engine.resolve_dice_roll(roll_string, context=context)

        if not isinstance(roll_result, dict):
             await send_callback(f"An error occurred while trying to roll '{roll_string}'. Invalid result from RuleEngine.")
             print(f"MetaCommands: RuleEngine.resolve_dice_roll returned unexpected type: {type(roll_result)}")
             return

        rolls_str = ", ".join(map(str, roll_result.get('rolls', [])))
        result_message = f"🎲 {message.author.mention} rolled **{roll_result.get('roll_string', roll_string)}**:\n"

        if roll_result.get('dice_sides') == 'F':
            result_message += f"Rolls: [{rolls_str}] (Symbols: {' '.join(['+' if r > 0 else '-' if r < 0 else '0' for r in roll_result.get('rolls', [])])})"
        else:
            result_message += f"Rolls: [{rolls_str}]"

        modifier_val = roll_result.get('modifier', 0)
        if modifier_val != 0:
            result_message += f" Modifier: {modifier_val:+}"

        result_message += f"\n**Total: {roll_result.get('total')}**"
        await send_callback(result_message)

    except ValueError as ve:
        await send_callback(f"Error: Invalid dice notation for '{roll_string}'. {ve}")
    except Exception as e:
        print(f"MetaCommands: Error in handle_roll for '{roll_string}': {e}")
        # It's good practice to import traceback if you use it.
        # import traceback
        # traceback.print_exc()
        await send_callback(f"An error occurred while trying to roll '{roll_string}'.")
