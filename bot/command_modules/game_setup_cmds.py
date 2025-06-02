# bot/command_modules/game_setup_cmds.py

import discord
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING
import traceback # Added traceback import

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # For type hinting interaction.client
    from bot.services.db_service import DBService

# --- Placeholder functions for imports in bot_core.py ---
# These are not used by /start but are imported by bot_core.py
# so they need to exist.
def is_master_or_admin(ctx) -> bool:
    # Replace with actual logic if needed elsewhere
    print(f"DEBUG: is_master_or_admin called for {ctx.user.id}. Placeholder returning True.")
    return True

def is_gm_channel(ctx) -> bool:
    # Replace with actual logic if needed elsewhere
    print(f"DEBUG: is_gm_channel called for channel {ctx.channel.id}. Placeholder returning True.")
    return True
# --- End Placeholder functions ---

# Example command that might have been here before, for structure.
@app_commands.command(name="start_game", description="GM Command: Starts a new game session in this channel.")
async def cmd_start_game(interaction: Interaction):
    await interaction.response.send_message("Placeholder for starting a new game.", ephemeral=True)

@app_commands.command(name="join_game", description="Join the current game session.")
async def cmd_join_game(interaction: Interaction):
    await interaction.response.send_message("Placeholder for joining game.", ephemeral=True)


# --- /start command ---
@app_commands.command(name="start", description="Create your character and begin your adventure!")
@app_commands.describe(
    name="Your character's name.",
    race="Your character's race (e.g., Human, Elf, Dwarf)."
)
async def cmd_start_new_character(interaction: Interaction, name: str, race: str):
    """
    Allows a player to create a new character if they don't already have one in the guild.
    """
    await interaction.response.defer(ephemeral=True) # Defer for potentially slow DB operations

    try:
        # Access DBService via interaction.client (which is RPGBot instance)
        # then game_manager, then db_service
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service'):
            await interaction.followup.send("Error: The game systems are not fully initialized. Please try again later.", ephemeral=True)
            return

        # Type hint for clarity after checks
        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service

        if not db_service: # Should not happen if game_manager has it
            await interaction.followup.send("Error: Database service is unavailable. Please contact an admin.", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        # 1. Check for Existing Character
        existing_player = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if existing_player:
            await interaction.followup.send(f"Welcome back, {existing_player['name']}! You already have a character in this world. Use `/look` to see your surroundings.", ephemeral=True)
            return

        # 2. Create New Character
        # Default values
        starting_location_id = "town_square" # Default starting location
        default_hp = 100
        default_mp = 50
        default_attack = 10
        default_defense = 5
        default_stats = {"strength": 10, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10}

        # player_id for DBService.create_player can be None if DBService/adapter handles generation,
        # or we can generate one here (e.g., UUID).
        # DBService.create_player expects player_id or generates a composite one.
        # Let DBService handle player_id generation as per its implementation.

        new_player_data = await db_service.create_player(
            discord_user_id=discord_user_id,
            name=name,
            race=race,
            guild_id=guild_id,
            location_id=starting_location_id,
            hp=default_hp,
            mp=default_mp,
            attack=default_attack, # This will go into stats if not a direct column
            defense=default_defense, # This will go into stats if not a direct column
            stats=default_stats,
            level=1,
            experience=0,
            unspent_xp=0,
            current_game_status='исследование' # Set default status
            # player_id can be omitted if DBService handles it
        )

        if not new_player_data:
            await interaction.followup.send("There was an error creating your character. Please try again or contact an admin.", ephemeral=True)
            return

        # 3. Success Message
        # Fetch location name for the message
        location_data = await db_service.get_location(starting_location_id, guild_id=guild_id)
        location_name = location_data['name'] if location_data else starting_location_id

        response_message = (
            f"Welcome, {new_player_data['name']} the {new_player_data['race']}! Your adventure begins in {location_name}.\n"
            f"Use `/look` to see your surroundings."
        )
        await interaction.followup.send(response_message, ephemeral=False) # Send publicly

    except Exception as e:
        print(f"Error in /start command: {e}")
        traceback.print_exc()
        if interaction.response.is_done():
            await interaction.followup.send("An unexpected error occurred while starting your adventure. Please try again later.", ephemeral=True)
        else:
            # This case should ideally not happen if we defer properly
            try:
                await interaction.response.send_message("An unexpected error occurred. Please try again later.", ephemeral=True)
            except discord.errors.InteractionResponded: # If somehow it got responded to between error and here
                 await interaction.followup.send("An unexpected error occurred. Please try again later.", ephemeral=True)
