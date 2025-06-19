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

class Combat(Base):
    __tablename__ = 'combats'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True)
    participants = Column(JSONB, nullable=False, default=lambda: [])
    initial_positions = Column(JSONB, nullable=True)
    current_round = Column(Integer, default=0)
    combat_log = Column(Text, nullable=True)
    turn_log_structured = Column(JSONB, nullable=True, default=lambda: [])
    state_variables = Column(JSONB, nullable=True)
    combat_rules_snapshot = Column(JSONB, nullable=True)
    channel_id = Column(String, nullable=True)
    event_id = Column(String, ForeignKey('events.id'), nullable=True)
    turn_order = Column(JSON, nullable=True)
    current_turn_index = Column(Integer, default=0)
    location = relationship("Location")
    event = relationship("Event")


class Ability(Base):
    __tablename__ = 'abilities'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JSONB, nullable=False)
    description_i18n = Column(JSONB, nullable=False)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    effect_i18n = Column(JSONB, nullable=False)
    cost = Column(JSONB, nullable=True)
    requirements = Column(JSONB, nullable=True)
    type_i18n = Column(JSONB, nullable=False)
    __table_args__ = (Index('idx_ability_guild_id', 'guild_id'),)


class Spell(Base):
    __tablename__ = 'spells'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JSONB, nullable=False)
    description_i18n = Column(JSONB, nullable=False)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    effect_i18n = Column(JSONB, nullable=False)
    cost = Column(JSONB, nullable=True)
    requirements = Column(JSONB, nullable=True)
    type_i18n = Column(JSONB, nullable=False)  # e.g., school of magic
    __table_args__ = (Index('idx_spell_guild_id', 'guild_id'),)


class Skill(Base):
    __tablename__ = 'skills'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_skill_guild_id', 'guild_id'),)


class Status(Base):
    __tablename__ = 'statuses'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    status_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    duration_turns = Column(Float, nullable=True)
    applied_at = Column(Float, nullable=True)
    source_id = Column(String, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    effects = Column(JSONB, nullable=True)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)


class CraftingRecipe(Base):
    __tablename__ = 'crafting_recipes'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    name_i18n = Column(JSONB, nullable=False)
    description_i18n = Column(JSONB, nullable=True)

    ingredients_json = Column(JSONB, nullable=False, default=lambda: [])

    output_item_template_id = Column(String, ForeignKey('item_templates.id'), nullable=False)
    output_quantity = Column(Integer, default=1, nullable=False)

    required_skill_id = Column(String, ForeignKey('skills.id'), nullable=True)
    required_skill_level = Column(Integer, nullable=True)

    other_requirements_json = Column(JSONB, nullable=True, default=lambda: {})
    ai_metadata_json = Column(JSONB, nullable=True, default=lambda: {})

    __table_args__ = (
        Index('idx_craftingrecipe_guild_output_item', 'guild_id', 'output_item_template_id'),
        Index('idx_craftingrecipe_guild_skill', 'guild_id', 'required_skill_id'),
    )

    def __repr__(self):
        name_en = self.name_i18n.get('en', 'Unnamed Recipe') if isinstance(self.name_i18n, dict) else 'Unnamed Recipe (i18n error)'
        return f"<CraftingRecipe(id='{self.id}', name_en='{name_en}', guild_id='{self.guild_id}')>"


class CraftingQueue(Base):
    __tablename__ = 'crafting_queues'
    entity_id = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    queue = Column(JSONB, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    __table_args__ = (PrimaryKeyConstraint('entity_id', 'entity_type', 'guild_id'),)


class Relationship(Base):
    __tablename__ = 'relationships'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    # Entity 1
    entity1_type = Column(String, nullable=False, index=True) # E.g., "CHARACTER", "NPC", "FACTION", "PARTY"
    entity1_id = Column(String, nullable=False, index=True)   # ID of the first entity

    # Entity 2
    entity2_type = Column(String, nullable=False, index=True) # E.g., "CHARACTER", "NPC", "FACTION", "PARTY"
    entity2_id = Column(String, nullable=False, index=True)   # ID of the second entity

    # Relationship details
    type = Column(String, nullable=False, index=True) # E.g., "personal_disposition", "faction_standing", "familial_bond"
                                                      # This describes the single relationship allowed by the unique constraint below.
    value = Column(Integer, nullable=False, default=0) # Numerical value (e.g., -100 to 100 for disposition)

    # Optional: Link to a StoryLog entry that caused or last significantly modified this relationship
    source_log_id = Column(String, ForeignKey('story_logs.id', ondelete='SET NULL'), nullable=True, index=True)

    # Optional: For storing more nuanced details about the relationship if 'value' and 'type' aren't enough
    details_json = Column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint('guild_id', 'entity1_type', 'entity1_id', 'entity2_type', 'entity2_id', name='uq_relationship_between_entities'),
        Index('idx_relationship_guild_entity1', 'guild_id', 'entity1_type', 'entity1_id'),
        Index('idx_relationship_guild_entity2', 'guild_id', 'entity2_type', 'entity2_id'),
        # Index on type can be useful for querying all relationships of a certain type
        Index('idx_relationship_guild_type', 'guild_id', 'type'),
    )

    def __repr__(self):
        return f"<Relationship(id='{self.id}', guild='{self.guild_id}', {self.entity1_type}:{self.entity1_id} <-> {self.entity2_type}:{self.entity2_id}, type='{self.type}', val={self.value})>"
