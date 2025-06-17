import logging
from typing import Optional, TYPE_CHECKING
from discord import Interaction, app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    # Character model might not be directly needed here anymore
    # from bot.game.models.character import Character
    from bot.database.models import Player # Import Player if type hinting the player object

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

        # CharacterManager check is no longer needed if we are fetching Player directly
        # if not game_mngr.character_manager:
        #     logging.error(f"/lang command by {interaction.user.name} ({interaction.user.id}) failed: CharacterManager not found.")
        #     await interaction.followup.send("Менеджер персонажей недоступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.", ephemeral=True)
        #     return

        if not game_mngr.db_service: # Ensure db_service is available for saving
            logging.error(f"/lang command by {interaction.user.name} ({interaction.user.id}) failed: DBService not found in GameManager.")
            await interaction.followup.send("Сервис базы данных недоступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.", ephemeral=True)
            return

        try:
            # Fetch the Player object
            player: Optional["Player"] = await game_mngr.get_player_by_discord_id(
                discord_id=str(interaction.user.id),
                guild_id=str(interaction.guild_id)
            )

            if not player:
                logging.info(f"/lang command by {interaction.user.name} ({interaction.user.id}): Player profile not found in guild {interaction.guild_id}.")
                await interaction.followup.send("Ваш профиль игрока не найден. Пожалуйста, создайте его сначала (например, используя /start или команду создания персонажа).", ephemeral=True)
                return

            # Update Player.selected_language
            # The player object from get_player_by_discord_id might be a SQLAlchemy model instance or a Pydantic model.
            # If it's a SQLAlchemy model from a session, direct assignment and session commit (handled by update_player_field) is one way.
            # update_player_field abstracts the direct DB interaction.

            success = await game_mngr.db_service.update_player_field(
                player_id=player.id, # Assumes player.id is the PK of the Player model
                field_name='selected_language',
                value=language_code,
                guild_id_str=str(interaction.guild_id) # Pass guild_id_str if required by update_player_field
            )

            if success:
                # Optionally update the language on the fetched player object in memory if it's used further
                # player.selected_language = language_code

                language_map = {"ru": "Русский", "en": "English"}
                user_friendly_language = language_map.get(language_code, language_code)
                logging.info(f"/lang command executed by {interaction.user.name} ({interaction.user.id}), set language to {language_code} for player {player.id}.")
                await interaction.followup.send(f"Ваш язык успешно изменен на {user_friendly_language}.", ephemeral=True)
            else:
                logging.error(f"/lang command by {interaction.user.name} ({interaction.user.id}) for player {player.id}: Failed to save language {language_code} to DB.")
                await interaction.followup.send("Не удалось сохранить ваш выбор языка. Попробуйте снова или свяжитесь с администратором.", ephemeral=True)

        except Exception as e:
            logging.error(f"Error in /lang command for {interaction.user.name} ({interaction.user.id}): {e}", exc_info=True)
            await interaction.followup.send("Произошла непредвиденная ошибка при изменении языка. Пожалуйста, сообщите администратору.", ephemeral=True)

async def setup(bot: "RPGBot"):
    await bot.add_cog(GeneralCog(bot))
    logging.info("GeneralCog loaded with /lang command.")
