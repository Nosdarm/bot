# bot/game/managers/spell_manager.py
from __future__ import annotations
import time # For cooldowns
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from ..models.spell import Spell # Import the Spell model

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.status_manager import StatusManager
    # from bot.game.managers.combat_manager import CombatManager # If needed for targeting/damage
    # from bot.game.managers.location_manager import LocationManager # If needed for targeting
    # from bot.game.managers.npc_manager import NpcManager # If needed for summon effects
    from ..models.character import Character # For type hinting

class SpellManager:
    def __init__(self, 
                 db_adapter: Optional[SqliteAdapter] = None, 
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional[CharacterManager] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 status_manager: Optional[StatusManager] = None,
                 # combat_manager: Optional[CombatManager] = None, # Add if direct interaction needed
                 # location_manager: Optional[LocationManager] = None, # Add if direct interaction needed
                 # npc_manager: Optional[NpcManager] = None, # Add if direct interaction needed
                 **kwargs: Any):
        self._db_adapter = db_adapter
        self._settings = settings if settings is not None else {}
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        # self._combat_manager = combat_manager
        # self._location_manager = location_manager
        # self._npc_manager = npc_manager
        
        self._spell_templates: Dict[str, Dict[str, Spell]] = {}  # guild_id -> spell_id -> Spell object
        print("SpellManager initialized.")

    async def load_spell_templates(self, guild_id: str, campaign_data: Dict[str, Any]) -> None:
        """Loads spell templates from campaign data."""
        guild_id_str = str(guild_id)
        self._spell_templates.setdefault(guild_id_str, {})
        
        spell_templates_data = campaign_data.get("spell_templates", [])
        if not spell_templates_data:
            print(f"SpellManager: No spell templates found in campaign_data for guild {guild_id_str}.")
            return

        loaded_count = 0
        for spell_data in spell_templates_data:
            try:
                spell = Spell.from_dict(spell_data)
                self._spell_templates[guild_id_str][spell.id] = spell
                loaded_count += 1
            except Exception as e:
                print(f"SpellManager: Error loading spell template '{spell_data.get('id', 'UnknownID')}' for guild {guild_id_str}: {e}")
        
        print(f"SpellManager: Successfully loaded {loaded_count} spell templates for guild {guild_id_str}.")
        if loaded_count > 0:
            print(f"SpellManager: Example spell templates for guild {guild_id_str}:")
            count = 0
            for spell_id, spell_obj in self._spell_templates[guild_id_str].items():
                if count < 3:
                    print(f"  - ID: {spell_obj.id}, Name: {spell_obj.name}, Mana Cost: {spell_obj.mana_cost}")
                    count += 1
                else:
                    break
            if loaded_count > 3:
                print(f"  ... and {loaded_count - 3} more.")


    async def get_spell(self, guild_id: str, spell_id: str) -> Optional[Spell]:
        """Retrieves a specific spell object from the cache."""
        guild_id_str = str(guild_id)
        spell_id_str = str(spell_id)
        return self._spell_templates.get(guild_id_str, {}).get(spell_id_str)

    async def learn_spell(self, guild_id: str, character_id: str, spell_id: str, **kwargs: Any) -> bool:
        """Allows a character to learn a spell."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        spell_id_str = str(spell_id)

        if not self._character_manager or not self._rule_engine:
            print("SpellManager: CharacterManager or RuleEngine not available for learn_spell.")
            return False

        spell = await self.get_spell(guild_id_str, spell_id_str)
        if not spell:
            print(f"SpellManager: Spell '{spell_id_str}' not found for guild {guild_id_str}.")
            return False

        character = await self._character_manager.get_character(guild_id_str, character_id_str)
        if not character:
            print(f"SpellManager: Character '{character_id_str}' not found for guild {guild_id_str}.")
            return False

        # Assume RuleEngine.check_spell_learning_requirements exists and takes character & spell
        can_learn, reasons = await self._rule_engine.check_spell_learning_requirements(character, spell)
        if not can_learn:
            print(f"SpellManager: Character '{character_id_str}' cannot learn spell '{spell_id_str}'. Reasons: {reasons}")
            return False

        # Add spell to character's known spells (assuming Character model has 'known_spells' list)
        if not hasattr(character, 'known_spells') or character.known_spells is None:
            # This indicates a potential issue with Character model definition or initialization
            print(f"SpellManager: Character model for '{character_id_str}' missing 'known_spells' attribute. Initializing.")
            character.known_spells = [] # type: ignore 
            
        if spell_id_str not in character.known_spells: # type: ignore
            character.known_spells.append(spell_id_str) # type: ignore
            await self._character_manager.mark_character_dirty(guild_id_str, character_id_str)
            print(f"SpellManager: Character '{character_id_str}' learned spell '{spell_id_str}'.")
            return True
        else:
            print(f"SpellManager: Character '{character_id_str}' already knows spell '{spell_id_str}'.")
            return True # Or False, depending on desired behavior for re-learning

    async def cast_spell(self, guild_id: str, caster_id: str, spell_id: str, target_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        """
        Casts a spell for a character, potentially targeting another entity.
        Returns a dictionary with the outcome of the spell casting.
        """
        guild_id_str = str(guild_id)
        caster_id_str = str(caster_id)
        spell_id_str = str(spell_id)

        if not self._character_manager or not self._rule_engine or not self._status_manager:
            print("SpellManager: CharacterManager, RuleEngine, or StatusManager not available for cast_spell.")
            return {"success": False, "message": "Internal server error: Manager not available."}

        spell = await self.get_spell(guild_id_str, spell_id_str)
        if not spell:
            return {"success": False, "message": f"Spell '{spell_id_str}' not found."}

        caster = await self._character_manager.get_character(guild_id_str, caster_id_str)
        if not caster:
            return {"success": False, "message": f"Caster '{caster_id_str}' not found."}
            
        # 1. Check if caster knows the spell (optional, depending on game rules)
        if hasattr(caster, 'known_spells') and spell_id_str not in caster.known_spells: # type: ignore
             return {"success": False, "message": f"Caster does not know the spell '{spell.name}'."}


        # 2. Check mana/resource cost
        # Assuming Character model has stats.mana or similar
        if not hasattr(caster, 'stats') or 'mana' not in caster.stats: # type: ignore
            return {"success": False, "message": "Caster has no mana attribute."}
        
        current_mana = caster.stats['mana'] # type: ignore
        if current_mana < spell.mana_cost:
            return {"success": False, "message": f"Not enough mana to cast {spell.name}. Needs {spell.mana_cost}, has {current_mana}."}
        
        caster.stats['mana'] -= spell.mana_cost # type: ignore
        await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
        print(f"SpellManager: Deducted {spell.mana_cost} mana from {caster_id_str} for {spell.name}. Remaining: {caster.stats['mana']}.") # type: ignore

        # 3. Handle cooldowns
        # Assuming Character model has spell_cooldowns: Dict[str, float] (timestamp of when cooldown ends)
        if not hasattr(caster, 'spell_cooldowns') or caster.spell_cooldowns is None: # type: ignore
            print(f"SpellManager: Character model for '{caster_id_str}' missing 'spell_cooldowns' attribute. Initializing.")
            caster.spell_cooldowns = {} # type: ignore
            
        current_time = time.time()
        if spell_id_str in caster.spell_cooldowns and caster.spell_cooldowns[spell_id_str] > current_time: # type: ignore
            remaining_cooldown = caster.spell_cooldowns[spell_id_str] - current_time # type: ignore
            return {"success": False, "message": f"{spell.name} is on cooldown for {remaining_cooldown:.1f} more seconds."}
        
        if spell.cooldown > 0:
            caster.spell_cooldowns[spell_id_str] = current_time + spell.cooldown # type: ignore
            await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
            print(f"SpellManager: Spell '{spell.name}' cooldown set for {caster_id_str} for {spell.cooldown}s.")

        # 4. Delegate effect processing to RuleEngine
        # RuleEngine will need access to CharacterManager, StatusManager, NpcManager, LocationManager etc.
        # It might be cleaner if RuleEngine gets these managers during its own init.
        try:
            outcomes = await self._rule_engine.process_spell_effects(
                caster=caster, 
                spell=spell, 
                target_id=target_id, 
                guild_id=guild_id_str,
                # Pass other managers if RuleEngine needs them and doesn't have them stored
                # character_manager=self._character_manager, 
                # status_manager=self._status_manager,
                # combat_manager=self._combat_manager, 
                # location_manager=self._location_manager,
                # npc_manager=self._npc_manager,
                **kwargs
            )
            print(f"SpellManager: Spell '{spell.name}' cast by '{caster_id_str}'. Outcomes: {outcomes}")
            return {"success": True, "message": f"{spell.name} cast successfully!", "outcomes": outcomes}
        except Exception as e:
            print(f"SpellManager: Error during spell effect processing for '{spell.name}': {e}")
            # Potentially refund mana if casting itself failed mid-way due to rule engine error
            # caster.stats['mana'] += spell.mana_cost
            # await self._character_manager.mark_character_dirty(guild_id_str, caster_id_str)
            return {"success": False, "message": f"Error processing spell effects for {spell.name}."}


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Loads spell-related states for a guild, primarily spell templates."""
        guild_id_str = str(guild_id)
        print(f"SpellManager: load_state for guild {guild_id_str}.")
        
        campaign_data = kwargs.get('campaign_data')
        if campaign_data:
            await self.load_spell_templates(guild_id_str, campaign_data)
        else:
            print(f"SpellManager: No campaign_data provided to load_state for guild {guild_id_str}, cannot load spell templates.")

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Saves spell-related states for a guild."""
        # Spell templates are static and loaded from campaign data, so no specific saving needed here.
        # Character-specific spell data (known_spells, cooldowns) should be saved by CharacterManager.
        print(f"SpellManager: save_state for guild {str(guild_id)} (No specific state to save for SpellManager itself).")

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Rebuilds any runtime caches if necessary."""
        # Currently, spell templates are the main cache, loaded by load_state.
        # If there were other runtime calculations or aggregations, they could be rebuilt here.
        print(f"SpellManager: Rebuilding runtime caches for guild {str(guild_id)}.")
        await self.load_state(guild_id, **kwargs) # Re-loading templates can be a form of cache rebuilding.


