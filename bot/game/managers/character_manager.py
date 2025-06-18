# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import logging
import asyncpg
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from bot.database.models import Player, Character # New SQLAlchemy models
# from bot.game.models.character import Character # Old Pydantic model - REMOVED
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

class CharacterManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    _characters: Dict[str, Dict[str, Character]] # GuildID -> CharacterID -> Character (SQLAlchemy model)
    _discord_to_player_map: Dict[str, Dict[int, str]] # GuildID -> DiscordUserID -> PlayerID
    _entities_with_active_action: Dict[str, Set[str]] # GuildID -> Set of CharacterIDs
    _dirty_characters: Dict[str, Set[str]] # GuildID -> Set of CharacterIDs
    _deleted_characters_ids: Dict[str, Set[str]] # GuildID -> Set of CharacterIDs

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
        logger.info("Initializing CharacterManager with new Player/Character model structure...")
        self._db_service = db_service
        self._settings = settings
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
        logger.info("CharacterManager initialized with new cache structure.")

    async def _recalculate_and_store_effective_stats(self, guild_id: str, character_id: str, char_model: Optional[Character] = None) -> None:
        if not char_model: # char_model is now SQLAlchemy Character
            char_model = self.get_character(guild_id, character_id)
            if not char_model:
                logger.error(f"CharacterManager: Character {character_id} not found in guild {guild_id} for effective stats recalc.")
                return

        if not self._game_manager:
            logger.warning(f"CharacterManager: GameManager not available, cannot recalculate effective_stats for char {character_id} in guild {guild_id}.")
            char_model.effective_stats_json = json.dumps({"error": "game_manager_unavailable"}) # Directly set on SQLAlchemy model
            return
        try:
            effective_stats_dict = await stats_calculator.calculate_effective_stats(
                entity=char_model,
                guild_id=guild_id,
                game_manager=self._game_manager
            )
            char_model.effective_stats_json = json.dumps(effective_stats_dict or {})
            logger.debug(f"CharacterManager: Recalculated effective_stats for character {character_id} in guild {guild_id}.")
        except Exception as es_ex:
            logger.error(f"CharacterManager: ERROR recalculating effective_stats for char {character_id} in guild {guild_id}: {es_ex}", exc_info=True)
            char_model.effective_stats_json = json.dumps({"error": "calculation_failed"})

    async def trigger_stats_recalculation(self, guild_id: str, character_id: str) -> None:
        char = self.get_character(guild_id, character_id) # Fetches SQLAlchemy Character
        if char:
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            self.mark_character_dirty(guild_id, character_id)
            logger.info(f"CharacterManager: Stats recalculation triggered for char {character_id} in guild {guild_id} and marked dirty.")
        else:
            logger.warning(f"CharacterManager: trigger_stats_recalculation - Character {character_id} not found in guild {guild_id}.")

    def get_character(self, guild_id: str, character_id: str) -> Optional[Character]: # Returns SQLAlchemy Character
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars:
             return guild_chars.get(character_id)
        logger.debug(f"Character {character_id} not found in cache for guild {guild_id}.")
        return None

    async def get_character_by_discord_id(self, guild_id: str, discord_user_id: int, session: Optional[AsyncSession] = None) -> Optional[Character]:
        guild_id_str = str(guild_id)
        player_id = self._discord_to_player_map.get(guild_id_str, {}).get(discord_user_id)
        active_character_id_to_fetch = None

        db_session_managed_locally = False
        if session is None and self._db_service:
            session = self._db_service.get_session() # type: ignore
            db_session_managed_locally = True

        if not session:
            logger.warning(f"Cannot get character by discord_id {discord_user_id} without a database session.")
            return None
        try:
            if player_id:
                player_obj = await session.get(Player, player_id)
                if player_obj and str(player_obj.guild_id) == guild_id_str:
                    active_character_id_to_fetch = player_obj.active_character_id
                else:
                    logger.warning(f"Player {player_id} (from cache for Discord ID {discord_user_id}) not found in DB or guild mismatch.")
                    return None
            else:
                from bot.database.crud_utils import get_entity_by_attributes
                player_account = await get_entity_by_attributes(session, Player, {"discord_id": str(discord_user_id)}, guild_id_str)
                if player_account:
                    self._discord_to_player_map.setdefault(guild_id_str, {})[discord_user_id] = player_account.id
                    active_character_id_to_fetch = player_account.active_character_id
                else:
                    logger.info(f"Player account not found in DB for Discord ID {discord_user_id} in guild {guild_id_str}.")
                    return None
        finally:
            if db_session_managed_locally and session:
                await session.close()

        if active_character_id_to_fetch:
            return self.get_character(guild_id_str, active_character_id_to_fetch)
        else:
            logger.debug(f"Player for Discord ID {discord_user_id} has no active character set in guild {guild_id_str}.")
            return None

    def get_character_by_name(self, guild_id: str, name: str) -> Optional[Character]: # Returns SQLAlchemy Character
         guild_chars = self._characters.get(str(guild_id))
         if guild_chars:
              for char_model in guild_chars.values(): # char_model is SQLAlchemy Character
                  if isinstance(char_model.name_i18n, dict):
                      if any(n.lower() == name.lower() for n in char_model.name_i18n.values()):
                          return char_model
                  # Fallback for older data if name_i18n was stored as string by mistake
                  elif isinstance(char_model.name_i18n, str) and char_model.name_i18n.lower() == name.lower():
                      return char_model
         return None

    def get_all_characters(self, guild_id: str) -> List[Character]: # Returns List of SQLAlchemy Character
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars:
             return list(guild_chars.values())
        return []

    def get_characters_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List[Character]:
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        characters_in_location = []
        guild_chars = self._characters.get(guild_id_str)
        if guild_chars:
             for char_model in guild_chars.values(): # char_model is SQLAlchemy Character
                 if str(char_model.current_location_id) == location_id_str:
                      characters_in_location.append(char_model)
        return characters_in_location

    def get_entities_with_active_action(self, guild_id: str) -> Set[str]:
        return self._entities_with_active_action.get(str(guild_id), set()).copy()

    def is_busy(self, guild_id: str, character_id: str) -> bool:
        char = self.get_character(guild_id, character_id) # Fetches SQLAlchemy Character
        if not char: return False
        # Accessing JSON fields directly from SQLAlchemy model
        if char.current_action_json or (char.action_queue_json and json.loads(char.action_queue_json or "[]")): return True

        if char.current_party_id is not None and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
            if char.current_party_id: # Ensure it's not None before passing
                return self._party_manager.is_party_busy(str(guild_id), char.current_party_id)
        return False

    async def create_character(
        self,
        player_id: str,
        character_name: str,
        guild_id_verification: str,
        session: AsyncSession, # Expect session to be passed, typically from GuildTransaction
        initial_location_id: Optional[str] = None,
        level: int = 1,
        experience: int = 0,
        unspent_xp: int = 0,
        **kwargs: Any
    ) -> Optional[Character]: # Returns SQLAlchemy Character
        if not self._game_manager:
            logger.error("CharacterManager: GameManager not available for create_character.")
            raise ValueError("GameManager not available for character creation.")
        if not self._item_manager:
            logger.error("CharacterManager: ItemManager not available for create_character.")
            raise ValueError("ItemManager not available for character creation.")

        player_account = await session.get(Player, player_id)
        if not player_account:
            logger.error(f"Player account {player_id} not found for create_character.")
            return None
        if str(player_account.guild_id) != str(guild_id_verification):
            logger.error(f"Player account {player_id} guild_id {player_account.guild_id} does not match verification guild_id {guild_id_verification}.")
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

    def mark_character_deleted(self, guild_id: str, character_id: str) -> None:
        logger.info(f"CharacterManager: Marking character {character_id} for deletion in guild {guild_id}.")
        guild_id_str = str(guild_id)
        char_to_delete = self._characters.get(guild_id_str, {}).pop(character_id, None)

        if char_to_delete:
            # Player mapping cleanup is harder here as Character model doesn't store discord_id directly.
            # This might need to be handled when Player.active_character_id is unset.
            self._entities_with_active_action.get(guild_id_str, set()).discard(character_id)
            self._deleted_characters_ids.setdefault(guild_id_str, set()).add(character_id)
            logger.info(f"CharacterManager: Character {character_id} removed from active cache and marked for DB deletion in guild {guild_id_str}.")
        else:
            logger.warning(f"CharacterManager: Attempted to mark non-existent character {character_id} for deletion in guild {guild_id_str}.")


    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_party_id = str(party_id) if party_id else None
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Set current_party_id to {party_id} for char {character_id} in guild {guild_id}.")
            return True
        logger.warning(f"CharacterManager: Char {character_id} not found in guild {guild_id} to set current_party_id.")
        return False

    async def update_character_location(self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any) -> Optional[Character]:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_location_id = str(location_id) if location_id else None
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Updated location for char {character_id} to {location_id} in guild {guild_id}.")
            return char
        logger.warning(f"CharacterManager: Char {character_id} not found in guild {guild_id} to update location.")
        return None

    async def add_item_to_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
        logger.debug(f"CharacterManager: add_item_to_inventory called for char {character_id}, item {item_id}, quantity {quantity}. Needs ItemManager integration with Character.inventory_json or separate Inventory table.")
        char = self.get_character(guild_id, character_id)
        if char and self._item_manager:
            # This is conceptual; assumes ItemManager is updated to work with character_id and a session
            # and potentially Character.inventory_json if that's the chosen inventory storage method.
            # success = await self._item_manager.add_item_to_character_inventory(guild_id, character_id, item_id, quantity, session=kwargs.get('session'))
            # if success:
            #    self.mark_character_dirty(guild_id, character_id) # If inventory_json is on Character
            #    await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            #    return True
            pass
        return False

    async def remove_item_from_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
        logger.debug(f"CharacterManager: remove_item_from_inventory for char {character_id}, item {item_id}, quantity {quantity}. Needs ItemManager integration.")
        return False

    async def update_health(self, guild_id: str, character_id: str, amount: float, **kwargs: Any) -> bool:
         char = self.get_character(guild_id, character_id)
         if not char:
             logger.warning(f"CharacterManager: Char {character_id} not found in guild {guild_id} for health update.")
             return False

         old_hp_val = char.current_hp if char.current_hp is not None else 0.0
         old_is_alive_val = char.is_alive

         if not old_is_alive_val and amount <= 0:
             logger.debug(f"CharacterManager: Char {character_id} in guild {guild_id} already not alive and damage applied, no change.")
             return False

         current_max_hp = char.max_hp if char.max_hp is not None else 0.0
         try:
             effective_stats = json.loads(char.effective_stats_json or '{}')
             current_max_hp = float(effective_stats.get('max_hp', char.max_hp if char.max_hp is not None else 0.0))
         except (json.JSONDecodeError, ValueError):
             logger.warning(f"Could not parse effective_stats_json for max_hp on char {character_id}. Using base max_hp.")

         char.current_hp = max(0.0, min(current_max_hp, old_hp_val + amount))
         new_is_alive_status = char.current_hp > 0

         hp_changed = char.current_hp != old_hp_val
         is_alive_status_changed = new_is_alive_status != old_is_alive_val
         char.is_alive = new_is_alive_status

         if hp_changed or is_alive_status_changed:
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Updated health for char {character_id}. HP: {old_hp_val} -> {char.current_hp}. Alive: {old_is_alive_val} -> {char.is_alive}.")

         if char.current_hp <= 0 and old_is_alive_val:
              logger.info(f"CharacterManager: Character {character_id} in guild {guild_id} has died.")
              await self.handle_character_death(guild_id, character_id, **kwargs)
         return True

    async def update_character_stats(self, guild_id: str, character_id: str, stats_update: Dict[str, Any], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if not char:
            logger.warning(f"CharacterManager: Char {character_id} not found for stats update.")
            return False

        updated_fields = []
        recalc_needed = False

        base_stats = json.loads(char.stats_json or '{}')
        original_base_stats_json_str = char.stats_json

        for key, value in stats_update.items():
            if key == "current_hp":
                await self.update_health(guild_id, character_id, float(value) - (char.current_hp or 0.0), **kwargs)
                updated_fields.append(f"current_hp to {char.current_hp}")
                continue
            elif key in ["current_mp", "gold", "level", "xp", "unspent_xp", "max_hp", "max_mp", "base_attack", "base_defense"]: # Direct Character attributes
                 if hasattr(char, key) and getattr(char, key) != value:
                    setattr(char, key, value)
                    updated_fields.append(f"{key} to {value}")
                    if key not in ["current_mp", "gold"]:
                        recalc_needed = True
            elif key in base_stats: # Modifying a base stat like "strength", "dexterity" stored in stats_json
                if base_stats.get(key) != value:
                    base_stats[key] = value
                    updated_fields.append(f"base_stat_{key} to {value}")
                    recalc_needed = True
            elif hasattr(char, key): # Other direct attributes on Character model
                if getattr(char, key) != value:
                    setattr(char, key, value)
                    updated_fields.append(f"{key} to {value}")
                    recalc_needed = True
            else:
                logger.debug(f"Key {key} not directly on Character model or in base stats for update of {character_id}.")
                continue

        new_base_stats_json_str = json.dumps(base_stats)
        if original_base_stats_json_str != new_base_stats_json_str: # Check if base_stats dict actually changed
            char.stats_json = new_base_stats_json_str
            # No need to add to updated_fields again, individual changes already noted

        if updated_fields:
            self.mark_character_dirty(guild_id, character_id)
            if recalc_needed:
                await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Updated stats for char {character_id}: {updated_fields}. Recalc_needed: {recalc_needed}.")
            return True
        logger.debug(f"No effective stat changes for char {character_id} from update: {stats_update}")
        return False

    async def handle_character_death(self, guild_id: str, character_id: str, **kwargs: Any):
        char = self.get_character(guild_id, character_id)
        if char and char.is_alive:
            char.is_alive = False
            char.current_hp = 0
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Processed death for char {character_id}. Marked not alive.")
        elif char and not char.is_alive:
             logger.info(f"CharacterManager: Character {character_id} already marked as not alive during death processing.")
        else:
             logger.warning(f"CharacterManager: Character {character_id} not found for death processing.")

    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_action_json = json.dumps(action_details) if action_details else None
            self.mark_character_dirty(guild_id, character_id)
            logger.debug(f"CharacterManager: set_active_action for char {character_id}. Action: {action_details}")
        else:
            logger.warning(f"Character {character_id} not found in guild {guild_id} to set active action.")


    def add_action_to_queue(self, guild_id: str, character_id: str, action_details: Dict[str, Any]) -> None:
        char = self.get_character(guild_id, character_id)
        if char:
            current_queue = json.loads(char.action_queue_json or "[]")
            current_queue.append(action_details)
            char.action_queue_json = json.dumps(current_queue)
            self.mark_character_dirty(guild_id, character_id)
            logger.debug(f"CharacterManager: add_action_to_queue for char {character_id}. Action: {action_details}")
        else:
            logger.warning(f"Character {character_id} not found in guild {guild_id} to add action to queue.")


    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        char = self.get_character(guild_id, character_id)
        if char:
            current_queue = json.loads(char.action_queue_json or "[]")
            if current_queue:
                next_action = current_queue.pop(0)
                char.action_queue_json = json.dumps(current_queue)
                self.mark_character_dirty(guild_id, character_id)
                logger.debug(f"CharacterManager: get_next_action_from_queue for char {character_id}. Action: {next_action}")
                return next_action
        logger.debug(f"CharacterManager: No action in queue for char {character_id}.")
        return None

    async def save_character(self, character: Character, guild_id: str) -> bool:
        if not isinstance(character, Character):
            logger.error("save_character expects a Character SQLAlchemy model instance.")
            return False
        if self._db_service is None:
            logger.error(f"CharacterManager: DB Service not available, cannot save char {character.id} in guild {guild_id}.")
            return False
        self.mark_character_dirty(guild_id, character.id)
        logger.debug(f"CharacterManager: Marked char {character.id} for saving in guild {guild_id}.")
        return True

    async def set_current_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_party_id = str(party_id) if party_id else None
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Set current_party_id to {party_id} for char {character_id} in guild {guild_id}.")
            return True
        logger.warning(f"CharacterManager: Char {character_id} not found in guild {guild_id} to set current_party_id.")
        return False

    async def save_character_field(self, guild_id: str, character_id: str, field_name: str, value: Any, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char and hasattr(char, field_name):
            setattr(char, field_name, value)
            self.mark_character_dirty(guild_id, character_id)
            if field_name in ["stats_json", "level", "is_alive", "current_hp", "max_hp", "current_mp", "max_mp", "base_attack", "base_defense"] or field_name.startswith("base_"):
                await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Saved field {field_name} to {value} for char {character_id} in guild {guild_id}.")
            return True
        logger.warning(f"CharacterManager: Field {field_name} not found or char {character_id} not found in guild {guild_id} for save_character_field.")
        return False

    async def revert_location_change(self, guild_id: str, character_id: str, old_location_id: str, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_location_id = old_location_id
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Reverted location for char {character_id} to {old_location_id} in guild {guild_id}.")
            return True
        return False

    async def revert_hp_change(self, guild_id: str, character_id: str, old_hp: float, old_is_alive: bool, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_hp = old_hp
            char.is_alive = old_is_alive
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Reverted HP for char {character_id} to {old_hp} (Alive: {old_is_alive}) in guild {guild_id}.")
            return True
        return False

    async def revert_stat_changes(self, guild_id: str, character_id: str, stat_changes: List[Dict[str, Any]], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            base_stats = json.loads(char.stats_json or '{}')
            for change in stat_changes:
                base_stats[change["stat_name"]] = change["old_value"]
            char.stats_json = json.dumps(base_stats)
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Reverted stat changes for char {character_id} in guild {guild_id} (simplified recalc).")
            return True
        return False

    async def revert_party_id_change(self, guild_id: str, character_id: str, old_party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_party_id = old_party_id
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Reverted current_party_id for char {character_id} to {old_party_id} in guild {guild_id}.")
            return True
        return False

    async def revert_xp_change(self, guild_id: str, character_id: str, old_xp: int, old_level: int, old_unspent_xp: int, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.xp = old_xp
            char.level = old_level
            char.unspent_xp = old_unspent_xp
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"CharacterManager: Reverted XP for char {character_id} to L{old_level}, {old_xp} XP, {old_unspent_xp} unspent in guild {guild_id}.")
            return True
        return False

    async def revert_status_effect_change(self, guild_id: str, character_id: str, action_taken: str, status_effect_id: str, full_status_effect_data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            current_effects = json.loads(char.status_effects_json or "[]")
            if action_taken == "added" :
                current_effects = [ef for ef in current_effects if ef.get("id") != status_effect_id]
            elif action_taken == "removed" and full_status_effect_data:
                current_effects.append(full_status_effect_data)
            char.status_effects_json = json.dumps(current_effects)
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info(f"Reverted status effect {action_taken} for {status_effect_id} on char {character_id}.")
            return True
        return False

    async def revert_inventory_changes(self, guild_id: str, character_id: str, inventory_changes: List[Dict[str, Any]], **kwargs: Any) -> bool:
        logger.debug(f"CharacterManager: revert_inventory_changes for char {character_id}. Needs proper ItemManager/inventory_json handling.")
        char = self.get_character(guild_id, character_id)
        if char:
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            return True
        return False

    async def revert_gold_change(self, guild_id: str, character_id: str, old_gold: int, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
             char.gold = old_gold
             self.mark_character_dirty(guild_id, character_id)
             logger.info(f"CharacterManager: Reverted gold for char {character_id} to {old_gold} in guild {guild_id}.")
             return True
        return False

    async def revert_action_queue_change(self, guild_id: str, character_id: str, old_action_queue_json: str, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.action_queue_json = old_action_queue_json
            self.mark_character_dirty(guild_id, character_id)
            logger.info(f"CharacterManager: Reverted action queue for char {character_id} in guild {guild_id}.")
            return True
        return False

    async def revert_collected_actions_change(self, guild_id: str, character_id: str, old_collected_actions_json: str, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.collected_actions_json = old_collected_actions_json
            self.mark_character_dirty(guild_id, character_id)
            logger.info(f"CharacterManager: Reverted collected_actions for char {character_id} in guild {guild_id}.")
            return True
        return False

    async def revert_character_creation(self, guild_id: str, character_id: str, **kwargs: Any) -> bool:
        session = kwargs.get("session")
        if not session:
            logger.error("revert_character_creation requires a session.")
            return False

        char_to_delete = await session.get(Character, character_id)
        if char_to_delete:
            if char_to_delete.player_id:
                player_account = await session.get(Player, char_to_delete.player_id)
                if player_account and player_account.active_character_id == character_id:
                    player_account.active_character_id = None
                    session.add(player_account)

            await session.delete(char_to_delete)
            if str(guild_id) in self._characters:
                self._characters[str(guild_id)].pop(character_id, None)
            logger.info(f"CharacterManager: Reverted character creation for char {character_id} (deleted from DB and cache).")
            return True
        logger.warning(f"Character {character_id} not found in DB for revert_character_creation.")
        return False

    async def recreate_character_from_data(self, guild_id: str, character_data: Dict[str, Any], **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        char_id = character_data.get('id')
        if not char_id:
            logger.error(f"CharacterManager: Cannot recreate character, missing ID in data for guild {guild_id_str}.")
            return False

        session = kwargs.get("session")
        if not session:
            logger.error("recreate_character_from_data requires a session.")
            return False

        try:
            new_char = Character(**character_data)
            await session.merge(new_char)

            if new_char.player_id: # is_active_character is not on Character model anymore
                player_account = await session.get(Player, new_char.player_id)
                if player_account and player_account.active_character_id != new_char.id : # Check if it needs to be set
                    # This logic might need refinement based on whether recreation implies making active.
                    # For now, if a character is recreated, it doesn't automatically become the active one unless explicitly set.
                    pass # player_account.active_character_id = new_char.id; session.add(player_account)

            self._characters.setdefault(guild_id_str, {})[new_char.id] = new_char
            await self._recalculate_and_store_effective_stats(guild_id_str, new_char.id, new_char)
            logger.info(f"CharacterManager: Recreated/merged character {new_char.id} from data in guild {guild_id_str}.")
            return True
        except Exception as e:
            logger.error(f"CharacterManager: Error recreating character {char_id} from data: {e}", exc_info=True)
            return False

    def level_up(self, character: Character) -> None:
        if not character:
            logger.warning("CharacterManager.level_up: Attempted to level up a None character.")
            return

        character.level = (character.level or 0) + 1
        logger.info(f"CharacterManager.level_up: Character {character.name_i18n.get('en', character.id) if isinstance(character.name_i18n, dict) else character.id} (ID: {character.id}) leveled up to {character.level}")

        base_stats = json.loads(character.stats_json or '{}')

        base_stats["strength"] = base_stats.get("strength", 8) + 1
        base_stats["dexterity"] = base_stats.get("dexterity", 8) + 1
        base_stats["constitution"] = base_stats.get("constitution", 8) + 1
        base_stats["intelligence"] = base_stats.get("intelligence", 8) + 1
        base_stats["wisdom"] = base_stats.get("wisdom", 8) + 1
        base_stats["charisma"] = base_stats.get("charisma", 8) + 1

        character.stats_json = json.dumps(base_stats)

    async def gain_xp(self, guild_id: str, character_id: str, amount: int) -> Dict[str, Any]:
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)

        if not char:
            logger.error(f"CharacterManager.gain_xp: Character {character_id} not found in guild {guild_id_str}.")
            raise ValueError(f"Character {character_id} not found in guild {guild_id_str}")

        if amount <= 0:
            logger.warning(f"CharacterManager.gain_xp: XP amount must be positive. Received {amount} for char {character_id}.")
            raise ValueError("XP amount must be positive.")

        char.xp = (char.xp or 0) + amount
        levels_gained = 0

        xp_for_next_level = (char.level or 1) * 100

        while (char.xp or 0) >= xp_for_next_level:
            char.xp -= xp_for_next_level
            self.level_up(char)
            levels_gained += 1
            xp_for_next_level = (char.level or 1) * 100

        self.mark_character_dirty(guild_id_str, character_id)
        await self._recalculate_and_store_effective_stats(guild_id_str, character_id, char)

        logger.info(f"CharacterManager.gain_xp: Character {char.id} gained {amount} XP. Levels gained: {levels_gained}. New XP: {char.xp}, New Level: {char.level}.")

        return {
            "id": char.id,
            "player_id": char.player_id,
            "guild_id": char.guild_id,
            "name_i18n": char.name_i18n,
            "character_class_key": char.character_class_key,
            "race_key": char.race_key,
            "level": char.level,
            "experience": char.xp,
            "unspent_xp": char.unspent_xp,
            "gold": char.gold,
            "current_hp": char.current_hp,
            "max_hp": char.max_hp,
            "current_mp": char.mp, # Changed from current_mp
            "max_mp": char.mp, # Assuming max_mp is same as mp for now, or derived
            "is_alive": char.is_alive,
            "stats_json": char.stats_json,
            "effective_stats_json": char.effective_stats_json,
            "levels_gained": levels_gained,
            "xp_added": amount,
            "xp_for_next_level": xp_for_next_level
        }


