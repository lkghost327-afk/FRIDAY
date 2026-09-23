"""Wake-model setup and checksum-verified updates from this project's releases."""
import hashlib
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
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    if not match:
        raise ValueError('The release does not use a supported stable version.')
    return tuple(map(int, match.groups()))


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
    asset = next((a for a in release.get('assets', []) if a['name'] == name+'-Setup.exe'), None)
    if not asset or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or ''):
        raise ValueError('This release has no checksum-verified installer. Visit the repository Releases page.')
    parsed = urlparse(asset['browser_download_url'])
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not parsed.path.startswith(f'/lkghost327-afk/{name}/releases/download/'):
        raise ValueError('Unexpected update download origin')
    if not 0 < asset.get('size', 0) <= 500*1024*1024:
        raise ValueError('Unexpected update size')
    return {'version':release['tag_name'], 'url':asset['browser_download_url'], 'digest':asset['digest'][7:],
            'size':asset['size'], 'name':name+'-Setup.exe'}


def download_update(update, directory, cancelled=lambda:False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / update['name']
    if target.name != update['name'] or not target.resolve().is_relative_to(directory.resolve()):
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
