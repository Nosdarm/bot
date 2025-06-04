# bot/command_modules/game_setup_cmds.py

import discord
from discord import app_commands, Interaction
from discord.app_commands import Choice as app_commands_Choice # Explicitly import Choice
from typing import Optional, TYPE_CHECKING, cast
import traceback

# Corrected imports
if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.services.db_service import DBService # This is likely the SqliteAdapter or similar
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.models.character import Character as CharacterModel


# Helper functions used by bot_core.py
def is_master_or_admin(interaction: Interaction, game_manager: Optional['GameManager']) -> bool:
    # TODO: Implement actual logic for checking GM/admin roles based on game_manager settings or Discord roles.
    # For now, this is a placeholder.
    if not game_manager:
        print("DEBUG: is_master_or_admin called but GameManager is None. Denying.")
        return False # Cannot verify without game_manager

    # Example: Check if user has a specific role ID stored in game_manager settings for this guild
    # guild_settings = game_manager.get_guild_settings(str(interaction.guild_id))
    # admin_role_id = guild_settings.get('admin_role_id')
    # if admin_role_id and interaction.user.get_role(admin_role_id):
    #     return True
    # Fallback to checking Discord permissions if no specific role is set
    if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
        print(f"DEBUG: is_master_or_admin: User {interaction.user.id} is a Discord admin in guild {interaction.guild_id}.")
        return True

    print(f"DEBUG: is_master_or_admin called for {interaction.user.id}. Placeholder logic used, returning True if admin, else False.")
    # This placeholder might need to be more restrictive depending on actual requirements.
    # For safety, let's default to False if no other condition met.
    return False # Default to False if not a Discord admin and no other GM logic implemented


def is_gm_channel(interaction: Interaction, game_manager: Optional['GameManager']) -> bool:
    # TODO: Implement actual logic for checking if the channel is a designated GM channel.
    if not game_manager:
        print("DEBUG: is_gm_channel called but GameManager is None. Denying.")
        return False

    # Example: Check if channel ID is in a list of GM channels stored in game_manager settings for this guild
    # guild_settings = game_manager.get_guild_settings(str(interaction.guild_id))
    # gm_channel_ids = guild_settings.get('gm_channel_ids', [])
    # if interaction.channel_id in gm_channel_ids:
    #     return True

    print(f"DEBUG: is_gm_channel called for channel {interaction.channel_id}. Placeholder returning True.")
    return True # Placeholder, assume any channel is fine for now. Should be more restrictive.


# Example command (remains placeholder as per original structure)
@app_commands.command(name="start_game", description="GM Command: Starts a new game session in this channel.")
async def cmd_start_game(interaction: Interaction):
    # Type hint for bot
    # Import RPGBot here for the cast to work at runtime
    from bot.bot_core import RPGBot
    bot = cast(RPGBot, interaction.client) # Used cast
    if not bot.game_manager:
        await interaction.response.send_message("Game Manager not available.", ephemeral=True)
        return
    # Example of using the helper, though start_game might have its own logic
    if not is_master_or_admin(interaction, bot.game_manager):
        await interaction.response.send_message("You are not authorized to start the game.", ephemeral=True)
        return
    await interaction.response.send_message("Placeholder for starting a new game.", ephemeral=True)

@app_commands.command(name="join_game", description="Join the current game session.")
async def cmd_join_game(interaction: Interaction):
    await interaction.response.send_message("Placeholder for joining game.", ephemeral=True)


@app_commands.command(name="start", description="Create your character and begin your adventure!")
@app_commands.describe(
    name="Your character's name.",
    race="Your character's race (e.g., Human, Elf, Dwarf)."
)
async def cmd_start_new_character(interaction: Interaction, name: str, race: str):
    await interaction.response.defer(ephemeral=True)
    # Import RPGBot here for the cast to work at runtime
    from bot.bot_core import RPGBot
    bot = cast(RPGBot, interaction.client) # Used cast

    try:
        if not bot.game_manager or \
           not bot.game_manager.character_manager: # Check for character_manager
            await interaction.followup.send("Error: The game systems (Game Manager or Character Manager) are not fully initialized.", ephemeral=True)
            return

        # Assuming db_service is on game_manager, or character_manager handles DB interactions.
        # If CharacterManager abstracts DB calls, direct db_service might not be needed here.
        # For now, let's assume CharacterManager handles its own persistence.
        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        # db_service is potentially character_manager._db_adapter or similar, not directly used here.

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        # 1. Check for Existing Character using CharacterManager
        existing_char_model: Optional[CharacterModel] = await character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )
        if existing_char_model:
            language = existing_char_model.selected_language or "en"
            char_name = existing_char_model.name_i18n.get(language, existing_char_model.name_i18n.get('en', 'Adventurer'))
            await interaction.followup.send(f"Welcome back, {char_name}! You already have a character in this world. Use `/look` to see your surroundings.", ephemeral=True)
            return

        # 2. Create New Character using CharacterManager
        # Default values can be handled by CharacterManager.create_character or passed explicitly
        # For example, initial_location_id might be determined by CharacterManager.

        # The old code used db_service.create_player. Now we use character_manager.create_character.
        # create_character in CharacterManager needs discord_id, name, guild_id, and optionally other fields.
        # It should handle setting defaults like initial_location_id, stats, hp, etc.

        new_char_model: Optional[CharacterModel] = await character_manager.create_character(
            discord_id=discord_user_id_int,
            name=name, # CharacterManager should handle i18n if needed, or take it as a dict
            guild_id=guild_id_str,
            race=race, # Pass race to the manager
            # Pass other relevant initial parameters if CharacterManager.create_character supports them:
            # initial_location_id="town_square", # Or let CharacterManager decide
            # level=1,
            # stats=default_stats, # Or let CharacterManager decide
            # current_game_status='исследование' # Or let CharacterManager decide
        )

        if not new_char_model:
            await interaction.followup.send("There was an error creating your character. Please try again or contact an admin.", ephemeral=True)
            return

        # The call to db_adapter.update_game_status was here.
        # As `update_game_status` method was not found on SqliteAdapter, it's commented out.
        # TODO: Investigate if game status needs to be updated here and how (e.g., via GameManager or a dedicated service).
        # if bot.game_manager.db_service: # Assuming db_service is the adapter
        #    # game_state_status = "some_status" # Determine what status this should be
        #    # await bot.game_manager.db_service.update_game_status(guild_id=guild_id_str, status=game_state_status)
        #    pass


        # 3. Success Message
        # Fetch location name for the message using LocationManager if character has location_id
        location_name_display = "an unknown place"
        if new_char_model.location_id and bot.game_manager.location_manager:
            location_instance = await bot.game_manager.location_manager.get_location_instance(guild_id_str, new_char_model.location_id)
            if location_instance:
                location_name_display = location_instance.get('name', location_name_display)

        language = new_char_model.selected_language or "en"
        char_name_display = new_char_model.name_i18n.get(language, new_char_model.name_i18n.get('en', name))
        # Assuming race is an attribute on new_char_model, or was passed to create_character and stored.
        # For now, use the input `race` parameter for the message.
        char_race_display = race

        response_message = (
            f"Welcome, {char_name_display} the {char_race_display}! Your adventure begins in {location_name_display}.\n"
            f"Use `/look` to see your surroundings."
        )
        await interaction.followup.send(response_message, ephemeral=False)

    except Exception as e:
        print(f"Error in /start command: {e}")
        traceback.print_exc()
        # Ensure followup is used if initial response was deferred and no other followup sent.
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("An unexpected error occurred. Please try again later.", ephemeral=True)
            except discord.errors.InteractionResponded:
                 await interaction.followup.send("An unexpected error occurred. Please try again later.", ephemeral=True)
        else:
            await interaction.followup.send("An unexpected error occurred while starting your adventure. Please try again later.", ephemeral=True)


@app_commands.command(name="set_bot_language", description="GM Command: Sets the default language for AI content generation and bot messages.")
@app_commands.describe(language="Choose the default language (русский/english)")
@app_commands.choices(language=[
    app_commands_Choice(name="Русский", value="ru"),
    app_commands_Choice(name="English", value="en")
])
async def cmd_set_bot_language(interaction: Interaction, language: str):
    """GM Command: Sets the default language for AI content generation and bot messages."""
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client)

    try:
        if not bot.game_manager:
            await interaction.followup.send("Error: Game Manager is not available.", ephemeral=True)
            return

        if not is_master_or_admin(interaction, bot.game_manager):
            await interaction.followup.send("You are not authorized to use this command.", ephemeral=True)
            return

        # Assuming a method like this exists or will be created in GameManager
        await bot.game_manager.set_default_bot_language(language, str(interaction.guild_id))

        confirmation_message = ""
        if language == "ru":
            confirmation_message = "Основной язык бота установлен на русский."
        else:  # Default to English
            confirmation_message = "Default bot language set to English."

        await interaction.followup.send(confirmation_message, ephemeral=True)

    except Exception as e:
        print(f"Error in /set_bot_language command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while setting the bot language.", ephemeral=True)
