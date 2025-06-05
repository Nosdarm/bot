from discord import Interaction, app_commands, TextChannel, Member, Role, Guild
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import logging # For logging

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # For type hinting self.bot
    from bot.game.managers.game_manager import GameManager

# Helper functions - will become methods or static methods in the Cog
# These functions are used by commands in this Cog.

async def is_master_or_admin_check(interaction: Interaction) -> bool:
    """Checks if the user is a bot admin or has the 'Master' role in the guild."""
    # Access bot instance from interaction.client
    bot_instance = interaction.client
    if not hasattr(bot_instance, 'game_manager') or not bot_instance.game_manager:
        logging.warning("is_master_or_admin_check: GameManager not found on bot instance.")
        return False # Or raise an error

    game_mngr = bot_instance.game_manager

    # Ensure settings are loaded in GameManager
    if not game_mngr._settings: # Accessing protected member, consider a getter in GM
        logging.warning("is_master_or_admin_check: Settings not loaded in GameManager.")
        return False

    bot_admin_ids = [str(id_val) for id_val in game_mngr._settings.get('bot_admins', [])]
    if str(interaction.user.id) in bot_admin_ids:
        return True

    if not interaction.guild: # Should not happen for guild commands but good check
        return False

    master_role_id = game_mngr.get_master_role_id(str(interaction.guild_id))
    if master_role_id and isinstance(interaction.user, Member):
        master_role = interaction.guild.get_role(int(master_role_id))
        if master_role and master_role in interaction.user.roles:
            return True
    return False

async def is_gm_channel_check(interaction: Interaction) -> bool:
    """Checks if the command is used in the designated GM channel for the guild."""
    bot_instance = interaction.client
    if not hasattr(bot_instance, 'game_manager') or not bot_instance.game_manager:
        logging.warning("is_gm_channel_check: GameManager not found on bot instance.")
        return False

    game_mngr = bot_instance.game_manager
    if not interaction.guild_id:
        return False

    gm_channel_id = game_mngr.get_gm_channel_id(str(interaction.guild_id))
    return gm_channel_id == interaction.channel_id


class GameSetupCog(commands.Cog, name="Game Setup"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    async def is_master_or_admin(self, interaction: Interaction) -> bool:
        return await is_master_or_admin_check(interaction)

    async def is_gm_channel(self, interaction: Interaction) -> bool:
        return await is_gm_channel_check(interaction)

    @app_commands.command(name="start_new_character", description="Начать игру новым персонажем в текущем канале Discord.")
    @app_commands.describe(
        character_name="Имя вашего нового персонажа.",
        player_language="Язык, на котором вы будете играть (например, 'ru' или 'en')."
    )
    async def cmd_start_new_character(self, interaction: Interaction, character_name: str, player_language: Optional[str] = None):
        if not interaction.guild:
            await interaction.response.send_message("Эту команду можно использовать только на сервере.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        game_mngr: "GameManager" = self.bot.game_manager
        if not game_mngr:
            await interaction.followup.send("Менеджер игры не инициализирован.", ephemeral=True)
            return

        try:
            effective_language = player_language or game_mngr.get_default_bot_language()
            success, message = await game_mngr.start_new_character_session(
                guild_id=str(interaction.guild_id),
                discord_user_id=interaction.user.id,
                discord_user_name=interaction.user.name,
                channel_id=interaction.channel_id,
                character_name=character_name,
                selected_language=effective_language
            )

            if success:
                await interaction.followup.send(f"{message}", ephemeral=True)
            else:
                await interaction.followup.send(f"Не удалось начать игру: {message}", ephemeral=True)

        except Exception as e:
            logging.error(f"Error in cmd_start_new_character: {e}", exc_info=True)
            await interaction.followup.send(f"Произошла ошибка при создании персонажа: {e}", ephemeral=True)

    @app_commands.command(name="set_bot_language", description="Установить язык бота для этой гильдии (только для Мастера).")
    @app_commands.describe(language_code="Код языка (например, 'ru', 'en').")
    async def cmd_set_bot_language(self, interaction: Interaction, language_code: str):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message("Только Мастер или администратор может менять язык бота.", ephemeral=True)
            return

        game_mngr: "GameManager" = self.bot.game_manager
        if not game_mngr:
            await interaction.response.send_message("Менеджер игры не инициализирован.", ephemeral=True)
            return

        success = await game_mngr.set_default_bot_language(language_code, str(interaction.guild_id))
        if success:
            await interaction.response.send_message(f"Язык бота для этой гильдии установлен на '{language_code}'.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Не удалось установить язык бота. Проверьте логи.", ephemeral=True)

    @app_commands.command(name="set_master_channel", description="Установить этот канал как канал Мастера (только для Мастера).")
    async def cmd_set_master_channel(self, interaction: Interaction):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message("Только Мастер может назначить этот канал.", ephemeral=True)
            return
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message("Эта команда должна быть использована в канале сервера.", ephemeral=True)
            return

        game_mngr: "GameManager" = self.bot.game_manager
        if not game_mngr:
            await interaction.response.send_message("Менеджер игры не инициализирован.", ephemeral=True)
            return

        if game_mngr.db_service:
            await game_mngr.db_service.set_guild_setting(str(interaction.guild_id), 'master_notification_channel_id', str(interaction.channel_id))
            await interaction.response.send_message(f"Канал <#{interaction.channel_id}> назначен как канал Мастера для этой гильдии.", ephemeral=True)
        else:
            await interaction.response.send_message("Не удалось сохранить настройку канала Мастера (DB service unavailable).", ephemeral=True)


    @app_commands.command(name="set_system_channel", description="Установить этот канал как системный канал (только для Мастера).")
    async def cmd_set_system_channel(self, interaction: Interaction):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message("Только Мастер может назначить этот канал.", ephemeral=True)
            return
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message("Эта команда должна быть использована в канале сервера.", ephemeral=True)
            return

        game_mngr: "GameManager" = self.bot.game_manager
        if not game_mngr:
            await interaction.response.send_message("Менеджер игры не инициализирован.", ephemeral=True)
            return

        if game_mngr.db_service:
            await game_mngr.db_service.set_guild_setting(str(interaction.guild_id), 'system_notification_channel_id', str(interaction.channel_id))
            await interaction.response.send_message(f"Канал <#{interaction.channel_id}> назначен как системный для этой гильдии.", ephemeral=True)
        else:
            await interaction.response.send_message("Не удалось сохранить настройку системного канала (DB service unavailable).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GameSetupCog(bot)) # type: ignore
    print("GameSetupCog loaded.")
