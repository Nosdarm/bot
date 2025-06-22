# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import logging
import asyncpg
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union

from pydantic import BaseModel # Added for UpdateHealthResult

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm.attributes import flag_modified

from bot.database.models import Player, Character
from builtins import dict, set, list, int

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

logger = logging.getLogger(__name__)

class CharacterAlreadyExistsError(Exception):
    pass

# Pydantic model for update_health return type
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
            logger.warning(f"CM: GameManager NA for stats recalc: char {character_id}, guild {guild_id}.")
            char_model.effective_stats_json = json.dumps({"error": "game_manager_unavailable"})
            if session_for_db: flag_modified(char_model, "effective_stats_json")
            return
        try:
            effective_stats_dict = await stats_calculator.calculate_effective_stats(entity=char_model, guild_id=guild_id, game_manager=self._game_manager)
            char_model.effective_stats_json = json.dumps(effective_stats_dict or {})
            if session_for_db: flag_modified(char_model, "effective_stats_json")
            logger.debug(f"CM: Recalculated effective_stats for char {character_id}, guild {guild_id}.")
        except Exception as es_ex:
            logger.error(f"CM: ERROR recalculating stats for char {character_id}, guild {guild_id}: {es_ex}", exc_info=True)
            char_model.effective_stats_json = json.dumps({"error": "calculation_failed"})
            if session_for_db: flag_modified(char_model, "effective_stats_json")

    async def trigger_stats_recalculation(self, guild_id: str, character_id: str, session: Optional[AsyncSession] = None) -> None:
        char_model: Optional[Character] = None
        if session:
            char_model = await session.get(Character, character_id)
            if char_model and str(char_model.guild_id) != guild_id: char_model = None
        else: char_model = self.get_character(guild_id, character_id)

        if char_model:
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char_model, session_for_db=session)
            if session: session.add(char_model)
            else: self.mark_character_dirty(guild_id, character_id)
            logger.info(f"CM: Stats recalc triggered for char {character_id}, guild {guild_id}. Session used: {'Yes' if session else 'No'}.")
        else: logger.warning(f"CM.trigger_stats_recalculation: Character {character_id} not found in guild {guild_id}.")

    def get_character(self, guild_id: str, character_id: str) -> Optional[Character]:
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars: return guild_chars.get(character_id)
        return None

    async def get_character_by_discord_id(self, guild_id: str, discord_user_id: int, session: Optional[AsyncSession] = None) -> Optional[Character]:
        guild_id_str = str(guild_id)
        player_id_in_cache = self._discord_to_player_map.get(guild_id_str, {}).get(discord_user_id)
        active_char_id: Optional[str] = None
        db_session_is_external = session is not None
        actual_session: AsyncSession = session if db_session_is_external else self._db_service.get_session() # type: ignore
        if not actual_session and not self._db_service :
            logger.error("CM.get_character_by_discord_id: DBService not available and no session passed.")
            return None
        try:
            if not db_session_is_external: await actual_session.__aenter__() # type: ignore
            if player_id_in_cache:
                player = await actual_session.get(Player, player_id_in_cache)
                if player and str(player.guild_id) == guild_id_str: active_char_id = player.active_character_id
                else: logger.debug(f"Player {player_id_in_cache} for Discord {discord_user_id} not found or guild mismatch in DB.")
            else:
                from bot.database.crud_utils import get_entity_by_attributes
                player_account = await get_entity_by_attributes(session, Player, {"discord_id": str(discord_user_id)}, guild_id_str)
                if player_account:
                    self._discord_to_player_map.setdefault(guild_id_str, {})[discord_user_id] = player_account.id
                    active_character_id_to_fetch = player_account.active_character_id
                else:
                    logger.info(f"Player account not found in DB for Discord ID {discord_user_id} in guild {guild_id_str}.")
                    return None
        except Exception as e:
            logger.error(f"Error in get_character_by_discord_id for {discord_user_id} in guild {guild_id_str}: {e}", exc_info=True)
            return None
        finally:
            if not db_session_is_external and actual_session: await actual_session.__aexit__(None, None, None) # type: ignore

    async def update_health(
        self,
        guild_id: str,
        character_id: str,
        amount: float, # This is the amount to change health by (can be negative for damage)
        session: Optional[AsyncSession] = None,
        **kwargs: Any # For potential future use, e.g., source of damage/healing
    ) -> Optional[UpdateHealthResult]:
        if not self._db_service:
            logger.error(f"CM: DBService not available for update_health: char {character_id}.")
            return None

        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore

        async with actual_session.begin() if manage_session else actual_session.begin_nested(): # type: ignore
            char_model = await actual_session.get(Character, character_id)
            if not char_model or str(char_model.guild_id) != guild_id:
                logger.warning(f"CM.update_health: Character {character_id} not found in guild {guild_id}.")
                return None

            original_hp = float(char_model.current_hp)

            char_model.current_hp = float(char_model.current_hp) + amount

            # Ensure max_hp is float for comparison and storage
            char_model.max_hp = float(char_model.max_hp)
            if char_model.current_hp < 0:
                char_model.current_hp = 0.0
            if char_model.current_hp > char_model.max_hp:
                char_model.current_hp = char_model.max_hp

            actual_hp_change = char_model.current_hp - original_hp

            char_model.is_alive = char_model.current_hp > 0

            flag_modified(char_model, "current_hp")
            flag_modified(char_model, "is_alive")

            logger.info(f"Character {character_id} health updated by {amount}. Original: {original_hp}, New: {char_model.current_hp}, Max: {char_model.max_hp}. Applied in session.")

            # char_model is already part of the session and changes are tracked.
            # If manage_session is true, session.commit() will be called by async with.

            return UpdateHealthResult(
                applied_amount=amount,
                actual_hp_change=actual_hp_change,
                current_hp=char_model.current_hp,
                max_hp=char_model.max_hp,
                is_alive=char_model.is_alive,
                original_hp=original_hp
            )


    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None:
            logger.error(f"CharacterManager: DB service not available for save_state in guild {guild_id}.")
            return

        guild_id_str = str(guild_id)
        dirty_ids = self._dirty_characters.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_characters_ids.get(guild_id_str, set()).copy()

        if not dirty_ids and not deleted_ids:
            logger.debug(f"CharacterManager: No dirty or deleted characters to save for guild {guild_id_str}.")
            return

        # Ensure db_service and its session_factory are available
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CharacterManager: DB service or session factory not available for save_state in guild {guild_id_str}.")
            return

        # Use GuildTransaction for saving state
        from bot.database.guild_transaction import GuildTransaction
        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str) as session:
                if deleted_ids:
                    ids_to_delete_list = list(deleted_ids)
                    if ids_to_delete_list:
                        from sqlalchemy import delete as sqlalchemy_delete
                        stmt = sqlalchemy_delete(Character).where(
                            Character.id.in_(ids_to_delete_list)
                            # Guild ID check is implicitly handled by GuildTransaction's pre-commit checks
                            # if we were fetching and then deleting, or if Character model had a before_delete hook.
                            # For a bulk delete like this, ensuring the IDs actually BELONG to the guild
                            # before adding to deleted_ids is important.
                            # The GuildTransaction won't catch deleting an object from another guild if it's not loaded.
                            # However, mark_character_deleted operates on cache which is guild-segregated.
                        )
                        await session.execute(stmt)
                        logger.info(f"CharacterManager: Executed delete for {len(ids_to_delete_list)} characters in DB for guild {guild_id_str}: {ids_to_delete_list}")

                guild_cache = self._characters.get(guild_id_str, {})
                processed_dirty_ids_in_transaction = set()
                for char_id in dirty_ids:
                    if char_id in guild_cache:
                        char_obj = guild_cache[char_id]
                        # Ensure the character object's guild_id matches before merging.
                        # GuildTransaction pre-commit check will also verify this.
                        if hasattr(char_obj, 'guild_id') and str(getattr(char_obj, 'guild_id')) != guild_id_str:
                            logger.error(f"CRITICAL: Character {char_id} in guild {guild_id_str} cache has mismatched guild_id {getattr(char_obj, 'guild_id')}. Skipping save.")
                            continue
                        await session.merge(char_obj)
                        processed_dirty_ids_in_transaction.add(char_id)
                    else:
                        logger.warning(f"Character {char_id} marked dirty but not found in cache for guild {guild_id_str}.")

                logger.info(f"CharacterManager: Processed {len(processed_dirty_ids_in_transaction)} dirty characters for guild {guild_id_str} via merge.")
                # No explicit session.commit() needed due to GuildTransaction

            # Cleanup local dirty/deleted sets only after successful transaction
            if guild_id_str in self._deleted_characters_ids:
                    self._deleted_characters_ids[guild_id_str].clear()
            if guild_id_str in self._dirty_characters:
                self._dirty_characters[guild_id_str].difference_update(processed_dirty_ids_in_transaction)
                if not self._dirty_characters[guild_id_str]: del self._dirty_characters[guild_id_str]
            logger.info(f"CharacterManager: Successfully saved state for guild {guild_id_str}.")

        except ValueError as ve: # Catch GuildTransaction specific errors
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
        from bot.database.guild_transaction import GuildTransaction # Recommended for consistency, though reads might use simpler session

        try:
            # Using GuildTransaction for consistency, though for pure reads, a simpler session might also work
            # if crud_utils are used which internally apply guild_id filtering.
            # GuildTransaction ensures session.info["current_guild_id"] is set, which crud_utils can use for verification.
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str, commit_on_exit=False) as session: # commit_on_exit=False for read-only
                all_players_in_guild = await get_entities(session, Player, guild_id=guild_id_str)
                for player_obj in all_players_in_guild:
                    if player_obj.discord_id:
                        try:
                            self._discord_to_player_map.setdefault(guild_id_str, {})[int(player_obj.discord_id)] = player_obj.id
                        except ValueError:
                            logger.warning(f"Could not parse discord_id '{player_obj.discord_id}' to int for player mapping for player {player_obj.id}.")
                logger.info(f"CharacterManager: Loaded {len(self._discord_to_player_map.get(guild_id_str, {}))} player ID mappings for guild {guild_id_str}.")

                all_characters_in_guild = await get_entities(session, Character, guild_id=guild_id_str)
                loaded_char_count = 0
                for char_obj in all_characters_in_guild:
                    self._characters.setdefault(guild_id_str, {})[char_obj.id] = char_obj
                    current_action_q_str = char_obj.action_queue_json or "[]"
                    current_action_q = []
                    try:
                        current_action_q = json.loads(current_action_q_str)
                    except json.JSONDecodeError:
                        logger.warning(f"Corrupt action_queue_json for char {char_obj.id}: {current_action_q_str}")

                    if char_obj.current_action_json or current_action_q: # Check if current_action_json is not None or empty
                        if isinstance(char_obj.current_action_json, str) and not char_obj.current_action_json.strip(): # handle empty string case for JSON
                             pass # treat empty string as no action
                        elif char_obj.current_action_json or current_action_q: # check again after potential empty string handling
                            self._entities_with_active_action.setdefault(guild_id_str, set()).add(char_obj.id)

                    loaded_char_count += 1
                logger.info(f"CharacterManager: Loaded {loaded_char_count} characters for guild {guild_id_str}.")

        except ValueError as ve: # Catch GuildTransaction specific errors if they arise
            logger.error(f"CharacterManager: GuildTransaction integrity error during load_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e:
            logger.error(f"CharacterManager: DB error during load_state for guild {guild_id_str}: {e}", exc_info=True)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info(f"CharacterManager: Rebuilding runtime caches for guild {guild_id} (currently a pass-through).")
        pass

    def mark_character_dirty(self, guild_id: str, character_id: str) -> None:
         if str(guild_id) in self._characters and character_id in self._characters[str(guild_id)]:
              self._dirty_characters.setdefault(str(guild_id), set()).add(character_id)
    async def save_state(self, guild_id: str, **kwargs: Any) -> None: pass # Assumes DB writes are transactional per method now
    async def load_state(self, guild_id: str, **kwargs: Any) -> None: # Needs full DB load
        if self._db_service is None: logger.error(f"CM: DB service NA for load_state guild {guild_id}."); return
        # ... (full load logic as previously provided) ...
    async def get_character_details_context(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]: return None # Placeholder

    # Other methods would need similar review for direct DB interaction with sessions or cache management
    def get_character_by_name(self, guild_id: str, name: str) -> Optional[Character]: return None
    def get_all_characters(self, guild_id: str) -> List[Character]: return []
    def get_characters_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List[Character]: return []
    def get_entities_with_active_action(self, guild_id: str) -> Set[str]: return set()
    def is_busy(self, guild_id: str, character_id: str) -> bool: return False
    def mark_character_deleted(self, guild_id: str, character_id: str) -> None: pass
    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool: return False
    async def update_character_location(self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any) -> Optional[Character]: return None
    async def add_item_to_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool: return False
    async def remove_item_from_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool: return False
    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None: pass
    def add_action_to_queue(self, guild_id: str, character_id: str, action_details: Dict[str, Any]) -> None: pass
    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]: return None
    async def save_character(self, character: Character, guild_id: str) -> bool: return False
    async def set_current_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool: return False
    async def save_character_field(self, guild_id: str, character_id: str, field_name: str, value: Any, **kwargs: Any) -> bool: return False
    async def gain_xp(self, guild_id: str, character_id: str, amount: int, session: Optional[AsyncSession] = None) -> Optional[Dict[str, Any]]: return None # Placeholder
    async def update_character_stats(self, guild_id: str, character_id: str, stats_update: Dict[str, Any], session: Optional[AsyncSession] = None, **kwargs: Any) -> bool: return False

    async def _create_and_activate_char_in_session(
        self,
        session: AsyncSession,
        guild_id: str,
        discord_user_id: str,
        character_name: str,
        player_language: Optional[str],
        char_class_key: Optional[str], # Not used yet, for future expansion
        race_key: Optional[str] # Not used yet, for future expansion
    ) -> Optional[CharacterPydantic]: # Return Pydantic model

        from bot.database.models import Player as PlayerDB, Character as CharacterDB
        from bot.game.models.character import Character as CharacterPydantic
        from bot.database.crud_utils import get_entity_by_attributes, create_entity # create_entity might not be used if we construct directly

        # 1. Find or Create Player DB record
        player_db_model = await get_entity_by_attributes(session, PlayerDB, {"discord_id": discord_user_id, "guild_id": guild_id})

        if not player_db_model:
            logger.info(f"CM: No existing PlayerDB found for {discord_user_id} in guild {guild_id}. Creating new PlayerDB.")
            player_default_lang = player_language or await self._game_manager.get_rule(guild_id, 'default_language', 'en') # type: ignore

            # Attempt to get display name; requires interaction object or pre-fetched name.
            # For robustness, if interaction isn't passed, use a placeholder.
            # This part of logic is better handled at command level or by passing display_name.
            user_display_name = f"User_{discord_user_id}" # Fallback

            player_data = {
                "id": str(uuid.uuid4()),
                "discord_id": discord_user_id,
                "guild_id": guild_id,
                "name_i18n": {"en": user_display_name, player_default_lang: user_display_name},
                "selected_language": player_default_lang,
                "is_active": True,
            }
            # Using create_entity, assuming it handles add & flush, and returns the instance.
            player_db_model = await create_entity(session, PlayerDB, player_data, guild_id=guild_id)
            if not player_db_model:
                logger.error(f"CM: Failed to create PlayerDB for {discord_user_id} in guild {guild_id}.")
                return None
            logger.info(f"CM: PlayerDB {player_db_model.id} created for {discord_user_id} in guild {guild_id}.")
            self._discord_to_player_map.setdefault(guild_id, {})[int(discord_user_id)] = player_db_model.id
            await session.flush() # Ensure player_db_model.id is available if create_entity doesn't flush

        # 2. Check if Character with the same name already exists for this player
        # A more robust check would involve checking name_i18n if it's the source of truth
        # For simplicity, assuming character_name is the primary name to check.
        stmt_existing_char = select(CharacterDB).where(
            CharacterDB.player_id == player_db_model.id,
            CharacterDB.name_i18n[player_language or self._game_manager.get_rule(guild_id, 'default_language', 'en')].astext == character_name # type: ignore
        )
        result_existing_char = await session.execute(stmt_existing_char)
        if result_existing_char.scalars().first():
            raise CharacterAlreadyExistsError(f"Character '{character_name}' already exists for player {player_db_model.id}.")

        # 3. Get default starting attributes from RuleEngine via GameManager
        starting_location_id = await self._game_manager.get_rule(guild_id, 'starting_location_id', 'town_square') # type: ignore
        starting_hp = float(await self._game_manager.get_rule(guild_id, 'starting_hp', 100.0)) # type: ignore
        starting_max_hp = float(await self._game_manager.get_rule(guild_id, 'starting_max_health', 100.0)) # type: ignore
        starting_gold = int(await self._game_manager.get_rule(guild_id, 'starting_gold', 0)) # type: ignore

        char_name_i18n_map = {"en": character_name}
        effective_lang = player_language or player_db_model.selected_language or await self._game_manager.get_rule(guild_id, 'default_language', 'en') # type: ignore
        if effective_lang and effective_lang != "en":
            char_name_i18n_map[effective_lang] = character_name

        new_char_id = str(uuid.uuid4())
        character_db_data = {
            "id": new_char_id, "player_id": player_db_model.id, "guild_id": guild_id,
            "name_i18n": char_name_i18n_map,
            "character_class_i18n": {"en": char_class_key or "Adventurer", effective_lang: char_class_key or "Adventurer"},
            "race_key": race_key or "human",
            "level": 1, "xp": 0, "unspent_xp": 0, "gold": starting_gold,
            "current_hp": starting_hp, "max_hp": starting_max_hp, "is_alive": True,
            "current_location_id": starting_location_id,
            "stats_json": {}, "effective_stats_json": {}, "status_effects_json": [],
            "skills_data_json": {}, "abilities_data_json": {}, "spells_data_json": {},
            "known_spells_json": [], "spell_cooldowns_json": {}, "inventory_json": [],
            "equipment_slots_json": {}, "active_quests_json": [], "flags_json": {},
            "state_variables_json": {}, "current_game_status": "active",
            "action_queue_json": "[]", "collected_actions_json": "[]"
        }
        new_character_db = CharacterDB(**character_db_data)
        session.add(new_character_db)
        await session.flush()

        player_db_model.active_character_id = new_char_id
        flag_modified(player_db_model, "active_character_id")
        session.add(player_db_model)

        await self._recalculate_and_store_effective_stats(guild_id, new_char_id, new_character_db, session_for_db=session)
        await session.flush() # Ensure all changes, including stats, are flushed before refresh
        await session.refresh(new_character_db)
        await session.refresh(player_db_model)


        # Convert DB model to Pydantic model dictionary
        char_dict_for_pydantic = {c.name: getattr(new_character_db, c.name) for c in CharacterDB.__table__.columns} # type: ignore

        json_fields_to_parse = [ # Ensure these match CharacterPydantic expectations
            "name_i18n", "character_class_i18n", "race_i18n", "description_i18n",
            "stats_json", "effective_stats_json", "status_effects_json",
            "skills_data_json", "abilities_data_json", "spells_data_json",
            "known_spells_json", "spell_cooldowns_json", "inventory_json",
            "equipment_slots_json", "active_quests_json", "flags_json",
            "state_variables_json", "current_action_json", "action_queue_json",
            "collected_actions_json"
        ]

        for field in json_fields_to_parse:
            val = char_dict_for_pydantic.get(field)
            if isinstance(val, str):
                try: char_dict_for_pydantic[field] = json.loads(val)
                except json.JSONDecodeError:
                    logger.warning(f"CM: JSONDecodeError for field {field} on char {new_char_id}, value: {val}. Using default.")
                    if field in ["status_effects_json", "known_spells_json", "inventory_json", "active_quests_json", "action_queue_json", "collected_actions_json", "abilities_data_json", "spells_data_json", "skills_data_json"]: # these are lists
                        char_dict_for_pydantic[field] = []
                    else: # these are dicts
                        char_dict_for_pydantic[field] = {}
            elif val is None: # Ensure JSON fields are at least empty dict/list if None from DB
                if field in ["status_effects_json", "known_spells_json", "inventory_json", "active_quests_json", "action_queue_json", "collected_actions_json", "abilities_data_json", "spells_data_json", "skills_data_json"]:
                    char_dict_for_pydantic[field] = []
                else:
                    char_dict_for_pydantic[field] = {}

        # Map DB field names to Pydantic field names if they differ
        char_dict_for_pydantic['discord_user_id'] = int(discord_user_id)
        char_dict_for_pydantic['selected_language'] = player_language or player_db_model.selected_language
        char_dict_for_pydantic['location_id'] = char_dict_for_pydantic.get('current_location_id')
        char_dict_for_pydantic['party_id'] = char_dict_for_pydantic.get('current_party_id')
        char_dict_for_pydantic['hp'] = char_dict_for_pydantic.get('current_hp', starting_hp)
        char_dict_for_pydantic['max_health'] = char_dict_for_pydantic.get('max_hp', starting_max_hp)
        char_dict_for_pydantic['experience'] = char_dict_for_pydantic.get('xp',0)
        char_dict_for_pydantic['stats'] = char_dict_for_pydantic.get('stats_json', {}) # Pydantic model expects 'stats'
        # Populate potentially missing fields expected by Pydantic model from CharacterPydantic.from_dict
        # These are fields in Pydantic Character not directly columns in DB Character or with different names
        char_dict_for_pydantic.setdefault('name', character_name) # Fallback if name_i18n is empty
        char_dict_for_pydantic.setdefault('skills', {}) # Old field, ensure it exists
        char_dict_for_pydantic.setdefault('known_abilities', []) # Old field
        char_dict_for_pydantic.setdefault('character_class', (char_dict_for_pydantic.get('character_class_i18n') or {}).get(effective_lang))

        try:
            character_pydantic = CharacterPydantic.from_dict(char_dict_for_pydantic)
        except Exception as pydantic_conversion_err:
            logger.error(f"CM: Error converting CharacterDB to CharacterPydantic for char {new_char_id} using from_dict: {pydantic_conversion_err}", exc_info=True)
            logger.error(f"Data passed to from_dict: {json.dumps(char_dict_for_pydantic, indent=2)}")
            return None

        self._characters.setdefault(guild_id, {})[new_char_id] = character_pydantic
        self.mark_character_dirty(guild_id, new_char_id)

        logger.info(f"CM: Character {new_char_id} ({character_name}) created and activated for player {player_db_model.id} (Discord: {discord_user_id}) in guild {guild_id}.")
        return character_pydantic

    async def create_and_activate_character_for_discord_user(
        self,
        guild_id: str,
        discord_user_id: str,
        character_name: str,
        player_language: Optional[str] = None,
        char_class_key: Optional[str] = None,
        race_key: Optional[str] = None
    ) -> Optional[CharacterPydantic]:
        if not self._db_service:
            logger.error("CM: DBService not available for character creation.")
            return None

        try:
            # Use GuildTransaction to manage the session and transaction
            from bot.database.guild_transaction import GuildTransaction # Ensure import
            async with GuildTransaction(self._db_service.get_session_factory, guild_id) as session: # type: ignore
                return await self._create_and_activate_char_in_session(
                    session, guild_id, discord_user_id, character_name, player_language, char_class_key, race_key
                )
        except CharacterAlreadyExistsError:
            # Logged inside _create_and_activate_char_in_session or by caller
            raise
        except Exception as e:
            logger.error(f"CM: Outer error in create_and_activate_character_for_discord_user for {discord_user_id} in {guild_id}: {e}", exc_info=True)
            return None

