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

    async def create_new_character(
        self,
        guild_id: str,
        user_id: int,  # Discord User ID
        character_name: str,
        language: str, # Effective language for character
        session: Optional[AsyncSession] = None # Optional session for transaction control
    ) -> Optional[Character]:
        """
        Creates a new character for a given player (user_id) in a guild.
        """
        if not self._db_service or not self._game_manager or not self._rule_engine or not self._location_manager:
            logger.error(f"CM.create_new_character: Required services (DB, GameManager, RuleEngine, LocationManager) not available for guild {guild_id}.")
            return None

        guild_id_str = str(guild_id)
        discord_id_str = str(user_id)
        
        manage_session = session is None
        # This variable will hold the actual session object to be used for DB operations.
        active_db_session: AsyncSession 
        player_record: Optional[Player] = None # Initialize player_record
        new_char_orm_instance: Optional[Character] = None 

        if manage_session:
            # DBService.get_session() is an async context manager.
            # We enter it, and it yields the actual session instance.
            # This outer context manager should handle the overall transaction commit/rollback.
            async with self._db_service.get_session() as session_instance: # type: ignore
                active_db_session = session_instance
                # All operations within this block use active_db_session.
                # No explicit .begin() here, assuming the get_session() context manager handles it.
                try:
                    from bot.database.crud_utils import get_entity_by_attributes
                    player_record = await get_entity_by_attributes(active_db_session, Player, {"discord_id": discord_id_str}, guild_id=guild_id_str)

                    if not player_record:
                        logger.error(f"CM.create_new_character: Player record not found for Discord ID {discord_id_str} in guild {guild_id_str}. Character creation aborted.")
                        return None

                    if player_record.active_character_id:
                        existing_char_check = await active_db_session.get(Character, player_record.active_character_id)
                        if existing_char_check and str(existing_char_check.guild_id) == guild_id_str:
                            logger.info(f"CM.create_new_character: Player {player_record.id} (Discord: {discord_id_str}) already has an active character {player_record.active_character_id}.")
                            raise CharacterAlreadyExistsError(f"Player already has an active character.")
                        else:
                            logger.warning(f"CM.create_new_character: Player {player_record.id} had an invalid active_character_id {player_record.active_character_id}. Clearing.")
                            player_record.active_character_id = None
                            flag_modified(player_record, "active_character_id")
                    
                    new_character_id = str(uuid.uuid4())
                    default_hp = await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.hp", 100.0)
                    default_max_hp = await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.max_hp", 100.0)
                    default_location_id = await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.starting_location_id", "default_start_location")
                    
                    starting_location = await self._location_manager.get_location_by_id(guild_id_str, default_location_id, session=active_db_session)
                    if not starting_location:
                        logger.error(f"CM.create_new_character: Default starting location '{default_location_id}' not found for guild {guild_id_str}. Character might have invalid location.")

                    character_data = {
                        "id": new_character_id, "player_id": player_record.id, "guild_id": guild_id_str,
                        "name_i18n": {language: character_name, "en": character_name},
                        "description_i18n": {"en": "A new adventurer.", language: "Новый искатель приключений."},
                        "current_hp": float(default_hp), "max_hp": float(default_max_hp),
                        "current_mp": 0.0, "max_mp": 0.0, "level": 1, "xp": 0, "unspent_xp": 0,
                        "gold": await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.gold", 10),
                        "base_stats_json": json.dumps(await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.base_stats", {"strength":10, "dexterity":10, "constitution":10, "intelligence":10, "wisdom":10, "charisma":10})),
                        "skills_json": "{}", "inventory_json": "[]", "equipment_json": "{}", 
                        "status_effects_json": "[]", "current_location_id": default_location_id if starting_location else None,
                        "action_queue_json": "[]", "current_action_json": None, "is_alive": True, "party_id": None,
                        "effective_stats_json": "{}", "abilities_json": "[]", "spellbook_json": "[]",
                        "race": await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.race", "human"),
                        "char_class": await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.char_class", "adventurer"),
                        "appearance_json": json.dumps({"description": "An ordinary looking individual."}),
                        "backstory_json": json.dumps({"summary": "A mysterious past."}),
                        "personality_json": json.dumps({"traits": ["brave"]}),
                        "relationships_json": "{}", "quests_json": "[]", "flags_json": "{}"
                    }
                    
                    new_char_orm = Character(**character_data)
                    await self._recalculate_and_store_effective_stats(guild_id_str, new_char_orm.id, new_char_orm, session_for_db=active_db_session)
                    active_db_session.add(new_char_orm)
                    
                    player_record.active_character_id = new_char_orm.id
                    flag_modified(player_record, "active_character_id")
                    active_db_session.add(player_record)
                    
                    new_char_orm_instance = new_char_orm # For caching after successful commit by context manager
                
                except CharacterAlreadyExistsError as caee:
                    logger.info(f"CM.create_new_character (managed session): Character already exists for Discord ID {discord_id_str} in guild {guild_id_str}.")
                    raise caee # Let the context manager handle rollback due to exception
                except Exception as e:
                    logger.error(f"CM.create_new_character (managed session): Error for Discord ID {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
                    # Let the context manager handle rollback
                    return None # Or re-raise e if preferred

        else: # manage_session is False, session was passed in
            active_db_session = session
            try:
                # Assuming the passed session is already in a transaction or caller handles it.
                # If a savepoint is desired within the caller's transaction:
                async with active_db_session.begin_nested(): # type: ignore 
                    from bot.database.crud_utils import get_entity_by_attributes
                    player_record = await get_entity_by_attributes(active_db_session, Player, {"discord_id": discord_id_str}, guild_id=guild_id_str)

                    if not player_record:
                        logger.error(f"CM.create_new_character (external session): Player record not found for Discord ID {discord_id_str} in guild {guild_id_str}.")
                        return None

                    if player_record.active_character_id:
                        existing_char_check = await active_db_session.get(Character, player_record.active_character_id)
                        if existing_char_check and str(existing_char_check.guild_id) == guild_id_str:
                            raise CharacterAlreadyExistsError(f"Player already has an active character.")
                        else:
                            player_record.active_character_id = None
                            flag_modified(player_record, "active_character_id")
                    
                    new_character_id = str(uuid.uuid4())
                    # ... (character_data creation as above, using active_db_session for rule/location lookups if necessary for some reason, though unlikely)
                    default_hp = await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.hp", 100.0)
                    default_max_hp = await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.max_hp", 100.0)
                    default_location_id = await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.starting_location_id", "default_start_location")
                    starting_location = await self._location_manager.get_location_by_id(guild_id_str, default_location_id, session=active_db_session)

                    character_data = {
                        "id": new_character_id, "player_id": player_record.id, "guild_id": guild_id_str,
                        "name_i18n": {language: character_name, "en": character_name},
                        "description_i18n": {"en": "A new adventurer.", language: "Новый искатель приключений."},
                        "current_hp": float(default_hp), "max_hp": float(default_max_hp), "current_mp": 0.0, "max_mp": 0.0,
                        "level": 1, "xp": 0, "unspent_xp": 0,
                        "gold": await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.gold", 10),
                        "base_stats_json": json.dumps(await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.base_stats", {"strength":10, "dexterity":10, "constitution":10, "intelligence":10, "wisdom":10, "charisma":10})),
                        "skills_json": "{}", "inventory_json": "[]", "equipment_json": "{}", "status_effects_json": "[]",
                        "current_location_id": default_location_id if starting_location else None,
                        "action_queue_json": "[]", "current_action_json": None, "is_alive": True, "party_id": None,
                        "effective_stats_json": "{}", "abilities_json": "[]", "spellbook_json": "[]",
                        "race": await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.race", "human"),
                        "char_class": await self._rule_engine.get_rule_value(guild_id_str, "character_creation.defaults.char_class", "adventurer"),
                        "appearance_json": json.dumps({"description": "An ordinary looking individual."}),
                        "backstory_json": json.dumps({"summary": "A mysterious past."}),
                        "personality_json": json.dumps({"traits": ["brave"]}),
                        "relationships_json": "{}", "quests_json": "[]", "flags_json": "{}"
                    }
                    new_char_orm = Character(**character_data)
                    await self._recalculate_and_store_effective_stats(guild_id_str, new_char_orm.id, new_char_orm, session_for_db=active_db_session)
                    active_db_session.add(new_char_orm)
                    
                    player_record.active_character_id = new_char_orm.id
                    flag_modified(player_record, "active_character_id")
                    active_db_session.add(player_record)
                    new_char_orm_instance = new_char_orm
            
            except CharacterAlreadyExistsError as caee:
                logger.info(f"CM.create_new_character (external session): Character already exists for Discord ID {discord_id_str} in guild {guild_id_str}.")
                raise caee # Let caller's transaction context handle rollback
            except Exception as e:
                logger.error(f"CM.create_new_character (external session): Error for Discord ID {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
                # Let caller's transaction context handle rollback
                return None # Or re-raise e

        # Cache update happens after successful operation, outside explicit transaction blocks
        if (new_char_orm_instance is not None) and (player_record is not None):
            self._characters.setdefault(guild_id_str, {})[new_char_orm_instance.id] = new_char_orm_instance
            self._discord_to_player_map.setdefault(guild_id_str, {})[user_id] = player_record.id # type: ignore
            logger.info(f"CM.create_new_character: Successfully created and cached Character {new_char_orm_instance.id} for Player {player_record.id} in guild {guild_id_str}. Cached (pending caller's commit if session was external).") # type: ignore

        return new_char_orm_instance
-
-        except CharacterAlreadyExistsError as caee:
-            logger.info(f"CM.create_new_character: Attempt to create character for Discord ID {discord_id_str} in guild {guild_id_str} failed as character already exists.")
-            # Rollback is handled by transaction_cm's __aexit__ if an exception occurs
-            raise caee
-        except Exception as e:
-            logger.error(f"CM.create_new_character: Error creating character for Discord ID {discord_id_str} in guild {guild_id_str}: {e}", exc_info=True)
-            # Rollback is handled by transaction_cm's __aexit__
-            return None
-        finally:
-            if manage_session and outer_session_cm:
-                await outer_session_cm.__aexit__(None, None, None)


