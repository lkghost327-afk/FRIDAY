"""Wake-model setup and checksum-verified updates from this project's releases."""
import hashlib
import base64
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlparse
import zipfile

import requests


def install_wake(emit=lambda text: None, cancelled=lambda: False):
    from .wake import MODEL_NAME, model_directory
    destination = model_directory()
    if (destination / 'am/final.mdl').is_file():
        return 'Local wake model is ready.'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wake-setup-', dir=destination.parent) as folder:
        root = Path(folder).resolve()
        archive = root / 'model.zip'
        url = 'https://alphacephei.com/vosk/models/' + MODEL_NAME + '.zip'
        total = 0
        with requests.get(url, stream=True, timeout=(10, 40)) as response:
            response.raise_for_status()
            with archive.open('wb') as output:
                for chunk in response.iter_content(256*1024):
                    if cancelled():
                        raise OSError('Wake setup cancelled.')
                    total += len(chunk)
                    if total > 80*1024*1024:
                        raise ValueError('Wake archive exceeds its expected size.')
                    output.write(chunk)
                    if total // (4*1024*1024) != (total-len(chunk)) // (4*1024*1024):
                        emit(f'Wake model: {total//(1024*1024)} MB downloaded')
        with zipfile.ZipFile(archive) as package:
            if sum(item.file_size for item in package.infolist()) > 160*1024*1024:
                raise ValueError('Wake archive expands beyond its expected size.')
            for item in package.infolist():
                if not (root/item.filename).resolve().is_relative_to(root):
                    raise ValueError('Invalid archive path')
                if item.filename.split('/')[0] != MODEL_NAME:
                    raise ValueError('Unexpected model archive content')
            package.extractall(root)
        source = root / MODEL_NAME
        if not all((source/file).is_file() for file in ('am/final.mdl','conf/model.conf','graph/HCLr.fst','graph/Gr.fst')):
            raise ValueError('The downloaded wake model is incomplete.')
        if destination.exists():
            if (destination/'am/final.mdl').is_file():
                return 'Local wake model is ready.'
            raise OSError('An incomplete model folder already exists. Rename it and run setup again.')
        if not destination.resolve().is_relative_to(destination.parent.resolve()):
            raise ValueError('Invalid model destination')
        shutil.move(str(source), str(destination))
    return 'Local wake model installed. Wake detection and local transcription are ready.'


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?', value)
    if not match:
        raise ValueError('The release does not use a supported stable version.')
    major, minor, patch, beta = match.groups()
    return (int(major), int(minor), int(patch), 0 if beta is not None else 1, int(beta or 0))


def _asset(release, name, filename, limit):
    matches = [a for a in release.get('assets', []) if a.get('name') == filename]
    if len(matches) != 1:
        raise ValueError('The release is missing its signed verification assets.')
    asset = matches[0]
    parsed = urlparse(asset['browser_download_url'])
    expected = f'/lkghost327-afk/{name}/releases/download/{release["tag_name"]}/{filename}'
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.path != expected or parsed.query or parsed.fragment:
        raise ValueError('Unexpected update download origin')
    if type(asset.get('size')) is not int or not 0 < asset['size'] <= limit:
        raise ValueError('Unexpected update asset size')
    return asset


def _small_download(asset, limit):
    data = bytearray()
    with requests.get(asset['browser_download_url'], stream=True, timeout=(5, 15)) as response:
        response.raise_for_status()
        for chunk in response.iter_content(8192):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError('Release verification data exceeds its size limit.')
    if len(data) != asset['size']:
        raise ValueError('Release verification data is incomplete.')
    return bytes(data)


def authenticate_update(update):
    from .release_identity import verify_manifest
    name = update['name'].removesuffix('-Setup.exe')
    try:
        item = verify_manifest(base64.b64decode(update['manifest'], validate=True),
            base64.b64decode(update['signature'], validate=True),
            base64.b64decode(update['public_key'], validate=True), name, update['version'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('This update has no valid publisher signature.') from None
    if item['sha256'] != update['digest'] or item['size'] != update['size']:
        raise ValueError('Installer metadata differs from the signed release.')
    _asset({'tag_name': update['version'], 'assets': [{'name': update['name'],
        'size': update['size'], 'browser_download_url': update['url']}]}, name, update['name'], 500*1024*1024)
    return item


def check_update(persona, current):
    name = 'ALFRED' if persona == 'alfred' else 'FRIDAY'
    url = f'https://api.github.com/repos/lkghost327-afk/{name}/releases/latest'
    response = requests.get(url, timeout=(5,15), headers={'Accept':'application/vnd.github+json'})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    release = response.json()
    if release.get('draft') or release.get('prerelease') or version_tuple(release['tag_name']) <= version_tuple(current):
        return None
    asset = _asset(release, name, name+'-Setup.exe', 500*1024*1024)
    if not asset or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or ''):
        raise ValueError('This release has no checksum-verified installer. Visit the repository Releases page.')
    parsed = urlparse(asset['browser_download_url'])
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not parsed.path.startswith(f'/lkghost327-afk/{name}/releases/download/'):
        raise ValueError('Unexpected update download origin')
    if not 0 < asset.get('size', 0) <= 500*1024*1024:
        raise ValueError('Unexpected update size')
    update = {'version':release['tag_name'], 'url':asset['browser_download_url'], 'digest':asset['digest'][7:],
              'size':asset['size'], 'name':name+'-Setup.exe'}
    for field, filename, limit in (('manifest', 'RELEASE-MANIFEST.json', 65536),
            ('signature', 'RELEASE-MANIFEST.sig', 4096), ('public_key', 'PUBLISHER-KEY.xml', 8192)):
        data = _small_download(_asset(release, name, filename, limit), limit)
        update[field] = base64.b64encode(data).decode('ascii')
    authenticate_update(update)
    return update


def download_update(update, directory, cancelled=lambda:False):
    authenticate_update(update)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (update['digest'][:16] + '-' + update['name'])
    if not target.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Invalid update filename')
    digest, size = hashlib.sha256(), 0
    with tempfile.NamedTemporaryFile(dir=directory, suffix='.download', delete=False) as output:
        partial = Path(output.name)
        try:
            with requests.get(update['url'], stream=True, timeout=(10,40)) as response:
                response.raise_for_status()
                for chunk in response.iter_content(256*1024):
                    if cancelled():
                        raise OSError('Update download cancelled.')
                    size += len(chunk)
                    if size > update['size']:
                        raise ValueError('Update is larger than its published size.')
                    digest.update(chunk)
                    output.write(chunk)
            if size != update['size'] or digest.hexdigest() != update['digest']:
                raise ValueError('Update checksum mismatch; the installer was not opened.')
        except Exception:
            output.close()
            partial.unlink(missing_ok=True)
            raise
    partial.replace(target)
    return target


def prepare_install(path, update, base_dir, current):
    """Recheck immediately before launch and keep a non-secret recovery checkpoint."""
    from .settings import atomic_json
    authenticate_update(update)
    path, base_dir = Path(path), Path(base_dir)
    if not path.resolve().is_relative_to((base_dir/'updates').resolve()):
        raise ValueError('The installer is outside the verified update cache.')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if path.stat().st_size != update['size'] or digest != update['digest']:
        raise ValueError('The verified installer has changed. Download it again.')
    settings = base_dir/'settings.json'
    if settings.is_file():
        values = json.loads(settings.read_text(encoding='utf-8'))
        if not isinstance(values, dict):
            raise ValueError('Settings could not be checkpointed.')
        for field in ('api_key', 'deepgram_api_key', 'persona'):
            values.pop(field, None)
        atomic_json(base_dir/'updates'/'settings-before-update.json', values)
    atomic_json(base_dir/'updates'/'pending.json', {'from':current, 'to':update['version'], 'installer':str(path)})
    return path


def recovery_status(base_dir, current):
    path = Path(base_dir)/'updates'/'pending.json'
    if not path.is_file():
        return ''
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        if version_tuple(current) >= version_tuple(record['to']):
            path.unlink()
            return 'Update completed. Your personal data and API keys were preserved.'
        return 'The previous update has not completed. You can retry it in Settings; your current version and personal data remain available.'
    except (ValueError, KeyError, OSError):
        return 'An update recovery record could not be read. Your personal data is unchanged.'


def restore_settings(base_dir, persona):
    from .settings import Settings
    base_dir = Path(base_dir)
    path = base_dir/'updates'/'settings-before-update.json'
    if not path.is_file():
        raise ValueError('There is no settings checkpoint from an earlier update.')
    values = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(values, dict) or set(values) & {'api_key', 'deepgram_api_key', 'persona'}:
        raise ValueError('Invalid settings checkpoint.')
    settings = Settings.load(base_dir, persona).updated(values)
    return settings
