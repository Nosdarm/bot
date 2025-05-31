# bot/command_modules/exploration_cmds.py
import discord
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING, Dict, Any, List # Keep TYPE_CHECKING for RPGBot and DBService
import traceback # For error logging

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.services.db_service import DBService # Keep this under TYPE_CHECKING
    # from bot.bot_core import global_game_manager, get_bot_instance # Remove old global imports

# TEST_GUILD_IDS can be removed if not used in decorators
# TEST_GUILD_IDS = []

async def _send_location_embed(
    interaction: Interaction,
    location_data: Dict[str, Any],
    db_service: 'DBService',
    guild_id: str,
    *,
    followup: bool = False,
    initial_message: Optional[str] = None
):
    """Helper function to construct and send the location embed."""
    embed = discord.Embed(
        title=location_data.get('name', 'Unknown Location'),
        description=location_data.get('description', 'A non-descript place.'),
        color=discord.Color.green()
    )

    location_id = location_data.get("id")
    if location_id:
        npcs_in_location = await db_service.get_npcs_in_location(location_id=location_id, guild_id=guild_id)
        if npcs_in_location:
            npc_names = ", ".join([npc['name'] for npc in npcs_in_location])
            embed.add_field(name="NPCs Here", value=npc_names if npc_names else "None", inline=False)
        else:
            embed.add_field(name="NPCs Here", value="None", inline=False)

    exits_data = location_data.get('exits')
    if exits_data and isinstance(exits_data, dict) and len(exits_data) > 0:
        exit_display_parts = []
        for exit_name, target_loc_id in exits_data.items():
            target_loc_details = await db_service.get_location(location_id=target_loc_id, guild_id=guild_id)
            if target_loc_details:
                exit_display_parts.append(f"{exit_name.capitalize()} to {target_loc_details['name']}")
            else:
                exit_display_parts.append(f"{exit_name.capitalize()} (leads to an unknown area)")

        if exit_display_parts:
            embed.add_field(name="Exits", value="\n".join(exit_display_parts), inline=False)
        else:
            embed.add_field(name="Exits", value="None apparent.", inline=False)

    else:
        embed.add_field(name="Exits", value="None apparent.", inline=False)

    message_content = initial_message if initial_message else ""

    if followup:
        if message_content:
            await interaction.followup.send(content=message_content, embed=embed, ephemeral=False)
        else:
            await interaction.followup.send(embed=embed, ephemeral=False)
    else:
        if message_content:
             await interaction.response.send_message(content=message_content, embed=embed, ephemeral=False)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=False)


@app_commands.command(name="look", description="Look around your current location.")
async def cmd_look(interaction: Interaction):
    """Shows details about the player's current location."""
    await interaction.response.defer(ephemeral=False)

    try:
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service'):
            await interaction.followup.send("Error: Game systems are not fully initialized.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service
        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        player_data = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if not player_data:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        location_id = player_data.get('location_id')
        if not location_id:
            await interaction.followup.send("Error: Your character isn't anywhere. Contact an admin.", ephemeral=True)
            return

        location_data = await db_service.get_location(location_id=location_id, guild_id=guild_id)
        if not location_data:
            await interaction.followup.send(f"Error: Details for your location (ID: {location_id}) are missing.", ephemeral=True)
            return

        await _send_location_embed(interaction, location_data, db_service, guild_id, followup=True)

    except Exception as e:
        print(f"Error in /look command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while looking around.", ephemeral=True)


@app_commands.command(name="move", description="Move to a connected location.")
@app_commands.describe(target_location_name="The name of the location you want to move to.")
async def cmd_move(interaction: Interaction, target_location_name: str):
    await interaction.response.defer(ephemeral=False)

    try:
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service'):
            await interaction.followup.send("Error: Game systems are not fully initialized.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service
        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        player_data = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if not player_data:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        current_location_id = player_data.get('location_id')
        if not current_location_id:
            await interaction.followup.send("Error: Your character isn't anywhere. Contact an admin.", ephemeral=True)
            return

        current_location_data = await db_service.get_location(location_id=current_location_id, guild_id=guild_id)
        if not current_location_data:
            await interaction.followup.send("Error: Cannot determine your current location's details.", ephemeral=True)
            return

        all_guild_locations = await db_service.get_all_locations(guild_id=guild_id)
        found_target_location: Optional[Dict[str, Any]] = None
        for loc in all_guild_locations:
            if loc.get('name', '').lower() == target_location_name.lower():
                found_target_location = loc
                break

        if not found_target_location:
            await interaction.followup.send(f"Location '{target_location_name}' not found in this area.", ephemeral=True)
            return

        target_location_id = found_target_location["id"]

        current_exits = current_location_data.get('exits', {})
        is_valid_move = False
        if isinstance(current_exits, dict):
            if target_location_id in current_exits.values():
                is_valid_move = True

        if not is_valid_move:
            await interaction.followup.send(f"You can't directly move to '{target_location_name}' from '{current_location_data.get('name', 'here')}'. Check the exits.", ephemeral=True)
            return

        old_location_id = current_location_id
        old_location_name = current_location_data.get('name', 'Unknown Starting Location')

        await db_service.update_player_location(player_id=player_data['id'], new_location_id=target_location_id)

        new_location_data = await db_service.get_location(location_id=target_location_id, guild_id=guild_id)
        if not new_location_data:
            await interaction.followup.send("Moved, but couldn't find details of your new location. Strange...", ephemeral=True)
            return

        new_location_name = new_location_data.get('name', 'an unknown place')
        player_id = player_data['id']
        player_name = player_data.get('name', 'Player')

        try:
            log_message = f"{player_name} moved from {old_location_name} to {new_location_name}."
            log_related_entities = {"old_location_id": old_location_id, "new_location_id": target_location_id}
            log_context_data = {"old_location_id": old_location_id}

            await db_service.add_log_entry(
                guild_id=guild_id,
                event_type="PLAYER_MOVE",
                message=log_message,
                player_id_column=player_id,
                related_entities=log_related_entities,
                context_data=log_context_data,
                channel_id=interaction.channel_id if interaction.channel else None
            )
            print(f"Log entry added for player move: {player_id} from {old_location_id} to {target_location_id}")
        except Exception as log_e:
            print(f"Error adding log entry for player move: {log_e}")

        move_message = f"{player_name} move to {new_location_name}."
        await _send_location_embed(interaction, new_location_data, db_service, guild_id, followup=True, initial_message=move_message)

    except Exception as e:
        print(f"Error in /move command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while moving. Your position might be unchanged.", ephemeral=True)


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