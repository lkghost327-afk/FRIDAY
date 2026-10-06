"""Destructive only inside isolated temp installs; preserves real startup/settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import winreg

NAMES = ('FRIDAY', 'ALFRED')
ROOT = Path(__file__).resolve().parents[2]
VALIDATION = Path(os.environ['LOCALAPPDATA']) / 'FanAssistants/validation/v51-2026-09-23/package-validation'
VALIDATION.mkdir(parents=True, exist_ok=True)
INSTALL_ROOT = Path(os.environ['USERPROFILE']) / 'AppData/Local/Temp/FanAssistants-v51'
INSTALL_ROOT.mkdir(parents=True, exist_ok=True)


def startup(name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            return winreg.QueryValueEx(key, 'FanAssistants.' + name)
    except FileNotFoundError:
        return None


def uninstall_key(name):
    return r'Software\Microsoft\Windows\CurrentVersion\Uninstall\FanAssistants.' + name + '_is1'


def ensure_unregistered(name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key(name)):
            raise RuntimeError(f'Existing {name} installation; refusing to replace it')
    except FileNotFoundError:
        pass


def install(setup, destination, log):
    subprocess.run([str(setup), '/CURRENTUSER', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                    '/NOICONS', '/DIR=' + str(destination), '/LOG=' + str(log)], timeout=180, check=True)


def uninstall(destination, log):
    subprocess.run([str(destination / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                    '/LOG=' + str(log)], timeout=90, check=True)


def check_app(name, executable, profile):
    environment = dict(os.environ, LOCALAPPDATA=str(profile), GROQ_API_KEY='', DEEPGRAM_API_KEY='',
                       PATH=os.environ.get('SystemRoot', r'C:\Windows') + r'\System32')
    environment.pop('PYTHONPATH', None)
    report = profile.parent / (name + '-diagnostics.json')
    subprocess.run([str(executable), '--check-offline', '--report', str(report)], env=environment,
                   cwd=profile.parent, timeout=90, check=True)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result['ok'] and result['local_wake_model'] and not result['key_configured'], result
    assert result['native_media_and_worker'] == 'passed', result
    subprocess.run([str(executable), '--smoke-ui', '--background'], env=environment,
                   cwd=profile.parent, timeout=45, check=True)


def validate(name):
    ensure_unregistered(name)
    before = startup(name)
    beta = Path(os.environ['LOCALAPPDATA']) / f'FanAssistants/{name}/build-output/dist/{name}-Setup.exe'
    stable = Path(r'C:\Users\lrksi\Desktop\Fan Assistants Releases') / f'{name}-Setup.exe'
    assert beta.is_file() and stable.is_file()
    # Keep below legacy MAX_PATH: packaged libraries contain several nested paths.
    with tempfile.TemporaryDirectory(prefix=name + '-', dir=INSTALL_ROOT) as temporary:
        folder = Path(temporary).resolve()
        assert folder.is_relative_to(INSTALL_ROOT.resolve())

        fresh = folder / 'fresh-app'
        install(beta, fresh, VALIDATION / f'{name}-fresh-install.log')
        check_app(name, fresh / f'{name}.exe', folder / 'fresh-profile')
        uninstall(fresh, VALIDATION / f'{name}-fresh-uninstall.log')
        assert not (fresh / f'{name}.exe').exists()
        ensure_unregistered(name)

        upgraded = folder / 'upgrade-app'
        install(stable, upgraded, VALIDATION / f'{name}-v5-install.log')
        personal = folder / f'upgrade-profile/FanAssistants/{name}'
        personal.mkdir(parents=True, exist_ok=True)
        sentinels = {
            'settings.json': b'{"recognition_language":"en-IN","speech_enabled":false,"wake_on_start":false,"start_with_windows":false,"microphone_threshold":420}',
            'notes.json': b'[{"text":"upgrade preservation test"}]',
            '.env': b'GROQ_API_KEY=\nDEEPGRAM_API_KEY=\n',
        }
        for filename, data in sentinels.items():
            (personal / filename).write_bytes(data)
        install(beta, upgraded, VALIDATION / f'{name}-beta-upgrade.log')
        for filename, data in sentinels.items():
            assert (personal / filename).read_bytes() == data, filename
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninstall_key(name)) as registration:
            assert winreg.QueryValueEx(registration, 'DisplayVersion')[0] == '5.1.0-beta.1'
        check_app(name, upgraded / f'{name}.exe', folder / 'upgrade-profile')
        uninstall(upgraded, VALIDATION / f'{name}-upgrade-uninstall.log')
        for filename, data in sentinels.items():
            assert (personal / filename).read_bytes() == data, filename
        ensure_unregistered(name)
    assert startup(name) == before, 'Startup setting changed unexpectedly'
    print(name, 'PASS: fresh beta; v5 upgrade; settings preserved; native diagnostics; hidden UI; uninstall')


if __name__ == '__main__':
    for argument in sys.argv[1:]:
        if argument not in NAMES:
            raise SystemExit('Choose FRIDAY and/or ALFRED')
        validate(argument)
