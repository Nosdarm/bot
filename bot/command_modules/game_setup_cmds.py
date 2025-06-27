import discord
from discord import Interaction, app_commands, Member, Role
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, Any, cast
import logging
import uuid
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Player
from bot.database.crud_utils import create_entity, get_entity_by_attributes
from bot.game.managers.character_manager import CharacterAlreadyExistsError
from bot.database.guild_transaction import GuildTransaction


if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.database.models import Location
    from bot.services.db_service import DBService
    from bot.game.managers.location_manager import LocationManager


async def is_master_or_admin_check(interaction: Interaction) -> bool:
    """Checks if the user is a bot admin or has the 'Master' role in the guild."""
    if not isinstance(interaction.client, commands.Bot) or not hasattr(interaction.client, 'game_manager'):
        logging.warning("is_master_or_admin_check: interaction.client is not a valid RPGBot instance or has no game_manager.")
        return False

    bot_instance = cast("RPGBot", interaction.client)

    if bot_instance.game_manager is None:
        logging.warning("is_master_or_admin_check: GameManager not found on bot instance.")
        return False

    game_mngr = cast("GameManager", bot_instance.game_manager)

    if not hasattr(game_mngr, '_settings') or not game_mngr._settings:
        logging.warning("is_master_or_admin_check: Settings not loaded in GameManager.")
        return False

    settings_val = game_mngr._settings.get('bot_admins', [])
    bot_admin_ids = [str(id_val) for id_val in settings_val if id_val is not None]

    if str(interaction.user.id) in bot_admin_ids:
        return True

    if not interaction.guild:
        return False

    get_master_role_id_method = getattr(game_mngr, "get_master_role_id", None)
    master_role_id_str: Optional[str] = None
    if callable(get_master_role_id_method):
        master_role_id_str = get_master_role_id_method(str(interaction.guild_id))
    else:
        logging.warning(f"GameManager does not have a callable 'get_master_role_id' method for guild {interaction.guild_id}.")
        return False

    if master_role_id_str and isinstance(interaction.user, Member):
        try:
            master_role = interaction.guild.get_role(int(master_role_id_str))
            if master_role and master_role in interaction.user.roles:
                return True
        except ValueError:
            logging.warning(f"Invalid master_role_id '{master_role_id_str}' for guild {interaction.guild_id}.")
    return False


async def is_gm_channel_check(interaction: Interaction) -> bool:
    """Checks if the command is used in the designated GM channel for the guild."""
    if not isinstance(interaction.client, commands.Bot) or not hasattr(interaction.client, 'game_manager'):
        logging.warning("is_gm_channel_check: interaction.client is not a valid RPGBot instance or has no game_manager.")
        return False

    bot_instance = cast("RPGBot", interaction.client)

    if bot_instance.game_manager is None:
        logging.warning("is_gm_channel_check: GameManager not found on bot instance.")
        return False

    game_mngr = cast("GameManager", bot_instance.game_manager)
    if not interaction.guild_id:
        return False

    get_gm_channel_id_method = getattr(game_mngr, "get_gm_channel_id", None)
    gm_channel_id_val: Optional[int] = None
    if callable(get_gm_channel_id_method):
        gm_channel_id_str = get_gm_channel_id_method(str(interaction.guild_id))
        if gm_channel_id_str is not None:
            try:
                gm_channel_id_val = int(gm_channel_id_str)
            except ValueError:
                logging.warning(f"Invalid gm_channel_id '{gm_channel_id_str}' for guild {interaction.guild_id}.")
    else:
        logging.warning(f"GameManager does not have a callable 'get_gm_channel_id' method for guild {interaction.guild_id}.")
        return False

    return gm_channel_id_val == interaction.channel_id


class GameSetupCog(commands.Cog, name="Game Setup"):
    def __init__(self, bot: "RPGBot"):
        self.bot: "RPGBot" = bot

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

        bot_instance = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            logging.error(f"GameManager not available for /start_new_character by {interaction.user.id}")
            await interaction.followup.send("GameManager is not available. Please try again later or contact an admin.", ephemeral=True)
            return

        game_mngr = cast("GameManager", bot_instance.game_manager)

        db_service: Optional["DBService"] = None
        if hasattr(game_mngr, 'db_service') and game_mngr.db_service is not None:
            db_service = cast("DBService", game_mngr.db_service)
        else:
            logging.error(f"DBService not available on GameManager for /start_new_character by {interaction.user.id}")
            await interaction.followup.send("Database service is not available. Please contact an admin.", ephemeral=True)
            return

        if not hasattr(db_service, 'get_session') or not callable(db_service.get_session):
            logging.error(f"DBService does not have a callable get_session method for /start_new_character by {interaction.user.id}")
            await interaction.followup.send("Database service session handling is misconfigured. Please contact an admin.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        player_display_name = interaction.user.display_name

        active_session_ref: Optional[AsyncSession] = None

        try:
            async with db_service.get_session() as session_context:
                active_session_ref = session_context
                existing_player_stmt = select(Player).where(Player.discord_id == discord_id_str, Player.guild_id == guild_id_str)
                result = await active_session_ref.execute(existing_player_stmt)
                existing_player = result.scalars().first()

                if not existing_player:
                    logging.info(f"No existing Player found for {discord_id_str} in guild {guild_id_str}. Creating new Player.")

                    get_rule_method = getattr(game_mngr, "get_rule", None)
                    player_initial_language_val: Optional[str] = 'en'

                    if callable(get_rule_method):
                        player_initial_language_val = await get_rule_method(guild_id_str, 'default_language', 'en')

                    player_initial_language = str(player_initial_language_val) if player_initial_language_val is not None else 'en'

                    player_data: dict[str, Any] = {
                        "id": str(uuid.uuid4()),
                        "discord_id": discord_id_str,
                        "guild_id": guild_id_str,
                        "name_i18n": {"en": player_display_name},
                        "selected_language": player_initial_language,
                        "is_active": True
                    }
                    if isinstance(player_initial_language, str):
                        player_data["name_i18n"][player_initial_language] = player_display_name

                    new_player_record = await create_entity(active_session_ref, Player, player_data)
                    if not new_player_record:
                        logging.error(f"Failed to create Player record for {discord_id_str} in guild {guild_id_str} (create_entity returned None/False).")
                        await interaction.followup.send("There was an issue creating your player profile. Please try again.", ephemeral=True)
                        if active_session_ref is not None and hasattr(active_session_ref, 'is_active') and active_session_ref.is_active:
                            await active_session_ref.rollback()
                        return

                    await active_session_ref.commit()
                    logging.info(f"Player record {getattr(new_player_record, 'id', 'UNKNOWN_ID')} created for {discord_id_str} in guild {guild_id_str}.")
                    existing_player = new_player_record
                else:
                    logging.info(f"Existing Player {existing_player.id} found for {discord_id_str} in guild {guild_id_str}.")

        except IntegrityError:
            if active_session_ref is not None and hasattr(active_session_ref, 'is_active') and active_session_ref.is_active:
                await active_session_ref.rollback()
            logging.warning(f"IntegrityError during Player creation for {discord_id_str} in guild {guild_id_str}.", exc_info=True)
            pass
        except Exception as e:
            if active_session_ref is not None and hasattr(active_session_ref, 'is_active') and active_session_ref.is_active:
                 await active_session_ref.rollback()
            logging.error(f"Unexpected error during Player creation/check for {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send(f"An unexpected error occurred while setting up your player profile: {e}", ephemeral=True)
            return

        try:
            get_rule_method = getattr(game_mngr, "get_rule", None)
            default_lang_val = 'en'
            if callable(get_rule_method):
                default_lang_val = await get_rule_method(guild_id_str, 'default_language', 'en')

            effective_character_language_val = player_language or default_lang_val
            effective_character_language = str(effective_character_language_val) if effective_character_language_val is not None else 'en'

            if not hasattr(game_mngr, 'character_manager') or game_mngr.character_manager is None:
                logging.error(f"CharacterManager not available for /start_new_character by {interaction.user.id} in guild {guild_id_str}")
                await interaction.followup.send("Character manager is not available. Please contact an admin.", ephemeral=True)
                return

            char_manager = game_mngr.character_manager

            new_character_obj = await char_manager.create_new_character( # type: ignore
                guild_id=guild_id_str,
                user_id=interaction.user.id,
                character_name=character_name,
                language=effective_character_language,
            )

            if new_character_obj:
                char_id_log = getattr(new_character_obj, 'id', 'UNKNOWN_ID')
                logging.info(f"Character {char_id_log} created for Player {discord_id_str} in guild {guild_id_str}.")

                char_name_display_val = getattr(new_character_obj, 'name', character_name)
                char_name_display = str(char_name_display_val) if char_name_display_val is not None else character_name

                name_i18n_attr = getattr(new_character_obj, 'name_i18n', None)
                if isinstance(name_i18n_attr, dict):
                    lang_key = str(effective_character_language)
                    char_name_display = name_i18n_attr.get(lang_key, char_name_display)

                await interaction.followup.send(
                    f"Персонаж '{char_name_display}' успешно создан! "
                    f"Язык для сообщений: {effective_character_language}.",
                    ephemeral=True
                )
            else:
                logging.warning(f"Character creation returned None for Player {discord_id_str} in guild {guild_id_str}.")
                await interaction.followup.send(
                    f"Не удалось создать персонажа '{character_name}'. Проверьте, возможно имя уже занято или существуют другие ограничения.",
                    ephemeral=True
                )
        except CharacterAlreadyExistsError:
            logging.info(f"Character already exists for Player {discord_id_str} in guild {guild_id_str} when trying to create '{character_name}'.")
            await interaction.followup.send("У вас уже есть персонаж в этой игре. Вы не можете создать еще одного.", ephemeral=True)
        except Exception as e:
            logging.error(f"Unexpected error during Character creation for {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send(f"Произошла непредвиденная ошибка при создании персонажа: {e}", ephemeral=True)

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

        game_mngr = cast("GameManager", self.bot.game_manager)

        db_service: Optional["DBService"] = None
        if hasattr(game_mngr, 'db_service') and game_mngr.db_service is not None:
            db_service = cast("DBService", game_mngr.db_service)

        if not db_service or not hasattr(db_service, 'get_session_factory') or not callable(db_service.get_session_factory):
            logging.error(f"/start command by {discord_id_str} in guild {guild_id_str}: DBService or session factory not found/callable.")
            await interaction.followup.send("Database service is not available. Please try again later or contact an administrator.", ephemeral=True)
            return

        session_factory = db_service.get_session_factory()

        try:
            async with GuildTransaction(session_factory, guild_id_str) as session_context:
                session = cast(AsyncSession, session_context)
                existing_player = await get_entity_by_attributes(session, Player, {"discord_id": discord_id_str}, guild_id=guild_id_str)

                if existing_player:
                    await interaction.followup.send(f"{interaction.user.mention}, you already have a player profile here! Use `/character` commands to manage your characters.", ephemeral=True)
                else:
                    get_rule_method = getattr(game_mngr, "get_rule", None)
                    default_lang_val = 'en'
                    if callable(get_rule_method):
                         default_lang_val = await get_rule_method(guild_id_str, "default_language", "en")

                    default_lang = str(default_lang_val) if default_lang_val is not None else 'en'

                    player_name_i18n: dict[str, Any] = {"en": user_display_name}
                    if isinstance(default_lang, str) and default_lang not in player_name_i18n: # Key must be str
                        player_name_i18n[default_lang] = user_display_name

                    player_data: dict[str, Any] = {
                        "discord_id": discord_id_str,
                        "guild_id": guild_id_str,
                        "name_i18n": player_name_i18n,
                        "selected_language": default_lang,
                        "is_active": True
                    }

                    created_player = await create_entity(session, Player, player_data, guild_id=guild_id_str)

                    if created_player:
                        await interaction.followup.send(f"Welcome, {interaction.user.mention}! Your player profile is set up. Next, create your adventurer with `/character create name:YourCharacterName`.", ephemeral=True)
                        logging.info(f"Player profile created for {discord_id_str} in guild {guild_id_str} by /start command.")
                    else:
                        await interaction.followup.send("Sorry, there was an issue creating your player profile. Please try again later.", ephemeral=True)
                        logging.error(f"Player profile creation failed for {discord_id_str} in guild {guild_id_str} (create_entity returned None).")
        except IntegrityError as ie:
            logging.warning(f"IntegrityError for /start command user {discord_id_str} in guild {guild_id_str}: {ie}. Player likely created concurrently.", exc_info=True)
            await interaction.followup.send(f"{interaction.user.mention}, it looks like your profile was just created! Try `/character create name:YourCharacterName`.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in /start command for user {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred while setting up your profile. Please try again later.", ephemeral=True)


async def setup(bot: "RPGBot"):
    await bot.add_cog(GameSetupCog(bot))
    logging.info("GameSetupCog loaded.")
