import logging
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Callable, Coroutine, Any

logger = logging.getLogger(__name__)

@asynccontextmanager
async def GuildTransaction(session_factory: Callable[[], AsyncSession], guild_id: str, commit_on_exit: bool = True):
    """
    Provides a transactional scope that is aware of a specific guild_id.

    It stores the guild_id in session.info['current_guild_id'] and can perform
    pre-commit checks to ensure data integrity across guild-specific tables.

    Args:
        session_factory: A callable that returns a new SQLAlchemy AsyncSession.
        guild_id: The ID of the guild for which this transaction is scoped.
        commit_on_exit: If True (default), commits the transaction upon successful
                        exit from the context block. If False, the caller is
                        responsible for committing the session.
    """
    if not guild_id:
        raise ValueError("guild_id must be provided for a GuildTransaction")

    # session_factory is a method like DBService.get_session_factory
    # It returns a sessionmaker instance (e.g., adapter._SessionLocal)
    session_maker_instance = session_factory()

    # Now, call the sessionmaker instance to get an actual AsyncSession
    actual_session: AsyncSession = session_maker_instance()

    if not isinstance(actual_session, AsyncSession):
        logger.error(f"GuildTransaction: The provided factory mechanism did not ultimately yield an AsyncSession. Got: {type(actual_session)}")
        raise TypeError("The session factory mechanism must produce an SQLAlchemy AsyncSession.")

    original_guild_id_in_info = actual_session.info.get("current_guild_id")
    actual_session.info["current_guild_id"] = guild_id

    transaction = None
    try:
        # Begin a transaction. If already in a transaction, this creates a savepoint.
        transaction = actual_session.begin_nested() if actual_session.in_transaction() else actual_session.begin()
        async with transaction:
            logger.debug(f"GuildTransaction started for guild_id: {guild_id} with session {id(actual_session)}.")
            yield actual_session # The session yielded is now "guild-aware" via its .info

            # Pre-commit/flush verification (best effort)
            guild_id_str = str(guild_id)

            for obj in actual_session.dirty:
                if hasattr(obj, 'guild_id'):
                    obj_guild_id = getattr(obj, 'guild_id', None)
                    if obj_guild_id is not None and str(obj_guild_id) != guild_id_str:
                        logger.error(f"GuildTransaction: Cross-guild write attempt detected for dirty object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}). Expected guild {guild_id_str}, got {obj_guild_id}.")
                        raise ValueError(f"Cross-guild write attempt for dirty object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}). Expected guild {guild_id_str}, got {obj_guild_id}.")

            for obj in actual_session.new:
                if hasattr(obj, 'guild_id'):
                    obj_guild_id = getattr(obj, 'guild_id', None)
                    if obj_guild_id is None and "current_guild_id" in actual_session.info:
                        logger.debug(f"GuildTransaction: Auto-setting guild_id {guild_id_str} for new object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}).")
                        setattr(obj, 'guild_id', guild_id_str)
                    elif obj_guild_id is not None and str(obj_guild_id) != guild_id_str:
                        logger.error(f"GuildTransaction: Cross-guild write attempt detected for new object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}). Expected guild {guild_id_str}, got {obj_guild_id}.")
                        raise ValueError(f"Cross-guild write attempt for new object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}). Expected guild {guild_id_str}, got {obj_guild_id}.")

            if commit_on_exit:
                pass # Commit handled by `async with transaction:`

            logger.debug(f"GuildTransaction for guild_id: {guild_id} completed operations within 'try' block.")

    except Exception as e:
        logger.error(f"GuildTransaction for guild_id: {guild_id} encountered an exception: {e}. Transaction will be rolled back.", exc_info=True)
        raise
    finally:
        if original_guild_id_in_info is not None:
            actual_session.info["current_guild_id"] = original_guild_id_in_info
        elif "current_guild_id" in actual_session.info:
            del actual_session.info["current_guild_id"]

        await actual_session.close()
        logger.debug(f"GuildTransaction: Session {id(actual_session)} for guild_id: {guild_id} closed.")
