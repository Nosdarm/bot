# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
# Import typing components
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union

# --- Imports ---
from bot.game.models.character import Character
from builtins import dict, set, list, int # Use lowercase for isinstance

# --- Imports needed ONLY for Type Checking ---
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
    from bot.game.managers.npc_manager import NPCManager
    from bot.game.managers.game_manager import GameManager


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
        game_manager: Optional["GameManager"] = None
    ):
        print("Initializing CharacterManager...")
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
        self._game_manager = game_manager

        self._characters = {}
        self._discord_to_char_map = {}
        self._entities_with_active_action = {}
        self._dirty_characters = {}
        self._deleted_characters_ids = {}
        print("CharacterManager initialized.")

    async def _recalculate_and_store_effective_stats(self, guild_id: str, character_id: str, char_model: Optional[Character] = None) -> None:
        """Helper to recalculate and store effective stats for a character."""
        if not char_model: # Fetch if not provided
            char_model = self.get_character(guild_id, character_id)
            if not char_model:
                print(f"CharacterManager: ERROR - Character {character_id} not found for effective stats recalc.")
                return

        # Ensure all required managers are available
        if not (self._rule_engine and self._item_manager and self._status_manager and
                  self._npc_manager and self._db_service and hasattr(self._rule_engine, 'rules_config_data')):
            missing_deps = [dep_name for dep_name, dep in [
                ("rule_engine", self._rule_engine), ("item_manager", self._item_manager),
                ("status_manager", self._status_manager), ("npc_manager", self._npc_manager), # NpcManager needed by calculator
                ("db_service", self._db_service)
            ] if dep is None]
            if self._rule_engine and not hasattr(self._rule_engine, 'rules_config_data'):
                missing_deps.append("rule_engine.rules_config_data")

            print(f"CharacterManager: WARNING - Could not recalculate effective_stats for {character_id} due to missing dependencies: {missing_deps}.")
            setattr(char_model, 'effective_stats_json', "{}")
            return

        from bot.game.utils import stats_calculator # Local import for safety
        try:
            rules_config = self._rule_engine.rules_config_data
            effective_stats_dict = await stats_calculator.calculate_effective_stats(
                db_service=self._db_service, guild_id=guild_id, entity_id=character_id,
                entity_type="Character", rules_config_data=rules_config,
                character_manager=self, npc_manager=self._npc_manager,
                item_manager=self._item_manager, status_manager=self._status_manager
            )
            setattr(char_model, 'effective_stats_json', json.dumps(effective_stats_dict))
            # print(f"CharacterManager: Recalculated effective_stats for character {character_id}.") # Can be noisy
        except Exception as es_ex:
            print(f"CharacterManager: ERROR recalculating effective_stats for {character_id}: {es_ex}")
            traceback.print_exc()
            setattr(char_model, 'effective_stats_json', "{}")

    async def trigger_stats_recalculation(self, guild_id: str, character_id: str) -> None:
        """Public method to trigger effective stats recalculation and mark character dirty."""
        char = self.get_character(guild_id, character_id)
        if char:
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            self.mark_character_dirty(guild_id, character_id)
            print(f"CharacterManager: Stats recalculation triggered and character {character_id} marked dirty.")
        else:
            print(f"CharacterManager: trigger_stats_recalculation - Character {character_id} not found in guild {guild_id}.")


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
                 char = self.get_character(guild_id, char_id)
                 if not char:
                     print(f"CRITICAL: CharacterManager: Char_id '{char_id}' for Discord ID {discord_user_id} found in map, but character NOT in _characters cache for guild {guild_id_str}! Cache inconsistency.")
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
        log_prefix = "CM.create_character DEBUG:"
        if self._db_service is None or self._db_service.adapter is None:
            raise ConnectionError("Database service or adapter is not initialized in CharacterManager.")
        guild_id_str = str(guild_id)
        if self.get_character_by_discord_id(guild_id_str, discord_id): return None
        if self.get_character_by_name(guild_id_str, name): return None
        new_id = str(uuid.uuid4())
        stats = {'strength': 10, 'dexterity': 10, 'intelligence': 10}
        if self._rule_engine and hasattr(self._rule_engine, 'generate_initial_character_stats'):
            try:
                generated_stats = self._rule_engine.generate_initial_character_stats()
                if isinstance(generated_stats, dict): stats = generated_stats
            except Exception: traceback.print_exc()
        default_player_language = "en"
        if hasattr(self, '_game_manager') and self._game_manager and hasattr(self._game_manager, 'get_default_bot_language'):
            try: default_player_language = self._game_manager.get_default_bot_language()
            except Exception: default_player_language = "en"
        resolved_initial_location_id = initial_location_id
        if resolved_initial_location_id is None and self._settings:
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            default_loc_id = guild_settings.get('default_start_location_id') or self._settings.get('default_start_location_id')
            if default_loc_id: resolved_initial_location_id = str(default_loc_id)
        elif initial_location_id: resolved_initial_location_id = str(initial_location_id)

        name_i18n_data = {"en": name, "ru": name}
        data: Dict[str, Any] = {
            'id': new_id, 'discord_id': discord_id, 'name': name, 'name_i18n': name_i18n_data,
            'guild_id': guild_id_str, 'current_location_id': resolved_initial_location_id,
            'stats': stats, 'inventory': [], 'current_action': None, 'action_queue': [],
            'party_id': None, 'state_variables': {}, 'hp': 100.0, 'max_health': 100.0,
            'is_alive': True, 'status_effects': [], 'level': level, 'experience': experience,
            'unspent_xp': unspent_xp, 'selected_language': default_player_language,
            'collected_actions_json': None, 'skills_data_json': json.dumps([]),
            'abilities_data_json': json.dumps([]), 'spells_data_json': json.dumps([]),
            'character_class': kwargs.get('character_class', 'Adventurer'),
            'flags_json': json.dumps({}), 'effective_stats_json': "{}"
        }
        model_data = data.copy()
        model_data['discord_user_id'] = model_data.pop('discord_id')
        for k_json in ['skills_data_json', 'abilities_data_json', 'spells_data_json', 'flags_json', 'effective_stats_json']:
            if k_json in model_data: del model_data[k_json]
        model_data['skills_data']=[]; model_data['abilities_data']=[]; model_data['spells_data']=[]; model_data['flags']={}

        sql = """
        INSERT INTO players (
            id, discord_id, name_i18n, guild_id, current_location_id, stats, inventory,
            current_action, action_queue, party_id, state_variables,
            hp, max_health, is_alive, status_effects, level, xp, unspent_xp,
            selected_language, collected_actions_json,
            skills_data_json, abilities_data_json, spells_data_json, character_class, flags_json, effective_stats_json
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26)
        RETURNING id;
        """
        db_params = (
            data['id'], str(data['discord_id']), json.dumps(data['name_i18n']), data['guild_id'],
            data['current_location_id'], json.dumps(data['stats']), json.dumps(data['inventory']),
            json.dumps(data['current_action']) if data['current_action'] is not None else None,
            json.dumps(data['action_queue']), data['party_id'], json.dumps(data['state_variables']),
            data['hp'], data['max_health'], data['is_alive'], json.dumps(data['status_effects']),
            data['level'], data['experience'], data['unspent_xp'], data['selected_language'],
            data['collected_actions_json'], data['skills_data_json'], data['abilities_data_json'],
            data['spells_data_json'], data['character_class'], data['flags_json'], data['effective_stats_json']
        )
        try:
            await self._db_service.adapter.execute_insert(sql, db_params)
            char = Character.from_dict(model_data)
            setattr(char, 'effective_stats_json', data['effective_stats_json'])

            self._characters.setdefault(guild_id_str, {})[char.id] = char
            if char.discord_user_id is not None:
                 self._discord_to_char_map.setdefault(guild_id_str, {})[char.discord_user_id] = char.id

            await self._recalculate_and_store_effective_stats(guild_id_str, char.id, char)
            self.mark_character_dirty(guild_id_str, char.id)
            print(f"{log_prefix} Character '{char.name}' (ID: {char.id}) created.")
            return char
        except Exception as e:
            print(f"CharacterManager: Error creating character '{name}': {e}")
            traceback.print_exc(); raise

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or self._db_service.adapter is None: return
        guild_id_str = str(guild_id)
        dirty_ids = self._dirty_characters.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_characters_ids.get(guild_id_str, set()).copy()
        if not dirty_ids and not deleted_ids: return

        if deleted_ids:
            # ... (deletion logic as before) ...
            ids_to_delete_list = list(deleted_ids)
            if ids_to_delete_list:
                pg_placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_delete_list))])
                delete_sql = f"DELETE FROM players WHERE guild_id = $1 AND id IN ({pg_placeholders})"
                try:
                    await self._db_service.adapter.execute(delete_sql, (guild_id_str, *ids_to_delete_list))
                    self._deleted_characters_ids.pop(guild_id_str, None)
                except Exception as e: print(f"Error deleting characters: {e}"); traceback.print_exc()
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
                character_class, selected_language, current_game_status, collected_actions_json, current_party_id, effective_stats_json
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30, $31)
            ON CONFLICT (id) DO UPDATE SET
                discord_id=EXCLUDED.discord_id, name_i18n=EXCLUDED.name_i18n, guild_id=EXCLUDED.guild_id, current_location_id=EXCLUDED.current_location_id, stats=EXCLUDED.stats, inventory=EXCLUDED.inventory, current_action=EXCLUDED.current_action, action_queue=EXCLUDED.action_queue, party_id=EXCLUDED.party_id, state_variables=EXCLUDED.state_variables, hp=EXCLUDED.hp, max_health=EXCLUDED.max_health, is_alive=EXCLUDED.is_alive, status_effects=EXCLUDED.status_effects, level=EXCLUDED.level, xp=EXCLUDED.experience, unspent_xp=EXCLUDED.unspent_xp, active_quests=EXCLUDED.active_quests, known_spells=EXCLUDED.known_spells, spell_cooldowns=EXCLUDED.spell_cooldowns, skills_data_json=EXCLUDED.skills_data_json, abilities_data_json=EXCLUDED.abilities_data_json, spells_data_json=EXCLUDED.spells_data_json, flags_json=EXCLUDED.flags_json, character_class=EXCLUDED.character_class, selected_language=EXCLUDED.selected_language, current_game_status=EXCLUDED.current_game_status, collected_actions_json=EXCLUDED.collected_actions_json, current_party_id=EXCLUDED.current_party_id, effective_stats_json=EXCLUDED.effective_stats_json;
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
                        effective_stats_j
                    )
                    data_to_upsert.append(db_params)
                    processed_dirty_ids.add(char_obj.id)
                except Exception as e: print(f"Error preparing char {char_obj.id} for save: {e}")

            if data_to_upsert:
                try:
                    await self._db_service.adapter.execute_many(upsert_sql, data_to_upsert)
                    if guild_id_str in self._dirty_characters:
                        self._dirty_characters[guild_id_str].difference_update(processed_dirty_ids)
                        if not self._dirty_characters[guild_id_str]: del self._dirty_characters[guild_id_str]
                except Exception as e: print(f"Error batch upserting characters: {e}")

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or self._db_service.adapter is None: return
        guild_id_str = str(guild_id)
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
                   active_quests, known_spells, spell_cooldowns, effective_stats_json
            FROM players WHERE guild_id = $1
            '''
            rows = await self._db_service.adapter.fetchall(sql, (guild_id_str,))
        except Exception as e: print(f"DB fetchall error: {e}"); traceback.print_exc(); raise
        guild_chars_cache = self._characters[guild_id_str]
        guild_discord_map_cache = self._discord_to_char_map[guild_id_str]
        guild_active_action_cache = self._entities_with_active_action[guild_id_str]
        for row in rows:
            data = dict(row)
            try:
                char_id = str(data.get('id'))
                data['effective_stats_json'] = data.get('effective_stats_json', '{}')
                for k, v_type, d_val_str in [('stats','{}',dict), ('inventory','[]',list), ('action_queue','[]',list),
                                   ('state_variables','{}',dict), ('status_effects','[]',list),
                                   ('skills_data_json','[]',list), ('abilities_data_json','[]',list),
                                   ('spells_data_json','[]',list), ('flags_json','{}',dict),
                                   ('active_quests','[]',list), ('known_spells','[]',list),
                                   ('spell_cooldowns','{}',dict)]:
                    raw_val = data.get(k)
                    parsed_val = v_type()
                    if isinstance(raw_val, (str, bytes)): parsed_val = json.loads(raw_val or d_val_str)
                    elif isinstance(raw_val, v_type): parsed_val = raw_val
                    data[k.replace('_json','')] = parsed_val
                    if '_json' in k and k in data: del data[k]
                current_action_json = data.get('current_action')
                data['current_action'] = json.loads(current_action_json) if isinstance(current_action_json, str) else (current_action_json if isinstance(current_action_json, dict) else None)
                name_i18n_json = data.get('name_i18n')
                data['name_i18n'] = json.loads(name_i18n_json or '{}') if isinstance(name_i18n_json, str) else (name_i18n_json if isinstance(name_i18n_json, dict) else {})
                data['name'] = data['name_i18n'].get(data.get('selected_language','en'), next(iter(data['name_i18n'].values()), char_id[:8]))
                data['discord_user_id'] = int(data['discord_id']) if data.get('discord_id') else None
                if 'discord_id' in data: del data['discord_id']
                char = Character.from_dict(data)
                setattr(char, 'effective_stats_json', data.get('effective_stats_json', '{}'))
                guild_chars_cache[char.id] = char
                if char.discord_user_id: guild_discord_map_cache[char.discord_user_id] = char.id
                if char.current_action or char.action_queue: guild_active_action_cache.add(char.id)
            except Exception as e: print(f"Error processing char row {data.get('id')}: {e}")

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None: pass
    def mark_character_dirty(self, guild_id: str, character_id: str) -> None:
         if str(guild_id) in self._characters and character_id in self._characters[str(guild_id)]:
              self._dirty_characters.setdefault(str(guild_id), set()).add(character_id)
    def mark_character_deleted(self, guild_id: str, character_id: str) -> None: pass # Placeholder
    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char: char.party_id = str(party_id) if party_id else None; self.mark_character_dirty(guild_id, character_id); await self._recalculate_and_store_effective_stats(guild_id, character_id, char); return True
        return False
    async def update_character_location(self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any) -> Optional["Character"]:
        char = self.get_character(guild_id, character_id)
        if char: char.current_location_id = str(location_id) if location_id else None; self.mark_character_dirty(guild_id, character_id); await self._recalculate_and_store_effective_stats(guild_id, character_id, char); return char
        return None
    async def add_item_to_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool: return True
    async def remove_item_from_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool: return True
    async def update_health(self, guild_id: str, character_id: str, amount: float, **kwargs: Any) -> bool:
         guild_id_str = str(guild_id); char = self.get_character(guild_id_str, character_id)
         if not char or not all(hasattr(char, attr) for attr in ['hp', 'max_health', 'is_alive']): return False
         old_hp_val = char.hp; old_is_alive_val = char.is_alive
         if not old_is_alive_val and amount <= 0: return False
         current_max_hp = char.max_health
         eff_stats_json = getattr(char, 'effective_stats_json', '{}')
         if isinstance(eff_stats_json, str) and eff_stats_json:
             try: current_max_hp = json.loads(eff_stats_json).get('max_hp', char.max_health)
             except json.JSONDecodeError: pass
         char.hp = max(0.0, min(float(current_max_hp), old_hp_val + amount))
         new_is_alive_status = char.hp > 0
         hp_changed = char.hp != old_hp_val; is_alive_status_changed = new_is_alive_status != old_is_alive_val
         char.is_alive = new_is_alive_status
         if hp_changed or is_alive_status_changed:
            self.mark_character_dirty(guild_id_str, character_id)
            await self._recalculate_and_store_effective_stats(guild_id_str, character_id, char)
         if char.hp <= 0 and old_is_alive_val:
              await self.handle_character_death(guild_id_str, character_id, hp_before_death_processing=old_hp_val, was_alive_before_death_processing=old_is_alive_val, **kwargs)
         return True
    async def update_character_stats(self, guild_id: str, character_id: str, stats_update: Dict[str, Any], **kwargs: Any) -> bool:
        guild_id_str = str(guild_id); char = self.get_character(guild_id_str, character_id)
        if not char: return False
        updated_fields = []; recalc_needed = False
        for key, value in stats_update.items():
            try:
                if key == "hp": await self.update_health(guild_id_str, character_id, float(value) - char.hp, **kwargs); updated_fields.append(f"hp to {char.hp}"); continue
                elif key.startswith("stats."):
                    stat_name = key.split("stats.", 1)[1]
                    if not hasattr(char, 'stats') or not isinstance(char.stats, dict): char.stats = {}
                    if char.stats.get(stat_name) != value: char.stats[stat_name] = value; updated_fields.append(f"{key} to {value}"); recalc_needed = True
                elif hasattr(char, key):
                    if getattr(char, key) != value: setattr(char, key, value); updated_fields.append(f"{key} to {value}"); recalc_needed = True
                else: continue
            except Exception: pass
        if updated_fields:
            self.mark_character_dirty(guild_id_str, character_id)
            if recalc_needed: await self._recalculate_and_store_effective_stats(guild_id_str, character_id, char)
            return True
        return False
    async def handle_character_death(self, guild_id: str, character_id: str, **kwargs: Any):
        char = self.get_character(guild_id, character_id)
        if char and getattr(char, 'is_alive', False):
            char.is_alive = False; self.mark_character_dirty(guild_id, character_id)
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
        elif char: print(f"Character {character_id} already marked as not alive.")
        else: print(f"Character {character_id} not found for death processing.")
    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None: pass
    def add_action_to_queue(self, guild_id: str, character_id: str, action_details: Dict[str, Any]) -> None: pass
    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]: return None
    async def save_character(self, character: "Character", guild_id: str) -> bool:
        if self._db_service is None or not hasattr(self._db_service, 'adapter') or self._db_service.adapter is None: return False
        self.mark_character_dirty(guild_id, character.id)
        return True
    async def set_current_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char: char.current_party_id = str(party_id) if party_id else None; self.mark_character_dirty(guild_id, character_id); await self._recalculate_and_store_effective_stats(guild_id, character_id, char); return True
        return False
    async def save_character_field(self, guild_id: str, character_id: str, field_name: str, value: Any, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id)
        if char and hasattr(char, field_name):
            setattr(char, field_name, value); self.mark_character_dirty(guild_id, character_id)
            if field_name.startswith("stats") or field_name == "level": await self._recalculate_and_store_effective_stats(guild_id, character_id, char)
            return True
        return False
    async def revert_location_change(self, guild_id: str, character_id: str, old_location_id: str, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id);
        if char: char.current_location_id = old_location_id; self.mark_character_dirty(guild_id, character_id); await self._recalculate_and_store_effective_stats(guild_id, character_id, char); return True
        return False
    async def revert_hp_change(self, guild_id: str, character_id: str, old_hp: float, old_is_alive: bool, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id);
        if char: char.hp = old_hp; char.is_alive = old_is_alive; self.mark_character_dirty(guild_id, character_id); await self._recalculate_and_store_effective_stats(guild_id, character_id, char); return True
        return False
    async def revert_stat_changes(self, guild_id: str, character_id: str, stat_changes: List[Dict[str, Any]], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id);
        if char: self.mark_character_dirty(guild_id, character_id); await self._recalculate_and_store_effective_stats(guild_id, character_id, char); return True # Simplified
        return False
    async def revert_party_id_change(self, guild_id: str, character_id: str, old_party_id: Optional[str], **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id);
        if char: char.party_id = old_party_id; char.current_party_id = old_party_id; self.mark_character_dirty(guild_id, character_id); await self._recalculate_and_store_effective_stats(guild_id, character_id, char); return True
        return False
    async def revert_xp_change(self, guild_id: str, character_id: str, old_xp: int, old_level: int, old_unspent_xp: int, **kwargs: Any) -> bool:
        char = self.get_character(guild_id, character_id);
        if char: char.experience = old_xp; char.level = old_level; char.unspent_xp = old_unspent_xp; self.mark_character_dirty(guild_id, character_id); await self._recalculate_and_store_effective_stats(guild_id, character_id, char); return True
        return False
    async def revert_status_effect_change(self, guild_id: str, character_id: str, action_taken: str, status_effect_id: str, full_status_effect_data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> bool: return True
    async def revert_inventory_changes(self, guild_id: str, character_id: str, inventory_changes: List[Dict[str, Any]], **kwargs: Any) -> bool: return True
    async def revert_gold_change(self, guild_id: str, character_id: str, old_gold: int, **kwargs: Any) -> bool: return True
    async def revert_action_queue_change(self, guild_id: str, character_id: str, old_action_queue_json: str, **kwargs: Any) -> bool: return True
    async def revert_collected_actions_change(self, guild_id: str, character_id: str, old_collected_actions_json: str, **kwargs: Any) -> bool: return True
    async def revert_character_creation(self, guild_id: str, character_id: str, **kwargs: Any) -> bool: return True
    async def recreate_character_from_data(self, guild_id: str, character_data: Dict[str, Any], **kwargs: Any) -> bool: return True
