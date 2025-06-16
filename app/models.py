from sqlalchemy import Column, Integer, String, BigInteger, UniqueConstraint, ForeignKey
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

    # Unique constraint for a player (discord_id) within a specific guild (guild_id)
    __table_args__ = (UniqueConstraint('guild_id', 'discord_id', name='_guild_user_uc'),)

    # Relationship to GuildConfig (optional)
    # If using a direct FK:
    # guild_config = relationship("GuildConfig", back_populates="players", foreign_keys=[guild_id], primaryjoin="Player.guild_id == GuildConfig.guild_id")


    def __repr__(self):
        return f"<Player(guild_id={self.guild_id}, discord_id={self.discord_id}, language='{self.selected_language}')>"

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
