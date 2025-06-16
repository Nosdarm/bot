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

        # Placeholder for actual Master Role ID checking:
        # This section needs to be implemented based on how Master Role IDs are stored and retrieved.
        # For example, if master_role_id is stored in GuildConfig or a global bot config:
        #
        # master_role_id_str = None
        # try:
        #     # Assuming DBService is part of the bot instance or globally accessible
        #     # This is just an example path, adapt to your DBService access pattern.
        #     if hasattr(interaction.client, 'db_service') and interaction.client.db_service:
        #         async with interaction.client.db_service.get_session() as session:
        #             # This assumes a way to get a specific guild setting, e.g., the master role ID
        #             # master_role_id_str = await interaction.client.db_service.get_guild_setting(
        #             #    str(interaction.guild_id), "master_role_id", session=session
        #             # )
        #             # Or, if GuildConfig stores it directly:
        #             from bot.database.models import GuildConfig # Local import to avoid circularity if models use decorators
        #             from sqlalchemy.future import select
        #             stmt = select(GuildConfig.master_role_id_for_commands).where(GuildConfig.guild_id == str(interaction.guild_id))
        #             result = await session.execute(stmt)
        #             master_role_id_str = result.scalars().first() # Assuming GuildConfig has such a field
        #     else:
        #         logger.warning("is_master_role: DBService not found on bot client. Cannot fetch Master Role ID.")
        #
        # except Exception as e:
        #     logger.error(f"is_master_role: Error fetching Master Role ID for guild {interaction.guild.id}: {e}", exc_info=True)
        #     return False # Fail closed
        #
        # if not master_role_id_str:
        #     logger.warning(f"is_master_role: Master Role ID not configured for guild {interaction.guild.id}.")
        #     return False
        #
        # try:
        #     master_role_id = int(master_role_id_str)
        # except ValueError:
        #     logger.error(f"is_master_role: Master Role ID '{master_role_id_str}' for guild {interaction.guild.id} is not a valid integer.")
        #     return False
        #
        # user_role_ids = {role.id for role in interaction.user.roles}
        # if master_role_id in user_role_ids:
        #     logger.info(f"is_master_role: User {interaction.user.id} has Master Role ({master_role_id}) in guild {interaction.guild.id}.")
        #     return True

        logger.warning(f"is_master_role: User {interaction.user.id} does not have the Master Role (or it's not configured/owner override not met) in guild {interaction.guild.id}.")
        return False # Default to False if not owner and actual role check isn't implemented/passes

    return app_commands.check(predicate)
