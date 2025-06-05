from typing import List, Dict, Any, Optional
from discord import Message
# import traceback # For debugging if needed

async def handle_quest_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """
    Manages character quests. Usage: {prefix}quest <action> [args]
    {prefix}quest list
    {prefix}quest start <quest_template_id>
    {prefix}quest complete <active_quest_id>
    {prefix}quest fail <active_quest_id>
    {prefix}quest objectives <active_quest_id> # Optional: To view current objectives
    """
    send_callback = context.get('send_to_command_channel')
    guild_id = context.get('guild_id')
    author_id_str = context.get('author_id')
    command_prefix = context.get('command_prefix', '/') # Get prefix from context

    if not send_callback: return
    if not guild_id:
        await send_callback("Quest commands can only be used on a server.")
        return
    if not author_id_str:
        await send_callback("Could not identify your user ID.")
        return

    char_manager = context.get('character_manager')
    quest_manager = context.get('quest_manager')
    status_manager = context.get('status_manager') # For 'awaiting_moderation'

    if not char_manager or not quest_manager: # status_manager is optional for base functionality
        await send_callback("Quest or Character system is currently unavailable.")
        print("QuestCommands: Missing CharacterManager or QuestManager for handle_quest_command.")
        return

    doc_string_template = context.get('command_docstrings', {}).get('quest', handle_quest_command.__doc__)
    doc_string = doc_string_template.format(prefix=command_prefix) if doc_string_template else handle_quest_command.__doc__.format(prefix=command_prefix)


    try:
        author_discord_id = int(author_id_str)
        # get_character_by_discord_id is sync
        player_char = char_manager.get_character_by_discord_id(guild_id, author_discord_id)
        if not player_char:
            await send_callback(f"You do not have an active character. Use `{command_prefix}character create <name>`.")
            return
        character_id = player_char.id
    except ValueError:
        await send_callback("Invalid user ID format.")
        return
    except Exception as e:
        await send_callback(f"Error fetching your character: {e}")
        return

    if not args:
        await send_callback(f"Please specify a quest action. Usage:\n{doc_string}")
        return

    subcommand = args[0].lower()
    quest_action_args = args[1:]

    try:
        if subcommand == "list":
            quest_list = await quest_manager.list_quests_for_character(character_id, guild_id, context)
            if not quest_list:
                await send_callback("No quests currently available or active for you.")
                return

            char_name_i18n = getattr(player_char, 'name_i18n', {})
            char_display_name = char_name_i18n.get(context.get('bot_language', 'en'), player_char.id) if isinstance(char_name_i18n, dict) else getattr(player_char, 'name', player_char.id)


            response = f"**Your Quests, {char_display_name}:**\n"
            for q_data in quest_list:
                q_name_i18n = getattr(q_data, 'name_i18n', {})
                q_name = q_name_i18n.get(context.get('bot_language', 'en'), getattr(q_data, 'id', 'Unknown Quest')) if isinstance(q_name_i18n, dict) else getattr(q_data, 'name', getattr(q_data, 'id', 'Unknown Quest'))
                q_status = getattr(q_data, 'status', 'unknown')
                q_desc_i18n = getattr(q_data, 'description_i18n', {})
                q_desc = q_desc_i18n.get(context.get('bot_language', 'en'), 'No description.') if isinstance(q_desc_i18n, dict) else getattr(q_data, 'description', 'No description.')
                q_id = getattr(q_data, 'id', 'Unknown ID')

                response += f"- **{q_name}** (Status: {q_status})\n"
                response += f"  _{q_desc}_\n"
                response += f"  _(ID: {q_id})_\n"
            if len(response) > 1950: response = response[:1950] + "\n... (list truncated)"
            await send_callback(response)

        elif subcommand == "start":
            if not quest_action_args:
                await send_callback(f"Usage: {command_prefix}quest start <quest_template_id>")
                return
            quest_template_id_arg = quest_action_args[0]
            extended_context = {**context, 'user_id': author_id_str}
            quest_start_result = await quest_manager.start_quest(
                guild_id=guild_id,
                character_id=character_id,
                quest_template_id=quest_template_id_arg,
                **extended_context
            )

            if isinstance(quest_start_result, dict):
                if quest_start_result.get("status") == "pending_moderation":
                    request_id = quest_start_result["request_id"]
                    await send_callback(f"📜 Your request for quest '{quest_template_id_arg}' has been submitted for moderation (ID: `{request_id}`).")
                    if status_manager and player_char:
                        await status_manager.add_status_effect_to_entity(
                            target_id=player_char.id, target_type='Character',
                            status_type='awaiting_moderation', guild_id=guild_id, duration=None,
                            source_id=f"quest_generation_user_{author_id_str}", context=context
                        )

                    notify_master_func = context.get('_notify_master_of_pending_content_func')
                    if notify_master_func:
                        await notify_master_func(request_id, guild_id, author_id_str, context)
                    else:
                        print(f"QuestCommands: _notify_master_of_pending_content_func not found in context. Cannot notify master channel for request {request_id}.")


                elif 'id' in quest_start_result:
                    quest_name_i18n = quest_start_result.get('name_i18n', {})
                    quest_name = quest_name_i18n.get(context.get('bot_language', 'en'), quest_template_id_arg) if isinstance(quest_name_i18n, dict) else quest_template_id_arg
                    char_name_i18n = getattr(player_char, 'name_i18n', {})
                    char_display_name = char_name_i18n.get(context.get('bot_language', 'en'), player_char.id) if isinstance(char_name_i18n, dict) else getattr(player_char, 'name', player_char.id)
                    await send_callback(f"Quest '{quest_name}' started for {char_display_name}!")
                else:
                    await send_callback(f"Failed to start quest '{quest_template_id_arg}'. Unexpected format.")
            elif quest_start_result is False:
                await send_callback(f"Failed to start quest '{quest_template_id_arg}'. Prerequisites not met or quest unavailable.")
            else:
                await send_callback(f"Failed to start quest '{quest_template_id_arg}'. Unknown error or quest does not exist.")

        elif subcommand == "complete":
            if not quest_action_args:
                await send_callback(f"Usage: {command_prefix}quest complete <active_quest_id>")
                return
            active_quest_id = quest_action_args[0]
            success = await quest_manager.complete_quest(character_id, active_quest_id, guild_id, context)
            if success:
                await send_callback(f"✅ Quest '{active_quest_id}' completed!")
            else:
                await send_callback(f"❌ Failed to complete quest '{active_quest_id}'. Objectives not met or ID incorrect.")

        elif subcommand == "fail":
            if not quest_action_args:
                await send_callback(f"Usage: {command_prefix}quest fail <active_quest_id>")
                return
            active_quest_id = quest_action_args[0]
            success = await quest_manager.fail_quest(character_id, active_quest_id, guild_id, context)
            if success:
                await send_callback(f"⚠️ Quest '{active_quest_id}' marked as failed.")
            else:
                await send_callback(f"❌ Failed to mark quest '{active_quest_id}' as failed.")

        elif subcommand == "objectives" or subcommand == "details":
            if not quest_action_args:
                await send_callback(f"Usage: {command_prefix}quest {subcommand} <active_quest_id>")
                return
            active_quest_id = quest_action_args[0]
            quest_details_response = await quest_manager.get_active_quest_details(character_id, active_quest_id, guild_id, context)
            if quest_details_response:
                await send_callback(quest_details_response)
            else:
                await send_callback(f"Quest '{active_quest_id}' not found or details unavailable.")
        else:
            await send_callback(f"Unknown quest action: '{subcommand}'. Usage:\n{doc_string}")

    except Exception as e:
        print(f"QuestCommands: Error in handle_quest_command for subcommand '{subcommand}': {e}")
        # import traceback; traceback.print_exc() # Uncomment for detailed debugging
        await send_callback(f"An error occurred processing quest command: {e}")
