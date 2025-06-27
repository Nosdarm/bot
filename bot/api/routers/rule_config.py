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
    """
    Helper function to retrieve RulesConfig for a guild, assembling it from individual rows,
    or creating default rows if none exist.
    Returns a Pydantic RuleConfigData model.
    """
    stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    result = await db.execute(stmt)
    existing_rules_rows = result.scalars().all()

    rules_data_dict = {row.key: row.value for row in existing_rules_rows}

    if not existing_rules_rows:
        logger.info(f"No RulesConfig rows found for guild {guild_id}. Initializing with defaults.")
        default_rules_pydantic = RuleConfigData() # Pydantic model with defaults
        default_rules_dict = default_rules_pydantic.model_dump(mode='json') # Get dict representation, mode='json' ensures complex types are serializable if needed

        for key, value in default_rules_dict.items():
            new_rule_row = RulesConfig(
                guild_id=guild_id,
                key=key,
                value=value, # value should be JSON-compatible (dict, list, str, int, etc.)
                description=f"Default value for {key}" # Optional: add description
            )
            db.add(new_rule_row)
        
        try:
            # No explicit commit here; let the session from Depends(get_db_session) handle it.
            # We need to flush to get IDs if necessary, but for simple add, commit at end of request is fine.
            # For the purpose of returning the RuleConfigData, we can use the default_rules_dict directly.
            logger.info(f"Prepared default RulesConfig rows for guild {guild_id} to be added in current session.")
            rules_data_dict = default_rules_dict # Use the defaults we just prepared
            # The actual commit will happen when get_db_session context manager exits.
        except Exception as e_create: # Should be less likely now without commit
            # await db.rollback() # Rollback is handled by get_db_session context manager on exception
            logger.error(f"Error preparing default RulesConfig rows for guild {guild_id}: {e_create}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error preparing default RulesConfig for guild {guild_id}."
            )

    # Construct the Pydantic model from the dictionary of rules
    # This assumes RuleConfigData can be instantiated from a flat dictionary of its fields
    # If RuleConfigData has nested Pydantic models, this might need adjustment.
    # For now, assuming direct field mapping.
    try:
        # Ensure that all fields expected by RuleConfigData are present in rules_data_dict,
        # or that RuleConfigData handles missing fields with defaults.
        # If a key is in RuleConfigData but not in DB, Pydantic will use its default.
        # Filter out keys not present in RuleConfigData model fields to prevent unexpected argument error
        valid_fields = RuleConfigData.model_fields.keys()
        filtered_rules_data = {k: v for k, v in rules_data_dict.items() if k in valid_fields}

        return RuleConfigData(**filtered_rules_data)
    except Exception as e_pydantic:
        logger.error(f"Error creating RuleConfigData Pydantic model for guild {guild_id} from DB data: {e_pydantic}", exc_info=True)
        logger.warning(f"Falling back to default RuleConfigData for guild {guild_id} due to Pydantic model creation error.")
        return RuleConfigData() # Return a default instance on error


@router.get(
    "/",
    response_model=RuleConfigResponse, # This should be RuleConfigResponse which contains RuleConfigData
    summary="Get current game rule configuration for the guild"
)
async def get_guild_rules_config( # Renamed to be unique
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Fetching RulesConfig for guild {guild_id}")
    try:
        # get_or_create_rules_config returns a RuleConfigData instance
        rules_data_pydantic = await get_or_create_rules_config(db, guild_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching or creating RulesConfig for guild {guild_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error accessing guild configuration.")
        
    # Wrap the RuleConfigData in RuleConfigResponse
    return RuleConfigResponse(guild_id=guild_id, config_data=rules_data_pydantic)


@router.put(
    "/",
    response_model=RuleConfigResponse, # This should be RuleConfigResponse
    summary="Update game rule configuration for the guild"
)
async def update_guild_rules_config( # Renamed to be unique
    config_update_payload: RuleConfigUpdate,
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Updating RulesConfig for guild {guild_id}")

    # Fetch existing rules to update them or create new ones
    stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    result = await db.execute(stmt)
    existing_rules_rows = result.scalars().all()
    current_rules_map = {row.key: row for row in existing_rules_rows}

    updated_rules_data_dict = config_update_payload.config_data.model_dump(mode='json') # Get all fields from payload

    for key, new_value in updated_rules_data_dict.items():
        if key in current_rules_map:
            # Update existing rule row
            current_rules_map[key].value = new_value
            # logger.debug(f"Updating rule {key} for guild {guild_id} to {new_value}")
            db.add(current_rules_map[key]) # Mark as dirty
        else:
            # Create new rule row
            # Optional: Add a description if one can be inferred or is standard for new rules
            new_rule_row = RulesConfig(
                guild_id=guild_id,
                key=key,
                value=new_value,
                description=f"Custom value for {key}"
            )
            # logger.debug(f"Creating new rule {key} for guild {guild_id} with value {new_value}")
            db.add(new_rule_row)
            current_rules_map[key] = new_rule_row # Add to map for response assembly

    try:
        await db.commit() # Commit all changes (updates and new rows)
        logger.info(f"Successfully updated/created RulesConfig rows for guild {guild_id}.")

        # Re-assemble the Pydantic model from the potentially updated/newly created DB state
        # This ensures the response reflects exactly what's in the DB after the transaction.
        # Alternatively, update rules_data_dict directly and construct RuleConfigData from it,
        # but re-fetching is safer if DB triggers/defaults could modify data.

        # For simplicity and to reflect the committed state, create RuleConfigData from current_rules_map values
        # (after they've been added to session and potentially refreshed by commit)
        final_rules_values = {key: row.value for key, row in current_rules_map.items()}

    # Filter out keys not present in RuleConfigData model fields before creating Pydantic model
    valid_fields = RuleConfigData.model_fields.keys()
    filtered_final_rules_values = {k: v for k, v in final_rules_values.items() if k in valid_fields}

    updated_pydantic_data = RuleConfigData(**filtered_final_rules_values)

    except Exception as e_update:
        # Rollback is handled by get_db_session context manager on exception
        # await db.rollback()
        logger.error(f"Error updating RulesConfig rows for guild {guild_id}: {e_update}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update RulesConfig.")

    return RuleConfigResponse(guild_id=guild_id, config_data=updated_pydantic_data)
