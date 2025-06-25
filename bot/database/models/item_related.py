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

class ItemTemplate(Base):
    __tablename__ = 'item_templates'
    id = Column(String, primary_key=True)
    name_i18n = Column(JsonVariant, nullable=False)
    description_i18n = Column(JsonVariant, nullable=True)
    type = Column(String, nullable=True)
    properties = Column(JsonVariant, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_itemtemplate_guild_id', 'guild_id'),)


class Item(Base):
    __tablename__ = 'items'
    id = Column(String, primary_key=True)
    template_id = Column(String, ForeignKey('item_templates.id'), nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    owner_id = Column(String, nullable=True)
    owner_type = Column(String, nullable=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    quantity = Column(Integer, default=1)
    state_variables = Column(JsonVariant, nullable=True)
    is_temporary = Column(Boolean, default=False)
    name_i18n = Column(JsonVariant, nullable=True)
    description_i18n = Column(JsonVariant, nullable=True)
    properties = Column(JsonVariant, nullable=True)
    slot = Column(String, nullable=True)
    value = Column(Integer, nullable=True)
    __table_args__ = (Index('idx_item_guild_id', 'guild_id'),)


class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id = Column(String, ForeignKey('players.id', ondelete='CASCADE'), nullable=False, index=True)
    item_id = Column(String, ForeignKey('items.id', ondelete='CASCADE'), nullable=False, index=True)
    quantity = Column(Integer, default=1)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    player = relationship("Player")
    item = relationship("Item")

    __table_args__ = (
        UniqueConstraint('player_id', 'item_id', name='uq_player_item_inventory'),
        Index('idx_inventory_guild_player', 'guild_id', 'player_id')
    )


class ItemProperty(Base):
    __tablename__ = 'item_properties'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JsonVariant, nullable=True)
    description_i18n = Column(JsonVariant, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_itemproperty_guild_id', 'guild_id'),)


class NewItem(Base):
    __tablename__ = 'new_items'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False) # Removed unique=True, will be unique with guild_id
    description = Column(String, nullable=True)
    item_type = Column(String, nullable=False)
    item_metadata = Column(JsonVariant, name="metadata", nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True) # ADDED guild_id
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # guild_config = relationship("GuildConfig") # ADDED relationship - If needed explicitly

    __table_args__ = (
        UniqueConstraint('guild_id', 'name', name='uq_new_item_guild_name'), # ADDED unique constraint for guild_id and name
        Index('idx_newitem_guild_id', 'guild_id'), # ADDED index for guild_id
    )

    def __repr__(self):
        return f"<NewItem(id={self.id}, name='{self.name}', item_type='{self.item_type}', guild_id='{self.guild_id}')>"


class NewCharacterItem(Base):
    __tablename__ = 'new_character_items'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_id = Column(String, ForeignKey('characters.id', ondelete='CASCADE'), nullable=False, index=True) # Corrected FK ondelete
    item_id = Column(UUID(as_uuid=True), ForeignKey('new_items.id', ondelete='CASCADE'), nullable=False, index=True) # Corrected FK ondelete
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True) # ADDED guild_id
    quantity = Column(Integer, default=1, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    item = relationship("NewItem")
    # character = relationship("Character") # If needed
    # guild_config = relationship("GuildConfig") # If needed

    __table_args__ = (
        CheckConstraint('quantity > 0', name='check_new_char_item_quantity_positive'),
        Index('idx_newcharitem_guild_char_item', 'guild_id', 'character_id', 'item_id'), # ADDED index
    )

    def __repr__(self):
        return f"<NewCharacterItem(id={self.id}, character_id='{self.character_id}', item_id='{self.item_id}', quantity={self.quantity}, guild_id='{self.guild_id}')>"


class Shop(Base):
    __tablename__ = 'shops'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True) # ADDED FK
    name_i18n = Column(JsonVariant, nullable=False)
    description_i18n = Column(JsonVariant, nullable=True)
    type_i18n = Column(JsonVariant, nullable=True)
    inventory = Column(JsonVariant, nullable=True)
    owner_id = Column(String, ForeignKey('npcs.id', ondelete='SET NULL'), nullable=True) # ADDED ondelete
    location_id = Column(String, ForeignKey('locations.id', ondelete='SET NULL'), nullable=True) # ADDED ondelete
    economic_parameters_override = Column(JsonVariant, nullable=True)

    owner = relationship("NPC")
    location = relationship("Location")

    __table_args__ = (
        Index('idx_shop_guild_id', 'guild_id'),
    )

    def __repr__(self):
        return f"<Shop(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}')>"


class Currency(Base):
    __tablename__ = 'currencies'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True) # ADDED FK
    name_i18n = Column(JsonVariant, nullable=False)
    symbol_i18n = Column(JsonVariant, nullable=True)
    exchange_rate_to_standard = Column(Float, nullable=False, default=1.0)
    is_default = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index('idx_currency_guild_id', 'guild_id'), # Index already exists, FK ensures integrity
    )

    def __repr__(self):
        return f"<Currency(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}', is_default={self.is_default})>"
