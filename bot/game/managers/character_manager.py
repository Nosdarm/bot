# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import logging
# import asyncpg # Keep if other parts of the system use it directly, though not used in this file
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union, cast

from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm.attributes import flag_modified

from bot.database.models import Player, Character as CharacterDBModel
from bot.game.models.character import Character # Pydantic model
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
    from bot.game.managers.npc_manager import NPCManager # Added import
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.equipment_manager import EquipmentManager
    from bot.game.managers.game_manager import GameManager


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
            logger.warning(f"CM: GameManager NA for stats recalc: char {character_id}, guild {guild_id}.")
            return
        try:
            # Assuming char_model is Pydantic Character, which is compatible with stats_calculator.calculate_effective_stats's entity param
            effective_stats_dict = await stats_calculator.calculate_effective_stats(entity=char_model, guild_id=guild_id, game_manager=self._game_manager)

            if hasattr(char_model, 'effective_stats_json'):
                 char_model.effective_stats_json = json.dumps(effective_stats_dict or {})
            logger.debug(f"CM: Effective stats calculated for Pydantic char model {character_id}, guild {guild_id}.")
        except Exception as es_ex:
            logger.error(f"CM: ERROR recalculating stats for Pydantic char model {character_id}, guild {guild_id}: {es_ex}", exc_info=True)

    async def trigger_stats_recalculation(self, guild_id: str, character_id: str, session: Optional[AsyncSession] = None) -> None:
        char_model_pydantic = self.get_character(guild_id, character_id)
        if char_model_pydantic:
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char_model_pydantic, session_for_db=session)
            self.mark_character_dirty(guild_id, character_id)
            logger.info(f"CM: Stats recalc triggered for char {character_id}, guild {guild_id}. Marked dirty.")
        else:
            logger.warning(f"CM.trigger_stats_recalculation: Pydantic Character model {character_id} not found in guild {guild_id} cache.")

    def get_character(self, guild_id: str, character_id: str) -> Optional[Character]:
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars: return guild_chars.get(character_id)
        return None

    async def _fetch_character_logic(self, current_session: AsyncSession, guild_id_str: str, discord_user_id: int, cached_player_id: Optional[str]) -> Optional[Character]:
        active_char_id: Optional[str] = None
        resolved_player_id = cached_player_id
        fetched_player_obj_db: Optional[Player] = None

        if resolved_player_id:
            player_db = await current_session.get(Player, resolved_player_id)
            if player_db and str(player_db.guild_id) == guild_id_str:
                fetched_player_obj_db = player_db
            else:
                if guild_id_str in self._discord_to_player_map and discord_user_id in self._discord_to_player_map[guild_id_str]:
                    del self._discord_to_player_map[guild_id_str][discord_user_id]
                resolved_player_id = None

        if not resolved_player_id:
            from bot.database.crud_utils import get_entity_by_attributes # Local import
            player_db_account = await get_entity_by_attributes(current_session, Player, {"discord_id": str(discord_user_id)}, guild_id=guild_id_str)
            if player_db_account:
                self._discord_to_player_map.setdefault(guild_id_str, {})[discord_user_id] = str(player_db_account.id)
                fetched_player_obj_db = player_db_account

        if fetched_player_obj_db:
            try:
                await current_session.refresh(fetched_player_obj_db, attribute_names=['active_character_id'])
                active_char_id = fetched_player_obj_db.active_character_id
            except Exception as refresh_exc:
                logger.error(f"CM: Exception during Player refresh for active_character_id: {refresh_exc}", exc_info=True)
                active_char_id = getattr(fetched_player_obj_db, 'active_character_id', None)

        if active_char_id:
            active_char_id_str = str(active_char_id) # Ensure string
            cached_char_pydantic = self._characters.get(guild_id_str, {}).get(active_char_id_str)
            if cached_char_pydantic:
                return cached_char_pydantic

            char_db_model = await current_session.get(CharacterDBModel, active_char_id_str)
            if char_db_model and str(char_db_model.guild_id) == guild_id_str:
                char_pydantic = Character.from_db_model(char_db_model)
                self._characters.setdefault(guild_id_str, {})[char_pydantic.id] = char_pydantic
                return char_pydantic
            else:
                logger.warning(f"Active character ID {active_char_id_str} for player (Discord: {discord_user_id}) not found in DB or guild mismatch.")
                return None
        return None

    async def get_character_by_discord_id(self, guild_id: str, discord_user_id: int, session: Optional[AsyncSession] = None) -> Optional[Character]:
        guild_id_str = str(guild_id)
        player_id_in_cache = self._discord_to_player_map.get(guild_id_str, {}).get(discord_user_id)

        if session:
            # Ensure session is AsyncSession
            current_session = cast(AsyncSession, session)
            return await self._fetch_character_logic(current_session, guild_id_str, discord_user_id, player_id_in_cache)
        else:
            if not self._db_service or not hasattr(self._db_service, 'get_session') or not callable(self._db_service.get_session):
                logger.error("CM.get_character_by_discord_id: DBService or get_session not available.")
                return None
            async with self._db_service.get_session() as internal_session_context:
                internal_session = cast(AsyncSession, internal_session_context)
                return await self._fetch_character_logic(internal_session, guild_id_str, discord_user_id, player_id_in_cache)

    async def _create_new_character_core_logic(
        self, active_db_session: AsyncSession, guild_id_str: str, user_id: int,
        character_name: str, language: str, player_record: Player
    ) -> Character:
        if player_record.active_character_id:
            existing_char_db = await active_db_session.get(CharacterDBModel, str(player_record.active_character_id))
            if existing_char_db and str(existing_char_db.guild_id) == guild_id_str:
                raise CharacterAlreadyExistsError(f"Player {player_record.id} already has active character {player_record.active_character_id}.")
            else:
                player_record.active_character_id = None # type: ignore
                flag_modified(player_record, "active_character_id")

        new_character_id = str(uuid.uuid4())
        base_stats: Dict[str, Any] = {}
        default_hp = 100.0
        default_max_hp = 100.0
        starting_location_id_val: Optional[str] = self._settings.get("default_initial_location_id", "limbo")
        default_bot_lang = "en"

        if self._rule_engine and hasattr(self._rule_engine, 'get_base_stats_for_new_character') and callable(getattr(self._rule_engine, 'get_base_stats_for_new_character')):
            base_stats = await self._rule_engine.get_base_stats_for_new_character(guild_id_str, "default_player_role")
            default_hp = float(base_stats.get("hp", 100.0))
            default_max_hp = float(base_stats.get("max_health", 100.0))

        if self._location_manager and hasattr(self._location_manager, 'get_default_starting_location') and callable(getattr(self._location_manager, 'get_default_starting_location')):
            starting_location = await self._location_manager.get_default_starting_location(guild_id_str, session=active_db_session)
            if starting_location and hasattr(starting_location, 'id'):
                starting_location_id_val = str(starting_location.id)

        if self._game_manager and hasattr(self._game_manager, 'get_default_bot_language') and callable(getattr(self._game_manager, 'get_default_bot_language')):
            default_bot_lang = await self._game_manager.get_default_bot_language(guild_id_str)


        pydantic_char_data: Dict[str, Any] = {
            "id": new_character_id, "discord_user_id": user_id,
            "name_i18n": {language: character_name, default_bot_lang: character_name},
            "guild_id": guild_id_str, "selected_language": language,
            "hp": default_hp, "max_health": default_max_hp,
            "stats": base_stats, "location_id": starting_location_id_val,
            "level": 1, "experience": 0, "unspent_xp": 0, "gold": 0, "is_alive": True,
            "inventory": [], "status_effects": [], "active_quests": [], "known_spells": [],
            "spell_cooldowns": {}, "skills_data": [], "abilities_data": [], "spells_data": [],
            "flags": {}, "state_variables": {}, "equipment_slots": {}, "effective_stats_json": None
        }
        new_char_pydantic = Character(**pydantic_char_data)
        await self._recalculate_and_store_effective_stats(guild_id_str, new_character_id, new_char_pydantic, session_for_db=active_db_session)

        db_model_insert_data = new_char_pydantic.to_db_dict()
        db_model_insert_data['player_id'] = str(player_record.id)

        char_orm_to_add = CharacterDBModel(**db_model_insert_data)
        active_db_session.add(char_orm_to_add)

        player_record.active_character_id = char_orm_to_add.id # type: ignore
        flag_modified(player_record, "active_character_id")
        active_db_session.add(player_record)

        await active_db_session.flush()
        await active_db_session.refresh(char_orm_to_add)
        await active_db_session.refresh(player_record)

        return Character.from_db_model(char_orm_to_add)

    async def create_new_character(
        self, guild_id: str, user_id: int, character_name: str, language: str,
        session: Optional[AsyncSession] = None
    ) -> Optional[Character]:
        if not self._db_service or not self._game_manager or not self._rule_engine or not self._location_manager:
            logger.error(f"CM.create_new_character: Required services not available for guild {guild_id}.")
            return None

        guild_id_str = str(guild_id)
        discord_id_str = str(user_id)
        new_char_pydantic: Optional[Character] = None
        from bot.database.crud_utils import get_entity_by_attributes

        active_db_session_to_use: AsyncSession
        if session is None:
            if not hasattr(self._db_service, 'get_session') or not callable(self._db_service.get_session): return None
            async with self._db_service.get_session() as active_db_session_context:
                active_db_session_to_use = cast(AsyncSession, active_db_session_context)
                async with active_db_session_to_use.begin():
                    try:
                        player_record = await get_entity_by_attributes(active_db_session_to_use, Player, {"discord_id": discord_id_str}, guild_id=guild_id_str)
                        if not player_record: return None
                        new_char_pydantic = await self._create_new_character_core_logic(active_db_session_to_use, guild_id_str, user_id, character_name, language, player_record)
                        if new_char_pydantic and hasattr(player_record, 'id'):
                             self._characters.setdefault(guild_id_str, {})[new_char_pydantic.id] = new_char_pydantic
                             self._discord_to_player_map.setdefault(guild_id_str, {})[user_id] = str(player_record.id)
                             self.mark_character_dirty(guild_id_str, new_char_pydantic.id)
                    except CharacterAlreadyExistsError: raise
                    except Exception as e_managed: logger.error(f"CM.create_new_character (managed): {e_managed}", exc_info=True); new_char_pydantic = None
        else:
            active_db_session_to_use = cast(AsyncSession, session)
            try:
                player_record = await get_entity_by_attributes(active_db_session_to_use, Player, {"discord_id": discord_id_str}, guild_id=guild_id_str)
                if not player_record: return None
                new_char_pydantic = await self._create_new_character_core_logic(active_db_session_to_use, guild_id_str, user_id, character_name, language, player_record)
                if new_char_pydantic and hasattr(player_record, 'id'):
                     self._characters.setdefault(guild_id_str, {})[new_char_pydantic.id] = new_char_pydantic
                     self._discord_to_player_map.setdefault(guild_id_str, {})[user_id] = str(player_record.id)
                     self.mark_character_dirty(guild_id_str, new_char_pydantic.id)
            except CharacterAlreadyExistsError: raise
            except Exception as e_ext: logger.error(f"CM.create_new_character (external): {e_ext}", exc_info=True); new_char_pydantic = None
        return new_char_pydantic

    async def update_health(
        self, guild_id: str, character_id: str, amount: float, session: Optional[AsyncSession] = None, **kwargs: Any
    ) -> Optional[UpdateHealthResult]:
        char_model_pydantic = self.get_character(guild_id, character_id)
        if not char_model_pydantic: return None
        original_hp = float(char_model_pydantic.hp)
        original_is_alive = char_model_pydantic.is_alive
        new_hp_value = float(char_model_pydantic.hp) + amount
        current_max_health = float(char_model_pydantic.max_health)
        new_hp_value = max(0.0, min(new_hp_value, current_max_health))
        actual_hp_change = new_hp_value - original_hp
        char_model_pydantic.hp = new_hp_value
        char_model_pydantic.is_alive = new_hp_value > 0
        self.mark_character_dirty(guild_id, character_id)
        if actual_hp_change != 0 or char_model_pydantic.is_alive != original_is_alive:
             await self._recalculate_and_store_effective_stats(guild_id, character_id, char_model_pydantic, session_for_db=session)
        logger.info(f"Char {character_id} health updated by {amount}. NewHP: {char_model_pydantic.hp}")
        return UpdateHealthResult(applied_amount=amount, actual_hp_change=actual_hp_change, current_hp=char_model_pydantic.hp, max_hp=char_model_pydantic.max_health, is_alive=char_model_pydantic.is_alive, original_hp=original_hp)

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory') or not callable(self._db_service.get_session_factory):
            logger.error(f"CM: DB service/factory NA for save_state, guild {guild_id}.")
            return
        guild_id_str = str(guild_id)
        dirty_ids = self._dirty_characters.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_characters_ids.get(guild_id_str, set()).copy()
        if not dirty_ids and not deleted_ids: return

        from bot.database.guild_transaction import GuildTransaction
        from sqlalchemy import delete as sqlalchemy_delete

        try:
            async with GuildTransaction(self._db_service.get_session_factory(), guild_id_str) as session_context: # Call factory
                session = cast(AsyncSession, session_context)
                if deleted_ids:
                    ids_to_delete_list = list(deleted_ids)
                    if ids_to_delete_list:
                        stmt = sqlalchemy_delete(CharacterDBModel).where(CharacterDBModel.id.in_(ids_to_delete_list))
                        await session.execute(stmt)
                guild_cache = self._characters.get(guild_id_str, {})
                processed_dirty_ids = set()
                for char_id in dirty_ids:
                    if char_id in guild_cache:
                        char_pydantic = guild_cache[char_id]
                        db_data = char_pydantic.to_db_dict()
                        db_char = await session.get(CharacterDBModel, char_id)
                        if db_char:
                            for key, value in db_data.items(): setattr(db_char, key, value)
                        else: db_char = CharacterDBModel(**db_data)
                        await session.merge(db_char); processed_dirty_ids.add(char_id)
                logger.info(f"CM: Processed {len(processed_dirty_ids)} dirty, {len(deleted_ids)} deleted chars for guild {guild_id_str}.")
            if guild_id_str in self._deleted_characters_ids: self._deleted_characters_ids[guild_id_str].clear()
            if guild_id_str in self._dirty_characters: self._dirty_characters[guild_id_str].difference_update(processed_dirty_ids)
        except Exception as e: logger.error(f"CM: Error save_state guild {guild_id_str}: {e}", exc_info=True)

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory') or not callable(self._db_service.get_session_factory):
            logger.error(f"CM: DB service/factory NA for load_state, guild {guild_id}.")
            return
        guild_id_str = str(guild_id)
        logger.info(f"CM: Loading state for guild {guild_id_str}.")
        self._characters[guild_id_str] = {}; self._discord_to_player_map[guild_id_str] = {}
        self._entities_with_active_action.pop(guild_id_str, None); self._dirty_characters.pop(guild_id_str, None); self._deleted_characters_ids.pop(guild_id_str, None)
        from bot.database.crud_utils import get_entities as get_db_entities # Alias to avoid conflict
        from bot.database.guild_transaction import GuildTransaction
        try:
            async with GuildTransaction(self._db_service.get_session_factory(), guild_id_str, commit_on_exit=False) as session_context:
                session = cast(AsyncSession, session_context)
                all_players_db = await get_db_entities(session, Player, guild_id=guild_id_str) or []
                for player_db in all_players_db:
                    if player_db.discord_id:
                        try: self._discord_to_player_map.setdefault(guild_id_str, {})[int(player_db.discord_id)] = str(player_db.id)
                        except ValueError: logger.warning(f"Invalid discord_id '{player_db.discord_id}' for player {player_db.id}.")
                all_chars_db = await get_db_entities(session, CharacterDBModel, guild_id=guild_id_str) or []
                for char_db in all_chars_db:
                    char_pydantic = Character.from_db_model(char_db)
                    self._characters.setdefault(guild_id_str, {})[char_pydantic.id] = char_pydantic
                    if char_pydantic.current_action or char_pydantic.action_queue:
                         self._entities_with_active_action.setdefault(guild_id_str, set()).add(char_pydantic.id)
                logger.info(f"CM: Loaded {len(all_chars_db)} characters for guild {guild_id_str}.")
        except Exception as e: logger.error(f"CM: DB error load_state guild {guild_id_str}: {e}", exc_info=True)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None: logger.info(f"CM: Rebuilding runtime caches for guild {guild_id} (pass-through).")
    def mark_character_dirty(self, guild_id: str, character_id: str) -> None:
         guild_id_str = str(guild_id)
         if guild_id_str in self._characters and character_id in self._characters[guild_id_str]:
             self._dirty_characters.setdefault(guild_id_str, set()).add(character_id)
         else: logger.warning(f"Attempted to mark non-cached char {character_id} in guild {guild_id_str} as dirty.")

    async def get_character_details_context(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]: return None
    def get_character_by_name(self, guild_id: str, name: str) -> Optional[Character]: return None
    def get_all_characters(self, guild_id: str) -> List[Character]: return list(self._characters.get(str(guild_id), {}).values())
    def get_characters_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List[Character]:
        all_guild_chars = self.get_all_characters(str(guild_id))
        return [char for char in all_guild_chars if str(getattr(char, 'location_id', None)) == str(location_id)]
    def get_entities_with_active_action(self, guild_id: str) -> Set[str]: return self._entities_with_active_action.get(str(guild_id), set())
    def is_busy(self, guild_id: str, character_id: str) -> bool: return False
    def mark_character_deleted(self, guild_id: str, character_id: str) -> None:
        gid_str = str(guild_id)
        self._deleted_characters_ids.setdefault(gid_str, set()).add(character_id)
        if gid_str in self._characters and character_id in self._characters[gid_str]: del self._characters[gid_str][character_id]
        if gid_str in self._dirty_characters and character_id in self._dirty_characters[gid_str]: self._dirty_characters[gid_str].remove(character_id)

    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool: return False
    async def update_character_location(self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any) -> Optional[Character]: return None
    async def add_item_to_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool: return False
    async def remove_item_from_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool: return False
    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None: pass
    def add_action_to_queue(self, guild_id: str, character_id: str, action_type: str, action_data: dict) -> None:
        character = self.get_character(guild_id, character_id)
        if character:
            if not character.action_queue:
                character.action_queue = []
            character.action_queue.append({"type": action_type, "data": action_data})
            self.mark_character_dirty(guild_id, character_id)
    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]: return None
    async def save_character(self, character: Character, guild_id: str) -> bool: return False
    async def set_current_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool: return False
    async def save_character_field(self, guild_id: str, character_id: str, field_name: str, value: Any, **kwargs: Any) -> bool: return False
    async def gain_xp(self, guild_id: str, character_id: str, amount: int, session: Optional[AsyncSession] = None) -> Optional[Dict[str, Any]]: return None
    async def update_character_stats(self, guild_id: str, character_id: str, stats_update: Dict[str, Any], session: Optional[AsyncSession] = None, **kwargs: Any) -> bool: return False
    async def get_player_account_by_char_id(self, character_id: str, guild_id: str, session: Optional[AsyncSession] = None) -> Optional[Player]:
        # Placeholder implementation
        # In a real scenario, this would query the DB for the Player associated with the character_id
        # For now, returning None as the cache structure for this is not fully implemented here.
        logger.debug(f"CM.get_player_account_by_char_id: Called for char {character_id}, guild {guild_id}. Placeholder returns None.")
        return None
