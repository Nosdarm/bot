# bot/command_modules/exploration_cmds.py
import discord
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING, Dict, Any, List # Keep TYPE_CHECKING for RPGBot and DBService
import traceback # For error logging

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.services.db_service import DBService # Keep this under TYPE_CHECKING for logging for now
    # Import Manager types for type hinting
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.npc_manager import NpcManager
    # from bot.bot_core import global_game_manager, get_bot_instance # Remove old global imports

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

    location_instance_id = location_data.get("id")
    if location_instance_id:
        # Assuming NpcManager has a method get_npcs_in_location or similar
        # This method should take guild_id and location_instance_id
        # For now, let's assume it returns a list of objects with a 'name' attribute.
        try:
            # NPCs list - assuming NpcManager has get_npcs_in_location(guild_id, location_id)
            # This method might need to be created or adjusted in NpcManager.
            # For now, if it's not there, this will be an empty list or needs a placeholder.
            # Also assuming NpcManager is injected and available.
            npcs_in_location = npc_manager.get_npcs_in_location(guild_id=guild_id, location_instance_id=location_instance_id)
            if npcs_in_location:
                npc_names = ", ".join([getattr(npc, 'name', 'Unnamed NPC') for npc in npcs_in_location])
                embed.add_field(name="NPCs Here", value=npc_names if npc_names else "None", inline=False)
            else:
                embed.add_field(name="NPCs Here", value="None", inline=False)
        except AttributeError: # If NpcManager or method is missing
             embed.add_field(name="NPCs Here", value="*NPC data currently unavailable*", inline=False)
        except Exception as e:
            print(f"Error fetching NPCs for embed: {e}")
            embed.add_field(name="NPCs Here", value="Error loading NPCs.", inline=False)


    # Exits - using location_manager
    connected_exits = location_manager.get_connected_locations(guild_id, location_instance_id)
    if connected_exits and isinstance(connected_exits, dict) and len(connected_exits) > 0:
        exit_display_parts = []
        for exit_name_or_direction, target_loc_instance_id in connected_exits.items():
            # For each exit, get the name of the target location instance
            target_loc_instance_data = location_manager.get_location_instance(guild_id, target_loc_instance_id)
            if target_loc_instance_data:
                exit_display_parts.append(f"{exit_name_or_direction.capitalize()} to {target_loc_instance_data.get('name', 'an unnamed area')}")
            else:
                # This case should ideally not happen if get_connected_locations is robust
                exit_display_parts.append(f"{exit_name_or_direction.capitalize()} (leads to an unknown area - ID: {target_loc_instance_id[:6]})")
        
        if exit_display_parts:
            embed.add_field(name="Exits", value="\n".join(exit_display_parts), inline=False)
        else: # Should not happen if connected_exits is not empty
            embed.add_field(name="Exits", value="None apparent.", inline=False)
    else:
        embed.add_field(name="Exits", value="None apparent.", inline=False)

    message_content = initial_message if initial_message else ""

    if followup:
        if message_content:
            await interaction.followup.send(content=message_content, embed=embed, ephemeral=False)
        else:
            await interaction.followup.send(embed=embed, ephemeral=False)
    else: # This branch might not be used by /move which uses followup=True
        if message_content:
             await interaction.response.send_message(content=message_content, embed=embed, ephemeral=False)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=False)


@app_commands.command(name="look", description="Look around your current location.")
async def cmd_look(interaction: Interaction):
    """Shows details about the player's current location."""
    await interaction.response.defer(ephemeral=False)

    try:
        # Ensure game_manager and its core components are available
        if not hasattr(interaction.client, 'game_manager') or \
           not interaction.client.game_manager or \
           not hasattr(interaction.client.game_manager, 'character_manager') or \
           not hasattr(interaction.client.game_manager, 'location_manager') or \
           not hasattr(interaction.client.game_manager, 'npc_manager'):
            await interaction.followup.send("Error: Core game systems are not fully initialized.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        game_manager = client_bot.game_manager
        character_manager: 'CharacterManager' = game_manager.character_manager
        location_manager: 'LocationManager' = game_manager.location_manager
        npc_manager: 'NpcManager' = game_manager.npc_manager

        guild_id_str = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id)
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        current_location_id = getattr(character, 'current_location_id', None)
        if not current_location_id: # Should be set if character exists
            await interaction.followup.send("Error: Your character isn't anywhere. This is unusual. Contact an admin.", ephemeral=True)
            return

        location_data = location_manager.get_location_instance(guild_id_str, current_location_id)
        if not location_data:
            await interaction.followup.send(f"Error: Details for your location (ID: {current_location_id}) are missing.", ephemeral=True)
            return
        
        # Use the refactored _send_location_embed
        await _send_location_embed(
            interaction, 
            location_data, 
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

    try:
        # Ensure game_manager and its core components are available
        if not hasattr(interaction.client, 'game_manager') or \
           not interaction.client.game_manager or \
           not hasattr(interaction.client.game_manager, 'character_manager') or \
           not hasattr(interaction.client.game_manager, 'location_manager') or \
           not hasattr(interaction.client.game_manager, 'party_manager') or \
           not hasattr(interaction.client.game_manager, 'npc_manager') or \
           not hasattr(interaction.client.game_manager, 'item_manager') or \
           not hasattr(interaction.client.game_manager, 'combat_manager') or \
           not hasattr(interaction.client.game_manager, 'status_manager') or \
           not hasattr(interaction.client.game_manager, 'time_manager') or \
           not hasattr(interaction.client.game_manager, 'event_manager') or \
           not hasattr(interaction.client.game_manager, 'rule_engine') or \
           not hasattr(interaction.client.game_manager, 'on_enter_action_executor') or \
           not hasattr(interaction.client.game_manager, 'stage_description_generator') or \
           not hasattr(interaction.client.game_manager, 'send_callback_factory') or \
           not hasattr(interaction.client.game_manager, 'db_service'): # db_service for logging
            await interaction.followup.send("Error: Core game systems are not fully initialized. Please notify an admin.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        game_manager = client_bot.game_manager
        
        # Access managers from game_manager
        location_manager: 'LocationManager' = game_manager.location_manager
        character_manager: 'CharacterManager' = game_manager.character_manager
        party_manager: 'PartyManager' = game_manager.party_manager
        npc_manager: 'NpcManager' = game_manager.npc_manager
        db_service: 'DBService' = game_manager.db_service # For logging, temporarily

        guild_id_str = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        # 1. Fetch Player State
        character = await character_manager.get_character_by_discord_id(guild_id_str, discord_user_id)
        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        current_location_id = getattr(character, 'current_location_id', None)
        if not current_location_id: 
            await interaction.followup.send("Error: Your character isn't anywhere. This is unusual. Contact an admin.", ephemeral=True)
            return

        # 2. Fetch Current Location State
        current_location_data = location_manager.get_location_instance(guild_id_str, current_location_id)
        if not current_location_data:
            await interaction.followup.send(f"Error: Cannot determine details for your current location (ID: {current_location_id}). Contact an admin.", ephemeral=True)
            return
        
        # 3. Resolve Target Location by name (case-insensitive, strip whitespace)
        target_location_name_stripped = target_location_name.strip().lower()
        found_target_location: Optional[Dict[str, Any]] = None
        guild_location_instances_cache = location_manager._location_instances.get(guild_id_str, {})
        for loc_instance_data in guild_location_instances_cache.values():
            if loc_instance_data.get('name', '').lower() == target_location_name_stripped:
                found_target_location = loc_instance_data
                break
        
        if not found_target_location:
            await interaction.followup.send(f"Location '{target_location_name.strip()}' not found.", ephemeral=True)
            return

        target_location_id = found_target_location["id"]

        # 4. Validate Move 
        valid_exits = location_manager.get_connected_locations(guild_id_str, current_location_id)
        if target_location_id not in valid_exits.values():
            await interaction.followup.send(f"You can't directly move to '{found_target_location.get('name',target_location_name.strip())}' from '{current_location_data.get('name', 'here')}'. Check the exits.", ephemeral=True)
            return

        # 5. Determine Mover (Player or Party)
        party = await party_manager.get_party_by_member_id(guild_id_str, character.id) 
        
        entity_to_move_id: str
        entity_type: str
        log_identifier: str
        display_name: str

        if party and getattr(party, 'id', None):
            entity_to_move_id = party.id
            entity_type = "Party"
            party_name = getattr(party, 'name', f"Party {party.id[:6]}")
            log_identifier = f"Party {party_name} (ID: {party.id})"
            display_name = party_name
        else:
            entity_to_move_id = character.id
            entity_type = "Character"
            character_name = getattr(character, 'name', f"Character {character.id[:6]}")
            log_identifier = f"Character {character_name} (ID: {character.id})"
            display_name = character_name
        
        move_kwargs: Dict[str, Any] = {
            'guild_id': guild_id_str,
            'channel_id': interaction.channel_id,
            'send_callback_factory': game_manager.send_callback_factory,
            'character_manager': character_manager,
            'npc_manager': npc_manager,
            'item_manager': game_manager.item_manager,
            'combat_manager': game_manager.combat_manager,
            'status_manager': game_manager.status_manager,
            'party_manager': party_manager,
            'time_manager': game_manager.time_manager,
            'event_manager': game_manager.event_manager,
            'rule_engine': game_manager.rule_engine,
            'on_enter_action_executor': game_manager.on_enter_action_executor,
            'stage_description_generator': game_manager.stage_description_generator,
            'location_manager': location_manager,
        }
        
        old_location_name = current_location_data.get('name', 'Unknown Starting Location')

        move_successful = await location_manager.move_entity(
            guild_id=guild_id_str, 
            entity_id=entity_to_move_id,
            entity_type=entity_type,
            from_location_id=current_location_id,
            to_location_id=target_location_id,
            **move_kwargs
        )

        if not move_successful:
            await interaction.followup.send(f"Movement of {display_name} to '{found_target_location.get('name', target_location_name.strip())}' failed. You remain in '{old_location_name}'.", ephemeral=True)
            return
            
        new_location_data_after_move = location_manager.get_location_instance(guild_id_str, target_location_id)
        if not new_location_data_after_move: 
            await interaction.followup.send("Moved, but couldn't ascertain new location details. This is odd!", ephemeral=True)
            return
            
        new_location_name = new_location_data_after_move.get('name', 'an unnamed place')
        
        # 6. Logging 
        try:
            log_message = f"{log_identifier} moved from {old_location_name} to {new_location_name}."
            log_actor_id = character.id 
            await db_service.add_log_entry(
                guild_id=guild_id_str,
                event_type="ENTITY_MOVE",
                message=log_message,
                player_id_column=log_actor_id, 
                related_entities={
                    "old_location_id": current_location_id, 
                    "new_location_id": target_location_id, 
                    "moved_entity_id": entity_to_move_id, 
                    "moved_entity_type": entity_type
                },
                context_data={"initiator_discord_user_id": discord_user_id},
                channel_id=interaction.channel_id if interaction.channel else None
            )
            print(f"Log entry added: {log_identifier} moved from {current_location_id} to {target_location_id}")
        except Exception as log_e:
            print(f"Error adding log entry for entity move: {log_e}")
            traceback.print_exc()

        # 7. Provide Feedback
        move_feedback_message = f"{display_name} moved to {new_location_name}."
        await _send_location_embed(
            interaction, 
            new_location_data_after_move, 
            location_manager=location_manager, 
            npc_manager=npc_manager,
            guild_id=guild_id_str, 
            followup=True, 
            initial_message=move_feedback_message
        )

    except Exception as e:
        print(f"Error in /move command: {e}")
        traceback.print_exc()
        if interaction.response.is_done():
            await interaction.followup.send("An unexpected server error occurred while trying to move. Please try again later or contact an admin.", ephemeral=True)
        else:
            await interaction.response.send_message("An unexpected server error occurred. Please try again later or contact an admin.",ephemeral=True)


@app_commands.command(name="check", description="Выполнить проверку навыка.")
async def cmd_check(interaction: Interaction, skill_name: str, complexity: str = "medium", target_description: Optional[str] = None):
    await interaction.response.defer(ephemeral=True)

    # TODO: Refactor /check to use DBService and interaction.client.game_manager
    game_manager_accessible_via_client = hasattr(interaction.client, 'game_manager') and \
                                         interaction.client.game_manager is not None

    global_game_manager_imported_successfully = False
    global_game_manager_instance = None
    get_bot_instance_func = None

    try:
        from bot.bot_core import global_game_manager as ggm, get_bot_instance as gbi
        global_game_manager_instance = ggm
        get_bot_instance_func = gbi
        if global_game_manager_instance:
            global_game_manager_imported_successfully = True
    except ImportError:
        pass

    if global_game_manager_imported_successfully and global_game_manager_instance:
        response_data = await global_game_manager_instance.process_player_action(
            server_id=interaction.guild_id,
            discord_user_id=interaction.user.id,
            action_type="skill_check",
            action_data={
                "skill_name": skill_name,
                "complexity": complexity,
                "target_description": target_description or f"совершить действие, требующее навыка {skill_name}"
            },
            ctx_channel_id=interaction.channel_id
        )
        target_channel_id = response_data.get("target_channel_id", interaction.channel_id)
        bot_instance_for_channel = get_bot_instance_func() if get_bot_instance_func else None
        target_channel = bot_instance_for_channel.get_channel(target_channel_id) if bot_instance_for_channel else None
        message_to_send = response_data.get("message", "Произошла ошибка при выполнении проверки.")

        if target_channel and target_channel.id != interaction.channel_id :
            await target_channel.send(message_to_send)
            await interaction.followup.send(f"You attempt a {skill_name} check...", ephemeral=True)
        else:
            await interaction.followup.send(message_to_send, ephemeral=True)

    elif game_manager_accessible_via_client:
        await interaction.followup.send("'/check' command is awaiting full refactor to the new system. For now, it's offline.", ephemeral=True)
    else:
        await interaction.followup.send("**Ошибка Мастера:** Игровая система недоступна.", ephemeral=True)
