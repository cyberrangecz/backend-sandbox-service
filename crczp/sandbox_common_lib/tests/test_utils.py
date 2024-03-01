import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from crczp.sandbox_common_lib import utils


def test_generate_ssh_keypair_correct_format():
    priv_key, pub_key = utils.generate_ssh_keypair()
    assert priv_key.startswith("-----BEGIN RSA PRIVATE KEY-----")
    assert priv_key.endswith("-----END RSA PRIVATE KEY-----\n")
    assert pub_key.startswith("ssh-rsa ")
    # test if private key and public key fits together
    key = serialization.load_pem_private_key(
        data=bytes(priv_key, 'utf-8'),
        password=None,
        backend=default_backend()
    )

    expected_pub_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH
    ).decode()

    assert pub_key == expected_pub_key


def test_generate_create_self_signed_certificate_correct_format():
    priv_key, _ = utils.generate_ssh_keypair()
    certificate = utils.create_self_signed_certificate(priv_key)

    assert certificate.startswith("-----BEGIN CERTIFICATE-----")
    assert certificate.endswith("-----END CERTIFICATE-----\n")
