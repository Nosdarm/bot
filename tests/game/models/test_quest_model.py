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
            "steps": [  # Changed from stages (dict) to steps (list)
                {
                    "id": "step1_std", # QuestStep needs an id
                    "title_i18n": {"en": "Speak to the Chamberlain", "ru": "Поговорить с Камергером"},
                    "description_i18n": {"en": "The Chamberlain has details.", "ru": "Камергер знает детали."},
                    "objective_type": "talk_to_npc", # This would be part of abstract_goal_json or similar
                    "target": "npc_chamberlain_id",  # This would be part of abstract_goal_json or similar
                    "step_order": 0,
                    # Add other required fields for QuestStep like required_mechanics_json, abstract_goal_json, consequences_json
                    "required_mechanics_json": "{}",
                    "abstract_goal_json": json.dumps({"type": "talk_to_npc", "target_npc_id": "npc_chamberlain_id"}),
                    "consequences_json": "{}"
                }
            ],
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
        self.assertIsInstance(quest.steps, list)
        self.assertEqual(len(quest.steps), 1)
        self.assertEqual(quest.steps[0].title_i18n, original_data["steps"][0]["title_i18n"])
        self.assertEqual(quest.rewards, original_data["rewards"])
        self.assertEqual(quest.is_ai_generated, False)
        # self.assertIsNone(quest.stages_json_str) # This attribute no longer exists directly

        quest_dict = quest.to_dict()
        # Compare steps separately as they are now objects
        original_steps_data = original_data.pop("steps")
        serialized_steps_data = quest_dict.pop("steps")
        self.assertEqual(len(serialized_steps_data), len(original_steps_data))
        for i, step_dict in enumerate(serialized_steps_data):
            # Compare relevant fields, QuestStep.to_dict() might have more than original_data's step
            self.assertEqual(step_dict["title_i18n"], original_steps_data[i]["title_i18n"])
            self.assertEqual(step_dict["id"], original_steps_data[i]["id"])


        for key in original_data:
            if key == "name": continue
            self.assertEqual(quest_dict[key], original_data[key], f"Mismatch for key: {key}")

        # Add steps back for the set comparison if needed, or adjust comparison
        # For simplicity, will compare keys of original_data (without steps) to quest_dict (without steps)
        original_data_keys_for_set = set(original_data.keys())
        quest_dict_keys_for_set = set(k for k in quest_dict.keys() if k in original_data_keys_for_set) # Only compare common top-level keys
        self.assertEqual(original_data_keys_for_set, quest_dict_keys_for_set)


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
            "steps_json_str": json.dumps(stages_list_for_ai), # Renamed from stages_json_str
            "rewards_json_str": json.dumps(rewards_dict_for_ai),
            "prerequisites_json_str": json.dumps([{"condition_type": "level", "min_level": 3}]),
            "consequences_json_str": json.dumps({"on_complete": [{"type": "faction_rep_change"}]}),
            "ai_prompt_context_json_str": json.dumps({"original_idea": "fetch quest for healer"}),
            # Other fields that might be empty or have defaults
            "prerequisites": None,
            "connections": {},
            "steps": None, # This will be populated by from_dict from steps_json_str
            "rewards": None,
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

        # The _json_str attributes are primarily for input to from_dict if that's the source.
        # The Quest object itself will have parsed these into their respective fields (e.g., quest.steps, quest.rewards).
        # Direct access to _json_str fields on the Quest object might not be intended after initialization.
        # However, to_dict() *does* include them.
        # Let's verify the parsed versions and then the to_dict output.

        self.assertIsInstance(quest.steps, list)
        self.assertEqual(len(quest.steps), 1)
        self.assertEqual(quest.steps[0].title_i18n, stages_list_for_ai[0]["title_i18n"])

        self.assertIsInstance(quest.rewards, dict)
        self.assertEqual(quest.rewards, rewards_dict_for_ai)

        self.assertIsInstance(quest.prerequisites, list) # from_dict parses prerequisites_json_str
        self.assertEqual(quest.prerequisites, [{"condition_type": "level", "min_level": 3}])


        quest_dict_output = quest.to_dict()

        # Check that the _json_str fields in the output dict match the input _json_str fields
        # The original_data used "stages_json_str", but the model uses "steps_json_str" conceptually for this.
        # Quest.from_dict handles "stages_json_str" as a fallback for "steps_json_str".
        # Quest.to_dict() currently does not output a "steps_json_str". It outputs "steps" as a list of dicts.
        # So, we will compare the important ones that are output by to_dict.

        self.assertEqual(quest_dict_output["rewards_json_str"], original_data["rewards_json_str"])
        self.assertEqual(quest_dict_output["prerequisites_json_str"], original_data["prerequisites_json_str"])
        self.assertEqual(quest_dict_output["consequences_json_str"], original_data["consequences_json_str"])
        self.assertEqual(quest_dict_output["ai_prompt_context_json_str"], original_data["ai_prompt_context_json_str"])

        # Compare other relevant fields, excluding those that are parsed objects derived from _json_str
        # unless we reconstruct original_data to match to_dict() structure.
        temp_original_data = original_data.copy()
        temp_original_data["name_i18n"] = temp_original_data.pop("title_i18n") # Adjust for name mapping
        temp_original_data.pop("steps_json_str") # to_dict() outputs 'steps' not 'steps_json_str'
        temp_original_data.pop("steps") # remove None 'steps' from original_data for comparison

        for key in temp_original_data:
            if key not in ["rewards", "prerequisites", "name"]: # These are parsed or properties
                 if key in quest_dict_output: # only compare if key exists in output
                    self.assertEqual(quest_dict_output[key], temp_original_data[key], f"Mismatch for key: {key}")


    def test_quest_stages_i18n_processing(self):
        """Test the internal i18n processing of stages in __init__."""
        quest_data_with_plain_stages = {
            "id": "q_stages",
            "name_i18n": {"en": "Stage Test"},
            "guild_id": "g1",
            "steps": [ # Changed from stages dict to steps list
                {
                    "id": "s1", "step_order": 0,
                    "title": "Stage 1 Title", "description": "Stage 1 Desc", # Plain strings
                    "required_mechanics_json": "{}", "abstract_goal_json": "{}", "consequences_json": "{}"
                },
                {
                    "id": "s2", "step_order": 1,
                    "title_i18n": {"en": "S2 Title EN"},
                    "description_i18n": {"en": "S2 Desc EN"},
                    "required_mechanics_json": "{}", "abstract_goal_json": "{}", "consequences_json": "{}"
                },
                {
                    "id": "s3", "step_order": 2,
                    "title": "S3 Title Mixed", # Plain title
                    "description_i18n": {"en": "S3 Desc EN From i18n"}, # i18n description
                    "required_mechanics_json": "{}", "abstract_goal_json": "{}", "consequences_json": "{}"
                }
            ]
        }
        # Assuming QuestStep.from_dict (called by Quest.from_dict for each step)
        # will handle promoting title/description to title_i18n/description_i18n
        # with default language if only plain string is provided.
        # The Quest.from_dict logic for top-level name/description was:
        # if name_i18n_val is None and "name" in data_copy: name_i18n_val = {"en": data_copy.pop("name")}
        # QuestStep model needs similar logic if this test is to pass as written.
        # For now, let's assume QuestStep.from_dict does this. If not, this test will fail and QuestStep model needs adjustment.

        quest = Quest.from_dict(quest_data_with_plain_stages)

        self.assertEqual(len(quest.steps), 3)
        # Assuming default language 'en' for promotion if QuestStep behaves like Quest for i18n fields
        self.assertEqual(quest.steps[0].title_i18n, {"en": "Stage 1 Title"})
        self.assertEqual(quest.steps[0].description_i18n, {"en": "Stage 1 Desc"})

        self.assertEqual(quest.steps[1].title_i18n, {"en": "S2 Title EN"})
        self.assertEqual(quest.steps[1].description_i18n, {"en": "S2 Desc EN"})

        self.assertEqual(quest.steps[2].title_i18n, {"en": "S3 Title Mixed"})
        self.assertEqual(quest.steps[2].description_i18n, {"en": "S3 Desc EN From i18n"})


if __name__ == '__main__':
    unittest.main()
