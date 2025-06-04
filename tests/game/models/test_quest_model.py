import unittest
import json
from bot.game.models.quest import Quest

class TestQuestModel(unittest.TestCase):

    def test_quest_serialization_deserialization_standard(self):
        """Test Quest model for a standard quest."""
        original_data = {
            "id": "quest_std_1",
            "name_i18n": {"en": "The King's Request", "ru": "Запрос Короля"},
            "description_i18n": {"en": "A request from the King himself.", "ru": "Запрос от самого Короля."},
            "status": "available",
            "influence_level": "kingdom",
            "prerequisites": ["main_story_arc_part1_complete"],
            "connections": {"next_quest": ["quest_std_2"]},
            "stages": {
                "stage1": {
                    "title_i18n": {"en": "Speak to the Chamberlain", "ru": "Поговорить с Камергером"},
                    "description_i18n": {"en": "The Chamberlain has details.", "ru": "Камергер знает детали."},
                    "objective_type": "talk_to_npc",
                    "target": "npc_chamberlain_id"
                }
            },
            "rewards": {"xp": 1000, "gold": 500, "items": ["royal_seal_id"]},
            "npc_involvement": {"giver": "npc_king_id", "key_npc": "npc_chamberlain_id"},
            "guild_id": "g1",
            "quest_giver_details_i18n": {"en": "King Theodore", "ru": "Король Теодор"},
            "consequences_summary_i18n": {"en": "Increased royal faction standing.", "ru": "Повышение репутации с королевской фракцией."},
            "is_ai_generated": False
        }

        quest = Quest.from_dict(original_data)

        self.assertEqual(quest.id, original_data["id"])
        self.assertEqual(quest.name_i18n, original_data["name_i18n"])
        self.assertEqual(quest.name, "The King's Request") # Derived, 'en' default
        self.assertEqual(quest.description_i18n, original_data["description_i18n"])
        self.assertEqual(quest.status, original_data["status"])
        self.assertEqual(quest.prerequisites, original_data["prerequisites"])
        self.assertEqual(quest.stages["stage1"]["title_i18n"], original_data["stages"]["stage1"]["title_i18n"])
        self.assertEqual(quest.rewards, original_data["rewards"])
        self.assertEqual(quest.is_ai_generated, False)
        self.assertIsNone(quest.stages_json_str) # Should be None if stages were parsed

        quest_dict = quest.to_dict()
        for key in original_data:
            if key == "name": continue # Not in original_data for to_dict comparison
            self.assertEqual(quest_dict[key], original_data[key], f"Mismatch for key: {key}")
        self.assertEqual(set(original_data.keys()), set(k for k in quest_dict.keys() if k in original_data))


    def test_quest_serialization_deserialization_ai_generated(self):
        """Test Quest model for an AI-generated quest, using *_json_str fields."""
        stages_list_for_ai = [
            {"id": "s1", "title_i18n": {"en": "Gather Herbs"}, "description_i18n": {"en": "Collect 5 Sunpetals."}}
        ]
        rewards_dict_for_ai = {"xp": 150, "item_ids": ["healing_potion_id"]}

        original_data = {
            "id": "quest_ai_1",
            "title_i18n": {"en": "Herbal Remedy", "ru": "Травяное Лекарство"}, # from generated_quests table
            "description_i18n": {"en": "A local healer needs rare herbs.", "ru": "Местному лекарю нужны редкие травы."},
            "status": "pending_approval",
            "influence_level": "village", # maps to suggested_level later
            "guild_id": "g2",
            "is_ai_generated": True,
            # JSON string fields as they might come from DB for generated_quests
            "stages_json_str": json.dumps(stages_list_for_ai),
            "rewards_json_str": json.dumps(rewards_dict_for_ai),
            "prerequisites_json_str": json.dumps([{"condition_type": "level", "min_level": 3}]),
            "consequences_json_str": json.dumps({"on_complete": [{"type": "faction_rep_change"}]}),
            "ai_prompt_context_json_str": json.dumps({"original_idea": "fetch quest for healer"}),
            # Other fields that might be empty or have defaults
            "prerequisites": None, # Will be populated by manager from _json_str
            "connections": {},
            "stages": None, # Will be populated by manager
            "rewards": None, # Will be populated by manager
            "npc_involvement": {},
            "quest_giver_details_i18n": {},
            "consequences_summary_i18n": {},
            "consequences": {} # Will be populated by manager
        }

        quest = Quest.from_dict(original_data)

        self.assertEqual(quest.id, original_data["id"])
        self.assertEqual(quest.name_i18n, original_data["title_i18n"]) # Check mapping
        self.assertEqual(quest.name, "Herbal Remedy")
        self.assertEqual(quest.is_ai_generated, True)

        self.assertEqual(quest.stages_json_str, original_data["stages_json_str"])
        self.assertEqual(quest.rewards_json_str, original_data["rewards_json_str"])
        self.assertEqual(quest.prerequisites_json_str, original_data["prerequisites_json_str"])
        self.assertEqual(quest.consequences_json_str, original_data["consequences_json_str"])
        self.assertEqual(quest.ai_prompt_context_json_str, original_data["ai_prompt_context_json_str"])

        # Test that direct attributes are None initially if only _json_str was provided
        self.assertIsNone(quest.stages) # from_dict doesn't auto-parse these _json_str fields
        self.assertIsNone(quest.rewards)
        self.assertIsNone(quest.prerequisites)
        # self.assertEqual(quest.consequences, {}) # consequences is initialized to {}

        quest_dict = quest.to_dict()
        for key in original_data:
            self.assertEqual(quest_dict[key], original_data[key], f"Mismatch for key: {key}")

        # Test manual parsing (simulate what manager would do)
        if quest.stages_json_str:
            quest.stages = json.loads(quest.stages_json_str)
        if quest.rewards_json_str:
            quest.rewards = json.loads(quest.rewards_json_str)

        self.assertEqual(quest.stages, stages_list_for_ai)
        self.assertEqual(quest.rewards, rewards_dict_for_ai)


    def test_quest_stages_i18n_processing(self):
        """Test the internal i18n processing of stages in __init__."""
        quest_data_with_plain_stages = {
            "id": "q_stages",
            "name_i18n": {"en": "Stage Test"},
            "guild_id": "g1",
            "stages": {
                "s1": {"title": "Stage 1 Title", "description": "Stage 1 Desc"},
                "s2": {"title_i18n": {"en": "S2 Title EN"}, "description_i18n": {"en": "S2 Desc EN"}},
                "s3": {"title": "S3 Title Mixed", "description_i18n": {"en": "S3 Desc EN From i18n"}}
            }
        }
        quest = Quest.from_dict(quest_data_with_plain_stages)

        self.assertEqual(quest.stages["s1"]["title_i18n"], {"en": "Stage 1 Title", "ru": "Stage 1 Title"})
        self.assertEqual(quest.stages["s1"]["description_i18n"], {"en": "Stage 1 Desc", "ru": "Stage 1 Desc"})
        self.assertNotIn("title", quest.stages["s1"]) # Old key should be removed

        self.assertEqual(quest.stages["s2"]["title_i18n"], {"en": "S2 Title EN"})

        self.assertEqual(quest.stages["s3"]["title_i18n"], {"en": "S3 Title Mixed", "ru": "S3 Title Mixed"})
        self.assertEqual(quest.stages["s3"]["description_i18n"], {"en": "S3 Desc EN From i18n"})


if __name__ == '__main__':
    unittest.main()
