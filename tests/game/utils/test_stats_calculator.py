import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock

from bot.game.utils.stats_calculator import calculate_effective_stats
from bot.ai.rules_schema import CoreGameRulesConfig, BaseStatDefinition, StatModifierRule, StatusEffectDefinition, GrantedAbilityOrSkill # MODIFIED: ItemDefinition removed
from bot.game.models.character import Character
from bot.game.models.npc import NPC as NpcModel
from bot.database.models import ItemTemplate # Corrected import path
from bot.game.models.status_effect import StatusEffect as StatusEffectInstance
# StatusEffectTemplate removed

class TestStatsCalculator(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()

        self.rules_config = CoreGameRulesConfig(
            base_stats={
                "STRENGTH": BaseStatDefinition(name_i18n={"en": "Strength"}, description_i18n={"en": "Measures physical power"}, default_value=10, min_value=1, max_value=30),
                "DEXTERITY": BaseStatDefinition(name_i18n={"en": "Dexterity"}, description_i18n={"en": "Measures agility"}, default_value=10, min_value=1, max_value=30),
                "CONSTITUTION": BaseStatDefinition(name_i18n={"en": "Constitution"}, description_i18n={"en": "Measures endurance"}, default_value=10, min_value=1, max_value=30),
                "MAX_HP": BaseStatDefinition(name_i18n={"en": "Max HP"}, description_i18n={"en": "Maximum health points"}, default_value=50, min_value=1, max_value=1000),
                "ATTACK_BONUS": BaseStatDefinition(name_i18n={"en": "Attack Bonus"}, description_i18n={"en": "Bonus to attack rolls"}, default_value=0, min_value=-5, max_value=20),
                "FIRE_RESISTANCE": BaseStatDefinition(name_i18n={"en": "Fire Resistance"}, description_i18n={"en": "Resistance to fire damage"}, default_value=0, min_value=0, max_value=100),
            },
            # derived_stat_rules is removed
            item_effects={}, # Changed from item_definitions
            status_effects={},
            equipment_slots={},
            checks={},
            damage_types={},
            xp_rules=None, # Assuming XPRule is optional and can be None
            loot_tables={},
            action_conflicts=[],
            location_interactions={},
            relation_rules=[], # Added missing required field
            relationship_influence_rules=[] # Added missing required field
        )

        self.player_entity = Character(
            id="player1", name_i18n={"en": "Test Player"}, guild_id="guild1", discord_user_id=123,
            stats={"strength": 12, "dexterity": 11, "constitution": 14},
            skills_data=[{"skill_id": "sword_skill", "level": 5}],
            inventory=[],
            status_effects=[]
            # effective_stats_json removed
        )
        self.npc_entity = NpcModel(
            id="npc1", name_i18n={"en": "Test NPC"}, guild_id="guild1", template_id="goblin_warrior",
            stats={"strength": 15, "dexterity": 8, "constitution": 13},
            skills_data=[{"skill_id": "axe_skill", "level": 3}],
            inventory=[],
            status_effects=[]
        )

    async def test_base_stats_no_modifiers_player(self):
        self.mock_character_manager.get_character = AsyncMock(return_value=self.player_entity)
        self.mock_item_manager.get_item_template = AsyncMock(return_value=None)
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[])

        effective_stats = await calculate_effective_stats(
            db_service=self.mock_db_service, guild_id="guild1", entity_id="player1", entity_type="Character",
            rules_config_data=self.rules_config,
            character_manager=self.mock_character_manager, npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager, status_manager=self.mock_status_manager
        )

        self.assertEqual(effective_stats.get("strength"), 12)
        self.assertEqual(effective_stats.get("dexterity"), 11)
        self.assertEqual(effective_stats.get("constitution"), 14)
        self.assertEqual(effective_stats.get("max_hp"), 140)
        self.assertEqual(effective_stats.get("sword_skill"), 5)
        self.assertEqual(effective_stats.get("attack_bonus"), 0)
        self.assertEqual(len(effective_stats.get("granted_abilities_skills", [])), 0)

    async def test_item_flat_bonus(self):
        self.player_entity.inventory = [{"template_id": "strong_ring", "equipped": True, "id": "ring1"}] # Added 'id' for instance

        strong_ring_template = ItemTemplate(
            id="strong_ring", name_i18n={"en":"Ring of Strength"}, type="ring",
            properties={"stat_modifiers": [StatModifierRule(stat_name="STRENGTH", bonus_type="flat", value=2.0).model_dump()]} # Store in properties
        )
        self.mock_item_manager.get_item_template = AsyncMock(return_value=strong_ring_template)
        self.mock_character_manager.get_character = AsyncMock(return_value=self.player_entity)
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[])

        effective_stats = await calculate_effective_stats(
            db_service=self.mock_db_service, guild_id="guild1", entity_id="player1", entity_type="Character",
            rules_config_data=self.rules_config,
            character_manager=self.mock_character_manager, npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager, status_manager=self.mock_status_manager
        )
        self.assertEqual(effective_stats.get("strength"), 14)

    async def test_item_multiplier_bonus(self):
        self.player_entity.inventory = [{"template_id": "agile_boots", "equipped": True, "id": "boots1"}]
        agile_boots_template = ItemTemplate(
            id="agile_boots", name_i18n={"en":"Boots of Agility"}, type="feet",
            properties={"stat_modifiers": [StatModifierRule(stat_name="DEXTERITY", bonus_type="multiplier", value=1.1).model_dump()]} # Store in properties
        )
        self.mock_item_manager.get_item_template = AsyncMock(return_value=agile_boots_template)
        self.mock_character_manager.get_character = AsyncMock(return_value=self.player_entity)
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[])

        effective_stats = await calculate_effective_stats(
            db_service=self.mock_db_service, guild_id="guild1", entity_id="player1", entity_type="Character",
            rules_config_data=self.rules_config,
            character_manager=self.mock_character_manager, npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager, status_manager=self.mock_status_manager
        )
        self.assertEqual(effective_stats.get("dexterity"), 12) # 11 * 1.1 = 12.1, rounded to 12

    async def test_status_flat_bonus(self):
        blessed_status_instance = StatusEffectInstance(id="status1", status_type="blessed_buff", target_id="player1", target_type="Character", duration=3.0) # template_id removed
        # StatusEffectTemplate removed, using StatusEffectDefinition from rules_schema
        blessed_template_data = StatusEffectDefinition(
            id="blessed_buff", name_i18n={"en":"Blessed"}, description_i18n={"en":"Feeling blessed."},
            stat_modifiers=[StatModifierRule(stat_name="STRENGTH", bonus_type="flat", value=3.0)]
        )
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[blessed_status_instance])
        self.mock_status_manager.get_status_template = AsyncMock(return_value=blessed_template_data)
        self.mock_character_manager.get_character = AsyncMock(return_value=self.player_entity)
        self.mock_item_manager.get_item_template = AsyncMock(return_value=None)

        effective_stats = await calculate_effective_stats(
            db_service=self.mock_db_service, guild_id="guild1", entity_id="player1", entity_type="Character",
            rules_config_data=self.rules_config,
            character_manager=self.mock_character_manager, npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager, status_manager=self.mock_status_manager
        )
        self.assertEqual(effective_stats.get("strength"), 15)

    async def test_combined_item_status_flat_multiplier_order(self):
        self.player_entity.inventory = [{"template_id": "strong_ring", "equipped": True, "id": "ring1"}]
        strong_ring_template = ItemTemplate(
            id="strong_ring", name_i18n={"en":"Ring of Strength"}, type="ring",
            properties={"stat_modifiers": [StatModifierRule(stat_name="STRENGTH", bonus_type="flat", value=2.0).model_dump()]} # Store in properties
        )
        titans_status_instance = StatusEffectInstance(id="status_titan", status_type="might_of_titans", target_id="player1", target_type="Character", duration=2.0) # template_id removed
        # StatusEffectTemplate removed, using StatusEffectDefinition from rules_schema
        titans_template_data = StatusEffectDefinition(
            id="might_of_titans", name_i18n={"en":"Might of Titans"}, description_i18n={"en":"Feeling mighty."},
            stat_modifiers=[StatModifierRule(stat_name="STRENGTH", bonus_type="multiplier", value=1.5)]
        )

        self.mock_item_manager.get_item_template = AsyncMock(return_value=strong_ring_template)
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[titans_status_instance])
        self.mock_status_manager.get_status_template = AsyncMock(return_value=titans_template_data)
        self.mock_character_manager.get_character = AsyncMock(return_value=self.player_entity)

        effective_stats = await calculate_effective_stats(
            db_service=self.mock_db_service, guild_id="guild1", entity_id="player1", entity_type="Character",
            rules_config_data=self.rules_config,
            character_manager=self.mock_character_manager, npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager, status_manager=self.mock_status_manager
        )
        self.assertEqual(effective_stats.get("strength"), 21) # Base 12 + 2 (item_flat) = 14. Then 14 * 1.5 (status_multi) = 21.

    async def test_stat_capping(self):
        self.player_entity.inventory = [{"template_id": "godly_ring", "equipped": True, "id": "ring_god"}]
        godly_ring_template = ItemTemplate(
            id="godly_ring", name_i18n={"en":"Godly Ring of Strength"}, type="ring",
            properties={"stat_modifiers": [StatModifierRule(stat_name="STRENGTH", bonus_type="flat", value=100.0).model_dump()]} # Store in properties
        )
        self.mock_item_manager.get_item_template = AsyncMock(return_value=godly_ring_template)
        self.mock_character_manager.get_character = AsyncMock(return_value=self.player_entity)
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[])

        effective_stats = await calculate_effective_stats(
            db_service=self.mock_db_service, guild_id="guild1", entity_id="player1", entity_type="Character",
            rules_config_data=self.rules_config,
            character_manager=self.mock_character_manager, npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager, status_manager=self.mock_status_manager
        )
        self.assertEqual(effective_stats.get("strength"), 30)

    async def test_granted_abilities(self):
        self.player_entity.inventory = [{"template_id": "skill_helm", "equipped": True, "id": "helm1"}]
        skill_helm_template = ItemTemplate(
            id="skill_helm", name_i18n={"en":"Helm of Knowing"}, type="head",
            properties={"grants_abilities_or_skills": [GrantedAbilityOrSkill(type="skill", id="ancient_knowledge", level=1).model_dump()]} # Store in properties
        )
        self.mock_item_manager.get_item_template = AsyncMock(return_value=skill_helm_template)
        self.mock_character_manager.get_character = AsyncMock(return_value=self.player_entity)
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[])

        effective_stats = await calculate_effective_stats(
            db_service=self.mock_db_service, guild_id="guild1", entity_id="player1", entity_type="Character",
            rules_config_data=self.rules_config,
            character_manager=self.mock_character_manager, npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager, status_manager=self.mock_status_manager
        )
        self.assertIn({"type": "skill", "id": "ancient_knowledge", "level": 1}, effective_stats.get("granted_abilities_skills", []))

    async def test_npc_stats(self):
        self.mock_npc_manager.get_npc = AsyncMock(return_value=self.npc_entity)
        self.mock_item_manager.get_item_template = AsyncMock(return_value=None)
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[])

        effective_stats = await calculate_effective_stats(
            db_service=self.mock_db_service, guild_id="guild1", entity_id="npc1", entity_type="NPC",
            rules_config_data=self.rules_config,
            character_manager=self.mock_character_manager, npc_manager=self.mock_npc_manager,
            item_manager=self.mock_item_manager, status_manager=self.mock_status_manager
        )
        self.assertEqual(effective_stats.get("strength"), 15)
        self.assertEqual(effective_stats.get("constitution"), 13)
        self.assertEqual(effective_stats.get("max_hp"), 130)
        self.assertEqual(effective_stats.get("axe_skill"), 3)

if __name__ == '__main__':
    unittest.main()
