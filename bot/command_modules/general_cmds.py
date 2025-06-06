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
            f"Pong! Задержка: {latency_ms:.2f} мс."
        )
        logging.info(f"Command /ping executed by {interaction.user.name} ({interaction.user.id}) in guild {interaction.guild_id or 'DM'}")

    @app_commands.command(name="lang", description="Устанавливает ваш язык для взаимодействия с ботом.")
    @app_commands.describe(language_code="Желаемый язык")
    @app_commands.choices(language_code=[
        app_commands.Choice(name="Русский", value="ru"),
        app_commands.Choice(name="English", value="en")
    ])
    async def cmd_lang(self, interaction: Interaction, language_code: str):
        if not interaction.guild_id:
            await interaction.response.send_message("Эту команду можно использовать только на сервере.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        bot_instance: "RPGBot" = self.bot

        if not hasattr(bot_instance, 'game_manager') or not bot_instance.game_manager:
            logging.error(f"/lang command by {interaction.user.name} ({interaction.user.id}) failed: GameManager not found.")
            await interaction.followup.send("Менеджер игры недоступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.", ephemeral=True)
            return

        game_mngr: "GameManager" = bot_instance.game_manager

        if not game_mngr.character_manager:
            logging.error(f"/lang command by {interaction.user.name} ({interaction.user.id}) failed: CharacterManager not found.")
            await interaction.followup.send("Менеджер персонажей недоступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.", ephemeral=True)
            return

        try:
            player_char: Optional["Character"] = game_mngr.character_manager.get_character_by_discord_id(
                guild_id=str(interaction.guild_id),
                discord_user_id=interaction.user.id
            )

            if not player_char:
                logging.info(f"/lang command by {interaction.user.name} ({interaction.user.id}): Character not found in guild {interaction.guild_id}.")
                await interaction.followup.send("Ваш персонаж не найден. Пожалуйста, создайте персонажа, например, командой /start_new_character.", ephemeral=True)
                return

            success = await game_mngr.character_manager.save_character_field(
                guild_id=str(interaction.guild_id),
                character_id=player_char.id,
                field_name='selected_language',
                value=language_code
            )

            if success:
                if hasattr(player_char, 'selected_language'):
                    player_char.selected_language = language_code

                language_map = {"ru": "Русский", "en": "English"}
                user_friendly_language = language_map.get(language_code, language_code)
                logging.info(f"/lang command executed by {interaction.user.name} ({interaction.user.id}), set language to {language_code} for character {player_char.id}.")
                await interaction.followup.send(f"Ваш язык успешно изменен на {user_friendly_language}.", ephemeral=True)
            else:
                logging.error(f"/lang command by {interaction.user.name} ({interaction.user.id}) for character {player_char.id}: Failed to save language {language_code} to DB.")
                await interaction.followup.send("Не удалось сохранить ваш выбор языка. Попробуйте снова или свяжитесь с администратором.", ephemeral=True)

        except Exception as e:
            logging.error(f"Error in /lang command for {interaction.user.name} ({interaction.user.id}): {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка при изменении языка. Пожалуйста, сообщите администратору.", ephemeral=True)

async def setup(bot: "RPGBot"):
    await bot.add_cog(GeneralCog(bot))
    logging.info("GeneralCog loaded with /lang command.")
