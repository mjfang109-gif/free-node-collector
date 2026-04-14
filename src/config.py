import yaml
from pathlib import Path

CONFIG_DIR = Path("config")
DIST_DIR = Path("dist")
DIST_DIR.mkdir(exist_ok=True)


def load_sources():
    with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]
