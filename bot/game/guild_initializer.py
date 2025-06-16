# bot/game/guild_initializer.py
import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.database.models import RulesConfig, GeneratedFaction, Location, GuildConfig, WorldState

logger = logging.getLogger(__name__)

async def initialize_new_guild(db_session: AsyncSession, guild_id: str, force_reinitialize: bool = False):
    """
    Initializes a new guild with default data: RuleConfig, a default Faction, and a starting Location.
    Checks if GuildConfig already exists to prevent re-initialization unless force_reinitialize is True.
    Also creates or updates GuildConfig.
    """
    logger.info(f"Attempting to initialize guild_id: {guild_id} (force_reinitialize: {force_reinitialize})")
    guild_id_str = str(guild_id) # Ensure guild_id is a string

    existing_guild_config_stmt = select(GuildConfig).where(GuildConfig.guild_id == guild_id_str)
    result = await db_session.execute(existing_guild_config_stmt)
    existing_guild_config = result.scalars().first()

    if existing_guild_config and not force_reinitialize:
        logger.warning(f"Guild {guild_id_str} already has a GuildConfig and force_reinitialize is False. Skipping full initialization.")
        return False

    try:
        guild_config_values = {
            "guild_id": guild_id_str,
            "bot_language": "en"
        }

        stmt_guild_config = pg_insert(GuildConfig).values(guild_config_values)
        stmt_guild_config = stmt_guild_config.on_conflict_do_update(
            index_elements=['guild_id'],
            set_={
                "bot_language": stmt_guild_config.excluded.bot_language,
                "game_channel_id": None,
                "master_channel_id": None,
                "system_notifications_channel_id": None
            }
        )
        await db_session.execute(stmt_guild_config)
        logger.info(f"GuildConfig for guild {guild_id_str} upserted successfully.")

        if force_reinitialize:
            logger.info(f"Force reinitializing rules for guild {guild_id_str}. Deleting existing rules.")
            delete_rules_stmt = RulesConfig.__table__.delete().where(RulesConfig.guild_id == guild_id_str)
            await db_session.execute(delete_rules_stmt)

        should_add_rules = False
        if force_reinitialize:
            should_add_rules = True
            logger.info(f"Rules will be added for guild {guild_id_str} due to force_reinitialize.")
        elif existing_guild_config is None:
            should_add_rules = True
            logger.info(f"Rules will be added for new guild {guild_id_str}.")
        else:
            existing_rule_check_stmt = select(RulesConfig.id).where(
                RulesConfig.guild_id == guild_id_str,
                RulesConfig.key == "default_language"
            ).limit(1)
            rule_result = await db_session.execute(existing_rule_check_stmt)
            if not rule_result.scalars().first():
                should_add_rules = True
                logger.info(f"Rules will be added for existing guild {guild_id_str} because marker rule was missing.")
            else:
                logger.info(f"Rules already exist for guild {guild_id_str} and not forcing. Skipping rule addition.")

        if should_add_rules:
            default_rules = {
                "experience_rate": 1.0,
                "loot_drop_chance": 0.5,
                "combat_difficulty_modifier": 1.0,
                "default_language": "en",
                "command_prefixes": ["!"],
                "max_party_size": 4,
                "action_cooldown_seconds": 30
            }
            rules_to_add = []
            for key, value in default_rules.items():
                new_rule = RulesConfig(guild_id=guild_id_str, key=key, value=value)
                rules_to_add.append(new_rule)
            if rules_to_add:
                db_session.add_all(rules_to_add)
                logger.info(f"Added {len(rules_to_add)} default rule entries for guild {guild_id_str}.")

        if existing_guild_config is None or force_reinitialize:
            logger.info(f"Proceeding with Factions/Locations initialization for guild {guild_id_str} (New or Forced).")

            logger.info(f"Initializing default factions for guild {guild_id_str}.")
            if force_reinitialize:
                logger.info(f"Force reinitialize: Deleting existing factions for guild {guild_id_str}.")
                existing_factions_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == guild_id_str)
                result = await db_session.execute(existing_factions_stmt)
                for faction in result.scalars().all():
                    await db_session.delete(faction)
                await db_session.flush()

            default_factions_data = [
                {"id": f"faction_observers_{str(uuid.uuid4())[:8]}", "name_i18n": {"en": "Neutral Observers", "ru": "Нейтральные Наблюдатели"}, "description_i18n": {"en": "A neutral faction...", "ru": "Нейтральная фракция..."}},
                {"id": f"faction_guardians_{str(uuid.uuid4())[:8]}", "name_i18n": {"en": "Forest Guardians", "ru": "Стражи Леса"}, "description_i18n": {"en": "Protectors of the woods...", "ru": "Защитники лесов..."}},
                {"id": f"faction_merchants_{str(uuid.uuid4())[:8]}", "name_i18n": {"en": "Rivertown Traders", "ru": "Торговцы Речного Города"}, "description_i18n": {"en": "A mercantile collective...", "ru": "Торговый коллектив..."}}
            ]
            factions_to_add = []
            for faction_data in default_factions_data:
                new_faction = GeneratedFaction(
                    id=faction_data["id"], guild_id=guild_id_str,
                    name_i18n=faction_data["name_i18n"], description_i18n=faction_data["description_i18n"]
                )
                factions_to_add.append(new_faction)
            if factions_to_add:
                db_session.add_all(factions_to_add)
                logger.info(f"Added {len(factions_to_add)} default factions for guild {guild_id_str}.")

            logger.info(f"Initializing default map for guild {guild_id_str}.")
            if force_reinitialize:
                logger.info(f"Force reinitialize: Deleting existing locations for guild {guild_id_str}.")
                existing_locations_stmt = select(Location).where(Location.guild_id == guild_id_str)
                result = await db_session.execute(existing_locations_stmt)
                for loc in result.scalars().all():
                    await db_session.delete(loc)
                await db_session.flush()

            village_square_id = f"loc_village_square_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"
            village_tavern_id = f"loc_village_tavern_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"
            village_shop_id = f"loc_village_shop_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"
            forest_edge_id = f"loc_forest_edge_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"
            deep_forest_id = f"loc_deep_forest_{guild_id_str[:4]}_{str(uuid.uuid4())[:4]}"

            default_locations_data = [
                {
                    "id": village_square_id,
                    "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"},
                    "descriptions_i18n": {"en": "The village square is a hub of activity during the day, though quieter now. A large oak tree stands in the center, its branches providing shade. An old well sits nearby, and a weathered notice board is posted next to it.", "ru": "Деревенская площадь - центр активности днем, хотя сейчас здесь тише. В центре стоит большой дуб, его ветви дают тень. Рядом находится старый колодец, а возле него - выветрившаяся доска объявлений."},
                    "static_name": f"internal_village_square_{guild_id_str}",
                    "exits": {
                        "north": {"id": forest_edge_id, "name_i18n": {"en": "Forest Edge", "ru": "Опушка Леса"}},
                        "east": {"id": village_tavern_id, "name_i18n": {"en": "The Prancing Pony Tavern", "ru": "Таверна 'Гарцующий Пони'"}},
                        "west": {"id": village_shop_id, "name_i18n": {"en": "General Store", "ru": "Универсальный Магазин"}}
                    },
                    "details_i18n": {
                        "en": {
                            "old_well": "The well is built from weathered grey stones, covered in patches of green moss. Peering inside, you see darkness and hear the faint drip of water, suggesting it might still hold water.",
                            "notice_board": "A sturdy wooden board, clearly old but still functional. Several notices are pinned to it: a faded poster offering a reward for 'information leading to the capture of the bandit Gnarlfang', a newer-looking bill advertising a local farmer's lost pig, and a small, elegantly written card announcing a traveling merchant will be visiting soon.",
                            "market_stall_ruins": "The charred and blackened timbers are all that remain of what were once bustling market stalls. The ground is littered with ash and a few broken, burnt remnants of goods. The air still smells faintly of smoke."
                        },
                        "ru": {
                            "old_well": "Колодец сложен из выветрившихся серых камней, покрытых пятнами зеленого мха. Заглянув внутрь, вы видите тьму и слышите слабое капание воды, что говорит о том, что в нем еще может быть вода.",
                            "notice_board": "Крепкая деревянная доска, явно старая, но все еще функциональная. К ней приколото несколько объявлений: выцветший плакат, предлагающий награду за 'информацию, ведущую к поимке бандита Змеезуба', более свежий листок о пропавшей свинье местного фермера и небольшая, элегантно написанная карточка, объявляющая о скором визите странствующего торговца.",
                            "market_stall_ruins": "Обгоревшие и почерневшие бревна - все, что осталось от некогда оживленных рыночных прилавков. Земля усеяна пеплом и несколькими сломанными, обгоревшими остатками товаров. В воздухе все еще слегка пахнет дымом."
                        }
                    },
                    "type_i18n": {"en": "Area", "ru": "Область"}
                },
                {
                    "id": village_tavern_id,
                    "name_i18n": {"en": "The Prancing Pony Tavern", "ru": "Таверна 'Гарцующий Пони'"},
                    "descriptions_i18n": {"en": "A cozy-looking tavern with warm light spilling from its windows. The sound of merry chatter and clinking mugs can be heard from within. A sign depicting a cheerfully leaping pony hangs above the door.", "ru": "Уютно выглядящая таверна, из окон которой льется теплый свет. Изнутри доносятся звуки веселой болтовни и звяканья кружек. Над дверью висит вывеска с изображением весело прыгающего пони."},
                    "static_name": f"internal_village_tavern_{guild_id_str}",
                    "exits": {"west": {"id": village_square_id, "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"}}},
                    "details_i18n": {
                        "en": {
                            "bar_counter": "The long wooden bar counter is worn smooth by countless tankards and elbows. Several empty glasses and a damp rag sit upon it. Behind it, shelves hold a variety of bottles.",
                            "fireplace": "A large stone fireplace dominates one wall, though it is currently unlit. The hearth is clean, ready for a fire.",
                            "common_table": "A sturdy, round wooden table surrounded by several mismatched chairs. It looks like a popular spot for patrons."
                        },
                        "ru": {
                            "bar_counter": "Длинная деревянная стойка бара отполирована до блеска бесчисленными кружками и локтями. На ней стоят несколько пустых стаканов и влажная тряпка. За стойкой на полках расставлены разнообразные бутылки.",
                            "fireplace": "Большой каменный камин доминирует на одной из стен, хотя в данный момент он не разожжен. Очаг чист и готов к разведению огня.",
                            "common_table": "Крепкий круглый деревянный стол, окруженный несколькими разномастными стульями. Похоже, это популярное место среди посетителей."
                        }
                    },
                    "type_i18n": {"en": "Building Interior", "ru": "Интерьер Здания"}
                },
                {"id": village_shop_id, "name_i18n": {"en": "General Store", "ru": "Универсальный Магазин"}, "descriptions_i18n": {"en": "Various goods...", "ru": "Различные товары..."}, "static_name": f"internal_village_shop_{guild_id_str}", "exits": {"east": {"id": village_square_id, "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"}}}},
                {"id": forest_edge_id, "name_i18n": {"en": "Forest Edge", "ru": "Опушка Леса"}, "descriptions_i18n": {"en": "Edge of a forest...", "ru": "Край леса..."}, "static_name": f"internal_forest_edge_{guild_id_str}", "exits": {"south": {"id": village_square_id, "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"}}, "north": {"id": deep_forest_id, "name_i18n": {"en": "Deep Forest", "ru": "Глубокий Лес"}}}},
                {"id": deep_forest_id, "name_i18n": {"en": "Deep Forest", "ru": "Глубокий Лес"}, "descriptions_i18n": {"en": "Heart of the woods...", "ru": "Сердце леса..."}, "static_name": f"internal_deep_forest_{guild_id_str}", "exits": {"south": {"id": forest_edge_id, "name_i18n": {"en": "Forest Edge", "ru": "Опушка Леса"}}}}
            ]
            locations_to_add = []
            for loc_data in default_locations_data:
                locations_to_add.append(Location(
                    id=loc_data["id"], guild_id=guild_id_str, name_i18n=loc_data["name_i18n"],
                    descriptions_i18n=loc_data["descriptions_i18n"], static_name=loc_data["static_name"],
                    is_active=True, exits=loc_data.get("exits", {}), inventory={}, state_variables={},
                    static_connections={}, details_i18n=loc_data.get("details_i18n", {}),
                    tags_i18n=loc_data.get("tags_i18n", {}),
                    atmosphere_i18n=loc_data.get("atmosphere_i18n", {}),
                    features_i18n=loc_data.get("features_i18n", {}),
                    type_i18n=loc_data.get("type_i18n", {"en": "Area", "ru": "Область"})
                ))
            if locations_to_add:
                db_session.add_all(locations_to_add)
                logger.info(f"Added {len(locations_to_add)} default locations for guild {guild_id_str}.")
        else:
            logger.info(f"Skipping Factions/Locations initialization for guild {guild_id_str} as it's not new or forced.")

        # Initialize WorldState
        logger.info(f"Attempting to initialize WorldState for guild {guild_id_str}.")
        if force_reinitialize:
            logger.info(f"Force reinitialize: Deleting existing WorldState for guild {guild_id_str}.")
            existing_world_state_stmt = select(WorldState).where(WorldState.guild_id == guild_id_str)
            result = await db_session.execute(existing_world_state_stmt)
            existing_world_state = result.scalars().first()
            if existing_world_state:
                await db_session.delete(existing_world_state)
                await db_session.flush()
                logger.info(f"Deleted existing WorldState for guild {guild_id_str}.")

        world_state_stmt = select(WorldState).where(WorldState.guild_id == guild_id_str)
        result = await db_session.execute(world_state_stmt)
        world_state = result.scalars().first()

        if not world_state:
            logger.info(f"No existing WorldState found for guild {guild_id_str} or it was deleted; creating new one.")
            new_world_state = WorldState(
                guild_id=guild_id_str,
                global_narrative_state_i18n={},
                current_era_i18n={},
                custom_flags={}
            )
            db_session.add(new_world_state)
            logger.info(f"New WorldState created and added to session for guild {guild_id_str}.")
        else:
            logger.info(f"WorldState already exists for guild {guild_id_str}. No action taken.")

        await db_session.commit()
        logger.info(f"Successfully initialized/updated default data for guild_id: {guild_id_str}")
        return True
    except IntegrityError as e:
        await db_session.rollback()
        logger.error(f"IntegrityError during guild initialization for {guild_id_str}: {e}. Rolled back session.")
        return False
    except Exception as e:
        await db_session.rollback()
        logger.error(f"Unexpected error during guild initialization for {guild_id_str}: {e}. Rolled back session.", exc_info=True)
        return False

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
