import time
import structlog
from redis import Redis
from rq.exceptions import NoSuchJobError
from rq.job import Job

LOG = structlog.get_logger()


def lock_job(job: Job, timeout=60, step=5) -> None:
    stage = job.kwargs.get('stage')
    elapsed = 0

    while elapsed <= timeout:
        job.refresh()
        locked = job.meta.get('locked', True)
        if not locked:
            LOG.debug('Stage unlocked.', stage=stage)
            break
        else:
            LOG.debug('Wait until the stage is unlocked.', stage=stage)
            time.sleep(step)
            elapsed += step


def unlock_job(job: Job) -> None:
    stage = job.kwargs.get('stage')
    if job.meta.get('locked', True):
        LOG.debug('Unlocking stage.', stage=stage)
    job.meta['locked'] = False
    job.save_meta()


def delete_job(job_id: str) -> None:
    try:
        Job.fetch(job_id, connection=Redis()).delete(delete_dependents=True)
    except NoSuchJobError:  # Job already deleted
        pass
