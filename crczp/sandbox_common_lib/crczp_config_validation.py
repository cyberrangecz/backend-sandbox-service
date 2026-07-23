"""Validation helpers for CrczpConfiguration attributes."""

from ipaddress import IPv4Network

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_ipv4_address

ALLOWED_SCHEMES = ['http', 'https']

# Netbird's setup-key `expires_in` accepts 1 to 365 days, in seconds.
NETBIRD_KEY_EXPIRY_MIN_SECONDS = 86400
NETBIRD_KEY_EXPIRY_MAX_SECONDS = 31536000

# OpenStack Neutron TaaS tunnel encapsulations supported for network-forwarding tap mirrors.
VALID_MIRROR_TYPES = ('gre', 'erspanv1')


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


def validate_hypervisor_cidr(obj: object, hypervisor_cidr: str | None) -> bool:
    """Validate that the hypervisor CIDR, when set, is a valid IPv4 network."""
    if hypervisor_cidr is None:
        return True

    try:
        IPv4Network(hypervisor_cidr, strict=False)
    except ValueError:
        _msg = 'Cannot set {}.hypervisor_cidr to "{}". Not a valid IPv4 CIDR.'
        raise ValueError(_msg.format(obj.__class__.__name__, hypervisor_cidr)) from None

    return True


def validate_mirror_type(obj: object, mirror_type: str) -> bool:
    """Validate that the network-forwarding mirror_type is a supported TaaS encapsulation."""
    if mirror_type not in VALID_MIRROR_TYPES:
        _msg = 'Cannot set {}.mirror_type to "{}". Must be one of {}.'
        raise ValueError(_msg.format(obj.__class__.__name__, mirror_type, list(VALID_MIRROR_TYPES)))

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
