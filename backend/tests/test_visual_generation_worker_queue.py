import unittest
from unittest.mock import patch

from app.modules.visual_generation import worker


class VisualGenerationWorkerQueueTest(unittest.TestCase):
    def test_drain_dispatches_multiple_jobs_without_waiting_for_each_job_to_finish(self):
        jobs = [
            {"taskId": "visual-1", "userId": "user-1"},
            {"taskId": "visual-2", "userId": "user-1"},
            {"taskId": "visual-3", "userId": "user-1"},
        ]
        dispatched: list[dict] = []

        def pop_job():
            return jobs.pop(0) if jobs else None

        def capture_dispatch(job):
            dispatched.append(job)
            return None

        with patch("app.modules.visual_generation.worker.acquire_worker_lock", return_value=(True, "lock-token")):
            with patch("app.modules.visual_generation.worker.release_worker_lock") as release_lock:
                with patch("app.modules.visual_generation.worker.pop_visual_job", side_effect=pop_job):
                    with patch("app.modules.visual_generation.worker.promote_due_deferred_jobs", return_value=0):
                        with patch("app.modules.visual_generation.worker.promote_due_retry_jobs", return_value=0):
                            with patch("app.modules.visual_generation.worker.count_running_visual_tasks_global", return_value=1):
                                with patch("app.modules.visual_generation.worker.start_visual_job_thread", side_effect=capture_dispatch):
                                    result = worker.run_visual_queue_drain(max_jobs=5)

        self.assertEqual(result["processed"], 3)
        self.assertEqual([job["taskId"] for job in dispatched], ["visual-1", "visual-2", "visual-3"])
        release_lock.assert_called_once_with("lock-token")


if __name__ == "__main__":
    unittest.main()
