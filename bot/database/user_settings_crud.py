from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload # If relationships need to be loaded, e.g. player

from .models import UserSettings, Player # Assuming Player might be needed for context or future expansion

async def get_user_settings(db: AsyncSession, user_id: str, guild_id: str) -> UserSettings | None:
    """
    Retrieves user settings for a specific user in a specific guild.
    """
    result = await db.execute(
        select(UserSettings)
        .where(UserSettings.user_id == user_id)
        .where(UserSettings.guild_id == guild_id)
    )
    return result.scalar_one_or_none()

async def create_or_update_user_settings(
    db: AsyncSession,
    user_id: str,
    guild_id: str,
    language_code: Optional[str] = None,
    timezone: Optional[str] = None
) -> UserSettings:
    """
    Creates new user settings if they don't exist, or updates them if they do.
    Only updates fields that are explicitly provided (not None).
    """
    existing_settings = await get_user_settings(db, user_id, guild_id)

    if existing_settings:
        # Update existing settings
        if language_code is not None:
            existing_settings.language_code = language_code
        if timezone is not None:
            existing_settings.timezone = timezone
        db_settings = existing_settings
    else:
        # Create new settings
        db_settings = UserSettings(
            user_id=user_id,
            guild_id=guild_id,
            language_code=language_code,
            timezone=timezone
        )
        db.add(db_settings)

    try:
        await db.commit()
        await db.refresh(db_settings)
        return db_settings
    except IntegrityError: # Should ideally not happen if get_user_settings is used first for updates
        await db.rollback()
        # Log or handle appropriately
        raise

async def update_user_settings_specific_fields(
    db: AsyncSession,
    user_id: str,
    guild_id: str,
    settings_update_data: Dict[str, Any]
) -> UserSettings | None:
    """
    Updates specific fields of a user's settings.
    `settings_update_data` is a dictionary containing only the fields to update.
    e.g., {'language_code': 'en-US'}
    """
    db_settings = await get_user_settings(db, user_id, guild_id)
    if db_settings is None:
        return None # Or raise an exception: settings not found

    for key, value in settings_update_data.items():
        if hasattr(db_settings, key):
            setattr(db_settings, key, value)
        else:
            # Handle unknown field if necessary, e.g., log a warning or raise error
            print(f"Warning: Attempted to update unknown field '{key}' in UserSettings.")

    try:
        await db.commit()
        await db.refresh(db_settings)
        return db_settings
    except IntegrityError:
        await db.rollback()
        raise # Or handle more gracefully

async def delete_user_settings(db: AsyncSession, user_id: str, guild_id: str) -> bool:
    """
    Deletes user settings for a specific user in a specific guild.
    Returns True if settings were deleted, False otherwise.
    """
    db_settings = await get_user_settings(db, user_id, guild_id)
    if db_settings is None:
        return False

    await db.delete(db_settings)
    await db.commit()
    return True
