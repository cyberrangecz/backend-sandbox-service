import structlog
import smtplib
import ssl
from email.message import EmailMessage

from django.conf import settings
from kypo.sandbox_common_lib.exceptions import EmailException, ValidationError
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration

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

    if not kypo_config.sender_email_password:
        send_insecure_email(receiver_email, em, kypo_config)
    else:
        send_secure_email(receiver_email, em, kypo_config)


def validate_emails_enabled(value: bool):
    if value and not settings.KYPO_CONFIG.smtp_server:
        raise ValidationError("Email SMTP server is not configured, "
                              "email notifications are disabled.")


def send_secure_email(receiver_email, em: EmailMessage, kypo_config: KypoConfiguration):
    context = ssl.create_default_context()
    sender_email = kypo_config.sender_email
    password = kypo_config.sender_email_password

    try:
        with smtplib.SMTP_SSL(
            kypo_config.smtp_server,
            kypo_config.smtp_port,
            context=context,
        ) as smtp:
            smtp.login(sender_email, password)
            smtp.sendmail(sender_email, receiver_email, em.as_string())
            LOG.debug("Email sent successfully!")
    except smtplib.SMTPAuthenticationError as exc:
        LOG.info(f"WARNING: Email {sender_email} login failed. "
                 f"Please check the sender_email/password in config.yml. Detail: {exc}")
        raise EmailException(f"Email authentication failed. Check configured credentials or contact the administrator."
                             f"Detail: {exc}")


def send_insecure_email(receiver_email, em: EmailMessage, kypo_config: KypoConfiguration):
    sender_email = kypo_config.sender_email

    with smtplib.SMTP(
        kypo_config.smtp_server,
        kypo_config.smtp_port,
    ) as smtp:
        smtp.sendmail(sender_email, receiver_email, em.as_string())
