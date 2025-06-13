import pytest
import asyncio # If RelationshipManager methods are async
from typing import Dict, Any, List, Optional

# Mock objects / Stubs
class MockDBService:
    # Mock DB methods if RelationshipManager interacts with DB directly during update_relationship
    # For this test, we might not need complex DB mocking if we focus on cache changes
    pass

class MockRuleEngine:
    def __init__(self, rules_data: Dict[str, Any]):
        self._rules_data = rules_data

class MockGameLogManager:
    def __init__(self):
        self.log_entries: List[Dict[str, Any]] = []

    async def log_event(self, guild_id: str, event_name: str, data: Dict[str, Any]):
        self.log_entries.append({
            "guild_id": guild_id,
            "event_name": event_name,
            "data": data
        })
        print(f"MockGameLogManager: Logged event {event_name} for guild {guild_id} with data {data}")


# Actual classes to test (or minimal versions if too complex to instantiate fully)
from bot.game.models.relationship import Relationship
from bot.game.managers.relationship_manager import RelationshipManager
# Import schemas for rule data structure (optional, but good for reference)
# from bot.ai.rules_schema import RelationChangeRule, RelationChangeInstruction


# Sample rule data (mirroring data/relationship_rules_config.json)
SAMPLE_RULES_CONFIG = {
  "relation_rules": [
    {
      "name": "QuestCompletedWithNpcPositive_Test",
      "event_type": "quest_completed_test", # Use a distinct event_type for testing
      "condition": "event_data.get('npc_id') is not None and event_data.get('outcome') == 'success'",
      "changes": [
        {
          "entity1_ref": "player_id",
          "entity1_type_ref": "player_type",
          "entity2_ref": "npc_id",
          "entity2_type_ref": "npc_type",
          "relation_type": "friendly",
          "update_type": "add",
          "magnitude_formula": "event_data.get('quest_xp_reward', 50) * 0.1",
          "description": "Player gains friendship with NPC based on quest XP."
        },
        {
          "entity1_ref": "player_id",
          "entity1_type_ref": "player_type",
          "entity2_ref": "faction_id", # Assumes event_data contains faction_id
          "entity2_type_ref": "'faction'", # Explicitly type as faction
          "condition": "event_data.get('faction_id') is not None", # Rule-specific condition
          "relation_type": "reputation",
          "update_type": "add",
          "magnitude_formula": "event_data.get('quest_xp_reward', 50) * 0.05",
          "description": "Player gains reputation with NPC's faction."
        }
      ]
    },
    {
      "name": "PlayerAttacksFactionMember_Test",
      "event_type": "combat_attack_test",
      "condition": "event_data.get('attacker_type') == 'Player' and event_data.get('target_faction_id') is not None",
      "changes": [
        {
          "entity1_ref": "attacker_id",
          "entity1_type_ref": "attacker_type",
          "entity2_ref": "target_faction_id",
          "entity2_type_ref": "'faction'",
          "relation_type": "hostile",
          "update_type": "add",
          "magnitude_formula": "15 + current_strength", # Test current_strength usage
          "description": "Player's faction standing worsens."
        }
      ]
    }
  ],
  "relationship_influence_rules": [] # Not tested in this file
}

@pytest.fixture
def mock_db_service() -> MockDBService:
    return MockDBService()

@pytest.fixture
def mock_rule_engine() -> MockRuleEngine:
    return MockRuleEngine(rules_data=SAMPLE_RULES_CONFIG) # Load sample rules

@pytest.fixture
def mock_game_log_manager() -> MockGameLogManager:
    return MockGameLogManager()

@pytest.fixture
def relationship_manager(mock_db_service: MockDBService, mock_rule_engine: MockRuleEngine) -> RelationshipManager:
    # Initialize RelationshipManager with mocks.
    # No character_manager or other complex dependencies needed if focusing on update_relationship's direct logic.
    manager = RelationshipManager(db_service=mock_db_service, rule_engine=mock_rule_engine)
    # Pre-populate cache if needed for 'current_strength' tests, or rely on create_or_update_relationship
    return manager

# --- Test Cases ---

@pytest.mark.asyncio
async def test_update_relationship_quest_success_new_relationship(
    relationship_manager: RelationshipManager,
    mock_rule_engine: MockRuleEngine, # Used to access its _rules_data
    mock_game_log_manager: MockGameLogManager
):
    guild_id = "test_guild_1"
    player_id = "player_A"
    npc_id = "npc_X"
    faction_id = "faction_Z"
    event_data = {
        "player_id": player_id,
        "player_type": "Player",
        "npc_id": npc_id,
        "npc_type": "NPC",
        "faction_id": faction_id,
        # "faction_type": "Faction", # Not needed due to rule using literal 'faction'
        "outcome": "success",
        "quest_xp_reward": 100
    }

    updated_rels = await relationship_manager.update_relationship(
        guild_id=guild_id,
        event_type="quest_completed_test",
        rule_engine=mock_rule_engine, # Pass the mock rule engine
        game_log_manager=mock_game_log_manager,
        **event_data
    )

    assert len(updated_rels) == 2

    # Player-NPC relationship
    # Check cache for the relationship
    # Note: RelationshipManager sorts entity IDs, so player_id might be entity1 or entity2

    # Find Player-NPC relationship (friendly)
    rel_player_npc_list = [
        r for r in relationship_manager._relationships.get(guild_id, {}).values()
        if ((r.entity1_id == player_id and r.entity2_id == npc_id) or \
            (r.entity1_id == npc_id and r.entity2_id == player_id)) and \
           r.relationship_type == "friendly"
    ]
    assert len(rel_player_npc_list) == 1
    rel_player_npc = rel_player_npc_list[0]

    assert rel_player_npc is not None
    assert rel_player_npc.relationship_type == "friendly"
    assert rel_player_npc.strength == pytest.approx(100 * 0.1) # 10

    # Player-Faction relationship (reputation)
    rel_player_faction_list = [
        r for r in relationship_manager._relationships.get(guild_id, {}).values()
        if r.relationship_type == "reputation" and \
           ( (r.entity1_id == player_id and r.entity1_type == "Player" and r.entity2_id == faction_id and r.entity2_type == "faction") or \
             (r.entity1_id == faction_id and r.entity1_type == "faction" and r.entity2_id == player_id and r.entity2_type == "Player") )
    ]
    assert len(rel_player_faction_list) == 1
    rel_player_faction = rel_player_faction_list[0]

    assert rel_player_faction is not None
    # Ensure we assert on the correct entity's strength if player_id became entity2_id
    # The strength itself is what matters, and it's associated with the pair.
    assert rel_player_faction.relationship_type == "reputation"
    assert rel_player_faction.strength == pytest.approx(100 * 0.05) # 5

    assert len(mock_game_log_manager.log_entries) == 2
    # Order of log entries might vary if changes are processed in parallel or order is not guaranteed
    log_messages = [log["data"]["message"] for log in mock_game_log_manager.log_entries]
    assert any(f"Relationship between Player {player_id} and NPC {npc_id} changed" in msg for msg in log_messages)
    assert any(f"Relationship between Player {player_id} and faction {faction_id} changed" in msg for msg in log_messages)


@pytest.mark.asyncio
async def test_update_relationship_attack_existing_relationship_uses_current_strength(
    relationship_manager: RelationshipManager,
    mock_rule_engine: MockRuleEngine,
    mock_game_log_manager: MockGameLogManager
):
    guild_id = "test_guild_2"
    attacker_id = "player_B" # This will be entity1_id due to sorting with faction_Y
    target_faction_id = "faction_Y"
    initial_hostility_strength = -10.0

    # Pre-establish an initial hostile relationship
    # Ensure entity1_id < entity2_id for consistent key in cache if manager sorts them this way upon creation.
    # Here, "player_B" < "faction_Y" is not guaranteed. RelationshipManager handles sorting.
    await relationship_manager.create_or_update_relationship(
        guild_id=guild_id,
        entity1_id=attacker_id,
        entity1_type="Player",
        entity2_id=target_faction_id,
        entity2_type="faction",
        relationship_type="hostile",
        strength=initial_hostility_strength
    )

    event_data = {
        "attacker_id": attacker_id,
        "attacker_type": "Player",
        "target_id": "some_npc_in_faction_Y",
        "target_type": "NPC",
        "target_faction_id": target_faction_id,
        "damage_done": 25
    }

    updated_rels = await relationship_manager.update_relationship(
        guild_id=guild_id,
        event_type="combat_attack_test",
        rule_engine=mock_rule_engine,
        game_log_manager=mock_game_log_manager,
        **event_data
    )
    assert len(updated_rels) == 1
    updated_rel = updated_rels[0]

    # Verify that entity IDs in the relationship object are sorted as expected by RelationshipManager
    expected_e1_id, expected_e2_id = sorted((attacker_id, target_faction_id))
    assert updated_rel.entity1_id == expected_e1_id
    assert updated_rel.entity2_id == expected_e2_id

    assert updated_rel.relationship_type == "hostile"
    # Magnitude formula: "15 + current_strength" -> 15 + (-10.0) = 5.0
    # Update type: "add" -> New strength = old_strength + magnitude = -10.0 + 5.0 = -5.0
    assert updated_rel.strength == pytest.approx(-5.0)

    assert len(mock_game_log_manager.log_entries) == 1
    log_msg = mock_game_log_manager.log_entries[0]["data"]["message"]
    # Check for semantic content rather than exact string match due to entity order
    assert f"{attacker_id}" in log_msg and f"{target_faction_id}" in log_msg
    assert f"Strength: {initial_hostility_strength:.2f} -> -5.00" in log_msg
    assert "Change: 5.00 via add" in log_msg


@pytest.mark.asyncio
async def test_update_relationship_rule_condition_not_met(
    relationship_manager: RelationshipManager,
    mock_rule_engine: MockRuleEngine,
    mock_game_log_manager: MockGameLogManager
):
    guild_id = "test_guild_3"
    event_data_fail_condition = {
        "player_id": "player_C", "player_type": "Player",
        "npc_id": "npc_Z", "npc_type": "NPC",
        "outcome": "failure", # This will fail the condition in "QuestCompletedWithNpcPositive_Test"
        "quest_xp_reward": 100
    }

    updated_rels = await relationship_manager.update_relationship(
        guild_id=guild_id,
        event_type="quest_completed_test",
        rule_engine=mock_rule_engine,
        game_log_manager=mock_game_log_manager,
        **event_data_fail_condition
    )
    assert len(updated_rels) == 0
    assert len(mock_game_log_manager.log_entries) == 0

@pytest.mark.asyncio
async def test_update_relationship_no_rules_for_event_type(
    relationship_manager: RelationshipManager,
    mock_rule_engine: MockRuleEngine,
    mock_game_log_manager: MockGameLogManager
):
    guild_id = "test_guild_4"
    event_data = {"player_id": "player_D"}

    updated_rels = await relationship_manager.update_relationship(
        guild_id=guild_id,
        event_type="some_unhandled_event", # No rules for this type
        rule_engine=mock_rule_engine,
        game_log_manager=mock_game_log_manager,
        **event_data
    )
    assert len(updated_rels) == 0
    assert len(mock_game_log_manager.log_entries) == 0
