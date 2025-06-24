import unittest
from unittest.mock import MagicMock, AsyncMock, patch, ANY
import json
import uuid # For fallback model ID generation
from typing import Optional, Dict, Any, List, Tuple # Ensure these are imported

from bot.game.managers.relationship_manager import RelationshipManager
try:
    from bot.game.models.relationship import Relationship
except ImportError:
    Relationship = Any # type: ignore

# Fallback model if real Relationship is complex
_RelationshipModel = Relationship
if not hasattr(Relationship, 'model_fields') and not hasattr(Relationship, '__fields__'): # Pydantic v2 and v1 check
    from pydantic import BaseModel, Field
    from typing import Dict as PydanticDict, Optional as PydanticOptional

    class MinimalRelationship(BaseModel):
        id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        guild_id: str
        entity1_id: str
        entity1_type: str
        entity2_id: str
        entity2_type: str
        relationship_type: str = "neutral"
        strength: float = 0.0
        details_i18n: PydanticDict[str, str] = Field(default_factory=dict)
    _RelationshipModel = MinimalRelationship # type: ignore


class TestRelationshipManagerUpdates(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild_id = "rel_mgr_guild"
        self.mock_db_service = AsyncMock()
        self.mock_rule_engine = MagicMock() # Spec RuleEngine if available
        self.mock_game_log_manager = AsyncMock() # Spec GameLogManager if available

        # RelationshipManager's __init__ also takes character_manager, but it's optional
        # and not directly used by update_relationship if entity refs are IDs.
        self.relationship_manager = RelationshipManager(
            db_service=self.mock_db_service,
            settings={},
            character_manager=None,
            rule_engine=self.mock_rule_engine
        )

    async def test_update_relationship_applies_rule_strength_change(self):
        event_type = "QUEST_SUCCESS"
        player_id = "player1"
        npc_id = "npc_quest_giver"

        event_data = {
            "resolved_player_id": player_id, # Use direct keys for refs
            "resolved_npc_id": npc_id,
            "details": { # Keep details for strength_change eval
                "quest_value": 20
            }
        }

        mock_rules = {
            "relation_rules": [
                {
                    "name": "Quest Success Boosts Trust",
                    "event_type": "QUEST_SUCCESS",
                    "condition": "event_data.get('details', {}).get('quest_value', 0) > 10",
                    "changes": [{
                        "entity1_ref": "resolved_player_id", "entity1_type": "PLAYER", # Changed ref
                        "entity2_ref": "resolved_npc_id", "entity2_type": "NPC",       # Changed ref
                        "relationship_type": "trust",
                        "strength_change": "float(event_data.get('details', {}).get('quest_value', 0)) / 2.0",
                        "details_i18n": {"en": "Completed a significant quest together."}
                    }]
                }
            ]
        }
        self.mock_rule_engine._rules_data = mock_rules

        # Store created/updated relationships by RelationshipManager
        # This mock simulates the behavior of create_or_update_relationship
        # which should add to cache and mark dirty.
        # For this test, we want to verify the relationship object passed to it or returned by it.

        # We will mock the create_or_update_relationship method itself
        mock_created_relationship = _RelationshipModel(
            id=str(uuid.uuid4()), guild_id=self.guild_id,
            entity1_id=player_id, entity1_type="PLAYER", # Assuming player_id < npc_id
            entity2_id=npc_id, entity2_type="NPC",
            relationship_type="trust", strength=10.0, # Expected strength after change
            details_i18n={"en": "Completed a significant quest together."}
        )
        self.relationship_manager.create_or_update_relationship = AsyncMock(return_value=mock_created_relationship)


        updated_rels = await self.relationship_manager.update_relationship(
            self.guild_id, event_type, self.mock_rule_engine, self.mock_game_log_manager, **event_data
        )

        self.assertEqual(len(updated_rels), 1)
        new_rel = updated_rels[0]

        self.assertEqual(new_rel.entity1_id, player_id)
        self.assertEqual(new_rel.entity2_id, npc_id)
        self.assertEqual(new_rel.entity1_type, "PLAYER")
        self.assertEqual(new_rel.entity2_type, "NPC")
        self.assertEqual(new_rel.relationship_type, "trust")
        self.assertEqual(new_rel.strength, 10.0)
        self.assertEqual(new_rel.details_i18n.get("en"), "Completed a significant quest together.")

        self.relationship_manager.create_or_update_relationship.assert_called_once_with(
            guild_id=self.guild_id,
            entity1_id=player_id, entity1_type="PLAYER",
            entity2_id=npc_id, entity2_type="NPC",
            relationship_type="trust",
            strength=10.0, # 0 initial (assumed for new) + 10 change
            details_i18n={"en": "Completed a significant quest together."}
        )


    async def test_update_relationship_no_applicable_rule(self):
        event_data = {"player_id": "p1", "details": {}}
        self.mock_rule_engine._rules_data = {"relation_rules": [{"event_type": "OTHER_EVENT", "changes":[]}]}

        updated_rels = await self.relationship_manager.update_relationship(
            self.guild_id, "THIS_EVENT", self.mock_rule_engine, self.mock_game_log_manager, **event_data
        )
        self.assertEqual(len(updated_rels), 0)

    async def test_update_relationship_condition_not_met(self):
        event_data = {"player_id": "p1", "details": {"quest_value": 5}}
        mock_rules = {
            "relation_rules": [{
                "event_type": "QUEST_SUCCESS",
                "condition": "event_data.get('details', {}).get('quest_value', 0) > 10",
                "changes": [{"entity1_ref": "player_id", "entity1_type": "PLAYER",
                             "entity2_ref": "details.npc_id", "entity2_type": "NPC",
                             "relationship_type": "trust", "strength_change": "+1"}]
            }]
        }
        self.mock_rule_engine._rules_data = mock_rules

        updated_rels = await self.relationship_manager.update_relationship(
            self.guild_id, "QUEST_SUCCESS", self.mock_rule_engine, self.mock_game_log_manager, **event_data
        )
        self.assertEqual(len(updated_rels), 0)

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
