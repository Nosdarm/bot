from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING 
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from bot.models.pending_generation import PendingGeneration, GenerationType, PendingStatus

if TYPE_CHECKING:
    from bot.services.db_service import DBService

logger = logging.getLogger(__name__)

class PendingGenerationCRUD:
    """
    CRUD operations for PendingGeneration records.
    These methods expect to be called within an existing transaction/session scope.
    """

    def __init__(self, db_service: DBService): # db_service might not be needed if session is always passed
        self.db_service = db_service # Or just pass session_factory if creating sessions here

    async def create_pending_generation(
        self,
        session: AsyncSession,
        guild_id: str,
        request_type: GenerationType,
        status: PendingStatus,
        request_params_json: Optional[Dict[str, Any]] = None,
        raw_ai_output_text: Optional[str] = None,
        parsed_data_json: Optional[Dict[str, Any]] = None,
        validation_issues_json: Optional[List[Dict[str, Any]]] = None,
        created_by_user_id: Optional[str] = None,
        moderated_by_user_id: Optional[str] = None,
        moderated_at: Optional[Any] = None, # datetime
        moderator_notes: Optional[str] = None
    ) -> PendingGeneration:
        """Creates a new PendingGeneration record."""

        new_pending_gen = PendingGeneration(
            guild_id=str(guild_id),
            request_type=request_type, # Direct enum member
            status=status,             # Direct enum member
            request_params_json=request_params_json,
            raw_ai_output_text=raw_ai_output_text,
            parsed_data_json=parsed_data_json,
            validation_issues_json=validation_issues_json,
            created_by_user_id=str(created_by_user_id) if created_by_user_id else None,
            moderated_by_user_id=str(moderated_by_user_id) if moderated_by_user_id else None,
            moderated_at=moderated_at,
            moderator_notes=moderator_notes
            # id and created_at have defaults
        )
        session.add(new_pending_gen)
        await session.flush() # To get the ID if needed immediately, and for consistency
        await session.refresh(new_pending_gen) # To get server-set defaults like created_at
        logger.info(f"PendingGeneration record created with ID: {new_pending_gen.id} for guild {guild_id}, type {request_type.value}, status {status.value}")
        return new_pending_gen

    async def get_pending_generation_by_id(self, session: AsyncSession, record_id: str, guild_id: Optional[str] = None) -> Optional[PendingGeneration]:
        """Fetches a PendingGeneration record by its ID, optionally verifying guild_id."""
        stmt = select(PendingGeneration).where(PendingGeneration.id == str(record_id))
        if guild_id:
            stmt = stmt.where(PendingGeneration.guild_id == str(guild_id))

        result = await session.execute(stmt)
        instance = result.scalars().first()
        if instance:
            logger.debug(f"Fetched PendingGeneration record by ID: {record_id} for guild {guild_id or 'any'}")
        else:
            logger.debug(f"No PendingGeneration record found for ID: {record_id} for guild {guild_id or 'any'}")
        return instance

    async def update_pending_generation_status(
        self,
        session: AsyncSession,
        record_id: str,
        new_status: PendingStatus, # Expect enum member
        guild_id: Optional[str] = None, # For verification
        validation_issues_json: Optional[List[Dict[str, Any]]] = None, # To update if status is FAILED_VALIDATION
        parsed_data_json: Optional[Dict[str, Any]] = None, # To update if status is PENDING_MODERATION (after successful validation)
        moderated_by_user_id: Optional[str] = None, # For APPROVED/REJECTED
        moderator_notes: Optional[str] = None # For APPROVED/REJECTED
    ) -> Optional[PendingGeneration]:
        """Updates the status and optionally other fields of a PendingGeneration record."""

        # Fetch first to ensure it exists and optionally matches guild_id
        record = await self.get_pending_generation_by_id(session, record_id, guild_id)
        if not record:
            logger.warning(f"Cannot update status for non-existent PendingGeneration record ID: {record_id} in guild {guild_id or 'any'}")
            return None

        record.status = new_status
        update_fields = {"status": new_status} # Start with status

        if validation_issues_json is not None: # Allow explicitly setting to None or providing new issues
            record.validation_issues_json = validation_issues_json
            update_fields["validation_issues_json"] = validation_issues_json

        if parsed_data_json is not None: # Allow updating parsed data if re-validation was successful
            record.parsed_data_json = parsed_data_json
            update_fields["parsed_data_json"] = parsed_data_json

        if new_status in [PendingStatus.APPROVED, PendingStatus.REJECTED]:
            if moderated_by_user_id:
                record.moderated_by_user_id = str(moderated_by_user_id)
                update_fields["moderated_by_user_id"] = str(moderated_by_user_id)
            if moderator_notes is not None: # Allow empty string for notes
                record.moderator_notes = moderator_notes
                update_fields["moderator_notes"] = moderator_notes
            record.moderated_at = func.now() # Update moderation timestamp
            update_fields["moderated_at"] = func.now()

        if new_status == PendingStatus.APPLIED:
            # Potentially clear raw_ai_output_text or other fields if no longer needed
            pass


        # Instead of setattr, use SQLAlchemy's update mechanism for partial updates if preferred,
        # but direct assignment on the fetched object within a session also works.
        # The session.add(record) ensures it's marked as dirty if changes occurred.
        session.add(record)
        await session.flush()
        await session.refresh(record)
        logger.info(f"PendingGeneration record ID: {record_id} status updated to {new_status.value}. Additional fields updated: {list(update_fields.keys())}")
        return record

    async def get_pending_reviews_for_guild(
        self,
        session: AsyncSession,
        guild_id: str,
        status: PendingStatus = PendingStatus.PENDING_MODERATION,
        limit: int = 10
    ) -> List[PendingGeneration]:
        """Fetches PendingGeneration records for a guild that are awaiting moderation (or other specified status)."""
        stmt = select(PendingGeneration).\
            where(PendingGeneration.guild_id == str(guild_id)).\
            where(PendingGeneration.status == status).\
            order_by(PendingGeneration.created_at.asc()).\
            limit(limit)

        result = await session.execute(stmt)
        records = result.scalars().all()
        logger.debug(f"Fetched {len(records)} PendingGeneration records for guild {guild_id} with status {status.value}")
        return list(records)

    async def get_all_for_guild_by_type_and_status(
        self,
        session: AsyncSession,
        guild_id: str,
        request_type: Optional[GenerationType] = None,
        status: Optional[PendingStatus] = None,
        limit: int = 100
    ) -> List[PendingGeneration]:
        """ Fetches records by guild, optionally filtering by type and/or status. """
        stmt = select(PendingGeneration).where(PendingGeneration.guild_id == str(guild_id))
        if request_type:
            stmt = stmt.where(PendingGeneration.request_type == request_type)
        if status:
            stmt = stmt.where(PendingGeneration.status == status)
        stmt = stmt.order_by(PendingGeneration.created_at.desc()).limit(limit)

        result = await session.execute(stmt)
        records = result.scalars().all()
        logger.debug(f"Fetched {len(records)} PendingGeneration records for guild {guild_id} (type: {request_type}, status: {status}).")
        return list(records)
