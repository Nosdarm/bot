from discord import Interaction, app_commands, Member
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import logging  # For logging

if TYPE_CHECKING:
    from bot.bot_core import RPGBot  # For type hinting self.bot
    from bot.game.managers.game_manager import GameManager

# Helper functions - will become methods or static methods in the Cog
# These functions are used by commands in this Cog.


async def is_master_or_admin_check(interaction: Interaction) -> bool:
    """Checks if the user is a bot admin or has the 'Master' role in the guild."""
    # Access bot instance from interaction.client
    bot_instance = interaction.client  # type: RPGBot
    if (not hasattr(bot_instance, 'game_manager') or  # Break before or
            bot_instance.game_manager is None):
        logging.warning(
            "is_master_or_admin_check: GameManager not found on bot instance."
        )
        return False  # Or raise an error

    game_mngr: "GameManager" = bot_instance.game_manager

    # Ensure settings are loaded in GameManager
    if not game_mngr._settings:  # Accessing protected member, GM
        logging.warning(
            "is_master_or_admin_check: Settings not loaded in GameManager."
        )
        return False

    bot_admin_ids = [
        str(id_val) for id_val in game_mngr._settings.get('bot_admins', [])
    ]
    if str(interaction.user.id) in bot_admin_ids:
        return True

    if not interaction.guild:  # Should not happen for guild commands but good check
        return False

    master_role_id = game_mngr.get_master_role_id(
        str(
            interaction.guild_id
        )  # Wrap str() argument
    )
    if master_role_id and isinstance(interaction.user, Member):
        master_role = interaction.guild.get_role(int(master_role_id))
        if master_role and master_role in interaction.user.roles:
            return True
    return False


async def is_gm_channel_check(interaction: Interaction) -> bool:
    """Checks if the command is used in the designated GM channel for the guild."""
    bot_instance = interaction.client  # type: RPGBot
    if (not hasattr(bot_instance, 'game_manager') or  # Break before or
            bot_instance.game_manager is None):
        logging.warning(
            "is_gm_channel_check: GameManager not found on bot instance."
        )
        return False

    game_mngr: "GameManager" = bot_instance.game_manager
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

    @app_commands.command(
        name="start_new_character",
        description="Начать игру новым персонажем в текущем канале Discord."
    )
    @app_commands.describe(
        character_name="Имя вашего нового персонажа.",
        player_language=(
            "Язык, на котором вы будете играть (например, 'ru' или 'en')."
        )
    )
    async def cmd_start_new_character(
        self,
        interaction: Interaction,
        character_name: str,
        player_language: Optional[str] = None
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                "Эту команду можно использовать только на сервере.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None:
            await interaction.followup.send(
                "GameManager is not available. "
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        try:
            effective_language = (
                player_language or game_mngr.get_default_bot_language()
            )
            # The method signature for start_new_character_session in
            # GameManager is (self, user_id: int, guild_id: str,
            # character_name: str)
            # It does not take discord_user_name, channel_id,
            # selected_language directly like this.
            # This call needs to be updated based on the actual signature
            # implemented in GameManager.
            # For now, assuming the subtask to implement
            # start_new_character_session will define its signature.
            # Based on the provided signature for
            # GameManager.start_new_character_session:
            # (self, user_id: int, guild_id: str, character_name: str)
            # -> Optional["Character"]
            # The call here needs adjustment. The current subtask is to fix
            # game_setup_cmds.py access,
            # and then implement the method in GameManager.
            # The success, message tuple return is also not matching.
            # Let's adjust the call to the specified signature and handle the
            # Character return.
            new_character = await game_mngr.start_new_character_session(
                user_id=interaction.user.id,
                guild_id=str(interaction.guild_id),
                character_name=character_name
                # selected_language and discord_user_name would need to be
                # handled differently, e.g. by setting language on the
                # character object afterwards if create_character doesn't take
                # it.
            )

            if new_character:
                # If selected_language was provided and Character model has
                # selected_language field
                if (player_language and  # Break before and
                        hasattr(new_character, 'selected_language')):
                    if (game_mngr.character_manager and  # Break before and
                            hasattr(game_mngr.character_manager, 'save_character_field')):
                        await game_mngr.character_manager.save_character_field(
                            guild_id=str(interaction.guild_id),
                            character_id=new_character.id,
                            field_name='selected_language',
                            value=player_language
                        )
                        # Optionally update the in-memory object too
                        new_character.selected_language = player_language

                char_name_display = getattr(
                    new_character, 'name', character_name
                )  # Fallback to input name
                if hasattr(new_character, 'name_i18n') and \
                   isinstance(new_character.name_i18n, dict):
                    char_name_display = new_character.name_i18n.get(
                        effective_language, char_name_display
                    )

                await interaction.followup.send(
                    f"Персонаж '{char_name_display}' успешно создан! "
                    f"Язык: {effective_language}.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Не удалось создать персонажа '{character_name}'.",
                    ephemeral=True
                )
        except Exception as e:
            logging.error(
                f"Error in cmd_start_new_character: {e}", exc_info=True
            )
            await interaction.followup.send(
                f"Произошла ошибка при создании персонажа: {e}",
                ephemeral=True
            )

    @app_commands.command(
        name="set_bot_language",
        description=(
            "Установить язык бота для этой гильдии (только для Мастера)."
        )
    )
    @app_commands.describe(language_code="Код языка (например, 'ru', 'en').")
    async def cmd_set_bot_language(
        self, interaction: Interaction, language_code: str
    ):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message(
                "Только Мастер или администратор может менять язык бота.",
                ephemeral=True
            )
            return

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None:
            await interaction.response.send_message(
                "GameManager is not available. "
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        success = await game_mngr.set_default_bot_language(
            language_code, str(interaction.guild_id)
        )
        if success:
            await interaction.response.send_message(
                f"Язык бота для этой гильдии установлен на '{language_code}'.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось установить язык бота. Проверьте логи.",
                ephemeral=True
            )

    @app_commands.command(
        name="set_master_channel",
        description=(
            "Установить этот канал как канал Мастера (только для Мастера)."
        )
    )
    async def cmd_set_master_channel(self, interaction: Interaction):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message(
                "Только Мастер может назначить этот канал.", ephemeral=True
            )
            return
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message(
                "Эта команда должна быть использована в канале сервера.",
                ephemeral=True
            )
            return

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None:
            await interaction.response.send_message(
                "GameManager is not available. "
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        if game_mngr.db_service:
            await game_mngr.db_service.set_guild_setting(
                str(interaction.guild_id),
                'master_notification_channel_id',
                str(interaction.channel_id)
            )
            await interaction.response.send_message(
                f"Канал <#{interaction.channel_id}> назначен как "
                "канал Мастера для этой гильдии.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось сохранить настройку канала Мастера "
                "(DB service unavailable).",
                ephemeral=True
            )

    @app_commands.command(
        name="set_system_channel",
        description=(
            "Установить этот канал как системный канал (только для Мастера)."
        )
    )
    async def cmd_set_system_channel(self, interaction: Interaction):
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message(
                "Только Мастер может назначить этот канал.", ephemeral=True
            )
            return
        if not interaction.guild_id or not interaction.channel_id:
            await interaction.response.send_message(
                "Эта команда должна быть использована в канале сервера.",
                ephemeral=True
            )
            return

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None:
            await interaction.response.send_message(
                "GameManager is not available. "
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager

        if game_mngr.db_service:
            await game_mngr.db_service.set_guild_setting(
                str(interaction.guild_id),
                'system_notification_channel_id',
                str(interaction.channel_id)
            )
            await interaction.response.send_message(
                f"Канал <#{interaction.channel_id}> назначен как "
                "системный для этой гильдии.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось сохранить настройку системного канала "
                "(DB service unavailable).",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(GameSetupCog(bot))  # type: ignore
    print("GameSetupCog loaded.")
