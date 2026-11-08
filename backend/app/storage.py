from pathlib import Path
from uuid import uuid4

from app.config import settings


def save_file(file_bytes: bytes) -> str:
    """Save the uploaded bytes to the upload folder and return the file path."""
    upload_folder = Path(settings.upload_dir)
    upload_folder.mkdir(parents=True, exist_ok=True)

    # A random name avoids clashes and strange characters in user file names
    file_name = uuid4().hex + ".pdf"
    file_path = upload_folder / file_name
    file_path.write_bytes(file_bytes)

    return str(file_path)


def delete_file(file_path: str) -> None:
    """Delete a saved file if it still exists."""
    path = Path(file_path)
    if path.exists():
        path.unlink()