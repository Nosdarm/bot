# bot/utils/config_utils.py
import logging
from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import update, insert # Added insert for update_or_create logic
from sqlalchemy.dialects.postgresql import insert as pg_insert # For upsert

from bot.database.models import RulesConfig

logger = logging.getLogger(__name__)

async def load_rules_config(db_session: AsyncSession, guild_id: str) -> Dict[str, Any]:
    """
    Fetches all RulesConfig entries for the given guild_id from the database.
    Returns a dictionary of {key: value}.
    """
    logger.debug(f"Loading rules configuration for guild_id: {guild_id}")
    stmt = select(RulesConfig.key, RulesConfig.value).where(RulesConfig.guild_id == guild_id)
    try:
        result = await db_session.execute(stmt)
        rules_dict = {row.key: row.value for row in result.all()}
        logger.info(f"Successfully loaded {len(rules_dict)} rules for guild {guild_id}.")
        return rules_dict
    except Exception as e:
        logger.error(f"Error loading rules config for guild {guild_id}: {e}", exc_info=True)
        return {}

async def get_rule(db_session: AsyncSession, guild_id: str, key: str, rule_cache: Optional[Dict[str, Any]] = None) -> Any:
    """
    Fetches a specific RulesConfig entry for guild_id and key.
    If rule_cache is provided and contains the key, return from cache.
    Otherwise, fetch from the database.
    """
    if rule_cache and key in rule_cache:
        logger.debug(f"Retrieved rule '{key}' for guild {guild_id} from cache.")
        return rule_cache[key]

    logger.debug(f"Fetching rule '{key}' for guild {guild_id} from database.")
    stmt = select(RulesConfig.value).where(RulesConfig.guild_id == guild_id, RulesConfig.key == key)
    try:
        result = await db_session.execute(stmt)
        rule_value_row = result.scalars().first()
        if rule_value_row is not None:
            logger.info(f"Successfully fetched rule '{key}' for guild {guild_id} from DB.")
            return rule_value_row
        else:
            logger.warning(f"Rule '{key}' not found for guild {guild_id} in DB.")
            return None # Or raise a custom NotFound error
    except Exception as e:
        logger.error(f"Error fetching rule '{key}' for guild {guild_id}: {e}", exc_info=True)
        return None # Or raise

async def update_rule_config(db_session: AsyncSession, guild_id: str, key: str, value: Any) -> None:
    """
    Updates or creates the RulesConfig entry for the given guild_id and key with the new value.
    This implements an "upsert" functionality.
    """
    logger.info(f"Updating rule '{key}' for guild {guild_id} with value: {str(value)[:100]}") # Log truncated value

    # Using PostgreSQL's ON CONFLICT DO UPDATE (upsert)
    # This requires the table `rules_config` to have a unique constraint on `(guild_id, key)`.
    # The model definition includes `UniqueConstraint('guild_id', 'key', name='uq_guild_rule_key')`.

    # The `id` column is a UUID default, so we don't specify it for insert.
    # If the row (based on guild_id, key) exists, its 'value' is updated.
    # If it does not exist, a new row is inserted.

    stmt = pg_insert(RulesConfig).values(
        guild_id=guild_id,
        key=key,
        value=value
    )

    # Define the conflict target (the columns that define uniqueness)
    # and the update action if there's a conflict.
    # The `excluded` object refers to the values that would have been inserted.
    stmt = stmt.on_conflict_do_update(
        index_elements=['guild_id', 'key'], # Columns forming the unique constraint
        set_={'value': stmt.excluded.value}
    )

    try:
        await db_session.execute(stmt)
        await db_session.commit() # Commit the transaction
        logger.info(f"Successfully upserted rule '{key}' for guild {guild_id}.")
    except Exception as e:
        await db_session.rollback() # Rollback on error
        logger.error(f"Error upserting rule '{key}' for guild {guild_id}: {e}", exc_info=True)
        # Potentially re-raise or handle as needed
        raise # Re-raise to make the caller aware of the failure

# Example usage (for testing, not part of the module's public API directly)
async def _example_usage(db_session: AsyncSession, test_guild_id: str):
    logger.info("--- Running config_utils example usage ---")

    # Test update_rule_config (upsert)
    await update_rule_config(db_session, test_guild_id, "test_rate", 2.5)
    await update_rule_config(db_session, test_guild_id, "test_feature_enabled", True)

    # Test get_rule (without cache)
    rate = await get_rule(db_session, test_guild_id, "test_rate")
    logger.info(f"Fetched 'test_rate': {rate}")

    feature_enabled = await get_rule(db_session, test_guild_id, "test_feature_enabled")
    logger.info(f"Fetched 'test_feature_enabled': {feature_enabled}")

    non_existent_rule = await get_rule(db_session, test_guild_id, "non_existent_key")
    logger.info(f"Fetched 'non_existent_key': {non_existent_rule}")

    # Test load_rules_config
    all_rules = await load_rules_config(db_session, test_guild_id)
    logger.info(f"All rules for guild {test_guild_id}: {all_rules}")

    # Test get_rule (with cache)
    cached_rate = await get_rule(db_session, test_guild_id, "test_rate", rule_cache=all_rules)
    logger.info(f"Fetched 'test_rate' from cache: {cached_rate}")

    # Test update_rule_config (update existing)
    await update_rule_config(db_session, test_guild_id, "test_rate", 3.0)
    updated_rate = await get_rule(db_session, test_guild_id, "test_rate") # Fetch from DB to confirm
    logger.info(f"Updated 'test_rate': {updated_rate}")

    all_rules_after_update = await load_rules_config(db_session, test_guild_id)
    logger.info(f"All rules for guild {test_guild_id} after update: {all_rules_after_update}")

    logger.info("--- Finished config_utils example usage ---")

if __name__ == '__main__':
    # This is a placeholder for how one might test these utility functions.
    # It requires an async environment and a configured database session.

    # Configure logging for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    async def run_tests():
        from sqlalchemy.ext.asyncio import create_async_engine
        from bot.database.models import Base # Ensure Base is imported for metadata

        # Use an in-memory SQLite for testing if PostgreSQL is not available for this specific test run
        # NOTE: pg_insert specific features (on_conflict_do_update) will NOT work with SQLite.
        # For `update_rule_config` to work as intended, a PostgreSQL DB is required.
        # If running this __main__ block for testing, ensure DATABASE_URL points to a test PG database.
        # DATABASE_URL = "sqlite+aiosqlite:///./test_config_utils.db" # Won't work for upsert
        DATABASE_URL = "postgresql+asyncpg://user:password@host:port/test_db" # Replace with your test PG

        # A more robust way to get DB URL, e.g., from env var
        import os
        db_url_from_env = os.getenv("TEST_DATABASE_URL")
        if not db_url_from_env:
            print("Please set TEST_DATABASE_URL environment variable for testing config_utils with PostgreSQL.")
            print("Example: export TEST_DATABASE_URL=postgresql+asyncpg://user:password@host:port/test_db")
            return

        engine = create_async_engine(db_url_from_env, echo=False)

        async with engine.begin() as conn:
            # For testing, you might want to drop and recreate tables
            # await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        session_factory = lambda: AsyncSession(bind=engine, expire_on_commit=False)
        test_guild = f"test_guild_config_utils_{os.urandom(4).hex()}"

        async with session_factory() as session:
            try:
                await _example_usage(session, test_guild)
            except Exception as e:
                logger.error(f"Error during example usage: {e}", exc_info=True)
            finally:
                # Clean up test data (optional, depends on test DB setup)
                # from sqlalchemy import delete
                # await session.execute(delete(RulesConfig).where(RulesConfig.guild_id == test_guild))
                # await session.commit()
                pass

        await engine.dispose()

    # import asyncio
    # asyncio.run(run_tests()) # Commented out to prevent auto-run
    pass
