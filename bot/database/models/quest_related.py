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

class QuestTable(Base):
    __tablename__ = 'quests'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    status = Column(String, default='available', nullable=False)
    influence_level = Column(String, default='local', nullable=True)
    prerequisites_json_str = Column(Text, nullable=True)
    connections_json = Column(JSONB, nullable=True)
    rewards_json_str = Column(Text, nullable=True)
    npc_involvement_json = Column(JSONB, nullable=True)
    consequences_json_str = Column(Text, nullable=True)
    quest_giver_details_i18n = Column(JSONB, nullable=True)
    consequences_summary_i18n = Column(JSONB, nullable=True)
    ai_prompt_context_json_str = Column(Text, nullable=True)
    is_ai_generated = Column(Boolean, default=False, nullable=False)
    __table_args__ = (Index('idx_quests_guild_id', 'guild_id'),)


class GeneratedQuest(Base):
    __tablename__ = 'generated_quests'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    status = Column(String, default='available', nullable=True)
    suggested_level = Column(Integer, nullable=True)
    rewards_json = Column(Text, nullable=True)
    prerequisites_json = Column(Text, nullable=True)
    consequences_json = Column(Text, nullable=True)
    quest_giver_npc_id = Column(String, nullable=True)
    ai_prompt_context_json = Column(Text, nullable=True)
    quest_giver_details_i18n = Column(JSONB, nullable=True)
    consequences_summary_i18n = Column(JSONB, nullable=True)

    steps = relationship("QuestStepTable", back_populates="quest", cascade="all, delete-orphan")

    __table_args__ = (Index('idx_generatedquest_guild_id', 'guild_id'),)


class Questline(Base):
    __tablename__ = 'questlines'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=True)
    __table_args__ = (Index('idx_questline_guild_id', 'guild_id'),)


class QuestStepTable(Base):
    __tablename__ = 'quest_steps'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    quest_id = Column(String, ForeignKey('generated_quests.id', ondelete='CASCADE'), nullable=False, index=True)

    quest = relationship("GeneratedQuest", back_populates="steps")

    title_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    requirements_i18n = Column(JSONB, nullable=True)

    required_mechanics_json = Column(JSONB, default=lambda: {}, nullable=False)
    abstract_goal_json = Column(JSONB, default=lambda: {}, nullable=False)
    conditions_json = Column(JSONB, default=lambda: {}, nullable=False)
    consequences_json = Column(JSONB, default=lambda: {}, nullable=False)

    step_order = Column(Integer, default=0, nullable=False)
    status = Column(String, default='pending', nullable=False)

    assignee_type = Column(String, nullable=True)
    assignee_id = Column(String, nullable=True)

    linked_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    linked_npc_id = Column(String, ForeignKey('npcs.id'), nullable=True)
    linked_item_id = Column(String, ForeignKey('items.id'), nullable=True)
    linked_guild_event_id = Column(String, ForeignKey('events.id'), nullable=True)

    __table_args__ = (
        Index('idx_queststep_guild_quest', 'guild_id', 'quest_id'),
    )
