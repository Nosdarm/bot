# bot/api/routers/player.py
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload # For eager loading characters
from sqlalchemy.exc import IntegrityError
import uuid # For generating player IDs
import logging

from bot.api.dependencies import get_db_session
from bot.api.schemas.player_schemas import PlayerCreate, PlayerUpdate, PlayerRead # Updated PlayerResponse to PlayerRead
from bot.database.models import Player

logger = logging.getLogger(__name__)
router = APIRouter() # Prefix will be added in main.py: /api/v1/guilds/{guild_id}/players

@router.post("/", response_model=PlayerRead, status_code=status.HTTP_201_CREATED, summary="Create a new player")
async def create_player(
    # guild_id from path is usually preferred as the authoritative source
    path_guild_id: str = Path(..., description="Guild ID from path", alias="guild_id"),
    player_data: PlayerCreate, # Removed Depends(), direct model usage
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Attempting to create player for discord_id {player_data.discord_id} in guild {player_data.guild_id}")

    if path_guild_id != player_data.guild_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Guild ID in path ({path_guild_id}) does not match Guild ID in body ({player_data.guild_id})."
        )

    player_id = str(uuid.uuid4())

    # Ensure discord_id is not already taken for this guild (UniqueConstraint handles this at DB)
    # but a pre-check can give a nicer error.
    existing_player_stmt = select(Player).where(Player.discord_id == player_data.discord_id, Player.guild_id == player_data.guild_id)
    result = await db.execute(existing_player_stmt)
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Player with Discord ID {player_data.discord_id} already exists in guild {player_data.guild_id}"
        )

    # Create Player instance using all fields from PlayerCreate schema
    db_player_data = player_data.dict()
    # guild_id is already in player_data.dict() due to schema change
    db_player = Player(
        id=player_id,
        **db_player_data
    )
    db.add(db_player)
    try:
        await db.commit()
        await db.refresh(db_player) # To get DB defaults and relationships if any immediately
    except IntegrityError as e: # Handles the UniqueConstraint uq_player_discord_guild
        await db.rollback()
        logger.error(f"IntegrityError creating player: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A player with this Discord ID likely already exists in this guild, or another integrity constraint failed."
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating player: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create player.")

    # Manually load characters for the response as they might not be loaded by default after refresh
    # If PlayerResponse expects characters, ensure they are loaded.
    # For creation, characters list will be empty.
    db_player.characters = [] # Initialize as empty list for new player response
    # Ensure all fields expected by PlayerRead are present, or adjust PlayerRead schema
    # For example, if PlayerRead expects xp, level, etc., ensure they have default values in the Player model or are set here.
    # The Player model has defaults for xp, level, etc.

    return db_player


@router.get("/{player_id}", response_model=PlayerRead, summary="Get player details by Player ID")
async def get_player(
    guild_id: str = Path(..., description="Guild ID from path"),
    player_id: str = Path(..., description="ID of the player to retrieve"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Fetching player {player_id} for guild {guild_id}")
    stmt = select(Player).options(selectinload(Player.characters)).where(Player.id == player_id, Player.guild_id == guild_id)
    result = await db.execute(stmt)
    db_player = result.scalars().first()
    if not db_player:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found in this guild")
    return db_player


@router.get("/by_discord/{discord_user_id}", response_model=PlayerResponse, summary="Get player details by Discord User ID")
async def get_player_by_discord_id(
    guild_id: str = Path(..., description="Guild ID from path"),
    discord_user_id: str = Path(..., description="Discord User ID of the player"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Fetching player by discord_id {discord_user_id} for guild {guild_id}")
    stmt = select(Player).options(selectinload(Player.characters)).where(Player.discord_id == discord_user_id, Player.guild_id == guild_id)
    result = await db.execute(stmt)
    db_player = result.scalars().first()
    if not db_player:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player with specified Discord ID not found in this guild")
    return db_player


@router.put("/{player_id}", response_model=PlayerRead, summary="Update player details")
async def update_player(
    guild_id: str = Path(..., description="Guild ID from path"),
    player_id: str = Path(..., description="ID of the player to update"),
    player_update_data: PlayerUpdate, # Removed Depends(), direct model usage
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Updating player {player_id} in guild {guild_id}")
    stmt = select(Player).where(Player.id == player_id, Player.guild_id == guild_id)
    result = await db.execute(stmt)
    db_player = result.scalars().first()

    if not db_player:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found in this guild")

    update_data = player_update_data.dict(exclude_unset=True) # Get only fields that were actually sent
    for key, value in update_data.items():
        setattr(db_player, key, value)

    db.add(db_player) # Add to session to mark as dirty
    try:
        await db.commit()
        await db.refresh(db_player)
         # Eager load characters again after refresh for the response
        stmt_refresh = select(Player).options(selectinload(Player.characters)).where(Player.id == db_player.id)
        refreshed_result = await db.execute(stmt_refresh)
        db_player_refreshed = refreshed_result.scalars().first()
        if not db_player_refreshed: # Should not happen if refresh worked
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to reload player after update.")
        return db_player_refreshed

    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating player {player_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update player.")


@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a player (marks inactive)")
async def delete_player(
    guild_id: str = Path(..., description="Guild ID from path"),
    player_id: str = Path(..., description="ID of the player to delete/mark inactive"),
    db: AsyncSession = Depends(get_db_session)
):
    # This currently marks the player as inactive instead of actually deleting.
    # This will be a hard delete as per requirements.
    logger.info(f"Attempting to delete player {player_id} in guild {guild_id}")
    stmt = select(Player).where(Player.id == player_id, Player.guild_id == guild_id)
    result = await db.execute(stmt)
    db_player = result.scalars().first()

    if not db_player:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found in this guild")

    await db.delete(db_player)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting player {player_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete player.")

    # For HTTP 204, FastAPI expects no response body.
    # If a message is desired, change status_code and return a dict.
    # For example, return {"message": "Player deleted successfully"} with status_code=200
    # However, sticking to 204 as per current code for delete.
    return # Implicitly returns 204 No Content
