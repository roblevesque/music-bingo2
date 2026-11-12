"""Runtime configuration, read from environment variables with safe defaults."""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int = 50 * 1024 * 1024
    max_import_bytes: int = 300 * 1024 * 1024  # a game bundle (with audio) may be larger than one clip
    session_max_age: int = 60 * 60 * 24 * 14  # seconds
    https_only: bool = False  # set MUSICBINGO_HTTPS_ONLY=1 when served over TLS
    public_url: str = ""  # e.g. https://bingo.example.com, so join links are right behind a proxy
    pdf_font: str | None = None  # optional .ttf so printed tickets can show non-Latin titles
    pdf_font_bold: str | None = None

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'bingo.db3'}"

    @property
    def clips_dir(self) -> Path:
        return self.data_dir / "clips"

    @property
    def branding_dir(self) -> Path:
        return self.data_dir / "branding"

    def ensure_dirs(self) -> None:
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.branding_dir.mkdir(parents=True, exist_ok=True)

    def secret_key(self) -> str:
        """Session-signing key: env var if set, else generated once and kept in data/."""
        env_key = os.environ.get("MUSICBINGO_SECRET_KEY")
        if env_key:
            return env_key
        path = self.data_dir / "secret_key"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return path.read_text().strip()
        key = secrets.token_urlsafe(48)
        with os.fdopen(fd, "w") as handle:
            handle.write(key)
        return key


def _public_url(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    if raw and not raw.startswith(("http://", "https://")):
        raise ValueError("MUSICBINGO_PUBLIC_URL must start with http:// or https://, for example https://bingo.example.com")
    return raw


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("MUSICBINGO_DATA_DIR", "data")).resolve(),
        max_upload_bytes=int(os.environ.get("MUSICBINGO_MAX_UPLOAD_MB", "50")) * 1024 * 1024,
        max_import_bytes=int(os.environ.get("MUSICBINGO_MAX_IMPORT_MB", "300")) * 1024 * 1024,
        https_only=os.environ.get("MUSICBINGO_HTTPS_ONLY", "0") == "1",
        public_url=_public_url(os.environ.get("MUSICBINGO_PUBLIC_URL", "")),
        pdf_font=os.environ.get("MUSICBINGO_PDF_FONT") or None,
        pdf_font_bold=os.environ.get("MUSICBINGO_PDF_FONT_BOLD") or None,
    )
