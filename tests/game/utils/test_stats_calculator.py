import asyncio
import unittest
import json
from typing import Dict, Any, List, Optional, Tuple

from bot.ai.rules_schema import CoreGameRulesConfig, BaseStatDefinition, ItemEffectDefinition, StatusEffectDefinition, StatModifierRule, GrantedAbilityOrSkill
from bot.game.utils.stats_calculator import calculate_effective_stats

# --- Mock DB Service (adapted from stats_calculator.py) ---
class MockDBService:
    def __init__(self, player_data: Optional[Dict[str, Any]] = None, npc_data: Optional[Dict[str, Any]] = None):
        self.player_data_store = {"player_test_1": player_data} if player_data else {}
        self.npc_data_store = {"npc_test_1": npc_data} if npc_data else {}

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        # print(f"MockDBService: Fetchone query: {query}, params: {params}") # Optional: for debugging tests
        entity_id = params[0] if params else None
        if "FROM players" in query:
            return self.player_data_store.get(entity_id)
        elif "FROM npcs" in query:
            return self.npc_data_store.get(entity_id)
        return None

    def add_player_data(self, player_id: str, data: Dict[str, Any]):
        self.player_data_store[player_id] = data

    def add_npc_data(self, npc_id: str, data: Dict[str, Any]):
        self.npc_data_store[npc_id] = data

class TestStatsCalculator(unittest.TestCase):

    def _create_base_rules_config(self) -> CoreGameRulesConfig:
        """Helper to create a minimal valid CoreGameRulesConfig."""
        return CoreGameRulesConfig(
            base_stats={
                "STRENGTH": BaseStatDefinition(name_i18n={"en": "Strength"}, description_i18n={}, default_value=10, min_value=1, max_value=30),
                "DEXTERITY": BaseStatDefinition(name_i18n={"en": "Dexterity"}, description_i18n={}, default_value=10, min_value=1, max_value=30),
                "CONSTITUTION": BaseStatDefinition(name_i18n={"en": "Constitution"}, description_i18n={}, default_value=10, min_value=1, max_value=30),
                "WISDOM": BaseStatDefinition(name_i18n={"en": "Wisdom"}, description_i18n={}, default_value=10, min_value=1, max_value=30),
                "INTELLIGENCE": BaseStatDefinition(name_i18n={"en": "Intelligence"}, description_i18n={}, default_value=10, min_value=1, max_value=30),
                "CHARISMA": BaseStatDefinition(name_i18n={"en": "Charisma"}, description_i18n={}, default_value=10, min_value=1, max_value=30),
                "MAX_HP": BaseStatDefinition(name_i18n={"en": "Max HP"}, description_i18n={}, default_value=10, min_value=1, max_value=999),
                "PERCEPTION": BaseStatDefinition(name_i18n={"en": "Perception Skill"}, description_i18n={}, default_value=0, min_value=-5, max_value=20),
                "STEALTH": BaseStatDefinition(name_i18n={"en": "Stealth Skill"}, description_i18n={}, default_value=0, min_value=-5, max_value=20),
                "ATHLETICS": BaseStatDefinition(name_i18n={"en": "Athletics Skill"}, description_i18n={}, default_value=0, min_value=-5, max_value=20),
                "CURRENT_HP": BaseStatDefinition(name_i18n={"en": "Current HP"}, description_i18n={}, default_value=10, min_value=0, max_value=999), # For healing effects
            },
            item_effects={}, status_effects={}, checks={}, damage_types={}, action_conflicts=[], location_interactions={}, equipment_slots={}
        )

    def test_no_effects_player(self):
        rules = self._create_base_rules_config()
        player_data = {
            "id": "player_test_1",
            "stats": json.dumps({"strength": 10, "dexterity": 12, "wisdom": 14, "constitution": 13}),
            "skills_data_json": json.dumps({"perception": 2, "stealth": 1, "athletics": 3}),
            "inventory": json.dumps([]),
            "status_effects": json.dumps([])
        }
        mock_db = MockDBService(player_data=player_data)

        effective_stats = asyncio.run(calculate_effective_stats(mock_db, "player_test_1", "player", rules))

        self.assertEqual(effective_stats["strength"], 10)
        self.assertEqual(effective_stats["dexterity"], 12)
        self.assertEqual(effective_stats["wisdom"], 14)
        self.assertEqual(effective_stats["constitution"], 13)
        self.assertEqual(effective_stats["perception"], 2)
        self.assertEqual(effective_stats["stealth"], 1)
        self.assertEqual(effective_stats["athletics"], 3)
        self.assertEqual(effective_stats["max_hp"], 10) # Default from base_stats
        self.assertEqual(effective_stats.get("intelligence", rules.base_stats["INTELLIGENCE"].default_value), 10) # Check default for unlisted base stat

    def test_item_flat_bonus(self):
        rules = self._create_base_rules_config()
        rules.item_effects["tpl_sword_str"] = ItemEffectDefinition(
            stat_modifiers=[StatModifierRule(stat_name="strength", bonus_type="flat", value=2)]
        )
        player_data = {
            "id": "player_test_1",
            "stats": json.dumps({"strength": 10}),
            "inventory": json.dumps([{"template_id": "tpl_sword_str", "equipped": True}]),
            "status_effects": json.dumps([]),
            "skills_data_json": json.dumps({})
        }
        mock_db = MockDBService(player_data=player_data)
        effective_stats = asyncio.run(calculate_effective_stats(mock_db, "player_test_1", "player", rules))
        self.assertEqual(effective_stats["strength"], 12) # 10 + 2

    def test_item_multiplier_bonus(self):
        rules = self._create_base_rules_config()
        rules.item_effects["tpl_boots_dex_multi"] = ItemEffectDefinition(
            stat_modifiers=[StatModifierRule(stat_name="dexterity", bonus_type="multiplier", value=1.1)] # +10%
        )
        player_data = {
            "id": "player_test_1",
            "stats": json.dumps({"dexterity": 10}),
            "inventory": json.dumps([{"template_id": "tpl_boots_dex_multi", "equipped": True}]),
            "status_effects": json.dumps([]),
            "skills_data_json": json.dumps({})
        }
        mock_db = MockDBService(player_data=player_data)
        effective_stats = asyncio.run(calculate_effective_stats(mock_db, "player_test_1", "player", rules))
        self.assertEqual(effective_stats["dexterity"], 11) # 10 * 1.1 = 11

    def test_status_effect_bonus(self):
        rules = self._create_base_rules_config()
        rules.status_effects["sef_blessed"] = StatusEffectDefinition(
            id="sef_blessed", name_i18n={"en":"Blessed"}, description_i18n={},
            stat_modifiers=[StatModifierRule(stat_name="wisdom", bonus_type="flat", value=2)]
        )
        player_data = {
            "id": "player_test_1",
            "stats": json.dumps({"wisdom": 10}),
            "inventory": json.dumps([]),
            "status_effects": json.dumps([{"id": "sef_blessed"}]),
            "skills_data_json": json.dumps({})
        }
        mock_db = MockDBService(player_data=player_data)
        effective_stats = asyncio.run(calculate_effective_stats(mock_db, "player_test_1", "player", rules))
        self.assertEqual(effective_stats["wisdom"], 12) # 10 + 2

    def test_stacking_effects_player(self):
        rules = self._create_base_rules_config()
        rules.item_effects["tpl_sword_str"] = ItemEffectDefinition(
            stat_modifiers=[StatModifierRule(stat_name="strength", bonus_type="flat", value=2)]
        )
        rules.item_effects["tpl_amulet_con"] = ItemEffectDefinition(
            stat_modifiers=[StatModifierRule(stat_name="constitution", bonus_type="flat", value=5)]
        )
        rules.item_effects["tpl_boots_dex_multi"] = ItemEffectDefinition(
            stat_modifiers=[StatModifierRule(stat_name="dexterity", bonus_type="multiplier", value=1.1)] # +10%
        )
        rules.status_effects["sef_blessed"] = StatusEffectDefinition(
            id="sef_blessed", name_i18n={"en":"Blessed"}, description_i18n={},
            stat_modifiers=[
                StatModifierRule(stat_name="strength", bonus_type="flat", value=1),
                StatModifierRule(stat_name="perception", bonus_type="flat", value=2)
            ]
        )
        rules.status_effects["sef_weakened"] = StatusEffectDefinition(
            id="sef_weakened", name_i18n={"en":"Weakened"}, description_i18n={},
            stat_modifiers=[StatModifierRule(stat_name="strength", bonus_type="flat", value=-2)]
        )

        player_data = {
            "id": "player_test_1",
            "stats": json.dumps({"strength": 10, "dexterity": 12, "wisdom": 14, "constitution": 13}),
            "skills_data_json": json.dumps({"perception": 2, "stealth": 1, "athletics": 3}),
            "inventory": json.dumps([
                {"template_id": "tpl_sword_str", "equipped": True},
                {"template_id": "tpl_amulet_con", "equipped": True},
                {"template_id": "tpl_boots_dex_multi", "equipped": True},
            ]),
            "status_effects": json.dumps([{"id": "sef_blessed"}, {"id": "sef_weakened"}])
        }
        mock_db = MockDBService(player_data=player_data)
        effective_stats = asyncio.run(calculate_effective_stats(mock_db, "player_test_1", "player", rules))

        # Strength: 10 (base) + 2 (sword) + 1 (blessed) - 2 (weakened) = 11
        self.assertEqual(effective_stats["strength"], 11)
        # Dexterity: 12 (base) * 1.1 (boots) = 13.2, rounded to 13
        self.assertEqual(effective_stats["dexterity"], 13)
        # Constitution: 13 (base) + 5 (amulet) = 18
        self.assertEqual(effective_stats["constitution"], 18)
        # Wisdom: 14 (base)
        self.assertEqual(effective_stats["wisdom"], 14)
        # Perception: 2 (base skill) + 2 (blessed) = 4
        self.assertEqual(effective_stats["perception"], 4)
        # Max HP: 10 (default)
        self.assertEqual(effective_stats["max_hp"], 10)

    def test_npc_defaults_and_skills(self):
        rules = self._create_base_rules_config()
        npc_data = {
            "id": "npc_test_1",
            "stats": json.dumps({"strength": 15, "dexterity": 8}), # Missing wisdom, constitution
            "skills_data": json.dumps({"intimidation": 4}), # 'skills_data' not 'skills_data_json'
            "inventory": json.dumps([]),
            "status_effects": json.dumps([])
        }
        mock_db = MockDBService(npc_data=npc_data)
        effective_stats = asyncio.run(calculate_effective_stats(mock_db, "npc_test_1", "npc", rules))

        self.assertEqual(effective_stats["strength"], 15)
        self.assertEqual(effective_stats["dexterity"], 8)
        self.assertEqual(effective_stats["wisdom"], 10) # Default
        self.assertEqual(effective_stats["constitution"], 10) # Default
        self.assertEqual(effective_stats.get("intimidation"), 4) # Custom skill

    def test_min_max_caps(self):
        rules = self._create_base_rules_config()
        rules.base_stats["STRENGTH"].min_value = 5
        rules.base_stats["STRENGTH"].max_value = 18
        rules.item_effects["tpl_str_massive_buff"] = ItemEffectDefinition(
            stat_modifiers=[StatModifierRule(stat_name="strength", bonus_type="flat", value=20)] # Should hit max
        )
        rules.item_effects["tpl_str_massive_debuff"] = ItemEffectDefinition(
            stat_modifiers=[StatModifierRule(stat_name="strength", bonus_type="flat", value=-20)] # Should hit min
        )

        # Test Max Cap
        player_data_max = {
            "id": "player_max", "stats": json.dumps({"strength": 10}),
            "inventory": json.dumps([{"template_id": "tpl_str_massive_buff", "equipped": True}]),
            "status_effects": json.dumps([]), "skills_data_json": json.dumps({})
        }
        mock_db_max = MockDBService()
        mock_db_max.add_player_data("player_max", player_data_max)
        effective_stats_max = asyncio.run(calculate_effective_stats(mock_db_max, "player_max", "player", rules))
        self.assertEqual(effective_stats_max["strength"], 18) # Capped at max_value

        # Test Min Cap
        player_data_min = {
            "id": "player_min", "stats": json.dumps({"strength": 10}),
            "inventory": json.dumps([{"template_id": "tpl_str_massive_debuff", "equipped": True}]),
            "status_effects": json.dumps([]), "skills_data_json": json.dumps({})
        }
        mock_db_min = MockDBService()
        mock_db_min.add_player_data("player_min", player_data_min)
        effective_stats_min = asyncio.run(calculate_effective_stats(mock_db_min, "player_min", "player", rules))
        self.assertEqual(effective_stats_min["strength"], 5) # Capped at min_value

    def test_granted_abilities_skills(self):
        rules = self._create_base_rules_config()
        rules.item_effects["tpl_skill_ring"] = ItemEffectDefinition(
            grants_abilities_or_skills=[GrantedAbilityOrSkill(id="skill_persuasion", type="skill")]
        )
        rules.status_effects["sef_inspired"] = StatusEffectDefinition(
            id="sef_inspired", name_i18n={"en":"Inspired"}, description_i18n={},
            grants_abilities_or_skills=[GrantedAbilityOrSkill(id="abil_rally_cry", type="ability")]
        )
        player_data = {
            "id": "player_test_1", "stats": json.dumps({}), "skills_data_json": json.dumps({}),
            "inventory": json.dumps([{"template_id": "tpl_skill_ring", "equipped": True}]),
            "status_effects": json.dumps([{"id": "sef_inspired"}])
        }
        mock_db = MockDBService(player_data=player_data)
        effective_stats = asyncio.run(calculate_effective_stats(mock_db, "player_test_1", "player", rules))

        expected_grants = [
            {"id": "skill_persuasion", "type": "skill"},
            {"id": "abil_rally_cry", "type": "ability"}
        ]
        self.assertCountEqual(effective_stats["granted_abilities_skills"], expected_grants)


if __name__ == '__main__':
    unittest.main()
