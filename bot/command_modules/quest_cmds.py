import logging
import json
from typing import TYPE_CHECKING, List, Dict, Any, Optional, cast

import discord
from discord import app_commands, Interaction, Embed
from discord.ext import commands
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Player, GeneratedQuest, QuestStepTable
from bot.database.crud_utils import get_entity_by_attributes, get_entity_by_id
from bot.utils.i18n_utils import DEFAULT_BOT_LANGUAGE # Import for default

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager # For type hint
    from bot.services.db_service import DBService # For type hint

logger_cog = logging.getLogger(__name__) # Use a unique name for the logger

class QuestCmdsCog(commands.Cog):
    """Cog for handling player quest-related commands."""

    def __init__(self, bot: "RPGBot"):
        self.bot = bot
        self.logger = logger_cog # Use the module-level logger
        self.logger.info("QuestCmdsCog initialized.")

    def _get_i18n_value(self, i18n_data: Optional[Dict[str, str]], lang: str, fallback_lang: str = DEFAULT_BOT_LANGUAGE) -> str:
        """
        Helper to get i18n value from a simple {"lang": "value"} dict with fallback.
        Key is implicit (e.g. this dict *is* the title_i18n or description_i18n).
        """
        if not i18n_data or not isinstance(i18n_data, dict):
            return "N/A (missing data)"

        value_lang = i18n_data.get(lang)
        if value_lang is not None: # Check for None explicitly, empty string is valid
            return value_lang

        value_fallback = i18n_data.get(fallback_lang)
        if value_fallback is not None:
            return value_fallback

        # Fallback to the first available language if specific and fallback are missing
        if i18n_data:
            return next(iter(i18n_data.values()), "N/A (no translations)")

        return "N/A (no translations found)"


    @app_commands.command(name="quests", description="Displays your active quests and current objectives.")
    async def show_quests(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id) if interaction.guild_id else None
        discord_id = str(interaction.user.id)

        if not guild_id:
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        game_mngr: Optional["GameManager"] = getattr(self.bot, 'game_manager', None)
        if not game_mngr:
            self.logger.error(f"GameManager not available for /quests. Guild: {guild_id}, User: {discord_id}")
            await interaction.followup.send("The game manager is currently unavailable.", ephemeral=True)
            return

        db_service: Optional["DBService"] = getattr(game_mngr, 'db_service', None)
        if not db_service or not hasattr(db_service, 'get_session') or not callable(db_service.get_session):
            self.logger.error(f"DBService not available for /quests. Guild: {guild_id}, User: {discord_id}")
            await interaction.followup.send("The database service is currently unavailable.", ephemeral=True)
            return

        try:
            async with db_service.get_session() as session_context:
                session = cast(AsyncSession, session_context)
                player = await get_entity_by_attributes(
                    session, Player, {"discord_id": discord_id, "guild_id": guild_id}, guild_id=guild_id
                )

                if not player:
                    await interaction.followup.send("Player profile not found.", ephemeral=True)
                    return

                active_quests_data: List[Dict[str, Any]] = []
                player_active_quests_attr = getattr(player, 'active_quests', None)

                if isinstance(player_active_quests_attr, (str, bytes)):
                    try:
                        parsed_quests = json.loads(player_active_quests_attr)
                        if isinstance(parsed_quests, list): active_quests_data = parsed_quests
                        else: self.logger.warning(f"Parsed active_quests for player {player.id} is not a list.")
                    except json.JSONDecodeError:
                        self.logger.error(f"Failed to decode active_quests for player {player.id}.", exc_info=True)
                        await interaction.followup.send("Error reading quest data.", ephemeral=True); return
                elif isinstance(player_active_quests_attr, list):
                    active_quests_data = player_active_quests_attr

                if not active_quests_data:
                    await interaction.followup.send("You have no active quests.", ephemeral=True); return

                embeds_list: List[Embed] = []

                player_lang_val: Optional[str] = getattr(player, 'selected_language', None)
                if not player_lang_val and hasattr(game_mngr, 'get_rule') and callable(getattr(game_mngr, 'get_rule')):
                    player_lang_val = await game_mngr.get_rule(guild_id, 'default_language', DEFAULT_BOT_LANGUAGE) # type: ignore

                player_lang: str = player_lang_val if isinstance(player_lang_val, str) else DEFAULT_BOT_LANGUAGE


                for quest_entry in active_quests_data:
                    if not isinstance(quest_entry, dict): continue

                    quest_id = quest_entry.get("quest_id")
                    current_step_id = quest_entry.get("current_step_id")
                    quest_status = str(quest_entry.get("status", "In Progress"))

                    if not quest_id or not current_step_id:
                        embeds_list.append(Embed(title="Unknown Quest", description="Incomplete quest data.", color=discord.Color.orange())); continue

                    main_quest_db = await get_entity_by_id(session, GeneratedQuest, str(quest_id), guild_id=guild_id)
                    current_step_db = await get_entity_by_id(session, QuestStepTable, str(current_step_id), guild_id=guild_id)

                    if main_quest_db and current_step_db:
                        # Assuming title_i18n, description_i18n are JSONB columns automatically parsed to dict by SQLAlchemy
                        main_quest_title_i18n: Optional[Dict[str,str]] = getattr(main_quest_db, 'title_i18n', None)
                        current_step_title_i18n: Optional[Dict[str,str]] = getattr(current_step_db, 'title_i18n', None)
                        current_step_desc_i18n: Optional[Dict[str,str]] = getattr(current_step_db, 'description_i18n', None)
                        main_quest_giver_i18n: Optional[Dict[str,str]] = getattr(main_quest_db, 'quest_giver_details_i18n', None)

                        quest_title = self._get_i18n_value(main_quest_title_i18n, player_lang)
                        step_title = self._get_i18n_value(current_step_title_i18n, player_lang)
                        step_desc = self._get_i18n_value(current_step_desc_i18n, player_lang)

                        embed = Embed(title=f"📜 {quest_title}", color=discord.Color.blue())
                        embed.add_field(name="Status", value=quest_status, inline=True)
                        embed.add_field(name="Current Objective", value=f"**{step_title}**\n{step_desc}", inline=False)

                        if main_quest_giver_i18n is not None: # Check if attribute exists and is not None
                            giver_name = self._get_i18n_value(main_quest_giver_i18n, player_lang)
                            if giver_name and "N/A" not in giver_name :
                                embed.add_field(name="Quest Giver", value=giver_name, inline=True)
                        embed.set_footer(text=f"Quest ID: {quest_id} | Step ID: {current_step_id}")
                        embeds_list.append(embed)
                    else:
                        embeds_list.append(Embed(title=f"Quest ID: {quest_id}", description="Details unavailable.", color=discord.Color.red()))

                if embeds_list:
                    for i in range(0, len(embeds_list), 10):
                        await interaction.followup.send(embeds=embeds_list[i:i+10], ephemeral=True)
                else: await interaction.followup.send("No quest details to display.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error in /quests for {discord_id} in {guild_id}: {e}", exc_info=True)
            await interaction.followup.send("Error fetching quests.", ephemeral=True)

async def setup(bot: "RPGBot"):
    await bot.add_cog(QuestCmdsCog(bot))
    logger_cog.info("QuestCmdsCog added to bot.")
