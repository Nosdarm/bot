# bot/database/pending_generation_crud.py
import logging
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING
from uuid import UUID, uuid4
from enum import Enum
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, and_

# Enums and Model sourced from bot.database.models (which re-exports them from their canonical locations)
from bot.database.models import PendingGeneration, PendingStatus, GenerationType


logger = logging.getLogger(__name__)

class PendingGenerationCRUD:
    def __init__(self):
        # db_service is not used if session is always passed to methods
        pass

    async def create_pending_generation(
        self, session: AsyncSession, guild_id: str, request_type: GenerationType, status: PendingStatus, **kwargs: Any
    ) -> PendingGeneration:
        entity_data = {
            "guild_id": str(guild_id),
            "request_type": request_type.value, # Enums should be stored by value
            "status": status.value,          # Enums should be stored by value
            **kwargs
        }
        if 'id' not in entity_data or entity_data['id'] is None:
             entity_data['id'] = str(uuid4())
        if 'created_at' not in entity_data: # Ensure created_at is set if model doesn't auto-set
            entity_data['created_at'] = datetime.now(timezone.utc)
        if 'updated_at' not in entity_data: # Ensure updated_at is set
            entity_data['updated_at'] = datetime.now(timezone.utc)


        new_record = PendingGeneration(**entity_data)
        session.add(new_record)
        await session.flush()
        await session.refresh(new_record)
        logger.info(f"Created PendingGeneration record ID {new_record.id} for guild {guild_id}.")
        return new_record

    async def get_pending_generation_by_id(
        self, session: AsyncSession, record_id: str, guild_id: Optional[str] = None
    ) -> Optional[PendingGeneration]:
        stmt = select(PendingGeneration).where(PendingGeneration.id == str(record_id))
        if guild_id:
            stmt = stmt.where(PendingGeneration.guild_id == str(guild_id))
        result = await session.execute(stmt)
        return result.scalars().first()

    async def update_pending_generation_status(
        self,
        session: AsyncSession,
        record_id: str,
        new_status: PendingStatus,
        guild_id: str,
        moderated_by_user_id: Optional[str] = None,
        moderator_notes: Optional[str] = None,
        validation_issues_json: Optional[List[Dict[str, Any]]] = None,
        parsed_data_json: Optional[Dict[str, Any]] = None, # Added to match test usage
        entity_id: Optional[str] = None # Added to match test usage
    ) -> Optional[PendingGeneration]:
        record = await self.get_pending_generation_by_id(session, str(record_id), str(guild_id))
        if not record:
            logger.warning(f"Attempted to update non-existent PendingGeneration record {record_id} for guild {guild_id}.")
            return None

        record.status = new_status.value # Store enum by value
        if moderated_by_user_id is not None: # Allow explicit None
            record.moderated_by_user_id = str(moderated_by_user_id) if moderated_by_user_id else None
        if moderator_notes is not None:
            record.moderator_notes = moderator_notes
        if validation_issues_json is not None:
            record.validation_issues_json = validation_issues_json
        if parsed_data_json is not None:
            record.parsed_data_json = parsed_data_json
        if entity_id is not None:
            record.entity_id = entity_id

        record.moderated_at = datetime.now(timezone.utc)
        record.updated_at = datetime.now(timezone.utc) # Ensure updated_at is set

        session.add(record)
        await session.flush()
        await session.refresh(record)
        logger.info(f"Updated PendingGeneration record {record_id} to status {new_status.value}.")
        return record

    async def get_pending_reviews_for_guild(
        self, session: AsyncSession, guild_id: str,
        status: PendingStatus = PendingStatus.PENDING_MODERATION,
        limit: int = 10
    ) -> List[PendingGeneration]:
        stmt = (
            select(PendingGeneration)
            .where(PendingGeneration.guild_id == str(guild_id))
            .where(PendingGeneration.status == status.value) # Store enum by value
            .order_by(PendingGeneration.created_at.desc()) # type: ignore[attr-defined]
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_for_guild_by_type_and_status(
        self,
        session: AsyncSession,
        guild_id: str,
        request_type: Optional[GenerationType] = None,
        status: Optional[PendingStatus] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[PendingGeneration]:
        conditions = [PendingGeneration.guild_id == str(guild_id)]
        if request_type:
            conditions.append(PendingGeneration.request_type == request_type.value) # Store enum by value
        if status:
            conditions.append(PendingGeneration.status == status.value) # Store enum by value

        stmt = select(PendingGeneration).where(and_(*conditions))

        if hasattr(PendingGeneration, 'created_at'):
            stmt = stmt.order_by(PendingGeneration.created_at.desc()) # type: ignore[attr-defined]

        if limit is not None: stmt = stmt.limit(limit)
        if offset is not None: stmt = stmt.offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def delete_pending_generation(
        self, session: AsyncSession, record_id: str, guild_id: str
    ) -> bool:
        record = await self.get_pending_generation_by_id(session, str(record_id), str(guild_id))
        if not record:
            logger.warning(f"Attempted to delete non-existent PendingGeneration record {record_id} for guild {guild_id}.")
            return False
        await session.delete(record)
        await session.flush()
        logger.info(f"Deleted PendingGeneration record {record_id} for guild {guild_id}.")
        return True
