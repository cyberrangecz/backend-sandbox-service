from Crypto.PublicKey import RSA

from kypo.sandbox_common_lib import utils


def test_json_pretty_print_formatting():
    data = {"key": "val"}
    assert utils.json_pretty_print(data) == '{\n  "key": "val"\n}'


def test_generate_ssh_keypair_correct_format():
    priv_key, pub_key = utils.generate_ssh_keypair()
    assert priv_key.startswith("-----BEGIN RSA PRIVATE KEY-----")
    assert priv_key.endswith("-----END RSA PRIVATE KEY-----")
    assert pub_key.startswith("ssh-rsa ")
    # test if private key and public key fits together
    key = RSA.importKey(priv_key)
    assert pub_key == key.publickey().exportKey("OpenSSH").decode()
