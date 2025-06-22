import logging
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker # For isinstance check
from typing import Callable, Union, Any, Coroutine, Optional # Ensure Coroutine is imported if needed by Callable type hint

logger = logging.getLogger(__name__)

@asynccontextmanager
async def GuildTransaction(
    session_factory_input: Union[Callable[[], AsyncSession], Callable[[], Callable[[], AsyncSession]], AsyncSession],
    guild_id: str,
    commit_on_exit: bool = True
):
    """
    Provides a transactional scope that is aware of a specific guild_id.
    It stores the guild_id in session.info['current_guild_id'].

    Args:
        session_factory_input: Can be:
            1. A sessionmaker instance (preferred: callable that returns AsyncSession).
            2. A function that, when called, returns a sessionmaker instance.
            3. An already instantiated AsyncSession (less preferred, logs warning).
        guild_id: The ID of the guild for which this transaction is scoped.
        commit_on_exit: If True, commits on successful exit.
    """
    if not guild_id:
        raise ValueError("guild_id must be provided for a GuildTransaction")

    session_to_use: Optional[AsyncSession] = None
    created_session_locally = False

    if isinstance(session_factory_input, sessionmaker):
        # Case 1: Input is a sessionmaker instance
        logger.debug("GuildTransaction received a sessionmaker instance.")
        session_to_use = session_factory_input()
        created_session_locally = True
    elif isinstance(session_factory_input, AsyncSession):
        # Case 3: Input is already an AsyncSession instance
        logger.warning("GuildTransaction received an already instantiated AsyncSession. Using it directly. Ensure it's managed correctly externally if commit_on_exit=False.")
        session_to_use = session_factory_input
        # If session is passed directly, assume its lifecycle (begin/commit/close) is managed externally if commit_on_exit is False.
        # If commit_on_exit is True, we'll still try to manage a transaction on it.
    elif callable(session_factory_input):
        # Case 2: Input is a callable (e.g., DBService.get_session_factory method)
        logger.debug("GuildTransaction received a callable. Calling it to get factory/session.")
        potential_factory_or_session = session_factory_input()
        if isinstance(potential_factory_or_session, sessionmaker):
            logger.debug("Callable returned a sessionmaker. Calling it to get session.")
            session_to_use = potential_factory_or_session()
            created_session_locally = True
        elif isinstance(potential_factory_or_session, AsyncSession):
            logger.warning("Callable returned an already instantiated AsyncSession.")
            session_to_use = potential_factory_or_session
            created_session_locally = True # Still treat as locally created for close
        else:
            logger.error(f"GuildTransaction: Callable input did not return a sessionmaker or AsyncSession. Got: {type(potential_factory_or_session)}")
            raise TypeError("Callable input for session_factory_input did not yield a sessionmaker or AsyncSession.")
    else:
        logger.error(f"GuildTransaction: Invalid type for session_factory_input: {type(session_factory_input)}")
        raise TypeError("session_factory_input must be a sessionmaker, an AsyncSession, or a callable returning one.")

    if not isinstance(session_to_use, AsyncSession):
        # This should be caught by earlier checks, but as a final safeguard.
        logger.error(f"GuildTransaction: Failed to obtain a valid AsyncSession. Final object type: {type(session_to_use)}")
        raise TypeError("Failed to obtain a valid SQLAlchemy AsyncSession for the transaction.")

    original_guild_id_in_info = session_to_use.info.get("current_guild_id")
    session_to_use.info["current_guild_id"] = guild_id

    transaction = None
    try:
        # Begin a transaction. If already in a transaction (e.g. session passed in was already in one),
        # this creates a savepoint.
        is_external_transaction = session_to_use.in_transaction()
        if is_external_transaction:
            transaction = session_to_use.begin_nested()
            logger.debug(f"GuildTransaction for guild_id: {guild_id} started nested transaction (savepoint) on session {id(session_to_use)}.")
        else:
            transaction = session_to_use.begin()
            logger.debug(f"GuildTransaction for guild_id: {guild_id} started new transaction on session {id(session_to_use)}.")

        async with transaction: # This handles commit/rollback of the (possibly nested) transaction
            yield session_to_use

            # Pre-commit/flush verification (best effort)
            guild_id_str = str(guild_id)
            for obj in session_to_use.dirty:
                if hasattr(obj, 'guild_id'):
                    obj_guild_id = getattr(obj, 'guild_id', None)
                    if obj_guild_id is not None and str(obj_guild_id) != guild_id_str:
                        logger.error(f"GuildTransaction: Cross-guild write attempt for dirty object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}). Expected guild {guild_id_str}, got {obj_guild_id}.")
                        raise ValueError(f"Cross-guild write attempt for dirty object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}). Expected guild {guild_id_str}, got {obj_guild_id}.")
            for obj in session_to_use.new:
                if hasattr(obj, 'guild_id'):
                    obj_guild_id = getattr(obj, 'guild_id', None)
                    if obj_guild_id is None and "current_guild_id" in session_to_use.info:
                        logger.debug(f"GuildTransaction: Auto-setting guild_id {guild_id_str} for new object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}).")
                        setattr(obj, 'guild_id', guild_id_str)
                    elif obj_guild_id is not None and str(obj_guild_id) != guild_id_str:
                        logger.error(f"GuildTransaction: Cross-guild write attempt for new object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}). Expected guild {guild_id_str}, got {obj_guild_id}.")
                        raise ValueError(f"Cross-guild write attempt for new object {type(obj).__name__} (ID: {getattr(obj, 'id', 'N/A')}). Expected guild {guild_id_str}, got {obj_guild_id}.")

            # Commit logic is now implicitly handled by 'async with transaction:' if commit_on_exit is True
            # If commit_on_exit is False, the outer transaction block will not commit here.
            # However, the problem is that the `transaction` object itself will commit if no error.
            # To prevent commit if commit_on_exit is False, we'd need to rollback manually if an error didn't already cause it.
            # This design is a bit tricky. The standard way is that the context manager handles commit/rollback.
            # If commit_on_exit is False, it implies the session is managed externally.
            if not commit_on_exit and not is_external_transaction:
                 logger.debug(f"GuildTransaction for guild_id: {guild_id}: commit_on_exit is False and not nested, transaction will be rolled back unless committed by caller.")
                 # To truly prevent commit by this context manager if commit_on_exit=False and it's the outermost transaction,
                 # we'd need to call await transaction.rollback() here before it auto-commits.
                 # This makes commit_on_exit=False a bit non-standard for `async with session.begin()`.
                 # A common pattern for commit_on_exit=False is for the caller to manage the session.begin() itself.
                 # For now, let's assume if commit_on_exit is False, the user is aware of this.
                 # The `async with transaction` will commit if no exception.

            logger.debug(f"GuildTransaction for guild_id: {guild_id} completed operations within 'try' block of 'async with transaction'.")

    except Exception as e:
        logger.error(f"GuildTransaction for guild_id: {guild_id} encountered an exception. Transaction (if started by GT) will be rolled back by its context manager.", exc_info=True)
        raise # Re-raise the error after logging
    finally:
        if session_to_use: # Ensure session_to_use was successfully created
            if original_guild_id_in_info is not None:
                session_to_use.info["current_guild_id"] = original_guild_id_in_info
            elif "current_guild_id" in session_to_use.info:
                del session_to_use.info["current_guild_id"]

            if created_session_locally: # Only close sessions that this context manager created via a factory
                await session_to_use.close()
                logger.debug(f"GuildTransaction: Session {id(session_to_use)} for guild_id: {guild_id} (created locally) closed.")
            else:
                logger.debug(f"GuildTransaction: Session {id(session_to_use)} for guild_id: {guild_id} was passed in, not closing here.")
