import structlog
import smtplib
import ssl
from email.message import EmailMessage

from django.conf import settings
from kypo.sandbox_common_lib.exceptions import EmailException, ValidationError
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration, SMTPEncryption

LOG = structlog.get_logger()


def send_email(receiver_email, subject, body, kypo_config: KypoConfiguration):
    if not kypo_config.smtp_server:
        LOG.warning("ERROR: SMTP server is not configured, email notifications disabled. No email sent.")
        return

    em = EmailMessage()
    em['From'] = kypo_config.sender_email
    em['To'] = receiver_email
    em['Subject'] = subject
    em.set_content(body)

    sender_email = kypo_config.sender_email

    try:
        with EmailManager(kypo_config) as smtp:
            smtp.sendmail(sender_email, receiver_email, em.as_string())
            LOG.debug("Email sent successfully!")
    except smtplib.SMTPAuthenticationError as exc:
        LOG.warning(f"Email {sender_email} login failed. "
                    f"Please check the sender_email/password in config.yml. Detail: {exc}")
        raise EmailException(
            f"Email authentication failed. Check configured credentials or contact the administrator."
            f"Detail: {exc}")
    except Exception as exc:
        LOG.warning(f"Email notification failed to send for unknown reason. Detail: {exc}")
        raise EmailException(f"Email notification failed to send for unknown reason. Detail: {exc}")


def validate_emails_enabled(value: bool):
    if value and not settings.KYPO_CONFIG.smtp_server:
        raise ValidationError("Email SMTP server is not configured, "
                              "email notifications are disabled.")


class EmailManager:
    def __init__(self, kypo_config: KypoConfiguration):
        self.config = kypo_config
        self.smtp = None

    def __enter__(self):
        encryption = self.config.smtp_encryption

        if encryption == SMTPEncryption.INSECURE or \
                encryption == SMTPEncryption.TSL:
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
            self.smtp.starttls()

        if encryption != SMTPEncryption.INSECURE:
            self.smtp.login(
                self.config.sender_email,
                self.config.sender_email_password,
            )

        return self.smtp

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.smtp:
            self.smtp.quit()

