import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from typing import AsyncIterator
import os

from bot.api.main import app
from bot.database.database import get_db
from bot.database.models import Base

# Use the in-memory SQLite database for testing
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)

async def override_get_db() -> AsyncIterator[AsyncSession]:
    """
    Dependency override for getting a DB session in tests.
    """
    async with TestingSessionLocal() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db

@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncIterator[AsyncClient]:
    """
    Provides an AsyncClient for making API requests to the FastAPI app,
    with a clean database for each test function.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
