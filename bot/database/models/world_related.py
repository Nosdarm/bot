from sqlalchemy import (
    Column, Integer, String, ForeignKey, Boolean, Text, # JSON removed
    PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID # JSONB removed
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any, List

from ..base import Base, JsonVariant # Import Base and JsonVariant

class Location(Base):
    __tablename__ = 'locations'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    static_id = Column(String, nullable=True, index=True)
    name_i18n = Column(JsonVariant, nullable=False) # Changed
    descriptions_i18n = Column(JsonVariant, nullable=False) # Changed
    type_i18n = Column(JsonVariant, nullable=False) # Changed
    coordinates = Column(JsonVariant, nullable=True) # Changed
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    neighbor_locations_json = Column(JsonVariant, nullable=True, comment="Stores a list of connection objects, e.g., [{'to_location_id': 'id1', 'path_description_i18n': {'en': 'a path'}, 'travel_time_hours': 1}]") # Changed
    inventory = Column(JsonVariant, nullable=True) # Changed
    npc_ids = Column(JsonVariant, nullable=True, default=lambda: []) # Changed
    event_triggers = Column(JsonVariant, nullable=True, default=lambda: []) # Changed
    template_id = Column(String, nullable=True)
    state_variables = Column(JsonVariant, nullable=True) # Changed
    is_active = Column(Boolean, default=True, nullable=False)
    details_i18n = Column(JsonVariant, nullable=True) # Changed
    tags_i18n = Column(JsonVariant, nullable=True) # Changed
    atmosphere_i18n = Column(JsonVariant, nullable=True) # Changed
    features_i18n = Column(JsonVariant, nullable=True) # Changed
    channel_id = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    ai_metadata_json = Column(JsonVariant, nullable=True, comment="Stores metadata for AI generation purposes") # Changed
    points_of_interest_json = Column(JsonVariant, nullable=True, comment="List of Points of Interest objects/dictionaries") # Changed
    on_enter_events_json = Column(JsonVariant, nullable=True, default=lambda: []) # Changed
    generated_details_json = Column(JsonVariant, nullable=True, comment="Additional AI-generated descriptive details for the location") # Changed

    __table_args__ = (
        UniqueConstraint('guild_id', 'static_id', name='uq_location_guild_static_id'),
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Location':
        if 'id' not in data or 'guild_id' not in data:
            raise ValueError("Location data must include 'id' and 'guild_id'.")

        i18n_fields = ['name_i18n', 'descriptions_i18n', 'details_i18n',
                       'tags_i18n', 'atmosphere_i18n', 'features_i18n']
        for field in i18n_fields:
            data.setdefault(field, {})

        json_fields_default_dict = ['inventory', 'state_variables',
                                    'neighbor_locations_json', 'ai_metadata_json',
                                    'npc_ids', 'event_triggers']
        for field in json_fields_default_dict:
            data.setdefault(field, {})

        data.setdefault('points_of_interest_json', [])
        data.setdefault('on_enter_events_json', [])

        if data.get('is_active') is None:
            data['is_active'] = True

        data.pop('exits', None)
        data.pop('static_connections', None)
        if 'static_name' in data and 'static_id' not in data:
            data['static_id'] = data.pop('static_name')

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "guild_id": self.guild_id, "template_id": self.template_id,
            "static_id": self.static_id, "name_i18n": self.name_i18n or {},
            "descriptions_i18n": self.descriptions_i18n or {}, "details_i18n": self.details_i18n or {},
            "tags_i18n": self.tags_i18n or {}, "atmosphere_i18n": self.atmosphere_i18n or {},
            "features_i18n": self.features_i18n or {},
            "neighbor_locations_json": self.neighbor_locations_json or {},
            "inventory": self.inventory or {},
            "state_variables": self.state_variables or {},
            "ai_metadata_json": self.ai_metadata_json or {},
            "is_active": self.is_active,
            "channel_id": self.channel_id,
            "image_url": self.image_url,
            "npc_ids": self.npc_ids or [],
            "event_triggers": self.event_triggers or [],
            "type_i18n": self.type_i18n or {},
            "coordinates": self.coordinates or {},
            "points_of_interest_json": self.points_of_interest_json or [],
            "on_enter_events_json": self.on_enter_events_json or []
        }


class GeneratedLocation(Base):
    __tablename__ = 'generated_locations'
    id = Column(String, primary_key=True)
    name_i18n = Column(JsonVariant, nullable=True) # Changed
    descriptions_i18n = Column(JsonVariant, nullable=True) # Changed
    details_i18n = Column(JsonVariant, nullable=True) # Changed
    tags_i18n = Column(JsonVariant, nullable=True) # Changed
    atmosphere_i18n = Column(JsonVariant, nullable=True) # Changed
    features_i18n = Column(JsonVariant, nullable=True) # Changed
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_generatedlocation_guild_id', 'guild_id'),)


class LocationTemplate(Base):
    __tablename__ = 'location_templates'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description_i18n = Column(JsonVariant, nullable=True) # Changed
    properties = Column(JsonVariant, nullable=True) # Changed
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)


class MobileGroup(Base):
    __tablename__ = 'mobile_groups'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JsonVariant, nullable=False) # Changed
    description_i18n = Column(JsonVariant, nullable=True) # Changed
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    member_ids = Column(JsonVariant, nullable=True) # Changed
    destination_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    state_variables = Column(JsonVariant, nullable=True) # Changed
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    current_location = relationship("Location", foreign_keys=[current_location_id])
    destination_location = relationship("Location", foreign_keys=[destination_location_id])

    __table_args__ = (
        Index('idx_mobilegroup_guild_id', 'guild_id'),
        Index('idx_mobilegroup_is_active', 'is_active'),
    )

    def __repr__(self):
        return f"<MobileGroup(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}')>"


class WorldState(Base):
    __tablename__ = 'world_states'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    global_narrative_state_i18n = Column(JsonVariant, nullable=True) # Changed
    current_era_i18n = Column(JsonVariant, nullable=True) # Changed
    custom_flags = Column(JsonVariant, nullable=True) # Changed

    guild = relationship("GuildConfig")

    def __repr__(self):
        return f"<WorldState(id='{self.id}', guild_id='{self.guild_id}')>"


class GeneratedFaction(Base):
    __tablename__ = 'generated_factions'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JsonVariant, nullable=False) # Changed
    ideology_i18n = Column(JsonVariant, nullable=True) # Changed
    description_i18n = Column(JsonVariant, nullable=True) # Changed
    leader_concept_i18n = Column(JsonVariant, nullable=True) # Changed
    resource_notes_i18n = Column(JsonVariant, nullable=True) # Changed
    ai_metadata_json = Column(JsonVariant, nullable=True, comment="Stores metadata from AI generation, like prompt details or model version") # Changed

    __table_args__ = (Index('idx_generatedfaction_guild_id', 'guild_id'),)

    def __repr__(self):
        name_en = self.name_i18n.get('en', 'Unknown Faction') if isinstance(self.name_i18n, dict) else 'Unknown Faction'
        return f"<GeneratedFaction(id='{self.id}', name_en='{name_en}', guild_id='{self.guild_id}')>"
