import pytest

from kypo.sandbox_instance_app.lib import jobs


class TestLockJob:
    def test_lock_job_success(self, mocker):
        mock_job = mocker.Mock()
        mock_job.meta.get.return_value = False
        jobs.lock_job(mock_job, timeout=1, step=2)
        assert  mock_job.meta.get.called_once()

    def test_lock_job_raies(self, mocker):
        with pytest.raises(TimeoutError):
            jobs.lock_job(mocker.Mock(), timeout=0.01, step=0.02)
