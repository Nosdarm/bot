import asyncio
from bot.services.db_service import DBService
import os
import traceback

# Set PGPASSWORD environment variable for the DB connection
# This is needed because PostgresAdapter might try to connect
# and the connection string is in the code, using credentials.
# Note: For security, PGPASSWORD is not the best way for production,
# but can be acceptable for controlled test environments.
# Ensure this is not logged if the script output is captured.
os.environ['PGPASSWORD'] = 'test123'

async def main():
    print('Starting DBService test...')
    # SQLALCHEMY_DATABASE_URL in postgres_adapter.py is:
    # "postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot"
    db_service = None # Initialize to None for finally block
    try:
        db_service = DBService() # Instantiation happens here
        print('DBService instantiated.')

        print('Attempting DBService.initialize_database()...')
        # This method in PostgresAdapter ensures the pool and SQLAlchemy session can be created.
        await db_service.initialize_database()
        print('DBService.initialize_database() successful.')

        # db_service.connect() is implicitly called by initialize_database if session/pool not up.
        # Let's explicitly call connect() again to ensure it handles existing sessions/pools gracefully.
        print('Attempting DBService.connect() again explicitly...')
        await db_service.connect()
        print('DBService.connect() (explicit call) successful.')

        if db_service.adapter and hasattr(db_service.adapter, '_conn_pool') and db_service.adapter._conn_pool: # type: ignore[protected-access]
            print(f"Asyncpg connection pool status: {db_service.adapter._conn_pool}") # type: ignore[protected-access]
            # Try a very simple query using raw asyncpg connection to test the pool
            try:
                conn = await db_service.adapter._get_raw_connection() # type: ignore[protected-access]
                db_version = await conn.fetchval("SELECT version();")
                print(f"PostgreSQL version fetched via raw connection: {db_version[:30]}...") # Print first 30 chars
                if hasattr(db_service.adapter, '_conn_pool') and db_service.adapter._conn_pool and conn: # type: ignore[protected-access]
                     await db_service.adapter._conn_pool.release(conn) # type: ignore[protected-access]
                print("Raw asyncpg connection test successful.")
            except Exception as raw_e:
                print(f"Error during raw asyncpg connection test: {raw_e}")
                traceback.print_exc()
        else:
            print("Asyncpg connection pool not initialized after connect(). This is unexpected.")

        if hasattr(db_service, 'db') and db_service.db is not None: # type: ignore[attr-defined]
            print(f"SQLAlchemy async session status: {db_service.db}") # type: ignore[attr-defined]
            # Try a simple query with SQLAlchemy session
            try:
                from sqlalchemy import text
                async with db_service.db.begin(): # type: ignore[attr-defined] # Start a transaction
                    result = await db_service.db.execute(text("SELECT 1")) # type: ignore[attr-defined]
                    print(f"SQLAlchemy session test query (SELECT 1) result: {result.scalar_one_or_none()}")
                print("SQLAlchemy session test successful.")
            except Exception as sa_e:
                print(f"Error during SQLAlchemy session test: {sa_e}")
                traceback.print_exc()
        else:
            print("SQLAlchemy async session not initialized after connect(). This is unexpected.")

        print('DBService connection lifecycle test completed (before close).')

    except Exception as e:
        print(f'Error during DBService setup or initial connection tests: {e}')
        traceback.print_exc()
    finally:
        if db_service and db_service.adapter: # Check if db_service and adapter were initialized
            print('Attempting DBService.close() in finally block...')
            try:
                await db_service.close()
                print('DBService.close() successful.')
                if hasattr(db_service.adapter, '_conn_pool') and db_service.adapter._conn_pool is None: # type: ignore[protected-access]
                    print("Asyncpg connection pool closed as expected.")
                elif hasattr(db_service.adapter, '_conn_pool'):
                    print(f"WARNING: Asyncpg connection pool not None after close: {db_service.adapter._conn_pool}") # type: ignore[protected-access]
                else:
                    print("Adapter or _conn_pool attribute missing after close.")

                # Check if 'db' attribute exists before trying to access it
                if hasattr(db_service, 'db') and db_service.db is None: # type: ignore[attr-defined]
                    print("SQLAlchemy async session closed as expected.")
                elif hasattr(db_service, 'db') and db_service.db is not None: # type: ignore[attr-defined]
                    print(f"WARNING: SQLAlchemy async session not None after close: {db_service.db}") # type: ignore[attr-defined]
                else:
                    print("SQLAlchemy async session was likely never initialized or 'db' attribute missing after close.")
            except Exception as close_e:
                print(f"Error during DBService.close(): {close_e}")
                traceback.print_exc()

        # Cleanup PGPASSWORD
        if 'PGPASSWORD' in os.environ:
            del os.environ['PGPASSWORD']
            print("PGPASSWORD environment variable cleaned up.")
        else:
            print("PGPASSWORD was not found in environment variables for cleanup (this is unexpected if set at start).")

        print('DBService test finished.')

if __name__ == '__main__':
    # Ensure PATH includes .local/bin for any child processes if necessary, though not directly for this script.
    # This script itself relies on Python path for imports.
    local_bin_path = "/home/swebot/.local/bin"
    if local_bin_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{local_bin_path}:{os.environ.get('PATH', '')}"
        print(f"Temporarily added {local_bin_path} to PATH for script execution context if needed by sub-processes.")

    asyncio.run(main())
