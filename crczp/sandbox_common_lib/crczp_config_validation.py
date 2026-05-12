"""Validation helpers for CrczpConfiguration attributes."""

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_ipv4_address

ALLOWED_SCHEMES = ['http', 'https']


def validate_git_rest_url(obj, git_rest_server) -> bool:
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


def validate_head_ip(obj, head_ip):
    """Validate that the head IP is a valid IPv4 address."""
    try:
        validate_ipv4_address(head_ip)
    except ValidationError:
        _msg = 'Cannot set {}.head_ip to "{}". Invalid IP address.'
        raise ValueError(_msg.format(obj.__class__.__name__, head_ip)) from None

    return True
