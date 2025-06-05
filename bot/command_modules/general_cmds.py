from discord import Interaction, app_commands
from discord.ext import commands

class GeneralCog(commands.Cog, name="General Commands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Проверяет задержку ответа бота.")
    async def cmd_ping(self, interaction: Interaction):
        """Проверяет задержку ответа бота."""
        latency_ms = self.bot.latency * 1000
        # Ensure game_manager and its attributes are accessed correctly via self.bot
        # For example, if game_manager has a way to get a status string:
        # gm_status = "OK" # Placeholder
        # if hasattr(self.bot, 'game_manager') and self.bot.game_manager:
        #     gm_status = await self.bot.game_manager.get_status_string() # Assuming such a method

        await interaction.response.send_message(
            f"Pong! Задержка: {latency_ms:.2f} мс."
            # f"\nСтатус GameManager: {gm_status}" # Example if you want to add more info
        )
        print(f"Command /ping executed by {interaction.user.name}")

async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCog(bot))
    print("GeneralCog loaded.")
