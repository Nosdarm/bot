# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import logging
import asyncpg # Not directly used, consider removing if not needed elsewhere or by asyncpg specifics
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union

from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select # Not directly used, consider removing
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.exc import IntegrityError

# Use Player and Character directly. PlayerDB and CharacterDB seem to be causing import issues.
# The original traceback used PlayerDB, but the ImportError suggests it's not a separate model.
from bot.database.models import Player, Character
from builtins import dict, set, list, int # These are built-in, not usually imported directly

from bot.game.utils import stats_calculator

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.npc_manager import NPCManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.equipment_manager import EquipmentManager
    from bot.game.managers.game_manager import GameManager
    # from bot.database.guild_transaction import GuildTransaction # Added for type hint - Keep if used

logger = logging.getLogger(__name__)

class CharacterAlreadyExistsError(Exception):
    pass

class UpdateHealthResult(BaseModel):
    applied_amount: float
    actual_hp_change: float
    current_hp: float
    max_hp: float
    is_alive: bool
    original_hp: float

class CharacterManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    _characters: Dict[str, Dict[str, Character]]
    _discord_to_player_map: Dict[str, Dict[int, str]]
    _entities_with_active_action: Dict[str, Set[str]]
    _dirty_characters: Dict[str, Set[str]]
    _deleted_characters_ids: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        npc_manager: Optional["NPCManager"] = None,
        inventory_manager: Optional["InventoryManager"] = None,
        equipment_manager: Optional["EquipmentManager"] = None,
        game_manager: Optional["GameManager"] = None
    ):
        logger.info("Initializing CharacterManager...")
        self._db_service = db_service
        self._settings = settings if settings is not None else {}
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager
        self._relationship_manager = relationship_manager
        self._game_log_manager = game_log_manager
        self._npc_manager = npc_manager
        self._inventory_manager = inventory_manager
        self._equipment_manager = equipment_manager
        self._game_manager = game_manager

        self._characters = {}
        self._discord_to_player_map = {}
        self._entities_with_active_action = {}
        self._dirty_characters = {}
        self._deleted_characters_ids = {}
        logger.info("CharacterManager initialized.")

    async def _recalculate_and_store_effective_stats(self, guild_id: str, character_id: str, char_model: Character, session_for_db: Optional[AsyncSession] = None) -> None:
        if not self._game_manager:
            logger.warning(f"CM: GameManager not available for stats recalculation of character {character_id} in guild {guild_id}.")
            char_model.effective_stats_json = json.dumps({"error": "game_manager_unavailable"})
            if session_for_db:
                flag_modified(char_model, "effective_stats_json")
            return
        try:
            effective_stats_dict = await stats_calculator.calculate_effective_stats(entity=char_model, guild_id=guild_id, game_manager=self._game_manager)
            char_model.effective_stats_json = json.dumps(effective_stats_dict or {})
            if session_for_db:
                flag_modified(char_model, "effective_stats_json")
            logger.debug(f"CM: Recalculated and stored effective_stats for character {character_id} in guild {guild_id}.")
        except Exception as es_ex:
            logger.error(f"CM: ERROR recalculating effective_stats for character {character_id} in guild {guild_id}: {es_ex}", exc_info=True)
            char_model.effective_stats_json = json.dumps({"error": "calculation_failed"})
            if session_for_db:
                flag_modified(char_model, "effective_stats_json")

    async def trigger_stats_recalculation(self, guild_id: str, character_id: str, session: Optional[AsyncSession] = None) -> None:
        char_model: Optional[Character] = None
        if session:
            char_model = await session.get(Character, character_id)
            if char_model and str(char_model.guild_id) != guild_id:
                logger.warning(f"CM.trigger_stats_recalculation: Character {character_id} found but belongs to different guild {char_model.guild_id} instead of {guild_id}.")
                char_model = None
        else:
            char_model = self.get_character(guild_id, character_id)

        if char_model:
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char_model, session_for_db=session)
            if session:
                session.add(char_model)
            else:
                self.mark_character_dirty(guild_id, character_id)
            logger.info(f"CM: Stats recalculation triggered for character {character_id} in guild {guild_id}. Session used: {'Yes' if session else 'No'}.")
        else:
            logger.warning(f"CM.trigger_stats_recalculation: Character {character_id} not found in guild {guild_id}.")

    def get_character(self, guild_id: str, character_id: str) -> Optional[Character]:
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars:
            return guild_chars.get(character_id)
        return None

    async def get_character_by_discord_id(self, guild_id: str, discord_user_id: int, session: Optional[AsyncSession] = None) -> Optional[Character]:
        guild_id_str = str(guild_id)
        active_char_id: Optional[str] = None
        player_id_from_cache = self._discord_to_player_map.get(guild_id_str, {}).get(discord_user_id)

        db_session_is_external = session is not None
        actual_session: AsyncSession = session if db_session_is_external else self._db_service.get_session() # type: ignore
        if not actual_session and not self._db_service:
             logger.error("CM.get_character_by_discord_id: DBService not available and no session passed.")
             return None

        try:
            if not db_session_is_external: await actual_session.__aenter__() # type: ignore

            if player_id_from_cache:
                player = await actual_session.get(Player, player_id_from_cache)
                if player and str(player.guild_id) == guild_id_str:
                    active_char_id = player.active_character_id
                else:
                    logger.debug(f"Player {player_id_from_cache} (from cache for Discord {discord_user_id}) not found in DB or guild mismatch.")
                    if guild_id_str in self._discord_to_player_map and discord_user_id in self._discord_to_player_map[guild_id_str]:
                        del self._discord_to_player_map[guild_id_str][discord_user_id]
            else:
                from bot.database.crud_utils import get_entity_by_attributes
                player_account = await get_entity_by_attributes(actual_session, Player, {"discord_id": str(discord_user_id)}, guild_id_str)
                if player_account:
                    self._discord_to_player_map.setdefault(guild_id_str, {})[discord_user_id] = player_account.id
                    active_char_id = player_account.active_character_id
                else:
                    logger.info(f"Player account not found in DB for Discord ID {discord_user_id} in guild {guild_id_str}.")
                    return None

            if active_char_id:
                character = self.get_character(guild_id_str, active_char_id)
                if character:
                    return character
                character = await actual_session.get(Character, active_char_id)
                if character and str(character.guild_id) == guild_id_str:
                    self._characters.setdefault(guild_id_str, {})[active_char_id] = character
                    return character
                else:
                    logger.warning(f"Active character {active_char_id} for player (Discord: {discord_user_id}) not found in DB or guild mismatch.")
                    return None
            else:
                logger.info(f"No active character set for player (Discord: {discord_user_id}) in guild {guild_id_str}.")
                return None
        except Exception as e:
            logger.error(f"Error in get_character_by_discord_id for {discord_user_id} in guild {guild_id_str}: {e}", exc_info=True)
            return None
        finally:
            if not db_session_is_external and actual_session : await actual_session.__aexit__(None, None, None) # type: ignore

    async def _create_and_activate_char_in_session(
        self, session: AsyncSession, guild_id: str, discord_user_id: int, character_name: str, player_language: Optional[str] = None
    ) -> Optional[Character]:
        from bot.database.crud_utils import get_entity_by_attributes, create_entity

        guild_id_str = str(guild_id)
        discord_user_id_str = str(discord_user_id)

        # Use Player model instead of PlayerDB
        player_model = await get_entity_by_attributes(session, Player, {"discord_id": discord_user_id_str}, guild_id_str)
        if not player_model:
            logger.info(f"Player not found for Discord ID {discord_user_id_str}, guild {guild_id_str}. Creating new player.")
            player_data = {
                "discord_id": discord_user_id_str,
                "guild_id": guild_id_str,
                "settings_json": json.dumps({"language": player_language or self._settings.get("DEFAULT_LANGUAGE", "en")})
            }
            player_model = await create_entity(session, Player, player_data, guild_id=guild_id_str)
            if not player_model:
                logger.error(f"Failed to create player for Discord ID {discord_user_id_str}, guild {guild_id_str}.")
                return None
            logger.info(f"Player {player_model.id} created for Discord ID {discord_user_id_str}, guild {guild_id_str}.")
        else:
            logger.info(f"Player {player_model.id} found for Discord ID {discord_user_id_str}, guild {guild_id_str}.")
            player_settings_str = player_model.settings_json if player_model.settings_json else '{}'
            player_settings = json.loads(player_settings_str)
            if player_language and player_settings.get('language') != player_language:
                player_settings['language'] = player_language
                player_model.settings_json = json.dumps(player_settings)
                flag_modified(player_model, "settings_json")
                logger.info(f"Updated language for player {player_model.id} to {player_language}.")

        # Use Character model instead of CharacterDB
        existing_character_with_name = await get_entity_by_attributes(
            session,
            Character,
            {"name": character_name, "player_id": player_model.id},
            guild_id_str
        )
        if existing_character_with_name:
            logger.warning(f"Character with name '{character_name}' already exists for player {player_model.id} in guild {guild_id_str}.")
            return None

        default_stats = self._settings.get("new_character_defaults", {}).get("stats", {"health": 100, "attack": 10, "defense": 5})
        default_level_details = self._settings.get("new_character_defaults", {}).get("level_details", {"current_level": 1, "current_xp": 0, "xp_to_next_level": 100})
        default_status_effects = self._settings.get("new_character_defaults", {}).get("status_effects", [])
        default_location_id = self._settings.get("new_character_defaults", {}).get("location_id")

        character_id = str(uuid.uuid4())
        character_data = {
            "id": character_id,
            "player_id": player_model.id,
            "guild_id": guild_id_str,
            "name": character_name,
            "current_hp": float(default_stats.get("health", 100.0)),
            "max_hp": float(default_stats.get("health", 100.0)),
            "base_stats_json": json.dumps(default_stats),
            "level_details_json": json.dumps(default_level_details),
            "status_effects_json": json.dumps(default_status_effects),
            "action_queue_json": json.dumps([]),
            "is_npc": False,
            "is_alive": True,
        }
        if default_location_id:
            character_data["location_id"] = default_location_id

        if self._inventory_manager:
            inv_id = await self._inventory_manager.create_inventory_for_entity(session, entity_id=character_id, entity_type="character", guild_id=guild_id_str)
            if inv_id: character_data["inventory_id"] = inv_id
        if self._equipment_manager:
            eq_id = await self._equipment_manager.create_equipment_for_entity(session, entity_id=character_id, entity_type="character", guild_id=guild_id_str)
            if eq_id: character_data["equipment_id"] = eq_id

        # Use Character model instead of CharacterDB
        new_character = await create_entity(session, Character, character_data, guild_id=guild_id_str)
        if not new_character:
            logger.error(f"Failed to create character '{character_name}' for player {player_model.id}, guild {guild_id_str}.")
            return None
        logger.info(f"Character {new_character.id} ('{character_name}') created for player {player_model.id}, guild {guild_id_str}.")

        await self._recalculate_and_store_effective_stats(guild_id_str, new_character.id, new_character, session_for_db=session)

        player_model.active_character_id = new_character.id

        self._discord_to_player_map.setdefault(guild_id_str, {})[discord_user_id] = player_model.id
        self._characters.setdefault(guild_id_str, {})[new_character.id] = new_character
        self.mark_character_dirty(guild_id_str, new_character.id)

        logger.info(f"Character {new_character.id} ('{character_name}') activated for player {player_model.id} (Discord: {discord_user_id_str}), guild {guild_id_str}.")
        return new_character

    async def create_and_activate_character_for_discord_user(
        self,
        guild_id: str,
        discord_user_id: int,
        character_name: str,
        player_language: Optional[str] = None
    ) -> Optional[Character]:
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CM: DBService or session factory not available for character creation (guild {guild_id}).")
            return None

        from bot.database.guild_transaction import GuildTransaction
        guild_id_str = str(guild_id)

        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str) as session:
                created_char = await self._create_and_activate_char_in_session(
                    session, guild_id_str, discord_user_id, character_name, player_language
                )
                if created_char:
                    logger.info(f"CM: Successfully created and activated char '{character_name}' (ID: {created_char.id}) for user {discord_user_id} in guild {guild_id_str} within transaction.")
                else:
                    logger.warning(f"CM: _create_and_activate_char_in_session returned None for '{character_name}', user {discord_user_id}, guild {guild_id_str}. Possible existing char or creation failure.")
                return created_char
        except IntegrityError as ie:
            logger.error(f"CM: Database integrity error (e.g. unique constraint) creating character '{character_name}' for user {discord_user_id} in guild {guild_id_str}: {ie}", exc_info=True)
            if "characters.name" in str(ie).lower() or "character_name_guild_idx" in str(ie).lower() :
                 raise CharacterAlreadyExistsError(f"A character named '{character_name}' already exists in this guild.") from ie
            return None
        except CharacterAlreadyExistsError:
             raise
        except Exception as e:
            logger.error(f"CM: Unexpected error in create_and_activate_character_for_discord_user for {discord_user_id} in {guild_id_str}: {e}", exc_info=True)
            return None

    async def update_health(
        self,
        guild_id: str,
        character_id: str,
        amount: float,
        session: Optional[AsyncSession] = None,
        **kwargs: Any
    ) -> Optional[UpdateHealthResult]:
        if not self._db_service and not session:
            logger.error(f"CM: DBService not available and no session passed for update_health: char {character_id}.")
            return None

        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore

        try:
            async with actual_session.begin() if manage_session else asyncio.Semaphore(1):
                char_model = await actual_session.get(Character, character_id)
                if not char_model or str(char_model.guild_id) != guild_id:
                    logger.warning(f"CM.update_health: Character {character_id} not found or guild mismatch in guild {guild_id}.")
                    if manage_session and actual_session.in_transaction(): await actual_session.rollback()
                    return None

                original_hp = float(char_model.current_hp)
                char_model.current_hp = float(char_model.current_hp) + amount
                char_model.max_hp = float(char_model.max_hp)

                if char_model.current_hp < 0: char_model.current_hp = 0.0
                if char_model.current_hp > char_model.max_hp: char_model.current_hp = char_model.max_hp

                actual_hp_change = char_model.current_hp - original_hp
                char_model.is_alive = char_model.current_hp > 0

                flag_modified(char_model, "current_hp")
                flag_modified(char_model, "is_alive")
                actual_session.add(char_model)

                logger.info(f"Character {character_id} health updated by {amount}. Original: {original_hp}, New: {char_model.current_hp}, Max: {char_model.max_hp}. Applied in session.")

                return UpdateHealthResult(
                    applied_amount=amount,
                    actual_hp_change=actual_hp_change,
                    current_hp=char_model.current_hp,
                    max_hp=char_model.max_hp,
                    is_alive=char_model.is_alive,
                    original_hp=original_hp
                )
        except Exception as e:
            logger.error(f"CM: Error updating health for char {character_id} in guild {guild_id}: {e}", exc_info=True)
            return None
        finally:
            if manage_session and actual_session:
                 await actual_session.close()

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CharacterManager: DB service or session factory not available for save_state in guild {guild_id}.")
            return

        guild_id_str = str(guild_id)
        dirty_ids = self._dirty_characters.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_characters_ids.get(guild_id_str, set()).copy()

        if not dirty_ids and not deleted_ids:
            logger.debug(f"CharacterManager: No dirty or deleted characters to save for guild {guild_id_str}.")
            return

        from bot.database.guild_transaction import GuildTransaction
        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str) as session:
                if deleted_ids:
                    from sqlalchemy import delete as sqlalchemy_delete
                    stmt = sqlalchemy_delete(Character).where(Character.id.in_(list(deleted_ids)), Character.guild_id == guild_id_str)
                    result = await session.execute(stmt)
                    logger.info(f"CharacterManager: Executed delete for {result.rowcount} characters in DB for guild {guild_id_str}.")

                guild_cache = self._characters.get(guild_id_str, {})
                merged_count = 0
                for char_id in dirty_ids:
                    if char_id in guild_cache:
                        char_obj_from_cache = guild_cache[char_id]
                        if str(getattr(char_obj_from_cache, 'guild_id', 'DIFFERENT')) != guild_id_str:
                            logger.error(f"CRITICAL: Character {char_id} in guild {guild_id_str} cache has mismatched guild_id {getattr(char_obj_from_cache, 'guild_id')}. Skipping save for this character.")
                            continue
                        await session.merge(char_obj_from_cache)
                        merged_count +=1
                    else:
                        logger.warning(f"Character {char_id} marked dirty but not found in local cache for guild {guild_id_str}. Cannot save.")
                if merged_count > 0:
                    logger.info(f"CharacterManager: Merged {merged_count} dirty characters for guild {guild_id_str}.")

            if guild_id_str in self._deleted_characters_ids:
                self._deleted_characters_ids[guild_id_str].clear()
            if guild_id_str in self._dirty_characters:
                self._dirty_characters[guild_id_str].clear()
                if not self._dirty_characters[guild_id_str]:
                    del self._dirty_characters[guild_id_str]
            logger.info(f"CharacterManager: Successfully saved state for guild {guild_id_str}.")
        except ValueError as ve:
            logger.error(f"CharacterManager: GuildTransaction integrity error during save_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e:
            logger.error(f"CharacterManager: Error during save_state for guild {guild_id_str}: {e}", exc_info=True)

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CharacterManager: DB service or session factory not available for load_state in guild {guild_id}.")
            return

        guild_id_str = str(guild_id)
        logger.info(f"CharacterManager: Loading state for guild {guild_id_str}.")

        self._characters[guild_id_str] = {}
        self._discord_to_player_map[guild_id_str] = {}
        self._entities_with_active_action.pop(guild_id_str, None)
        self._dirty_characters.pop(guild_id_str, None)
        self._deleted_characters_ids.pop(guild_id_str, None)

        from bot.database.crud_utils import get_entities
        from bot.database.guild_transaction import GuildTransaction

        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str, commit_on_exit=False) as session:
                all_players_in_guild = await get_entities(session, Player, guild_id=guild_id_str)
                for player_obj in all_players_in_guild:
                    if player_obj.discord_id:
                        try:
                            self._discord_to_player_map.setdefault(guild_id_str, {})[int(player_obj.discord_id)] = player_obj.id
                        except ValueError:
                             logger.warning(f"Could not parse discord_id '{player_obj.discord_id}' to int for player mapping (Player ID: {player_obj.id}).")
                logger.info(f"CharacterManager: Loaded {len(self._discord_to_player_map.get(guild_id_str, {}))} player ID mappings for guild {guild_id_str}.")

                all_characters_in_guild = await get_entities(session, Character, guild_id=guild_id_str)
                loaded_char_count = 0
                for char_obj in all_characters_in_guild:
                    self._characters.setdefault(guild_id_str, {})[char_obj.id] = char_obj
                    current_action_q_str = char_obj.action_queue_json if char_obj.action_queue_json else "[]"
                    current_action_q = []
                    try:
                        current_action_q = json.loads(current_action_q_str)
                    except json.JSONDecodeError:
                        logger.warning(f"Corrupt action_queue_json for char {char_obj.id} in guild {guild_id_str}: {current_action_q_str}")

                    has_current_action = False
                    if char_obj.current_action_json:
                        if isinstance(char_obj.current_action_json, str) and char_obj.current_action_json.strip() and char_obj.current_action_json != "null":
                            try:
                                if json.loads(char_obj.current_action_json): has_current_action = True
                            except json.JSONDecodeError:
                                logger.warning(f"Corrupt current_action_json for char {char_obj.id} in guild {guild_id_str}: {char_obj.current_action_json}")
                        elif isinstance(char_obj.current_action_json, dict) and char_obj.current_action_json:
                            has_current_action = True

                    if has_current_action or current_action_q:
                        self._entities_with_active_action.setdefault(guild_id_str, set()).add(char_obj.id)
                    loaded_char_count += 1
                logger.info(f"CharacterManager: Loaded {loaded_char_count} characters for guild {guild_id_str}.")
                logger.info(f"CharacterManager: {len(self._entities_with_active_action.get(guild_id_str, set()))} entities with active actions in guild {guild_id_str}.")
        except ValueError as ve:
            logger.error(f"CharacterManager: GuildTransaction integrity error during load_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e:
            logger.error(f"CharacterManager: DB error during load_state for guild {guild_id_str}: {e}", exc_info=True)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info(f"CharacterManager: Rebuilding runtime caches for guild {guild_id}. This involves reloading player maps and active action sets.")
        guild_id_str = str(guild_id)
        self._discord_to_player_map[guild_id_str] = {}
        self._entities_with_active_action[guild_id_str] = set()
        guild_chars = self._characters.get(guild_id_str, {})
        if not guild_chars:
            logger.info(f"CharacterManager.rebuild_runtime_caches: No characters loaded for guild {guild_id_str}, nothing to rebuild caches from.")
            return

        for char_id, char_obj in guild_chars.items():
            current_action_q_str = char_obj.action_queue_json or "[]"
            current_action_q = []
            try: current_action_q = json.loads(current_action_q_str)
            except json.JSONDecodeError: pass

            has_current_action = False
            if char_obj.current_action_json:
                if isinstance(char_obj.current_action_json, str) and char_obj.current_action_json.strip() and char_obj.current_action_json != "null":
                    try:
                        if json.loads(char_obj.current_action_json): has_current_action = True
                    except json.JSONDecodeError: pass
                elif isinstance(char_obj.current_action_json, dict) and char_obj.current_action_json:
                    has_current_action = True

            if has_current_action or current_action_q:
                self._entities_with_active_action.setdefault(guild_id_str, set()).add(char_id)

        logger.info(f"CharacterManager.rebuild_runtime_caches: Rebuilt _entities_with_active_action for guild {guild_id_str} ({len(self._entities_with_active_action.get(guild_id_str, set()))} active).")
        logger.warning("CharacterManager.rebuild_runtime_caches: _discord_to_player_map not fully rebuilt by this method; rely on load_state for full DB sync.")
        pass

    def mark_character_dirty(self, guild_id: str, character_id: str) -> None:
        guild_id_str = str(guild_id)
        if guild_id_str in self._characters and character_id in self._characters[guild_id_str]:
            self._dirty_characters.setdefault(guild_id_str, set()).add(character_id)
            logger.debug(f"Character {character_id} in guild {guild_id_str} marked as dirty.")
        else:
            logger.warning(f"Attempted to mark non-cached character {character_id} in guild {guild_id_str} as dirty.")

    def get_character_by_name(self, guild_id: str, name: str) -> Optional[Character]:
        guild_id_str = str(guild_id)
        guild_chars = self._characters.get(guild_id_str)
        if guild_chars:
            for char in guild_chars.values():
                if char.name == name and not char.is_npc:
                    return char
        return None

    async def get_character_by_name_async(self, session: AsyncSession, guild_id: str, name: str, is_npc: Optional[bool] = None) -> Optional[Character]: # Changed CharacterDB to Character
        from bot.database.crud_utils import get_entity_by_attributes
        attributes: Dict[str, Any] = {"name": name}
        if is_npc is not None:
            attributes["is_npc"] = is_npc
        return await get_entity_by_attributes(session, Character, attributes, str(guild_id)) # Changed CharacterDB to Character

    def get_all_characters(self, guild_id: str, include_npcs: bool = True) -> List[Character]:
        guild_id_str = str(guild_id)
        guild_chars = self._characters.get(guild_id_str, {})
        if include_npcs:
            return list(guild_chars.values())
        else:
            return [char for char in guild_chars.values() if not char.is_npc]

    def get_characters_in_location(self, guild_id: str, location_id: str, include_npcs: bool = True) -> List[Character]:
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        chars_in_location = []
        for char in self._characters.get(guild_id_str, {}).values():
            if str(char.location_id) == location_id_str:
                if include_npcs or not char.is_npc:
                    chars_in_location.append(char)
        return chars_in_location

    def get_entities_with_active_action(self, guild_id: str) -> Set[str]:
        return self._entities_with_active_action.get(str(guild_id), set()).copy()

    def is_busy(self, guild_id: str, character_id: str) -> bool:
        guild_id_str = str(guild_id)
        return character_id in self._entities_with_active_action.get(guild_id_str, set())

    def mark_character_deleted(self, guild_id: str, character_id: str) -> None:
        guild_id_str = str(guild_id)
        if guild_id_str in self._characters and character_id in self._characters[guild_id_str]:
            del self._characters[guild_id_str][character_id]
            if not self._characters[guild_id_str]:
                del self._characters[guild_id_str]
            self._deleted_characters_ids.setdefault(guild_id_str, set()).add(character_id)
            logger.info(f"Character {character_id} in guild {guild_id_str} marked for deletion and removed from cache.")
            self._dirty_characters.get(guild_id_str, set()).discard(character_id)
            self._entities_with_active_action.get(guild_id_str, set()).discard(character_id)
        else:
            logger.warning(f"Attempted to mark non-cached or already removed character {character_id} in guild {guild_id_str} for deletion.")

    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], session: Optional[AsyncSession] = None, **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if char:
            char.party_id = party_id
            self.mark_character_dirty(guild_id_str, character_id)
            logger.debug(f"Character {character_id} party_id set to {party_id} in cache for guild {guild_id_str}.")
            if session:
                db_char = await session.get(Character, character_id)
                if db_char and str(db_char.guild_id) == guild_id_str:
                    db_char.party_id = party_id
                    session.add(db_char)
                    flag_modified(db_char, "party_id")
                    logger.debug(f"Character {character_id} party_id updated in DB session for guild {guild_id_str}.")
                elif db_char:
                     logger.warning(f"set_party_id: Character {character_id} found in DB but guild mismatch ({db_char.guild_id} vs {guild_id_str}).")
                else:
                    logger.warning(f"set_party_id: Character {character_id} not found in DB for guild {guild_id_str} during session update.")
            return True
        else:
            logger.warning(f"Character {character_id} not found in cache for guild {guild_id_str}. Cannot set party ID.")
            return False

    async def update_character_location(
        self, character_id: str, new_location_id: Optional[str], guild_id: str, session: Optional[AsyncSession] = None, **kwargs: Any
    ) -> Optional[Character]:
        guild_id_str = str(guild_id)
        char_in_cache = self.get_character(guild_id_str, character_id)

        if char_in_cache:
            char_in_cache.location_id = new_location_id
            self.mark_character_dirty(guild_id_str, character_id)
            logger.info(f"Character {character_id} location updated to {new_location_id} in cache (Guild: {guild_id_str}).")

            if session:
                db_char = await session.get(Character, character_id)
                if db_char and str(db_char.guild_id) == guild_id_str:
                    db_char.location_id = new_location_id
                    session.add(db_char)
                    flag_modified(db_char, "location_id")
                    logger.info(f"Character {character_id} location updated in DB session (Guild: {guild_id_str}).")
                    return db_char
                else:
                    logger.warning(f"update_character_location: Character {character_id} not found in DB or guild mismatch during session update (Guild: {guild_id_str}).")
                    return None
            return char_in_cache
        else:
            logger.warning(f"update_character_location: Character {character_id} not found in cache (Guild: {guild_id_str}).")
            return None

    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None:
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if char:
            current_action_json_str = json.dumps(action_details) if action_details else None
            char.current_action_json = current_action_json_str
            self.mark_character_dirty(guild_id_str, character_id)
            active_actions_set = self._entities_with_active_action.setdefault(guild_id_str, set())
            action_queue = json.loads(char.action_queue_json or "[]")
            if action_details:
                active_actions_set.add(character_id)
                logger.debug(f"Active action set for {character_id} in guild {guild_id_str}: {action_details}")
            elif not action_queue:
                active_actions_set.discard(character_id)
                logger.debug(f"Active action cleared for {character_id} (no queued actions) in guild {guild_id_str}.")
            else:
                logger.debug(f"Active action cleared for {character_id}, but queue still has actions in guild {guild_id_str}.")
        else:
            logger.warning(f"Cannot set active action: Character {character_id} not found in guild {guild_id_str}.")

    def add_action_to_queue(self, guild_id: str, character_id: str, action_details: Dict[str, Any]) -> None:
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if char:
            current_queue = json.loads(char.action_queue_json or "[]")
            current_queue.append(action_details)
            char.action_queue_json = json.dumps(current_queue)
            self.mark_character_dirty(guild_id_str, character_id)
            self._entities_with_active_action.setdefault(guild_id_str, set()).add(character_id)
            logger.debug(f"Action added to queue for {character_id} in guild {guild_id_str}: {action_details}")
        else:
            logger.warning(f"Cannot add action to queue: Character {character_id} not found in guild {guild_id_str}.")

    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if char:
            current_queue = json.loads(char.action_queue_json or "[]")
            if current_queue:
                next_action = current_queue.pop(0)
                char.action_queue_json = json.dumps(current_queue)
                self.mark_character_dirty(guild_id_str, character_id)
                if not current_queue and not (char.current_action_json and json.loads(char.current_action_json)):
                    self._entities_with_active_action.get(guild_id_str, set()).discard(character_id)
                logger.debug(f"Retrieved next action for {character_id} from queue in guild {guild_id_str}: {next_action}")
                return next_action
            else:
                if not (char.current_action_json and json.loads(char.current_action_json)):
                     self._entities_with_active_action.get(guild_id_str, set()).discard(character_id)
                logger.debug(f"Action queue empty for {character_id} in guild {guild_id_str}.")
                return None
        else:
            logger.warning(f"Cannot get next action: Character {character_id} not found in guild {guild_id_str}.")
            return None

    async def save_character(self, character: Character, guild_id: str) -> bool:
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CM.save_character: DBService or session factory not available (guild {guild_id}).")
            return False
        guild_id_str = str(guild_id)
        if str(character.guild_id) != guild_id_str:
            logger.error(f"CM.save_character: Character {character.id} guild_id ({character.guild_id}) does not match target guild_id ({guild_id_str}). Aborting save.")
            return False

        from bot.database.guild_transaction import GuildTransaction
        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str) as session:
                await session.merge(character)
            self._characters.setdefault(guild_id_str, {})[character.id] = character
            self._dirty_characters.get(guild_id_str, set()).discard(character.id)
            logger.info(f"Character {character.id} saved successfully to DB and cache updated for guild {guild_id_str}.")
            return True
        except Exception as e:
            logger.error(f"CM.save_character: Error saving character {character.id} for guild {guild_id_str}: {e}", exc_info=True)
            return False

    async def gain_xp(self, guild_id: str, character_id: str, amount: int, session: Optional[AsyncSession] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
        if amount <= 0:
            logger.debug(f"gain_xp: Non-positive XP amount ({amount}) for char {character_id}, no change.")
            return None
        guild_id_str = str(guild_id)
        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore
        if not actual_session and not self._db_service :
             logger.error(f"CM.gain_xp: DBService not available and no session passed for char {character_id}.")
             return None

        try:
            async with actual_session.begin() if manage_session else asyncio.Semaphore(1):
                char_model: Optional[Character] = None
                if not manage_session:
                    char_model = await actual_session.get(Character, character_id)
                    if char_model and str(char_model.guild_id) != guild_id_str: char_model = None

                if not char_model:
                    char_model = self.get_character(guild_id_str, character_id)
                    if char_model and manage_session:
                        char_model = await actual_session.merge(char_model)

                if not char_model:
                    logger.warning(f"gain_xp: Character {character_id} not found in guild {guild_id_str}.")
                    return None

                level_details = json.loads(char_model.level_details_json or '{}')
                original_level = level_details.get('current_level', 1)
                current_xp = level_details.get('current_xp', 0)
                xp_to_next = level_details.get('xp_to_next_level', 100)

                current_xp += amount
                leveled_up = False
                levels_gained = 0

                while current_xp >= xp_to_next:
                    current_xp -= xp_to_next
                    level_details['current_level'] += 1
                    leveled_up = True
                    levels_gained +=1
                    xp_to_next = self._settings.get("xp_per_level_map", {}).get(str(level_details['current_level'] +1), xp_to_next * 2)
                    level_details['xp_to_next_level'] = xp_to_next

                level_details['current_xp'] = current_xp
                char_model.level_details_json = json.dumps(level_details)
                flag_modified(char_model, "level_details_json")

                if not manage_session: actual_session.add(char_model)

                self.mark_character_dirty(guild_id_str, character_id)

                logger.info(f"Character {character_id} gained {amount} XP. New XP: {current_xp}, Level: {level_details['current_level']}.")
                if leveled_up:
                    logger.info(f"Character {character_id} leveled up to {level_details['current_level']}!")
                    await self.trigger_stats_recalculation(guild_id_str, character_id, session=actual_session)

                return {
                    "character_id": character_id,
                    "xp_gained": amount,
                    "current_xp": current_xp,
                    "current_level": level_details['current_level'],
                    "xp_to_next_level": xp_to_next,
                    "leveled_up": leveled_up,
                    "levels_gained": levels_gained,
                    "original_level": original_level
                }
        except Exception as e:
            logger.error(f"CM.gain_xp: Error processing XP for char {character_id} in guild {guild_id_str}: {e}", exc_info=True)
            return None
        finally:
            if manage_session and actual_session:
                 await actual_session.close()

    async def update_character_stats(
        self, guild_id: str, character_id: str, stats_update: Dict[str, Any],
        session: Optional[AsyncSession] = None, recalculate_effective: bool = True, **kwargs: Any
    ) -> bool:
        guild_id_str = str(guild_id)
        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore
        if not actual_session and not self._db_service:
             logger.error(f"CM.update_character_stats: DBService not available and no session passed for char {character_id}.")
             return False

        try:
            async with actual_session.begin() if manage_session else asyncio.Semaphore(1):
                char_model: Optional[Character] = None
                if not manage_session:
                    char_model = await actual_session.get(Character, character_id)
                    if char_model and str(char_model.guild_id) != guild_id_str: char_model = None

                if not char_model:
                    char_model = self.get_character(guild_id_str, character_id)
                    if char_model and manage_session:
                        char_model = await actual_session.merge(char_model)

                if not char_model:
                    logger.warning(f"update_character_stats: Character {character_id} not found in guild {guild_id_str}.")
                    return False

                base_stats = json.loads(char_model.base_stats_json or '{}')
                updated_any = False
                for stat_name, value in stats_update.items():
                    if stat_name in base_stats and base_stats[stat_name] != value:
                        base_stats[stat_name] = value
                        updated_any = True
                    elif stat_name not in base_stats:
                        base_stats[stat_name] = value
                        updated_any = True

                if updated_any:
                    char_model.base_stats_json = json.dumps(base_stats)
                    flag_modified(char_model, "base_stats_json")
                    if not manage_session: actual_session.add(char_model)
                    self.mark_character_dirty(guild_id_str, character_id)
                    logger.info(f"Base stats updated for character {character_id} in guild {guild_id_str}. Update: {stats_update}")
                    if recalculate_effective:
                        await self.trigger_stats_recalculation(guild_id_str, character_id, session=actual_session)
                else:
                    logger.debug(f"No change in base stats for character {character_id} with update: {stats_update}")
                return True
        except Exception as e:
            logger.error(f"CM.update_character_stats: Error for char {character_id}, guild {guild_id_str}: {e}", exc_info=True)
            return False
        finally:
            if manage_session and actual_session:
                 await actual_session.close()
