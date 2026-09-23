"""Build a per-user installer with Python, native audio libraries and wake model."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from build_exe import NAME, OUTPUT, ROOT
from assistant_core import __version__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', help='Path to the official Inno Setup 6 compiler')
    parser.add_argument('--skip-build', action='store_true', help='Package an already built installer payload')
    args = parser.parse_args()
    compiler = args.iscc or shutil.which('ISCC.exe')
    if not compiler:
        local = Path(os.environ.get('LOCALAPPDATA', ''))
        candidates = [local / 'FanAssistants/build-tools/InnoSetup/ISCC.exe',
                      Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe']
        compiler = next((str(p) for p in candidates if p.is_file()), None)
    if not compiler:
        raise SystemExit('Install Inno Setup 6 from https://jrsoftware.org/isinfo.php or pass --iscc.')
    if not args.skip_build:
        subprocess.run([sys.executable, str(ROOT / 'build_exe.py'), '--onedir', '--bundle-wake-model'], check=True)
    source = OUTPUT / 'installer-payload' / NAME
    if not (source / (NAME + '.exe')).is_file():
        raise SystemExit('Installer payload is missing.')
    subprocess.run([compiler, '/DAppName=' + NAME, '/DAppVersion=' + __version__,
                    '/DSourceDir=' + str(source), '/DOutputDir=' + str(OUTPUT / 'dist'),
                    str(ROOT / 'installer.iss')], check=True)
    print('Installer:', OUTPUT / 'dist' / (NAME + '-Setup.exe'))


if __name__ == '__main__':
    main()
