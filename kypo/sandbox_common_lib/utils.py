"""
Simple utils module.
"""
import json
import logging
import uuid
import jinja2
from typing import Tuple, Union, Iterable, Callable, Dict
import structlog
from django.conf import settings
from django.utils.decorators import method_decorator
from drf_yasg2 import openapi
from rest_framework import status
from drf_yasg2.utils import swagger_auto_schema
from rest_framework import serializers

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from kypo.openstack_driver import KypoOpenStackClient

import datetime

# Create logger
LOG = structlog.get_logger()
# Name of user on windows instance
WIN_USERNAME = 'windows'
# Object identifier, this extension must be present in certificates
OID = '1.3.6.1.4.1.311.20.2.3'
# First two bytes are 'FORM FEED' and 'DEVICE CONTROL ONE' in order.
OID_LOGIN = '\x0c\x11' + WIN_USERNAME + '@localhost'


def configure_logging() -> None:
    """Configure logging and structlog"""
    # noinspection PyArgumentList
    logging.basicConfig(level=settings.KYPO_CONFIG.log_level,
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(settings.KYPO_CONFIG.log_file)],
                        format="%(message)s")
    structlog.configure(
        processors=[
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),  # (colors=False) to decolorise
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    LOG.debug("Logging is set and ready to use.")


def create_self_signed_certificate(private_key: str) -> str:
    """
    Create self-signed certificate.

    :param private_key: Private key used to sign certificate
    :return: Certificate string
    """
    private_key = serialization.load_pem_private_key(bytes(private_key, encoding='UTF-8'), password=None,
                                                     backend=default_backend())

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, WIN_USERNAME)
    ])

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.max
    ).add_extension(
        x509.ExtendedKeyUsage(
            [ExtendedKeyUsageOID.CLIENT_AUTH],
        ),
        critical=False,
    ).add_extension(
        x509.SubjectAlternativeName(
            [
                x509.OtherName(
                    x509.oid.ObjectIdentifier(OID),
                    OID_LOGIN.encode('utf-8'),
                ),
            ]
        ),
        critical=False,
    ).sign(private_key, hashes.SHA256(), backend=default_backend())

    return cert.public_bytes(encoding=serialization.Encoding.PEM).decode()


def generate_ssh_keypair(bits: int = 2048) -> Tuple[str, str]:
    """Generate SSH-RSA key pair.

    :param bits: Length of key in bits
    :return: Tuple of private and public key strings
    """
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
        backend=default_backend(),
    )

    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode()

    return private_key, public_key


def get_ostack_client() -> KypoOpenStackClient:
    """Abstracts creation and authentication to KYPO lib client."""
    return KypoOpenStackClient(
        auth_url=settings.KYPO_CONFIG.os_auth_url,
        application_credential_id=settings.KYPO_CONFIG.os_application_credential_id,
        application_credential_secret=settings.KYPO_CONFIG.os_application_credential_secret,
        trc=settings.KYPO_CONFIG.trc)


def get_simple_uuid() -> str:
    """First four bytes of UUID as string."""
    return str(uuid.uuid4()).split('-')[0]


class ErrorSerilizer(serializers.Serializer):
    """Serializer for error responses."""
    detail = serializers.CharField(help_text='String message describing the error.')


ERROR_RESPONSES = {
    status.HTTP_400_BAD_REQUEST:
        openapi.Response('Client sent invalid data.', ErrorSerilizer()),
    status.HTTP_401_UNAUTHORIZED:
        openapi.Response('Authentication failed.', ErrorSerilizer()),
    status.HTTP_403_FORBIDDEN:
        openapi.Response('You do not have permission to perform this action.', ErrorSerilizer()),
    status.HTTP_404_NOT_FOUND:
        openapi.Response('Resource not found.', ErrorSerilizer()),
    status.HTTP_500_INTERNAL_SERVER_ERROR:
        openapi.Response('Server encountered an unexpected error.', ErrorSerilizer()),
}


def add_error_responses_doc(method: str, statuses: Iterable[Union[int, str]]) -> Callable:
    """Decorator to include error responses into documentation.
    Can be used only if the method responses are not already decorated with
    a swagger_auto_schema decorator.
    Otherwise the error responses must be added to already used swagger_auto_schema
    decorator.
    """
    def decorate(cls):
        method_decorator(name=method, decorator=swagger_auto_schema(
            responses={k: v for k, v in ERROR_RESPONSES.items()
                       if k in statuses}
        ))(cls)
        return cls
    return decorate
