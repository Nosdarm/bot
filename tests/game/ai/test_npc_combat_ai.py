import unittest
import random # For potential mocking later if tests are flaky

from bot.game.ai.npc_combat_ai import NpcCombatAI
from bot.game.models.npc import NPC
from bot.game.models.character import Character # Assuming Character model is in this path

class TestNpcCombatAI(unittest.TestCase):

    def setUp(self):
        # NPC actor for most tests
        self.npc_actor = NPC(
            id="npc_1",
            name_i18n={"en": "Test NPC"},
            template_id="test_template",
            guild_id="test_guild",
            stats={"strength": 10, "dexterity": 10},
            health=50,
            max_health=50,
            is_alive=True,
            known_spells=["fireball_id"], # Assuming these are spell/ability IDs
            known_abilities=["power_attack_id"],
            role="dps"
        )

        # NPC with no special abilities
        self.npc_no_specials = NPC(
            id="npc_no_specials",
            name_i18n={"en": "Basic NPC"},
            template_id="basic_template",
            guild_id="test_guild",
            stats={"strength": 5},
            health=30,
            max_health=30,
            is_alive=True,
            known_spells=[],
            known_abilities=[],
            role="grunt"
        )

        # Character targets
        # Assuming Character constructor: id, name_i18n, guild_id, hp, max_health, is_alive, stats, state_variables
        # discord_user_id is not a standard field in Character model based on previous context
        self.char_healer_full_hp = Character(
            id="char_1", name_i18n={"en": "Healer Full"}, guild_id="test_guild",
            hp=100, max_health=100, is_alive=True, stats={"intelligence": 15},
            state_variables={"role": "healer"}
        )
        self.char_healer_injured = Character(
            id="char_healer_inj", name_i18n={"en": "Healer Injured"}, guild_id="test_guild",
            hp=80, max_health=100, is_alive=True, stats={"intelligence": 15},
            state_variables={"role": "healer"} # HP is 80/100, so < max_hp
        )
        self.char_mage_low_hp = Character(
            id="char_2", name_i18n={"en": "Mage Low"}, guild_id="test_guild",
            hp=30, max_health=100, is_alive=True, stats={"intelligence": 18},
            state_variables={"role": "mage"} # HP is 30/100, so < max_hp
        )
        self.char_fighter_mid_hp = Character( # Corrected name for clarity
            id="char_3", name_i18n={"en": "Fighter Mid"}, guild_id="test_guild",
            hp=60, max_health=120, is_alive=True, stats={"strength": 16},
            state_variables={"role": "fighter"}
        )
        self.dead_char = Character(
            id="char_dead", name_i18n={"en": "Dead"}, guild_id="test_guild",
            hp=0, max_health=100, is_alive=False # Explicitly is_alive=False
        )

        # NPC target
        self.other_npc_target = NPC(
            id="npc_2",
            name_i18n={"en": "Other NPC"},
            template_id="test_template_2",
            guild_id="test_guild",
            health=40, # Lower HP than char_fighter_mid_hp for one test
            max_health=40,
            is_alive=True,
            role="tank"
        )

        self.dead_npc_target = NPC(
            id="npc_dead",
            name_i18n={"en": "Dead NPC"},
            template_id="dead_template",
            guild_id="test_guild",
            health=0,
            max_health=50,
            is_alive=False, # Explicitly is_alive=False
            role="grunt"
        )


    # --- Tests for select_target ---
    def test_select_target_no_targets(self):
        ai = NpcCombatAI(self.npc_actor)
        targets = []
        self.assertIsNone(ai.select_target(targets, {}))

    def test_select_target_only_self(self):
        ai = NpcCombatAI(self.npc_actor)
        targets = [self.npc_actor]
        self.assertIsNone(ai.select_target(targets, {}))

    def test_select_target_dead_target(self):
        ai = NpcCombatAI(self.npc_actor)
        targets = [self.dead_char]
        self.assertIsNone(ai.select_target(targets, {}))

    def test_select_target_all_dead_targets(self):
        ai = NpcCombatAI(self.npc_actor)
        targets = [self.dead_char, self.dead_npc_target]
        self.assertIsNone(ai.select_target(targets, {}))

    def test_select_target_lowest_hp_low_difficulty(self):
        ai = NpcCombatAI(self.npc_actor)
        targets = [self.char_healer_full_hp, self.char_mage_low_hp, self.other_npc_target]
        # Healer: 100hp, Mage: 30hp, Other NPC: 40hp
        context = {"difficulty_level": 1}
        selected = ai.select_target(targets, context)
        self.assertEqual(selected, self.char_mage_low_hp)

    def test_select_target_prioritizes_injured_healer_high_difficulty(self):
        ai = NpcCombatAI(self.npc_actor)
        # Mage: 30hp, Other NPC: 40hp, Injured Healer: 80hp (but is < max_hp)
        targets = [self.char_healer_injured, self.char_mage_low_hp, self.other_npc_target]
        context = {"difficulty_level": 3}
        selected = ai.select_target(targets, context)
        # AI should pick injured healer (role prio for Character, HP < max_hp)
        self.assertEqual(selected, self.char_healer_injured)

    def test_select_target_prioritizes_injured_mage_high_difficulty_healer_full(self):
        ai = NpcCombatAI(self.npc_actor)
        # Healer Full: 100hp, Mage Low: 30hp, Other NPC: 40hp
        # Mage is injured (hp < max_hp) and has a priority role.
        targets = [self.char_healer_full_hp, self.char_mage_low_hp, self.other_npc_target]
        context = {"difficulty_level": 3}
        selected = ai.select_target(targets, context)
        self.assertEqual(selected, self.char_mage_low_hp)

    def test_select_target_character_over_npc_high_difficulty_no_priority_role(self):
        ai = NpcCombatAI(self.npc_actor)
        # Fighter Mid HP: 60hp, Other NPC: 40hp. No priority roles injured.
        # AI should prefer Character over NPC at high difficulty.
        targets = [self.char_fighter_mid_hp, self.other_npc_target]
        context = {"difficulty_level": 3}
        selected = ai.select_target(targets, context)
        self.assertEqual(selected, self.char_fighter_mid_hp)

    def test_select_target_npc_if_only_option_high_difficulty(self):
        ai = NpcCombatAI(self.npc_actor)
        targets = [self.other_npc_target]
        context = {"difficulty_level": 3}
        selected = ai.select_target(targets, context)
        self.assertEqual(selected, self.other_npc_target)

    # --- Tests for select_action ---
    def test_select_action_no_target(self):
        ai = NpcCombatAI(self.npc_actor)
        action = ai.select_action(target=None, combat_context={})
        self.assertIsNotNone(action)
        self.assertEqual(action.get("type"), "wait")
        self.assertEqual(action.get("actor_id"), self.npc_actor.id)

    def test_select_action_with_target_low_difficulty(self):
        ai = NpcCombatAI(self.npc_actor)
        context = {"difficulty_level": 1}
        action = ai.select_action(target=self.char_mage_low_hp, combat_context=context)
        self.assertIsNotNone(action)
        self.assertEqual(action.get("type"), "attack")
        self.assertEqual(action.get("target_id"), self.char_mage_low_hp.id)
        self.assertEqual(action.get("actor_id"), self.npc_actor.id)

    def test_select_action_with_target_high_difficulty_can_choose_special(self):
        ai = NpcCombatAI(self.npc_actor) # This NPC has spells and abilities
        context = {"difficulty_level": 3}
        action_types = set()

        # Mock random.random to control outcomes for deterministic testing of both branches
        # Test spell/ability path
        with unittest.mock.patch('random.random', return_value=0.4): # < 0.5, should pick special
            action_special = ai.select_action(target=self.char_mage_low_hp, combat_context=context)
            self.assertIsNotNone(action_special)
            self.assertIn(action_special.get("type"), ["spell", "ability"])
            if action_special.get("type") == "spell":
                self.assertEqual(action_special.get("spell_id"), "fireball_id")
            else: # ability
                self.assertEqual(action_special.get("ability_id"), "power_attack_id")

        # Test attack path
        with unittest.mock.patch('random.random', return_value=0.6): # >= 0.5, should pick attack
            action_attack = ai.select_action(target=self.char_mage_low_hp, combat_context=context)
            self.assertIsNotNone(action_attack)
            self.assertEqual(action_attack.get("type"), "attack")

        # Original probabilistic check (can be flaky, kept for reference or if mocking is removed)
        # for _ in range(50): # Run multiple times for probabilistic check
        #     action = ai.select_action(target=self.char_mage_low_hp, combat_context=context)
        #     self.assertIsNotNone(action)
        #     action_types.add(action["type"])
        # self.assertIn("attack", action_types)
        # self.assertTrue("spell" in action_types or "ability" in action_types,
        #                 f"Neither spell nor ability found in action types: {action_types}")


    def test_select_action_high_difficulty_no_specials_defaults_to_attack(self):
        ai = NpcCombatAI(self.npc_no_specials) # This NPC has no spells/abilities
        context = {"difficulty_level": 3}
        action = ai.select_action(target=self.char_mage_low_hp, combat_context=context)
        self.assertIsNotNone(action)
        self.assertEqual(action.get("type"), "attack")
        self.assertEqual(action.get("target_id"), self.char_mage_low_hp.id)
        self.assertEqual(action.get("actor_id"), self.npc_no_specials.id)


if __name__ == '__main__':
    unittest.main()
