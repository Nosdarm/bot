from typing import List, Dict, Any, Optional
from discord import Message
import json # For parsing params_json in resolve_conflict and other GM commands
# import traceback # For debugging

# Placeholder for _notify_master_of_pending_content_func if needed directly by GM commands
# This function itself will be passed in context from CommandRouter
async def _local_notify_master_placeholder(request_id: str, guild_id: str, user_id: str, context: Dict[str, Any]):
    print(f"GMCommands (Placeholder): Notify master about request {request_id} for guild {guild_id}, user {user_id}")
    # In reality, this would use context['send_callback_factory'] and settings for channel ID

async def _gm_action_load_campaign(message: Message, sub_args: List[str], context: Dict[str, Any]) -> None:
    send_callback = context['send_to_command_channel']
    # campaign_loader in original was CampaignLoader, now CampaignLoaderService
    campaign_loader: Optional[Any] = context.get('campaign_loader') # Type hint Any for now
    command_prefix = context.get('command_prefix', '/')

    if not campaign_loader:
        await send_callback("❌ CampaignLoader service unavailable.")
        return
    if not sub_args:
        await send_callback(f"Usage: `{command_prefix}gm load_campaign <file_path_or_campaign_id>`") # Clarified usage
        return

    campaign_identifier = sub_args[0] # This can be a path or an ID
    guild_id = context.get('guild_id')

    if not guild_id: # Required by the more likely new method
        await send_callback("❌ Guild ID context missing for campaign load. This command must be run in a server.")
        return

    try:
        # Prefer the new method name if available
        if hasattr(campaign_loader, 'trigger_campaign_load_and_distribution'):
            await send_callback(f"Initiating campaign load for '{campaign_identifier}' in guild {guild_id}...")
            # This method is expected to handle everything, including messaging success/failure internally or via exceptions
            await campaign_loader.trigger_campaign_load_and_distribution(guild_id, campaign_identifier, **context)
            # If it doesn't message success, we might add one here, but usually manager methods handle their own comms.
            # For now, assuming it messages on success or raises specific errors handled below.
        elif hasattr(campaign_loader, 'load_campaign_from_file'): # Fallback to old method if it exists
            campaign_data = campaign_loader.load_campaign_from_file(campaign_identifier) # campaign_identifier is file_path here
            if campaign_data:
                await send_callback(f"✅ Campaign data loaded from `{campaign_identifier}` (using old method). Distribution might be manual.")
            else:
                await send_callback(f"❌ Failed to load campaign data from `{campaign_identifier}` (data was empty, using old method).")
        else:
            await send_callback("❌ CampaignLoader service does not have a suitable load method.")
            return # Added return
    except FileNotFoundError: # Specific to load_campaign_from_file path
        await send_callback(f"❌ Error: Campaign file not found at `{campaign_identifier}`.")
    except Exception as e:
        await send_callback(f"❌ Error loading campaign '{campaign_identifier}': {e}")
        print(f"GMCommands: Error in _gm_action_load_campaign for '{campaign_identifier}': {e}")
        # import traceback; traceback.print_exc()

async def _gm_action_inspect_relationships(message: Message, sub_args: List[str], context: Dict[str, Any]) -> None:
    send_callback = context['send_to_command_channel']
    guild_id = context.get('guild_id')
    command_prefix = context.get('command_prefix', '/')

    if not guild_id:
        await send_callback("❌ This GM command can only be used in a guild.")
        return

    relationship_manager: Optional[Any] = context.get('relationship_manager') # Type Any for now
    if not relationship_manager:
        await send_callback("❌ RelationshipManager service unavailable.")
        return

    if not sub_args or len(sub_args) < 1:
        await send_callback(f"Usage: `{command_prefix}gm relationships inspect <entity_id>`")
        return

    entity_id_to_inspect = sub_args[0]

    try:
        relationships = await relationship_manager.get_relationships_for_entity(guild_id, entity_id_to_inspect, context=context)
        if not relationships:
            await send_callback(f"ℹ️ No relationships found for entity `{entity_id_to_inspect}` in this guild.")
            return

        response_lines = [f"Relationships for Entity `{entity_id_to_inspect}`:"]
        char_mgr: Optional[Any] = context.get('character_manager') # Type Any for now
        npc_mgr: Optional[Any] = context.get('npc_manager') # Type Any for now
        bot_lang = context.get('bot_language', 'en')

        for rel_data_obj in relationships:
            rel_data = {}
            if isinstance(rel_data_obj, dict): # If it's already a dict
                rel_data = rel_data_obj
            else: # Assuming it's a model instance, try to get attributes
                rel_data = {
                    'entity1_id': getattr(rel_data_obj, 'entity1_id', None),
                    'entity1_type': getattr(rel_data_obj, 'entity1_type', None),
                    'entity2_id': getattr(rel_data_obj, 'entity2_id', None),
                    'entity2_type': getattr(rel_data_obj, 'entity2_type', None),
                    'relationship_type': getattr(rel_data_obj, 'relationship_type', 'unknown'),
                    'strength': getattr(rel_data_obj, 'strength', 0.0),
                    'details': getattr(rel_data_obj, 'details', 'N/A')
                }

            other_entity_id = None
            other_entity_type = None
            if rel_data.get('entity1_id') == entity_id_to_inspect:
                other_entity_id = rel_data.get('entity2_id', 'Unknown')
                other_entity_type = rel_data.get('entity2_type', 'Unknown')
            elif rel_data.get('entity2_id') == entity_id_to_inspect:
                other_entity_id = rel_data.get('entity1_id', 'Unknown')
                other_entity_type = rel_data.get('entity1_type', 'Unknown')
            else:
                continue

            target_name_str = other_entity_id
            if other_entity_id: # Ensure other_entity_id is not None
                if other_entity_type == 'Character' and char_mgr and hasattr(char_mgr, 'get_character'):
                        char_obj = await char_mgr.get_character(guild_id, other_entity_id)
                        if char_obj: target_name_str = getattr(char_obj, 'name_i18n', {}).get(bot_lang, getattr(char_obj, 'name', other_entity_id))
                elif other_entity_type == 'NPC' and npc_mgr and hasattr(npc_mgr, 'get_npc'):
                        npc_obj = await npc_mgr.get_npc(guild_id, other_entity_id)
                        if npc_obj: target_name_str = getattr(npc_obj, 'name_i18n', {}).get(bot_lang, getattr(npc_obj, 'name', other_entity_id))

            rel_type = rel_data.get('relationship_type', 'unknown')
            strength = rel_data.get('strength', 0.0)
            details = rel_data.get('details', 'N/A')

            response_lines.append(
                f"- With **{target_name_str}** (`{other_entity_id}` ({other_entity_type})): Type: `{rel_type}`, Strength: `{strength:.1f}`. Details: _{details}_"
            )
        response = "\n".join(response_lines)
        if len(response) > 1950: response = response[:1950] + "\n... (truncated)"
        await send_callback(response)

    except Exception as e:
        print(f"GMCommands: Error in _gm_action_inspect_relationships: {e}")
        # import traceback; traceback.print_exc()
        await send_callback(f"❌ Error inspecting relationships: {e}")


async def handle_gm_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """GM-level commands. Usage: {prefix}gm <subcommand> [args]"""
    send_callback = context['send_to_command_channel']
    author_id_str = str(message.author.id)
    settings = context.get('settings', {})
    command_prefix = context.get('command_prefix', '/')

    gm_ids = [str(gm_id) for gm_id in settings.get('bot_admins', [])]
    if author_id_str not in gm_ids:
        await send_callback("Access Denied: This command is for GMs only.")
        return

    doc_string_template = context.get('command_docstrings', {}).get('gm', "{prefix}gm <subcommand> [args]")
    full_doc_string = doc_string_template.format(prefix=command_prefix) if doc_string_template else "{prefix}gm <subcommand> [args]".format(prefix=command_prefix)


    if not args:
        await send_callback(f"Usage: {command_prefix}gm <subcommand> [arguments]\nSubcommands: save_state, create_npc, delete_npc, relationships, load_campaign, ai_create_quest, ai_create_location.\nFull usage: {full_doc_string}") # Removed resolve_conflict from here as it's separate
        return

    subcommand = args[0].lower()
    gm_args = args[1:]
    guild_id = context.get('guild_id')

    notify_master_func = context.get('_notify_master_of_pending_content_func', _local_notify_master_placeholder)


    if subcommand == "save_state":
        if not guild_id: await send_callback("Error: Must be used in a server channel."); return
        persistence_manager = context.get('persistence_manager')
        if not persistence_manager: await send_callback("Error: PersistenceManager unavailable."); return
        try:
            await persistence_manager.save_game_state(guild_ids=[guild_id], **context)
            await send_callback(f"✅ Game state saving initiated for guild {guild_id}.")
        except Exception as e: await send_callback(f"❌ Error during game state save: {e}"); print(f"GMCommands: Error in GM save_state: {e}")


    elif subcommand == "create_npc":
        if not guild_id: await send_callback("Error: Must be used in a server channel."); return
        if not gm_args: await send_callback(f"Usage: {command_prefix}gm create_npc <template_id> [loc_id] [name] [temp(t/f)]"); return

        template_id = gm_args[0]
        loc_id = gm_args[1] if len(gm_args) > 1 else None
        name_arg = gm_args[2] if len(gm_args) > 2 else None
        is_temp_str = gm_args[3].lower() if len(gm_args) > 3 else "false"
        is_temp_bool = is_temp_str == "true"

        npc_manager = context.get('npc_manager')
        if not npc_manager: await send_callback("Error: NpcManager unavailable."); return

        creation_kwargs = {**context, 'user_id': author_id_str, '_notify_master_of_pending_content_func': notify_master_func}
        created_npc_info = await npc_manager.create_npc(guild_id, template_id, loc_id, name_arg, is_temp_bool, **creation_kwargs)

        if isinstance(created_npc_info, dict) and created_npc_info.get("status") == "pending_moderation":
            req_id = created_npc_info["request_id"]
            await send_callback(f"NPC data for '{template_id}' submitted for moderation. ID: `{req_id}`.")
            # Notification to master is now handled within NpcManager via the passed callback
        elif isinstance(created_npc_info, str):
            new_npc = await npc_manager.get_npc(guild_id, created_npc_info)
            display_name = getattr(new_npc, 'name', template_id) # Default to template_id if name not found
            if hasattr(new_npc, 'name_i18n') and isinstance(getattr(new_npc, 'name_i18n'),dict):
                display_name = new_npc.name_i18n.get(context.get('bot_language','en'), template_id)

            await send_callback(f"✅ NPC '{display_name}' (ID: `{created_npc_info}`) created.")
        else:
            await send_callback(f"❌ Failed to create NPC from template '{template_id}'.")


    elif subcommand == "ai_create_quest":
        if not guild_id: await send_callback("Error: Must be used in a server channel."); return
        if not gm_args: await send_callback(f"Usage: {command_prefix}gm ai_create_quest <idea|AI:template_id> [char_id]"); return

        idea_or_template_id = gm_args[0]
        char_id_arg = gm_args[1] if len(gm_args) > 1 else None

        quest_manager = context.get('quest_manager')
        char_manager = context.get('character_manager')
        if not quest_manager or not char_manager: await send_callback("Error: Quest/Character manager unavailable."); return

        final_char_id = None
        if char_id_arg:
            char_to_assign = await char_manager.get_character(guild_id, char_id_arg) # get_character should be async
            if not char_to_assign: await send_callback(f"Error: Specified char ID '{char_id_arg}' not found."); return
            final_char_id = char_to_assign.id
        else:
            gm_char = await char_manager.get_character_by_discord_id(guild_id, int(author_id_str)) # get_character_by_discord_id needs to be async or sync consistently
            if gm_char: final_char_id = gm_char.id

        if not final_char_id: await send_callback("Error: Triggering character ID required."); return

        creation_kwargs = {**context, 'user_id': author_id_str, '_notify_master_of_pending_content_func': notify_master_func}
        quest_info = await quest_manager.start_quest(guild_id, final_char_id, idea_or_template_id, **creation_kwargs)

        if isinstance(quest_info, dict) and quest_info.get("status") == "pending_moderation":
            req_id = quest_info["request_id"]
            await send_callback(f"Quest data for '{idea_or_template_id}' submitted for moderation. ID: `{req_id}`.")
            # Notification to master handled by QuestManager via callback
        elif isinstance(quest_info, dict) and 'id' in quest_info:
            q_name = quest_info.get('name_i18n', {}).get(context.get('bot_language', 'en'), idea_or_template_id)
            await send_callback(f"✅ Quest '{q_name}' started for char '{final_char_id}'.")
        else:
            await send_callback(f"❌ Failed to start/generate quest '{idea_or_template_id}'.")

    elif subcommand == "ai_create_location":
        if not guild_id: await send_callback("Error: Must be used in a server channel."); return
        if not gm_args: await send_callback(f"Usage: {command_prefix}gm ai_create_location <idea|AI:template_id>"); return

        idea_or_template_id = gm_args[0]
        loc_manager = context.get('location_manager')
        if not loc_manager: await send_callback("Error: LocationManager unavailable."); return

        creation_kwargs = {**context, 'user_id': author_id_str, '_notify_master_of_pending_content_func': notify_master_func}
        loc_info = await loc_manager.create_location_instance(guild_id, idea_or_template_id, **creation_kwargs)

        if isinstance(loc_info, dict) and loc_info.get("status") == "pending_moderation":
            req_id = loc_info["request_id"]
            await send_callback(f"Location data for '{idea_or_template_id}' submitted for moderation. ID: `{req_id}`.")
            # Notification to master handled by LocationManager via callback
        elif isinstance(loc_info, dict) and 'id' in loc_info:
            l_name = loc_info.get('name_i18n', {}).get(context.get('bot_language', 'en'), idea_or_template_id)
            await send_callback(f"✅ Location '{l_name}' (ID: {loc_info.get('id')}) created.")
        else:
            await send_callback(f"❌ Failed to create/generate location '{idea_or_template_id}'.")


    elif subcommand == "delete_npc":
        if not guild_id: await send_callback("Error: Must be used in a server channel."); return
        if not gm_args: await send_callback(f"Usage: {command_prefix}gm delete_npc <npc_id>"); return
        npc_id_del = gm_args[0]
        npc_manager = context.get('npc_manager')
        if not npc_manager: await send_callback("Error: NpcManager unavailable."); return
        removed_id = await npc_manager.remove_npc(guild_id, npc_id_del, **context) # remove_npc should be async
        if removed_id: await send_callback(f"✅ NPC `{removed_id}` removed.")
        else: await send_callback(f"❌ Failed to remove NPC `{npc_id_del}`.")

    elif subcommand == "relationships" or subcommand == "rel":
        if not gm_args: await send_callback(f"Usage: {command_prefix}gm {subcommand} inspect <entity_id>"); return
        op = gm_args[0].lower()
        if op == "inspect":
            await _gm_action_inspect_relationships(message, gm_args[1:], context)
        else: await send_callback(f"Unknown operation for relationships: '{op}'. Try 'inspect'.")

    elif subcommand == "load_campaign":
        await _gm_action_load_campaign(message, gm_args, context) # Use the refactored version

    else:
        await send_callback(f"Unknown GM subcommand: '{subcommand}'. Full usage:\n{full_doc_string}")

async def handle_resolve_conflict_command(message: Message, args: List[str], context: Dict[str, Any]) -> None:
    """Allows a Master to manually resolve a pending conflict. Usage: {prefix}resolve_conflict <conflict_id> <outcome_type> [<params_json>]"""
    send_callback = context['send_to_command_channel']
    author_id_str = str(message.author.id)
    settings = context.get('settings', {})
    command_prefix = context.get('command_prefix', '/')

    gm_ids = [str(gm_id) for gm_id in settings.get('bot_admins', [])]
    if author_id_str not in gm_ids:
        await send_callback("Access Denied: This command is for GMs/Masters only.")
        return

    if len(args) < 2:
        await send_callback(f"Usage: {command_prefix}resolve_conflict <conflict_id> <outcome_type> [<params_json>]")
        return

    conflict_id_arg = args[0]
    outcome_type_arg = args[1]
    params_json_arg = " ".join(args[2:]) if len(args) > 2 else None
    parsed_params: Optional[Dict[str, Any]] = None

    if params_json_arg:
        try:
            parsed_params = json.loads(params_json_arg)
            if not isinstance(parsed_params, dict):
                await send_callback("Error: params_json must be a valid JSON object.")
                return
        except json.JSONDecodeError as e:
            await send_callback(f"Error parsing params_json: {e}")
            return

    conflict_resolver = context.get('conflict_resolver')
    if not conflict_resolver:
        await send_callback("Error: ConflictResolver service unavailable.")
        return

    try:
        resolution_result = None
        if hasattr(conflict_resolver, "process_master_resolution_async"): # Prefer async if available
            resolution_result = await conflict_resolver.process_master_resolution_async(
                conflict_id=conflict_id_arg,
                outcome_type=outcome_type_arg,
                params=parsed_params,
                context=context
            )
        elif hasattr(conflict_resolver, "process_master_resolution"):
             resolution_result = conflict_resolver.process_master_resolution(
                conflict_id=conflict_id_arg,
                outcome_type=outcome_type_arg,
                params=parsed_params,
                context=context
            )
        else:
            await send_callback("Error: ConflictResolver has no suitable resolution method.")
            return


        if not isinstance(resolution_result, dict):
            await send_callback(f"Error resolving conflict '{conflict_id_arg}'. Invalid result from resolver.")
            return

        response_msg = resolution_result.get("message", "Conflict resolution processed.")
        if resolution_result.get("success"):
            await send_callback(f"✅ {response_msg}")
        else:
            await send_callback(f"❌ {response_msg}")
    except Exception as e:
        print(f"GMCommands: Error in handle_resolve_conflict_command for ID '{conflict_id_arg}': {e}")
        # import traceback; traceback.print_exc()
        await send_callback(f"An unexpected error occurred: {e}")
