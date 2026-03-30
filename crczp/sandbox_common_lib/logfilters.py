import logging


class SuppressAllocationUnit404(logging.Filter):
    """
    Suppress noisy 404 logs for sandbox-allocation-units detail.

    Training-service and internal cleanup jobs poll allocation units that may already
    have been deleted after cleanup. These 404s are expected and happen every 30s per
    active user; logging them just floods the logs without adding signal.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Django attaches the request and status_code to log records from django.request
        status_code = getattr(record, "status_code", None)
        request = getattr(record, "request", None)
        path = getattr(request, "path", "") if request is not None else ""

        # Suppress 404 for sandbox-allocation-units detail endpoint; keep everything else.
        if status_code == 404 and path.startswith("/sandbox-service/api/v1/sandbox-allocation-units/"):
            return False
        return True

