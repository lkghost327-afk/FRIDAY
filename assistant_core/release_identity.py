"""Authenticate release bytes against the original publisher's pinned RSA key."""
import base64
import hashlib
import json
import re
import xml.etree.ElementTree as ET

from .ownership import OWNER, PUBLISHER_KEY_SHA256


def verify_manifest(raw, signature, public_key, name, version):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.exceptions import InvalidSignature
    if name not in {'FRIDAY', 'ALFRED'}:
        raise ValueError('Unknown release persona.')
    if len(raw) > 65536 or len(signature) > 4096 or len(public_key) > 8192:
        raise ValueError('Release identity data is too large.')
    if hashlib.sha256(public_key).hexdigest() != PUBLISHER_KEY_SHA256:
        raise ValueError('The publisher key does not match the original project.')
    try:
        xml = ET.fromstring(public_key)
        modulus = int.from_bytes(base64.b64decode(xml.findtext('Modulus'), validate=True), 'big')
        exponent = int.from_bytes(base64.b64decode(xml.findtext('Exponent'), validate=True), 'big')
        key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        key.verify(base64.b64decode(signature.strip(), validate=True), raw, padding.PKCS1v15(), hashes.SHA256())
        manifest = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, TypeError, InvalidSignature, ET.ParseError):
        raise ValueError('The release signature is invalid.') from None
    if (manifest.get('schema') != 1 or manifest.get('publisher') != OWNER or
            manifest.get('repository') != f'https://github.com/{OWNER}/{name}' or
            manifest.get('version', '').lstrip('v') != version.lstrip('v') or
            manifest.get('key_sha256') != PUBLISHER_KEY_SHA256 or
            not re.fullmatch('[0-9a-f]{40}', manifest.get('source_commit', ''))):
        raise ValueError('The signed release identity does not match this update.')
    files = manifest.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= 20:
        raise ValueError('Invalid signed file list.')
    names = set()
    for item in files:
        if (not isinstance(item, dict) or not re.fullmatch(r'[A-Za-z0-9_.-]+', item.get('name', '')) or
                item['name'] in names or type(item.get('size')) is not int or
                not 0 < item['size'] <= 500*1024*1024 or
                not re.fullmatch('[0-9a-f]{64}', item.get('sha256', ''))):
            raise ValueError('Invalid signed file entry.')
        names.add(item['name'])
    installer = next((item for item in files if item['name'] == name+'-Setup.exe'), None)
    if installer is None:
        raise ValueError('The signed manifest does not include the installer.')
    return installer
