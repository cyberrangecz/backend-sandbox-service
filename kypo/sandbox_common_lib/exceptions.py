"""
Module containing exceptions.
All exceptions inherit from the ApiException class.
"""


class ApiException(Exception):
    """
    Base exception class for this project.
    All other exceptions inherit form it.
    """
    pass


class DockerError(ApiException):
    """
    Raised when there is a problem with Docker container.
    """
    pass


class ValidationError(ApiException):
    """
    Raised when request contains invalid values.
    """
    pass


class LimitExceededError(ApiException):
    """
    Raised when internally set limits are exceeded, eg. count of Ansible outputs.
    """
    pass


class NetworkError(ApiException):
    """
    Raised when call to external services fails.
    """
    pass


class GitError(ApiException):
    """
    For Git related errors.
    """
    pass


class StackError(ApiException):
    """
    Raised when application was not configured properly.
    """
    pass


class AnsibleError(ApiException):
    """
    Raised when there is some error during Ansible.
    """
    pass


class InterruptError(ApiException):
    """
    Raised when there is need to interrupt some action because of unspecified error.
    """
    pass


class ImproperlyConfigured(ApiException):
    """
    Raised when application was not configured properly.
    """
    pass


class EmailException(ApiException):
    """
    Raised when email notifications are not sent successfully.
    """
