"""
Simple utils module.
"""
import json
import logging
import uuid
import jinja2
from drf_spectacular.utils import  OpenApiResponse
from typing import Tuple, Union, Iterable, Callable
import structlog
from django.conf import settings
from django.core.cache import cache
from django.http import Http404
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework import serializers
from rest_framework.generics import get_object_or_404 as gen_get_object_or_404
from rest_framework.response import Response

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from crczp.terraform_driver import CrczpTerraformClient

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
    logging.basicConfig(level=settings.CRCZP_CONFIG.log_level,
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(settings.CRCZP_CONFIG.log_file)],
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
        datetime.datetime.utcnow() - datetime.timedelta(hours=48)
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


def get_terraform_client() -> CrczpTerraformClient:
    """
    Simplify access for the terraform client.
    """
    return settings.TERRAFORM_CLIENT


def clear_cache(cache_key: str) -> None:
    """
    Delete record from cache

    :param cache_key: Key of record that will be deleted
    """
    cache.delete(cache_key)


def get_simple_uuid() -> str:
    """First four bytes of UUID as string."""
    return str(uuid.uuid4()).split('-')[0]


class ErrorSerilizer(serializers.Serializer):
    """Serializer for error responses."""
    detail = serializers.CharField(help_text='String message describing the error.')


ERROR_RESPONSES = {
    status.HTTP_400_BAD_REQUEST:
        OpenApiResponse(ErrorSerilizer(), description='Client sent invalid data.'),
    status.HTTP_401_UNAUTHORIZED:
        OpenApiResponse(ErrorSerilizer(), description='Authentication failed.'),
    status.HTTP_403_FORBIDDEN:
        OpenApiResponse(ErrorSerilizer(), description='You do not have permission to perform this action.'),
    status.HTTP_404_NOT_FOUND:
        OpenApiResponse(ErrorSerilizer(), description='Resource not found.'),
    status.HTTP_500_INTERNAL_SERVER_ERROR:
        OpenApiResponse(ErrorSerilizer(), description='Server encountered an unexpected error.'),
}

def get_object_or_404(queryset, *filter_args, **filter_kwargs):
    try:
        return gen_get_object_or_404(queryset, *filter_args, **filter_kwargs)
    except Http404:
        raise Http404(f'The instance of {queryset.__name__} with {filter_kwargs} not found.')
