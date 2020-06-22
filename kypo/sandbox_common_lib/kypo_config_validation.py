from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

ALLOWED_SCHEMES = ['http', 'https']


def validate_git_rest_url(obj, git_rest_server) -> bool:
    validate = URLValidator(schemes=ALLOWED_SCHEMES)

    try:
        validate(git_rest_server)
    except ValidationError:
        _msg = 'Cannot set {}.git_rest_server to "{}". Invalid URL. Allowed schemes are: {}.'
        raise ValueError(_msg.format(obj.__class__.__name__, git_rest_server, ALLOWED_SCHEMES))

    return True
