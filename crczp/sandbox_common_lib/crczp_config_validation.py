from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_ipv4_address

ALLOWED_SCHEMES = ['http', 'https']


def validate_git_rest_url(obj, git_rest_server) -> bool:
    validate = URLValidator(schemes=ALLOWED_SCHEMES)

    try:
        validate(git_rest_server)
    except ValidationError:
        _msg = 'Cannot set {}.git_providers server to "{}". Invalid URL. Allowed schemes are: {}.'
        raise ValueError(_msg.format(obj.__class__.__name__, git_rest_server, ALLOWED_SCHEMES))

    return True


def validate_head_ip(obj, head_ip):
    try:
        validate_ipv4_address(head_ip)
    except ValidationError:
        _msg = 'Cannot set {}.head_ip to "{}". Invalid IP address.'
        raise ValueError(_msg.format(obj.__class__.__name__, head_ip))

    return True
