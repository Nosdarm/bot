# bot/api/routers/guild.py
from fastapi import APIRouter, Depends, HTTPException, Path, Body, status
from pydantic import BaseModel # Moved to top
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from bot.api.dependencies import get_db_session
from bot.game.guild_initializer import initialize_new_guild

logger = logging.getLogger(__name__)
router = APIRouter() # No prefix here, it will be handled by app.include_router

class GuildInitializationResponse(BaseModel):
    guild_id: str
    message: str
    success: bool

@router.post(
    "/initialize", # Path relative to the router's prefix
    response_model=GuildInitializationResponse,
    summary="Initialize the guild with default settings",
    tags=["Guild Initialization"] # More specific tag
)
async def init_guild_endpoint(
    guild_id: str = Path(..., title="The ID of the guild to initialize", min_length=3), # guild_id from path
    force_reinitialize: bool = Body(False, description="If true, attempts to re-initialize even if data exists."),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Initializes the guild identified by **guild_id** path parameter.
    - **force_reinitialize**: Optional boolean in request body.
    """
    logger.info(f"API call to initialize guild: {guild_id}, force: {force_reinitialize}")

    success = await initialize_new_guild(db_session=db, guild_id=guild_id, force_reinitialize=force_reinitialize)

    if success:
        # Check if it was truly a new initialization or an update due to force_reinitialize
        # This simple check doesn't differentiate well; initialize_new_guild would need to return more state.
        # For now, if initialize_new_guild returns True, we assume it means "action taken and succeeded".
        return GuildInitializationResponse(
            guild_id=guild_id,
            message=f"Guild {guild_id} processed for initialization successfully.",
            success=True
        )
    else:
        # This path is taken if initialize_new_guild explicitly returns False.
        # This could be due to an IntegrityError, other exception, or skipped (if not forced and already exists).
        # We need to differentiate "skipped" from "failed".
        # initialize_new_guild currently returns False for skipped (if not forced) and for errors.

        # Let's assume for now that if not successful, it's an error unless it was skipped.
        # The current initialize_new_guild returns False if skipped and no force.
        # Let's refine the response based on whether the guild config exists *after* the call.
        from bot.database.models import RulesConfig # Local import for check
        from sqlalchemy.future import select
        stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
        result = await db.execute(stmt) # Re-query the session state
        config_exists_after_call = result.scalars().first()

        if not force_reinitialize and config_exists_after_call:
            # This means it likely existed before and was skipped by initialize_new_guild's internal check
            return GuildInitializationResponse(
                guild_id=guild_id,
                message=f"Guild {guild_id} was already initialized and force_reinitialize was false. No changes made.",
                success=True # Reporting success as "no action needed and state is as expected"
            )

        # If we reach here, it means initialize_new_guild returned False for a reason other than skipping.
        # This implies an actual error during the process.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize guild {guild_id}. An error occurred during the process. Check server logs."
        )
