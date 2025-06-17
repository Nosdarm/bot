# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
import asyncpg # Driver for PostgreSQL
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union

class CharacterAlreadyExistsError(Exception):
    pass

from bot.game.models.character import Character
from builtins import dict, set, list, int

from bot.game.utils import stats_calculator # Added import

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.models.npc import NPC
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.npc_manager import NPCManager # Already present
    from bot.game.managers.inventory_manager import InventoryManager # Added
    from bot.game.managers.equipment_manager import EquipmentManager # Added
    from bot.game.managers.game_manager import GameManager # Already present

logger = logging.getLogger(__name__) # Added

class CharacterManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    _characters: Dict[str, Dict[str, "Character"]]
    _discord_to_char_map: Dict[str, Dict[int, str]]
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
        inventory_manager: Optional["InventoryManager"] = None, # Added
        equipment_manager: Optional["EquipmentManager"] = None, # Added
        game_manager: Optional["GameManager"] = None
    ):
        logger.info("Initializing CharacterManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._item_manager = item_manager # Existing
        self._location_manager = location_manager # Existing
        self._rule_engine = rule_engine # Existing
        self._status_manager = status_manager # Existing
        self._party_manager = party_manager # Existing
        self._combat_manager = combat_manager # Existing
        self._dialogue_manager = dialogue_manager # Existing
        self._relationship_manager = relationship_manager # Existing
        self._game_log_manager = game_log_manager # Existing
        self._npc_manager = npc_manager # Existing
        self._inventory_manager = inventory_manager # Added
        self._equipment_manager = equipment_manager # Added
        self._game_manager = game_manager # Existing

        self._characters = {}
        self._discord_to_char_map = {}
        self._entities_with_active_action = {}
        self._dirty_characters = {}
        self._deleted_characters_ids = {}
        logger.info("CharacterManager initialized.") # Changed

    async def _recalculate_and_store_effective_stats(self, guild_id: str, character_id: str, char_model: Optional[Character] = None) -> None:
        """Helper to recalculate and store effective stats for a character."""
        if not char_model:
            char_model = self.get_character(guild_id, character_id)
            if not char_model:
                logger.error("CharacterManager: Character %s not found in guild %s for effective stats recalc.", character_id, guild_id) # Changed
                return

        char_model_to_use = char_model # Use existing fetched char_model

        if not self._game_manager:
            logger.warning("CharacterManager: GameManager not available, cannot recalculate effective_stats for char %s in guild %s.", character_id, guild_id)
            setattr(char_model_to_use, 'effective_stats_json', json.dumps({"error": "game_manager_unavailable"}))
            return

        # stats_calculator.calculate_effective_stats will handle checks for its needed sub-managers from game_manager
        try:
            effective_stats_dict = await stats_calculator.calculate_effective_stats(
                entity=char_model_to_use,
                guild_id=guild_id,
                game_manager=self._game_manager
            )
            # Ensure effective_stats_json attribute exists before setting
            if not hasattr(char_model_to_use, 'effective_stats_json'):
                 logger.warning(f"CharacterManager: Character model for {character_id} does not have 'effective_stats_json' attribute. Stat calculation done but not stored on model directly.")
                 # Storing it anyway as per original logic, assuming the model should have it or this is intended to add it dynamically
            setattr(char_model_to_use, 'effective_stats_json', json.dumps(effective_stats_dict or {}))
            logger.debug("CharacterManager: Recalculated effective_stats for character %s in guild %s.", character_id, guild_id)
        except Exception as es_ex:
            logger.error("CharacterManager: ERROR recalculating effective_stats for char %s in guild %s: %s", character_id, guild_id, es_ex, exc_info=True) # Changed
            if hasattr(char_model_to_use, 'effective_stats_json'):
                setattr(char_model_to_use, 'effective_stats_json', json.dumps({"error": "calculation_failed"}))

    async def trigger_stats_recalculation(self, guild_id: str, character_id: str) -> None:
        """Public method to trigger effective stats recalculation and mark character dirty."""
        char = self.get_character(guild_id, character_id)
        if char:
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            self.mark_character_dirty(guild_id, character_id)
            logger.info("CharacterManager: Stats recalculation triggered for char %s in guild %s and marked dirty.", character_id, guild_id) # Changed
        else:
            logger.warning("CharacterManager: trigger_stats_recalculation - Character %s not found in guild %s.", character_id, guild_id) # Changed


    def get_character(self, guild_id: str, character_id: str) -> Optional["Character"]:
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars:
             return guild_chars.get(character_id)
        return None

    def get_character_by_discord_id(self, guild_id: str, discord_user_id: int) -> Optional["Character"]:
        guild_id_str = str(guild_id)
        guild_discord_map = self._discord_to_char_map.get(guild_id_str)
        if isinstance(guild_discord_map, dict):
             char_id = guild_discord_map.get(discord_user_id)
             if char_id:
                 char = self.get_character(guild_id_str, char_id) # Changed to guild_id_str
                 if not char:
                     logger.critical("CharacterManager: Char_id '%s' for Discord ID %s found in map, but character NOT in _characters cache for guild %s! Cache inconsistency.", char_id, discord_user_id, guild_id_str) # Changed
                 return char
        return None

    def get_character_by_name(self, guild_id: str, name: str) -> Optional["Character"]:
         guild_chars = self._characters.get(str(guild_id))
         if guild_chars:
              for char in guild_chars.values():
                  if isinstance(char, Character) and getattr(char, 'name', char.id) == name:
                      return char
         return None

    def get_all_characters(self, guild_id: str) -> List["Character"]:
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars:
             return list(guild_chars.values())
        return []

    def get_characters_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List["Character"]:
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        characters_in_location = []
        guild_chars = self._characters.get(guild_id_str)
        if guild_chars:
             for char in guild_chars.values():
                 if isinstance(char, Character) and hasattr(char, 'location_id') and str(getattr(char, 'location_id', None)) == location_id_str:
                      characters_in_location.append(char)
        return characters_in_location

    def get_entities_with_active_action(self, guild_id: str) -> Set[str]:
        return self._entities_with_active_action.get(str(guild_id), set()).copy()

    def is_busy(self, guild_id: str, character_id: str) -> bool:
        char = self.get_character(guild_id, character_id)
        if not char: return False
        if getattr(char, 'current_action', None) is not None or getattr(char, 'action_queue', []): return True
        if getattr(char, 'party_id', None) is not None and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
            party_id = getattr(char, 'party_id', None)
            if party_id: return self._party_manager.is_party_busy(str(guild_id), party_id)
        return False

    async def create_character(
        self, discord_id: int, name: str, guild_id: str,
        initial_location_id: Optional[str] = None, level: int = 1, experience: int = 0,
        unspent_xp: int = 0, **kwargs: Any
    ) -> Optional["Character"]:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("CharacterManager: Database service or adapter is not initialized for guild %s.", guild_id_str)
            raise ConnectionError("Database service or adapter is not initialized in CharacterManager.")

        if not self._game_manager:
            logger.error("CharacterManager: GameManager not available. Cannot fetch starting rules.")
            raise ValueError("GameManager not available for character creation.")

        if self.get_character_by_name(guild_id_str, name): # Check by name first
            logger.warning("CharacterManager: Character with name '%s' already exists in guild %s.", name, guild_id_str)
            return None

        # Pre-emptive check for Discord ID to provide a cleaner error than DB constraint failure
        # This check should ideally be done using a DB query for atomicity, but for now, using cache.
        if self.get_character_by_discord_id(guild_id_str, discord_id):
            logger.warning("CharacterManager: Character with Discord ID %s already exists in guild %s (cache check).", discord_id, guild_id_str)
            raise CharacterAlreadyExistsError(f"A character already exists for user {discord_id} in this guild.")


        new_id = str(uuid.uuid4())

        # Fetch starting rules
        starting_base_stats = await self._game_manager.get_rule(guild_id_str, "starting_base_stats", default={"strength": 8, "dexterity": 8, "constitution": 8, "intelligence": 8, "wisdom": 8, "charisma": 8})
        starting_items_rules = await self._game_manager.get_rule(guild_id_str, "starting_items", default=[])
        starting_skills_rules = await self._game_manager.get_rule(guild_id_str, "starting_skills", default=[])
        starting_abilities_rules = await self._game_manager.get_rule(guild_id_str, "starting_abilities", default=[])
        starting_character_class = await self._game_manager.get_rule(guild_id_str, "starting_character_class", default="commoner")
        starting_race = await self._game_manager.get_rule(guild_id_str, "starting_race", default="human")
        starting_mp = await self._game_manager.get_rule(guild_id_str, "starting_mp", default=10)
        starting_attack_base = await self._game_manager.get_rule(guild_id_str, "starting_attack_base", default=1)
        starting_defense_base = await self._game_manager.get_rule(guild_id_str, "starting_defense_base", default=0)

        # HP and Max Health might also come from rules or be calculated based on stats (e.g., constitution)
        # For now, using kwargs or defaults as before, but this is an area for future rule integration.
        base_hp = kwargs.get('hp', 100.0)
        base_max_health = kwargs.get('max_health', 100.0)


        # Prepare stats for Player model (ensure keys match Player.stats expectations, e.g., "base_strength")
        # The rule "starting_base_stats" should directly provide {"strength": val, ...}
        # We need to map this to {"base_strength": val, ...} if Player.stats expects that.
        # Assuming Player.stats expects keys like "base_strength", "base_dexterity", etc.
        player_stats_data = {}
        for key, value in starting_base_stats.items():
            player_stats_data[f"base_{key}"] = value

        # Add attack and defense to stats if they are stored there, or handle as separate Player fields.
        # Assuming they might be part of the 'stats' JSONB for flexibility:
        player_stats_data["attack_base"] = starting_attack_base
        player_stats_data["defense_base"] = starting_defense_base
        # If Player model has distinct `attack` and `defense` columns, those should be used directly in `data`.

        default_player_language = "en"
        if hasattr(self, '_game_manager') and self._game_manager and hasattr(self._game_manager, 'get_default_bot_language'):
            try: default_player_language = self._game_manager.get_default_bot_language(guild_id_str) # Pass guild_id
            except Exception: default_player_language = "en"

        resolved_initial_location_id = initial_location_id
        if resolved_initial_location_id is None and self._settings: # Fallback to settings if not provided
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            default_loc_id = guild_settings.get('default_start_location_id') or self._settings.get('default_start_location_id')
            if default_loc_id: resolved_initial_location_id = str(default_loc_id)
        elif initial_location_id: resolved_initial_location_id = str(initial_location_id)

        # Prepare skills and abilities data
        skills_list_for_json = starting_skills_rules # Assumes rule format matches Player model's expected JSON structure
        abilities_list_for_json = starting_abilities_rules # Same assumption

        name_i18n_data = {"en": name, "ru": name} # Basic default, consider making this rule-based too
        data: Dict[str, Any] = {
            'id': new_id,
            'discord_id': discord_id,
            'name': name,
            'name_i18n': name_i18n_data,
            'guild_id': guild_id_str,
            'current_location_id': resolved_initial_location_id,
            'stats': player_stats_data, # Using fetched and prepared stats
            'inventory': [], # Starting items will be handled after player creation
            'current_action': None,
            'action_queue': [],
            'party_id': None,
            'state_variables': {},
            'hp': base_hp, # Use base_hp from earlier
            'max_health': base_max_health, # Use base_max_health
            'mp': starting_mp, # From rules
            'attack': starting_attack_base, # From rules - assuming 'attack' field exists on Player model
            'defense': starting_defense_base, # From rules - assuming 'defense' field exists on Player model
            'race': starting_race, # From rules - assuming 'race' field exists
            'is_alive': True,
            'status_effects': [],
            'level': level,
            'experience': experience,
            'unspent_xp': unspent_xp,
            'selected_language': default_player_language,
            'collected_actions_json': None,
            'skills_data_json': json.dumps(skills_list_for_json),
            'abilities_data_json': json.dumps(abilities_list_for_json),
            'spells_data_json': json.dumps([]), # No specific starting spells rule mentioned, default to empty
            'character_class': starting_character_class, # From rules
            'flags_json': json.dumps({}),
            'effective_stats_json': "{}" # Will be recalculated
        }

        # Prepare for Character.from_dict (expects different field names for some)
        model_data_init = data.copy()
        model_data_init['discord_user_id'] = model_data_init.pop('discord_id')
        # Remove fields that are JSON strings in DB but parsed in Character model
        for k_json in ['skills_data_json', 'abilities_data_json', 'spells_data_json', 'flags_json', 'effective_stats_json']:
            if k_json in model_data_init: del model_data_init[k_json]
        # Add parsed versions for Character model
        model_data_init['skills_data'] = skills_list_for_json
        model_data_init['abilities_data'] = abilities_list_for_json
        model_data_init['spells_data'] = []
        model_data_init['flags'] = {}


        # Construct SQL INSERT statement and parameters
        # This needs to be robust to Player model changes. For now, list common fields.
        # Assume 'race', 'mp', 'attack', 'defense' are direct columns on Player table.
        # If they are part of 'stats' JSONB, then 'stats' field in SQL needs to include them.
        # For this iteration, let's assume they are direct columns for clarity.
        # A more dynamic way to build this SQL would be better in the long run.
        sql = """
        INSERT INTO players (
            id, discord_id, name_i18n, guild_id, current_location_id, stats, inventory,
            current_action, action_queue, party_id, state_variables,
            hp, max_health, mp, attack, defense, race, character_class, -- Added mp, attack, defense, race
            is_alive, status_effects, level, xp, unspent_xp,
            selected_language, collected_actions_json,
            skills_data_json, abilities_data_json, spells_data_json, flags_json, effective_stats_json, is_active
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30)
        RETURNING id;
        """
        # Parameter order must match VALUES clause
        db_params = (
            data['id'], str(data['discord_id']), json.dumps(data['name_i18n']), data['guild_id'],
            data['current_location_id'], json.dumps(data['stats']), json.dumps(data['inventory']),
            json.dumps(data['current_action']) if data['current_action'] is not None else None,
            json.dumps(data['action_queue']), data['party_id'], json.dumps(data['state_variables']),
            data['hp'], data['max_health'], data['mp'], data['attack'], data['defense'], data['race'], data['character_class'],
            data['is_alive'], json.dumps(data['status_effects']),
            data['level'], data['experience'], data['unspent_xp'], data['selected_language'],
            data['collected_actions_json'], data['skills_data_json'], data['abilities_data_json'],
            data['spells_data_json'], data['flags_json'], data['effective_stats_json'], True
        )

        try:
            await self._db_service.adapter.execute_insert(sql, db_params)
            char = Character.from_dict(model_data_init) # Use prepared model_data_init
            setattr(char, 'effective_stats_json', data['effective_stats_json']) # Set this as it's not in model_data_init

            self._characters.setdefault(guild_id_str, {})[char.id] = char
            if char.discord_user_id is not None:
                 self._discord_to_char_map.setdefault(guild_id_str, {})[char.discord_user_id] = char.id

            # Handle starting items
            if self._item_manager:
                for item_info in starting_items_rules:
                    template_id = item_info.get("template_id")
                    quantity = item_info.get("quantity", 1)
                    state_vars = item_info.get("state_variables") # Optional state for the item
                    if template_id:
                        try:
                            # Assuming ItemManager.create_and_add_item_to_player_inventory exists and handles DB operations
                            # This method would need to accept a session if called within a larger transaction.
                            # For now, assuming it manages its own or this create_character is not within an outer transaction.
                            await self._item_manager.create_and_add_item_to_player_inventory(
                                guild_id=guild_id_str,
                                player_id=char.id,
                                item_template_id=template_id,
                                quantity=quantity,
                                state_variables=state_vars
                                # session=db_session_from_guild_transaction_if_available # Future consideration
                            )
                            logger.info(f"Granted starting item {template_id} (x{quantity}) to character {char.id}")
                        except Exception as item_ex:
                            logger.error(f"Error granting starting item {template_id} to char {char.id}: {item_ex}", exc_info=True)
            else:
                logger.warning("ItemManager not available. Cannot grant starting items to character %s.", char.id)

            await self._recalculate_and_store_effective_stats(guild_id_str, char.id, char)
            self.mark_character_dirty(guild_id_str, char.id)
            logger.info("CharacterManager: Character '%s' (ID: %s) created in guild %s.", char.name, char.id, guild_id_str)
            return char
        except asyncpg.exceptions.UniqueViolationError as uve:
            logger.warning(
                "CharacterManager: Attempted to create a character that already exists for discord_id %s in guild %s (unique constraint violation). Details: %s",
                discord_id, guild_id_str, uve
            )
            raise CharacterAlreadyExistsError(
                f"A character already exists for user {discord_id} in guild {guild_id_str}."
            ) from uve
        except Exception as e:
            logger.error("CharacterManager: Error creating character '%s' in guild %s: %s", name, guild_id_str, e, exc_info=True) # Changed
            # Optionally, you might want to wrap other exceptions in a generic CharacterCreationError
            # or let them propagate if they represent different kinds of issues.
            # For now, we'll re-raise other exceptions as they are.
            raise

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("CharacterManager: DB service not available for save_state in guild %s.", guild_id) # Added
            return

        guild_id_str = str(guild_id)
        dirty_ids = self._dirty_characters.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_characters_ids.get(guild_id_str, set()).copy()

        if not dirty_ids and not deleted_ids:
            logger.debug("CharacterManager: No dirty or deleted characters to save for guild %s.", guild_id_str) # Added
            return

        if deleted_ids:
            ids_to_delete_list = list(deleted_ids)
            if ids_to_delete_list:
                pg_placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_delete_list))])
                delete_sql = f"DELETE FROM players WHERE guild_id = $1 AND id IN ({pg_placeholders})"
                try:
                    await self._db_service.adapter.execute(delete_sql, (guild_id_str, *ids_to_delete_list))
                    logger.info("CharacterManager: Deleted %s characters for guild %s: %s", len(ids_to_delete_list), guild_id_str, ids_to_delete_list) # Added
                    self._deleted_characters_ids.pop(guild_id_str, None)
                except Exception as e:
                    logger.error("CharacterManager: Error deleting characters for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            else: self._deleted_characters_ids.pop(guild_id_str, None)

        guild_cache = self._characters.get(guild_id_str, {})
        chars_to_save = [guild_cache[cid] for cid in list(dirty_ids) if cid in guild_cache]

        if chars_to_save:
            upsert_sql = '''
            INSERT INTO players (
                id, discord_id, name_i18n, guild_id, current_location_id, stats, inventory,
                current_action, action_queue, party_id, state_variables, hp, max_health,
                is_alive, status_effects, level, xp, unspent_xp, active_quests, known_spells,
                spell_cooldowns, skills_data_json, abilities_data_json, spells_data_json, flags_json,
                character_class, selected_language, current_game_status, collected_actions_json, current_party_id, effective_stats_json, equipment_slots_json
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30, $31, $32)
            ON CONFLICT (id) DO UPDATE SET
                discord_id=EXCLUDED.discord_id, name_i18n=EXCLUDED.name_i18n, guild_id=EXCLUDED.guild_id, current_location_id=EXCLUDED.current_location_id, stats=EXCLUDED.stats, inventory=EXCLUDED.inventory, current_action=EXCLUDED.current_action, action_queue=EXCLUDED.action_queue, party_id=EXCLUDED.party_id, state_variables=EXCLUDED.state_variables, hp=EXCLUDED.hp, max_health=EXCLUDED.max_health, is_alive=EXCLUDED.is_alive, status_effects=EXCLUDED.status_effects, level=EXCLUDED.level, xp=EXCLUDED.experience, unspent_xp=EXCLUDED.unspent_xp, active_quests=EXCLUDED.active_quests, known_spells=EXCLUDED.known_spells, spell_cooldowns=EXCLUDED.spell_cooldowns, skills_data_json=EXCLUDED.skills_data_json, abilities_data_json=EXCLUDED.abilities_data_json, spells_data_json=EXCLUDED.spells_data_json, flags_json=EXCLUDED.flags_json, character_class=EXCLUDED.character_class, selected_language=EXCLUDED.selected_language, current_game_status=EXCLUDED.current_game_status, collected_actions_json=EXCLUDED.collected_actions_json, current_party_id=EXCLUDED.current_party_id, effective_stats_json=EXCLUDED.effective_stats_json, equipment_slots_json=EXCLUDED.equipment_slots_json;
            '''
            data_to_upsert = []
            processed_dirty_ids = set()
            for char_obj in chars_to_save:
                try:
                    char_data = char_obj.to_dict()
                    effective_stats_j = getattr(char_obj, 'effective_stats_json', '{}')
                    if not isinstance(effective_stats_j, str): effective_stats_j = json.dumps(effective_stats_j or {})
                    db_params = (
                        char_data.get('id'), char_data.get('discord_id'), json.dumps(char_data.get('name_i18n', {})),
                        char_data.get('guild_id'), char_data.get('current_location_id'), json.dumps(char_data.get('stats', {})),
                        json.dumps(char_data.get('inventory', [])), json.dumps(char_data.get('current_action')) if char_data.get('current_action') else None,
                        json.dumps(char_data.get('action_queue', [])), char_data.get('party_id'), json.dumps(char_data.get('state_variables', {})),
                        float(char_data.get('hp',0.0)), float(char_data.get('max_health',0.0)), bool(char_data.get('is_alive',True)),
                        json.dumps(char_data.get('status_effects', [])), int(char_data.get('level',1)), int(char_data.get('experience',0)),
                        int(char_data.get('unspent_xp',0)), json.dumps(char_data.get('active_quests', [])), json.dumps(char_data.get('known_spells', [])),
                        json.dumps(char_data.get('spell_cooldowns', {})), json.dumps(char_data.get('skills_data', [])),
                        json.dumps(char_data.get('abilities_data', [])), json.dumps(char_data.get('spells_data', [])),
                        json.dumps(char_data.get('flags', {})), char_data.get('character_class'), char_data.get('selected_language'),
                        char_data.get('current_game_status'), char_data.get('collected_actions_json'), char_data.get('current_party_id'),
                        effective_stats_j, json.dumps(char_data.get('equipment_slots_json', {}))
                    )
                    data_to_upsert.append(db_params)
                    processed_dirty_ids.add(char_obj.id)
                except Exception as e:
                    logger.error("CharacterManager: Error preparing char %s for save in guild %s: %s", char_obj.id, guild_id_str, e, exc_info=True) # Changed

            if data_to_upsert:
                try:
                    await self._db_service.adapter.execute_many(upsert_sql, data_to_upsert)
                    logger.info("CharacterManager: Saved %s characters for guild %s.", len(data_to_upsert), guild_id_str) # Added
                    if guild_id_str in self._dirty_characters:
                        self._dirty_characters[guild_id_str].difference_update(processed_dirty_ids)
                        if not self._dirty_characters[guild_id_str]: del self._dirty_characters[guild_id_str]
                except Exception as e:
                    logger.error("CharacterManager: Error batch upserting characters for guild %s: %s", guild_id_str, e, exc_info=True) # Changed

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("CharacterManager: DB service not available for load_state in guild %s.", guild_id) # Added
            return

        guild_id_str = str(guild_id)
        logger.info("CharacterManager: Loading state for guild %s.", guild_id_str) # Added
        self._characters.pop(guild_id_str, None); self._characters[guild_id_str] = {}
        self._discord_to_char_map.pop(guild_id_str, None); self._discord_to_char_map[guild_id_str] = {}
        self._entities_with_active_action.pop(guild_id_str, None); self._entities_with_active_action[guild_id_str] = set()
        self._dirty_characters.pop(guild_id_str, None); self._deleted_characters_ids.pop(guild_id_str, None)

        rows = []
        try:
            sql = '''
            SELECT id, discord_id, name_i18n, guild_id, current_location_id, stats, inventory,
                   current_action, action_queue, party_id, state_variables, hp, max_health,
                   is_alive, status_effects, race, mp, attack, defense, level, xp AS experience, unspent_xp,
                   collected_actions_json, selected_language, current_game_status, current_party_id,
                   skills_data_json, abilities_data_json, spells_data_json, character_class, flags_json,
                   active_quests, known_spells, spell_cooldowns, effective_stats_json, equipment_slots_json
            FROM players WHERE guild_id = $1
            '''
            rows = await self._db_service.adapter.fetchall(sql, (guild_id_str,))
        except Exception as e:
            logger.error("CharacterManager: DB fetchall error for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            raise

        guild_chars_cache = self._characters[guild_id_str]
        guild_discord_map_cache = self._discord_to_char_map[guild_id_str]
        guild_active_action_cache = self._entities_with_active_action[guild_id_str]
        loaded_count = 0
        for row in rows:
            data = dict(row)
            try:
                char_id = str(data.get('id'))
                data['effective_stats_json'] = data.get('effective_stats_json', '{}')
                for k, d_val_str, v_type in [('stats','{}',dict), ('inventory','[]',list), ('action_queue','[]',list),
                                   ('state_variables','{}',dict), ('status_effects','[]',list),
                                   ('skills_data_json','[]',list), ('abilities_data_json','[]',list),
                                   ('spells_data_json','[]',list), ('flags_json','{}',dict),
                                   ('active_quests','[]',list), ('known_spells','[]',list),
                                   ('spell_cooldowns','{}',dict), ('equipment_slots_json','{}',dict)]: # Added equipment_slots_json
                    raw_val = data.get(k)
                    # v_type is now correctly dict or list, d_val_str is '{}' or '[]'
                    parsed_val = v_type() # This will call dict() or list()
                    if isinstance(raw_val, (str, bytes)):
                        parsed_val = json.loads(raw_val or d_val_str)
                    elif isinstance(raw_val, v_type):
                        parsed_val = raw_val
                    # If raw_val is None and not a string/bytes or already the correct type,
                    # parsed_val will remain the empty dict/list created by v_type().
                    # This behavior seems acceptable.

                    data[k.replace('_json','')] = parsed_val
                    if '_json' in k and k in data: del data[k]
                current_action_json = data.get('current_action')
                data['current_action'] = json.loads(current_action_json) if isinstance(current_action_json, str) else (current_action_json if isinstance(current_action_json, dict) else None)
                name_i18n_json = data.get('name_i18n')
                data['name_i18n'] = json.loads(name_i18n_json or '{}') if isinstance(name_i18n_json, str) else (name_i18n_json if isinstance(name_i18n_json, dict) else {})
                data['name'] = data['name_i18n'].get(data.get('selected_language','en'), next(iter(data['name_i18n'].values()), char_id[:8]))
                data['discord_user_id'] = int(data['discord_id']) if data.get('discord_id') else None
                if 'discord_id' in data: del data['discord_id'] # From players table

                char = Character.from_dict(data)
                setattr(char, 'effective_stats_json', data.get('effective_stats_json', '{}'))
                guild_chars_cache[char.id] = char
                if char.discord_user_id: guild_discord_map_cache[char.discord_user_id] = char.id
                if char.current_action or char.action_queue: guild_active_action_cache.add(char.id)
                loaded_count +=1
            except Exception as e:
                logger.error("CharacterManager: Error processing char row %s for guild %s: %s", data.get('id'), guild_id_str, e, exc_info=True) # Changed
        logger.info("CharacterManager: Loaded %s characters for guild %s.", loaded_count, guild_id_str) # Added

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("CharacterManager: Rebuilding runtime caches for guild %s (currently a pass-through).", guild_id) # Added
        pass

    def mark_character_dirty(self, guild_id: str, character_id: str) -> None:
         if str(guild_id) in self._characters and character_id in self._characters[str(guild_id)]:
              self._dirty_characters.setdefault(str(guild_id), set()).add(character_id)

    def mark_character_deleted(self, guild_id: str, character_id: str) -> None:
        logger.info("CharacterManager: Marking character %s for deletion in guild %s.", character_id, guild_id) # Added
        # Actual deletion from cache and adding to _deleted_characters_ids should happen here
        guild_id_str = str(guild_id)
        if guild_id_str in self._characters and character_id in self._characters[guild_id_str]:
            char_to_delete = self._characters[guild_id_str].pop(character_id, None)
            if char_to_delete and char_to_delete.discord_user_id and guild_id_str in self._discord_to_char_map:
                self._discord_to_char_map[guild_id_str].pop(char_to_delete.discord_user_id, None)
            self._entities_with_active_action.get(guild_id_str, set()).discard(character_id)
            self._deleted_characters_ids.setdefault(guild_id_str, set()).add(character_id)
            logger.info("CharacterManager: Character %s removed from active cache and marked for DB deletion in guild %s.", character_id, guild_id_str)
        else:
            logger.warning("CharacterManager: Attempted to mark non-existent character %s for deletion in guild %s.", character_id, guild_id_str)


    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.party_id = str(party_id) if party_id else None
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Set party_id to %s for char %s in guild %s.", party_id, character_id, guild_id) # Added
            return True
        logger.warning("CharacterManager: Char %s not found in guild %s to set party_id.", character_id, guild_id) # Added
        return False

    async def update_character_location(self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any) -> Optional["Character"]:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_location_id = str(location_id) if location_id else None
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Updated location for char %s to %s in guild %s.", character_id, location_id, guild_id) # Added
            return char
        logger.warning("CharacterManager: Char %s not found in guild %s to update location.", character_id, guild_id) # Added
        return None

    async def add_item_to_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
        # Placeholder - actual inventory logic is in ItemManager or directly via DBService
        logger.debug("CharacterManager: add_item_to_inventory called for char %s, item %s, quantity %s in guild %s. Delegating to ItemManager.", character_id, item_id, quantity, guild_id) # Added
        return True

    async def remove_item_from_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
        # Placeholder
        logger.debug("CharacterManager: remove_item_from_inventory called for char %s, item %s, quantity %s in guild %s. Delegating to ItemManager.", character_id, item_id, quantity, guild_id) # Added
        return True

    async def update_health(self, guild_id: str, character_id: str, amount: float, **kwargs: Any) -> bool:
         guild_id_str = str(guild_id)
         char = self.get_character(guild_id_str, character_id)
         if not char or not all(hasattr(char, attr) for attr in ['hp', 'max_health', 'is_alive']):
             logger.warning("CharacterManager: Char %s not found or missing HP attributes in guild %s.", character_id, guild_id_str) # Added
             return False

         old_hp_val = char.hp
         old_is_alive_val = char.is_alive

         if not old_is_alive_val and amount <= 0:
             logger.debug("CharacterManager: Char %s in guild %s already not alive and damage applied, no change.", character_id, guild_id_str) # Added
             return False # No change if already dead and taking damage

         current_max_hp = char.max_health
         eff_stats_json = getattr(char, 'effective_stats_json', '{}')
         if isinstance(eff_stats_json, str) and eff_stats_json:
             try: current_max_hp = json.loads(eff_stats_json).get('max_hp', char.max_health)
             except json.JSONDecodeError:
                 logger.warning("CharacterManager: Failed to parse effective_stats_json for char %s in guild %s.", character_id, guild_id_str) # Added
                 pass # Use base max_health

         char.hp = max(0.0, min(float(current_max_hp), old_hp_val + amount))
         new_is_alive_status = char.hp > 0

         hp_changed = char.hp != old_hp_val
         is_alive_status_changed = new_is_alive_status != old_is_alive_val
         char.is_alive = new_is_alive_status

         if hp_changed or is_alive_status_changed:
            self.mark_character_dirty(guild_id_str, character_id)
            await self._recalculate_and_store_effective_stats(guild_id_str, character_id, char)
            logger.info("CharacterManager: Updated health for char %s in guild %s. HP: %s -> %s. Alive: %s -> %s.", character_id, guild_id_str, old_hp_val, char.hp, old_is_alive_val, char.is_alive) # Added

         if char.hp <= 0 and old_is_alive_val: # Was alive, now is not
              logger.info("CharacterManager: Character %s in guild %s has died.", character_id, guild_id_str) # Added
              await self.handle_character_death(guild_id_str, character_id, hp_before_death_processing=old_hp_val, was_alive_before_death_processing=old_is_alive_val, **kwargs)
         return True

    async def update_character_stats(self, guild_id: str, character_id: str, stats_update: Dict[str, Any], **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if not char:
            logger.warning("CharacterManager: Char %s not found in guild %s for stats update.", character_id, guild_id_str) # Added
            return False

        updated_fields = []
        recalc_needed = False
        for key, value in stats_update.items():
            try:
                if key == "hp":
                    await self.update_health(guild_id_str, character_id, float(value) - char.hp, **kwargs)
                    updated_fields.append(f"hp to {char.hp}")
                    continue
                elif key.startswith("stats."):
                    stat_name = key.split("stats.", 1)[1]
                    if not hasattr(char, 'stats') or not isinstance(char.stats, dict): char.stats = {}
                    if char.stats.get(stat_name) != value:
                        char.stats[stat_name] = value
                        updated_fields.append(f"{key} to {value}")
                        recalc_needed = True
                elif hasattr(char, key):
                    if getattr(char, key) != value:
                        setattr(char, key, value)
                        updated_fields.append(f"{key} to {value}")
                        recalc_needed = True # Assume most direct attribute changes might affect effective stats
                else:
                    logger.debug("CharacterManager: Key %s not directly on char model for stats update of %s in guild %s.", key, character_id, guild_id_str) # Added
                    continue # Skip unknown keys
            except Exception as e:
                logger.error("CharacterManager: Error updating key %s for char %s in guild %s: %s", key, character_id, guild_id_str, e, exc_info=True) # Added

        if updated_fields:
            self.mark_character_dirty(guild_id_str, character_id)
            if recalc_needed:
                await self._recalculate_and_store_effective_stats(guild_id_str, character_id, char)
            logger.info("CharacterManager: Updated stats for char %s in guild %s: %s. Recalc_needed: %s.", character_id, guild_id_str, updated_fields, recalc_needed) # Added
            return True
        logger.debug("CharacterManager: No effective stat changes for char %s in guild %s from update: %s", character_id, guild_id_str, stats_update) # Added
        return False

    async def handle_character_death(self, guild_id: str, character_id: str, **kwargs: Any):
        char = self.get_character(guild_id, character_id)
        if char and getattr(char, 'is_alive', False): # If it was marked alive before this specific call
            char.is_alive = False
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char) # Recalc after setting is_alive
            logger.info("CharacterManager: Processed death for char %s in guild %s. Marked not alive.", character_id, guild_id) # Added
        elif char and not getattr(char, 'is_alive', True): # Check if already not alive
             logger.info("CharacterManager: Character %s in guild %s already marked as not alive during death processing.", character_id, guild_id) # Changed
        else:
             logger.warning("CharacterManager: Character %s not found in guild %s for death processing.", character_id, guild_id) # Changed

    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None:
        # Placeholder
        logger.debug("CharacterManager: set_active_action for char %s in guild %s. Action: %s", character_id, guild_id, action_details) # Added
        pass

    def add_action_to_queue(self, guild_id: str, character_id: str, action_details: Dict[str, Any]) -> None:
        # Placeholder
        logger.debug("CharacterManager: add_action_to_queue for char %s in guild %s. Action: %s", character_id, guild_id, action_details) # Added
        pass

    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        # Placeholder
        logger.debug("CharacterManager: get_next_action_from_queue for char %s in guild %s.", character_id, guild_id) # Added
        return None

    async def save_character(self, character: "Character", guild_id: str) -> bool:
        if self._db_service is None or not hasattr(self._db_service, 'adapter') or self._db_service.adapter is None:
            logger.error("CharacterManager: DB Service not available, cannot save char %s in guild %s.", character.id, guild_id) # Added
            return False
        self.mark_character_dirty(guild_id, character.id)
        # Actual saving is batched in save_state
        logger.debug("CharacterManager: Marked char %s for saving in guild %s.", character.id, guild_id) # Added
        return True

    async def set_current_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_party_id = str(party_id) if party_id else None
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Set current_party_id to %s for char %s in guild %s.", party_id, character_id, guild_id) # Added
            return True
        logger.warning("CharacterManager: Char %s not found in guild %s to set current_party_id.", character_id, guild_id) # Added
        return False

    async def save_character_field(self, guild_id: str, character_id: str, field_name: str, value: Any, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char and hasattr(char, field_name):
            setattr(char, field_name, value)
            self.mark_character_dirty(guild_id, character_id)
            if field_name.startswith("stats") or field_name == "level" or field_name == "is_alive": # Added is_alive
                await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Saved field %s to %s for char %s in guild %s.", field_name, value, character_id, guild_id) # Added
            return True
        logger.warning("CharacterManager: Field %s not found or char %s not found in guild %s for save_character_field.", field_name, character_id, guild_id) # Added
        return False

    # --- Revert Methods ---
    async def revert_location_change(self, guild_id: str, character_id: str, old_location_id: str, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.current_location_id = old_location_id
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Reverted location for char %s to %s in guild %s.", character_id, old_location_id, guild_id) # Added
            return True
        return False

    async def revert_hp_change(self, guild_id: str, character_id: str, old_hp: float, old_is_alive: bool, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.hp = old_hp
            char.is_alive = old_is_alive
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Reverted HP for char %s to %s (Alive: %s) in guild %s.", character_id, old_hp, old_is_alive, guild_id) # Added
            return True
        return False

    async def revert_stat_changes(self, guild_id: str, character_id: str, stat_changes: List[Dict[str, Any]], **kwargs: Any) -> bool:
        # This is simplified, real revert would apply inverse of stat_changes
        char = self.get_character(guild_id, character_id)
        if char:
            # For a true revert, you'd iterate stat_changes and apply old values
            # For now, just marking dirty and recalculating
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Reverted stat changes for char %s in guild %s (simplified recalc).", character_id, guild_id) # Added
            return True
        return False

    async def revert_party_id_change(self, guild_id: str, character_id: str, old_party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.party_id = old_party_id
            char.current_party_id = old_party_id # Assuming current_party_id should also revert
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Reverted party_id for char %s to %s in guild %s.", character_id, old_party_id, guild_id) # Added
            return True
        return False

    async def revert_xp_change(self, guild_id: str, character_id: str, old_xp: int, old_level: int, old_unspent_xp: int, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            char.experience = old_xp
            char.level = old_level
            char.unspent_xp = old_unspent_xp
            self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            logger.info("CharacterManager: Reverted XP for char %s to L%s, %s XP, %s unspent in guild %s.", character_id, old_level, old_xp, old_unspent_xp, guild_id) # Added
            return True
        return False

    async def revert_status_effect_change(self, guild_id: str, character_id: str, action_taken: str, status_effect_id: str, full_status_effect_data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> bool:
        # Placeholder - needs integration with StatusManager
        logger.debug("CharacterManager: revert_status_effect_change for char %s, action %s, status %s in guild %s.", character_id, action_taken, status_effect_id, guild_id) # Added
        await self._recalculate_and_store_effective_stats(guild_id, character_id) # Recalculate after status change
        return True

    async def revert_inventory_changes(self, guild_id: str, character_id: str, inventory_changes: List[Dict[str, Any]], **kwargs: Any) -> bool:
        # Placeholder - needs integration with ItemManager
        logger.debug("CharacterManager: revert_inventory_changes for char %s in guild %s. Changes: %s", character_id, guild_id, inventory_changes) # Added
        await self._recalculate_and_store_effective_stats(guild_id, character_id) # Recalculate after inventory change
        return True

    async def revert_gold_change(self, guild_id: str, character_id: str, old_gold: int, **kwargs: Any) -> bool:
        # Placeholder - needs gold attribute on Character model
        logger.debug("CharacterManager: revert_gold_change for char %s to %s in guild %s.", character_id, old_gold, guild_id) # Added
        # char = self.get_character(guild_id, character_id)
        # if char and hasattr(char, 'gold'): char.gold = old_gold; self.mark_character_dirty(guild_id, character_id)
        return True

    async def revert_action_queue_change(self, guild_id: str, character_id: str, old_action_queue_json: str, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            try:
                char.action_queue = json.loads(old_action_queue_json)
                self.mark_character_dirty(guild_id, character_id)
                logger.info("CharacterManager: Reverted action queue for char %s in guild %s.", character_id, guild_id) # Added
                return True
            except json.JSONDecodeError:
                logger.error("CharacterManager: Error decoding old_action_queue_json for char %s in guild %s.", character_id, guild_id, exc_info=True) # Added
        return False

    async def revert_collected_actions_change(self, guild_id: str, character_id: str, old_collected_actions_json: str, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char:
            # Assuming 'collected_actions_json' is the field name on the model that stores this JSON string
            if hasattr(char, 'collected_actions_json'):
                char.collected_actions_json = old_collected_actions_json
                self.mark_character_dirty(guild_id, character_id)
                logger.info("CharacterManager: Reverted collected_actions for char %s in guild %s.", character_id, guild_id) # Added
                return True
        return False

    async def revert_character_creation(self, guild_id: str, character_id: str, **kwargs: Any) -> bool:
        self.mark_character_deleted(guild_id, character_id) # This handles cache removal and marks for DB deletion
        logger.info("CharacterManager: Reverted character creation for char %s in guild %s (marked for deletion).", character_id, guild_id) # Added
        return True

    async def recreate_character_from_data(self, guild_id: str, character_data: Dict[str, Any], **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        char_id = character_data.get('id')
        if not char_id:
            logger.error("CharacterManager: Cannot recreate character, missing ID in data for guild %s.", guild_id_str) # Added
            return False
        try:
            # Ensure data is clean for Character.from_dict, especially JSON fields
            # This logic is similar to load_state processing for a single row
            data = character_data.copy() # Avoid modifying original dict
            for k, v_type, d_val_str in [('stats','{}',dict), ('inventory','[]',list), ('action_queue','[]',list),
                               ('state_variables','{}',dict), ('status_effects','[]',list),
                               ('skills_data','[]',list), ('abilities_data','[]',list),
                               ('spells_data','[]',list), ('flags','{}',dict),
                               ('active_quests','[]',list), ('known_spells','[]',list),
                               ('spell_cooldowns','{}',dict)]:
                raw_val = data.get(k) # Use .get() to avoid KeyError if field is missing
                parsed_val = v_type() # Default to empty type
                if isinstance(raw_val, (str, bytes)):
                    try: parsed_val = json.loads(raw_val or d_val_str)
                    except json.JSONDecodeError:
                        logger.warning("CharacterManager: JSONDecodeError for field %s in char %s, guild %s. Using default.", k, char_id, guild_id_str)
                        parsed_val = json.loads(d_val_str) # Load default string
                elif isinstance(raw_val, v_type): parsed_val = raw_val
                data[k] = parsed_val # Ensure the key exists with parsed or default value

            current_action_json = data.get('current_action')
            data['current_action'] = json.loads(current_action_json) if isinstance(current_action_json, str) else (current_action_json if isinstance(current_action_json, dict) else None)

            name_i18n_json = data.get('name_i18n')
            data['name_i18n'] = json.loads(name_i18n_json or '{}') if isinstance(name_i18n_json, str) else (name_i18n_json if isinstance(name_i18n_json, dict) else {})

            if 'name' not in data: # Ensure 'name' exists for Character model
                 data['name'] = data['name_i18n'].get(data.get('selected_language','en'), next(iter(data['name_i18n'].values()), char_id[:8]))


            char = Character.from_dict(data)
            effective_stats_j = character_data.get('effective_stats_json', '{}') # Get from original data
            if not isinstance(effective_stats_j, str): effective_stats_j = json.dumps(effective_stats_j or {})
            setattr(char, 'effective_stats_json', effective_stats_j)

            self._characters.setdefault(guild_id_str, {})[char.id] = char
            if char.discord_user_id:
                 self._discord_to_char_map.setdefault(guild_id_str, {})[char.discord_user_id] = char.id
            if char.current_action or char.action_queue:
                self._entities_with_active_action.setdefault(guild_id_str, set()).add(char.id)

            self.mark_character_dirty(guild_id_str, char.id) # Ensure it's saved
            # Remove from deleted list if it was marked
            self._deleted_characters_ids.get(guild_id_str, set()).discard(char.id)
            logger.info("CharacterManager: Recreated character %s from data in guild %s.", char.id, guild_id_str) # Added
            return True
        except Exception as e:
            logger.error("CharacterManager: Error recreating character %s from data in guild %s: %s", char_id, guild_id_str, e, exc_info=True) # Added
            return False

    def level_up(self, character: Character) -> None:
        """
        Increases a character's level and base stats.
        This method directly modifies the character object.
        Saving and stat recalculation should be handled by the calling method.
        """
        if not character:
            logger.warning("CharacterManager.level_up: Attempted to level up a None character.")
            return

        character.level += 1
        logger.info("CharacterManager.level_up: Character %s (ID: %s) leveled up to %s.", getattr(character, 'name', 'Unknown'), character.id, character.level)

        current_stats = character.stats
        if not isinstance(current_stats, dict):
            logger.warning("CharacterManager.level_up: Character %s (ID: %s) has invalid or missing stats. Initializing to defaults for level up.", getattr(character, 'name', 'Unknown'), character.id)
            current_stats = {
                "base_strength": 10, "base_dexterity": 10, "base_constitution": 10,
                "base_intelligence": 10, "base_wisdom": 10, "base_charisma": 10
            }

        # Increment base stats, using .get() with a default in case a stat is missing
        current_stats["base_strength"] = current_stats.get("base_strength", 10) + 1
        current_stats["base_dexterity"] = current_stats.get("base_dexterity", 10) + 1
        current_stats["base_constitution"] = current_stats.get("base_constitution", 10) + 1
        current_stats["base_intelligence"] = current_stats.get("base_intelligence", 10) + 1
        current_stats["base_wisdom"] = current_stats.get("base_wisdom", 10) + 1
        current_stats["base_charisma"] = current_stats.get("base_charisma", 10) + 1

        character.stats = current_stats
        # Note: Saving/marking dirty and recalculating effective stats is handled by the calling method (e.g., gain_xp)

    async def gain_xp(self, guild_id: str, character_id: str, amount: int) -> Dict[str, Any]:
        """
        Adds XP to a character, handles level ups, and returns update information.
        """
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)

        if not char:
            logger.error("CharacterManager.gain_xp: Character %s not found in guild %s.", character_id, guild_id_str)
            raise ValueError(f"Character {character_id} not found in guild {guild_id_str}")

        if amount <= 0:
            logger.warning("CharacterManager.gain_xp: XP amount must be positive. Received %s for char %s.", amount, character_id)
            raise ValueError("XP amount must be positive.")

        # Ensure 'xp', 'level', and 'stats' attributes exist. The Character model should define these.
        if not all(hasattr(char, attr) for attr in ['xp', 'level', 'stats']):
            logger.error("CharacterManager.gain_xp: Character %s (ID: %s) is missing required attributes (xp, level, or stats).", getattr(char, 'name', 'Unknown'), char.id)
            # Fallback: initialize missing attributes if possible, or raise error
            if not hasattr(char, 'xp'): setattr(char, 'xp', 0)
            if not hasattr(char, 'level'): setattr(char, 'level', 1)
            if not hasattr(char, 'stats'):
                setattr(char, 'stats', {
                    "base_strength": 10, "base_dexterity": 10, "base_constitution": 10,
                    "base_intelligence": 10, "base_wisdom": 10, "base_charisma": 10
                })
            # Or, more strictly: raise AttributeError("Character object is missing critical attributes for XP gain.")


        char.xp += amount
        levels_gained = 0

        # XP requirement formula: current_level * 100 (example)
        # This should ideally come from game settings or rules engine
        xp_for_next_level = char.level * 100

        while char.xp >= xp_for_next_level:
            char.xp -= xp_for_next_level
            self.level_up(char) # Call the synchronous level_up method
            levels_gained += 1
            # Recalculate XP needed for the new level
            xp_for_next_level = char.level * 100

        self.mark_character_dirty(guild_id_str, character_id)
        # Recalculate effective stats, especially if a level was gained.
        await self._recalculate_and_store_effective_stats(guild_id_str, character_id, char)

        logger.info("CharacterManager.gain_xp: Character %s (ID: %s) gained %s XP. Levels gained: %s. New XP: %s, New Level: %s.",
                    getattr(char, 'name', 'Unknown'), char.id, amount, levels_gained, char.xp, char.level)

        # Prepare return data. Using char.to_dict() if available, otherwise manual construction.
        if hasattr(char, 'to_dict') and callable(char.to_dict):
            char_data = char.to_dict()
            # Ensure names match API schema (experience vs xp)
            if 'xp' in char_data and 'experience' not in char_data:
                char_data['experience'] = char_data['xp']
            if 'name_i18n' not in char_data and hasattr(char, 'name_i18n'): # Ensure name_i18n is included
                 char_data['name_i18n'] = char.name_i18n
            if 'class_i18n' not in char_data and hasattr(char, 'character_class'): # Map character_class to class_i18n if needed
                 char_data['class_i18n'] = {"en": char.character_class} # Example mapping

        else:
            # Manual construction, try to match CharacterResponse schema
            char_data = {
                "id": char.id,
                "player_id": str(char.discord_user_id) if hasattr(char, 'discord_user_id') else None, # Assuming discord_user_id maps to player_id
                "guild_id": guild_id_str,
                "name_i18n": getattr(char, 'name_i18n', {"en": getattr(char, 'name', '')}),
                "class_i18n": {"en": getattr(char, 'character_class', "N/A")}, # Example mapping
                "description_i18n": getattr(char, 'description_i18n', {}), # Assuming this exists or is added
                "level": char.level,
                "experience": char.xp, # Mapping xp to experience for the response
                "stats": char.stats, # This should be the base stats dict
                "current_hp": getattr(char, 'hp', 0),
                "max_hp": getattr(char, 'max_health', 0), # Assuming max_health maps to max_hp
                "abilities": getattr(char, 'abilities_data', []), # Assuming abilities_data exists
                "inventory": getattr(char, 'inventory', []), # Assuming inventory exists
                "npc_relationships": getattr(char, 'npc_relationships', {}), # Assuming this exists or is added
                "is_active_char": getattr(char, 'is_active_char', False) # Assuming this exists or is added
            }

        # If effective_stats are stored on char model as a JSON string, parse them for the response
        # This part is speculative based on _recalculate_and_store_effective_stats
        effective_stats_json_str = getattr(char, 'effective_stats_json', '{}')
        try:
            effective_stats = json.loads(effective_stats_json_str)
        except json.JSONDecodeError:
            effective_stats = {}

        # The CharacterResponse schema might expect stats to be the base stats (CharacterStatsSchema)
        # and might have a separate field for effective/derived stats.
        # For now, char_data['stats'] is the base stats. If effective stats need to be part of char_data:
        # char_data['effective_stats'] = effective_stats # Or merge as appropriate

        return {
            "updated_character_data": char_data, # This should ideally match CharacterResponse schema
            "levels_gained": levels_gained,
            "xp_added": amount,
            "xp_for_next_level": xp_for_next_level, # Added for context
            "effective_stats_preview": effective_stats # Added for context, might not be part of final response
        }
