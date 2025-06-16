import logging
import json
from typing import TYPE_CHECKING, List, Dict, Any

import discord
from discord import app_commands, Interaction, Embed
from discord.ext import commands

from bot.database.models import Player, GeneratedQuest, QuestStepTable
from bot.database.crud_utils import get_entity_by_attributes, get_entity_by_id

if TYPE_CHECKING:
    from bot.bot_core import RPGBot

logger = logging.getLogger(__name__)

class QuestCmdsCog(commands.Cog):
    """Cog for handling player quest-related commands."""

    def __init__(self, bot: "RPGBot"):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.logger.info("QuestCmdsCog initialized.")

    def _get_i18n_value(self, data_i18n: Dict[str, Any], key: str, lang: str, fallback_lang: str = 'en') -> str:
        """Helper to get i18n value with fallback."""
        if not data_i18n or not isinstance(data_i18n, dict):
            return f"Missing i18n data for '{key}'"

        value_lang = data_i18n.get(lang, {}).get(key)
        if value_lang:
            return value_lang

        value_fallback = data_i18n.get(fallback_lang, {}).get(key)
        if value_fallback:
            return value_fallback

        return f"No translation for '{key}' in '{lang}' or '{fallback_lang}'"


    @app_commands.command(name="quests", description="Displays your active quests and current objectives.")
    async def show_quests(self, interaction: Interaction):
        """Displays the player's active quests and their current objectives."""
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        discord_id = str(interaction.user.id)

        db_service = self.bot.game_manager.db_service
        if not db_service:
            self.logger.error(f"DBService not available for /quests command. Guild: {guild_id}, User: {discord_id}")
            await interaction.followup.send("The database service is currently unavailable. Please try again later.", ephemeral=True)
            return

        try:
            async with db_service.get_session() as session:
                player = await get_entity_by_attributes(
                    session,
                    Player,
                    {"discord_id": discord_id, "guild_id": guild_id},
                    guild_id # Pass guild_id for logging/error context if needed by crud_util
                )

                if not player:
                    await interaction.followup.send("Player not found. Make sure you have registered and are playing in this server.", ephemeral=True)
                    return

                active_quests_data = []
                if player.active_quests:
                    if isinstance(player.active_quests, (str, bytes)):
                        try:
                            active_quests_data = json.loads(player.active_quests)
                        except json.JSONDecodeError:
                            self.logger.error(f"Failed to decode active_quests JSON for player {player.id} in guild {guild_id}. Data: {player.active_quests}")
                            await interaction.followup.send("There was an error reading your quest data. Please contact an admin.", ephemeral=True)
                            return
                    elif isinstance(player.active_quests, list):
                        active_quests_data = player.active_quests

                    if not isinstance(active_quests_data, list): # Ensure it's a list after potential parsing
                        self.logger.warning(f"active_quests_data for player {player.id} is not a list after processing. Type: {type(active_quests_data)}")
                        active_quests_data = []


                if not active_quests_data:
                    await interaction.followup.send("You have no active quests at the moment.", ephemeral=True)
                    return

                embeds_list: List[Embed] = []
                player_lang = player.selected_language or await self.bot.game_manager.get_rule(guild_id, 'default_language', 'en')

                for quest_entry in active_quests_data:
                    if not isinstance(quest_entry, dict):
                        self.logger.warning(f"Skipping non-dict quest_entry for player {player.id}: {quest_entry}")
                        continue

                    quest_id = quest_entry.get("quest_id")
                    current_step_id = quest_entry.get("current_step_id")
                    quest_status = quest_entry.get("status", "In Progress")

                    if not quest_id or not current_step_id:
                        self.logger.warning(f"Missing quest_id or current_step_id in quest_entry for player {player.id}: {quest_entry}")
                        embed = Embed(
                            title="Unknown Quest",
                            description="Details for this quest entry are incomplete.",
                            color=discord.Color.orange()
                        )
                        embeds_list.append(embed)
                        continue

                    main_quest = await get_entity_by_id(session, GeneratedQuest, quest_id, guild_id)
                    current_step = await get_entity_by_id(session, QuestStepTable, current_step_id, guild_id)

                    if main_quest and current_step:
                        quest_title = self._get_i18n_value(main_quest.title_i18n, "title", player_lang) \
                                      if main_quest.title_i18n else "Quest Title Unavailable"

                        step_title = self._get_i18n_value(current_step.title_i18n, "title", player_lang) \
                                     if current_step.title_i18n else "Objective Title Unavailable"

                        step_desc = self._get_i18n_value(current_step.description_i18n, "description", player_lang) \
                                    if current_step.description_i18n else "Objective Description Unavailable"

                        embed = Embed(
                            title=f"📜 {quest_title}",
                            color=discord.Color.blue() # Or a color based on status
                        )
                        embed.add_field(name="Status", value=quest_status, inline=True)
                        embed.add_field(name="Current Objective", value=f"**{step_title}**\n{step_desc}", inline=False)

                        # Add more fields if necessary, e.g., quest giver
                        if main_quest.quest_giver_details_i18n:
                            giver_name = self._get_i18n_value(main_quest.quest_giver_details_i18n, "name", player_lang)
                            if giver_name and giver_name.lower() != "missing i18n data for 'name'": # Avoid showing placeholder
                                embed.add_field(name="Quest Giver", value=giver_name, inline=True)

                        embed.set_footer(text=f"Quest ID: {quest_id} | Step ID: {current_step_id}")
                        embeds_list.append(embed)
                    else:
                        self.logger.warning(f"Could not find main_quest (ID: {quest_id}) or current_step (ID: {current_step_id}) for player {player.id}")
                        embed = Embed(
                            title=f"Quest ID: {quest_id}",
                            description="Details for this quest or its current step are currently unavailable or might have been removed.",
                            color=discord.Color.red()
                        )
                        embeds_list.append(embed)

                if embeds_list:
                    # Discord allows up to 10 embeds per message. Handle more if necessary.
                    for i in range(0, len(embeds_list), 10):
                        await interaction.followup.send(embeds=embeds_list[i:i+10], ephemeral=True)
                else: # Should be caught by "no active quests" earlier, but as a safeguard
                    await interaction.followup.send("No quest details could be displayed.", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in /quests command for player {discord_id} in guild {guild_id}: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while fetching your quests. Please try again later.", ephemeral=True)

async def setup(bot: "RPGBot"):
    await bot.add_cog(QuestCmdsCog(bot))
    logger.info("QuestCmdsCog added to bot.")
