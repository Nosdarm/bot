from sqlalchemy.orm import Session # Keep for potential type hinting if specific Session methods were used
from app.config import logger
from app import crud # Ensure crud is imported
from app.db import transactional_session # Ensure transactional_session is imported
from app.models import RuleConfig # Ensure RuleConfig is imported

_rule_config_cache = {}
DEFAULT_RULES = {"default_greeting": "Hello adventurer!"} # Example default rules

def load_rules_config(guild_id: int) -> dict:
    if guild_id in _rule_config_cache:
        logger.debug(f"Returning cached RuleConfig for guild {guild_id}")
        return _rule_config_cache[guild_id].copy() # Return a copy to prevent external modification of cache

    logger.debug(f"Loading RuleConfig for guild {guild_id} from DB.")
    with transactional_session(guild_id=guild_id) as db:
        # Use the specific getter from crud.py
        rule_config_entity = crud.get_guild_config_by_guild_id(db, RuleConfig, guild_id)
        # crud.get_guild_config_by_guild_id was an example, let's assume a more generic or direct approach
        # rule_config_entity = db.query(RuleConfig).filter(RuleConfig.guild_id == guild_id).first()
        # Corrected: crud.get_one_by_field or similar would be better.
        # For now, using the direct query as in the plan:
        rule_config_entity = db.query(RuleConfig).filter(RuleConfig.guild_id == guild_id).first()

        if not rule_config_entity:
            logger.info(f"No RuleConfig found for guild {guild_id}. Creating with default rules.")
            # Use a copy of DEFAULT_RULES to avoid modifying the global default
            # Ensure guild_id is passed for create_entity if it expects it explicitly and model doesn't auto-set from relationship
            rule_data = {"guild_id": guild_id, "rules": DEFAULT_RULES.copy()}
            rule_config_entity = crud.create_entity(db, RuleConfig, rule_data)
            # create_entity in this setup should take guild_id separately if it's not part of 'data' keys
            # but my crud.create_entity was designed to take guild_id as a separate param for models that have it.
            # Let's adjust create_entity call if needed, or assume 'guild_id' in rule_data is handled by create_entity.
            # The current crud.create_entity will add guild_id to the data if guild_id param is passed and model has guild_id.
            # So, this should be fine:
            # rule_config_entity = crud.create_entity(db, RuleConfig, {"rules": DEFAULT_RULES.copy()}, guild_id=guild_id)


        if rule_config_entity and rule_config_entity.rules is not None:
            _rule_config_cache[guild_id] = rule_config_entity.rules.copy() # Cache a copy
            return rule_config_entity.rules.copy()
        else: # Should not happen if creation works
            logger.error(f"RuleConfig entity for guild {guild_id} has null rules after load/create. Returning default.")
            _rule_config_cache[guild_id] = DEFAULT_RULES.copy()
            return DEFAULT_RULES.copy()


def get_rule(guild_id: int, key: str, default: any = None) -> any:
    rules = load_rules_config(guild_id)
    return rules.get(key, default)

def update_rule_config(guild_id: int, key: str, value: any) -> dict:
    logger.debug(f"Updating RuleConfig for guild {guild_id}: {key} = {value}")
    with transactional_session(guild_id=guild_id) as db:
        rule_config_entity = db.query(RuleConfig).filter(RuleConfig.guild_id == guild_id).first()

        new_rules = {}
        if not rule_config_entity:
            logger.warning(f"RuleConfig not found for guild {guild_id} during update. Creating new one.")
            new_rules = DEFAULT_RULES.copy()
            new_rules[key] = value
            # guild_id is part of the model, so it's a key in the data dict
            rule_data = {"guild_id": guild_id, "rules": new_rules}
            rule_config_entity = crud.create_entity(db, RuleConfig, rule_data)
        else:
            current_rules = rule_config_entity.rules.copy() if rule_config_entity.rules else DEFAULT_RULES.copy()
            current_rules[key] = value
            new_rules = current_rules
            # Update the 'rules' field. SQLAlchemy's JSON type tracks in-place mutations
            # if 'mutable': True is set on JSON type, or by re-assigning.
            rule_config_entity.rules = new_rules
            # No explicit crud.update_entity call here as we are modifying the loaded entity directly.
            # The commit is handled by transactional_session.

        _rule_config_cache[guild_id] = new_rules.copy() # Update cache
        return new_rules.copy()
