import unittest
import time
import uuid

# Assuming ActionRequest and GuildActionScheduler are importable
# Adjust import paths if necessary based on your project structure
from bot.game.models.action_request import ActionRequest
from bot.game.action_scheduler import GuildActionScheduler

class TestActionRequest(unittest.TestCase):
    def test_action_request_creation_defaults(self):
        ar = ActionRequest(guild_id="guild1", actor_id="actor1", action_type="TEST_ACTION")
        self.assertIsNotNone(ar.action_id)
        self.assertIsInstance(ar.action_id, str)
        self.assertEqual(ar.guild_id, "guild1")
        self.assertEqual(ar.actor_id, "actor1")
        self.assertEqual(ar.action_type, "TEST_ACTION")
        self.assertEqual(ar.action_data, {})
        self.assertEqual(ar.priority, 10)
        self.assertAlmostEqual(ar.requested_at, time.time(), delta=0.1)
        self.assertAlmostEqual(ar.execute_at, time.time(), delta=0.1)
        self.assertEqual(ar.dependencies, [])
        self.assertEqual(ar.status, "pending")
        self.assertIsNone(ar.result)

    def test_action_request_creation_custom_values(self):
        custom_id = str(uuid.uuid4())
        custom_data = {"key": "value"}
        custom_deps = ["dep1"]
        req_time = time.time() - 10
        exec_time = time.time() + 10

        ar = ActionRequest(
            action_id=custom_id,
            guild_id="guild2",
            actor_id="actor2",
            action_type="CUSTOM_ACTION",
            action_data=custom_data,
            priority=5,
            requested_at=req_time,
            execute_at=exec_time,
            dependencies=custom_deps,
            status="processing",
            result={"done": True}
        )
        self.assertEqual(ar.action_id, custom_id)
        self.assertEqual(ar.guild_id, "guild2")
        self.assertEqual(ar.actor_id, "actor2")
        self.assertEqual(ar.action_type, "CUSTOM_ACTION")
        self.assertEqual(ar.action_data, custom_data)
        self.assertEqual(ar.priority, 5)
        self.assertEqual(ar.requested_at, req_time)
        self.assertEqual(ar.execute_at, exec_time)
        self.assertEqual(ar.dependencies, custom_deps)
        self.assertEqual(ar.status, "processing")
        self.assertEqual(ar.result, {"done": True})

    def test_action_request_sorting(self):
        ar1 = ActionRequest(guild_id="g1", actor_id="a1", action_type="T1", execute_at=time.time() + 100, priority=10)
        ar2 = ActionRequest(guild_id="g1", actor_id="a2", action_type="T2", execute_at=time.time() + 50, priority=10) # Earlier execute_at
        ar3 = ActionRequest(guild_id="g1", actor_id="a3", action_type="T3", execute_at=time.time() + 50, priority=5)  # Same execute_at, higher priority
        ar4 = ActionRequest(guild_id="g1", actor_id="a4", action_type="T4", execute_at=time.time() + 50, priority=5)  # Identical to ar3 for sorting

        actions = [ar1, ar2, ar3, ar4]
        actions.sort() # Uses ActionRequest.__lt__

        self.assertEqual(actions[0].actor_id, ar3.actor_id) # or ar4
        self.assertEqual(actions[1].actor_id, ar4.actor_id) # or ar3
        self.assertEqual(actions[2].actor_id, ar2.actor_id)
        self.assertEqual(actions[3].actor_id, ar1.actor_id)

        # Verify stability or specific order for equal items if important
        # For this test, as long as ar3 and ar4 are before ar2, and ar2 before ar1, it's fine.
        # Python's sort is stable, so if they were added in a specific order and are equal, that order is preserved.
        # Here we check they are the first two.
        self.assertIn(actions[0].actor_id, [ar3.actor_id, ar4.actor_id])
        self.assertIn(actions[1].actor_id, [ar3.actor_id, ar4.actor_id])
        self.assertNotEqual(actions[0].actor_id, actions[1].actor_id)


class TestGuildActionScheduler(unittest.TestCase):
    def setUp(self):
        self.scheduler = GuildActionScheduler()
        self.guild_id1 = "guild1"
        self.guild_id2 = "guild2"

    def test_add_action(self):
        ar = ActionRequest(guild_id=self.guild_id1, actor_id="a1", action_type="T1")
        self.scheduler.add_action(ar)
        self.assertEqual(len(self.scheduler._action_queues[self.guild_id1]), 1)
        self.assertIn(ar.action_id, self.scheduler._action_map[self.guild_id1])
        self.assertEqual(self.scheduler._action_map[self.guild_id1][ar.action_id], ar)

    def test_add_action_multiple_guilds(self):
        ar1 = ActionRequest(guild_id=self.guild_id1, actor_id="a1", action_type="T1")
        ar2 = ActionRequest(guild_id=self.guild_id2, actor_id="a2", action_type="T2")
        self.scheduler.add_action(ar1)
        self.scheduler.add_action(ar2)
        self.assertEqual(len(self.scheduler._action_queues[self.guild_id1]), 1)
        self.assertEqual(len(self.scheduler._action_queues[self.guild_id2]), 1)
        self.assertIsNotNone(self.scheduler.get_action(self.guild_id1, ar1.action_id))
        self.assertIsNotNone(self.scheduler.get_action(self.guild_id2, ar2.action_id))

    def test_get_action(self):
        ar = ActionRequest(guild_id=self.guild_id1, actor_id="a1", action_type="T1")
        self.scheduler.add_action(ar)
        retrieved_ar = self.scheduler.get_action(self.guild_id1, ar.action_id)
        self.assertEqual(retrieved_ar, ar)
        self.assertIsNone(self.scheduler.get_action(self.guild_id1, "nonexistent_id"))
        self.assertIsNone(self.scheduler.get_action(self.guild_id2, ar.action_id)) # Wrong guild

    def test_update_action_status(self):
        ar = ActionRequest(guild_id=self.guild_id1, actor_id="a1", action_type="T1")
        self.scheduler.add_action(ar)

        res_data = {"detail": "completed successfully"}
        updated = self.scheduler.update_action_status(self.guild_id1, ar.action_id, "completed", res_data)
        self.assertTrue(updated)

        updated_ar = self.scheduler.get_action(self.guild_id1, ar.action_id)
        self.assertEqual(updated_ar.status, "completed")
        self.assertEqual(updated_ar.result, res_data)

        not_updated = self.scheduler.update_action_status(self.guild_id1, "nonexistent", "failed")
        self.assertFalse(not_updated)

    def test_get_ready_actions_simple_time(self):
        ar_past = ActionRequest(guild_id=self.guild_id1, actor_id="a1", action_type="T_PAST", execute_at=time.time() - 1)
        ar_future = ActionRequest(guild_id=self.guild_id1, actor_id="a2", action_type="T_FUTURE", execute_at=time.time() + 100)
        self.scheduler.add_action(ar_past)
        self.scheduler.add_action(ar_future)

        ready_actions = self.scheduler.get_ready_actions(self.guild_id1)
        self.assertEqual(len(ready_actions), 1)
        self.assertEqual(ready_actions[0].action_id, ar_past.action_id)

        # Ensure future action is still in queue
        self.assertEqual(len(self.scheduler._action_queues[self.guild_id1]), 1)
        self.assertEqual(self.scheduler._action_queues[self.guild_id1][0].action_id, ar_future.action_id)


    def test_get_ready_actions_dependencies(self):
        dep_action = ActionRequest(guild_id=self.guild_id1, actor_id="dep_actor", action_type="DEP_ACTION", execute_at=time.time() - 2)
        main_action = ActionRequest(guild_id=self.guild_id1, actor_id="main_actor", action_type="MAIN_ACTION",
                                    execute_at=time.time() -1 , dependencies=[dep_action.action_id])

        self.scheduler.add_action(dep_action)
        self.scheduler.add_action(main_action)

        # Dependency not completed yet
        ready_actions = self.scheduler.get_ready_actions(self.guild_id1)
        self.assertEqual(len(ready_actions), 1) # Only dep_action should be ready
        self.assertEqual(ready_actions[0].action_id, dep_action.action_id)

        # Mark dependency as completed
        self.scheduler.update_action_status(self.guild_id1, dep_action.action_id, "completed")

        # Now try to get ready actions again
        # First, process the completed dep_action from the queue (get_ready_actions removes it)
        # In a real loop, dep_action would be processed and removed. Here we simulate that.
        # For this test, let's assume the first get_ready_actions call effectively processes dep_action.
        # We need to remove it from the map for the next get_ready_actions to work as expected for main_action.
        # A better way to test this might be to call get_ready_actions, then update status, then call again.

        # After dep_action is processed and its status is "completed":
        # We need to ensure the scheduler "sees" the completed status.
        # The current get_ready_actions re-adds non-ready actions. So dep_action is gone from queue if it was ready.
        # Let's re-evaluate ready actions:

        ready_actions_after_dep = self.scheduler.get_ready_actions(self.guild_id1)

        self.assertEqual(len(ready_actions_after_dep), 1)
        self.assertEqual(ready_actions_after_dep[0].action_id, main_action.action_id)

    def test_get_ready_actions_multiple_ready_sorted(self):
        ar1 = ActionRequest(guild_id=self.guild_id1, actor_id="a1", action_type="T1", execute_at=time.time() - 3, priority=20)
        ar2 = ActionRequest(guild_id=self.guild_id1, actor_id="a2", action_type="T2", execute_at=time.time() - 2, priority=10) # Higher priority
        ar3 = ActionRequest(guild_id=self.guild_id1, actor_id="a3", action_type="T3", execute_at=time.time() - 2, priority=10) # Same as ar2

        self.scheduler.add_action(ar1)
        self.scheduler.add_action(ar2)
        self.scheduler.add_action(ar3)

        ready_actions = self.scheduler.get_ready_actions(self.guild_id1)
        self.assertEqual(len(ready_actions), 3)
        self.assertEqual(ready_actions[0].actor_id, ar1.actor_id) # Earliest execute_at

        # ar2 and ar3 have same execute_at and priority, their order depends on insertion with current heap logic
        # or secondary sort criteria if any. ActionRequest.__lt__ sorts by priority if execute_at is same.
        # Since ar2 and ar3 have same priority, their relative order is stable based on insertion into heap if values are equal.
        # However, the test for ActionRequest.__lt__ showed priority is the tie-breaker.
        # The get_ready_actions sorts the final list.
        self.assertIn(ready_actions[1].actor_id, [ar2.actor_id, ar3.actor_id])
        self.assertIn(ready_actions[2].actor_id, [ar2.actor_id, ar3.actor_id])
        self.assertNotEqual(ready_actions[1].actor_id, ready_actions[2].actor_id)


    def test_remove_action(self):
        ar1 = ActionRequest(guild_id=self.guild_id1, actor_id="a1", action_type="T1")
        ar2 = ActionRequest(guild_id=self.guild_id1, actor_id="a2", action_type="T2")
        self.scheduler.add_action(ar1)
        self.scheduler.add_action(ar2)

        self.assertTrue(self.scheduler.remove_action(self.guild_id1, ar1.action_id))
        self.assertIsNone(self.scheduler.get_action(self.guild_id1, ar1.action_id))
        self.assertEqual(len(self.scheduler._action_queues[self.guild_id1]), 1)
        self.assertEqual(self.scheduler._action_queues[self.guild_id1][0].action_id, ar2.action_id)

        self.assertFalse(self.scheduler.remove_action(self.guild_id1, "nonexistent"))
        self.assertFalse(self.scheduler.remove_action(self.guild_id2, ar2.action_id)) # Wrong guild

    def test_get_all_actions_for_guild(self):
        ar1 = ActionRequest(guild_id=self.guild_id1, actor_id="a1", action_type="T1", priority=2)
        ar2 = ActionRequest(guild_id=self.guild_id1, actor_id="a2", action_type="T2", priority=1) # Higher priority
        ar3 = ActionRequest(guild_id=self.guild_id2, actor_id="a3", action_type="T3")

        self.scheduler.add_action(ar1)
        self.scheduler.add_action(ar2)
        self.scheduler.add_action(ar3)

        guild1_actions = self.scheduler.get_all_actions_for_guild(self.guild_id1)
        self.assertEqual(len(guild1_actions), 2)
        self.assertEqual(guild1_actions[0].action_id, ar2.action_id) # Sorted by priority (due to same execute_at)
        self.assertEqual(guild1_actions[1].action_id, ar1.action_id)

        guild2_actions = self.scheduler.get_all_actions_for_guild(self.guild_id2)
        self.assertEqual(len(guild2_actions), 1)
        self.assertEqual(guild2_actions[0].action_id, ar3.action_id)

        self.assertEqual(self.scheduler.get_all_actions_for_guild("nonexistent_guild"), [])

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
