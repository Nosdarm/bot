from __future__ import annotations

# bot/database/crud_utils.py
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar, Callable, Coroutine
from functools import wraps

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import InstrumentedAttribute # For getattr with model columns

from bot.database.models import Base # Assuming your Base is accessible here
# It's often better if the DBService or a session factory is passed around or accessed via bot context
# For now, assuming these utils might be used in places where a session is already available.
# from bot.services.db_service import DBService # If needed for session factory

logger = logging.getLogger(__name__)

# Base is imported from bot.database.models and is expected to be a
# type (class) resulting from SQLAlchemy's declarative_base().
# If a type checker (like Pylance) reports an error such as
# "Variable not allowed in type expression" for `Base` on the next line,
# it may indicate an issue with the type checker's import resolution,
# environment configuration, or a specific linter bug. The usage of
# `Base` as a bound here is standard and should be valid.
ModelType = TypeVar("ModelType", bound="Base")
AsyncCallable = Callable[..., Coroutine[Any, Any, Any]]
F = TypeVar('F', bound=Callable[..., Coroutine[Any, Any, Any]])

# Transactional Decorator
def transactional_session(session_param_name: str = 'db_session'):
    """
    Decorator to provide a transactional scope around a service method.
    It assumes the decorated function will receive an AsyncSession named as specified
    by `session_param_name`. The decorator itself does not create the session,
    but manages the transaction block (begin, commit, rollback).
    This version expects the session to be passed into the decorated function.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            db_session: Optional[AsyncSession] = kwargs.get(session_param_name)
            if db_session is None:
                try:
                    if args and len(args) > 1 and isinstance(args[1], AsyncSession):
                        db_session = args[1]
                    elif args and isinstance(args[0], AsyncSession):
                        db_session = args[0]
                    else:
                        raise ValueError(f"AsyncSession parameter '{session_param_name}' not found in arguments for {func.__name__}")
                except (IndexError, ValueError) as e:
                    logger.error(f"Error in transactional_session decorator for {func.__name__}: {e}")
                    raise

            if not db_session.in_transaction():
                async with db_session.begin():
                    result = await func(*args, **kwargs)
                    return result
            else:
                return await func(*args, **kwargs)
        return wrapper
    return decorator

# Guild-Aware CRUD Utility Functions

async def create_entity(
    db_session: AsyncSession,
    model_class: Type[ModelType],
    data: Dict[str, Any],
    guild_id: str
) -> Optional[ModelType]:
    """
    Creates a new entity with guild_id awareness.
    `guild_id` is automatically added to `data` if not present.
    """
    logger.debug(f"Creating entity for model {model_class.__name__} in guild {guild_id} with data: {data}")

    # Ensure guild_id is part of the data for creation
    if 'guild_id' not in data and hasattr(model_class, 'guild_id'):
        data['guild_id'] = guild_id
    elif hasattr(model_class, 'guild_id') and str(data.get('guild_id')) != str(guild_id):
        logger.error(f"Data guild_id {data.get('guild_id')} does not match provided guild_id {guild_id} for {model_class.__name__}.")
        raise ValueError("guild_id in data conflicts with the guild_id parameter.")

    try:
        entity = model_class(**data)
        db_session.add(entity)
        await db_session.flush()  # Flush to get auto-generated IDs, if any, and to check constraints early
        # Commit is expected to be handled by the transactional decorator or the calling context
        logger.info(f"Successfully created entity (ID: {getattr(entity, 'id', 'N/A')}) of type {model_class.__name__} for guild {guild_id}.")
        return entity
    except IntegrityError as e:
        # logger.error(f"Integrity error creating entity of type {model_class.__name__} for guild {guild_id}: {e}", exc_info=True)
        # Rollback should be handled by the transactional decorator / context
        raise # Re-raise for the transactional layer to handle rollback
    except Exception as e:
        logger.error(f"Unexpected error creating entity of type {model_class.__name__} for guild {guild_id}: {e}", exc_info=True)
        raise # Re-raise


async def get_entity_by_id(
    db_session: AsyncSession,
    model_class: Type[ModelType],
    entity_id: Any,
    guild_id: str,
    id_field_name: str = 'id'
) -> Optional[ModelType]:
    """
    Fetches a single entity by its primary key and guild_id.
    """
    logger.debug(f"Fetching {model_class.__name__} by {id_field_name}: {entity_id} for guild {guild_id}")

    if not hasattr(model_class, id_field_name):
        logger.error(f"Model {model_class.__name__} does not have an ID field named '{id_field_name}'.")
        return None
    if not hasattr(model_class, 'guild_id'):
        logger.error(f"Model {model_class.__name__} is not guild-aware (missing 'guild_id' attribute). Cannot perform guild-scoped get.")
        # Or, if some models are intentionally not guild_aware but accessed via this generic util,
        # then guild_id check could be optional. For now, assume guild-awareness.
        return None

    stmt = select(model_class).where(
        getattr(model_class, id_field_name) == entity_id,
        model_class.guild_id == guild_id # type: ignore
    )
    try:
        result = await db_session.execute(stmt)
        entity = result.scalars().first()
        if entity:
            logger.debug(f"Found {model_class.__name__} with {id_field_name} {entity_id} for guild {guild_id}.")
        else:
            logger.debug(f"{model_class.__name__} with {id_field_name} {entity_id} not found for guild {guild_id}.")
        return entity
    except Exception as e:
        logger.error(f"Error fetching {model_class.__name__} by {id_field_name} {entity_id} for guild {guild_id}: {e}", exc_info=True)
        return None


async def get_entities(
    db_session: AsyncSession,
    model_class: Type[ModelType],
    guild_id: str,
    conditions: Optional[List[Any]] = None, # List of SQLAlchemy filter expressions
    order_by: Optional[List[Any]] = None,   # List of SQLAlchemy order_by expressions
    limit: Optional[int] = None,
    offset: Optional[int] = None
) -> List[ModelType]:
    """
    Fetches multiple entities for a given guild_id, with optional filters, ordering, and pagination.
    """
    logger.debug(f"Fetching entities of type {model_class.__name__} for guild {guild_id} with conditions: {conditions}")

    if not hasattr(model_class, 'guild_id'):
        logger.error(f"Model {model_class.__name__} is not guild-aware. Cannot perform guild-scoped get_entities.")
        return []

    stmt = select(model_class).where(model_class.guild_id == guild_id) # type: ignore

    if conditions:
        for condition in conditions:
            stmt = stmt.where(condition)

    if order_by:
        for ob_clause in order_by:
            stmt = stmt.order_by(ob_clause)

    if limit is not None:
        stmt = stmt.limit(limit)

    if offset is not None:
        stmt = stmt.offset(offset)

    try:
        result = await db_session.execute(stmt)
        entities = result.scalars().all()
        logger.debug(f"Found {len(entities)} entities of type {model_class.__name__} for guild {guild_id}.")
        return list(entities)
    except Exception as e:
        logger.error(f"Error fetching entities of type {model_class.__name__} for guild {guild_id}: {e}", exc_info=True)
        return []


async def update_entity(
    db_session: AsyncSession,
    entity_instance: ModelType,
    data: Dict[str, Any],
    guild_id: str # For verification
) -> Optional[ModelType]:
    """
    Updates an existing entity instance with guild_id verification.
    """
    if not hasattr(entity_instance, 'guild_id'):
        logger.error(f"Entity of type {type(entity_instance).__name__} is not guild-aware. Update aborted.")
        # Consider raising an error or returning None based on desired strictness
        return None

    if str(getattr(entity_instance, 'guild_id')) != str(guild_id):
        logger.error(
            f"Attempt to update entity for guild {getattr(entity_instance, 'guild_id')} "
            f"with conflicting guild_id parameter {guild_id}. Update aborted for entity ID {getattr(entity_instance, 'id', 'N/A')}."
        )
        # This is a critical error, should probably raise an exception
        raise ValueError(f"Guild ID mismatch: Entity belongs to guild {getattr(entity_instance, 'guild_id')}, operation specified for guild {guild_id}.")

    logger.debug(f"Updating entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__} in guild {guild_id} with data: {data}")
    try:
        for key, value in data.items():
            if key == 'guild_id' and str(value) != str(guild_id): # Prevent changing guild_id via update data
                logger.warning(f"Attempt to change 'guild_id' during update of {type(entity_instance).__name__} was ignored.")
                continue
            setattr(entity_instance, key, value)

        db_session.add(entity_instance) # Add to session, it's now dirty
        await db_session.flush() # Flush to check constraints early
        # Commit is expected to be handled by the transactional decorator or the calling context
        logger.info(f"Successfully updated entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__} for guild {guild_id}.")
        return entity_instance
    except IntegrityError as e:
        # logger.error(f"Integrity error updating entity of type {type(entity_instance).__name__}: {e}", exc_info=True)
        raise # Re-raise for the transactional layer to handle rollback
    except Exception as e:
        logger.error(f"Unexpected error updating entity of type {type(entity_instance).__name__}: {e}", exc_info=True)
        raise # Re-raise


async def delete_entity(
    db_session: AsyncSession,
    entity_instance: ModelType,
    guild_id: str # For verification
) -> bool:
    """
    Deletes an existing entity instance with guild_id verification.
    """
    if not hasattr(entity_instance, 'guild_id'):
        logger.error(f"Entity of type {type(entity_instance).__name__} is not guild-aware. Delete aborted.")
        return False

    if str(getattr(entity_instance, 'guild_id')) != str(guild_id):
        logger.error(
            f"Attempt to delete entity for guild {getattr(entity_instance, 'guild_id')} "
            f"with conflicting guild_id parameter {guild_id}. Delete aborted for entity ID {getattr(entity_instance, 'id', 'N/A')}."
        )
        raise ValueError(f"Guild ID mismatch: Entity belongs to guild {getattr(entity_instance, 'guild_id')}, delete operation specified for guild {guild_id}.")

    logger.debug(f"Deleting entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__} from guild {guild_id}")
    try:
        await db_session.delete(entity_instance)
        await db_session.flush() # To ensure delete operation is processed by SQLAlchemy
        # Commit is expected to be handled by the transactional decorator or the calling context
        logger.info(f"Successfully deleted entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__} from guild {guild_id}.")
        return True
    except Exception as e:
        logger.error(f"Error deleting entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__}: {e}", exc_info=True)
        # Rollback should be handled by the transactional decorator / context
        raise # Re-raise


async def get_entity_by_attributes(
    db_session: AsyncSession,
    model_class: Type[ModelType],
    attributes: Dict[str, Any],
    guild_id: str
) -> Optional[ModelType]:
    """
    Fetches a single entity based on a dictionary of attributes and guild_id.
    """
    logger.debug(f"Fetching {model_class.__name__} by attributes {attributes} for guild {guild_id}")

    if not hasattr(model_class, 'guild_id'):
        logger.error(f"Model {model_class.__name__} is not guild-aware. Cannot perform guild-scoped get_entity_by_attributes.")
        return None

    conditions = [(getattr(model_class, k) == v) for k, v in attributes.items()]
    conditions.append(model_class.guild_id == guild_id) # type: ignore

    stmt = select(model_class).where(*conditions)

    try:
        result = await db_session.execute(stmt)
        entity = result.scalars().first()
        if entity:
            logger.debug(f"Found {model_class.__name__} with attributes {attributes} for guild {guild_id}.")
        else:
            logger.debug(f"{model_class.__name__} with attributes {attributes} not found for guild {guild_id}.")
        return entity
    except Exception as e:
        logger.error(f"Error fetching {model_class.__name__} by attributes for guild {guild_id}: {e}", exc_info=True)
        return None

# Example of an async context manager for transactions (alternative to decorator)
from contextlib import asynccontextmanager

@asynccontextmanager
async def guild_transaction_scope(session_factory: Any, guild_id: str): # session_factory e.g. from DBService
    """
    Provides a transactional scope for operations within a specific guild.
    This creates and manages the session.
    """
    # This assumes session_factory is something like DBService().get_session_factory()
    # or a direct async_sessionmaker instance.
    # Example: session: AsyncSession = session_factory()
    # For now, this is conceptual. The decorator pattern is often easier to apply to existing functions.
    # A concrete implementation would depend on how DBService or session provision is structured.

    # This is a simplified example. A real implementation needs robust session provision.
    # Let's assume session_factory() returns a new session:
    # async with session_factory() as session:
    #     async with session.begin():
    #         try:
    #             # The yielded value could be the session, or a context object
    #             # containing the session and guild_id.
    #             yield session # Or a custom context object
    #             await session.commit() # This commit might be redundant if session.begin() auto-commits on exit without error
    #         except Exception:
    #             await session.rollback()
    #             raise
    # This is highly dependent on the DBService structure, so I'll leave it as a conceptual placeholder.
    # The decorator is more immediately usable with existing function signatures that accept a session.
    pass

logger.info("Guild-aware CRUD utilities and transactional decorator defined in crud_utils.py")

# To make the transactional_session decorator more robust in finding the session:
# One could inspect function signature using `inspect` module to find the param annotated with AsyncSession.
# Or enforce that the session parameter must always be named 'db_session' or passed as a kwarg.
# The current implementation is a basic attempt.
