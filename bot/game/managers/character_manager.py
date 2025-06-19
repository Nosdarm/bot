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

        try:
            async with actual_session.begin() if manage_session else actual_session.begin_nested(): # type: ignore
                char_model = await actual_session.get(Character, character_id)
                if not char_model or str(char_model.guild_id) != guild_id:
                    logger.warning(f"CM.update_health: Character {character_id} not found in guild {guild_id}.")
                    return None

        guild_id_str = str(player_account.guild_id)

        name_check_stmt = select(Character).where(
            Character.guild_id == guild_id_str,
            Character.name_i18n.op('->>')('en') == character_name
        )
        existing_char_by_name_result = await session.execute(name_check_stmt)
        if existing_char_by_name_result.scalars().first():
            logger.warning(f"Character with name '{character_name}' already exists in guild {guild_id_str}.")
            raise CharacterAlreadyExistsError(f"A character with the name '{character_name}' already exists in this guild.")

        new_char_id = str(uuid.uuid4())

        # Fetch starting rules
        starting_base_stats_rule = await self._game_manager.get_rule(guild_id_str, "starting_base_stats", default={"strength": 8,"dexterity": 8,"constitution": 8,"intelligence": 8,"wisdom": 8,"charisma": 8})
        starting_items_rules = await self._game_manager.get_rule(guild_id_str, "starting_items", default=[])
        starting_skills_rules = await self._game_manager.get_rule(guild_id_str, "starting_skills", default=[])
        starting_abilities_rules = await self._game_manager.get_rule(guild_id_str, "starting_abilities", default=[])
        starting_character_class_key = await self._game_manager.get_rule(guild_id_str, "starting_character_class", default="commoner")
        starting_race_key = await self._game_manager.get_rule(guild_id_str, "starting_race", default="human")
        starting_mp = await self._game_manager.get_rule(guild_id_str, "starting_mp", default=10)
        starting_attack_base = await self._game_manager.get_rule(guild_id_str, "starting_attack_base", default=1)
        starting_defense_base = await self._game_manager.get_rule(guild_id_str, "starting_defense_base", default=0)

        con_stat = float(starting_base_stats_rule.get("constitution", 8))
        base_hp = kwargs.get('hp', con_stat * 10 + 50)
        base_max_health = kwargs.get('max_health', base_hp)

        resolved_initial_location_id = initial_location_id
        if not resolved_initial_location_id:
            default_loc_static_id = await self._game_manager.get_rule(guild_id_str, "default_starting_location_id", "village_square")
            if self._location_manager:
                loc_obj = await self._location_manager.get_location_by_static_id(guild_id_str, default_loc_static_id, session=session)
                if loc_obj:
                    resolved_initial_location_id = loc_obj.id
                else:
                    logger.error(f"Default starting location '{default_loc_static_id}' (static_id) not found for guild {guild_id_str}.")
                    resolved_initial_location_id = None # Or raise error
            else:
                logger.error("LocationManager not available, cannot resolve default starting location.")
                resolved_initial_location_id = None

        char_data_dict = {
            "id": new_char_id, "player_id": player_id, "guild_id": guild_id_str,
            "name_i18n": {"en": character_name},
            "character_class_key": starting_character_class_key, # Assuming model has character_class_key
            "race_key": starting_race_key, # Assuming model has race_key
            "level": level, "xp": experience, "unspent_xp": unspent_xp,
            "gold": kwargs.get('gold', 0),
            "current_hp": base_hp, "max_hp": base_max_health,
            "mp": float(starting_mp), # Changed to 'mp' to match Character model
            "base_attack": starting_attack_base,
            "base_defense": starting_defense_base,
            "is_alive": True,
            "stats_json": json.dumps(starting_base_stats_rule),
            "effective_stats_json": json.dumps({}),
            "status_effects_json": json.dumps([]),
            "skills_data_json": json.dumps(starting_skills_rules),
            "abilities_data_json": json.dumps(starting_abilities_rules),
            "spells_data_json": json.dumps([]),
            "known_spells_json": json.dumps([]),
            "spell_cooldowns_json": json.dumps({}),
            "inventory_json": json.dumps([]),
            "equipment_slots_json": json.dumps({}),
            "active_quests_json": json.dumps([]),
            "flags_json": json.dumps({}),
            "state_variables_json": json.dumps({}),
            "current_game_status": "active",
            "current_action_json": None,
            "action_queue_json": json.dumps([]),
            "collected_actions_json": None,
            "current_location_id": resolved_initial_location_id,
            "current_party_id": None,
            # is_active_character is NOT on the Character model in the new design. It's on Player.
        }

        new_character = Character(**char_data_dict)
        session.add(new_character)

        player_account.active_character_id = new_char_id
        session.add(player_account)

        if self._item_manager: # Ensure item_manager exists
            for item_info in starting_items_rules:
                template_id = item_info.get("template_id")
                quantity = item_info.get("quantity", 1)
                state_vars = item_info.get("state_variables")
                if template_id:
                    try:
                        await self._item_manager.create_and_add_item_to_character_inventory(
                            guild_id=guild_id_str, character_id=new_char_id,
                            item_template_id=template_id, quantity=quantity,
                            state_variables=state_vars, session=session
                        )
                        logger.info(f"Granted starting item {template_id} (x{quantity}) to character {new_char_id}")
                    except Exception as item_ex:
                        logger.error(f"Error granting starting item {template_id} to char {new_char_id}: {item_ex}", exc_info=True)
                        raise

        await session.flush()

        self._characters.setdefault(guild_id_str, {})[new_char_id] = new_character

        await self._recalculate_and_store_effective_stats(guild_id_str, new_char_id, new_character)

        logger.info(f"CharacterManager: Character '{character_name}' (ID: {new_char_id}) creation process complete for Player {player_id} in guild {guild_id_str}.")
        return new_character

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


