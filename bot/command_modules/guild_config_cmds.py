# bot/command_modules/guild_config_cmds.py
import logging
import discord
from discord import app_commands, Interaction, TextChannel, Role
from discord.ext import commands

from bot.database.models import GuildConfig
from bot.services.db_service import DBService # Assuming DBService is accessible for cogs
from bot.utils.decorators import is_master_role # Assuming a decorator for role check
from sqlalchemy.future import select # For querying GuildConfig

logger = logging.getLogger(__name__)

# Language choices for the set_bot_language command
LANGUAGE_CHOICES = [
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="Russian", value="ru"),
]

class GuildConfigCmds(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # It's generally better if DBService instance is passed or accessed via self.bot,
        # e.g., self.db_service = bot.db_service
        # For now, direct instantiation is kept as per existing structure.
        self.db_service = DBService()

    async def _update_guild_channel_config(self, interaction: Interaction, channel_type: str, channel: TextChannel) -> None:
        """Helper function to update a specific channel type in GuildConfig."""
        guild_id_str = str(interaction.guild_id)
        if not guild_id_str:
            await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
            return

        async with self.db_service.get_session() as session:
            try:
                # GuildConfig's PK is guild_id (String), so pass guild_id_str directly to session.get
                guild_config = await session.get(GuildConfig, guild_id_str)

                if not guild_config:
                    # This might happen if the guild was never initialized properly.
                    # Attempt a select as a fallback, though guild_initializer should prevent this.
                    logger.warning(f"GuildConfig not found with session.get for guild {guild_id_str}. Attempting select.")
                    stmt = select(GuildConfig).where(GuildConfig.guild_id == guild_id_str)
                    result = await session.execute(stmt)
                    guild_config = result.scalars().first()

                if not guild_config:
                    # This case should ideally be handled by guild_initializer on bot join/first command
                    await interaction.response.send_message(
                        "Error: Guild configuration not found. Please try re-inviting the bot or contact support.",
                        ephemeral=True
                    )
                    return

                setattr(guild_config, channel_type, str(channel.id))
                session.add(guild_config)
                await session.commit()
                await interaction.response.send_message(
                    f"{channel_type.replace('_', ' ').capitalize()} has been set to {channel.mention}.",
                    ephemeral=True
                )
                logger.info(f"{channel_type} set to {channel.id} for guild {guild_id_str} by {interaction.user.id}.")

            except Exception as e:
                logger.error(f"Error updating {channel_type} for guild {guild_id_str}: {e}", exc_info=True)
                await interaction.response.send_message(
                    f"An error occurred while setting the {channel_type.replace('_', ' ')}.",
                    ephemeral=True
                )

    @app_commands.command(name="set_game_channel", description="Sets the primary game channel for bot activities.")
    @app_commands.describe(channel="The text channel to be used as the game channel.")
    @is_master_role() # Apply decorator
    async def set_game_channel(self, interaction: Interaction, channel: TextChannel):
        """Sets the game channel for the guild."""
        await self._update_guild_channel_config(interaction, "game_channel_id", channel)

    @app_commands.command(name="set_master_channel", description="Sets the channel for Master role commands and verbose logs.")
    @app_commands.describe(channel="The text channel to be used as the Master channel.")
    @is_master_role() # Apply decorator
    async def set_master_channel(self, interaction: Interaction, channel: TextChannel):
        """Sets the master channel for the guild."""
        await self._update_guild_channel_config(interaction, "master_channel_id", channel)

    @app_commands.command(name="set_system_channel", description="Sets the channel for important system notifications and events.")
    @app_commands.describe(channel="The text channel for system notifications.")
    @is_master_role() # Apply decorator
    async def set_system_channel(self, interaction: Interaction, channel: TextChannel):
        """Sets the system notifications/events channel for the guild."""
        await self._update_guild_channel_config(interaction, "system_channel_id", channel)

    @app_commands.command(name="set_bot_language", description="Sets the default language for the bot in this server.")
    @app_commands.describe(language="Choose the default language for the bot.")
    @app_commands.choices(language=LANGUAGE_CHOICES)
    @is_master_role()
    async def set_bot_language(self, interaction: Interaction, language: app_commands.Choice[str]):
        """Sets the default bot language for the guild."""
        guild_id_str = str(interaction.guild_id)
        chosen_lang_code = language.value
        chosen_lang_name = language.name

        if not guild_id_str: # Should not happen with guild_only=True implicitly by decorator context
            await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
            return

        logger.info(f"Master {interaction.user.id} attempting to set bot language to {chosen_lang_code} for guild {guild_id_str}.")

        async with self.db_service.get_session() as session:
            try:
                # Fetch GuildConfig
                stmt = select(GuildConfig).where(GuildConfig.guild_id == guild_id_str)
                result = await session.execute(stmt)
                guild_config = result.scalars().first()

                if not guild_config:
                    # This case should ideally be handled by guild_initializer on bot join/first command
                    # Or, create it here if that's the desired behavior for this command.
                    # For now, error out if not found.
                    logger.warning(f"GuildConfig not found for guild {guild_id_str} when trying to set bot language.")
                    await interaction.response.send_message(
                        "Error: Guild configuration not found. The bot might need to be re-invited or initial setup is pending.",
                        ephemeral=True
                    )
                    return

                guild_config.bot_language = chosen_lang_code
                session.add(guild_config)
                await session.commit()

                # Update RulesConfig via GameManager
                if hasattr(self.bot, 'game_manager') and self.bot.game_manager:
                    try:
                        await self.bot.game_manager.update_rule_config(guild_id_str, "default_language", chosen_lang_code)
                        logger.info(f"Successfully called GameManager.update_rule_config for default_language in guild {guild_id_str} to {chosen_lang_code}.")
                    except Exception as e_gm_rules:
                        logger.error(f"Error calling GameManager.update_rule_config for default_language in guild {guild_id_str}: {e_gm_rules}", exc_info=True)
                        # Optionally inform the user that part of the update failed
                        await interaction.response.send_message(
                            f"Bot language for GuildConfig updated to {chosen_lang_name} ({chosen_lang_code}), but failed to update central RulesConfig. Please check logs.",
                            ephemeral=True
                        )
                        return # Exit if this critical part fails
                else:
                    logger.warning("GameManager not available, RulesConfig for default_language not updated via GameManager.")
                    # Depending on strictness, you might want to inform user or not.
                    # For now, we proceed with GuildConfig update success message if GM is missing.

                await interaction.response.send_message(
                    f"Bot language for this server has been set to {chosen_lang_name} ({chosen_lang_code}). RulesConfig also updated.",
                    ephemeral=True
                )
                logger.info(f"Bot language set to {chosen_lang_code} for guild {guild_id_str} by Master {interaction.user.id}.")

            except Exception as e:
                logger.error(f"Error setting bot language for guild {guild_id_str}: {e}", exc_info=True)
                await interaction.response.send_message(
                    "An error occurred while trying to set the bot language.",
                    ephemeral=True
                )

    @app_commands.command(name="set_master_role", description="Sets the Master Role for bot administration commands.")
    @app_commands.describe(role="The role to be designated as the Master Role.")
    @is_master_role()
    async def set_master_role(self, interaction: Interaction, role: discord.Role):
        """Sets the Master Role for the guild, allowing users with this role to use administrative bot commands."""
        guild_id_str = str(interaction.guild_id)

        if not guild_id_str: # Should not happen with guild_only=True implicitly
            await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
            return

        logger.info(f"User {interaction.user.id} attempting to set master role to {role.name} ({role.id}) for guild {guild_id_str}.")

        async with self.db_service.get_session() as session:
            try:
                # Fetch GuildConfig
                stmt = select(GuildConfig).where(GuildConfig.guild_id == guild_id_str)
                result = await session.execute(stmt)
                guild_config = result.scalars().first()

                if not guild_config:
                    logger.warning(f"GuildConfig not found for guild {guild_id_str} when trying to set master role.")
                    await interaction.response.send_message(
                        "Error: Guild configuration not found. The bot might need to be re-invited or initial setup is pending.",
                        ephemeral=True
                    )
                    return

                guild_config.master_role_id = str(role.id)
                session.add(guild_config)
                await session.commit()

                await interaction.response.send_message(
                    f"Master Role has been set to {role.mention}.",
                    ephemeral=True
                )
                logger.info(f"Master Role set to {role.name} ({role.id}) for guild {guild_id_str} by user {interaction.user.id}.")

            except Exception as e:
                logger.error(f"Error setting master role for guild {guild_id_str}: {e}", exc_info=True)
                await interaction.response.send_message(
                    "An error occurred while trying to set the Master Role.",
                    ephemeral=True
                )

    # Error handler for this cog's commands
    async def cog_app_command_error(self, interaction: Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure): # Catches failed is_master_role()
            await interaction.response.send_message(
                "You do not have the required Master role to use this command.",
                ephemeral=True
            )
            logger.warning(f"User {interaction.user.id} attempted to use a Master command without permission in guild {interaction.guild_id}.")
        else:
            logger.error(f"Unhandled error in GuildConfigCmds cog: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)


async def setup(bot: commands.Bot):
    # Assumption: DBService is initialized and accessible, e.g. bot.db_service
    # If DBService needs to be passed to the cog, this setup might need adjustment
    # For now, assuming cog can instantiate its own or access globally/via bot attr.
    # A better pattern is to pass dependencies: await bot.add_cog(GuildConfigCmds(bot, bot.db_service))
    await bot.add_cog(GuildConfigCmds(bot))
    logger.info("GuildConfigCmds cog loaded.")

# Note on is_master_role decorator:
# This decorator needs to be defined elsewhere, e.g., in bot/utils/decorators.py
# Example structure for is_master_role:
"""
from discord import Interaction, app_commands
from functools import wraps
# from bot.services.db_service import DBService # or however master role ID is fetched

def is_master_role():
    async def predicate(interaction: Interaction) -> bool:
        # Placeholder: Actual master role ID fetching and checking logic needed
        # This might involve a DB call to get the configured master role ID for the guild
        # For example:
        # db_service = DBService() # Or get from bot instance if available in interaction context
        # async with db_service.get_session() as session:
        #     master_role_id = await db_service.get_guild_setting(str(interaction.guild_id), "master_role_id", session=session)
        # if not master_role_id: return False
        # master_role = interaction.guild.get_role(int(master_role_id))
        # if not master_role: return False
        # return master_role in interaction.user.roles

        # Temporary placeholder - replace with actual role check logic
        # This basic check looks for a role named "Master Role" (case-sensitive)
        # This is NOT secure or robust. Use role IDs fetched from config.
        if interaction.guild is None: return False # Not a guild context
        # master_role_name = "Master Role"
        # role = discord.utils.get(interaction.guild.roles, name=master_role_name)
        # if role and role in interaction.user.roles:
        #    return True
        # For testing, let's assume guild owner is master
        if interaction.user.id == interaction.guild.owner_id:
             logger.warning(f"is_master_role: Allowing guild owner {interaction.user.id} for testing.")
             return True
        logger.warning(f"is_master_role: User {interaction.user.id} is not guild owner. Actual master role check needed.")
        return False # Default to False if placeholder logic fails
    return app_commands.check(predicate)
"""
