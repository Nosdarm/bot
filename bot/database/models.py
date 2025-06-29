from sqlalchemy import create_engine, Column, BigInteger, String, Integer, JSON, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class GuildConfig(Base):
    __tablename__ = 'guild_configs'

    id = Column(BigInteger, primary_key=True)
    master_channel_id = Column(BigInteger)
    system_channel_id = Column(BigInteger)
    notification_channel_id = Column(BigInteger)
    main_language = Column(String)

class Player(Base):
    __tablename__ = 'players'

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    discord_id = Column(BigInteger, index=True)
    name = Column(String)
    stats_json = Column(JSON)
    current_location_id = Column(Integer, ForeignKey('locations.id'))
    selected_language = Column(String)
    xp = Column(Integer)
    level = Column(Integer)
    unspent_xp = Column(Integer)
    gold = Column(Integer)
    current_status = Column(String)
    collected_actions_json = Column(JSON)
    current_party_id = Column(Integer, ForeignKey('parties.id'), nullable=True)

    __table_args__ = (UniqueConstraint('guild_id', 'discord_id', name='_guild_discord_uc'),)

    guild = relationship("GuildConfig")
    location = relationship("Location")
    party = relationship("Party")

class Location(Base):
    __tablename__ = 'locations'

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    static_id = Column(String, index=True)
    name_i18n = Column(JSON)
    descriptions_i18n = Column(JSON)
    type = Column(String)
    coordinates_json = Column(JSON)
    neighbor_locations_json = Column(JSON)
    generated_details_json = Column(JSON)
    ai_metadata_json = Column(JSON)
    channel_id = Column(BigInteger)

    guild = relationship("GuildConfig")

class Party(Base):
    __tablename__ = 'parties'

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    name = Column(String)
    player_ids_json = Column(JSON)
    current_location_id = Column(Integer, ForeignKey('locations.id'))
    turn_status = Column(String)

    guild = relationship("GuildConfig")
    location = relationship("Location")

class StoryLog(Base):
    __tablename__ = 'story_logs'

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    timestamp = Column(DateTime)
    location_id = Column(Integer, ForeignKey('locations.id'), nullable=True)
    event_type = Column(String)
    entity_ids_json = Column(JSON)
    details_json = Column(JSON)

    guild = relationship("GuildConfig")
    location = relationship("Location")

class GeneratedNpc(Base):
    __tablename__ = 'generated_npcs'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    faction_id = Column(Integer, ForeignKey('generated_factions.id'), nullable=True)
    inventory_id = Column(Integer, ForeignKey('inventories.id'), nullable=True)
    stats_json = Column(JSON)
    abilities_json = Column(JSON)
    skills_json = Column(JSON)
    current_location_id = Column(Integer, ForeignKey('locations.id'))
    home_location_id = Column(Integer, ForeignKey('locations.id'))
    ai_metadata_json = Column(JSON)

class GeneratedFaction(Base):
    __tablename__ = 'generated_factions'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    ideology_i18n = Column(JSON)
    resources_json = Column(JSON)
    leader_npc_id = Column(Integer, ForeignKey('generated_npcs.id'), nullable=True)
    ai_metadata_json = Column(JSON)

class GeneratedQuest(Base):
    __tablename__ = 'generated_quests'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    questline_id = Column(Integer, ForeignKey('questlines.id'), nullable=True)
    required_level = Column(Integer)
    rewards_json = Column(JSON)
    prerequisites_json = Column(JSON)
    ai_metadata_json = Column(JSON)

class Item(Base):
    __tablename__ = 'items'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    item_property_id = Column(Integer, ForeignKey('item_properties.id'))
    base_value = Column(Integer)
    category = Column(String)

class Inventory(Base):
    __tablename__ = 'inventories'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    entity_id = Column(Integer)
    entity_type = Column(String)
    items_json = Column(JSON)

class Relationship(Base):
    __tablename__ = 'relationships'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    entity1_type = Column(String)
    entity1_id = Column(Integer)
    entity2_type = Column(String)
    entity2_id = Column(Integer)
    type = Column(String)
    value = Column(Integer)
    source_log_id = Column(Integer, ForeignKey('story_logs.id'), nullable=True)

class PlayerNpcMemory(Base):
    __tablename__ = 'player_npc_memories'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    player_id = Column(Integer, ForeignKey('players.id'))
    npc_id = Column(Integer, ForeignKey('generated_npcs.id'))
    event_type = Column(String)
    details = Column(JSON)

class Ability(Base):
    __tablename__ = 'abilities'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True, nullable=True)
    static_id = Column(String, index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    properties_json = Column(JSON)

class Skill(Base):
    __tablename__ = 'skills'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True, nullable=True)
    static_id = Column(String, index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    properties_json = Column(JSON)

class Status(Base):
    __tablename__ = 'statuses'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True, nullable=True)
    static_id = Column(String, index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    properties_json = Column(JSON)

class ItemProperty(Base):
    __tablename__ = 'item_properties'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True, nullable=True)
    properties_json = Column(JSON)

class Questline(Base):
    __tablename__ = 'questlines'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    ai_metadata_json = Column(JSON)

class QuestStep(Base):
    __tablename__ = 'quest_steps'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    questline_id = Column(Integer, ForeignKey('questlines.id'))
    step_order = Column(Integer)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    required_mechanics_json = Column(JSON)
    abstract_goal_json = Column(JSON)
    consequences_json = Column(JSON)

class MobileGroup(Base):
    __tablename__ = 'mobile_groups'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    composition_json = Column(JSON)
    current_location_id = Column(Integer, ForeignKey('locations.id'))
    goal_location_id = Column(Integer, ForeignKey('locations.id'))
    ai_metadata_json = Column(JSON)

class CraftingRecipe(Base):
    __tablename__ = 'crafting_recipes'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    name_i18n = Column(JSON)
    description_i18n = Column(JSON)
    ingredients_json = Column(JSON)
    output_json = Column(JSON)
    required_skill_id = Column(Integer, ForeignKey('skills.id'))
    required_skill_level = Column(Integer)
    other_requirements_json = Column(JSON)

class RuleConfig(Base):
    __tablename__ = 'rule_configs'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    key = Column(String)
    value = Column(JSON)

class CombatEncounter(Base):
    __tablename__ = 'combat_encounters'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey('guild_configs.id'), index=True)
    location_id = Column(Integer, ForeignKey('locations.id'))
    status = Column(String)
    current_turn_entity_id = Column(Integer)
    turn_order_json = Column(JSON)
    rules_config_snapshot_json = Column(JSON)
    participants_json = Column(JSON)
    combat_log_json = Column(JSON)
