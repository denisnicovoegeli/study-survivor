import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / "Apps" / "moodle-dl"
# Repo-Wurzel; Kursdaten (knowledge, lernen, termine, state ...) liegen in data/ (gitignored)
REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_DIR = REPO_DIR / "data"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    project_dir: Path

    @property
    def moodle_db(self) -> Path:
        return self.data_dir / "moodle_state.db"

    @property
    def moodle_config_path(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def knowledge_dir(self) -> Path:
        return self.project_dir / "knowledge"

    @property
    def lernen_dir(self) -> Path:
        return self.project_dir / "lernen"

    @property
    def briefings_dir(self) -> Path:
        return self.project_dir / "briefings"

    @property
    def state_dir(self) -> Path:
        return self.project_dir / "state"

    @property
    def termine_dir(self) -> Path:
        return self.project_dir / "termine"

    @property
    def projekte_dir(self) -> Path:
        return self.project_dir / "projekte"

    @property
    def klassen_path(self) -> Path:
        return self.project_dir / "klassen.yaml"


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("STUDY_DATA_DIR", DEFAULT_DATA_DIR)),
        project_dir=Path(os.environ.get("STUDY_PROJECT_DIR", DEFAULT_PROJECT_DIR)),
    )


@dataclass(frozen=True)
class MoodleConfig:
    site_url: str  # z.B. https://moodle.fhnw.ch, ohne Slash am Ende
    token: str = field(repr=False)

    @property
    def base_url(self) -> str:
        return f"{self.site_url}/webservice/rest/server.php"


def load_moodle_config(config_path: Path) -> MoodleConfig:
    raw = json.loads(config_path.read_text())
    path = (raw.get("moodle_path") or "/").strip("/")
    site = f"https://{raw['moodle_domain']}" + (f"/{path}" if path else "")
    return MoodleConfig(site_url=site, token=raw["token"])
