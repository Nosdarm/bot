# bot/api/dependencies.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from typing import AsyncGenerator
import os

# This should ideally come from a central config, same as Alembic and game_manager
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot")

engine = create_async_engine(DATABASE_URL, echo=False) # echo=True for debugging SQL
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit() # Commit if no exceptions during request handling
        except Exception:
            await session.rollback() # Rollback on error
            raise
        finally:
            await session.close()

async def create_db_and_tables():
    # This is for initial setup if needed, not typically run per request.
    # You would call this once at application startup if tables aren't managed by Alembic exclusively.
    # from bot.database.models import Base # Assuming Base is your declarative base
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    pass # Alembic handles table creation
