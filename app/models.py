from sqlalchemy import Column, Integer, String, BigInteger, UniqueConstraint, ForeignKey, Text, DateTime, func # Import Text, DateTime, func
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


class GeneratedNpc(Base):
    __tablename__ = "generated_npcs"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    location_id = Column(Integer, ForeignKey('locations.id', name='fk_npc_location_id'), nullable=True, index=True)
    static_id = Column(Text, nullable=True, index=True)

    name_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration
    description_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    npc_type = Column(Text, nullable=True) # Added npc_type
    dialogue_greeting_i18n = Column(JSON, nullable=True, default={}) # Added dialogue_greeting_i18n, server_default handled in migration
    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_npc_guild_static_id_uc'),)

    def __repr__(self):
        return f"<GeneratedNpc(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', name='{self.name_i18n.get('en', 'N/A') if self.name_i18n else 'N/A'}')>"


class GeneratedFaction(Base):
    __tablename__ = "generated_factions"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    static_id = Column(Text, nullable=True, index=True)

    name_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration
    description_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    ideology_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_faction_guild_static_id_uc'),)

    def __repr__(self):
        return f"<GeneratedFaction(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', name='{self.name_i18n.get('en', 'N/A') if self.name_i18n else 'N/A'}')>"

class GeneratedQuest(Base):
    __tablename__ = "generated_quests"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    static_id = Column(Text, nullable=True, index=True)

    title_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration
    description_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration

    questline_id = Column(Integer, ForeignKey('questlines.id', name='fk_quest_questline_id'), nullable=True, index=True)
    assigning_npc_id = Column(Integer, ForeignKey('generated_npcs.id', name='fk_quest_npc_id'), nullable=True, index=True)
    required_level = Column(Integer, nullable=True, default=1) # server_default handled in migration
    template_status = Column(Text, nullable=False, default='draft') # server_default handled in migration

    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_quest_guild_static_id_uc'),)

    def __repr__(self):
        return f"<GeneratedQuest(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', title='{self.title_i18n.get('en', 'N/A') if self.title_i18n else 'N/A'}')>"

class ItemProperty(Base):
    __tablename__ = "item_properties"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    property_name_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration

    def __repr__(self):
        return f"<ItemProperty(id={self.id}, guild_id={self.guild_id}, name='{self.property_name_i18n.get('en', 'N/A') if self.property_name_i18n else 'N/A'}')>"


class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    static_id = Column(Text, nullable=True, index=True)

    name_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration
    description_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    item_type_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    properties_json = Column(JSON, nullable=True, default={}) # server_default handled in migration
    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_item_guild_static_id_uc'),)

    def __repr__(self):
        return f"<Item(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', name='{self.name_i18n.get('en', 'N/A') if self.name_i18n else 'N/A'}')>"

class Inventory(Base):
    __tablename__ = "inventories"
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey('players.id', name='fk_inventory_player_id'), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey('items.id', name='fk_inventory_item_id'), nullable=False, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False) # server_default handled in migration

    def __repr__(self):
        return f"<Inventory(id={self.id}, player_id={self.player_id}, item_id={self.item_id}, quantity={self.quantity})>"

class PlayerNpcMemory(Base):
    __tablename__ = "player_npc_memories"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    npc_id = Column(Integer, ForeignKey('generated_npcs.id', name='fk_memory_npc_id'), nullable=False, index=True)
    player_or_party_id = Column(BigInteger, nullable=False, index=True)
    entity_type = Column(Text, nullable=False) # "player" or "party"
    memory_details_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration

    def __repr__(self):
        return f"<PlayerNpcMemory(id={self.id}, npc_id={self.npc_id}, entity_id={self.player_or_party_id}, type='{self.entity_type}')>"

class Ability(Base):
    __tablename__ = "abilities"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    static_id = Column(Text, nullable=True, index=True)

    name_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration
    description_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_ability_guild_static_id_uc'),)

    def __repr__(self):
        return f"<Ability(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', name='{self.name_i18n.get('en', 'N/A') if self.name_i18n else 'N/A'}')>"

class StatusEffect(Base):
    __tablename__ = "status_effects"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    static_id = Column(Text, nullable=True, index=True)

    name_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration
    description_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_status_effect_guild_static_id_uc'),)

    def __repr__(self):
        return f"<StatusEffect(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', name='{self.name_i18n.get('en', 'N/A') if self.name_i18n else 'N/A'}')>"

class Questline(Base):
    __tablename__ = "questlines"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    static_id = Column(Text, nullable=True, index=True)

    name_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration
    description_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    starting_quest_static_id = Column(Text, nullable=True) # AI can suggest a static_id of a quest

    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_questline_guild_static_id_uc'),)

    def __repr__(self):
        return f"<Questline(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', name='{self.name_i18n.get('en', 'N/A') if self.name_i18n else 'N/A'}')>"

class QuestStep(Base):
    __tablename__ = "quest_steps"
    id = Column(Integer, primary_key=True, index=True)
    quest_id = Column(Integer, ForeignKey('generated_quests.id', name='fk_queststep_quest_id'), nullable=False, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)

    step_order = Column(Integer, nullable=False, default=1) # server_default handled in migration
    description_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration

    goal_summary_i18n = Column(JSON, nullable=True, default={}) # server_default handled in migration
    required_mechanics_placeholder_json = Column(JSON, nullable=True, default={}) # server_default handled in migration
    consequences_placeholder_json = Column(JSON, nullable=True, default={}) # server_default handled in migration

    __table_args__ = (UniqueConstraint('quest_id', 'step_order', name='_quest_step_order_uc'),)

    def __repr__(self):
        return f"<QuestStep(id={self.id}, quest_id={self.quest_id}, order={self.step_order})>"

class MobileGroup(Base):
    __tablename__ = "mobile_groups"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    name_i18n = Column(JSON, nullable=False, default={}) # server_default handled in migration
    current_location_id = Column(Integer, ForeignKey('locations.id', name='fk_mobilegroup_location_id'), nullable=True, index=True)

    def __repr__(self):
        return f"<MobileGroup(id={self.id}, guild_id={self.guild_id}, name='{self.name_i18n.get('en', 'N/A') if self.name_i18n else 'N/A'}')>"

class CraftingRecipe(Base):
    __tablename__ = "crafting_recipes"
    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)
    static_id = Column(Text, nullable=True, index=True)

    result_item_id = Column(Integer, ForeignKey('items.id', name='fk_recipe_item_id'), nullable=False)
    ingredients_json = Column(JSON, nullable=False, default=[]) # server_default handled in migration
    __table_args__ = (UniqueConstraint('guild_id', 'static_id', name='_crafting_recipe_guild_static_id_uc'),)

    def __repr__(self):
        return f"<CraftingRecipe(id={self.id}, guild_id={self.guild_id}, static_id='{self.static_id}', result_item_id={self.result_item_id})>"


class PendingGeneration(Base):
    __tablename__ = "pending_generations"

    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(BigInteger, nullable=False, index=True)

    generation_type = Column(Text, nullable=False) # e.g., "npc_for_location", "location_detail"

    context_json = Column(JSON, nullable=False, default={}) # server_default handled in migration

    raw_ai_prompt = Column(Text, nullable=True)
    raw_ai_response = Column(Text, nullable=True)

    parsed_data_json = Column(JSON, nullable=True)

    validation_errors_json = Column(JSON, nullable=True)
    validation_warnings_json = Column(JSON, nullable=True)

    status = Column(Text, nullable=False, index=True, default='pending_api_call') # server_default handled in migration

    requested_by_discord_id = Column(BigInteger, nullable=True)

    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<PendingGeneration(id={self.id}, guild_id={self.guild_id}, type='{self.generation_type}', status='{self.status}')>"
