"""Validation helpers for CrczpConfiguration attributes."""

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_ipv4_address

ALLOWED_SCHEMES = ['http', 'https']

# Netbird's setup-key `expires_in` accepts 1 to 365 days, in seconds.
NETBIRD_KEY_EXPIRY_MIN_SECONDS = 86400
NETBIRD_KEY_EXPIRY_MAX_SECONDS = 31536000


def validate_git_rest_url(obj: object, git_rest_server: str) -> bool:
    """Validate that the git REST server URL uses an allowed scheme."""
    validate = URLValidator(schemes=ALLOWED_SCHEMES)

    try:
        validate(git_rest_server)
    except ValidationError:
        _msg = 'Cannot set {}.git_providers server to "{}". Invalid URL. Allowed schemes are: {}.'
        raise ValueError(
            _msg.format(obj.__class__.__name__, git_rest_server, ALLOWED_SCHEMES)
        ) from None

    return True


def validate_head_ip(obj: object, head_ip: str) -> bool:
    """Validate that the head IP is a valid IPv4 address."""
    try:
        validate_ipv4_address(head_ip)
    except ValidationError:
        _msg = 'Cannot set {}.head_ip to "{}". Invalid IP address.'
        raise ValueError(_msg.format(obj.__class__.__name__, head_ip)) from None

    return True


def validate_netbird_key_expiry(obj: object, key_expiry_seconds: int) -> bool:
    """Validate that the Netbird setup-key expiry is within Netbird's accepted range."""
    if not NETBIRD_KEY_EXPIRY_MIN_SECONDS <= key_expiry_seconds <= NETBIRD_KEY_EXPIRY_MAX_SECONDS:
        _msg = (
            'Cannot set {}.key_expiry_seconds to {}. Netbird requires a value between '
            '{} and {} seconds ({} to {} days).'
        )
        raise ValueError(
            _msg.format(
                obj.__class__.__name__,
                key_expiry_seconds,
                NETBIRD_KEY_EXPIRY_MIN_SECONDS,
                NETBIRD_KEY_EXPIRY_MAX_SECONDS,
                NETBIRD_KEY_EXPIRY_MIN_SECONDS // 86400,
                NETBIRD_KEY_EXPIRY_MAX_SECONDS // 86400,
            )
        )

    return True
