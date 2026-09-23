"""Original project publisher and pinned release-verification identity.

Publisher: lkghost327-afk — https://github.com/lkghost327-afk
This attribution covers this project's original code, not third-party components.
"""
OWNER = 'lkghost327-afk'
PUBLISHER_KEY_SHA256 = '5111ff26aa40aa8d927d0e8a9f191c82bb007d360eaacca9a4366cd3d6da3e0a'


def details(persona):
    name = 'ALFRED' if persona == 'alfred' else 'FRIDAY'
    return {'publisher': OWNER, 'repository': f'https://github.com/{OWNER}/{name}',
            'publisher_key_sha256': PUBLISHER_KEY_SHA256}
