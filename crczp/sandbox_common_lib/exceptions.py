"""
Module containing exceptions.
All exceptions inherit from the ApiException class.
"""


class ApiException(Exception):
    """
    Base exception class for this project.
    All other exceptions inherit form it.
    """


class DockerError(ApiException):
    """
    Raised when there is a problem with Docker container.
    """


class ValidationError(ApiException):
    """
    Raised when request contains invalid values.
    """


class LimitExceededError(ApiException):
    """
    Raised when internally set limits are exceeded, eg. count of Ansible outputs.
    """


class NetworkError(ApiException):
    """
    Raised when call to external services fails.
    """


class GitError(ApiException):
    """
    For Git related errors.
    """


class StackError(ApiException):
    """
    Raised when application was not configured properly.
    """


class AnsibleError(ApiException):
    """
    Raised when there is some error during Ansible.
    """


class InterruptError(ApiException):
    """
    Raised when there is need to interrupt some action because of unspecified error.
    """


class ImproperlyConfigured(ApiException):
    """
    Raised when application was not configured properly.
    """


class EmailException(ApiException):
    """
    Raised when email notifications are not sent successfully.
    """
