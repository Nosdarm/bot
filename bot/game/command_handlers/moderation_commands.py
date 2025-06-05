from typing import List, Dict, Any, Optional
from discord import Message
import json
# import traceback

# This function was originally in CommandRouter, moved here.
async def _activate_approved_content_internal(request_id: str, context: Dict[str, Any]) -> bool:
    send_to_master_channel = context['send_to_command_channel'] # Feedback to the master using the command
    persistence_manager = context.get('persistence_manager')

    if not persistence_manager or not hasattr(persistence_manager, '_db_adapter') or not persistence_manager._db_adapter:
        print("ModerationCommands:_activate_approved_content_internal ERROR - DB adapter unavailable.")
        await send_to_master_channel(f"Error: DB adapter unavailable for content activation {request_id}.")
        return False

    db_adapter = persistence_manager._db_adapter
    moderation_request = await db_adapter.get_pending_moderation_request(request_id)

    if not moderation_request:
        await send_to_master_channel(f"Error: Request {request_id} not found for activation.")
        return False

    original_user_id = moderation_request.get("user_id")
    guild_id = moderation_request.get("guild_id")
    content_type = moderation_request.get("content_type")
    data_json_str = moderation_request.get("data")

    if not all([original_user_id, guild_id, content_type, data_json_str]):
        await send_to_master_channel(f"Error: Malformed moderation request data for {request_id}.")
        return False

    try:
        approved_data = json.loads(data_json_str)
    except json.JSONDecodeError:
        await send_to_master_channel(f"Error: Invalid JSON in request {request_id}.")
        return False

    npc_manager = context.get('npc_manager')
    quest_manager = context.get('quest_manager')
    location_manager = context.get('location_manager')
    character_manager = context.get('character_manager')
    status_manager = context.get('status_manager')

    activation_successful = False
    entity_info = "N/A" # Default info string

    try:
        if content_type == 'npc':
            if not npc_manager: await send_to_master_channel("Error: NpcManager unavailable."); return False
            entity_id_or_data = await npc_manager.create_npc_from_moderated_data(guild_id, approved_data, context)
            if entity_id_or_data and isinstance(entity_id_or_data, str):
                npc_obj = await npc_manager.get_npc(guild_id, entity_id_or_data)
                npc_name = getattr(npc_obj, 'name', entity_id_or_data) # Default to ID if name is not found
                if hasattr(npc_obj, 'name_i18n') and isinstance(getattr(npc_obj, 'name_i18n'), dict): # Check if name_i18n exists and is a dict
                    npc_name = npc_obj.name_i18n.get(context.get('bot_language','en'), entity_id_or_data)
                entity_info = f"NPC '{npc_name}' (ID: {entity_id_or_data})"
                activation_successful = True
        elif content_type == 'quest':
            if not quest_manager or not character_manager: await send_to_master_channel("Error: Quest/Char manager unavailable."); return False
            player_char = await character_manager.get_character_by_discord_id(guild_id, int(original_user_id))
            if not player_char:
                await send_to_master_channel(f"Error: Original user for quest {request_id} has no character.")
                await db_adapter.update_pending_moderation_request(request_id, 'activation_failed_no_char', context.get('author_id', 'System'), None)
                return False
            entity_id_or_data = await quest_manager.start_quest_from_moderated_data(guild_id, player_char.id, approved_data, context)
            if entity_id_or_data and isinstance(entity_id_or_data, dict) and 'id' in entity_id_or_data:
                q_name_i18n = entity_id_or_data.get('name_i18n', {})
                q_name = q_name_i18n.get(context.get('bot_language','en'), entity_id_or_data.get('id', 'Unknown Quest'))
                char_name_i18n = getattr(player_char, 'name_i18n', {})
                char_name = char_name_i18n.get(context.get('bot_language','en'), getattr(player_char, 'name', player_char.id))
                entity_info = f"Quest '{q_name}' for {char_name}"
                activation_successful = True
        elif content_type == 'location':
            if not location_manager: await send_to_master_channel("Error: LocationManager unavailable."); return False
            entity_id_or_data = await location_manager.create_location_instance_from_moderated_data(guild_id, approved_data, original_user_id, context)
            if entity_id_or_data and isinstance(entity_id_or_data, dict) and 'id' in entity_id_or_data:
                loc_name_i18n = entity_id_or_data.get('name_i18n',{})
                loc_name = loc_name_i18n.get(context.get('bot_language','en'), entity_id_or_data.get('id', 'Unknown Location'))
                entity_info = f"Location '{loc_name}' (ID: {entity_id_or_data.get('id')})"
                activation_successful = True
        else:
            await send_to_master_channel(f"Error: Unknown content type '{content_type}' for request {request_id}.")
            activation_successful = False # Ensure this is set

    except Exception as e_activate:
        print(f"ModerationCommands:_activate_approved_content_internal ERROR activating {request_id}: {e_activate}")
        # import traceback; traceback.print_exc()
        await send_to_master_channel(f"❌ Critical error during activation for {request_id}: {e_activate}.")
        await db_adapter.update_pending_moderation_request(request_id, 'activation_failed', context.get('author_id', 'System'), None)
        return False

    if activation_successful:
        if character_manager and status_manager: # Ensure managers are available
            player_char_to_update = await character_manager.get_character_by_discord_id(guild_id, int(original_user_id))
            if player_char_to_update:
                await status_manager.remove_status_effects_by_type(player_char_to_update.id, 'Character', 'awaiting_moderation', guild_id, context)
                print(f"ModerationCommands: User {original_user_id} should be notified that '{entity_info}' was approved.")
        await db_adapter.delete_pending_moderation_request(request_id)
        return True
    else:
        # Ensure a message is sent if activation failed but no exception occurred
        if content_type and not entity_info == "N/A": # Check if content_type was valid but activation failed specifically
             await send_to_master_channel(f"⚠️ Activation failed for '{content_type}' from request {request_id}. Specific reason should be logged by manager. Content remains in moderation queue with status 'activation_failed'.")
        else: # General failure or unknown content type
             await send_to_master_channel(f"⚠️ Activation failed for request {request_id}. Check logs. Content remains in moderation queue with status 'activation_failed'.")

        # Ensure status is updated if not already done by a specific failure case
        current_req_status = await db_adapter.get_pending_moderation_request(request_id) # Re-fetch to check current status
        if current_req_status and current_req_status.get('status') != 'activation_failed':
            await db_adapter.update_pending_moderation_request(request_id, 'activation_failed', context.get('author_id', 'System'), None)
        return False

async def handle_approve_content_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Approves AI-generated content. Usage: {prefix}approve <request_id>"""
    send_callback = context['send_to_command_channel']
    author_id_str = str(message.author.id)
    settings = context.get('settings', {})
    command_prefix = context.get('command_prefix', '/')

    gm_ids = [str(gm_id) for gm_id in settings.get('bot_admins', [])]
    if author_id_str not in gm_ids: await send_callback("Access Denied."); return
    if not args: await send_callback(f"Usage: {command_prefix}approve <request_id>"); return

    request_id = args[0]
    persistence_manager = context.get('persistence_manager')
    if not persistence_manager or not hasattr(persistence_manager, '_db_adapter') or not persistence_manager._db_adapter:
        await send_callback("Error: DB service unavailable."); return
    db_adapter = persistence_manager._db_adapter

    try:
        moderation_request = await db_adapter.get_pending_moderation_request(request_id)
        if not moderation_request: await send_callback(f"Error: Request ID `{request_id}` not found."); return
        if moderation_request.get("status") != 'pending':
            await send_callback(f"Error: Request `{request_id}` status is '{moderation_request.get('status')}'."); return

        update_success = await db_adapter.update_pending_moderation_request(request_id, 'approved', author_id_str, moderation_request.get("data")) # Pass existing data
        if update_success:
            await send_callback(f"✅ Request `{request_id}` approved. Activating content...")
            activation_success = await _activate_approved_content_internal(request_id, context)
            if activation_success:
                await send_callback(f"🚀 Content from request `{request_id}` activated.")
            else:
                await send_callback(f"⚠️ Request `{request_id}` approved, but activation failed. Check logs.")
        else:
            await send_callback(f"Error: Failed to update status for request `{request_id}`.")
    except Exception as e:
        print(f"ModerationCommands: Error in handle_approve_content for '{request_id}': {e}")
        # import traceback; traceback.print_exc()
        await send_callback(f"Unexpected error approving content: {e}")

async def handle_reject_content_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Rejects AI-generated content. Usage: {prefix}reject <request_id> [reason...]"""
    send_callback = context['send_to_command_channel']
    author_id_str = str(message.author.id)
    settings = context.get('settings', {})
    command_prefix = context.get('command_prefix', '/')

    gm_ids = [str(gm_id) for gm_id in settings.get('bot_admins', [])]
    if author_id_str not in gm_ids: await send_callback("Access Denied."); return
    if not args: await send_callback(f"Usage: {command_prefix}reject <request_id> [reason...]"); return

    request_id = args[0]
    reason = " ".join(args[1:]) if len(args) > 1 else "No reason provided."
    persistence_manager = context.get('persistence_manager')
    if not persistence_manager or not hasattr(persistence_manager, '_db_adapter') or not persistence_manager._db_adapter:
        await send_callback("Error: DB service unavailable."); return
    db_adapter = persistence_manager._db_adapter

    try:
        moderation_request = await db_adapter.get_pending_moderation_request(request_id)
        if not moderation_request: await send_callback(f"Error: Request ID `{request_id}` not found."); return
        if moderation_request.get("status") != 'pending':
            await send_callback(f"Error: Request `{request_id}` status is '{moderation_request.get('status')}'."); return

        update_success = await db_adapter.update_pending_moderation_request(request_id, 'rejected', author_id_str, moderation_request.get("data"), moderator_notes=reason)

        if update_success:
            await send_callback(f"🗑️ Content request `{request_id}` rejected. Reason: {reason}")
            original_user_id = moderation_request.get("user_id")
            guild_id = moderation_request.get("guild_id")
            char_manager = context.get('character_manager')
            status_manager = context.get('status_manager')
            if char_manager and status_manager and original_user_id and guild_id:
                player_char = await char_manager.get_character_by_discord_id(guild_id, int(original_user_id))
                if player_char:
                    await status_manager.remove_status_effects_by_type(player_char.id, 'Character', 'awaiting_moderation', guild_id, context)
                    print(f"ModerationCommands: User {original_user_id} should be notified of rejection for {request_id}.")
        else:
            await send_callback(f"Error: Failed to update status for request `{request_id}`.")
    except Exception as e:
        print(f"ModerationCommands: Error in handle_reject_content for '{request_id}': {e}")
        # import traceback; traceback.print_exc()
        await send_callback(f"Unexpected error rejecting content: {e}")

async def handle_edit_content_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Edits and approves AI-generated content. Usage: {prefix}edit <request_id> <json_edited_data>"""
    send_callback = context['send_to_command_channel']
    author_id_str = str(message.author.id)
    settings = context.get('settings', {})
    command_prefix = context.get('command_prefix', '/')

    gm_ids = [str(gm_id) for gm_id in settings.get('bot_admins', [])]
    if author_id_str not in gm_ids: await send_callback("Access Denied."); return
    if len(args) < 2: await send_callback(f"Usage: {command_prefix}edit <request_id> <json_edited_data>"); return

    request_id = args[0]
    json_edited_data_str = " ".join(args[1:])

    persistence_manager = context.get('persistence_manager')
    ai_validator = context.get('ai_validator')

    if not persistence_manager or not hasattr(persistence_manager, '_db_adapter') or not persistence_manager._db_adapter:
        await send_callback("Error: DB service unavailable."); return
    db_adapter = persistence_manager._db_adapter
    if not ai_validator: await send_callback("Error: AIResponseValidator unavailable."); return

    try:
        moderation_request = await db_adapter.get_pending_moderation_request(request_id)
        if not moderation_request: await send_callback(f"Error: Request ID `{request_id}` not found."); return
        if moderation_request.get("status") != 'pending':
             await send_callback(f"Error: Request `{request_id}` status is '{moderation_request.get('status')}'."); return

        original_content_type = moderation_request.get("content_type")
        request_guild_id = moderation_request.get("guild_id")
        if not original_content_type or not request_guild_id:
            await send_callback(f"Error: Request `{request_id}` missing type/guild ID."); return

        try:
            edited_data_dict = json.loads(json_edited_data_str) # Validate JSON structure
            if not isinstance(edited_data_dict, dict):
                await send_callback("Error: Edited data must be a JSON object."); return
        except json.JSONDecodeError as e_json:
            await send_callback(f"Error parsing JSON for edited data: {e_json}."); return

        validation_result = await ai_validator.validate_ai_response(
            ai_json_string=json_edited_data_str, # Pass the string for validation
            expected_structure=original_content_type,
            guild_id=request_guild_id,
            **context
        )

        if not validation_result.get('overall_status','').startswith("success"):
            errors_str = json.dumps(validation_result.get('errors', ['Unknown validation error.']))
            await send_callback(f"Error: Edited data failed validation for type '{original_content_type}'. Errors: {errors_str}"); return

        update_success = await db_adapter.update_pending_moderation_request(request_id, 'approved_edited', author_id_str, json_edited_data_str)
        if update_success:
            await send_callback(f"✅ Request `{request_id}` updated to 'approved_edited'. Activating content...")
            activation_success = await _activate_approved_content_internal(request_id, context)
            if activation_success:
                await send_callback(f"🚀 Content from request `{request_id}` (edited) activated.")
            else:
                await send_callback(f"⚠️ Request `{request_id}` edited & approved, but activation failed. Check logs.")
        else:
            await send_callback(f"Error: Failed to update status/data for request `{request_id}`.")
    except Exception as e:
        print(f"ModerationCommands: Error in handle_edit_content for '{request_id}': {e}")
        # import traceback; traceback.print_exc()
        await send_callback(f"Unexpected error editing content: {e}")
