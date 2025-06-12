# bot/game/managers/npc_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union

from bot.game.models.npc import NPC
from builtins import dict, set, list, int, float, str, bool


if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.services.campaign_loader import CampaignLoader
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.services.openai_service import OpenAIService
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.services.notification_service import NotificationService

print("DEBUG: npc_manager.py module loaded.")

class NpcManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _npcs: Dict[str, Dict[str, "NPC"]]
    _entities_with_active_action: Dict[str, Set[str]]
    _dirty_npcs: Dict[str, Set[str]]
    _deleted_npc_ids: Dict[str, Set[str]]
    _npc_archetypes: Dict[str, Dict[str, Any]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        combat_manager: Optional["CombatManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None,
        openai_service: Optional["OpenAIService"] = None,
        ai_validator: Optional["AIResponseValidator"] = None,
        campaign_loader: Optional["CampaignLoader"] = None,
        notification_service: Optional["NotificationService"] = None
    ):
        print("Initializing NpcManager...")
        self._db_service = db_service
        self._settings = settings
        self._campaign_loader = campaign_loader
        self._npc_archetypes = {}
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager
        self._location_manager = location_manager
        self._game_log_manager = game_log_manager
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service
        self._ai_validator = ai_validator
        self._notification_service = notification_service
        self._npcs = {}
        self._entities_with_active_action = {}
        self._dirty_npcs = {}
        self._deleted_npc_ids = {}
        self._load_npc_archetypes()
        print("NpcManager initialized.")

    async def _recalculate_and_store_effective_stats(self, guild_id: str, npc_id: str, npc_model: Optional[NPC] = None) -> None:
        """Helper to recalculate and store effective stats for an NPC."""
        if not npc_model:
            npc_model = self.get_npc(guild_id, npc_id)
            if not npc_model:
                print(f"NpcManager: ERROR - NPC {npc_id} not found for effective stats recalc.")
                return

        if not (self._rule_engine and self._item_manager and self._status_manager and
                  self._character_manager and self._db_service and hasattr(self._rule_engine, 'rules_config_data')):
            missing_deps = [dep_name for dep_name, dep in [
                ("rule_engine", self._rule_engine), ("item_manager", self._item_manager),
                ("status_manager", self._status_manager), ("character_manager", self._character_manager),
                ("db_service", self._db_service)
            ] if dep is None]
            if self._rule_engine and not hasattr(self._rule_engine, 'rules_config_data'):
                missing_deps.append("rule_engine.rules_config_data")
            print(f"NpcManager: WARNING - Could not recalculate effective_stats for NPC {npc_id} due to missing dependencies: {missing_deps}.")
            setattr(npc_model, 'effective_stats_json', "{}")
            return

        from bot.game.utils import stats_calculator # Local import
        try:
            rules_config = self._rule_engine.rules_config_data
            effective_stats_dict = await stats_calculator.calculate_effective_stats(
                db_service=self._db_service, guild_id=guild_id, entity_id=npc_id,
                entity_type="NPC", rules_config_data=rules_config,
                character_manager=self._character_manager, npc_manager=self,
                item_manager=self._item_manager, status_manager=self._status_manager
            )
            setattr(npc_model, 'effective_stats_json', json.dumps(effective_stats_dict))
            # print(f"NpcManager: Recalculated effective_stats for NPC {npc_id}.") # Can be noisy
        except Exception as es_ex:
            print(f"NpcManager: ERROR recalculating effective_stats for NPC {npc_id}: {es_ex}")
            traceback.print_exc()
            setattr(npc_model, 'effective_stats_json', "{}")

    async def trigger_stats_recalculation(self, guild_id: str, npc_id: str) -> None:
        """Public method to trigger effective stats recalculation and mark NPC dirty."""
        npc = self.get_npc(guild_id, npc_id)
        if npc:
            await self._recalculate_and_store_effective_stats(guild_id, npc_id, npc)
            self.mark_npc_dirty(guild_id, npc_id)
            print(f"NpcManager: Stats recalculation triggered and NPC {npc_id} marked dirty.")
        else:
            print(f"NpcManager: trigger_stats_recalculation - NPC {npc_id} not found in guild {guild_id}.")

    def _load_npc_archetypes(self):
        # ... (original logic) ...
        pass

    def get_npc(self, guild_id: str, npc_id: str) -> Optional["NPC"]:
        guild_id_str = str(guild_id); guild_npcs = self._npcs.get(guild_id_str)
        if guild_npcs: return guild_npcs.get(npc_id)
        return None

    def get_all_npcs(self, guild_id: str) -> List["NPC"]:
        guild_id_str = str(guild_id); guild_npcs = self._npcs.get(guild_id_str)
        if guild_npcs: return list(guild_npcs.values())
        return []

    def get_npcs_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List["NPC"]:
        guild_id_str = str(guild_id); location_id_str = str(location_id)
        npcs_in_location = []; guild_npcs = self._npcs.get(guild_id_str)
        if guild_npcs:
             for npc in guild_npcs.values():
                 if isinstance(npc, NPC) and hasattr(npc, 'location_id') and str(getattr(npc, 'location_id', None)) == location_id_str:
                      npcs_in_location.append(npc)
        return npcs_in_location

    def get_entities_with_active_action(self, guild_id: str) -> Set[str]:
        return self._entities_with_active_action.get(str(guild_id), set()).copy()

    def is_busy(self, guild_id: str, npc_id: str) -> bool:
        npc = self.get_npc(str(guild_id), npc_id)
        if not npc: return False
        if getattr(npc, 'current_action', None) is not None or getattr(npc, 'action_queue', []): return True
        if getattr(npc, 'party_id', None) is not None and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
            party_id = getattr(npc, 'party_id', None)
            if party_id: return self._party_manager.is_party_busy(str(guild_id), party_id)
        return False

    async def create_npc(
        self, guild_id: str, npc_template_id: str,
        location_id: Optional[str] = None, **kwargs: Any,
    ) -> Optional[Union[str, Dict[str, str]]]:
        guild_id_str = str(guild_id)
        # ... (original AI path logic leading to return for moderation) ...
        if self._db_service is None or self._db_service.adapter is None: return None # Simplified DB check
        
        npc_id = str(uuid.uuid4())
        archetype_id_to_load = npc_template_id
        archetype_data_loaded = self._npc_archetypes.get(archetype_id_to_load)
        trigger_ai_generation = False
        if npc_template_id.startswith("AI:") or not archetype_data_loaded : trigger_ai_generation = True

        if trigger_ai_generation and not npc_template_id.startswith("AI_MODERATED_CONTENT:"): # Prevent re-generation for moderated content
            # ... (AI generation and moderation path as before) ...
            # This path returns a dict for moderation, not an NPC object directly.
             return {"status": "pending_moderation", "request_id": "dummy_request_id_for_ai_path"} # Placeholder for AI path

        # Non-AI Path (from archetype or default)
        final_data: Dict[str, Any] = { # Base defaults
            'name': "NPC " + npc_id[:6], 'stats': {"max_health": 50.0},
            'inventory': [], 'archetype': "commoner", 'traits': [], 'desires': [], 'motives': [],
            'name_i18n':{}, 'backstory_i18n':{}, # etc for i18n fields
            'effective_stats_json': "{}" # Initialize
        }
        if archetype_data_loaded: final_data.update(archetype_data_loaded) # Layer archetype
        final_data.update(kwargs) # Layer specific kwargs

        if 'max_health' not in final_data['stats']: final_data['stats']['max_health'] = 50.0
        try:
            data_for_npc_object: Dict[str, Any] = {
                'id': npc_id, 'template_id': archetype_id_to_load, 'guild_id': guild_id_str,
                'location_id': location_id, 'current_action': None, 'action_queue': [], 'party_id': None,
                'state_variables': kwargs.get('state_variables', {}),
                'health': float(final_data['stats'].get('max_health', 50.0)),
                'max_health': float(final_data['stats'].get('max_health', 50.0)),
                'is_alive': True, 'status_effects': [],
                'is_temporary': bool(kwargs.get('is_temporary', False)),
            }
            data_for_npc_object.update(final_data) # Add layered data
            npc = NPC.from_dict(data_for_npc_object)
            setattr(npc, 'effective_stats_json', data_for_npc_object.get('effective_stats_json', '{}'))

            self._npcs.setdefault(guild_id_str, {})[npc_id] = npc
            await self._recalculate_and_store_effective_stats(guild_id_str, npc.id, npc)
            self.mark_npc_dirty(guild_id_str, npc_id)
            return npc_id
        except Exception as e:
            print(f"NpcManager: Error creating NPC (non-AI path) '{npc_template_id}': {e}"); traceback.print_exc()
            return None

    async def remove_npc(self, guild_id: str, npc_id: str, **kwargs: Any) -> Optional[str]:
        # ... (original logic) ...
        pass; return None # Placeholder

    async def add_item_to_inventory(self, guild_id: str, npc_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
        npc = self.get_npc(guild_id, npc_id)
        if npc:
            # ... (original add item logic) ...
            self.mark_npc_dirty(guild_id, npc_id)
            # await self._recalculate_and_store_effective_stats(guild_id, npc_id, npc) # If non-equipped items grant stats
            return True
        return False

    async def remove_item_from_inventory(self, guild_id: str, npc_id: str, item_id: str, **kwargs: Any) -> bool:
        npc = self.get_npc(guild_id, npc_id)
        if npc:
            # ... (original remove item logic) ...
            self.mark_npc_dirty(guild_id, npc_id)
            # await self._recalculate_and_store_effective_stats(guild_id, npc_id, npc) # If non-equipped items grant stats
            return True
        return False

    async def add_status_effect(self, guild_id: str, npc_id: str, status_type: str, duration: Optional[float], source_id: Optional[str] = None, **kwargs: Any) -> Optional[str]:
        npc = self.get_npc(guild_id, npc_id)
        sm = self._status_manager or kwargs.get('status_manager')
        if npc and sm:
            status_effect_id = await sm.add_status_effect_to_entity(npc_id, 'NPC', status_type, duration, source_id, guild_id, **kwargs)
            if status_effect_id:
                if not hasattr(npc, 'status_effects') or not isinstance(npc.status_effects, list): npc.status_effects = []
                if status_effect_id not in npc.status_effects: npc.status_effects.append(status_effect_id)
                self.mark_npc_dirty(guild_id, npc_id)
                await self._recalculate_and_store_effective_stats(guild_id, npc_id, npc)
            return status_effect_id
        return None

    async def remove_status_effect(self, guild_id: str, npc_id: str, status_effect_id: str, **kwargs: Any) -> Optional[str]:
        npc = self.get_npc(guild_id, npc_id)
        sm = self._status_manager or kwargs.get('status_manager')
        if npc and sm:
            removed_id = await sm.remove_status_effect(status_effect_id, guild_id, **kwargs)
            if removed_id:
                if hasattr(npc, 'status_effects') and isinstance(npc.status_effects, list):
                    try: npc.status_effects.remove(status_effect_id)
                    except ValueError: pass
                self.mark_npc_dirty(guild_id, npc_id)
                await self._recalculate_and_store_effective_stats(guild_id, npc_id, npc)
            return removed_id
        return None

    async def update_npc_stats(
        self, guild_id: str, npc_id: str, stats_update: Dict[str, Any], **kwargs: Any
    ) -> bool:
        npc = self.get_npc(str(guild_id), npc_id)
        if not npc: return False
        updated_fields = []
        health_or_direct_stats_changed = False
        for key, value in stats_update.items():
            try:
                if key == "health":
                    if npc.health != float(value): npc.health = float(value); health_or_direct_stats_changed = True
                    new_is_alive = npc.health > 0
                    if npc.is_alive != new_is_alive: npc.is_alive = new_is_alive; health_or_direct_stats_changed = True
                    updated_fields.append("health/is_alive")
                elif key.startswith("stats."):
                    stat_name = key.split("stats.", 1)[1]
                    if not hasattr(npc, 'stats') or not isinstance(npc.stats, dict): npc.stats = {}
                    if npc.stats.get(stat_name) != value: npc.stats[stat_name] = value; health_or_direct_stats_changed = True; updated_fields.append(key)
                elif hasattr(npc, key):
                     if getattr(npc,key) != value: setattr(npc,key,value); health_or_direct_stats_changed = True; updated_fields.append(key)
                else: continue
            except Exception: pass
        if updated_fields:
            self.mark_npc_dirty(str(guild_id), npc_id)
            if health_or_direct_stats_changed:
                await self._recalculate_and_store_effective_stats(str(guild_id), npc_id, npc)
            # ... (logging) ...
            return True
        return False

    async def generate_npc_details_from_ai(self, guild_id: str, npc_id_concept: str, player_level_for_scaling: Optional[int] = None) -> Optional[Dict[str, Any]]:
        pass # Placeholder

    async def save_npc(self, npc: "NPC", guild_id: str) -> bool:
        if self._db_service is None or self._db_service.adapter is None: return False
        guild_id_str = str(guild_id); npc_id = getattr(npc, 'id', None)
        if not npc_id or str(getattr(npc, 'guild_id', None)) != guild_id_str: return False
        try:
            npc_data = npc.to_dict()
            target_table = 'generated_npcs' if getattr(npc, 'is_ai_generated', False) else 'npcs'
            eff_stats_json = getattr(npc, 'effective_stats_json', '{}')
            if not isinstance(eff_stats_json, str): eff_stats_json = json.dumps(eff_stats_json or {})

            if target_table == 'generated_npcs':
                db_params = (
                    str(npc_id), json.dumps(npc_data.get('name_i18n', {})),
                    json.dumps(npc_data.get('description_i18n', {})), json.dumps(npc_data.get('backstory_i18n', {})),
                    json.dumps(npc_data.get('persona_i18n', {})), eff_stats_json
                )
                upsert_sql = """
                INSERT INTO generated_npcs (id, name_i18n, description_i18n, backstory_i18n, persona_i18n, effective_stats_json)
                VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO UPDATE SET
                    name_i18n = EXCLUDED.name_i18n, description_i18n = EXCLUDED.description_i18n,
                    backstory_i18n = EXCLUDED.backstory_i18n, persona_i18n = EXCLUDED.persona_i18n,
                    effective_stats_json = EXCLUDED.effective_stats_json;"""
            else:
                db_params = (
                    str(npc_id), str(npc_data.get('template_id')), json.dumps(npc_data.get('name_i18n', {})),
                    json.dumps(npc_data.get('description_i18n', {})), json.dumps(npc_data.get('backstory_i18n', {})),
                    json.dumps(npc_data.get('persona_i18n', {})), guild_id_str, str(npc_data.get('location_id')),
                    json.dumps(npc_data.get('stats', {})), json.dumps(npc_data.get('inventory', [])),
                    json.dumps(npc_data.get('current_action')), json.dumps(npc_data.get('action_queue', [])),
                    str(npc_data.get('party_id')), json.dumps(npc_data.get('state_variables', {})),
                    float(npc_data.get('health',0.0)), float(npc_data.get('max_health',0.0)),
                    bool(npc_data.get('is_alive',False)), json.dumps(npc_data.get('status_effects', [])),
                    bool(npc_data.get('is_temporary',False)), npc_data.get('archetype', "commoner"),
                    json.dumps(npc_data.get('traits', [])), json.dumps(npc_data.get('desires', [])),
                    json.dumps(npc_data.get('motives', [])), eff_stats_json
                )
                upsert_sql = """
                INSERT INTO npcs (
                    id, template_id, name_i18n, description_i18n, backstory_i18n, persona_i18n,
                    guild_id, location_id, stats, inventory, current_action, action_queue, party_id,
                    state_variables, health, max_health, is_alive, status_effects, is_temporary, archetype,
                    traits, desires, motives, effective_stats_json
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24)
                ON CONFLICT (id) DO UPDATE SET
                    template_id=EXCLUDED.template_id, name_i18n=EXCLUDED.name_i18n, description_i18n=EXCLUDED.description_i18n,
                    backstory_i18n=EXCLUDED.backstory_i18n, persona_i18n=EXCLUDED.persona_i18n, guild_id=EXCLUDED.guild_id,
                    location_id=EXCLUDED.location_id, stats=EXCLUDED.stats, inventory=EXCLUDED.inventory,
                    current_action=EXCLUDED.current_action, action_queue=EXCLUDED.action_queue, party_id=EXCLUDED.party_id,
                    state_variables=EXCLUDED.state_variables, health=EXCLUDED.health, max_health=EXCLUDED.max_health,
                    is_alive=EXCLUDED.is_alive, status_effects=EXCLUDED.status_effects, is_temporary=EXCLUDED.is_temporary,
                    archetype=EXCLUDED.archetype, traits=EXCLUDED.traits, desires=EXCLUDED.desires, motives=EXCLUDED.motives,
                    effective_stats_json=EXCLUDED.effective_stats_json;"""
            await self._db_service.adapter.execute(upsert_sql, db_params)
            if guild_id_str in self._dirty_npcs and npc_id in self._dirty_npcs[guild_id_str]:
                self._dirty_npcs[guild_id_str].discard(npc_id)
                if not self._dirty_npcs[guild_id_str]: del self._dirty_npcs[guild_id_str]
            self._npcs.setdefault(guild_id_str, {})[npc_id] = npc
            return True
        except Exception as e: print(f"Error saving NPC {npc_id}: {e}"); traceback.print_exc(); return False

    async def create_npc_from_moderated_data(self, guild_id: str, npc_data: Dict[str, Any], context: Dict[str, Any]) -> Optional[str]:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None: return None # Changed from self._db_adapter
        npc_id = npc_data.get('id', str(uuid.uuid4()))
        data_for_npc_object: Dict[str, Any] = {
            'id': npc_id, 'guild_id': guild_id_str,
            'template_id': npc_data.get('template_id', npc_data.get('archetype')),
            'name': npc_data.get('name', f"NPC_{npc_id[:8]}"),
            'location_id': npc_data.get('location_id'),
            'stats': npc_data.get('stats', {"max_health": 50.0}),
            'inventory': npc_data.get('inventory', []), 'current_action': None, 'action_queue': [], 'party_id': None,
            'state_variables': npc_data.get('state_variables', {}),
            'health': float(npc_data.get('stats', {}).get('max_health', 50.0)),
            'max_health': float(npc_data.get('stats', {}).get('max_health', 50.0)),
            'is_alive': True, 'status_effects': [], 'is_temporary': npc_data.get('is_temporary', True), # Moderated NPCs might be temporary until fully placed
            'archetype': npc_data.get('archetype', "commoner"),
            'traits': npc_data.get('traits', []), 'desires': npc_data.get('desires', []), 'motives': npc_data.get('motives', []),
            'backstory': npc_data.get('backstory', ""),
            'effective_stats_json': json.dumps(npc_data.get('stats', {})) # Initial effective stats from moderated data (base)
        }
        for i18n_key in ['name_i18n', 'description_i18n', 'visual_description_i18n', 'personality_i18n',
                         'role_i18n', 'motivation_i18n', 'dialogue_hints_i18n', 'roleplaying_notes_i18n',
                         'knowledge_i18n', 'npc_goals_i18n', 'relationships_i18n', 'speech_patterns_i18n', 'backstory_i18n']:
            if i18n_key in npc_data: data_for_npc_object[i18n_key] = npc_data[i18n_key]
        try:
            npc = NPC.from_dict(data_for_npc_object)
            setattr(npc, 'is_ai_generated', True) # Mark as AI-originated
            setattr(npc, 'effective_stats_json', data_for_npc_object.get('effective_stats_json', '{}'))
            self._npcs.setdefault(guild_id_str, {})[npc.id] = npc
            await self._recalculate_and_store_effective_stats(guild_id_str, npc.id, npc) # Recalculate properly
            self.mark_npc_dirty(guild_id_str, npc.id) # This will ensure it's saved via save_npc to generated_npcs
            return npc.id
        except Exception as e: print(f"Error creating NPC from moderated data: {e}"); traceback.print_exc(); return None

    async def save_state(self, guild_id: str, **kwargs: Any) -> None: pass # Placeholder, relies on save_npc
    async def load_state(self, guild_id: str, **kwargs: Any) -> None: # Placeholder, needs full logic
        # ... (Ensure SQL for 'npcs' and 'generated_npcs' includes 'effective_stats_json') ...
        # ... (Ensure data['effective_stats_json'] = row.get('effective_stats_json', '{}') is loaded) ...
        # ... (Ensure setattr(npc, 'effective_stats_json', data.get('effective_stats_json','{}')) is done after NPC.from_dict) ...
        pass
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None: pass
    def mark_npc_dirty(self, guild_id: str, npc_id: str) -> None:
         if str(guild_id) in self._npcs and npc_id in self._npcs[str(guild_id)]:
              self._dirty_npcs.setdefault(str(guild_id), set()).add(npc_id)
    def set_active_action(self, guild_id: str, npc_id: str, action_details: Optional[Dict[str, Any]]) -> None: pass
    def add_action_to_queue(self, guild_id: str, npc_id: str, action_details: Dict[str, Any]) -> None: pass
    def get_next_action_from_queue(self, guild_id: str, npc_id: str) -> Optional[Dict[str, Any]]: return None
    async def revert_npc_spawn(self, guild_id: str, npc_id: str, **kwargs: Any) -> bool: return True
    async def recreate_npc_from_data(self, guild_id: str, npc_data: Dict[str, Any], **kwargs: Any) -> bool: return True
    async def revert_npc_location_change(self, guild_id: str, npc_id: str, old_location_id: Optional[str], **kwargs: Any) -> bool: return True
    async def revert_npc_hp_change(self, guild_id: str, npc_id: str, old_hp: float, old_is_alive: bool, **kwargs: Any) -> bool: return True
    async def revert_npc_stat_changes(self, guild_id: str, npc_id: str, stat_changes: List[Dict[str, Any]], **kwargs: Any) -> bool: return True
    async def revert_npc_inventory_changes(self, guild_id: str, npc_id: str, inventory_changes: List[Dict[str, Any]], **kwargs: Any) -> bool: return True
    async def revert_npc_party_change(self, guild_id: str, npc_id: str, old_party_id: Optional[str], **kwargs: Any) -> bool: return True
    async def revert_npc_state_variables_change(self, guild_id: str, npc_id: str, old_state_variables_json: str, **kwargs: Any) -> bool: return True

print("DEBUG: npc_manager.py module loaded.")
