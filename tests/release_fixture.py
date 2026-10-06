"""Ephemeral test-only signing identity; never a project signing key."""
import base64
from contextlib import contextmanager
import hashlib
import json
from unittest.mock import patch


@contextmanager
def signed_update(data=b'installer bytes', version='v5.1.0', name='FRIDAY'):
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    def encode(number):
        return base64.b64encode(number.to_bytes((number.bit_length()+7)//8, 'big')).decode()
    public = f'<RSAKeyValue><Modulus>{encode(numbers.n)}</Modulus><Exponent>{encode(numbers.e)}</Exponent></RSAKeyValue>'.encode()
    fingerprint = hashlib.sha256(public).hexdigest()
    item = {'name':name+'-Setup.exe', 'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
    raw = json.dumps({'schema':1, 'publisher':'lkghost327-afk',
        'repository':f'https://github.com/lkghost327-afk/{name}', 'version':version.lstrip('v'),
        'source_commit':'a'*40, 'key_sha256':fingerprint, 'files':[item]}).encode()
    signature = base64.b64encode(key.sign(raw, padding.PKCS1v15(), hashes.SHA256()))
    update = {'name':item['name'], 'size':item['size'], 'digest':item['sha256'], 'version':version,
              'url':f'https://github.com/lkghost327-afk/{name}/releases/download/{version}/{item["name"]}',
              'manifest':base64.b64encode(raw).decode(), 'signature':base64.b64encode(signature).decode(),
              'public_key':base64.b64encode(public).decode()}
    with patch('assistant_core.release_identity.PUBLISHER_KEY_SHA256', fingerprint):
        yield update
