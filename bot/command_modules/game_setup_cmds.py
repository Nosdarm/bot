import discord # Added for discord.Role
from discord import Interaction, app_commands, Member, Role # Added Role
from discord.ext import commands
from typing import Optional, TYPE_CHECKING
import logging  # For logging
import uuid # For Player ID
from sqlalchemy.exc import IntegrityError # For checking if Player already exists
from sqlalchemy import select # Added import

from bot.database.models import Player # Import Player model
from bot.database.crud_utils import create_entity # Import create_entity
from bot.game.managers.character_manager import CharacterAlreadyExistsError

if TYPE_CHECKING:
    from bot.bot_core import RPGBot  # For type hinting self.bot
    from bot.game.managers.game_manager import GameManager
    from bot.database.models import Player, Location # Added
    from bot.services.db_service import DBService # Added
    from bot.game.managers.location_manager import LocationManager # Added
    import uuid # Added

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
        # discord_id_str = str(interaction.user.id) # No longer needed here for direct DB ops
        # player_display_name = interaction.user.display_name # No longer needed here

        # Player creation/verification is now handled within GameManager/CharacterManager
        # --- Character Creation ---
        try:
            # Determine the language to be primarily associated with this character creation event/messages
            # This might be different from the player's stored preferred language if they override it for this command.
            # The CharacterManager's create_and_activate_character_for_discord_user will handle player's language preference.
            effective_command_language = player_language or await game_mngr.get_rule(guild_id_str, 'default_language', 'en')

            # Call the GameManager method which now encapsulates player and character creation logic
            new_character_pydantic = await game_mngr.start_new_character_session(
                user_id=interaction.user.id, # Pass as int
                guild_id=guild_id_str,
                character_name=character_name,
                player_language=player_language # Pass explicitly provided language for character preference
                # char_class_key and race_key can be added as parameters if desired
            )

            if new_character_pydantic:
                logging.info(f"Character {new_character_pydantic.id} (Pydantic) created for user {interaction.user.id} in guild {guild_id_str}.")

                # Use the name from the returned Pydantic object, respecting its i18n logic
                # The Pydantic Character model has a .name property that handles i18n
                char_name_display = new_character_pydantic.name

                await interaction.followup.send(
                    f"Персонаж '{char_name_display}' успешно создан! "
                    f"Язык персонажа установлен на: {new_character_pydantic.selected_language}.",
                    ephemeral=True
                )
            else:
                # This 'else' handles cases where start_new_character_session returns None
                # (e.g., internal validation failed in CharacterManager not raising an exception caught here)
                logging.warning(f"Character creation returned None for user {interaction.user.id} in guild {guild_id_str} via GameManager.start_new_character_session.")
                await interaction.followup.send(
                    f"Не удалось создать персонажа '{character_name}'. Пожалуйста, попробуйте еще раз или свяжитесь с администратором, если проблема повторяется.",
                    ephemeral=True
                )
        except CharacterAlreadyExistsError:
            logging.info(f"Character already exists for user {interaction.user.id} in guild {guild_id_str} when trying to create '{character_name}'.")
            await interaction.followup.send(
                "У вас уже есть персонаж с таким именем в этой игре, или вы достигли лимита персонажей. Вы не можете создать еще одного с этим именем.",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Unexpected error during /start_new_character for {interaction.user.id} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send(
                f"Произошла непредвиденная ошибка при создании персонажа: {e}",
                ephemeral=True
            )

    # Removed duplicate set_bot_language command
    # @app_commands.command(
    #     name="set_bot_language",
    #     description=(
    #         "Установить язык бота для этой гильдии (только для Мастера)."
    #     )
    # )
    # @app_commands.describe(language_code="Код языка (например, 'ru', 'en').")
    # async def cmd_set_bot_language(
    #     self, interaction: Interaction, language_code: str
    # ):
    #     if not await self.is_master_or_admin(interaction):
    #         await interaction.response.send_message(
    #             "Только Мастер или администратор может менять язык бота.",
    #             ephemeral=True
    #         )
    #         return
    #
    #     bot_instance = self.bot  # type: RPGBot
    #     if not hasattr(bot_instance, 'game_manager') or \
    #        bot_instance.game_manager is None:
    #         await interaction.response.send_message(
    #             "GameManager is not available. "
    #             "Please try again later or contact an admin.",
    #             ephemeral=True
    #         )
    #         return
    #     game_mngr: "GameManager" = bot_instance.game_manager
    #
    #     success = await game_mngr.set_default_bot_language(
    #         language_code, str(interaction.guild_id)
    #     )
    #     if success:
    #         await interaction.response.send_message(
    #             f"Язык бота для этой гильдии установлен на '{language_code}'.",
    #             ephemeral=True
    #         )
    #     else:
    #         await interaction.response.send_message(
    #             "Не удалось установить язык бота. Проверьте логи.",
    #             ephemeral=True
    #         )

    # Removed duplicate set_master_channel command
    # @app_commands.command(
    #     name="set_master_channel",
    #     description=(
    #         "Установить этот канал как канал Мастера (только для Мастера)."
    #     )
    # )
    # async def cmd_set_master_channel(self, interaction: Interaction):
    #     if not await self.is_master_or_admin(interaction):
    #         await interaction.response.send_message(
    #             "Только Мастер может назначить этот канал.", ephemeral=True
    #         )
    #         return
    #     if not interaction.guild_id or not interaction.channel_id:
    #         await interaction.response.send_message(
    #             "Эта команда должна быть использована в канале сервера.",
    #             ephemeral=True
    #         )
    #         return
    #
    #     bot_instance = self.bot  # type: RPGBot
    #     if not hasattr(bot_instance, 'game_manager') or \
    #        bot_instance.game_manager is None:
    #         await interaction.response.send_message(
    #             "GameManager is not available. "
    #             "Please try again later or contact an admin.",
    #             ephemeral=True
    #         )
    #         return
    #     game_mngr: "GameManager" = bot_instance.game_manager
    #
    #     if game_mngr.db_service:
    #         await game_mngr.db_service.set_guild_setting(
    #             str(interaction.guild_id),
    #             'master_notification_channel_id',
    #             str(interaction.channel_id)
    #         )
    #         await interaction.response.send_message(
    #             f"Канал <#{interaction.channel_id}> назначен как "
    #             "канал Мастера для этой гильдии.",
    #             ephemeral=True
    #         )
    #     else:
    #         await interaction.response.send_message(
    #             "Не удалось сохранить настройку канала Мастера "
    #             "(DB service unavailable).",
    #             ephemeral=True
    #         )

    # Removed duplicate set_system_channel command
    # @app_commands.command(
    #     name="set_system_channel",
    #     description=(
    #         "Установить этот канал как системный канал (только для Мастера)."
    #     )
    # )
    # async def cmd_set_system_channel(self, interaction: Interaction):
    #     if not await self.is_master_or_admin(interaction):
    #         await interaction.response.send_message(
    #             "Только Мастер может назначить этот канал.", ephemeral=True
    #         )
    #         return
    #     if not interaction.guild_id or not interaction.channel_id:
    #         await interaction.response.send_message(
    #             "Эта команда должна быть использована в канале сервера.",
    #             ephemeral=True
    #         )
    #         return
    #
    #     bot_instance = self.bot  # type: RPGBot
    #     if not hasattr(bot_instance, 'game_manager') or \
    #        bot_instance.game_manager is None:
    #         await interaction.response.send_message(
    #             "GameManager is not available. "
    #             "Please try again later or contact an admin.",
    #             ephemeral=True
    #         )
    #         return
    #     game_mngr: "GameManager" = bot_instance.game_manager
    #
    #     if game_mngr.db_service:
    #         await game_mngr.db_service.set_guild_setting(
    #             str(interaction.guild_id),
    #             'system_notification_channel_id',
    #             str(interaction.channel_id)
    #         )
    #         await interaction.response.send_message(
    #             f"Канал <#{interaction.channel_id}> назначен как "
    #             "системный для этой гильдии.",
    #             ephemeral=True
    #         )
    #     else:
    #         await interaction.response.send_message(
    #             "Не удалось сохранить настройку системного канала "
    #             "(DB service unavailable).",
    #             ephemeral=True
    #         )

    # Removed duplicate set_master_role command
    # @app_commands.command(
    #     name="set_master_role",
    #     description="Установить роль Мастера для этой гильдии (только для Мастера/Администратора)."
    # )
    # @app_commands.describe(role="Роль Discord, которая будет назначена как роль Мастера.")
    # async def cmd_set_master_role(self, interaction: Interaction, role: discord.Role):
    #     logging.info(f"Command /set_master_role received from {interaction.user.name} ({interaction.user.id}) with role: {role.name} ({role.id})")
    #     if not await self.is_master_or_admin(interaction):
    #         await interaction.response.send_message(
    #             "Только Мастер или администратор может назначать роль Мастера.",
    #             ephemeral=True
    #         )
    #         logging.warning(f"User {interaction.user.name} ({interaction.user.id}) attempted to use /set_master_role without permissions in guild {interaction.guild_id}.")
    #         return
    #
    #     if not interaction.guild_id:
    #         await interaction.response.send_message(
    #             "Эта команда должна быть использована на сервере.",
    #             ephemeral=True
    #         )
    #         return
    #
    #     bot_instance = self.bot  # type: RPGBot
    #     if not hasattr(bot_instance, 'game_manager') or \
    #        bot_instance.game_manager is None or \
    #        not hasattr(bot_instance.game_manager, 'db_service') or \
    #        bot_instance.game_manager.db_service is None:
    #         await interaction.response.send_message(
    #             "GameManager или DBService не доступен. Пожалуйста, попробуйте позже или свяжитесь с администратором.",
    #             ephemeral=True
    #         )
    #         logging.error(f"GameManager or DBService not available for /set_master_role in guild {interaction.guild_id}.")
    #         return
    #
    #     game_mngr: "GameManager" = bot_instance.game_manager
    #
    #     try:
    #         success = await game_mngr.db_service.set_guild_setting(
    #             str(interaction.guild_id),
    #             'master_role_id',
    #             str(role.id)
    #         )
    #         if success:
    #             await interaction.response.send_message(
    #                 f"Роль '{role.name}' была успешно назначена как роль Мастера для этой гильдии.",
    #                 ephemeral=True
    #             )
    #             logging.info(f"Master role set to '{role.name}' ({role.id}) for guild {interaction.guild_id} by {interaction.user.name}.")
    #         else:
    #             await interaction.response.send_message(
    #                 "Не удалось сохранить настройку роли Мастера. Проверьте логи для деталей.",
    #                 ephemeral=True
    #             )
    #             logging.error(f"Failed to set master role (DBService.set_guild_setting returned False) for guild {interaction.guild_id} by {interaction.user.name}.")
    #     except Exception as e:
    #         await interaction.response.send_message(
    #             f"Произошла ошибка при установке роли Мастера: {e}",
    #             ephemeral=True
    #         )
    #         logging.error(f"Exception occurred in /set_master_role for guild {interaction.guild_id} by {interaction.user.name}: {e}", exc_info=True)

    @app_commands.command(name="start", description="Begin your adventure by creating your player profile.")
    @app_commands.guild_only()
    async def start_player_profile(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        user_display_name = interaction.user.display_name

        if not hasattr(self.bot, 'game_manager') or not self.bot.game_manager:
            logging.error(f"/start command by {discord_id_str} in guild {guild_id_str}: GameManager not found.")
            await interaction.followup.send("Game manager is not available. Please try again later or contact an administrator.", ephemeral=True)
            return

        game_mngr: "GameManager" = self.bot.game_manager
        if not game_mngr.db_service or not hasattr(game_mngr.db_service, 'get_session_factory'):
            logging.error(f"/start command by {discord_id_str} in guild {guild_id_str}: DBService or session factory not found.")
            await interaction.followup.send("Database service is not available. Please try again later or contact an administrator.", ephemeral=True)
            return

        from bot.database.guild_transaction import GuildTransaction
        from bot.database.models import Player # Ensure Player is imported
        from bot.database.crud_utils import get_entity_by_attributes, create_entity

        try:
            async with GuildTransaction(game_mngr.db_service.get_session_factory, guild_id_str) as session:
                existing_player = await get_entity_by_attributes(session, Player, {"discord_id": discord_id_str}, guild_id=guild_id_str)

                if existing_player:
                    # Use i18n for this message in future
                    await interaction.followup.send(f"{interaction.user.mention}, you already have a player profile here! Use `/character` commands to manage your characters.", ephemeral=True)
                else:
                    # Determine default language for the guild
                    default_lang = await game_mngr.get_rule(guild_id_str, "default_language", "en")

                    player_name_i18n = {"en": user_display_name}
                    if default_lang not in player_name_i18n: # Add guild default lang if different
                        player_name_i18n[default_lang] = user_display_name

                    player_data = {
                        "discord_id": discord_id_str,
                        "guild_id": guild_id_str, # create_entity will use this, and GuildTransaction verifies
                        "name_i18n": player_name_i18n,
                        "selected_language": default_lang,
                        "is_active": True
                        # active_character_id will be null by default
                    }

                    created_player = await create_entity(session, Player, player_data, guild_id=guild_id_str) # Pass guild_id for verification

                    if created_player:
                        # Use i18n for this message in future
                        await interaction.followup.send(f"Welcome, {interaction.user.mention}! Your player profile is set up. Next, create your adventurer with `/character create name:YourCharacterName`.", ephemeral=True)
                        logging.info(f"Player profile created for {discord_id_str} in guild {guild_id_str} by /start command.")
                    else:
                        # This case should ideally be caught by create_entity raising an exception
                        await interaction.followup.send("Sorry, there was an issue creating your player profile. Please try again later.", ephemeral=True)
                        logging.error(f"Player profile creation failed for {discord_id_str} in guild {guild_id_str} (create_entity returned None).")
        except IntegrityError as ie: # Should be rare due to prior check, but good to have
            logging.warning(f"IntegrityError for /start command user {discord_id_str} in guild {guild_id_str}: {ie}. Player likely created concurrently.", exc_info=True)
            await interaction.followup.send(f"{interaction.user.mention}, it looks like your profile was just created! Try `/character create name:YourCharacterName`.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in /start command for user {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred while setting up your profile. Please try again later.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GameSetupCog(bot))  # type: ignore
    print("GameSetupCog loaded.")
