# bot/api/routers/rule_config.py
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import logging

from bot.api.dependencies import get_db_session
from bot.api.schemas.rule_config_schemas import RuleConfigUpdate, RuleConfigResponse, RuleConfigData
from bot.database.models import RulesConfig
# from bot.game.guild_initializer import initialize_new_guild # Decided against full init here

logger = logging.getLogger(__name__)
router = APIRouter() # Prefix will be /api/v1/guilds/{guild_id}/config from main.py

async def get_or_create_rules_config(db: AsyncSession, guild_id: str) -> RulesConfig:
    """
    Helper function to retrieve RulesConfig for a guild, creating it with defaults if it doesn't exist.
    """
    stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    result = await db.execute(stmt)
    db_config = result.scalars().first()

    if not db_config:
        logger.info(f"No RulesConfig found for guild {guild_id}. Initializing with defaults on-the-fly.")
        
        # Create RulesConfig with defaults from the Pydantic schema
        default_data = RuleConfigData().dict() # Get Pydantic model defaults
        db_config = RulesConfig(guild_id=guild_id, config_data=default_data)
        db.add(db_config)
        try:
            # This commit is within the session managed by get_db_session.
            # If get_db_session does a final commit, this might be redundant or could
            # cause issues if it's a nested transaction.
            # For now, let's assume this explicit commit is needed for refresh.
            await db.commit() 
            await db.refresh(db_config)
            logger.info(f"Created default RulesConfig for guild {guild_id} on-the-fly.")
        except Exception as e_create:
            await db.rollback() # Rollback this specific auto-creation attempt
            logger.error(f"Failed to create default RulesConfig for guild {guild_id} on-the-fly: {e_create}")
            # This exception will be caught by the endpoint and result in a 500 for the client.
            # Re-raising to ensure the calling endpoint knows this failed.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"RulesConfig was missing and could not be auto-created for guild {guild_id}."
            )
    return db_config

@router.get(
    "/",  # Path relative to the router's prefix (e.g., /api/v1/guilds/{guild_id}/config/)
    response_model=RuleConfigResponse, 
    summary="Get current game rule configuration for the guild"
)
async def get_guild_rules_config_endpoint( # Renamed to avoid conflict with model name
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Fetching RulesConfig for guild {guild_id}")
    try:
        db_config = await get_or_create_rules_config(db, guild_id)
    except HTTPException:
        raise # Re-raise if get_or_create_rules_config failed and raised HTTPException
    except Exception as e:
        logger.error(f"Unexpected error fetching or creating RulesConfig for guild {guild_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error accessing guild configuration.")
        
    return db_config


@router.put(
    "/", # Path relative to the router's prefix
    response_model=RuleConfigResponse, 
    summary="Update game rule configuration for the guild"
)
async def update_guild_rules_config_endpoint( # Renamed to avoid conflict
    config_update_payload: RuleConfigUpdate, # Body parameter
    guild_id: str = Path(..., description="Guild ID from path prefix"), # Path parameter
    db: AsyncSession = Depends(get_db_session) # Parameter with default
):
    logger.info(f"Updating RulesConfig for guild {guild_id}")
    try:
        db_config = await get_or_create_rules_config(db, guild_id)
    except HTTPException:
        raise 
    except Exception as e:
        logger.error(f"Unexpected error fetching or creating RulesConfig for update for guild {guild_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error accessing guild configuration before update.")

    # config_update_payload.config_data is an instance of RuleConfigData Pydantic model.
    # .dict() serializes the Pydantic model (with its defaults applied for any missing fields from request)
    new_config_data_dict = config_update_payload.config_data.dict()

    db_config.config_data = new_config_data_dict
    db.add(db_config) # Mark as dirty
    try:
        # The final commit is handled by the get_db_session dependency upon successful exit of the endpoint.
        # If an explicit commit is needed here (e.g., if get_db_session doesn't commit), uncomment:
        # await db.commit()
        await db.refresh(db_config) # Refresh to get the potentially DB-processed JSON data back
    except Exception as e:
        # Rollback is handled by get_db_session for general exceptions.
        logger.error(f"Error updating RulesConfig for guild {guild_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update RulesConfig.")
    
    return db_config
