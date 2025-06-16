from sqlalchemy.orm import Session
from app.db import Base  # Base is defined in db.py
from app.models import Player, GuildConfig # Specific models
# SessionLocal is not directly used here, but imported in db.py for transactional_session

def get_entity_by_id(db: Session, model: type[Base], entity_id: int, guild_id: int | None = None):
    """
    Fetches an entity by its primary key (id).
    If guild_id is provided and the model has a 'guild_id' attribute,
    it further filters by guild_id.
    """
    query = db.query(model).filter(model.id == entity_id)
    if guild_id is not None and hasattr(model, 'guild_id'):
        # Ensure the model actually has 'guild_id' before trying to filter
        if 'guild_id' in model.__table__.columns:
            query = query.filter(model.guild_id == guild_id)
    return query.first()

def create_entity(db: Session, model: type[Base], data: dict, guild_id: int | None = None):
    """
    Creates a new entity.
    If guild_id is provided and the model has a 'guild_id' attribute,
    it's automatically added to the data if not already present.
    """
    # Filter out keys not part of the model to prevent errors before instance creation
    valid_keys = {column.name for column in model.__table__.columns}

    # Prepare data, ensuring guild_id is included if applicable
    entity_data = {k: v for k, v in data.items() if k in valid_keys}

    if guild_id is not None and hasattr(model, 'guild_id'):
        if 'guild_id' in valid_keys and 'guild_id' not in entity_data:
             entity_data['guild_id'] = guild_id
        elif 'guild_id' not in valid_keys:
            # This case should ideally not happen if model is designed for guild_id
            pass # Or log a warning

    db_entity = model(**entity_data)
    db.add(db_entity)
    # db.commit() # Commit is handled by transactional_session
    # db.refresh(db_entity) # Refresh is handled by transactional_session
    return db_entity

def update_entity(db: Session, db_entity: Base, data: dict):
    """
    Updates an existing entity.
    It's assumed db_entity is already correctly scoped for guild_id if necessary.
    Commit and refresh should be handled by the calling transactional context.
    """
    valid_keys = {column.name for column in db_entity.__table__.columns}

    for key, value in data.items():
        if key in valid_keys and key != 'id': # Don't update PK
            setattr(db_entity, key, value)
    # db.commit() # Commit is handled by transactional_session
    # db.refresh(db_entity) # Refresh is handled by transactional_session
    return db_entity

def delete_entity(db: Session, db_entity: Base):
    """
    Deletes an entity.
    Commit should be handled by the calling transactional context.
    """
    db.delete(db_entity)
    # db.commit() # Commit is handled by transactional_session
    return db_entity # Or return True, or nothing

# Example of a more specific CRUD function you might add:
def get_player_by_discord_id(db: Session, guild_id: int, discord_id: int) -> Player | None:
    return db.query(Player).filter(Player.guild_id == guild_id, Player.discord_id == discord_id).first()

def get_guild_config_by_guild_id(db: Session, guild_id: int) -> GuildConfig | None:
    return db.query(GuildConfig).filter(GuildConfig.guild_id == guild_id).first()
