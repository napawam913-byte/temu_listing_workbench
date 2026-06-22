import unittest
from unittest.mock import patch

from app.modules.visual_generation import worker
from app.modules.visual_generation.service import VisualTaskCancelled


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

    def test_deleted_job_is_skipped_before_reserving_run_slot(self):
        job = {"taskId": "visual-removed", "userId": "user-1", "jobId": "job-1"}

        with patch(
            "app.modules.visual_generation.worker.assert_visual_task_not_cancelled",
            side_effect=VisualTaskCancelled("visual task was removed"),
        ):
            with patch("app.modules.visual_generation.worker.reserve_visual_run_slot") as reserve_slot:
                with patch("app.modules.visual_generation.worker.run_visual_task_pipeline") as run_pipeline:
                    with patch("app.modules.visual_generation.worker.set_visual_progress") as set_progress:
                        worker.run_visual_job(job)

        reserve_slot.assert_not_called()
        run_pipeline.assert_not_called()
        set_progress.assert_called_once()
        self.assertEqual(set_progress.call_args.args[1]["state"], "cancelled")

    def test_running_job_deleted_after_failure_does_not_retry_or_mark_failed(self):
        job = {"taskId": "visual-removed", "userId": "user-1", "jobId": "job-1"}

        with patch(
            "app.modules.visual_generation.worker.assert_visual_task_not_cancelled",
            side_effect=[None, VisualTaskCancelled("visual task was removed")],
        ):
            with patch("app.modules.visual_generation.worker.reserve_visual_run_slot", return_value=(True, "")):
                with patch("app.modules.visual_generation.worker.run_visual_task_pipeline", side_effect=RuntimeError("late failure")):
                    with patch("app.modules.visual_generation.worker.mark_task_retry_waiting") as mark_retry:
                        with patch("app.modules.visual_generation.worker.enqueue_visual_retry") as enqueue_retry:
                            with patch("app.modules.visual_generation.worker.mark_task_failed") as mark_failed:
                                with patch("app.modules.visual_generation.worker.enqueue_visual_dead") as enqueue_dead:
                                    with patch("app.modules.visual_generation.worker.set_visual_progress") as set_progress:
                                        worker.run_visual_job(job)

        mark_retry.assert_not_called()
        enqueue_retry.assert_not_called()
        mark_failed.assert_not_called()
        enqueue_dead.assert_not_called()
        set_progress.assert_called_once()
        self.assertEqual(set_progress.call_args.args[1]["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()
