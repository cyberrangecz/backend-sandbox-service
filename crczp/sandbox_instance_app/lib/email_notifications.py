"""Email notification utilities for sandbox allocation events."""

import smtplib
import ssl
from email.message import EmailMessage
from smtplib import SMTP, SMTP_SSL
from types import TracebackType

import structlog
from django.conf import settings

from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration, SMTPEncryption
from crczp.sandbox_common_lib.exceptions import EmailException, ValidationError

LOG = structlog.get_logger()


def send_email(
    receiver_email: str, subject: str, body: str, crczp_config: CrczpConfiguration
) -> None:
    """Send an email using the configured SMTP server."""
    if not crczp_config.smtp_server:
        LOG.warning(
            'ERROR: SMTP server is not configured, email notifications disabled. No email sent.'
        )
        return

    sender_email = crczp_config.sender_email
    em = EmailMessage()
    em['From'] = sender_email
    em['To'] = receiver_email
    em['Subject'] = subject
    em.set_content(body)

    with EmailManager(crczp_config) as mail:
        mail.send_email(sender_email, receiver_email, em)


def validate_emails_enabled(value: bool) -> None:
    """Validate that email notifications are enabled when required."""
    if value and not settings.CRCZP_CONFIG.smtp_server:
        raise ValidationError(
            'Email SMTP server is not configured, email notifications are disabled.'
        )


class EmailManager:
    """Context manager for sending emails via SMTP."""

    def __init__(self, crczp_config: CrczpConfiguration) -> None:
        self.config = crczp_config
        self.smtp: SMTP | SMTP_SSL | None = None

    def __enter__(self) -> 'EmailManager':
        encryption = self.config.smtp_encryption

        if encryption in (SMTPEncryption.INSECURE, SMTPEncryption.TSL):
            self.smtp = smtplib.SMTP(
                self.config.smtp_server,
                self.config.smtp_port,
            )
        elif encryption == SMTPEncryption.SSL:
            context = ssl.create_default_context()
            self.smtp = smtplib.SMTP_SSL(
                self.config.smtp_server,
                self.config.smtp_port,
                context=context,
            )

        if encryption == SMTPEncryption.TSL:
            if self.smtp is None:
                raise EmailException('SMTP connection was not established.')
            self.smtp.starttls()

        if encryption != SMTPEncryption.INSECURE:
            if self.smtp is None:
                raise EmailException('SMTP connection was not established.')
            self.smtp.login(
                self.config.sender_email,
                self.config.sender_email_password,
            )

        return self

    def send_email(self, sender_email: str, receiver_email: str, message: EmailMessage) -> None:
        """Send the given email message via the active SMTP connection."""
        if self.smtp is None:
            raise EmailException('SMTP connection was not established.')
        try:
            self.smtp.sendmail(sender_email, receiver_email, message.as_string())
            LOG.debug('Email sent successfully!')
        except smtplib.SMTPAuthenticationError as exc:
            LOG.warning(
                f'Email {sender_email} login failed. '
                f'Please check the sender_email/password in config.yml. Detail: {exc}'
            )
            raise EmailException(
                'Email authentication failed. Check configured credentials or contact the'
                f' administrator. Detail: {exc}'
            ) from exc
        except Exception as exc:
            LOG.warning(f'Email notification failed to send for unknown reason. Detail: {exc}')
            raise exc

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self.smtp:
            self.smtp.quit()
