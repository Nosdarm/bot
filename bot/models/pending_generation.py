import enum
import uuid
from sqlalchemy import Column, String, JSON, ForeignKey, DateTime, Enum as SAEnum, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB # For PostgreSQL specific JSONB

from ..database.base import Base # Corrected: Point to the centralized Base from bot.database.base

class GenerationType(enum.Enum):
    LOCATION_DESCRIPTION = "location_description"
    LOCATION_DETAILS = "location_details" # Comprehensive content like PoIs, connections
    NPC_PROFILE = "npc_profile"
    QUEST_IDEATION = "quest_ideation" # Initial idea
    QUEST_FULL = "quest_full" # Full quest structure with steps
    ITEM_PROFILE = "item_profile"
    FACTION_PROFILE = "faction_profile"
    LORE_ENTRY = "lore_entry"
    DIALOGUE_LINE = "dialogue_line"
    EVENT_DESCRIPTION = "event_description"
    CUSTOM_PROMPT = "custom_prompt" # For GM-defined prompts

class PendingStatus(enum.Enum):
    PENDING_GENERATION = "pending_generation" # AI request queued or in progress
    PENDING_VALIDATION = "pending_validation" # AI output received, awaiting structural/semantic validation
    FAILED_VALIDATION = "failed_validation"   # Validation found errors
    PENDING_MODERATION = "pending_moderation" # Validation passed, awaiting GM approval
    APPROVED = "approved"                   # GM approved
    REJECTED = "rejected"                   # GM rejected
    APPLIED = "applied"                     # Content successfully integrated into game state
    APPLICATION_FAILED = "application_failed" # Error occurred during integration
    ARCHIVED = "archived"                   # Kept for records but not active

class PendingGeneration(Base):
    __tablename__ = 'pending_generations'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete="CASCADE"), nullable=False, index=True)

    request_type = Column(SAEnum(GenerationType, name="generation_type_enum"), nullable=False, index=True)
    request_params_json = Column(JSONB, nullable=True) # Parameters used for the AI prompt

    raw_ai_output_text = Column(Text, nullable=True)    # The raw text from AI
    parsed_data_json = Column(JSONB, nullable=True)     # Parsed and Pydantic-validated JSON data
    validation_issues_json = Column(JSONB, nullable=True) # List of ValidationIssue dicts

    status = Column(SAEnum(PendingStatus, name="pending_status_enum"), nullable=False, default=PendingStatus.PENDING_GENERATION, index=True)

    # User who initiated the request, if applicable (e.g., a GM using a command)
    created_by_user_id = Column(String, nullable=True, index=True) # Discord user ID
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Moderation details
    moderated_by_user_id = Column(String, nullable=True) # Discord user ID of GM who moderated
    moderated_at = Column(DateTime(timezone=True), nullable=True)
    moderator_notes = Column(Text, nullable=True) # Renamed from moderator_notes_i18n for simplicity

    # Relationship to GuildConfig (optional, but good practice)
    guild = relationship("GuildConfig") # Assumes GuildConfig model exists

    __table_args__ = (
        Index('idx_pending_generation_guild_status_type', 'guild_id', 'status', 'request_type'),
    )

    def __repr__(self):
        return f"<PendingGeneration(id='{self.id}', guild_id='{self.guild_id}', type='{self.request_type.value if self.request_type else None}', status='{self.status.value if self.status else None}')>"

# Ensure GuildConfig model is defined in bot.models or accessible for the FK.
# If GuildConfig is in bot.database.models, the import might need adjustment based on package structure.
# For now, assuming it's accessible as 'guild_configs.guild_id'.
# Similarly, ensure Base is correctly imported.
# If Base is in the same directory in base.py: from .base import Base
# If Base is in bot.database.models: from bot.database.models import Base (but this creates circular if this file is bot.models.pending_generation)
# The prompt implies this file IS bot.models.pending_generation, so Base should be imported from a common location like bot.models.base.
# The ForeignKey to 'guild_configs.guild_id' implies a table named 'guild_configs' with a column 'guild_id'.
# This matches the GuildConfig model definition from previous tasks.
