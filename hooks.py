"""MkDocs hook: serve the repo-root llms.txt and llms-full.txt at the site root.

The files are maintained at the repository root (llmstxt.org); copying them at
build time keeps one source of truth and publishes them next to index.html.
"""

import shutil
from pathlib import Path

LLMS_FILES = ("llms.txt", "llms-full.txt")


def on_post_build(config, **kwargs):
    root = Path(config["config_file_path"]).parent
    site_dir = Path(config["site_dir"])
    for name in LLMS_FILES:
        shutil.copy2(root / name, site_dir / name)
