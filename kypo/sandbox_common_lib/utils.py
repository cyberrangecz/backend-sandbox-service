"""
Simple utils module.
"""
import json
import logging
import uuid
from typing import Tuple
import structlog
from Crypto.PublicKey import RSA
from django.conf import settings

from kypo.openstack_driver.ostack_client import KypoOstackClient

# Create logger
LOG = structlog.get_logger()


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


def json_pretty_print(data: dict) -> str:
    """
    Pretty print JSON as string. Used primarily for logging purposes.
    :param data: Mapping type of JSON
    :return: JSON string
    """
    return json.dumps(data, indent=2)


def generate_ssh_keypair(bits: int = 2048) -> Tuple[str, str]:
    """
    Generate SSH-RSA key pair.

    :return: Tuple of private and public key strings
    """
    key = RSA.generate(bits)
    priv_key = key.exportKey().decode()
    pub_key = key.publickey().exportKey("OpenSSH").decode()
    return priv_key, pub_key


def get_ostack_client() -> KypoOstackClient:
    """Abstracts creation and authentication to KYPO lib client."""
    return KypoOstackClient(app_creds_id=settings.KYPO_CONFIG.os_application_credential_id,
                            auth_url=settings.KYPO_CONFIG.os_auth_url,
                            app_creds_secret=settings.KYPO_CONFIG.os_application_credential_secret,
                            trc=settings.KYPO_CONFIG.trc)


def get_simple_uuid() -> str:
    """First four bytes of UUID as string."""
    return str(uuid.uuid4()).split('-')[0]
