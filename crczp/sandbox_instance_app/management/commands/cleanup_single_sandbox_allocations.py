"""
Cleanup single-sandbox (trainee-allocated) sandboxes in pools linked to non-managed training instances.

Runs when SINGLE_SANDBOX_CLEANUP_ENABLED is true. Fetches pool IDs from training-service
(non-managed only), then for each pool removes trainee-allocated allocation units older than
SINGLE_SANDBOX_CLEANUP_AGE_HOURS. Optionally waits 60s and retries failed cleanups once.
"""

import os
import time
from datetime import timedelta

import requests
import structlog
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from crczp.sandbox_instance_app.lib import requests as sandbox_requests
from crczp.sandbox_instance_app.models import SandboxAllocationUnit

LOG = structlog.get_logger()

HEADER_INTERNAL_SECRET = "X-Internal-Secret"
TRAINING_POOL_IDS_PATH = "/training-instances/internal/single-sandbox-cleanup-pool-ids"
DEFAULT_AGE_HOURS = 24
RETRY_WAIT_SECONDS = 60
REQUEST_TIMEOUT = 10


class Command(BaseCommand):
    help = (
        "Cleanup trainee-allocated (single-sandbox) allocation units in pools linked to "
        "non-managed training instances. Uses config training_service_api (default: http://training-service:8083/training/api/v1)."
    )
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only log what would be cleaned, do not create cleanup requests.",
        )

    def handle(self, *args, **options):
        # So each interval run is visible in container logs (background job shares stdout)
        LOG.info("single_sandbox_cleanup_run_started", msg="Cleanup job run started (interval or manual).")
        self.stdout.write("Single-sandbox cleanup job: run started.")

        if not self._is_enabled():
            LOG.info("single_sandbox_cleanup_disabled", msg="Cleanup not enabled, exiting.")
            return

        training_url = getattr(settings.CRCZP_CONFIG, "training_service_api", "").strip() or "http://training-service:8083/training/api/v1"
        pool_ids, _ = self._fetch_pool_ids(training_url, options["dry_run"])
        if pool_ids is None:
            return
        if not pool_ids:
            LOG.info("single_sandbox_cleanup_no_pools", msg="No non-managed pools from training-service, nothing to clean.")
            self.stdout.write("Single-sandbox cleanup: no non-managed pools in scope, skipping.")
            return

        age_hours = self._get_age_hours()
        cutoff = timezone.now() - timedelta(hours=age_hours)
        retry_failed = self._retry_failed_enabled()

        LOG.info(
            "single_sandbox_cleanup_start",
            pool_ids=pool_ids,
            pool_count=len(pool_ids),
            age_hours=age_hours,
            cutoff_iso=cutoff.isoformat(),
            dry_run=options["dry_run"],
        )
        self.stdout.write(
            f"Single-sandbox cleanup: starting (pools={len(pool_ids)}, age_hours={age_hours}, "
            f"cutoff={cutoff.isoformat()})"
        )

        cleaned = self._cleanup_units(pool_ids, cutoff, options["dry_run"])
        if options["dry_run"]:
            LOG.info("single_sandbox_cleanup_dry_run", would_clean=cleaned)
            self.stdout.write(f"Single-sandbox cleanup (dry-run): would clean {cleaned} allocation unit(s)")
            return

        retried = 0
        if cleaned > 0:
            LOG.info("single_sandbox_cleanup_finished", cleaned_count=cleaned)
            self.stdout.write(self.style.SUCCESS(f"Single-sandbox cleanup: cleaned {cleaned} allocation unit(s)"))

        if retry_failed and cleaned > 0:
            self.stdout.write(f"Single-sandbox cleanup: waiting {RETRY_WAIT_SECONDS}s before checking failed cleanups...")
            time.sleep(RETRY_WAIT_SECONDS)
            retried = self._retry_failed_cleanups(pool_ids)
            LOG.info("single_sandbox_cleanup_retry", retried_count=retried)
            if retried > 0:
                self.stdout.write(self.style.SUCCESS(f"Single-sandbox cleanup: retried {retried} failed cleanup(s)"))
            else:
                self.stdout.write("Single-sandbox cleanup: no failed cleanups to retry")

        if cleaned == 0 and (not retry_failed or retried == 0):
            self.stdout.write("Single-sandbox cleanup: no units to clean (run complete)")

    def _is_enabled(self):
        val = os.environ.get("SINGLE_SANDBOX_CLEANUP_ENABLED", "").strip().lower()
        return val in ("1", "true", "yes")

    def _get_age_hours(self):
        try:
            return int(os.environ.get("SINGLE_SANDBOX_CLEANUP_AGE_HOURS", DEFAULT_AGE_HOURS))
        except ValueError:
            return DEFAULT_AGE_HOURS

    def _retry_failed_enabled(self):
        val = os.environ.get("SINGLE_SANDBOX_CLEANUP_RETRY_FAILED", "true").strip().lower()
        return val in ("1", "true", "yes")

    def _fetch_pool_ids(self, base_url, dry_run):
        """Fetch pool IDs from training service. Returns (list or None, connection_failed: bool)."""
        url = base_url.rstrip("/") + TRAINING_POOL_IDS_PATH
        secret = (os.environ.get("TRAINING_INTERNAL_SECRET") or "").strip()
        headers = {}
        if secret:
            headers[HEADER_INTERNAL_SECRET] = secret

        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 403:
                LOG.warning("training_forbidden", msg="Training service returned 403 (internal secret mismatch or not allowed).")
                return None, False
            resp.raise_for_status()
            return resp.json(), False
        except (requests.ConnectionError, requests.Timeout) as e:
            LOG.warning("training_connection_failed", url=url, error=str(e))
            return None, True
        except requests.RequestException as e:
            LOG.warning("training_request_failed", url=url, error=str(e))
            return None, True
        except (ValueError, TypeError) as e:
            LOG.warning("training_response_invalid", error=str(e))
            return None, False

    def _trainee_allocated_units_older_than(self, pool_ids, cutoff):
        """Allocation units with created_by_sub set, in given pools, created_at <= cutoff."""
        return SandboxAllocationUnit.objects.filter(
            pool_id__in=pool_ids,
        ).exclude(
            created_by_sub__isnull=True,
        ).exclude(
            created_by_sub="",
        ).filter(
            created_at__lte=cutoff,
        ).select_related("pool").prefetch_related("cleanup_request", "cleanup_request__stages")

    def _has_active_cleanup(self, unit):
        if not hasattr(unit, "cleanup_request"):
            return False
        return not unit.cleanup_request.is_finished

    def _cleanup_units(self, pool_ids, cutoff, dry_run):
        units = self._trainee_allocated_units_older_than(pool_ids, cutoff)
        count = 0
        for unit in units:
            if self._has_active_cleanup(unit):
                continue
            if dry_run:
                LOG.info(
                    "single_sandbox_cleanup_unit_dry_run",
                    unit_id=unit.id,
                    pool_id=unit.pool_id,
                    created_by_sub=unit.created_by_sub,
                    created_at=unit.created_at.isoformat() if unit.created_at else None,
                )
                self.stdout.write(
                    f"  [dry-run] would clean unit_id={unit.id} pool_id={unit.pool_id} "
                    f"created_by_sub={unit.created_by_sub or '(none)'}"
                )
                count += 1
                continue
            try:
                sandbox_requests.create_cleanup_requests([unit], force=True)
                LOG.info(
                    "single_sandbox_cleanup_unit",
                    unit_id=unit.id,
                    pool_id=unit.pool_id,
                    created_by_sub=unit.created_by_sub,
                    created_at=unit.created_at.isoformat() if unit.created_at else None,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Cleaned unit_id={unit.id} pool_id={unit.pool_id} "
                        f"created_by_sub={unit.created_by_sub or '(none)'}"
                    )
                )
                count += 1
            except Exception as e:
                LOG.warning("cleanup_request_failed", unit_id=unit.id, pool_id=unit.pool_id, error=str(e))
                self.stdout.write(self.style.ERROR(f"  Failed to clean unit_id={unit.id}: {e}"))
        return count

    def _retry_failed_cleanups(self, pool_ids):
        """Find trainee-allocated units in pool_ids with failed cleanup request; cancel and retry once."""
        units = self._trainee_allocated_units_older_than(
            pool_ids,
            timezone.now(),  # no age filter for retry
        )
        retried = 0
        for unit in units:
            if not hasattr(unit, "cleanup_request"):
                continue
            cleanup = unit.cleanup_request
            if not getattr(cleanup, "is_failed", False):
                continue
            try:
                sandbox_requests.cancel_cleanup_request(cleanup)
                sandbox_requests.create_cleanup_requests([unit], force=True)
                LOG.info("single_sandbox_cleanup_retry_unit", unit_id=unit.id, pool_id=unit.pool_id)
                self.stdout.write(
                    self.style.SUCCESS(f"  Retried cleanup for unit_id={unit.id} pool_id={unit.pool_id}")
                )
                retried += 1
            except Exception as e:
                LOG.warning("retry_cleanup_failed", unit_id=unit.id, pool_id=unit.pool_id, error=str(e))
                self.stdout.write(self.style.ERROR(f"  Retry failed for unit_id={unit.id}: {e}"))
        return retried
