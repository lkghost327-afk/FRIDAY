"""Install the small Apache-2.0 Vosk wake model outside the source checkout."""
from pathlib import Path
import shutil
import tempfile
import zipfile
import requests
from assistant_core.wake import MODEL_NAME, model_directory


def main():
    destination = model_directory()
    if (destination / "am/final.mdl").is_file():
        print("Local wake model is ready.")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = "https://alphacephei.com/vosk/models/" + MODEL_NAME + ".zip"
    print("Downloading the 40 MB local wake model…")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix="wake-download-") as folder:
        temporary = Path(folder)
        archive = temporary / "model.zip"
        with requests.get(url, stream=True, timeout=(10, 90)) as response:
            response.raise_for_status()
            with archive.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    output.write(chunk)
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                target = (temporary / item.filename).resolve()
                if not target.is_relative_to(temporary.resolve()):
                    raise ValueError("Invalid model archive path")
            package.extractall(temporary)
        source = temporary / MODEL_NAME
        if not (source / "am/final.mdl").is_file():
            raise ValueError("Wake model is incomplete")
        if destination.exists():
            raise FileExistsError("An incomplete wake model already exists; preserve it and choose another model directory.")
        shutil.move(str(source), str(destination))
    print("Local wake model installed:", destination)


if __name__ == "__main__":
    main()
