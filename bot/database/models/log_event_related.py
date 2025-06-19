from sqlalchemy import (
    Column, Integer, String, JSON, ForeignKey, Boolean, Text,
    PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any, List # Add other typing imports if model uses them

from ..base import Base # Import Base from the new location

class Timer(Base):
    __tablename__ = 'timers'
    id = Column(String, primary_key=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    type = Column(String, nullable=False)
    ends_at = Column(Float, nullable=False)
    callback_data = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    def __repr__(self): return f"<Timer(id='{self.id}', type='{self.type}', ends_at={self.ends_at}, active={self.is_active}, guild_id='{self.guild_id}')>"

class Event(Base):
    __tablename__ = 'events'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name_i18n = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True)
    channel_id = Column(String, nullable=True)
    current_stage_id = Column(String, nullable=True)
    players = Column(JSONB, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    stages_data = Column(JSONB, nullable=True)
    end_message_template_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)


class PendingConflict(Base):
    __tablename__ = 'pending_conflicts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    conflict_data_json = Column(JSONB, nullable=False)
    status = Column(String, nullable=False, default='pending_gm_resolution', index=True)
    resolution_data_json = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)


class PendingGeneration(Base):
    __tablename__ = 'pending_generations'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    request_type = Column(String, nullable=False, index=True)
    request_params_json = Column(JSONB, nullable=True)

    raw_ai_output_text = Column(Text, nullable=True)
    parsed_data_json = Column(JSONB, nullable=True)
    validation_issues_json = Column(JSONB, nullable=True)

    status = Column(String, nullable=False, default="pending_validation", index=True)

    created_by_user_id = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    moderated_by_user_id = Column(String, nullable=True)
    moderated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    moderator_notes_i18n = Column(JSONB, nullable=True)

    __table_args__ = (
        Index('idx_pendinggeneration_guild_status', 'guild_id', 'status'),
    )

    def __repr__(self):
        return f"<PendingGeneration(id='{self.id}', guild_id='{self.guild_id}', type='{self.request_type}', status='{self.status}')>"


class StoryLog(Base):
    __tablename__ = 'story_logs'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)

    location_id = Column(String, ForeignKey('locations.id'), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)

    entity_ids_json = Column(JSONB, nullable=True, comment='Stores IDs of entities involved, e.g., {"character_ids": [], "npc_ids": [], "item_ids": []}')
    details_json = Column(JSONB, nullable=True, comment='Stores detailed, structured information about the event')

    # Optional relationships if direct querying from StoryLog to these tables is common
    # location = relationship("Location", foreign_keys=[location_id])
    # guild = relationship("GuildConfig", foreign_keys=[guild_id])

    __table_args__ = (
        Index('idx_storylog_guild_timestamp', 'guild_id', 'timestamp'),
        Index('idx_storylog_guild_event_type', 'guild_id', 'event_type'),
    )

    def __repr__(self):
        return f"<StoryLog(id='{self.id}', guild_id='{self.guild_id}', type='{self.event_type}', ts='{self.timestamp}')>"
