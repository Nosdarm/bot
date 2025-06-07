from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean, Text, PrimaryKeyConstraint, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class Player(Base):
    __tablename__ = 'players'

    id = Column(String, primary_key=True)
    discord_id = Column(Integer, nullable=True)
    name = Column(String) # Assuming String for now, can be changed to JSON if needed
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    selected_language = Column(String, nullable=True)
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    unspent_xp = Column(Integer, default=0)
    gold = Column(Integer, default=0)
    current_game_status = Column(String, nullable=True)
    collected_actions_json = Column(JSON, nullable=True)
    current_party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    guild_id = Column(String, nullable=False)
    stats = Column(JSON, nullable=True)
    current_action = Column(String, nullable=True)
    action_queue = Column(JSON, nullable=True)
    state_variables = Column(JSON, nullable=True)
    hp = Column(Integer, nullable=True)
    max_health = Column(Integer, nullable=True)
    is_alive = Column(Boolean, default=True)
    status_effects = Column(JSON, nullable=True)
    race = Column(String, nullable=True)
    mp = Column(Integer, nullable=True)
    attack = Column(Integer, nullable=True)
    defense = Column(Integer, nullable=True)
    skills_data_json = Column(JSON, nullable=True)
    abilities_data_json = Column(JSON, nullable=True)
    spells_data_json = Column(JSON, nullable=True)
    character_class = Column(String, nullable=True)
    flags_json = Column(JSON, nullable=True)
    active_quests = Column(JSON, nullable=True)
    known_spells = Column(JSON, nullable=True)
    spell_cooldowns = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True) # Added

    location = relationship("Location")
    party = relationship("Party", foreign_keys=[current_party_id]) # Specify foreign_keys for clarity

class Location(Base):
    __tablename__ = 'locations'

    id = Column(String, primary_key=True)
    static_name = Column(String, nullable=True)
    descriptions_i18n = Column(JSON, nullable=True)
    static_connections = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    exits = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True)
    # Added columns:
    name_i18n = Column(JSON, nullable=True)
    template_id = Column(String, nullable=True)
    state_variables = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False) # Added


class Timer(Base):
    __tablename__ = 'timers'

    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False) # Type of timer, e.g., 'event_stage_transition'
    ends_at = Column(Float, nullable=False) # Game time when the timer should trigger
    callback_data = Column(JSON, nullable=True) # Data needed by the callback
    is_active = Column(Boolean, default=True, nullable=False)
    # Optional: Add created_at/updated_at timestamps if desired for auditing
    # created_at = Column(DateTime, default=datetime.utcnow)
    # updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Timer(id='{self.id}', type='{self.type}', ends_at={self.ends_at}, active={self.is_active}, guild_id='{self.guild_id}')>"

# WorldState is replaced by GlobalState as per analysis of traceback
# class WorldState(Base):
#    __tablename__ = 'world_state'
#
#    key = Column(String, primary_key=True)
#    value = Column(Text, nullable=True) # Changed to Text for flexibility

class Event(Base):
    __tablename__ = 'events'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    channel_id = Column(String, nullable=True)
    current_stage_id = Column(String, nullable=True)
    players = Column(JSON, nullable=True) # Store as JSON list of player IDs
    state_variables = Column(JSON, nullable=True)
    stages_data = Column(JSON, nullable=True)
    end_message_template = Column(Text, nullable=True)
    guild_id = Column(String, nullable=False)

class Party(Base):
    __tablename__ = 'parties'

    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=True)
    player_ids = Column(JSON, nullable=True) # List of Player IDs
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    turn_status = Column(String, nullable=True)
    guild_id = Column(String, nullable=False)
    leader_id = Column(String, ForeignKey('players.id'), nullable=True)
    state_variables = Column(JSON, nullable=True)
    current_action = Column(String, nullable=True)

    location = relationship("Location")
    leader = relationship("Player", foreign_keys=[leader_id])

class RulesConfig(Base):
    __tablename__ = 'rules_config'

    id = Column(String, primary_key=True, default='main_config')
    config_data = Column(JSON)

# Stub Tables
class GeneratedLocation(Base):
    __tablename__ = 'generated_locations'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class ItemTemplate(Base):
    __tablename__ = 'item_templates'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=True) # e.g., weapon, armor, potion
    properties = Column(JSON, nullable=True) # For stats, effects, etc.
    guild_id = Column(String, nullable=True) # If templates can be guild-specific

class LocationTemplate(Base):
    __tablename__ = 'location_templates'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    properties = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False) # Or nullable if global templates

class NPC(Base): # Renamed from Npc to NPC for convention
    __tablename__ = 'npcs'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True) # Could be FK to an NpcTemplate table if one exists
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    backstory_i18n = Column(JSON, nullable=True)
    persona_i18n = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    stats = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True) # List of item IDs or more complex objects
    current_action = Column(String, nullable=True)
    action_queue = Column(JSON, nullable=True)
    party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    state_variables = Column(JSON, nullable=True)
    health = Column(Integer, nullable=True)
    max_health = Column(Integer, nullable=True)
    is_alive = Column(Boolean, default=True)
    status_effects = Column(JSON, nullable=True)
    is_temporary = Column(Boolean, default=False)
    archetype = Column(String, nullable=True)
    traits = Column(JSON, nullable=True)
    desires = Column(JSON, nullable=True)
    motives = Column(JSON, nullable=True)

    location = relationship("Location")
    party = relationship("Party")

class GeneratedNpc(Base):
    __tablename__ = 'generated_npcs'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class GeneratedFaction(Base):
    __tablename__ = 'generated_factions'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class GeneratedQuest(Base):
    __tablename__ = 'generated_quests'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Item(Base):
    __tablename__ = 'items'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True) # FK to an ItemTemplate table
    guild_id = Column(String, nullable=True) # Nullable if items can be global
    owner_id = Column(String, nullable=True) # Player, NPC, Location ID
    owner_type = Column(String, nullable=True) # "player", "npc", "location"
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    quantity = Column(Integer, default=1) # If items are stackable and not unique instances
    state_variables = Column(JSON, nullable=True)
    is_temporary = Column(Boolean, default=False)
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    properties = Column(JSON, nullable=True)
    slot = Column(String, nullable=True)
    value = Column(Integer, nullable=True)

class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(String, primary_key=True) # This might need to be a composite key or have a separate PK
    player_id = Column(String, ForeignKey('players.id'), nullable=False)
    item_id = Column(String, ForeignKey('items.id'), nullable=False)
    quantity = Column(Integer, default=1)

    player = relationship("Player")
    item = relationship("Item")

class Combat(Base):
    __tablename__ = 'combats'
    id = Column(String, primary_key=True) # Usually UUID
    guild_id = Column(String, nullable=False)
    location_id = Column(String, ForeignKey('locations.id'), nullable=False)
    is_active = Column(Boolean, default=True)
    participants = Column(JSON, nullable=True) # List of player/NPC IDs and their teams
    current_round = Column(Integer, default=0)
    combat_log = Column(Text, nullable=True) # Or JSON for structured logs
    state_variables = Column(JSON, nullable=True)
    channel_id = Column(String, nullable=True) # Discord channel ID
    event_id = Column(String, ForeignKey('events.id'), nullable=True) # Associated event
    turn_order = Column(JSON, nullable=True) # List of participant IDs in order
    current_turn_index = Column(Integer, default=0)

    location = relationship("Location")
    event = relationship("Event")

class GlobalState(Base): # Was WorldState, but table name from error is global_state
    __tablename__ = 'global_state'
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)

class Log(Base): # Renamed from logs to avoid conflict with math.log if imported
    __tablename__ = 'logs'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Relationship(Base):
    __tablename__ = 'relationships'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class PlayerNpcMemory(Base):
    __tablename__ = 'player_npc_memory'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Ability(Base):
    __tablename__ = 'abilities'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Skill(Base):
    __tablename__ = 'skills'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Status(Base):
    __tablename__ = 'statuses'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False) # "player", "npc"
    duration_turns = Column(Integer, nullable=True)
    applied_at = Column(Integer, nullable=True) # Changed from applied_at_time
    source_id = Column(String, nullable=True)
    state_variables = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    effects = Column(JSON, nullable=True)

class CraftingQueue(Base):
    __tablename__ = 'crafting_queues'
    entity_id = Column(String, nullable=False) # Player or NPC ID
    entity_type = Column(String, nullable=False) # "player" or "npc"
    guild_id = Column(String, nullable=False)
    queue = Column(JSON, nullable=True) # List of crafting task objects
    state_variables = Column(JSON, nullable=True)

    __table_args__ = (PrimaryKeyConstraint('entity_id', 'entity_type', 'guild_id'),)

class ItemProperty(Base):
    __tablename__ = 'item_properties'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Questline(Base):
    __tablename__ = 'questlines'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class QuestStep(Base):
    __tablename__ = 'quest_steps'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class MobileGroup(Base):
    __tablename__ = 'mobile_groups'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)
