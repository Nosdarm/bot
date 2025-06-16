from sqlalchemy import Column, Integer, String, BigInteger, UniqueConstraint, ForeignKey, Text # Import Text
from sqlalchemy.types import JSON # Import JSON type
from sqlalchemy.orm import relationship
from app.db import Base # Import Base from app/db.py

class GuildConfig(Base):
    __tablename__ = "guild_configs"

    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, unique=True, index=True, nullable=False) # Discord Guild ID

    master_channel_id = Column(BigInteger, nullable=True)
    system_channel_id = Column(BigInteger, nullable=True)
    notification_channel_id = Column(BigInteger, nullable=True)

    bot_language = Column(String(2), default="en", nullable=False) # e.g., "en", "ru"

    # Relationship to players (optional, but good for ORM features)
    # players = relationship("Player", back_populates="guild_config") # See Player model

    def __repr__(self):
        return f"<GuildConfig(guild_id={self.guild_id}, bot_language='{self.bot_language}')>"

class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)

    # Conceptually linked to GuildConfig.guild_id
    # Direct FK to GuildConfig.guild_id: Column(BigInteger, ForeignKey("guild_configs.guild_id"), nullable=False, index=True)
    # However, if GuildConfig might not exist when a player is first seen (e.g. DM context),
    # or if we want to decouple them slightly, we might not use a direct FK here immediately.
    # For now, storing guild_id directly. If strict FK is needed, ensure GuildConfig is created first.
    guild_id = Column(BigInteger, nullable=False, index=True)
    discord_id = Column(BigInteger, nullable=False, index=True) # Discord User ID

    selected_language = Column(String(2), default="en", nullable=False)

    # New fields for Player model
    current_location_id = Column(Integer, ForeignKey('locations.id'), nullable=True)
    xp = Column(Integer, default=0, nullable=False) # server_default will be handled in migration
    level = Column(Integer, default=1, nullable=False) # server_default will be handled in migration
    unspent_xp = Column(Integer, default=0, nullable=False) # server_default will be handled in migration
    gold = Column(Integer, default=0, nullable=False) # server_default will be handled in migration

    current_status = Column(Text, default='active', nullable=False) # server_default will be handled in migration

    collected_actions_json = Column(JSON, nullable=True, default={})
    current_party_id = Column(Integer, ForeignKey('parties.id', name='fk_player_party_id'), nullable=True) # Name for FK constraint

    # Unique constraint for a player (discord_id) within a specific guild (guild_id)
    __table_args__ = (UniqueConstraint('guild_id', 'discord_id', name='_guild_user_uc'),)

    # Example relationships (can be added later if fully implemented)
    # current_location = relationship("Location", foreign_keys=[current_location_id])
    # current_party = relationship("Party", foreign_keys=[current_party_id], back_populates="members") # if Party has 'members' relationship

    def __repr__(self):
        return f"<Player(id={self.id}, guild_id={self.guild_id}, discord_id={self.discord_id}, lang='{self.selected_language}', loc_id={self.current_location_id})>"

# Future models (like RuleConfig, WorldState, Character, Item etc.) would also be defined here.

class RuleConfig(Base):
    __tablename__ = "rule_configs"

    id = Column(Integer, primary_key=True, index=True)
    # unique=True on Column is standard for a unique constraint.
    # If a specific name is needed for the constraint, __table_args__ would be the place.
    guild_id = Column(BigInteger, unique=True, nullable=False, index=True)
    rules = Column(JSON, nullable=False, default={}) # Store rules as a JSON object

    # Example if a named unique constraint was absolutely required via __table_args__
    # __table_args__ = (UniqueConstraint('guild_id', name='uq_rule_configs_guild_id'),)
    # In this case, you might remove unique=True from the Column definition itself,
    # though some databases/SQLAlchemy versions handle the redundancy gracefully.
    # For now, unique=True on the column is cleaner and achieves the constraint.

    def __repr__(self):
        return f"<RuleConfig(guild_id={self.guild_id}, rules_count={len(self.rules) if self.rules else 0})>"


class WorldState(Base):
    __tablename__ = "world_states"

    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, unique=True, nullable=False, index=True) # Each guild has one WorldState
    state_data = Column(JSON, nullable=False, default={}) # Store state as a JSON object

    def __repr__(self):
        return f"<WorldState(guild_id={self.guild_id}, state_keys={len(self.state_data.keys()) if self.state_data else 0})>"


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    static_id = Column(Text, nullable=True, index=True) # Unique within a guild

    name_i18n = Column(JSON, nullable=False, default={}) # {"en": "Old Tavern", "ru": "Старая Таверна"}
    descriptions_i18n = Column(JSON, nullable=False, default={}) # {"en": "A dusty old tavern.", "ru": "Пыльная старая таверна."}

    type = Column(Text, nullable=True) # Example type: 'tavern', 'forest_path', 'city_square', 'dungeon_entrance'

    coordinates_json = Column(JSON, nullable=True, default=None) # {"x": 0, "y": 0, "map_id": "world"}

    neighbor_locations_json = Column(JSON, nullable=True, default={})

    generated_details_json = Column(JSON, nullable=True, default={}) # AI generated dynamic details
    ai_metadata_json = Column(JSON, nullable=True, default={}) # Hints for AI generation

    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_guild_static_id_uc'),)

    def __repr__(self):
        return f"<Location(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', name='{self.name_i18n.get('en', 'N/A') if self.name_i18n else 'N/A'}')>"


# Forward declaration for Party model if needed by Player, or ensure Party is defined before Player if relationships are complex.
# For now, Player.current_party_id is just an FK, so order isn't strictly critical unless using relationship() with back_populates.
# Let's define Party next.

class Party(Base):
    __tablename__ = "parties"

    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    name = Column(Text, nullable=False)

    leader_id = Column(Integer, ForeignKey('players.id', name='fk_party_leader_id'), nullable=False) # FK to Player.id

    player_ids_json = Column(JSON, nullable=False, default=[]) # List of Player.id (actual IDs, not discord_id)
    current_location_id = Column(Integer, ForeignKey('locations.id', name='fk_party_location_id'), nullable=True)

    turn_status = Column(Text, default='pending_actions', nullable=False) # server_default handled in migration

    # Example relationships (can be added later)
    # leader = relationship("Player", foreign_keys=[leader_id])
    # current_location = relationship("Location", foreign_keys=[current_location_id])
    # members = relationship("Player", secondary="association_table_player_party", back_populates="parties") # Requires many-to-many setup

    def __repr__(self):
        return f"<Party(id={self.id}, name='{self.name}', leader_id={self.leader_id}, players_count={len(self.player_ids_json) if self.player_ids_json else 0})>"
