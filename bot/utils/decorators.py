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


def guild_transactional(guild_id_param_name: str = "guild_id", session_factory_param_name: str = "db_session_factory", commit_on_exit: bool = True):
    """
    Decorator to wrap a function call within a GuildTransaction context.
    It extracts guild_id and a session factory (or an active session) from function arguments
    or the 'self' object if it's a method of a class with a db_service.

    Args:
        guild_id_param_name: The name of the parameter in the decorated function
                             that holds the guild_id.
        session_factory_param_name: The name of the parameter in the decorated function
                                    that holds the session factory or an active session.
                                    Alternatively, if 'self' is the first arg and has 'db_service.get_session_factory',
                                    that will be used.
        commit_on_exit: Whether the transaction should be committed on successful exit.
    """
    from bot.database.guild_transaction import GuildTransaction # Local import to avoid circular dependencies at module level

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            guild_id = kwargs.get(guild_id_param_name)
            if guild_id is None and args:
                # Try to find guild_id in positional arguments by matching name if signature is available
                # This is a simplified approach; inspect.signature could be used for robustness
                try:
                    func_param_names = func.__code__.co_varnames[:func.__code__.co_argcount]
                    if guild_id_param_name in func_param_names:
                        guild_id_idx = func_param_names.index(guild_id_param_name)
                        if guild_id_idx < len(args):
                            guild_id = args[guild_id_idx]
                except AttributeError: # E.g. if func is not a standard Python function
                    pass

            if guild_id is None:
                raise ValueError(f"Decorator guild_transactional: guild_id ('{guild_id_param_name}') not found in function arguments.")

            session_factory_or_session = kwargs.get(session_factory_param_name)
            if session_factory_or_session is None and args:
                # Try to find session factory in positional args or from 'self'
                resolved_from_self = False
                if args and hasattr(args[0], 'db_service') and hasattr(args[0].db_service, 'get_session_factory'):
                    # Common pattern: self.db_service.get_session_factory()
                    session_factory_or_session = args[0].db_service.get_session_factory
                    resolved_from_self = True
                elif args and hasattr(args[0], 'get_db_session'): # RPGBot like object
                    # This would yield an active session, GuildTransaction can handle it
                    session_factory_or_session = args[0].get_db_session
                    # This is tricky because get_db_session is an async context manager itself.
                    # GuildTransaction is designed to accept a factory or a session.
                    # If get_db_session is passed, GuildTransaction would need to be adapted or
                    # we'd need to enter that context here.
                    # For simplicity, let's prefer get_session_factory.
                    # This branch might need refinement based on exact usage.
                    # For now, if it's get_db_session, it's likely not a factory.
                    # GuildTransaction will warn if it receives an active session.
                    pass # Let GuildTransaction handle it, will log warning if it's an active session.


                if not resolved_from_self:
                    try:
                        func_param_names = func.__code__.co_varnames[:func.__code__.co_argcount]
                        if session_factory_param_name in func_param_names:
                            session_factory_idx = func_param_names.index(session_factory_param_name)
                            if session_factory_idx < len(args):
                                session_factory_or_session = args[session_factory_idx]
                    except AttributeError:
                        pass

            if session_factory_or_session is None:
                raise ValueError(f"Decorator guild_transactional: session factory/session ('{session_factory_param_name}') not found.")

            async with GuildTransaction(session_factory_or_session, str(guild_id), commit_on_exit=commit_on_exit) as session:
                # Pass the active session to the decorated function, replacing the factory if it was passed that way
                # This requires the decorated function to expect an active session as a kwarg or positional arg.

                # Create new args/kwargs to pass the session
                # If the original function expected a factory, this changes its contract.
                # A common pattern is for service methods to accept an optional session.

                # Simplest: assume the function can take 'session' as a kwarg or it's already handled
                # by how session_factory_or_session was obtained (e.g. if it was 'self.get_db_session')

                # If the original function had session_factory_param_name, we replace it with the active session.
                # This is complex due to args vs kwargs.
                # A common way is to add `session` to kwargs and let the function pick it up.
                kwargs_for_func = kwargs.copy()

                # Check if the decorated function explicitly asks for a 'session' parameter.
                # This is a simple check; `inspect.signature` is more robust.
                expects_session_kwarg = 'session' in func.__code__.co_varnames

                if not expects_session_kwarg:
                    # If the function expected the factory/session via session_factory_param_name,
                    # we need to ensure it gets the *active session* via that name if that's how it's coded.
                    # This can be tricky. The most straightforward is if the decorated function
                    # is designed to accept an optional `session: AsyncSession = None` kwarg.
                    # Then we can just do: kwargs_for_func['session'] = session
                    pass # Assuming for now the function might get the session implicitly or is not expecting it directly.
                         # This implies GuildTransaction sets it on 'self' or a global context, which it does not.
                         # The standard way is for the function to accept the session.

                # Let's assume the decorated function is designed to accept 'session' as a keyword argument.
                kwargs_for_func['session'] = session

                # Remove the original factory parameter if it was in kwargs, to avoid passing both factory and session
                if session_factory_param_name in kwargs_for_func and session_factory_param_name != 'session':
                    del kwargs_for_func[session_factory_param_name]

                # How to handle if session_factory_param_name was in *args? This gets complex.
                # For simplicity, this decorator works best if the decorated function
                # is designed to receive an active `session` via a kwarg, or if the session_factory_param_name
                # IS 'session'.

                # If the decorated function is a method and session_factory_param_name was not explicitly passed,
                # but resolved from self.db_service.get_session_factory, then 'args' and 'kwargs' don't
                # contain the factory. We just need to ensure 'session' is available.

                return await func(*args, **kwargs_for_func)
        return wrapper
    return decorator
