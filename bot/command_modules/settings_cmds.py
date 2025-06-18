import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional, TYPE_CHECKING

from sqlalchemy.future import select # Added for Player query
from bot.database import user_settings_crud # Still used for timezone
from bot.database.models import UserSettings, Player # Added Player

if TYPE_CHECKING:
    from bot.bot_core import RPGBot

# Configure logger
logger = logging.getLogger(__name__)

# Predefined language choices
LANGUAGE_CHOICES = [
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="Russian", value="ru"),
    # Add more languages as needed
]

class SettingsCog(commands.Cog, name="Settings Commands"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot
        # Assuming a session factory or getter is available on the bot instance
        # For example: self.get_db_session = bot.get_db_session
        # If not, this cog might need a direct session_factory passed or use a manager service.
        # For this task, we'll assume self.bot.get_db_session() exists as per the prompt.

    # Main settings command group
    settings_group = app_commands.Group(
        name="settings",
        description="Manage your personal settings.",
        guild_only=True
    )

    # /settings view
    @settings_group.command(name="view", description="View your current personal settings.")
    async def view_settings(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        user_id_str = str(interaction.user.id)
        guild_id_str = str(interaction.guild_id)

        logger.info(f"User {user_id_str} in guild {guild_id_str} requested to view settings.")

        try:
            # Assuming get_db_session is a context manager yielding an AsyncSession
            async with self.bot.get_db_session() as session:
                settings = await user_settings_crud.get_user_settings(session, user_id_str, guild_id_str)

            if settings:
                lang_display = settings.language_code if settings.language_code else "Not set"
                tz_display = settings.timezone if settings.timezone else "Not set"
                embed = discord.Embed(title=f"{interaction.user.display_name}'s Settings", color=discord.Color.blue())
                embed.add_field(name="Language Code", value=lang_display, inline=True)
                embed.add_field(name="Timezone", value=tz_display, inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(
                    "You don't have any settings configured yet. Use `/settings set language` or `/settings set timezone` to configure them.",
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Error fetching settings for user {user_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.response.send_message("An error occurred while trying to fetch your settings. Please try again later.", ephemeral=True)

    # Settings 'set' subgroup
    settings_set_group = app_commands.Group(
        name="set",
        description="Set your personal settings.",
        parent=settings_group
    )

    # /settings set language
    async def _set_player_language_preference(self, interaction: discord.Interaction, guild_id_str: str, user_id_str: str, chosen_lang_value: str, chosen_lang_name: str) -> str:
        """Helper method to set player language and return a response message."""
        if not hasattr(self.bot, 'game_manager') or not self.bot.game_manager:
            logger.error(f"Language change for user {user_id_str} in guild {guild_id_str} failed: GameManager not found on bot.")
            return "The game manager is not available. Please try again later or contact an administrator."

        game_mngr = self.bot.game_manager
        if not game_mngr.db_service:
            logger.error(f"Language change for user {user_id_str} in guild {guild_id_str} failed: DBService not found in GameManager.")
            return "The database service is not available. Please try again later or contact an administrator."

        try:
            player: Optional[Player] = await game_mngr.get_player_by_discord_id(
                discord_id=user_id_str,
                guild_id=guild_id_str
            )

            if not player:
                logger.warning(f"Player record not found for discord_id {user_id_str} in guild {guild_id_str} when trying to set language.")
                return "Your player profile was not found. Please ensure you have started playing or contact support."

            success = await game_mngr.db_service.update_player_field(
                player_id=player.id,
                field_name='selected_language',
                value=chosen_lang_value,
                guild_id_str=guild_id_str
            )

            if success:
                logger.info(f"Successfully updated Player.selected_language for user {user_id_str} (Player ID: {player.id}) in guild {guild_id_str} to {chosen_lang_value}.")
                return f"Your language has been set to: {chosen_lang_name} ({chosen_lang_value})."
            else:
                logger.error(f"Failed to save language {chosen_lang_value} to DB for user {user_id_str} (Player ID: {player.id}) in guild {guild_id_str}.")
                return "Could not save your language preference. Please try again or contact an administrator."
        except Exception as e:
            logger.error(f"Error setting language for user {user_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            return "An unexpected error occurred while trying to set your language. Please try again later."

    @settings_set_group.command(name="language", description="Set your preferred language.")
    @app_commands.choices(language_code=LANGUAGE_CHOICES)
    @app_commands.describe(language_code="Choose your preferred language.")
    async def set_language(self, interaction: discord.Interaction, language_code: app_commands.Choice[str]):
        if not interaction.guild_id: # Should be redundant due to guild_only on group
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        user_id_str = str(interaction.user.id)
        guild_id_str = str(interaction.guild_id)
        chosen_lang_value = language_code.value
        chosen_lang_name = language_code.name

        logger.info(f"User {user_id_str} in guild {guild_id_str} attempting to set language to {chosen_lang_value} via /settings set language.")

        # Defer the response as the helper method can take some time
        await interaction.response.defer(ephemeral=True)
        response_message = await self._set_player_language_preference(interaction, guild_id_str, user_id_str, chosen_lang_value, chosen_lang_name)
        await interaction.followup.send(response_message)


    @app_commands.command(name="lang", description="Set your preferred language for bot interactions.")
    @app_commands.guild_only()
    @app_commands.choices(language_code=LANGUAGE_CHOICES)
    @app_commands.describe(language_code="Choose your preferred language.")
    async def lang_command(self, interaction: discord.Interaction, language_code: app_commands.Choice[str]):
        # guild_id is guaranteed by @app_commands.guild_only()
        user_id_str = str(interaction.user.id)
        guild_id_str = str(interaction.guild_id)
        chosen_lang_value = language_code.value
        chosen_lang_name = language_code.name

        logger.info(f"User {user_id_str} in guild {guild_id_str} attempting to set language to {chosen_lang_value} via /lang.")

        # Defer the response as the helper method can take some time
        await interaction.response.defer(ephemeral=True)
        response_message = await self._set_player_language_preference(interaction, guild_id_str, user_id_str, chosen_lang_value, chosen_lang_name)
        await interaction.followup.send(response_message)

    # /settings set timezone
    @settings_set_group.command(name="timezone", description="Set your preferred timezone (e.g., UTC, Europe/Moscow).")
    @app_commands.describe(timezone_str="Enter your timezone (e.g., UTC, America/New_York).")
    async def set_timezone(self, interaction: discord.Interaction, timezone_str: str):
        if not interaction.guild_id:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        user_id_str = str(interaction.user.id)
        guild_id_str = str(interaction.guild_id)

        logger.info(f"User {user_id_str} in guild {guild_id_str} attempting to set timezone to {timezone_str}.")

        # Basic validation for timezone string length, more robust validation would require a timezone library
        if not (3 <= len(timezone_str) <= 50):
            await interaction.response.send_message("Invalid timezone string. Please provide a valid timezone (e.g., UTC, Europe/Moscow).", ephemeral=True)
            return

        try:
            async with self.bot.get_db_session() as session:
                await user_settings_crud.create_or_update_user_settings(
                    session,
                    user_id=user_id_str,
                    guild_id=guild_id_str,
                    timezone=timezone_str
                )
            await interaction.response.send_message(f"Your timezone has been set to: {timezone_str}.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error setting timezone for user {user_id_str} in guild {guild_id_str}: {e}", exc_info=True)
            await interaction.response.send_message("An error occurred while trying to set your timezone. Please try again later.", ephemeral=True)


async def setup(bot: "RPGBot"):
    await bot.add_cog(SettingsCog(bot))
    logger.info("SettingsCog loaded.")

# Note on self.bot.get_db_session():
# This code assumes that self.bot (an instance of RPGBot) has a method `get_db_session()`
# which acts as an async context manager returning an SQLAlchemy AsyncSession.
# Example:
# class RPGBot(commands.Bot):
#     ...
#     @asynccontextmanager
#     async def get_db_session(self) -> AsyncIterator[AsyncSession]:
#         async with self.async_session_factory() as session:
#             try:
#                 yield session
#                 await session.commit() # Or commit could be handled by the CRUD operation itself
#             except Exception:
#                 await session.rollback()
#                 raise
#             finally:
#                 await session.close() # If session_factory doesn't auto-close
#
# If the bot uses a different pattern (e.g., a session per command context, or managers handling sessions),
# the database interaction parts in this cog would need to be adjusted accordingly.
# For now, the CRUD functions are designed to accept a session, and this cog assumes it can get one.
# The create_or_update_user_settings function in user_settings_crud.py handles its own commit/rollback.
# So the session manager in the bot might not need to explicitly commit if CRUDs do it.
# However, it's good practice for the session provider to handle rollback on exception.
# The CRUDs currently re-raise on IntegrityError after rollback, so the session provider should catch it.
# The current CRUD `create_or_update_user_settings` already handles commit and rollback.
# So the `get_db_session` context manager might primarily be for ensuring the session is closed
# and potentially handling higher-level transaction errors if a command involved multiple CRUDs.
# The current implementation of CRUDs (committing per operation) means each call is its own transaction.
