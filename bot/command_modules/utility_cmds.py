import discord
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, Dict, Any, List, cast
import traceback
import json

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager # Added
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.models.character import Character # Changed from CharacterModel

class UtilityCog(commands.Cog, name="Utility"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="undo", description="Reverts your last collected (but not yet processed) game action.")
    async def cmd_undo(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        bot_instance = self.bot # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            await interaction.followup.send("GameManager is not available.", ephemeral=True)
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        if not game_mngr.character_manager:
            await interaction.followup.send("CharacterManager is not available.", ephemeral=True)
            return
        character_manager: "CharacterManager" = game_mngr.character_manager

        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        try:
            character: Optional["Character"] = character_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
            if not character:
                await interaction.followup.send("Create a character first with `/start_new_character`.", ephemeral=True); return

            actions_list: List[Dict[str, Any]] = []
            collected_actions_json = getattr(character, 'collected_actions_json', "[]")
            if isinstance(collected_actions_json, str):
                try:
                    actions_list = json.loads(collected_actions_json)
                    if not isinstance(actions_list, list): actions_list = []
                except json.JSONDecodeError:
                    setattr(character, 'collected_actions_json', "[]") # Correct way to update attribute
                    await character_manager.save_character_field(guild_id_str, character.id, 'collected_actions_json', "[]")
                    await interaction.followup.send("Error parsing actions. Cleared action queue.", ephemeral=True); return
            elif isinstance(collected_actions_json, list): # If already a list (e.g. if model hydration does this)
                actions_list = collected_actions_json

            if not actions_list:
                await interaction.followup.send("No actions to undo.", ephemeral=True); return

            undone_action = actions_list.pop()
            new_actions_json = json.dumps(actions_list)
            setattr(character, 'collected_actions_json', new_actions_json)
            await character_manager.save_character_field(guild_id_str, character.id, 'collected_actions_json', new_actions_json)

            undone_action_text = undone_action.get('original_text', 'last action')[:50]
            await interaction.followup.send(f"Removed '{undone_action_text}{'...' if len(undone_action.get('original_text', '')) > 50 else ''}' from queue.", ephemeral=True)
        except Exception as e:
            print(f"Error in /undo: {e}"); traceback.print_exc()
            await interaction.followup.send("Error undoing action.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(UtilityCog(bot)) # type: ignore
    print("UtilityCog loaded.")
