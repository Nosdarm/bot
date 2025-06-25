from sqlalchemy import (
    Column, Integer, String, ForeignKey, Boolean, Text, # JSON removed
    PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID # JSONB removed
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any, List, TYPE_CHECKING # Added TYPE_CHECKING

from ..base import Base, JsonVariant # Import Base and JsonVariant

# Explicitly import GuildConfig for ForeignKey definitions
from .config_related import GuildConfig

if TYPE_CHECKING: # Keep other type-only imports here if any are added later
    pass

class Timer(Base):
    __tablename__ = 'timers'
    id = Column(String, primary_key=True)
    guild_id = Column(String, ForeignKey(GuildConfig.guild_id, ondelete='CASCADE'), nullable=False, index=True)
    type = Column(String, nullable=False)
    ends_at = Column(Float, nullable=False)
    callback_data = Column(JsonVariant, nullable=True) # Changed
    is_active = Column(Boolean, default=True, nullable=False)
    def __repr__(self): return f"<Timer(id='{self.id}', type='{self.type}', ends_at={self.ends_at}, active={self.is_active}, guild_id='{self.guild_id}')>"

class Event(Base):
    __tablename__ = 'events'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name_i18n = Column(JsonVariant, nullable=True) # Changed
    is_active = Column(Boolean, default=True)
    channel_id = Column(String, nullable=True)
    current_stage_id = Column(String, nullable=True)
    players = Column(JsonVariant, nullable=True) # Changed
    state_variables = Column(JsonVariant, nullable=True) # Changed
    stages_data = Column(JsonVariant, nullable=True) # Changed
    end_message_template_i18n = Column(JsonVariant, nullable=True) # Changed
    guild_id = Column(String, ForeignKey(GuildConfig.guild_id, ondelete='CASCADE'), nullable=False, index=True)


class PendingConflict(Base):
    __tablename__ = 'pending_conflicts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey(GuildConfig.guild_id, ondelete='CASCADE'), nullable=False, index=True)
    conflict_data_json = Column(JsonVariant, nullable=False) # Changed
    status = Column(String, nullable=False, default='pending_gm_resolution', index=True)
    resolution_data_json = Column(JsonVariant, nullable=True) # Changed
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)


class StoryLog(Base):
    __tablename__ = 'story_logs'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey(GuildConfig.guild_id, ondelete='CASCADE'), nullable=False, index=True) # Changed to direct class attribute
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)

    location_id = Column(String, ForeignKey('locations.id'), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)

    entity_ids_json = Column(JsonVariant, nullable=True, comment='Stores IDs of entities involved, e.g., {"character_ids": [], "npc_ids": [], "item_ids": []}') # Changed
    details_json = Column(JsonVariant, nullable=True, comment='Stores detailed, structured information about the event') # Changed

    __table_args__ = (
        Index('idx_storylog_guild_timestamp', 'guild_id', 'timestamp'),
        Index('idx_storylog_guild_event_type', 'guild_id', 'event_type'),
    )

    def __repr__(self):
        return f"<StoryLog(id='{self.id}', guild_id='{self.guild_id}', type='{self.event_type}', ts='{self.timestamp}')>"
