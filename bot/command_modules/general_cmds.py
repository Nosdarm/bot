import logging
from typing import Optional, TYPE_CHECKING
from discord import Interaction, app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.models.character import Character

class GeneralCog(commands.Cog, name="General Commands"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="ping", description="Проверяет задержку ответа бота.")
    async def cmd_ping(self, interaction: Interaction):
        latency_ms = self.bot.latency * 1000
        await interaction.response.send_message(
            f"Pong! Задержка: {latency_ms:.2f} мс.",
            ephemeral=True
        )
        logging.info(f"Command /ping executed by {interaction.user.name} ({interaction.user.id}) in guild {interaction.guild_id or 'DM'}")

async def setup(bot: "RPGBot"):
    await bot.add_cog(GeneralCog(bot))
    logging.info("GeneralCog loaded (formerly had /lang command).")
