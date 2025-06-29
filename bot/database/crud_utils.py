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

ModelType = TypeVar("ModelType", bound=Any)
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
    guild_id: Optional[str] = None  # Made optional
) -> ModelType:
    """
    Creates a new entity with guild_id awareness.
    Uses session.info["current_guild_id"] if available and guild_id param/data is not set.
    Verifies guild_id consistency if multiple sources provide it.
    """
    session_guild_id = db_session.info.get("current_guild_id")
    final_guild_id: Optional[str] = None

    if guild_id is not None: # Explicit parameter takes precedence
        final_guild_id = str(guild_id)
        if session_guild_id and final_guild_id != str(session_guild_id):
            logger.error(f"Explicit guild_id '{final_guild_id}' conflicts with session's current_guild_id '{session_guild_id}' for {model_class.__name__}.")
            raise ValueError("Explicit guild_id conflicts with session's current_guild_id.")
    elif 'guild_id' in data: # guild_id from data
        final_guild_id = str(data['guild_id'])
        if session_guild_id and final_guild_id != str(session_guild_id):
            logger.error(f"Data guild_id '{final_guild_id}' conflicts with session's current_guild_id '{session_guild_id}' for {model_class.__name__}.")
            raise ValueError("Data guild_id conflicts with session's current_guild_id.")
    elif session_guild_id: # guild_id from session.info
        final_guild_id = str(session_guild_id)
        logger.debug(f"Using guild_id '{final_guild_id}' from session.info for new {model_class.__name__}.")

    if final_guild_id is None and hasattr(model_class, 'guild_id'):
        logger.error(f"guild_id not provided and not found in session.info for guild-aware model {model_class.__name__}.")
        raise ValueError(f"guild_id must be provided for guild-aware model {model_class.__name__}.")

    if hasattr(model_class, 'guild_id'):
        data['guild_id'] = final_guild_id # Set or overwrite data['guild_id'] with the verified one

    logger.debug(f"Creating entity for model {model_class.__name__} in guild {final_guild_id or 'N/A'} with data: {data}")

    try:
        entity = model_class(**data)
        db_session.add(entity)
        await db_session.flush()  # Flush to get auto-generated IDs, if any, and to check constraints early
        await db_session.refresh(entity)
        logger.info(f"Successfully created entity (ID: {getattr(entity, 'id', 'N/A')}) of type {model_class.__name__} for guild {final_guild_id or 'N/A'}.")
        return entity
    except IntegrityError as e:
        logger.error(f"Integrity error creating entity of type {model_class.__name__} for guild {final_guild_id or 'N/A'}: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating entity of type {model_class.__name__} for guild {final_guild_id or 'N/A'}: {e}", exc_info=True)
        raise


async def get_entity_by_id(
    db_session: AsyncSession,
    model_class: Type[ModelType],
    entity_id: Any,
    guild_id: str,
    id_field_name: str = 'id'
) -> Optional[ModelType]:
    """
    Fetches a single entity by its primary key and guild_id.
    Verifies guild_id against session.info["current_guild_id"] if present.
    """
    logger.debug(f"Fetching {model_class.__name__} by {id_field_name}: {entity_id} for guild {guild_id}")

    session_guild_id = db_session.info.get("current_guild_id")
    if session_guild_id and str(guild_id) != str(session_guild_id):
        logger.error(f"Requested guild_id '{guild_id}' conflicts with session's current_guild_id '{session_guild_id}' for {model_class.__name__} ID {entity_id}.")
        raise ValueError("Requested guild_id conflicts with session's current_guild_id.")

    if not hasattr(model_class, id_field_name):
        logger.error(f"Model {model_class.__name__} does not have an ID field named '{id_field_name}'.")
        return None

    stmt = select(model_class).where(getattr(model_class, id_field_name) == entity_id)
    if hasattr(model_class, 'guild_id'):
        stmt = stmt.where(model_class.guild_id == guild_id) # type: ignore

    try:
        result = await db_session.execute(stmt)
        entity = result.scalars().first()
        if entity:
            logger.debug(f"Found {model_class.__name__} with {id_field_name} {entity_id} for guild {guild_id if hasattr(model_class, 'guild_id') else 'N/A'}.")
        else:
            logger.debug(f"{model_class.__name__} with {id_field_name} {entity_id} not found for guild {guild_id if hasattr(model_class, 'guild_id') else 'N/A'}.")
        return entity
    except Exception as e:
        logger.error(f"Error fetching {model_class.__name__} by {id_field_name} {entity_id} for guild {guild_id if hasattr(model_class, 'guild_id') else 'N/A'}: {e}", exc_info=True)
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
    Verifies guild_id against session.info["current_guild_id"] if present.
    """
    logger.debug(f"Fetching entities of type {model_class.__name__} for guild {guild_id} with conditions: {conditions}")

    session_guild_id = db_session.info.get("current_guild_id")
    if session_guild_id and str(guild_id) != str(session_guild_id):
        logger.error(f"Requested guild_id '{guild_id}' conflicts with session's current_guild_id '{session_guild_id}' for {model_class.__name__} listing.")
        raise ValueError("Requested guild_id conflicts with session's current_guild_id.")

    stmt = select(model_class)
    if hasattr(model_class, 'guild_id'):
        stmt = stmt.where(model_class.guild_id == guild_id) # type: ignore

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
        logger.debug(f"Found {len(entities)} entities of type {model_class.__name__} for guild {guild_id if hasattr(model_class, 'guild_id') else 'N/A'}.")
        return list(entities)
    except Exception as e:
        logger.error(f"Error fetching entities of type {model_class.__name__} for guild {guild_id if hasattr(model_class, 'guild_id') else 'N/A'}: {e}", exc_info=True)
        return []


async def update_entity(
    db_session: AsyncSession,
    entity_instance: ModelType,
    data: Dict[str, Any],
    guild_id: str # For verification against entity's actual guild_id
) -> ModelType:
    """
    Updates an existing entity instance. Verifies against entity's guild_id and session.info.
    """
    entity_actual_guild_id = str(getattr(entity_instance, 'guild_id', None)) if hasattr(entity_instance, 'guild_id') else None

    if entity_actual_guild_id is None and hasattr(entity_instance, 'guild_id'):
        logger.error(f"Entity {type(entity_instance).__name__} ID {getattr(entity_instance, 'id', 'N/A')} has None for guild_id. Update aborted.")
        raise ValueError("Entity to be updated has a None guild_id.")

    if entity_actual_guild_id and entity_actual_guild_id != str(guild_id):
        logger.error(f"Attempt to update entity for guild {entity_actual_guild_id} with conflicting verification guild_id parameter {guild_id}.")
        raise ValueError(f"Verification guild_id mismatch: Entity belongs to {entity_actual_guild_id}, operation specified for {guild_id}.")

    session_guild_id = db_session.info.get("current_guild_id")
    if session_guild_id and entity_actual_guild_id and str(entity_actual_guild_id) != str(session_guild_id):
        logger.error(f"Entity's guild_id '{entity_actual_guild_id}' conflicts with session's current_guild_id '{session_guild_id}'.")
        raise ValueError("Entity's guild_id conflicts with session's current_guild_id.")

    # If model is not guild-aware, session_guild_id check is not strictly necessary unless we enforce all ops are guild-scoped
    if not hasattr(entity_instance, 'guild_id') and session_guild_id:
        logger.warning(f"Updating non-guild-aware entity {type(entity_instance).__name__} within guild-scoped transaction {session_guild_id}.")


    logger.debug(f"Updating entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__} in guild {entity_actual_guild_id or 'N/A'} with data: {data}")
    try:
        for key, value in data.items():
            if hasattr(entity_instance, 'guild_id') and key == 'guild_id' and str(value) != entity_actual_guild_id:
                logger.warning(f"Attempt to change 'guild_id' during update of {type(entity_instance).__name__} was ignored. Current: {entity_actual_guild_id}, Attempted: {value}")
                continue
            setattr(entity_instance, key, value)

        db_session.add(entity_instance)
        await db_session.flush()
        await db_session.refresh(entity_instance)
        logger.info(f"Successfully updated entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__} for guild {entity_actual_guild_id or 'N/A'}.")
        return entity_instance
    except IntegrityError as e:
        logger.error(f"Integrity error updating entity of type {type(entity_instance).__name__}: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating entity of type {type(entity_instance).__name__}: {e}", exc_info=True)
        raise


async def delete_entity(
    db_session: AsyncSession,
    entity_instance: ModelType,
    guild_id: str # For verification against entity's actual guild_id
) -> bool:
    """
    Deletes an existing entity instance. Verifies against entity's guild_id and session.info.
    """
    entity_actual_guild_id = str(getattr(entity_instance, 'guild_id', None)) if hasattr(entity_instance, 'guild_id') else None

    if entity_actual_guild_id is None and hasattr(entity_instance, 'guild_id'):
        logger.error(f"Entity {type(entity_instance).__name__} ID {getattr(entity_instance, 'id', 'N/A')} has None for guild_id. Delete aborted.")
        raise ValueError("Entity to be deleted has a None guild_id.")

    if entity_actual_guild_id and entity_actual_guild_id != str(guild_id):
        logger.error(f"Attempt to delete entity for guild {entity_actual_guild_id} with conflicting verification guild_id {guild_id}.")
        raise ValueError(f"Verification guild_id mismatch for delete: Entity is in {entity_actual_guild_id}, operation for {guild_id}.")

    session_guild_id = db_session.info.get("current_guild_id")
    if session_guild_id and entity_actual_guild_id and str(entity_actual_guild_id) != str(session_guild_id):
        logger.error(f"Entity's guild_id '{entity_actual_guild_id}' for delete conflicts with session's current_guild_id '{session_guild_id}'.")
        raise ValueError("Entity's guild_id for delete conflicts with session's current_guild_id.")

    if not hasattr(entity_instance, 'guild_id') and session_guild_id:
        logger.warning(f"Deleting non-guild-aware entity {type(entity_instance).__name__} within guild-scoped transaction {session_guild_id}.")

    logger.debug(f"Deleting entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__} from guild {entity_actual_guild_id or 'N/A'}")
    try:
        await db_session.delete(entity_instance)
        await db_session.flush()
        logger.info(f"Successfully deleted entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__} from guild {entity_actual_guild_id or 'N/A'}.")
        return True
    except Exception as e:
        logger.error(f"Error deleting entity (ID: {getattr(entity_instance, 'id', 'N/A')}) of type {type(entity_instance).__name__}: {e}", exc_info=True)
        raise


async def get_entity_by_attributes(
    db_session: AsyncSession,
    model_class: Type[ModelType],
    attributes: Dict[str, Any],
    guild_id: str # Mandatory for query construction for guild-aware models
) -> Optional[ModelType]:
    """
    Fetches a single entity based on a dictionary of attributes and guild_id.
    Verifies guild_id against session.info["current_guild_id"] if present.
    """
    logger.debug(f"Fetching {model_class.__name__} by attributes {attributes} for guild {guild_id}")

    session_guild_id = db_session.info.get("current_guild_id")
    if session_guild_id and str(guild_id) != str(session_guild_id):
        logger.error(f"Requested guild_id '{guild_id}' conflicts with session's current_guild_id '{session_guild_id}' for {model_class.__name__} attribute search.")
        raise ValueError("Requested guild_id conflicts with session's current_guild_id for attribute search.")

    stmt = select(model_class)
    for key, value in attributes.items():
        stmt = stmt.where(getattr(model_class, key) == value)

    if hasattr(model_class, 'guild_id'):
        stmt = stmt.where(model_class.guild_id == guild_id) # type: ignore

    try:
        result = await db_session.execute(stmt)
        entity = result.scalars().first()
        if entity:
            logger.debug(f"Found {model_class.__name__} with attributes {attributes} for guild {guild_id if hasattr(model_class, 'guild_id') else 'N/A'}.")
        else:
            logger.debug(f"{model_class.__name__} with attributes {attributes} not found for guild {guild_id if hasattr(model_class, 'guild_id') else 'N/A'}.")
        return entity
    except Exception as e:
        logger.error(f"Error fetching {model_class.__name__} by attributes for guild {guild_id if hasattr(model_class, 'guild_id') else 'N/A'}: {e}", exc_info=True)
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
