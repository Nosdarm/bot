# bot/ai/prompt_context_collector.py

from typing import TYPE_CHECKING, Dict, Any, List, Optional

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.ability_manager import AbilityManager
    from bot.game.managers.spell_manager import SpellManager
    from bot.game.managers.event_manager import EventManager
    # Forward reference for GameManager if needed, or pass settings directly
    # from bot.game.managers.game_manager import GameManager


class PromptContextCollector:
    def __init__(
        self,
        settings: Dict[str, Any],
        character_manager: 'CharacterManager',
        npc_manager: 'NpcManager',
        quest_manager: 'QuestManager',
        relationship_manager: 'RelationshipManager',
        item_manager: 'ItemManager',
        location_manager: 'LocationManager',
        ability_manager: 'AbilityManager',
        spell_manager: 'SpellManager',
        event_manager: 'EventManager'
        # Potentially lore_data if loaded separately, or handled via location_manager/settings
    ):
        self.settings = settings
        self.character_manager = character_manager
        self.npc_manager = npc_manager
        self.quest_manager = quest_manager
        self.relationship_manager = relationship_manager
        self.item_manager = item_manager
        self.location_manager = location_manager
        self.ability_manager = ability_manager
        self.spell_manager = spell_manager
        self.event_manager = event_manager

        # Example: Load lore data directly if not managed by another service
        # For now, assume lore can be accessed via settings or location_manager
        # self.lore_data = self._load_lore_data("game_data/lore_i18n.json")

    # def _load_lore_data(self, lore_file_path: str) -> Dict[str, Any]:
    #     try:
    #         with open(lore_file_path, 'r', encoding='utf-8') as f:
    #             return json.load(f)
    #     except FileNotFoundError:
    #         print(f"Warning: Lore file not found at {lore_file_path}")
    #         return {}
    #     except json.JSONDecodeError:
    #         print(f"Warning: Could not decode lore file at {lore_file_path}")
    #         return {}

    def get_main_language_code(self) -> str:
        """Determines the main language code for the bot."""
        return self.settings.get('main_language_code', 'ru') # Default to 'ru' as per plan

    def get_lore_context(self) -> List[Dict[str, Any]]:
        """Gathers lore context."""
        # This will need to read from game_data/lore_i18n.json
        # For now, returning a placeholder. Implementation later.
        # Consider if this should be loaded once in __init__ or fetched dynamically.
        # If lore_data is loaded in init: return self.lore_data.get("lore_entries", [])
        print("Placeholder: Fetching lore context")
        return [{"id": "world_creation_placeholder", "title_i18n": {"en": "Placeholder Creation", "ru": "Создание Заглушки"}, "text_i18n": {"en": "Placeholder lore...", "ru": "Лоровая заглушка..."}}]

    def get_world_state_context(self) -> Dict[str, Any]:
        """Gathers current world state context."""
        # Placeholder: Collate from EventManager, LocationManager (dynamic states), NpcManager (significant NPCs)
        print("Placeholder: Fetching world state context")
        active_events = [] # self.event_manager.get_active_global_events() # Assuming such a method
        key_location_states = [] # self.location_manager.get_key_location_statuses() # Assuming
        significant_npc_states = [] # self.npc_manager.get_significant_npc_updates() # Assuming
        return {
            "active_global_events": active_events,
            "key_location_statuses": key_location_states,
            "significant_npc_states": significant_npc_states,
            "current_time": {"game_time_string": "Placeholder Time"} # From TimeManager
        }

    def get_relationship_context(self, entity_id: str, entity_type: str) -> List[Dict[str, Any]]:
        """Gathers relationship context for a given entity."""
        # Placeholder: Use RelationshipManager
        print(f"Placeholder: Fetching relationship context for {entity_type} {entity_id}")
        # relationships = self.relationship_manager.get_relationships_for_entity(guild_id, entity_id) # Needs guild_id
        # return [rel.to_dict() for rel in relationships]
        return [{"entity1_id": entity_id, "entity2_id": "npc_placeholder_friend", "relationship_type": "friend", "strength": 75}]

    def get_quest_context(self, character_id: str) -> Dict[str, Any]:
        """Gathers quest context for a character."""
        # Placeholder: Use QuestManager
        print(f"Placeholder: Fetching quest context for character {character_id}")
        # active_quests = self.quest_manager.list_quests_for_character(guild_id, character_id) # Needs guild_id
        # completed_quests_summary = [] # Potentially summarize recent/important ones
        return {
            "active_quests": [{"name_i18n": {"en": "Active Placeholder Quest", "ru": "Активный Квест-Заглушка"}, "status": "active"}],
            "completed_quests_summary": [{"name_i18n": {"en": "Completed Placeholder Quest", "ru": "Завершенный Квест-Заглушка"}, "outcome": "success"}]
        }

    def get_game_rules_context(self) -> Dict[str, Any]:
        """Extracts relevant game rules (stats, skills, abilities, items) from settings."""
        print("Placeholder: Fetching game rules context")
        game_rules = self.settings.get("game_rules", {})

        stats_info = game_rules.get("character_stats_rules", {}).get("attributes", {})
        skills_info = game_rules.get("skill_rules", {}).get("skill_stat_map", {})

        # Names of abilities/spells would come from AbilityManager/SpellManager
        # For now, this method focuses on rules in settings.
        # ability_definitions = self.ability_manager.get_all_ability_definitions(guild_id) # Needs guild_id
        # spell_definitions = self.spell_manager.get_all_spell_definitions(guild_id) # Needs guild_id

        item_templates = self.settings.get("item_templates", {})

        return {
            "attributes": {attr: data.get("description", "") for attr, data in stats_info.items()},
            "skills": {skill: {"associated_stat": stat} for skill, stat in skills_info.items()},
            # "abilities": {ab_id: ab_data.get("name_i18n") for ab_id, ab_data in ability_definitions.items()}, # Example
            # "spells": {sp_id: sp_data.get("name_i18n") for sp_id, sp_data in spell_definitions.items()}, # Example
            "item_types_summary": {tmpl_id: data.get("type") for tmpl_id, data in item_templates.items()}
        }

    def get_player_level_context(self, character_id: str) -> Dict[str, Any]:
        """Gathers player/party level context."""
        # Placeholder: Use CharacterManager or PartyManager
        print(f"Placeholder: Fetching player level context for character {character_id}")
        # character = self.character_manager.get_character(guild_id, character_id) # Needs guild_id
        # if character:
        #     level = character.level
        #     party_id = character.party_id
        #     if party_id:
        #         party_avg_level = self.party_manager.get_average_party_level(guild_id, party_id) # Assuming
        #         return {"character_level": level, "party_average_level": party_avg_level}
        #     return {"character_level": level}
        return {"character_level": 5, "party_average_level": 5} # Placeholder values

    def get_full_context(self, target_entity_id: Optional[str] = None, target_entity_type: Optional[str] = None, guild_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Assembles all context components.
        guild_id is needed for manager calls that are guild-specific.
        target_entity_id and target_entity_type are for context specific to an entity (e.g., player character, NPC).
        """
        # Note: Many manager methods will require guild_id. This method should receive it.
        # For now, placeholders don't use guild_id, but real implementation will.

        print(f"Assembling full context (guild: {guild_id}, target: {target_entity_type} {target_entity_id})")

        context = {
            "main_language": self.get_main_language_code(),
            "game_rules": self.get_game_rules_context(),
            "lore": self.get_lore_context(),
            "world_state": self.get_world_state_context(),
        }
        if target_entity_id and target_entity_type == "character":
            context["player_character_level"] = self.get_player_level_context(character_id=target_entity_id)
            context["player_character_quests"] = self.get_quest_context(character_id=target_entity_id)
            context["player_character_relationships"] = self.get_relationship_context(entity_id=target_entity_id, entity_type="character")
        elif target_entity_id and target_entity_type == "npc":
            # context["npc_details"] = self.npc_manager.get_npc_details_for_prompt(guild_id, target_entity_id) # Assuming
            context["npc_relationships"] = self.get_relationship_context(entity_id=target_entity_id, entity_type="npc")

        # TODO: Add more context components as needed (e.g., specific location details, faction summaries)
        return context
