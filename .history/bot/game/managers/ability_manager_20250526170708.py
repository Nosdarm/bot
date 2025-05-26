# bot/game/managers/ability_manager.py
from __future__ import annotations
import time # For cooldowns
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from ..models.ability import Ability # Import the Ability model

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.rule_engine import RuleEngine
    from bot.game.managers.status_manager import StatusManager
    # from bot.game.models.character import Character # For type hinting Character object

class AbilityManager:
    """
    Manages character abilities, including loading templates, learning, activation,
    and interaction with the RuleEngine for effects.
    """
    required_args_for_load = ["guild_id", "campaign_data"]
    required_args_for_save = ["guild_id"] 
    required_args_for_rebuild = ["guild_id", "campaign_data"]

    def __init__(self,
                 db_adapter: Optional[SqliteAdapter] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional[CharacterManager] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 status_manager: Optional[StatusManager] = None,
                 **kwargs: Any):
        self._db_adapter = db_adapter
        self._settings = settings if settings is not None else {}
        self._character_manager = character_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        
        self._ability_templates: Dict[str, Dict[str, Ability]] = {}  # guild_id -> ability_id -> Ability object
        print("AbilityManager initialized.")

    async def load_ability_templates(self, guild_id: str, campaign_data: Dict[str, Any]) -> None:
        """Loads ability templates from campaign data for a specific guild."""
        guild_id_str = str(guild_id)
        self._ability_templates.setdefault(guild_id_str, {})
        
        ability_templates_data = campaign_data.get("ability_templates", [])
        if not ability_templates_data:
            print(f"AbilityManager: No ability templates found in campaign_data for guild {guild_id_str}.")
            return

        loaded_count = 0
        for ability_data in ability_templates_data:
            try:
                ability = Ability.from_dict(ability_data)
                self._ability_templates[guild_id_str][ability.id] = ability
                loaded_count += 1
            except Exception as e:
                print(f"AbilityManager: Error loading ability template '{ability_data.get('id', 'UnknownID')}' for guild {guild_id_str}: {e}")
        
        print(f"AbilityManager: Successfully loaded {loaded_count} ability templates for guild {guild_id_str}.")
        if loaded_count > 0:
            print(f"AbilityManager: Example ability templates for guild {guild_id_str}:")
            count = 0
            for ability_id, ability_obj in self._ability_templates[guild_id_str].items():
                if count < 3:
                    print(f"  - ID: {ability_obj.id}, Name: {ability_obj.name}, Type: {ability_obj.type}")
                    count += 1
                else:
                    break
            if loaded_count > 3:
                print(f"  ... and {loaded_count - 3} more.")

    async def get_ability(self, guild_id: str, ability_id: str) -> Optional[Ability]:
        """Retrieves a specific ability object from the cache for a guild."""
        guild_id_str = str(guild_id)
        ability_id_str = str(ability_id)
        return self._ability_templates.get(guild_id_str, {}).get(ability_id_str)

    async def learn_ability(self, guild_id: str, character_id: str, ability_id: str, source: str = "learned", **kwargs: Any) -> bool:
        """Allows a character to learn an ability."""
        guild_id_str = str(guild_id)
        
        if not self._character_manager or not self._rule_engine:
            print("AbilityManager: CharacterManager or RuleEngine not available for learn_ability.")
            return False

        ability = await self.get_ability(guild_id_str, ability_id)
        if not ability:
            print(f"AbilityManager: Ability '{ability_id}' not found for guild {guild_id_str}.")
            return False

        character = await self._character_manager.get_character(guild_id_str, character_id)
        if not character:
            print(f"AbilityManager: Character '{character_id}' not found for guild {guild_id_str}.")
            return False

        # Assume RuleEngine.check_ability_learning_requirements will be created
        # It should take character, ability, and potentially other context from kwargs
        can_learn, reasons = await self._rule_engine.check_ability_learning_requirements(character, ability, **kwargs)
        if not can_learn:
            print(f"AbilityManager: Character '{character_id}' cannot learn ability '{ability_id}'. Reasons: {reasons}")
            return False

        # Add ability to character's known_abilities (assuming Character model has this field)
        if not hasattr(character, 'known_abilities') or character.known_abilities is None:
            print(f"AbilityManager: Character model for '{character_id}' missing 'known_abilities' attribute. Initializing.")
            character.known_abilities = [] # type: ignore
            
        if ability_id not in character.known_abilities: # type: ignore
            character.known_abilities.append(ability_id) # type: ignore
            
            # Handle passive stat modifications if applicable and not managed by status effects
            # This is a complex area. Simpler passives are often best handled by RuleEngine
            # checking if the character *has* the ability flag.
            # More direct stat mods might be applied here or by a dedicated system.
            if ability.type == "passive_stat_modifier":
                # Example: self._rule_engine.apply_passive_ability_stat_mods(character, ability)
                # For now, this is conceptual. The RuleEngine would iterate ability.effects.
                print(f"AbilityManager: Passive ability '{ability.name}' learned. Stat mods would be applied by RuleEngine or Character model updates.")

            await self._character_manager.mark_character_dirty(guild_id_str, character_id)
            print(f"AbilityManager: Character '{character_id}' learned ability '{ability_id}' (Source: {source}).")
            return True
        else:
            print(f"AbilityManager: Character '{character_id}' already knows ability '{ability_id}'.")
            return True # Or False, depending on desired behavior

    async def activate_ability(self, guild_id: str, character_id: str, ability_id: str, target_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        """Activates an ability for a character."""
        guild_id_str = str(guild_id)

        if not self._character_manager or not self._rule_engine:
            print("AbilityManager: CharacterManager or RuleEngine not available for activate_ability.")
            return {"success": False, "message": "Internal server error: Manager not available."}

        ability = await self.get_ability(guild_id_str, ability_id)
        if not ability:
            return {"success": False, "message": f"Ability '{ability_id}' not found."}

        if not ability.type.startswith("activated_"):
            return {"success": False, "message": f"Ability '{ability.name}' is not an activatable ability."}

        caster = await self._character_manager.get_character(guild_id_str, character_id)
        if not caster:
            return {"success": False, "message": f"Caster '{character_id}' not found."}
            
        if not hasattr(caster, 'known_abilities') or ability_id not in caster.known_abilities: # type: ignore
             return {"success": False, "message": f"Caster does not know the ability '{ability.name}'."}

        # Resource Costs (e.g., stamina, action_points)
        if ability.resource_cost:
            for resource, cost in ability.resource_cost.items():
                if resource == "stamina": # Example resource
                    if not hasattr(caster, 'stats') or resource not in caster.stats: # type: ignore
                        return {"success": False, "message": f"Caster has no '{resource}' attribute."}
                    current_resource_val = caster.stats[resource] # type: ignore
                    if current_resource_val < cost:
                        return {"success": False, "message": f"Not enough {resource} to use {ability.name}. Needs {cost}, has {current_resource_val}."}
                    caster.stats[resource] -= cost # type: ignore
                    print(f"AbilityManager: Deducted {cost} {resource} from {character_id} for {ability.name}.")
                # TODO: Handle other resource types like "uses_per_day", "action_points"
                else:
                    print(f"AbilityManager: Warning: Unknown resource cost type '{resource}' for ability '{ability.name}'.")
            await self._character_manager.mark_character_dirty(guild_id_str, character_id)


        # Cooldowns
        if ability.cooldown and ability.cooldown > 0:
            if not hasattr(caster, 'ability_cooldowns') or caster.ability_cooldowns is None: # type: ignore
                print(f"AbilityManager: Character model for '{character_id}' missing 'ability_cooldowns' attribute. Initializing.")
                caster.ability_cooldowns = {} # type: ignore
            
            current_time = time.time()
            if ability_id in caster.ability_cooldowns and caster.ability_cooldowns[ability_id] > current_time: # type: ignore
                remaining_cooldown = caster.ability_cooldowns[ability_id] - current_time # type: ignore
                return {"success": False, "message": f"{ability.name} is on cooldown for {remaining_cooldown:.1f} more seconds."}
            
            caster.ability_cooldowns[ability_id] = current_time + ability.cooldown # type: ignore
            await self._character_manager.mark_character_dirty(guild_id_str, character_id)
            print(f"AbilityManager: Ability '{ability.name}' cooldown set for {character_id} for {ability.cooldown}s.")

        # Delegate effect processing to RuleEngine (new method to be created in RuleEngine)
        # RuleEngine.process_ability_effects(caster, ability, target_entity, guild_id, **kwargs)
        try:
            # Target resolution might need to happen here or in RuleEngine
            # For now, pass target_id, RuleEngine can fetch the entity
            target_entity = None
            if target_id:
                # Attempt to get target as Character or NPC
                target_entity = await self._character_manager.get_character(guild_id_str, target_id)
                if not target_entity and self._character_manager._npc_manager_ref: # Assuming a way to access NpcManager
                     target_entity = await self._character_manager._npc_manager_ref.get_npc(guild_id_str, target_id)

            outcomes = await self._rule_engine.process_ability_effects(
                caster=caster, 
                ability=ability, 
                target_entity=target_entity, # Pass the fetched entity or None
                guild_id=guild_id_str,
                **kwargs 
            )
            print(f"AbilityManager: Ability '{ability.name}' activated by '{character_id}'. Outcomes: {outcomes}")
            return {"success": True, "message": f"{ability.name} activated successfully!", "outcomes": outcomes}
        except Exception as e:
            print(f"AbilityManager: Error during ability effect processing for '{ability.name}': {e}")
            # Consider if resources/cooldowns should be reverted on error
            return {"success": False, "message": f"Error processing effects for {ability.name}."}

    async def process_passive_abilities(self, guild_id: str, character_id: str, event_type: str, event_data: Dict[str, Any], **kwargs: Any) -> None:
        """
        Conceptual: Processes passive abilities for a character based on a game event.
        This would likely be called by RuleEngine or an event bus system.
        """
        # This is a placeholder for a more complex system.
        # 1. Get character.
        # 2. Iterate character.known_abilities.
        # 3. For each ability, check if it's passive and if its trigger conditions match event_type.
        # 4. If matched, call RuleEngine to apply its effects.
        print(f"AbilityManager (Conceptual): process_passive_abilities called for char {character_id}, event {event_type}.")
        # Example:
        # character = await self._character_manager.get_character(guild_id, character_id)
        # if character and hasattr(character, 'known_abilities'):
        #     for ability_id in character.known_abilities:
        #         ability = await self.get_ability(guild_id, ability_id)
        #         if ability and ability.type.startswith("passive_") and ability.trigger_conditions_met(event_type, event_data):
        #             await self._rule_engine.apply_passive_ability_effect(character, ability, event_data, **kwargs)
        pass

    async def load_state(self, guild_id: str, campaign_data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        """Loads ability-related states for a guild, primarily ability templates."""
        guild_id_str = str(guild_id)
        print(f"AbilityManager: load_state for guild {guild_id_str}.")
        
        if campaign_data:
            await self.load_ability_templates(guild_id_str, campaign_data)
        else:
            # This case should ideally be handled by PersistenceManager ensuring campaign_data is passed
            # if this manager is part of the campaign-dependent load sequence.
            print(f"AbilityManager: No campaign_data provided to load_state for guild {guild_id_str}, cannot load ability templates.")

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Saves ability-related states for a guild."""
        # Ability templates are static and loaded from campaign data.
        # Character-specific ability data (known_abilities, cooldowns) should be saved by CharacterManager.
        print(f"AbilityManager: save_state for guild {str(guild_id)} (No specific state to save for AbilityManager itself).")

    async def rebuild_runtime_caches(self, guild_id: str, campaign_data: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        """Rebuilds any runtime caches if necessary, e.g., reloading templates."""
        guild_id_str = str(guild_id)
        print(f"AbilityManager: Rebuilding runtime caches for guild {str(guild_id)}.")
        # Re-loading templates can be a form of cache rebuilding.
        # Ensure campaign_data is available if called during a full game state rebuild.
        if campaign_data:
            await self.load_ability_templates(guild_id_str, campaign_data)
        else:
            print(f"AbilityManager: campaign_data not provided for rebuild_runtime_caches in guild {guild_id_str}. Template cache might be stale if not loaded via load_state.")

# Placeholder for CharacterManager._npc_manager_ref if needed by activate_ability
# This is a bit of a hack; ideally, NpcManager would be a direct dependency if always needed.
# Or, the target resolution logic should be more sophisticated, possibly within RuleEngine.
# For now, we'll assume CharacterManager might have a way to get to NpcManager, or activate_ability
# will have NpcManager passed via kwargs if complex target resolution is needed often.
# setattr(CharacterManager, '_npc_manager_ref', None) # This would be set by GameManager during init.
# This is not the place to do this. GameManager would inject it.
# We will assume RuleEngine.process_ability_effects handles target resolution if target_entity is just an ID.

