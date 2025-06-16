# bot/utils/decorators.py
import logging
import discord
from discord import Interaction, app_commands
from functools import wraps

# In a real scenario, DBService might be accessed via the bot instance
# from bot.services.db_service import DBService

logger = logging.getLogger(__name__)

def is_master_role():
    """
    Decorator to check if the interacting user has the Master role for the guild.
    The Master role ID should be configurable per guild.
    """
    async def predicate(interaction: Interaction) -> bool:
        if not interaction.guild: # Command used outside of a guild
            logger.warning(f"is_master_role check failed: Command used by {interaction.user.id} outside of a guild.")
            return False

        if interaction.user.id == interaction.guild.owner_id:
            logger.info(f"is_master_role: User {interaction.user.id} is guild owner in {interaction.guild.id}. Granting access for now.")
            return True

        # Actual Master Role ID checking:
        master_role_id_str = None
        try:
            if not hasattr(interaction.client, 'db_service') or not interaction.client.db_service:
                logger.warning(f"is_master_role: DBService not found on bot client (user: {interaction.user.id}, guild: {interaction.guild.id}). Cannot fetch Master Role ID.")
                return False # Fail closed if DB service is not available

            # Dynamically import here if necessary, or ensure it's available globally
            from bot.database.models import GuildConfig
            from sqlalchemy.future import select

            db_service = interaction.client.db_service
            async with db_service.get_session() as session:
                stmt = select(GuildConfig.master_role_id).where(GuildConfig.guild_id == str(interaction.guild.id))
                result = await session.execute(stmt)
                master_role_id_str = result.scalars().first()

        except Exception as e:
            logger.error(f"is_master_role: Error fetching Master Role ID for guild {interaction.guild.id} (user: {interaction.user.id}): {e}", exc_info=True)
            return False # Fail closed on DB error

        if not master_role_id_str:
            logger.info(f"is_master_role: Master Role ID not configured for guild {interaction.guild.id} (user: {interaction.user.id}). Access denied (owner check already passed).")
            return False # No role configured, and user is not owner

        try:
            master_role_id_int = int(master_role_id_str)
        except ValueError:
            logger.error(f"is_master_role: Master Role ID '{master_role_id_str}' for guild {interaction.guild.id} (user: {interaction.user.id}) is not a valid integer. Access denied.")
            return False

        # Ensure interaction.user is a Member object to access roles
        if not isinstance(interaction.user, discord.Member):
            logger.warning(f"is_master_role: interaction.user is not a discord.Member object for user {interaction.user.id} in guild {interaction.guild.id}. Cannot check roles.")
            return False

        user_role_ids = {role.id for role in interaction.user.roles}
        if master_role_id_int in user_role_ids:
            logger.info(f"is_master_role: User {interaction.user.id} has Master Role ({master_role_id_int}) in guild {interaction.guild.id}. Access granted.")
            return True

        logger.info(f"is_master_role: User {interaction.user.id} does not have the configured Master Role ({master_role_id_int}) in guild {interaction.guild.id}. Access denied.")
        return False

    return app_commands.check(predicate)
