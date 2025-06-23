# bot/game/guild_initializer.py
import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.database.models import RulesConfig, GeneratedFaction, Location, GuildConfig, WorldState, LocationTemplate # Added LocationTemplate

logger = logging.getLogger(__name__)

async def initialize_new_guild(db_session: AsyncSession, guild_id: str, force_reinitialize: bool = False):
    """
    Initializes a new guild with default data: RuleConfig, a default Faction, and a starting Location.
    Checks if GuildConfig already exists to prevent re-initialization unless force_reinitialize is True.
    Also creates or updates GuildConfig.
    """
    logger.info(f"Attempting to initialize/ensure default data for guild_id: {guild_id} (force_reinitialize: {force_reinitialize})")
    guild_id_str = str(guild_id) # Ensure guild_id is a string

    # Check for existing GuildConfig to determine if this is a "new" setup for some parts
    original_existing_guild_config_stmt = select(GuildConfig).where(GuildConfig.guild_id == guild_id_str)
    original_result = await db_session.execute(original_existing_guild_config_stmt)
    original_existing_guild_config = original_result.scalars().first()

    # This flag will determine if we populate new game world entities (factions, specific locations made by this func)
    is_new_world_setup = original_existing_guild_config is None or force_reinitialize
    logger.info(f"Guild Initializer for {guild_id_str}: is_new_world_setup = {is_new_world_setup} (original_existing_guild_config: {bool(original_existing_guild_config)}, force_reinitialize: {force_reinitialize})")

    # The early exit that was problematic:
    # if existing_guild_config and not force_reinitialize:
    #     logger.warning(f"Guild {guild_id_str} already has a GuildConfig and force_reinitialize is False. Skipping full initialization.")
    #     return False # THIS IS REMOVED/MODIFIED

    try:
        # 1. Upsert GuildConfig (always, as it might update bot_language or ensure presence)
        logger.info(f"Guild Initializer for {guild_id_str}: Attempting to upsert GuildConfig.")
        guild_config_values = {
            "guild_id": guild_id_str,
            "bot_language": "en" # Default, can be updated by commands
            # Other fields like game_channel_id are intentionally left to be set by specific commands
            # or later updates, to avoid overwriting them here if they were set manually.
        }

        stmt_guild_config = pg_insert(GuildConfig).values(guild_config_values)
        stmt_guild_config = stmt_guild_config.on_conflict_do_update(
            index_elements=['guild_id'],
            set_={
                # Only update bot_language if it's explicitly part of the insert,
                # otherwise, preserve existing. Since it's always in values, it will be set.
                "bot_language": stmt_guild_config.excluded.bot_language
                # To preserve existing channel IDs if they are already set and not part of `guild_config_values`:
                # "game_channel_id": GuildConfig.game_channel_id, # Keep existing
                # "master_channel_id": GuildConfig.master_channel_id, # Keep existing
                # ... and so on for other fields not intended to be reset by this basic init.
                # However, the current structure of on_conflict_do_update in SQLAlchemy
                # might require listing them if you want to selectively update.
                # The provided example for on_conflict_do_update implies that only fields in `set_` are touched.
                # If a field is not in `set_`, its existing value is retained on conflict.
                # If it's a new insert, fields not in `guild_config_values` get their SQL defaults.
            }
        )
        await db_session.execute(stmt_guild_config)
        logger.info(f"GuildConfig for guild {guild_id_str} upserted successfully.")

        # Initialize WorldState for the guild
        logger.info(f"Guild Initializer for {guild_id_str}: Attempting to upsert WorldState.")
        world_state_values = {
            "guild_id": guild_id_str,
            "global_narrative_state_i18n": {},
            "current_era_i18n": {},
            "custom_flags": {}
        }
        stmt_world_state = pg_insert(WorldState).values(world_state_values)
        stmt_world_state = stmt_world_state.on_conflict_do_update(
            index_elements=['guild_id'], # WorldState.guild_id is unique
            set_={
                "global_narrative_state_i18n": stmt_world_state.excluded.global_narrative_state_i18n,
                "current_era_i18n": stmt_world_state.excluded.current_era_i18n,
                "custom_flags": stmt_world_state.excluded.custom_flags
            }
        )
        await db_session.execute(stmt_world_state)
        logger.info(f"WorldState for guild {guild_id_str} upserted successfully.")

        # Always attempt to upsert default Location Templates.
        # This ensures they exist for CampaignLoader, regardless of force_reinitialize or GuildConfig existence.
        logger.info(f"Ensuring default location templates for guild {guild_id_str}.")
        default_template_ids_for_upsert = [
            "town_square", "tavern", "market_street", "guild_hall", "city_gate",
            "alchemist_shop", "wilderness_crossroads", "forest_path", "mountain_trail",
            "clearing_deepwood", "cave_entrance",
            "village_square", "village_tavern", "village_shop", "forest_edge", "deep_forest" # For guild_initializer's own locations
        ]
        location_template_values_to_upsert = []
        for template_id_val in default_template_ids_for_upsert:
            location_template_values_to_upsert.append({
                "id": template_id_val,
                "name": template_id_val.replace("_", " ").title(),
                "guild_id": guild_id_str,
                "description_i18n": {"en": f"Default template for {template_id_val}"}
            })

        if location_template_values_to_upsert:
            stmt_loc_templates = pg_insert(LocationTemplate).values(location_template_values_to_upsert)
            stmt_loc_templates = stmt_loc_templates.on_conflict_do_nothing(index_elements=['id'])
            await db_session.execute(stmt_loc_templates)
            logger.info(f"Upserted/Ensured {len(location_template_values_to_upsert)} default location templates for guild {guild_id_str}.")

        # Handle RulesConfig: Delete if force_reinitialize, then add if missing or forced.
        if force_reinitialize:
            logger.info(f"Guild Initializer for {guild_id_str}: Force reinitializing rules. Deleting existing RulesConfig entries.")
            delete_rules_stmt = RulesConfig.__table__.delete().where(RulesConfig.guild_id == guild_id_str)
            await db_session.execute(delete_rules_stmt)
            logger.info(f"Guild Initializer for {guild_id_str}: Existing RulesConfig entries deleted due to force_reinitialize.")
            # After forcing delete, we should ensure they are re-added.
            ensure_rules_are_added = True
        else:
            # If not forcing, check if essential rules are present. If not, add them.
            logger.info(f"Guild Initializer for {guild_id_str}: Checking for existing essential rules (e.g., default_language).")
            existing_rule_check_stmt = select(RulesConfig.id).where(
                RulesConfig.guild_id == guild_id_str,
                RulesConfig.key == "default_language"  # A marker default rule
            ).limit(1)
            rule_result = await db_session.execute(existing_rule_check_stmt)
            if not rule_result.scalars().first():
                logger.info(f"Guild Initializer for {guild_id_str}: Essential rules (e.g., default_language) missing. Flagging default rules for addition.")
                ensure_rules_are_added = True
            else:
                logger.info(f"Guild Initializer for {guild_id_str}: Essential rules appear to exist. Not re-adding default rules unless forced.")
                ensure_rules_are_added = False # Rules exist and not forcing, so don't add again.

        if ensure_rules_are_added:
            logger.info(f"Guild Initializer for {guild_id_str}: Proceeding to add/re-add default rules.")
            default_rules = {
                "experience_rate": 1.0,
                "loot_drop_chance": 0.5,
                "combat_difficulty_modifier": 1.0,
                "default_language": "en",
                "command_prefixes": ["!"],
                "max_party_size": 4,
                "action_cooldown_seconds": 30,
                # New rules for check_resolver
                "checks.skill_stealth.attribute": "dexterity",
                "checks.skill_perception.attribute": "wisdom",
                "checks.skill_athletics.attribute": "strength",
                "checks.skill_acrobatics.attribute": "dexterity",
                "checks.skill_intimidation.attribute": "charisma",
                "checks.skill_persuasion.attribute": "charisma",
                "checks.skill_deception.attribute": "charisma",
                "checks.skill_insight.attribute": "wisdom",
                "checks.skill_survival.attribute": "wisdom",
                "checks.skill_medicine.attribute": "wisdom",
                "checks.skill_investigation.attribute": "intelligence",
                "checks.skill_arcana.attribute": "intelligence",
                "checks.skill_history.attribute": "intelligence",
                "checks.skill_religion.attribute": "intelligence",
                "checks.skill_nature.attribute": "intelligence",
                "checks.skill_animal_handling.attribute": "wisdom",
                "checks.skill_sleight_of_hand.attribute": "dexterity",
                "checks.save_strength.attribute": "strength",
                "checks.save_dexterity.attribute": "dexterity",
                "checks.save_constitution.attribute": "constitution",
                "checks.save_intelligence.attribute": "intelligence",
                "checks.save_wisdom.attribute": "wisdom",
                "checks.save_charisma.attribute": "charisma",
                "checks.attack_melee_default.attribute": "strength",
                "checks.attack_ranged_default.attribute": "dexterity",
                "checks.spell_attack_primary.attribute": "intelligence",
                # NLU Action Verbs
                "nlu.action_verbs.en": {
                    "move": ["go", "walk", "travel", "head", "proceed", "run", "sprint", "dash", "stroll"],
                    "look": ["look", "examine", "inspect", "view", "observe", "scan", "check", "peer", "gaze"],
                    "attack": ["attack", "fight", "hit", "strike", "assault", "bash", "slash"],
                    "talk": ["talk", "speak", "chat", "ask", "converse", "address", "question"],
                    "use": ["use", "apply", "consume", "drink", "read", "equip", "activate"],
                    "pickup": ["pickup", "take", "get", "collect", "grab", "acquire"],
                    "drop": ["drop", "leave", "discard"],
                    "open": ["open", "unseal"],
                    "close": ["close", "seal"],
                    "search": ["search", "explore area", "look around", "investigate area"]
                },
                "nlu.action_verbs.ru": {
                    "move": ["иди", "идти", "двигайся", "шагай", "ступай", "отправляйся", "переместись", "беги", "мчись"],
                    "look": ["смотри", "осмотри", "глянь", "исследуй", "проверь", "оглядись", "взгляни", "рассмотри"],
                    "attack": ["атакуй", "дерись", "ударь", "бей", "напади", "руби", "коли"],
                    "talk": ["говори", "поговори", "спроси", "болтай", "общайся", "разговаривай", "задай вопрос"],
                    "use": ["используй", "примени", "выпей", "съешь", "прочти", "надень", "экипируй", "активируй"],
                    "pickup": ["подбери", "возьми", "собери", "хватай", "получи", "забери"],
                    "drop": ["брось", "выброси", "оставь"],
                    "open": ["открой", "распечатай"],
                    "close": ["закрой", "запечатай"],
                    "search": ["ищи", "обыщи", "осмотри местность", "исследуй внимательно"]
                },
                # Character Creation Defaults
                "starting_base_stats": {"strength": 10, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10},
                "starting_items": [{"template_id": "dagger_common", "quantity": 1}, {"template_id": "bread_common", "quantity": 2}],
                "starting_skills": [{"skill_id": "survival", "level": 1}],
                "starting_abilities": ["basic_strike_ability"],
                "starting_character_class": "adventurer",
                "starting_race": "human",
                "starting_mp": 50,
                "starting_attack_base": 5,
                "starting_defense_base": 0
            }
            rules_to_add = []
            for key, value in default_rules.items():
                new_rule = RulesConfig(guild_id=guild_id_str, key=key, value=value)
                rules_to_add.append(new_rule)
            if rules_to_add:
                db_session.add_all(rules_to_add)
                logger.info(f"Added {len(rules_to_add)} default rule entries for guild {guild_id_str}.")

        # Conditional population of game world entities (Factions, default Locations specific to this initializer)
        # This part only runs if it's a brand new guild setup OR force_reinitialize is True.
        if is_new_world_setup:
            logger.info(f"Guild Initializer for {guild_id_str}: Proceeding with new world entity initialization (Factions, default Locations) as is_new_world_setup is True.")

            # Initialize Factions
            logger.info(f"Guild Initializer for {guild_id_str}: Initializing default factions.")
            # No need to check force_reinitialize again here, is_new_world_setup already covers it.
            # If is_new_world_setup is true due to force_reinitialize, factions should be deleted.
            if force_reinitialize: # This specific deletion should only happen if forced.
                 logger.info(f"Guild Initializer for {guild_id_str}: Force reinitialize - Deleting existing GeneratedFaction entries.")
                 existing_factions_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == guild_id_str)
                 result = await db_session.execute(existing_factions_stmt)
                 deleted_faction_count = 0
                 for faction in result.scalars().all():
                     await db_session.delete(faction)
                     deleted_faction_count += 1
                 if deleted_faction_count > 0:
                    await db_session.flush()
                    logger.info(f"Guild Initializer for {guild_id_str}: Deleted {deleted_faction_count} existing GeneratedFaction entries.")

            default_factions_data_group1 = [ # Renamed to avoid conflict with a later redeclaration
                {"id": f"faction_observers_{str(uuid.uuid4())[:8]}", "name_i18n": {"en": "Neutral Observers", "ru": "Нейтральные Наблюдатели"}, "description_i18n": {"en": "A neutral faction...", "ru": "Нейтральная фракция..."}},
                {"id": f"faction_guardians_{str(uuid.uuid4())[:8]}", "name_i18n": {"en": "Forest Guardians", "ru": "Стражи Леса"}, "description_i18n": {"en": "Protectors of the woods...", "ru": "Защитники лесов..."}},
                {"id": f"faction_merchants_{str(uuid.uuid4())[:8]}", "name_i18n": {"en": "Rivertown Traders", "ru": "Торговцы Речного Города"}, "description_i18n": {"en": "A mercantile collective...", "ru": "Торговый коллектив..."}}
            ]
            factions_to_add_group1 = [] # Renamed
            for faction_data in default_factions_data_group1: # Use renamed variable
                new_faction = GeneratedFaction(
                    id=faction_data["id"], guild_id=guild_id_str,
                    name_i18n=faction_data["name_i18n"], description_i18n=faction_data["description_i18n"]
                )
                factions_to_add_group1.append(new_faction) # Use renamed variable
            if factions_to_add_group1: # Use renamed variable
                db_session.add_all(factions_to_add_group1) # Use renamed variable
                logger.info(f"Added {len(factions_to_add_group1)} default factions for guild {guild_id_str}.")

            # Initialize default Locations (those specific to this function, not from CampaignLoader)
            logger.info(f"Guild Initializer for {guild_id_str}: Initializing default map (Location entities).") # Moved this log up
            # The LocationTemplate creation block that was here is removed as it's redundant
            # with the pg_insert block earlier in the function.

            # Deletion of existing Locations if force_reinitialize
            if force_reinitialize: # This specific deletion should only happen if forced.
                logger.info(f"Guild Initializer for {guild_id_str}: Force reinitialize - Deleting existing Location entries for this guild.")
                # This was: existing_locations_stmt = select(Location).where(Location.guild_id == guild_id_str)
                # And then: result = await db_session.execute(existing_factions_stmt) <- TYPO: used existing_factions_stmt
                # Corrected:
                existing_locations_stmt = select(Location).where(Location.guild_id == guild_id_str)
                result = await db_session.execute(existing_locations_stmt) # Corrected to use existing_locations_stmt
                deleted_loc_count = 0
                for loc in result.scalars().all(): # Changed variable name from faction to loc
                    await db_session.delete(loc)
                    deleted_loc_count +=1
                if deleted_loc_count > 0:
                    await db_session.flush()
                    logger.info(f"Guild Initializer for {guild_id_str}: Deleted {deleted_loc_count} existing Location entries.")


            # This was a duplicate faction creation block, removing it.
            # default_factions_data = [ ... ]
            # factions_to_add = []
            # ...
            # db_session.add_all(factions_to_add)

            # The LocationTemplate creation that was here is removed as it's handled by the earlier pg_insert.
            # logger.info(f"Guild Initializer for {guild_id_str}: Initializing default location templates.")
            # if force_reinitialize:
            #    ... delete ...
            # default_template_ids = [ ... ]
            # location_templates_to_add = []
            # ...
            # db_session.add_all(location_templates_to_add)

            # Ensure the log for initializing map (Location entities) is not duplicated. It was moved up.
            # logger.info(f"Guild Initializer for {guild_id_str}: Initializing default map (Location entities).")
            # The deletion of locations if force_reinitialize was also moved up and corrected.
            # if force_reinitialize:
            #    logger.info(f"Guild Initializer for {guild_id_str}: Force reinitialize - Deleting existing Location entries.")
                existing_locations_stmt = select(Location).where(Location.guild_id == guild_id_str)
                result = await db_session.execute(existing_locations_stmt)
                deleted_loc_count = 0
                for loc in result.scalars().all():
                    await db_session.delete(loc)
                    deleted_loc_count += 1
                if deleted_loc_count > 0:
                    await db_session.flush()
                    logger.info(f"Guild Initializer for {guild_id_str}: Deleted {deleted_loc_count} existing Location entries.")

            village_square_id = f"loc_village_square_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"
            village_tavern_id = f"loc_village_tavern_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"
            village_shop_id = f"loc_village_shop_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"
            forest_edge_id = f"loc_forest_edge_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"
            deep_forest_id = f"loc_deep_forest_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"

            default_locations_data = [
                {
                    "id": village_square_id,
                    "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"},
                    "descriptions_i18n": {"en": "Bustling center...", "ru": "Шумный центр..."},
                    "static_id": "village_square", # Changed to a fixed, predictable static_id
                    "neighbor_locations_json": { # New structure for exits/connections
                        forest_edge_id: "path_to_forest_edge", # Using descriptive keys for connection type
                        village_tavern_id: "door_to_tavern",
                        village_shop_id: "door_to_shop"
                    }
                },
                {
                    "id": village_tavern_id,
                    "name_i18n": {"en": "The Prancing Pony Tavern", "ru": "Таверна 'Гарцующий Пони'"},
                    "descriptions_i18n": {"en": "Cozy tavern...", "ru": "Уютная таверна..."},
                    "static_id": f"internal_village_tavern_{guild_id_str}", # Renamed
                    "neighbor_locations_json": {
                        village_square_id: "door_to_square"
                    }
                },
                {
                    "id": village_shop_id,
                    "name_i18n": {"en": "General Store", "ru": "Универсальный Магазин"},
                    "descriptions_i18n": {"en": "Various goods...", "ru": "Различные товары..."},
                    "static_id": f"internal_village_shop_{guild_id_str}", # Renamed
                    "neighbor_locations_json": {
                        village_square_id: "door_to_square"
                    }
                },
                {
                    "id": forest_edge_id,
                    "name_i18n": {"en": "Forest Edge", "ru": "Опушка Леса"},
                    "descriptions_i18n": {"en": "Edge of a forest...", "ru": "Край леса..."},
                    "static_id": f"internal_forest_edge_{guild_id_str}", # Renamed
                    "neighbor_locations_json": {
                        village_square_id: "path_to_village_square",
                        deep_forest_id: "path_to_deep_forest"
                    },
                    "on_enter_events_json": [
                        {
                            "event_type": "AMBIENT_MESSAGE",
                            "chance": 0.5,
                            "message_i18n": {"en": "The wind rustles the leaves ominously here.", "ru": "Ветер зловеще шелестит здесь листьями."}
                        },
                        {
                            "event_type": "ITEM_DISCOVERY",
                            "chance": 0.1,
                            "items": [{"item_template_id": "healing_herb_common", "quantity": 1}],
                            "message_i18n": {"en": "You spot a medicinal herb growing by a tree.", "ru": "Вы замечаете у дерева целебную траву."},
                            "discovery_target": "entering_character"
                        }
                    ]
                },
                {
                    "id": deep_forest_id,
                    "name_i18n": {"en": "Deep Forest", "ru": "Глубокий Лес"},
                    "descriptions_i18n": {"en": "Heart of the woods...", "ru": "Сердце леса..."},
                    "static_id": f"internal_deep_forest_{guild_id_str}", # Renamed
                    "neighbor_locations_json": {
                        forest_edge_id: "path_to_forest_edge"
                    },
                    "on_enter_events_json": [
                        {
                            "event_type": "NPC_APPEARANCE",
                            "chance": 0.05,
                            "npc_template_id": "wolf_forest",
                            "spawn_count": 1,
                            "is_temporary": True,
                            "message_i18n": {"en": "A lone wolf eyes you warily from the deeper shadows.", "ru": "Одинокий волк настороженно смотрит на вас из глубоких теней."}
                        },
                        {
                            "event_type": "SIMPLE_HAZARD",
                            "chance": 0.03,
                            "effect_type": "damage",
                            "damage_amount": 2,
                            "damage_type": "minor_scratch",
                            "message_i18n": {"en": "You brush against a thorny vine, receiving a small scratch.", "ru": "Вы задеваете колючую лозу и получаете небольшую царапину."},
                            "target": "entering_character"
                        }
                    ]
                }
            ]
            locations_to_add = []
            for loc_data in default_locations_data:
                locations_to_add.append(Location(
                    id=loc_data["id"],
                    guild_id=guild_id_str,
                    name_i18n=loc_data["name_i18n"],
                    descriptions_i18n=loc_data["descriptions_i18n"],
                    static_id=loc_data["static_id"],
                    template_id=loc_data["static_id"], # Assign template_id, assuming it matches static_id for these defaults
                    is_active=True,
                    neighbor_locations_json=loc_data.get("neighbor_locations_json", {}),
                    ai_metadata_json={},
                    inventory={},
                    state_variables={},
                    details_i18n=loc_data.get("details_i18n", {}),
                    tags_i18n=loc_data.get("tags_i18n", {}),
                    atmosphere_i18n=loc_data.get("atmosphere_i18n", {}),
                    features_i18n=loc_data.get("features_i18n", {}),
                    type_i18n=loc_data.get("type_i18n", {"en": "Area", "ru": "Область"}),
                    points_of_interest_json=loc_data.get("points_of_interest_json", []),
                    on_enter_events_json=loc_data.get("on_enter_events_json", [])
                ))
            if locations_to_add:
                db_session.add_all(locations_to_add)
                logger.info(f"Guild Initializer for {guild_id_str}: Added {len(locations_to_add)} default Location entries.")
        else:
            logger.info(f"Guild Initializer for {guild_id_str}: Skipping Factions/Locations initialization as is_new_world_setup is False.")

        # Initialize WorldState
        logger.info(f"Guild Initializer for {guild_id_str}: Attempting to initialize WorldState.")
        if force_reinitialize:
            logger.info(f"Guild Initializer for {guild_id_str}: Force reinitialize - Deleting existing WorldState for guild.")
            existing_world_state_stmt = select(WorldState).where(WorldState.guild_id == guild_id_str)
            result = await db_session.execute(existing_world_state_stmt)
            existing_world_state = result.scalars().first()
            if existing_world_state:
                await db_session.delete(existing_world_state)
                await db_session.flush()
                logger.info(f"Guild Initializer for {guild_id_str}: Deleted existing WorldState.")
            else:
                logger.info(f"Guild Initializer for {guild_id_str}: No existing WorldState found to delete (force_reinitialize).")


        world_state_stmt = select(WorldState).where(WorldState.guild_id == guild_id_str)
        result = await db_session.execute(world_state_stmt)
        world_state = result.scalars().first()

        if not world_state:
            logger.info(f"Guild Initializer for {guild_id_str}: No existing WorldState found (or it was deleted); creating new one.")
            new_world_state = WorldState(
                guild_id=guild_id_str,
                global_narrative_state_i18n={},
                current_era_i18n={},
                custom_flags={}
            )
            db_session.add(new_world_state)
            logger.info(f"Guild Initializer for {guild_id_str}: New WorldState created and added to session.")
        else:
            logger.info(f"Guild Initializer for {guild_id_str}: WorldState already exists. No action taken for WorldState creation.")

        # logger.info(f"Guild Initializer for {guild_id_str}: Attempting to commit session.") # Removed
        # await db_session.commit() # Removed: Caller will handle commit/rollback
        logger.info(f"Guild Initializer for {guild_id_str}: Operations completed. Successfully staged data for initialization/update.")
        return True # Indicates logical success of operations, not commit status
    except IntegrityError as e:
        # await db_session.rollback() # Removed: Caller will handle rollback
        logger.error(f"Guild Initializer for {guild_id_str}: IntegrityError during guild initialization: {e}. Caller should roll back.", exc_info=True)
        # Re-raise the error so the caller's transaction management (e.g., GuildTransaction or manual try/except) can catch it and roll back.
        # This ensures the specific error is propagated if the caller wants to inspect it.
        # Alternatively, just return False and let the caller decide to rollback based on that.
        # For now, re-raising to make the failure explicit to the transactional context.
        raise  # Re-raise the caught IntegrityError
    except Exception as e:
        # await db_session.rollback() # Removed: Caller will handle rollback
        logger.error(f"Guild Initializer for {guild_id_str}: Unexpected error during guild initialization: {e}. Caller should roll back.", exc_info=True)
        raise # Re-raise other unexpected exceptions

# Main test function (commented out for bot use)
# if __name__ == '__main__':
#     async def main_test_run():
#         # Simplified test setup
#         DATABASE_URL_TEST = "postgresql+asyncpg://user:pass@host:port/test_db" # Replace
#         engine = create_async_engine(DATABASE_URL_TEST, echo=False)
#         async with engine.begin() as conn:
#             await conn.run_sync(Base.metadata.drop_all)
#             await conn.run_sync(Base.metadata.create_all)
#
#         async_session_local_test = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False) # type: ignore
#
#         test_g_id = f"test_g_{str(uuid.uuid4())[:6]}"
#         async with async_session_local_test() as session:
#             logging.info(f"Running test init for guild: {test_g_id}")
#             await initialize_new_guild(session, test_g_id)
#             logging.info(f"Running test re-init (no force) for guild: {test_g_id}")
#             await initialize_new_guild(session, test_g_id, force_reinitialize=False)
#             logging.info(f"Running test re-init (force) for guild: {test_g_id}")
#             await initialize_new_guild(session, test_g_id, force_reinitialize=True)
#         await engine.dispose()
#
#     logging.basicConfig(level=logging.INFO)
#     import asyncio
#     asyncio.run(main_test_run())
