# bot/command_modules/exploration_cmds.py
import discord
import discord.abc # Added for type checking Messageable
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING, Dict, Any, List, cast # Keep TYPE_CHECKING for RPGBot and DBService, add cast
import traceback # For error logging
import json # Added for json.dumps

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # Already imported by previous step, ensure it's here
    from bot.database.sqlite_adapter import SqliteAdapter # Corrected import
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.models.character import Character as CharacterModel
    from bot.game.models.location import Location as LocationModel # Assuming LocationInstance is Location
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.rules.rule_engine import RuleEngine
    
    # from bot.game.action_processors.on_enter_action_executor import OnEnterActionExecutor # If it's a class
    # from bot.game.generators.stage_description_generator import StageDescriptionGenerator # If it's a class

# TEST_GUILD_IDS can be removed if not used in decorators
# TEST_GUILD_IDS = []

async def _send_location_embed(
    interaction: Interaction,
    location_data: Dict[str, Any], # This is location_instance_data
    location_manager: 'LocationManager',
    npc_manager: 'NpcManager', # Added NpcManager
    guild_id: str,
    *,
    followup: bool = False,
    initial_message: Optional[str] = None
):
    """Helper function to construct and send the location embed using managers."""
    embed = discord.Embed(
        title=location_data.get('name', 'Unknown Location'),
        description=location_data.get('description', 'A non-descript place.'),
        color=discord.Color.green()
    )

    location_instance_id_str = location_data.get("id")
    if location_instance_id_str:
        try:
            # Assuming npc_manager.get_npcs_in_location expects location_id (which is an instance_id here)
            npcs_in_location_models = npc_manager.get_npcs_in_location(guild_id=guild_id, location_id=location_instance_id_str)
            if npcs_in_location_models:
                # Assuming character.selected_language is available or a default can be used.
                # For simplicity in this helper, using 'en' as default for NPC names.
                language = "en" # Placeholder, ideally passed or fetched from player context
                npc_names = ", ".join([npc.name_i18n.get(language, npc.name_i18n.get('en', 'Unnamed NPC')) for npc in npcs_in_location_models])
                embed.add_field(name="NPCs Here", value=npc_names if npc_names else "None", inline=False)
            else:
                embed.add_field(name="NPCs Here", value="None", inline=False)
        except Exception as e:
            print(f"Error fetching NPCs for embed: {e}")
            embed.add_field(name="NPCs Here", value="Error loading NPCs.", inline=False)
    else: # location_instance_id is None
        embed.add_field(name="NPCs Here", value="*Location ID missing, cannot load NPCs*", inline=False)


    # Exits - using location_manager
    if location_instance_id_str: # Only try to get exits if we have a valid current location instance ID
        # Ensure all required arguments are passed to get_connected_locations
        # get_connected_locations expects instance_id.
        # location_instance_id_str is the correct ID to pass.
        # location_template_id = location_data.get('template_id') # Not needed for this call

        # if location_template_id: # This check becomes redundant if we only need instance_id
        connected_exits = location_manager.get_connected_locations(
            guild_id=guild_id,
            instance_id=location_instance_id_str
        )
        if connected_exits and isinstance(connected_exits, dict) and len(connected_exits) > 0:
            exit_display_parts = []
            for exit_name_or_direction, target_loc_template_id in connected_exits.items(): # Corrected indentation
            for exit_name_or_direction, target_loc_template_id in connected_exits.items():
                # get_connected_locations returns template IDs as values based on its current implementation.
                # So, we still need to fetch the static data for the name.
                target_loc_template_data = location_manager.get_location_static(guild_id, target_loc_template_id)
                if target_loc_template_data:
                    exit_display_parts.append(f"{exit_name_or_direction.capitalize()} to {target_loc_template_data.get('name', 'an unnamed area')}")
                else:
                    exit_display_parts.append(f"{exit_name_or_direction.capitalize()} (leads to an unknown area - Template ID: {target_loc_template_id[:6]})")

            if exit_display_parts: # Corrected indentation
                embed.add_field(name="Exits", value="\n".join(exit_display_parts), inline=False)
            else:
                embed.add_field(name="Exits", value="None apparent.", inline=False)
            if exit_display_parts:
                embed.add_field(name="Exits", value="\n".join(exit_display_parts), inline=False)
            else:
                embed.add_field(name="Exits", value="None apparent.", inline=False)
        else: # This else corresponds to 'if connected_exits and ...'
            embed.add_field(name="Exits", value="None apparent.", inline=False)
            if exit_display_parts:
                embed.add_field(name="Exits", value="\n".join(exit_display_parts), inline=False)
            else:
                embed.add_field(name="Exits", value="None apparent.", inline=False)
        else:
            embed.add_field(name="Exits", value="None apparent.", inline=False)
        # else: # This else block for location_template_id check is no longer needed
            # embed.add_field(name="Exits", value="*Cannot determine exits: location template ID missing*", inline=False)
    else: # location_instance_id_str is None
        embed.add_field(name="Exits", value="*Cannot determine exits: current location ID missing*", inline=False)

    message_content = initial_message if initial_message else ""
    send_method = interaction.followup.send if followup else interaction.response.send_message

    # Ensure interaction.channel is sendable. For slash commands, it usually is.
    # If type errors persist here, a more specific channel type check might be needed.
    if hasattr(interaction.channel, 'send'):
        if message_content:
            await send_method(content=message_content, embed=embed, ephemeral=False)
        else:
            await send_method(embed=embed, ephemeral=False)
    else:
        print(f"Warning: interaction.channel (type: {type(interaction.channel)}) does not have send method in _send_location_embed.")
        # Fallback or error for non-sendable channels if necessary
        if followup:
             await interaction.followup.send("Error: Cannot send message to this channel type.", ephemeral=True)
        else:
             await interaction.response.send_message("Error: Cannot send message to this channel type.", ephemeral=True)


@app_commands.command(name="look", description="Look around your current location.")
async def cmd_look(interaction: Interaction):
    """Shows details about the player's current location."""
    await interaction.response.defer(ephemeral=False)
    bot = cast(RPGBot, interaction.client) # Used cast

    try:
        if not bot.game_manager or \
           not bot.game_manager.character_manager or \
           not bot.game_manager.location_manager or \
           not bot.game_manager.npc_manager:
            await interaction.followup.send("Error: Core game systems are not fully initialized.", ephemeral=True)
            return

        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        location_manager: Optional['LocationManager'] = bot.game_manager.location_manager # Make Optional for check
        npc_manager: 'NpcManager' = bot.game_manager.npc_manager

        if not location_manager:
            await interaction.followup.send("Error: Location manager is not available.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        character: Optional[CharacterModel] = character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id
        )
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        # current_location_id here refers to the location_instance_id
        current_location_instance_id = character.location_id
        if not current_location_instance_id:
            await interaction.followup.send("Error: Your character isn't anywhere. This is unusual. Contact an admin.", ephemeral=True)
            return

        # Fetch location instance data using the ID from the character model
        location_instance_data = location_manager.get_location_instance(guild_id_str, current_location_instance_id)
        if not location_instance_data:
            await interaction.followup.send(f"Error: Details for your location (Instance ID: {current_location_instance_id}) are missing.", ephemeral=True)
            return
        
        await _send_location_embed(
            interaction=interaction,
            location_data=location_instance_data,
            location_manager=location_manager, 
            npc_manager=npc_manager, 
            guild_id=guild_id_str, 
            followup=True
        )

    except Exception as e:
        print(f"Error in /look command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while looking around.", ephemeral=True)


@app_commands.command(name="move", description="Move to a connected location.")
@app_commands.describe(target_location_name="The name of the location you want to move to.")
async def cmd_move(interaction: Interaction, target_location_name: str):
    await interaction.response.defer(ephemeral=False)
    bot = cast(RPGBot, interaction.client) # Used cast

    try:
        if not bot.game_manager or \
           not bot.game_manager.character_manager or \
           not bot.game_manager.location_manager or \
           not bot.game_manager.party_manager or \
           not bot.game_manager.npc_manager or \
           not bot.game_manager._db_adapter: # Check for _db_adapter
            await interaction.followup.send("Error: Core game systems are not fully initialized. Please notify an admin.", ephemeral=True)
            return
        
        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        location_manager: Optional['LocationManager'] = bot.game_manager.location_manager # Make Optional for check
        party_manager: 'PartyManager' = bot.game_manager.party_manager
        npc_manager: 'NpcManager' = bot.game_manager.npc_manager
        db_adapter: 'SqliteAdapter' = bot.game_manager._db_adapter # Use _db_adapter

        if not location_manager:
            await interaction.followup.send("Error: Location manager is not available.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        character: Optional[CharacterModel] = character_manager.get_character_by_discord_id( # Removed await
            guild_id=guild_id_str,
            discord_user_id=discord_user_id
        )
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        current_location_instance_id = character.location_id
        if not current_location_instance_id:
            await interaction.followup.send("Error: Your character isn't anywhere. This is unusual. Contact an admin.", ephemeral=True)
            return

        current_location_instance_data = location_manager.get_location_instance(guild_id_str, current_location_instance_id)
        if not current_location_instance_data:
            await interaction.followup.send(f"Error: Cannot determine details for your current location (ID: {current_location_instance_id}). Contact an admin.", ephemeral=True)
            return
        
        current_location_template_id = current_location_instance_data.get('template_id')
        if not current_location_template_id:
            await interaction.followup.send(f"Error: Current location instance (ID: {current_location_instance_id}) is missing template ID. Cannot determine exits.", ephemeral=True)
            return

        target_location_name_stripped = target_location_name.strip().lower()
        found_target_template: Optional[Dict[str, Any]] = None # Will hold template data

        # Exits are defined on location templates, pointing to other location templates.
        # We need to find a target *template* whose name matches.
        # Then find an *instance* of that template in the guild.

        # Get valid exits from current location's *instance*
        # Get valid exits from current location's *template*
        # The method get_connected_locations now expects only guild_id and instance_id
        valid_exit_template_ids: Dict[str, str] = location_manager.get_connected_locations(
            guild_id=guild_id_str,
            instance_id=current_location_instance_id
        )

        target_exit_template_id: Optional[str] = None
        for exit_name, exit_tpl_id in valid_exit_template_ids.items():
            # Check if the exit name itself matches the target
            if exit_name.lower() == target_location_name_stripped:
                target_exit_template_id = exit_tpl_id
                break
            # If not, check the name of the target template
            target_template_candidate = location_manager.get_location_static(guild_id_str, exit_tpl_id) # Changed get_location_template_by_id to get_location_static
            if target_template_candidate and target_template_candidate.get('name','').lower() == target_location_name_stripped:
                target_exit_template_id = exit_tpl_id
                break
        
        if not target_exit_template_id:
            await interaction.followup.send(f"You can't directly move to '{target_location_name.strip()}' from '{current_location_instance_data.get('name', 'here')}'. Check the exits.", ephemeral=True)
            return

        # Now find an instance of this target template ID in the guild using the new manager method.
        target_location_instance_data = location_manager.find_active_instance_by_template_id(guild_id_str, target_exit_template_id)

        if not target_location_instance_data:
            # Try to get template name for a slightly better error message
            target_template_for_name = location_manager.get_location_static(guild_id_str, target_exit_template_id)
            target_name_for_error = target_template_for_name.get('name', 'the target location') if target_template_for_name else 'the target location'
            await interaction.followup.send(f"Found a path to {target_name_for_error}, but there's no active instance of it in this world right now.", ephemeral=True)
            return

        target_location_instance_id = target_location_instance_data.get('id')
        # found_target_location_instance_data is now target_location_instance_data, so no need for another get_location_instance call
        # if not target_location_instance_id: # This check is implicitly covered by "if not target_location_instance_data"
        #      await interaction.followup.send(f"Error: Target location instance data found, but it's missing an ID. Contact an admin.", ephemeral=True)
        #      return

        party = await party_manager.get_party_by_member_id(guild_id_str, character.id)
        
        entity_to_move_id: str = character.id
        entity_type: str = "Character"
        log_identifier: str = f"Character {character.name_i18n.get('en', character.id[:6])} (ID: {character.id})"
        display_name: str = character.name_i18n.get('en', character.id[:6])

        if party and party.id: # party.id should be a string
            entity_to_move_id = party.id
            entity_type = "Party"
            language = character.selected_language if character and character.selected_language else "en"
            party_name_display = party.name_i18n.get(language, party.id if party.id else "Unknown Party")
            log_identifier = f"Party {party_name_display} (ID: {party.id})"
            display_name = party_name_display
        
        # TODO: Comment out missing GameManager attributes for now
        move_kwargs: Dict[str, Any] = {
            # 'guild_id': guild_id_str, # guild_id is passed directly to move_entity
            'channel_id': interaction.channel_id,
            # 'send_callback_factory': bot.game_manager.send_callback_factory, # TODO: Fix in GameManager
            'character_manager': character_manager,
            'npc_manager': npc_manager,
            'item_manager': bot.game_manager.item_manager, # Assuming these exist
            'combat_manager': bot.game_manager.combat_manager,
            'status_manager': bot.game_manager.status_manager,
            'party_manager': party_manager,
            'time_manager': bot.game_manager.time_manager,
            'event_manager': bot.game_manager.event_manager,
            'rule_engine': bot.game_manager.rule_engine,
            # 'on_enter_action_executor': bot.game_manager.on_enter_action_executor, # TODO: Fix in GameManager
            # 'stage_description_generator': bot.game_manager.stage_description_generator, # TODO: Fix in GameManager
            'location_manager': location_manager,
        }
        
        old_location_name = current_location_instance_data.get('name', 'Unknown Starting Location')

        # Call move_entity with guild_id and other necessary parameters
        move_successful = await location_manager.move_entity(
            guild_id=guild_id_str,
            entity_id=entity_to_move_id,
            entity_type=entity_type,
            from_location_id=current_location_instance_id,
            to_location_id=target_location_instance_id,
            context=move_kwargs # Pass the constructed context dict as 'context'
        )

        if not move_successful:
            await interaction.followup.send(f"Movement of {display_name} to '{target_location_instance_data.get('name', target_location_name.strip())}' failed. You remain in '{old_location_name}'.", ephemeral=True)
            return
            
        # new_location_data_after_move is target_location_instance_data if the move was to this exact instance.
        # However, move_entity might create a new instance or modify it, so re-fetching is safer.
        new_location_data_after_move = location_manager.get_location_instance(guild_id_str, target_location_instance_id) if target_location_instance_id else None
        if not new_location_data_after_move:
            await interaction.followup.send("Moved, but couldn't ascertain new location details for the destination. This is odd!", ephemeral=True)
            return
            
        new_location_name = new_location_data_after_move.get('name', 'an unnamed place')
        
        try:
            log_message = f"{log_identifier} moved from {old_location_name} (Instance: {current_location_instance_id}) to {new_location_name} (Instance: {target_location_instance_id})."
            if bot.game_manager and bot.game_manager.game_log_manager:
                await bot.game_manager.game_log_manager.log_event(
                    guild_id=guild_id_str,
                    event_type="ENTITY_MOVE",
                    message=log_message,
                    related_entities_json=json.dumps({ # Ensure related_entities are passed as JSON string
                        "player_id": character.id,
                        "old_location_instance_id": current_location_instance_id,
                        "new_location_instance_id": target_location_instance_id,
                        "moved_entity_id": entity_to_move_id,
                        "moved_entity_type": entity_type,
                        "initiator_discord_user_id": discord_user_id,
                        "channel_id": interaction.channel_id if interaction.channel else None
                    })
                )
            else:
                print(f"Warning: GameLogManager not available. ENTITY_MOVE event for {log_identifier} not logged to DB.")
        except Exception as log_e:
            print(f"Error adding log entry for entity move: {log_e}")
            traceback.print_exc()

        move_feedback_message = f"{display_name} moved to {new_location_name}."
        await _send_location_embed(
            interaction=interaction,
            location_data=new_location_data_after_move,
            location_manager=location_manager, 
            npc_manager=npc_manager,
            guild_id=guild_id_str, 
            followup=True, 
            initial_message=move_feedback_message
        )

    except Exception as e:
        print(f"Error in /move command: {e}")
        traceback.print_exc()
        # Ensure followup is used if initial response was deferred and no other followup sent.
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("An unexpected server error occurred. Please try again later or contact an admin.",ephemeral=True)
            except discord.errors.InteractionResponded: # If somehow it got responded to
                 await interaction.followup.send("An unexpected server error occurred. Please try again later or contact an admin.", ephemeral=True)
        else:
            await interaction.followup.send("An unexpected server error occurred while trying to move. Please try again later or contact an admin.", ephemeral=True)


@app_commands.command(name="check", description="Выполнить проверку навыка.")
async def cmd_check(interaction: Interaction, skill_name: str, complexity: str = "medium", target_description: Optional[str] = None):
    await interaction.response.defer(ephemeral=True)
    # Removed bot = cast(RPGBot, interaction.client) as it's no longer needed for this simplified version.
    # Removed if not bot.game_manager: check as it's no longer relevant.

    if not hasattr(interaction.client, 'game_manager'):
        await interaction.followup.send("**Ошибка Мастера:** Игровая система (GameManager) не найдена на клиенте.", ephemeral=True)
        return

    if not bot.game_manager: # Check if game_manager itself is None on RPGBot instance
        await interaction.followup.send("**Ошибка Мастера:** Игровая система (GameManager) не инициализирована.", ephemeral=True)
        return

    try:
        from bot.bot_core import get_bot_instance # global_game_manager is not needed
        game_mngr = bot.game_manager # Use the already available game_mngr from RPGBot instance
        get_bot_instance_func = get_bot_instance # For consistency if used elsewhere
        if game_mngr: # Check if game_mngr (GameManager instance) is available
            global_game_manager_imported_successfully = True # Consider this path successful if game_mngr exists
    except ImportError:
        pass # Keep pass for the case where bot_core itself has issues, though unlikely here

    if global_game_manager_imported_successfully and game_mngr: # Check game_mngr
        response_data = await game_mngr.process_player_action(
            server_id=str(interaction.guild_id), # Ensure guild_id is string
    game_mngr_instance = bot.game_manager
        
    if hasattr(game_mngr_instance, 'process_player_action'):
        response_data = await game_mngr_instance.process_player_action(
            server_id=str(interaction.guild_id),
            discord_user_id=interaction.user.id,
            action_type="skill_check",
            action_data={
                "skill_name": skill_name,
                "complexity": complexity,
                "target_description": target_description or f"совершить действие, требующее навыка {skill_name}"
            }
            # ctx_channel_id is not a parameter of process_player_action
        )
        
        target_channel_id_any = response_data.get("target_channel_id", interaction.channel_id)
        target_channel_id: Optional[int] = None
        if isinstance(target_channel_id_any, (str, int)):
            try:
                target_channel_id = int(target_channel_id_any)
            except ValueError:
                print(f"Warning: target_channel_id '{target_channel_id_any}' is not a valid integer. Defaulting to interaction channel.")
                if interaction.channel: target_channel_id = interaction.channel.id
        elif interaction.channel: # if target_channel_id_any was None or other type
             target_channel_id = interaction.channel.id


        bot_instance_for_channel = bot # Use the RPGBot instance directly
        
        target_channel: Optional[discord.abc.Messageable] = None # Use Messageable for broader type compatibility
        if bot_instance_for_channel and target_channel_id:
            # Ensure target_channel_id is an int if get_channel expects an int
            try:
                # get_channel can return various types, ensure it's Messageable
                fetched_channel = bot_instance_for_channel.get_channel(int(target_channel_id))
                if isinstance(fetched_channel, discord.abc.Messageable):
                    target_channel = fetched_channel
                else:
                    print(f"Warning: Fetched channel {target_channel_id} is not Messageable. Type: {type(fetched_channel)}. Falling back to interaction.channel.")
                    if interaction.channel and isinstance(interaction.channel, discord.abc.Messageable):
                        target_channel = interaction.channel
                    else: # If interaction.channel is also not messageable (e.g. thread without send perms)
                        target_channel = None


            except ValueError: # Should be caught by earlier int conversion, but as safeguard
                print(f"Warning: target_channel_id '{target_channel_id}' is not a valid integer. Falling back to interaction.channel.")
                if interaction.channel and isinstance(interaction.channel, discord.abc.Messageable): # Check type for interaction.channel
                    target_channel = interaction.channel
                else:
                    target_channel = None

        else: # Fallback to interaction.channel if bot_instance or target_channel_id is problematic
            if interaction.channel and isinstance(interaction.channel, discord.abc.Messageable): # Check type for interaction.channel
                target_channel = interaction.channel
            else:
                target_channel = None


        message_to_send = response_data.get("message", "Произошла ошибка при выполнении проверки.")

        # Check if interaction.channel itself is Messageable
        interaction_channel_is_messageable = isinstance(interaction.channel, discord.abc.Messageable)


        # Check if target_channel is valid and different from interaction.channel
        if target_channel and target_channel.id != (interaction.channel.id if interaction.channel else None) :
            try:
                await target_channel.send(message_to_send)
                # Always send a followup to the interaction itself if the main message went to a different channel
                await interaction.followup.send(f"You attempt a {skill_name} check... (Response sent to designated channel).", ephemeral=True)
            except discord.errors.Forbidden:
                 await interaction.followup.send(f"I don't have permissions to send messages to channel {target_channel.mention}.", ephemeral=True)
            except Exception as send_e:
                 print(f"Error sending to target_channel {target_channel.id}: {send_e}")
                 await interaction.followup.send("Failed to send response to the target channel due to an error.", ephemeral=True)

        else: # Send to the interaction's channel (as followup)
            if interaction_channel_is_messageable: # Check if interaction.channel can even send messages
                await interaction.followup.send(message_to_send, ephemeral=True)
            else:
                print(f"Error: interaction.channel is not sendable and target_channel was not suitable. Message: {message_to_send}")
                # As a last resort, try to send to followup if the interaction itself is the problem, though this is unlikely if defer worked.
                await interaction.followup.send("Error: Could not send message to the channel.", ephemeral=True)
    else:
        # This 'else' corresponds to 'if global_game_manager_imported_successfully and global_game_manager_instance:'
        await interaction.followup.send("**Ошибка Мастера:** Игровая система недоступна или не инициализирована должным образом для команды /check.", ephemeral=True)
    # New logic: Inform user that the command is under rework.
    await interaction.followup.send(
        "The '/check' command is currently undergoing improvements and is temporarily unavailable. Please try again later.",
        ephemeral=True
    )
            else: # If interaction.channel is not messageable (e.g. None, or a non-text channel type somehow)
                print(f"Error: interaction.channel is not Messageable. Cannot send skill check result. Message: {message_to_send}")
                # Fallback, try to send to followup, though it might also fail if interaction context is broken
                try:
                    await interaction.followup.send("Error: Could not send message to the current channel context.", ephemeral=True)
                except Exception as final_send_e:
                    print(f"CRITICAL: Failed to send any response for /check command: {final_send_e}")

    else: # Corresponds to if hasattr(game_mngr_instance, 'process_player_action'):
        await interaction.followup.send("The '/check' command's underlying action processing is currently unavailable.", ephemeral=True)
        return

# Note: The _generate_location_details_embed function was not directly mentioned for changes
# in the prompt other than how it's called. Assuming its internal logic is fine for now,
# but its calls to location_manager.get_location_template_by_id were changed to get_location_static
# as part of fixing point 3.

# If _generate_location_details_embed itself also calls the old method name, it would need fixing too.
# Re-checking its definition in the provided file:
# _generate_location_details_embed calls:
# location_manager.get_connected_locations(...) - this seems fine.
# location_manager.get_location_template_by_id(...) - THIS NEEDS TO CHANGE to get_location_static.
# The previous diff for _send_location_embed already covered this change.
# The prompt for cmd_check (point 6) was about the parameter name in its call to _generate_location_details_embed.
# The prompt for cmd_move (point 2) was about the parameter name in its call to _generate_location_details_embed.

# Let's ensure the calls in cmd_move and cmd_check to _generate_location_details_embed use current_location_id.
# This was planned. The definition of _generate_location_details_embed itself was not part of this subtask's changes beyond what was caught by point 3.
# The change from location_id to current_location_id is in the *callers* of _generate_location_details_embed.
# The patch for _send_location_embed already fixed its internal call to get_location_static.
# The function _generate_location_details_embed is not present in the provided exploration_cmds.py.
# The calls were to _send_location_embed which was already handled.
# Point 2 and 6 are about calls to _generate_location_details_embed, which is not in the file.
# It seems there might be a mix-up with _send_location_embed.
# The prompt references lines 75 and 234 for these calls.
# Line 75 in the provided file for exploration_cmds.py is within cmd_look, not cmd_move's call.
# Line 234 is within cmd_move.
# The function _send_location_embed is called by cmd_look and cmd_move.
# _send_location_embed's signature is: _send_location_embed(interaction, location_data, location_manager, npc_manager, guild_id, followup, initial_message)
# It does not take current_location_id or location_name directly in that way.
# Points 2 and 6 seem to refer to a function that is not _send_location_embed.
# If _generate_location_details_embed was an old function, and the calls were updated to use _send_location_embed,
# then points 2 and 6 might be resolved or no longer applicable as stated.
# Given the current file content, I will assume points 2 and 6 are either misinterpretations of the error log
# or refer to a state of the file not represented by the last read. I will skip explicit changes for points 2 and 6
# if they refer to a non-existent function signature.
# The prompt was "No parameter named location_id in cmd_move" (and check) referring to calls to _generate_location_details_embed.
# Since that function is not in the file, I cannot change its call.
# I will proceed with other changes.

# Re-evaluating point 7 for cmd_check:
# The provided `cmd_check` is currently:
# async def cmd_check(interaction: Interaction, skill_name: str, complexity: str = "medium", target_description: Optional[str] = None):
#    ...
#    await interaction.followup.send("The '/check' command is currently being reworked. Please try again later.", ephemeral=True)
# There is no `party_manager.get_party_by_member_id` call in the current `cmd_check`.
# So point 7 is not applicable to `cmd_check` as it stands.
# It might be applicable to `_send_location_embed` if it were to fetch party details, but it doesn't.
# Or it's for another command. For this file, I will ignore point 7 for `cmd_check`.
# The attribute error on coroutine type for party would be in `cmd_move` if `await` was missing.
# In `cmd_move`, the line is `party = party_manager.get_party_by_member_id(guild_id_str, character.id)`.
# I've added `await` there. Then added `if party:` check. This covers point 7 for `cmd_move`.
