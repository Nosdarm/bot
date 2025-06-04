import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

from bot.game.rules.rule_engine import RuleEngine
from bot.game.models.check_models import DetailedCheckResult, CheckOutcome
from bot.game.models.character import Character
from bot.game.models.npc import NPC
from bot.game.models.status_effect import StatusEffect 
from bot.game.models.item import Item


class TestRuleEngineResolveCheck(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_game_log_manager = AsyncMock()

        self.mock_rules_data = {
            "check_rules": { # Global critical rules
                "critical_success": {"natural_roll": 20, "auto_succeeds": True},
                "critical_failure": {"natural_roll": 1, "auto_fails": True}
            },
            "checks": {
                "stealth_check_dexterity": {
                    "description": "A Dexterity (Stealth) check.",
                    "roll_formula": "1d20",
                    "primary_stat": "dexterity",
                    "relevant_skill": "stealth",
                    "target_dc_stat": "passive_perception",
                    "default_dc": 12
                },
                "strength_saving_throw": {
                    "description": "A Strength saving throw.",
                    "roll_formula": "1d20",
                    "primary_stat": "strength",
                    "default_dc": 14
                },
                "attack_roll_melee_strength": {
                    "description": "A melee attack roll using Strength.",
                    "roll_formula": "1d20",
                    "primary_stat": "strength",
                    "target_dc_stat": "armor_class",
                    "default_dc": 10
                },
                "persuasion_check_charisma": {
                    "description": "A Charisma (Persuasion) check.",
                    "roll_formula": "1d20",
                    "primary_stat": "charisma",
                    "relevant_skill": "persuasion",
                    "default_dc": 15
                },
                "perception_check_wisdom": { # For testing target_dc_stat
                    "description": "A Wisdom (Perception) check.",
                    "roll_formula": "1d20",
                    "primary_stat": "wisdom",
                    "relevant_skill": "perception",
                    "target_dc_stat": "passive_stealth_value", # Specific stat on target
                    "default_dc": 13
                },
                "generic_check_no_auto_crit": { # For testing criticals without auto-success/fail
                    "description": "Generic check where crits don't auto-succeed/fail.",
                    "roll_formula": "1d20",
                    "default_dc": 15,
                    "critical_success": {"natural_roll": 20, "auto_succeeds": False},
                    "critical_failure": {"natural_roll": 1, "auto_fails": False}
                },
                 "default_dc_only_check": { # For testing default_dc
                    "description": "A check that only has a default_dc.",
                    "roll_formula": "1d20",
                    "default_dc": 18
                }
            },
            "character_stats_rules": { 
                "attribute_modifier_formula": "(attribute_value - 10) // 2"
            },
            "status_templates": { 
                "dex_buff_status": {
                    "name_i18n": {"en": "Dexterity Boost"},
                    "modifies_stat": "dexterity",
                    "modifier_value": 2
                },
                "stealth_skill_buff_status": {
                    "name_i18n": {"en": "Stealth Expertise"},
                    "modifies_skill": "stealth",
                    "modifier_value": 3 
                },
                 "generic_bonus_to_stealth_checks": { 
                    "name_i18n": {"en": "Shadow Cloak"},
                    "modifies_check_type": "stealth_check_dexterity", 
                    "modifier_value": 5
                }
            },
            "item_templates": { 
                "charisma_amulet_template": {
                    "id": "charisma_amulet_template",
                    "name_i18n": {"en": "Amulet of Charisma"},
                    "properties": {
                        "modifies_stat": "charisma",
                        "modifier_value": 1
                    }
                },
                "persuasion_ring_template": {
                    "id": "persuasion_ring_template",
                    "name_i18n": {"en": "Ring of Persuasion"},
                    "properties": {
                        "modifies_skill": "persuasion",
                        "modifier_value": 2
                    }
                },
                "luckystone_template": {
                    "id": "luckystone_template",
                    "name_i18n": {"en": "Lucky Stone"},
                    "properties": {
                        "modifies_check_type": "persuasion_check_charisma", 
                        "modifier_value": 3
                    }
                }
            }
        }

        self.rule_engine = RuleEngine(
            settings={}, 
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            status_manager=self.mock_status_manager,
            item_manager=self.mock_item_manager,
            game_log_manager=self.mock_game_log_manager, # Pass the mock log manager
            rules_data=self.mock_rules_data
        )
        
        self.mock_status_manager.get_status_template.side_effect = lambda status_type: self.mock_rules_data["status_templates"].get(status_type)
        self.mock_item_manager.get_item_template.side_effect = lambda template_id: self.mock_rules_data["item_templates"].get(template_id)


        self.mock_resolve_dice_roll_patch = patch.object(self.rule_engine, 'resolve_dice_roll', new_callable=AsyncMock)
        self.mock_dice_roller = self.mock_resolve_dice_roll_patch.start()
        self.addCleanup(self.mock_resolve_dice_roll_patch.stop)

        # Store for mock actors created in tests
        self.mock_actors_cache = {}

        def mock_get_character_side_effect(guild_id, character_id):
            # print(f"TEST_DEBUG (side_effect): mock_get_character_side_effect called with guild_id='{guild_id}', character_id='{character_id}'")
            actor_found = self.mock_actors_cache.get(character_id)
            # print(f"TEST_DEBUG (side_effect): mock_actors_cache keys: {list(self.mock_actors_cache.keys())}")
            # print(f"TEST_DEBUG (side_effect): mock_get_character_side_effect returning: actor_id='{actor_found.id if actor_found else 'None'}' with status_effects: {getattr(actor_found, 'status_effects', 'N/A')}")
            return actor_found

        def mock_get_npc_side_effect(guild_id, npc_id):
            return self.mock_actors_cache.get(npc_id)

        self.mock_character_manager.get_character.side_effect = mock_get_character_side_effect
        self.mock_npc_manager.get_npc.side_effect = mock_get_npc_side_effect


    def _create_mock_actor(self, actor_id="actor1", entity_type="Character", stats=None, skills=None, current_status_effects=None, items=None):
        mock_actor = MagicMock(spec=Character if entity_type == "Character" else NPC)
        mock_actor.id = actor_id
        mock_actor.name = f"{entity_type}_{actor_id}" 
        mock_actor.stats = stats if stats else {}
        mock_actor.skills = skills if skills else {}
        mock_actor.status_effects = current_status_effects if current_status_effects else []
        mock_actor.inventory = items if items else [] 
        
        self.mock_actors_cache[actor_id] = mock_actor
        # print(f"TEST_DEBUG (_create_mock_actor): Created and cached actor_id='{actor_id}' with status_effects: {mock_actor.status_effects}")
        return mock_actor

    async def test_basic_dc_check_skill_stealth_success(self):
        actor = self._create_mock_actor(stats={"dexterity": 14}, skills={"stealth": 3})
        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10} 

        result = await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=15,
            context={"guild_id": "test_guild"}
        )

        self.assertTrue(result.is_success)
        self.assertEqual(result.total_roll_value, 15) 
        self.assertEqual(result.modifier_applied, 5) 
        self.assertIn({"value": 2, "source": "stat:dexterity"}, result.modifier_details)
        self.assertIn({"value": 3, "source": "skill:stealth"}, result.modifier_details)
        self.assertEqual(result.outcome, CheckOutcome.SUCCESS)

    async def test_basic_dc_check_skill_stealth_failure(self):
        actor = self._create_mock_actor(stats={"dexterity": 10}, skills={"stealth": 1}) 
        self.mock_dice_roller.return_value = {"rolls": [5], "total": 5}

        result = await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=15,
            context={"guild_id": "test_guild"}
        )

        self.assertFalse(result.is_success)
        self.assertEqual(result.total_roll_value, 6) 
        self.assertEqual(result.modifier_applied, 1)
        self.assertFalse(any(d['source'] == 'stat:dexterity' for d in result.modifier_details))
        self.assertIn({"value": 1, "source": "skill:stealth"}, result.modifier_details)
        self.assertEqual(result.outcome, CheckOutcome.FAILURE)

    async def test_basic_saving_throw_strength_success(self):
        actor = self._create_mock_actor(stats={"strength": 16}) 
        self.mock_dice_roller.return_value = {"rolls": [12], "total": 12}

        result = await self.rule_engine.resolve_check(
            check_type="strength_saving_throw",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=15, 
            context={"guild_id": "test_guild"}
        )
        self.assertTrue(result.is_success)
        self.assertEqual(result.total_roll_value, 15)
        self.assertEqual(result.modifier_applied, 3)
        self.assertIn({"value": 3, "source": "stat:strength"}, result.modifier_details)
        self.assertEqual(result.outcome, CheckOutcome.SUCCESS)

    async def test_attack_roll_melee_vs_target_ac(self):
        attacker = self._create_mock_actor(actor_id="attacker", stats={"strength": 12})
        target_npc = self._create_mock_actor(actor_id="target", entity_type="NPC", stats={"armor_class": 13})
        
        # self.mock_character_manager.get_character.return_value = attacker # Now handled by side_effect
        # self.mock_npc_manager.get_npc.return_value = target_npc

        self.mock_dice_roller.return_value = {"rolls": [13], "total": 13}

        result = await self.rule_engine.resolve_check(
            check_type="attack_roll_melee_strength",
            entity_doing_check_id=attacker.id,
            entity_doing_check_type="Character",
            target_entity_id=target_npc.id,
            target_entity_type="NPC",
            context={"guild_id": "test_guild"}
        )

        self.assertTrue(result.is_success)
        self.assertEqual(result.target_value, 13) 
        self.assertEqual(result.total_roll_value, 14)
        self.assertEqual(result.modifier_applied, 1)
        self.assertIn({"value": 1, "source": "stat:strength"}, result.modifier_details)

    async def test_check_with_status_effect_modifier_stat(self):
        status_effect_data = {"id": "status1", "status_type": "dex_buff_status", "target_id": "actor_char_status_stat", "target_type": "Character", "state_variables": {}}
        actor = self._create_mock_actor(actor_id="actor_char_status_stat", stats={"dexterity": 10}, current_status_effects=[status_effect_data])
        
        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}

        result = await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=13, 
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.total_roll_value, 12) 
        self.assertEqual(result.modifier_applied, 2) 
        
        found_status_mod = False
        for detail in result.modifier_details:
            if detail.get("source") == "status:dex_buff_status" and detail.get("value") == 2:
                found_status_mod = True
                self.assertEqual(detail.get("effect_id"), "status1")
                self.assertEqual(detail.get("effect_name"), "Dexterity Boost")
                break
        self.assertTrue(found_status_mod, "Status effect modifier not found or incorrect in details")

    async def test_check_with_status_effect_modifier_skill(self):
        status_effect_data = {"id": "status2", "status_type": "stealth_skill_buff_status", "target_id": "actor_char_status_skill", "target_type": "Character", "state_variables": {}}
        actor = self._create_mock_actor(actor_id="actor_char_status_skill", stats={"dexterity": 10}, skills={"stealth": 1}, current_status_effects=[status_effect_data])
        
        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}

        result = await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=15, 
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.total_roll_value, 14) 
        self.assertEqual(result.modifier_applied, 1 + 3) 
        
        self.assertIn({"value": 1, "source": "skill:stealth"}, result.modifier_details)
        found_status_mod = False
        for detail in result.modifier_details:
            if detail.get("source") == "status:stealth_skill_buff_status" and detail.get("value") == 3:
                found_status_mod = True
                break
        self.assertTrue(found_status_mod, "Status effect (skill) modifier not found or incorrect in details")

    async def test_check_with_status_effect_modifier_check_type(self):
        status_effect_data = {"id": "status3", "status_type": "generic_bonus_to_stealth_checks", "target_id": "actor_char_status_check", "target_type": "Character", "state_variables": {}}
        actor = self._create_mock_actor(actor_id="actor_char_status_check", stats={"dexterity": 10}, skills={"stealth": 0}, current_status_effects=[status_effect_data])
        
        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}

        result = await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=16, 
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.total_roll_value, 15) 
        self.assertEqual(result.modifier_applied, 5) 
        
        found_status_mod = False
        for detail in result.modifier_details:
            if detail.get("source") == "status:generic_bonus_to_stealth_checks" and detail.get("value") == 5:
                found_status_mod = True
                break
        self.assertTrue(found_status_mod, "Status effect (check_type) modifier not found or incorrect in details")

    async def test_check_with_item_modifier_stat(self):
        actor_id_for_test = "actor_item_stat"
        item_instance = Item(id="item1", template_id="charisma_amulet_template", guild_id="test_guild", owner_id=actor_id_for_test)
        actor = self._create_mock_actor(actor_id=actor_id_for_test, stats={"charisma": 10}, items=[item_instance])
        self.mock_item_manager.get_items_by_owner.return_value = [item_instance]

        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}

        result = await self.rule_engine.resolve_check(
            check_type="persuasion_check_charisma", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=12, 
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.total_roll_value, 11)
        self.assertEqual(result.modifier_applied, 1)
        
        found_item_mod = False
        for detail in result.modifier_details:
            if detail.get("source") == "item:Amulet of Charisma" and detail.get("value") == 1:
                found_item_mod = True
                self.assertEqual(detail.get("item_id"), "item1")
                break
        self.assertTrue(found_item_mod, "Item (stat) modifier not found or incorrect")

    async def test_check_with_item_modifier_skill(self):
        actor_id_for_test = "actor_item_skill"
        item_instance = Item(id="item2", template_id="persuasion_ring_template", guild_id="test_guild", owner_id=actor_id_for_test)
        actor = self._create_mock_actor(actor_id=actor_id_for_test, stats={"charisma": 10}, skills={"persuasion": 1}, items=[item_instance])
        self.mock_item_manager.get_items_by_owner.return_value = [item_instance]

        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}

        result = await self.rule_engine.resolve_check(
            check_type="persuasion_check_charisma", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=14, 
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.total_roll_value, 13)
        self.assertEqual(result.modifier_applied, 1 + 2)
        
        self.assertIn({"value": 1, "source": "skill:persuasion"}, result.modifier_details)
        found_item_mod = False
        for detail in result.modifier_details:
            if detail.get("source") == "item:Ring of Persuasion" and detail.get("value") == 2:
                found_item_mod = True
                break
        self.assertTrue(found_item_mod, "Item (skill) modifier not found or incorrect")

    async def test_check_with_item_modifier_check_type(self):
        actor_id_for_test = "actor_item_check_type"
        item_instance = Item(id="item3", template_id="luckystone_template", guild_id="test_guild", owner_id=actor_id_for_test)
        actor = self._create_mock_actor(actor_id=actor_id_for_test, stats={"charisma": 10}, skills={"persuasion": 0}, items=[item_instance])
        self.mock_item_manager.get_items_by_owner.return_value = [item_instance]

        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}

        result = await self.rule_engine.resolve_check(
            check_type="persuasion_check_charisma", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=14, 
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.total_roll_value, 13)
        self.assertEqual(result.modifier_applied, 3)

        found_item_mod = False
        for detail in result.modifier_details:
            if detail.get("source") == "item:Lucky Stone" and detail.get("value") == 3:
                found_item_mod = True
                break
        self.assertTrue(found_item_mod, "Item (check_type) modifier not found or incorrect")


    async def test_check_with_contextual_modifier(self):
        actor = self._create_mock_actor(stats={"dexterity": 10}) 
        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}
        context = {
            "guild_id": "test_guild",
            "situational_modifiers": [{'value': -2, 'source': 'Poor Lighting'}]
        }
        result = await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=9, 
            context=context
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.total_roll_value, 8)
        self.assertEqual(result.modifier_applied, -2)
        self.assertIn({"value": -2, "source": "context:Poor Lighting"}, result.modifier_details)

    async def test_check_with_all_modifiers_combined(self):
        # print(f"DEBUG_TEST ({self.id()}): STARTING") # Removed to reduce noise
        original_luckystone_props = self.mock_rules_data["item_templates"]["luckystone_template"]["properties"]
        self.mock_rules_data["item_templates"]["luckystone_template"]["properties"] = {
            "modifies_check_type": "stealth_check_dexterity", "modifier_value": 3
        }
        self.mock_item_manager.get_item_template.side_effect = lambda template_id: self.mock_rules_data["item_templates"].get(template_id)

        actor_id_for_test = "actor_all_mods_isolated" 
        
        status_effect_data_all_mods = { 
            "id": "s_dex_isolated", 
            "status_type": "dex_buff_status", 
            "target_id": actor_id_for_test, 
            "target_type": "Character",   
            "state_variables": {}
        } 
        item_instance = Item(id="item_luck_isolated", template_id="luckystone_template", guild_id="test_guild", owner_id=actor_id_for_test)
        
        # print(f"DEBUG_TEST ({self.id()}): status_effect_data_all_mods before create: {status_effect_data_all_mods}")

        actor = self._create_mock_actor(
            actor_id=actor_id_for_test, 
            stats={"dexterity": 14}, 
            skills={"stealth": 3},    
            current_status_effects=[status_effect_data_all_mods], 
            items=[item_instance] 
        )
        self.mock_item_manager.get_items_by_owner.return_value = [item_instance]
        # print(f"DEBUG_TEST ({self.id()}): actor.id after create: {actor.id}")
        # print(f"DEBUG_TEST ({self.id()}): actor.status_effects after create: {actor.status_effects}")


        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}
        context = {
            "guild_id": "test_guild",
            "situational_modifiers": [{'value': -1, 'source': 'Slightly Noisy'}] 
        }
        
        # print(f"DEBUG_TEST ({self.id()}): Calling resolve_check with actor_id='{actor.id}'")
        result = await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=18, 
            context=context
        )
        # print(f"DEBUG_TEST ({self.id()}): resolve_check returned. Result description: {result.description}")


        self.assertTrue(result.is_success)
        self.assertEqual(result.total_roll_value, 19)
        self.assertEqual(result.modifier_applied, 9)

        self.assertIn({"value": 2, "source": "stat:dexterity"}, result.modifier_details)
        self.assertIn({"value": 3, "source": "skill:stealth"}, result.modifier_details)
        self.assertTrue(any(d.get("source") == "status:dex_buff_status" and d.get("value") == 2 for d in result.modifier_details))
        self.assertTrue(any(d.get("source") == "item:Lucky Stone" and d.get("value") == 3 for d in result.modifier_details))
        self.assertIn({"value": -1, "source": "context:Slightly Noisy"}, result.modifier_details)
        
        self.mock_rules_data["item_templates"]["luckystone_template"]["properties"] = original_luckystone_props
        # print(f"DEBUG_TEST ({self.id()}): FINISHED") # Removed to reduce noise

    async def test_critical_success_auto_succeeds(self):
        actor = self._create_mock_actor(stats={"dexterity": 0}) 
        self.mock_dice_roller.return_value = {"rolls": [20], "total": 20} 

        result = await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=100, 
            context={"guild_id": "test_guild"}
        )
        self.assertTrue(result.is_success) 
        self.assertTrue(result.is_critical)
        self.assertEqual(result.outcome, CheckOutcome.CRITICAL_SUCCESS)
        self.assertEqual(result.total_roll_value, 15) 

    async def test_critical_failure_auto_fails(self):
        actor = self._create_mock_actor(stats={"strength": 30}) 
        self.mock_dice_roller.return_value = {"rolls": [1], "total": 1} 

        result = await self.rule_engine.resolve_check(
            check_type="strength_saving_throw", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=1, 
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success) 
        self.assertTrue(result.is_critical)
        self.assertEqual(result.outcome, CheckOutcome.CRITICAL_FAILURE)
        self.assertEqual(result.total_roll_value, 11) 

    async def test_critical_success_no_auto_succeed_pass(self):
        actor = self._create_mock_actor()
        self.mock_dice_roller.return_value = {"rolls": [20], "total": 20}
        result = await self.rule_engine.resolve_check(
            check_type="generic_check_no_auto_crit", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=15, 
            context={"guild_id": "test_guild"}
        )
        self.assertTrue(result.is_success)
        self.assertTrue(result.is_critical) 
        self.assertEqual(result.outcome, CheckOutcome.CRITICAL_SUCCESS) 

    async def test_critical_success_no_auto_succeed_fail(self):
        actor = self._create_mock_actor()
        self.mock_dice_roller.return_value = {"rolls": [20], "total": 20}
        result = await self.rule_engine.resolve_check(
            check_type="generic_check_no_auto_crit",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=25, 
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success) 
        self.assertTrue(result.is_critical) 
        self.assertEqual(result.outcome, CheckOutcome.CRITICAL_SUCCESS) 

    async def test_check_with_target_dc_stat(self):
        actor = self._create_mock_actor(stats={"wisdom": 12}, skills={"perception": 2}) 
        target = self._create_mock_actor(actor_id="target_npc_passive_stealth", entity_type="NPC", stats={"passive_stealth_value": 15})
        # self.mock_npc_manager.get_npc.return_value = target # Handled by side_effect

        self.mock_dice_roller.return_value = {"rolls": [11], "total": 11} 

        result = await self.rule_engine.resolve_check(
            check_type="perception_check_wisdom",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            target_entity_id=target.id,
            target_entity_type="NPC",
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.target_value, 15) 
        self.assertEqual(result.total_roll_value, 14)

    async def test_check_with_default_dc(self):
        actor = self._create_mock_actor()
        self.mock_dice_roller.return_value = {"rolls": [17], "total": 17} 

        result = await self.rule_engine.resolve_check(
            check_type="default_dc_only_check", 
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success) 
        self.assertEqual(result.target_value, 18) 
        self.assertEqual(result.total_roll_value, 17)

    async def test_invalid_check_type(self):
        actor = self._create_mock_actor()
        result = await self.rule_engine.resolve_check(
            check_type="non_existent_check",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=10,
            context={"guild_id": "test_guild"}
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.outcome, CheckOutcome.FAILURE) 
        self.assertTrue("Error: No configuration found" in result.description)

    async def test_logging_calls(self):
        actor = self._create_mock_actor(stats={"dexterity": 10})
        self.mock_dice_roller.return_value = {"rolls": [10], "total": 10}

        await self.rule_engine.resolve_check(
            check_type="stealth_check_dexterity",
            entity_doing_check_id=actor.id,
            entity_doing_check_type="Character",
            difficulty_dc=15,
            context={"guild_id": "test_guild_log"} 
        )

        self.mock_game_log_manager.log_event.assert_any_call(
            guild_id="test_guild_log",
            event_type="resolve_check_start",
            message=unittest.mock.ANY, 
            related_entities=unittest.mock.ANY,
            metadata=unittest.mock.ANY
        )
        self.mock_game_log_manager.log_event.assert_any_call(
            guild_id="test_guild_log",
            event_type="resolve_check_end",
            message=unittest.mock.ANY,
            related_entities=unittest.mock.ANY,
            metadata=unittest.mock.ANY
        )
        self.assertEqual(self.mock_game_log_manager.log_event.call_count, 2)


if __name__ == '__main__':
    unittest.main()
