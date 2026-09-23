"""Build either persona; generated binaries stay outside this repository."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
NAME = 'FRIDAY' if (ROOT / 'friday_app.py').is_file() else 'ALFRED'
OUTPUT = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "FanAssistants" / NAME / "build-output"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--onedir', action='store_true', help='Build the faster-starting installer payload')
    parser.add_argument('--bundle-wake-model', action='store_true')
    args = parser.parse_args()
    dist = OUTPUT / ('installer-payload' if args.onedir else 'dist')
    command = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onedir" if args.onedir else "--onefile", "--windowed",
               "--name", NAME, "--paths", str(ROOT), "--distpath", str(dist),
               "--workpath", str(OUTPUT / "build"), "--specpath", str(OUTPUT / "specs"),
               "--collect-all", "customtkinter", "--collect-all", "ddgs",
               "--collect-all", "pystray",
               "--collect-all", "vosk", "--hidden-import", "win32security", "--hidden-import", "win32con",
               "--collect-all", "miniaudio", "--collect-all", "aec_audio_processing",
               "--collect-submodules", "pywinauto",
               "--collect-submodules", "pycaw", "--hidden-import", "comtypes",
               "--hidden-import", "psutil", "--hidden-import", "screen_brightness_control",
               "--hidden-import", "screen_brightness_control.windows", "--hidden-import", "requests",
               "--hidden-import", "win32com.client", "--hidden-import", "pythoncom",
               "--hidden-import", "PIL.ImageGrab", "--hidden-import", "pyaudio", "--hidden-import", "audioop",
               "--exclude-module", "torch", "--exclude-module", "tensorflow",
               "--exclude-module", "chromadb", "--exclude-module", "sentence_transformers",
               "--exclude-module", "matplotlib", "--exclude-module", "pandas", "--exclude-module", "scipy",
               str(ROOT / (NAME.lower() + "_app.py"))]
    if args.bundle_wake_model:
        from assistant_core.wake import model_directory, MODEL_NAME
        model = model_directory()
        if not (model / 'am/final.mdl').is_file():
            raise SystemExit('Run setup_wake.py before bundling the wake model.')
        command[-1:-1] = ['--add-data', f'{model};models/{MODEL_NAME}']
    subprocess.run(command, cwd=ROOT, check=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    print("Built:", dist / NAME / (NAME + '.exe') if args.onedir else dist / (NAME + '.exe'))

if __name__ == "__main__":
    main()
