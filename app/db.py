import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import logger # Assuming logger is configured to be accessible

# Default DATABASE_URL for local development (e.g., using PostgreSQL in Docker)
# In a production environment, this should be set via an environment variable.
DEFAULT_DATABASE_URL = "postgresql://user:password@localhost:5432/text_rpg_db"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

logger.info(f"Using database URL: {'<DATABASE_URL_IS_SET_VIA_ENV_VAR>' if os.environ.get('DATABASE_URL') else DEFAULT_DATABASE_URL}")


try:
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
    logger.info("Database engine and SessionLocal created successfully.")
except Exception as e:
    logger.error(f"Error creating database engine or SessionLocal: {e}", exc_info=True)
    # exit(1) # Or handle more gracefully depending on application needs

def init_db():
    """
    Initializes the database by creating all tables defined by Base.metadata.
    This should be called once at application startup.
    """
    try:
        logger.info("Attempting to initialize database and create tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully (if they didn't exist).")
    except Exception as e:
        logger.error(f"Error during database initialization (create_all): {e}", exc_info=True)
        # Potentially re-raise or handle if critical for startup

def get_db():
    """
    FastAPI dependency to get a database session.
    Ensures the database session is always closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Example of how to use get_db in a FastAPI path operation:
# from fastapi import Depends
# from sqlalchemy.orm import Session
# from . import models, schemas # Assuming you have these
#
# @app.post("/users/", response_model=schemas.User)
# def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
#     db_user = models.User(email=user.email, hashed_password=user.hashed_password)
#     db.add(db_user)
#     db.commit()
#     db.refresh(db_user)
#     return db_user

from contextlib import contextmanager

@contextmanager
def transactional_session(guild_id: int | None = None): # guild_id for logging/assertion, not direct filtering here
    """Provides a transactional session context.
    The guild_id is primarily for logging or potential future assertions,
    as filtering logic resides in CRUD operations or service layer.
    """
    db = SessionLocal()
    # Using logger from app.config, already imported at the top of db.py
    logger.debug(f"Transaction started for guild_id: {guild_id if guild_id else 'N/A'}")
    try:
        yield db
        db.commit()
        logger.debug(f"Transaction committed for guild_id: {guild_id if guild_id else 'N/A'}")
    except Exception as e:
        logger.error(f"Transaction rollback due to error for guild_id {guild_id if guild_id else 'N/A'}: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()
        logger.debug(f"Session closed for guild_id: {guild_id if guild_id else 'N/A'}")
