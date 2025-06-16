import discord # Added for discord.Role
from discord import Interaction, app_commands, Member, Role # Added Role
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import logging  # For logging
import uuid # For Player ID
from sqlalchemy.exc import IntegrityError # For checking if Player already exists

from bot.database.models import Player # Import Player model
from bot.database.crud_utils import create_entity # Import create_entity
from bot.game.managers.character_manager import CharacterAlreadyExistsError

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
        logging.info(f"Command /start_new_character received from {interaction.user.name} ({interaction.user.id}) with arguments: character_name={character_name}, player_language={player_language}")
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
            logging.error(f"GameManager not available for /start_new_character by {interaction.user.id}")
            await interaction.followup.send(
                "GameManager is not available. " # User-facing message
                "Please try again later or contact an admin.",
                ephemeral=True
            )
            return
        game_mngr: "GameManager" = bot_instance.game_manager
        db_service = game_mngr.db_service

        if not db_service:
            logging.error(f"DBService not available for /start_new_character by {interaction.user.id}")
            await interaction.followup.send("Database service is not available. Please contact an admin.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        player_display_name = interaction.user.display_name

        # --- Player Creation/Verification ---
        try:
            async with db_service.get_session() as session:
                # Check if Player already exists
                existing_player_stmt = select(Player).where(Player.discord_id == discord_id_str, Player.guild_id == guild_id_str)
                result = await session.execute(existing_player_stmt)
                existing_player = result.scalars().first()

                if not existing_player:
                    logging.info(f"No existing Player found for {discord_id_str} in guild {guild_id_str}. Creating new Player.")

                    # Determine player language and starting location
                    # Using game_manager.get_rule which is async
                    player_initial_language = await game_mngr.get_rule(guild_id_str, 'default_language', 'en')
                    starting_location_id = await game_mngr.get_rule(guild_id_str, 'starting_location_id', "default_starting_location") # Placeholder if rule not set

                    player_data = {
                        "id": str(uuid.uuid4()),
                        "discord_id": discord_id_str,
                        "guild_id": guild_id_str,
                        "name_i18n": {"en": player_display_name, player_initial_language: player_display_name}, # Basic i18n
                        "current_location_id": starting_location_id,
                        "selected_language": player_initial_language,
                        "xp": 0,
                        "level": 1,
                        "unspent_xp": 0,
                        "gold": await game_mngr.get_rule(guild_id_str, 'starting_gold', 0),
                        "current_game_status": "active",
                        "collected_actions_json": "[]",
                        "hp": await game_mngr.get_rule(guild_id_str, 'starting_hp', 100.0), # Example starting HP from rules
                        "max_health": await game_mngr.get_rule(guild_id_str, 'starting_max_health', 100.0), # Example starting max_health
                        "is_alive": True,
                        # current_party_id can be None initially
                    }

                    # create_entity handles add and flush. Commit is handled by the session context manager.
                    new_player_record = await create_entity(session, Player, player_data) # guild_id not needed for create_entity per its definition
                    await session.commit() # Commit the new Player record
                    logging.info(f"Player record {new_player_record.id} created for {discord_id_str} in guild {guild_id_str}.")
                else:
                    logging.info(f"Existing Player {existing_player.id} found for {discord_id_str} in guild {guild_id_str}.")

        except IntegrityError: # This might occur if Player creation is attempted twice concurrently, though select check mitigates it.
            await session.rollback() # Rollback on integrity error during Player creation
            logging.warning(f"IntegrityError during Player creation for {discord_id_str} in guild {guild_id_str}. May indicate concurrent attempts or race condition.", exc_info=True)
            # Player likely exists, proceed with Character creation attempt or inform user.
            # For this flow, we assume if IntegrityError happens, player record was just created by another concurrent request.
            pass # Allow to proceed to character creation phase as player record should exist.
        except Exception as e:
            if 'session' in locals() and session.is_active: # Check if session was defined and is active
                 await session.rollback()
            logging.error(f"Unexpected error during Player creation/check for {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send(f"An unexpected error occurred while setting up your player profile: {e}", ephemeral=True)
            return

        # --- Character Creation ---
        try:
            # Effective language for character messages, potentially overriding player's selected language for this command
            effective_character_language = player_language or await game_mngr.get_rule(guild_id_str, 'default_language', 'en')

            new_character_obj = await game_mngr.start_new_character_session(
                user_id=interaction.user.id, # This is discord_id as int
                guild_id=guild_id_str,
                character_name=character_name
            )

            if new_character_obj:
                logging.info(f"Character {new_character_obj.id} created for Player {discord_id_str} in guild {guild_id_str}.")
                # If player_language was explicitly provided for the character (distinct from Player's selected_language)
                if player_language and hasattr(new_character_obj, 'selected_language'): # Character model might not have selected_language
                    # This depends on whether Character model stores language or if it's purely a Player attribute.
                    # For now, let's assume Character does not have its own 'selected_language' and Player's is used.
                    pass # player_language preference for character might be handled inside start_new_character_session or by setting Player.selected_language

                char_name_display = getattr(new_character_obj, 'name', character_name)
                if hasattr(new_character_obj, 'name_i18n') and isinstance(new_character_obj.name_i18n, dict):
                    char_name_display = new_character_obj.name_i18n.get(effective_character_language, char_name_display)

                await interaction.followup.send(
                    f"Персонаж '{char_name_display}' успешно создан! "
                    f"Язык для сообщений: {effective_character_language}.", # This refers to message language, Player.selected_language is the stored preference
                    ephemeral=True
                )
            else:
                # This 'else' handles cases where start_new_character_session returns None (e.g. other validation failed)
                logging.warning(f"Character creation returned None for Player {discord_id_str} in guild {guild_id_str} (GameManager.start_new_character_session returned None).")
                await interaction.followup.send(
                    f"Не удалось создать персонажа '{character_name}'. Проверьте, возможно имя уже занято или существуют другие ограничения.",
                    ephemeral=True
                )
        except CharacterAlreadyExistsError:
            logging.info(f"Character already exists for Player {discord_id_str} in guild {guild_id_str} when trying to create '{character_name}'.")
            await interaction.followup.send(
                "У вас уже есть персонаж в этой игре. Вы не можете создать еще одного.",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Unexpected error during Character creation for {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send(
                f"Произошла непредвиденная ошибка при создании персонажа: {e}",
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

    @app_commands.command(
        name="set_master_role",
        description="Установить роль Мастера для этой гильдии (только для Мастера/Администратора)."
    )
    @app_commands.describe(role="Роль Discord, которая будет назначена как роль Мастера.")
    async def cmd_set_master_role(self, interaction: Interaction, role: discord.Role):
        logging.info(f"Command /set_master_role received from {interaction.user.name} ({interaction.user.id}) with role: {role.name} ({role.id})")
        if not await self.is_master_or_admin(interaction):
            await interaction.response.send_message(
                "Только Мастер или администратор может назначать роль Мастера.",
                ephemeral=True
            )
            logging.warning(f"User {interaction.user.name} ({interaction.user.id}) attempted to use /set_master_role without permissions in guild {interaction.guild_id}.")
            return

        if not interaction.guild_id:
            await interaction.response.send_message(
                "Эта команда должна быть использована на сервере.",
                ephemeral=True
            )
            return

        bot_instance = self.bot  # type: RPGBot
        if not hasattr(bot_instance, 'game_manager') or \
           bot_instance.game_manager is None or \
           not hasattr(bot_instance.game_manager, 'db_service') or \
           bot_instance.game_manager.db_service is None:
            await interaction.response.send_message(
                "GameManager или DBService не доступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.",
                ephemeral=True
            )
            logging.error(f"GameManager or DBService not available for /set_master_role in guild {interaction.guild_id}.")
            return

        game_mngr: "GameManager" = bot_instance.game_manager

        try:
            success = await game_mngr.db_service.set_guild_setting(
                str(interaction.guild_id),
                'master_role_id',
                str(role.id)
            )
            if success:
                await interaction.response.send_message(
                    f"Роль '{role.name}' была успешно назначена как роль Мастера для этой гильдии.",
                    ephemeral=True
                )
                logging.info(f"Master role set to '{role.name}' ({role.id}) for guild {interaction.guild_id} by {interaction.user.name}.")
            else:
                await interaction.response.send_message(
                    "Не удалось сохранить настройку роли Мастера. Проверьте логи для деталей.",
                    ephemeral=True
                )
                logging.error(f"Failed to set master role (DBService.set_guild_setting returned False) for guild {interaction.guild_id} by {interaction.user.name}.")
        except Exception as e:
            await interaction.response.send_message(
                f"Произошла ошибка при установке роли Мастера: {e}",
                ephemeral=True
            )
            logging.error(f"Exception occurred in /set_master_role for guild {interaction.guild_id} by {interaction.user.name}: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GameSetupCog(bot))  # type: ignore
    print("GameSetupCog loaded.")
