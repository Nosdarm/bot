import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock

from bot.game.utils.stats_calculator import calculate_effective_stats
from bot.ai.rules_schema import CoreGameRulesConfig, BaseStatDefinition, ItemDefinition, StatModifierRule, StatusEffectDefinition, GrantedAbilityOrSkill # ItemDefinition might not be used directly if ItemTemplate is used
from bot.game.models.character import Character
from bot.game.models.npc import NPC as NpcModel
from bot.game.models.item import ItemTemplate
from bot.game.models.status_effect import StatusEffect as StatusEffectInstance
from bot.game.models.status_effect import StatusEffectTemplate

class TestStatsCalculator(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()

        self.rules_config = CoreGameRulesConfig(
            base_stats={
                "STRENGTH": BaseStatDefinition(name_i18n={"en": "Strength"}, default_value=10, min_value=1, max_value=30),
                "DEXTERITY": BaseStatDefinition(name_i18n={"en": "Dexterity"}, default_value=10, min_value=1, max_value=30),
                "CONSTITUTION": BaseStatDefinition(name_i18n={"en": "Constitution"}, default_value=10, min_value=1, max_value=30),
                "MAX_HP": BaseStatDefinition(name_i18n={"en": "Max HP"}, default_value=50, min_value=1, max_value=1000),
                "ATTACK_BONUS": BaseStatDefinition(name_i18n={"en": "Attack Bonus"}, default_value=0, min_value=-5, max_value=20),
                "FIRE_RESISTANCE": BaseStatDefinition(name_i18n={"en": "Fire Resistance"}, default_value=0, min_value=0, max_value=100),
            },
            derived_stat_rules={ # Assuming derived_stat_rules is a Dict[str, float] or a Pydantic model
                "hp_per_constitution_point": 10.0,
                "base_hp_offset": 0.0
            },
            item_definitions={},
            status_effects={},
            equipment_slots={}, checks={}, damage_types={}, xp_rules=None, loot_tables={}, action_conflicts=[], location_interactions={}
        )

        self.player_entity = Character(
            id="player1", name="Test Player", guild_id="guild1", discord_user_id=123,
            stats={"strength": 12, "dexterity": 11, "constitution": 14},
            skills_data_json=json.dumps({"sword_skill": 5}),
            inventory=[],
            status_effects=[],
            effective_stats_json="{}"
        )
        self.npc_entity = NpcModel(
            id="npc1", name_i18n={"en": "Test NPC"}, guild_id="guild1", template_id="goblin_warrior",
            stats={"strength": 15, "dexterity": 8, "constitution": 13},
            skills_data_json=json.dumps({"axe_skill": 3}),
            inventory=[],
            status_effects=[],
            effective_stats_json="{}"
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

        strong_ring_template = ItemTemplate( # Mocking ItemTemplate from models
            id="strong_ring", name_i18n={"en":"Ring of Strength"}, type="ring",
            stat_modifiers=[StatModifierRule(stat_name="STRENGTH", bonus_type="flat", value=2.0)]
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
            stat_modifiers=[StatModifierRule(stat_name="DEXTERITY", bonus_type="multiplier", value=1.1)]
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
        blessed_status_instance = StatusEffectInstance(id="status1", status_type="blessed_buff", target_id="player1", target_type="Character", duration=3.0, template_id="blessed_buff")
        blessed_template = StatusEffectTemplate( # Mocking StatusEffectTemplate
            id="blessed_buff", name_i18n={"en":"Blessed"},
            stat_modifiers=[StatModifierRule(stat_name="STRENGTH", bonus_type="flat", value=3.0)]
        )
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[blessed_status_instance])
        self.mock_status_manager.get_status_template = AsyncMock(return_value=blessed_template)
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
            stat_modifiers=[StatModifierRule(stat_name="STRENGTH", bonus_type="flat", value=2.0)]
        )
        titans_status_instance = StatusEffectInstance(id="status_titan", status_type="might_of_titans", target_id="player1", target_type="Character", duration=2.0, template_id="might_of_titans")
        titans_template = StatusEffectTemplate(
            id="might_of_titans", name_i18n={"en":"Might of Titans"},
            stat_modifiers=[StatModifierRule(stat_name="STRENGTH", bonus_type="multiplier", value=1.5)]
        )

        self.mock_item_manager.get_item_template = AsyncMock(return_value=strong_ring_template)
        self.mock_status_manager.get_active_statuses_for_entity = AsyncMock(return_value=[titans_status_instance])
        self.mock_status_manager.get_status_template = AsyncMock(return_value=titans_template)
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
            stat_modifiers=[StatModifierRule(stat_name="STRENGTH", bonus_type="flat", value=100.0)]
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
            grants_abilities_or_skills=[GrantedAbilityOrSkill(type="skill", id="ancient_knowledge", level=1)]
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
