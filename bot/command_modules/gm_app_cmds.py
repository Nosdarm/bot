from discord import Interaction, app_commands
from discord.ext import commands
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # For type hinting self.bot

class GMAppCog(commands.Cog, name="GM App Commands"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="gm_simulate", description="ГМ: Запустить один шаг симуляции мира.")
    async def cmd_gm_simulate(self, interaction: Interaction):
        # This command was standalone in bot_core.py
        # GM Check (simplified from game_setup_cmds for now)
        # Ensure game_manager and settings are accessible
        if not hasattr(self.bot, 'game_manager') or not self.bot.game_manager or not hasattr(self.bot.game_manager, '_settings'):
            await interaction.response.send_message("**Мастер:** Конфигурация игры не загружена.", ephemeral=True)
            return

        bot_admin_ids = [str(id_val) for id_val in self.bot.game_manager._settings.get('bot_admins', [])]
        if str(interaction.user.id) not in bot_admin_ids:
            await interaction.response.send_message("**Мастер:** Только Истинный Мастер может управлять ходом времени!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Эту команду можно использовать только на сервере.", ephemeral=True)
            return

        game_mngr = self.bot.game_manager
        if game_mngr:
            try:
                # Assuming trigger_manual_simulation_tick is on GameManager
                await game_mngr.trigger_manual_simulation_tick(server_id=str(interaction.guild_id)) # Ensure guild_id is string
                await interaction.followup.send("**Мастер:** Шаг симуляции мира (ручной) завершен!")
            except Exception as e:
                print(f"Error in cmd_gm_simulate (Cog): {e}")
                traceback.print_exc()
                await interaction.followup.send(f"**Мастер:** Ошибка при симуляции: {e}", ephemeral=True)
        else:
            await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(GMAppCog(bot)) # type: ignore
    print("GMAppCog loaded.")
