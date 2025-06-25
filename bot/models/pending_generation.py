import enum
import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, Enum as SAEnum, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
# JSONB removed from sqlalchemy.dialects.postgresql as JsonVariant will be used

from .base import Base
from sqlalchemy import JSON as JsonVariant # Assuming Base is in bot/models/base.py or accessible via .base
# Attempt to import GuildConfig directly for the relationship
try:
    from bot.database.models.config_related import GuildConfig
except ImportError:
    # This fallback might be hit if there's a circular dependency during initial load,
    # but SQLAlchemy might resolve it later if GuildConfig is part of the same Base metadata.
    # For type hinting and explicit relationship, direct import is preferred.
    # GuildConfig = "GuildConfig" # Keep as string if direct import fails, rely on SQLAlchemy's deferred resolution
    # No, we need Mapped from sqlalchemy.orm
    from sqlalchemy.orm import Mapped

class GenerationType(enum.Enum):
    LOCATION_DESCRIPTION = "location_description"
    LOCATION_DETAILS = "location_details"
    NPC_PROFILE = "npc_profile"
    QUEST_IDEATION = "quest_ideation"
    QUEST_FULL = "quest_full"
    ITEM_PROFILE = "item_profile"
    FACTION_PROFILE = "faction_profile"
    LORE_ENTRY = "lore_entry"
    DIALOGUE_LINE = "dialogue_line"
    EVENT_DESCRIPTION = "event_description"
    CUSTOM_PROMPT = "custom_prompt"

class PendingStatus(enum.Enum):
    PENDING_GENERATION = "pending_generation"
    PENDING_VALIDATION = "pending_validation"
    FAILED_VALIDATION = "failed_validation"
    PENDING_MODERATION = "pending_moderation"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    APPLICATION_FAILED = "application_failed"
    ARCHIVED = "archived"

class PendingGeneration(Base):
    __tablename__ = 'pending_generations'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete="CASCADE"), nullable=False, index=True)

    request_type = Column(SAEnum(GenerationType, name="generation_type_enum"), nullable=False, index=True)
    request_params_json = Column(JsonVariant, nullable=True) # Changed from JSONB

    raw_ai_output_text = Column(Text, nullable=True)
    parsed_data_json = Column(JsonVariant, nullable=True)     # Changed from JSONB
    validation_issues_json = Column(JsonVariant, nullable=True) # Changed from JSONB

    status = Column(SAEnum(PendingStatus, name="pending_status_enum"), nullable=False, default=PendingStatus.PENDING_GENERATION, index=True)

    created_by_user_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    moderated_by_user_id = Column(String, nullable=True)
    moderated_at = Column(DateTime(timezone=True), nullable=True)
    moderator_notes = Column(Text, nullable=True) # Kept as Text, was moderator_notes_i18n (JSONB)

    # Relationship to GuildConfig
    guild: Mapped["GuildConfig"] = relationship(back_populates="pending_generations")


    __table_args__ = (
        Index('idx_pending_generation_guild_status_type', 'guild_id', 'status', 'request_type'),
    )

    def __repr__(self):
        return f"<PendingGeneration(id='{self.id}', guild_id='{self.guild_id}', type='{self.request_type.value if self.request_type else None}', status='{self.status.value if self.status else None}')>"
