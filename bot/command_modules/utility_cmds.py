# bot/command_modules/utility_cmds.py
import discord
from discord import app_commands, Interaction, app_commands # Added app_commands.Choice
from discord.app_commands import Choice as app_commands_Choice # Explicitly import Choice
from typing import Optional, TYPE_CHECKING, Dict, Any, List, cast # Added cast
import traceback

import json # Added for JSON operations

# Corrected imports
if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.models.character import Character as CharacterModel

# TEST_GUILD_IDS can be removed if not used in decorators
# TEST_GUILD_IDS = []

@app_commands.command(name="undo", description="Reverts your last collected (but not yet processed) game action.")
async def cmd_undo(interaction: Interaction):
    """Allows a player to undo their last collected game action from the action queue."""
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client) # Used cast

    try:
        if not bot.game_manager or not bot.game_manager.character_manager:
            await interaction.followup.send("Error: Game systems (Character Manager) are not fully initialized.", ephemeral=True)
            return

        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional[CharacterModel] = await character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )

        if not character:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        actions_list: List[Dict[str, Any]] = []
        if character.collected_actions_json: # Changed attribute name
            try:
                actions_list = json.loads(character.collected_actions_json) # Changed attribute name
                if not isinstance(actions_list, list): # Ensure it's a list
                    # If it's a dict (single action previously), wrap it in a list then pop.
                    # Or consider it an invalid state and clear. For simplicity, let's clear if not list.
                    actions_list = []
                    print(f"Warning: collected_actions_json for char {character.id} was not a list. Cleared for undo.") # Changed attribute name
            except json.JSONDecodeError:
                await interaction.followup.send("Error: Could not parse your collected actions. Please contact an admin.", ephemeral=True)
                # Optionally clear the invalid JSON
                character.collected_actions_json = "[]" # Changed attribute name
                character_manager.mark_character_dirty(guild_id_str, character.id)
                await character_manager.save_character(character, guild_id=guild_id_str)
                return

        if not actions_list:
            await interaction.followup.send("You have no actions to undo.", ephemeral=True)
            return

        # Remove the last action
        undone_action = actions_list.pop()

        # Update the character's collected actions
        character.collected_actions_json = json.dumps(actions_list) # Changed attribute name
        character_manager.mark_character_dirty(guild_id_str, character.id)
        await character_manager.save_character(character, guild_id=guild_id_str)

        # Provide feedback about the undone action (optional, could be generic)
        # For a more detailed message, you might inspect undone_action['intent'] or undone_action['original_text']
        undone_action_text = undone_action.get('original_text', 'your last action')
        if len(undone_action_text) > 50: # Keep it brief
            undone_action_text = undone_action_text[:47] + "..."

        await interaction.followup.send(f"Successfully removed '{undone_action_text}' from your action queue.", ephemeral=True)

    except Exception as e:
        print(f"Error in /undo command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to undo your action.", ephemeral=True)


@app_commands.command(name="lang", description="Sets your preferred language for game messages.")
@app_commands.describe(language="Choose your language (русский/english)")
@app_commands.choices(language=[
    app_commands_Choice(name="Русский", value="ru"),
    app_commands_Choice(name="English", value="en")
])
async def cmd_lang(interaction: Interaction, language: str):
    """Sets the player's preferred language for game messages."""
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client)

    try:
        if not bot.game_manager or not bot.game_manager.character_manager:
            await interaction.followup.send("Error: Game systems (Character Manager) are not fully initialized.", ephemeral=True)
            return

        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id

        character: Optional[CharacterModel] = await character_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )

        if not character:
            await interaction.followup.send("You need to create a character first! Use /start.", ephemeral=True)
            return

        character.selected_language = language
        character_manager.mark_character_dirty(guild_id_str, character.id)
        await character_manager.save_character(character, guild_id=guild_id_str)

        confirmation_message = ""
        if language == "ru":
            confirmation_message = "Ваш язык изменен на русский."
        else:  # Default to English
            confirmation_message = "Your language has been changed to English."

        await interaction.followup.send(confirmation_message, ephemeral=True)

    except Exception as e:
        print(f"Error in /lang command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to set your language.", ephemeral=True)
