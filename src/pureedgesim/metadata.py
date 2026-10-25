"""Writes the provenance of a run next to its results, like RunMetadata in Java."""
from __future__ import annotations

import json
import re
from importlib import metadata as importlib_metadata
from pathlib import Path

RUN_FILE_NAME = "run.json"
SETTINGS_FOLDER_NAME = "settings"
SETTINGS_NAMES = ("simulation_parameters.properties", "applications.xml", "edge_datacenters.xml",
                  "edge_devices.xml", "cloud.xml")


def write_run_metadata(settings_folder: str | Path, results_folder: str | Path, parallelism: bool,
                       seed: int | None) -> None:
    """Writes ``run.json`` and a snapshot of the five settings files next to the results.

    The snapshot makes a result folder replayable even after the original scenario
    files change. A missing settings file stops the run, as in Java.
    """
    settings = Path(settings_folder)
    folder = Path(results_folder)
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / SETTINGS_FOLDER_NAME
    snapshot.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in SETTINGS_NAMES:
        source = settings / name
        if not source.is_file():
            raise FileNotFoundError(f"{folder}: cannot copy the settings file {source}, it does not exist")
        (snapshot / name).write_bytes(source.read_bytes())
        paths[name] = str(source.resolve())
    metadata = {
        "version": _version(),
        "git_commit": _git_commit(),
        "random_seed": seed,
        "parallelism": bool(parallelism),
        "output_folder": str(folder.resolve()),
        "settings": paths,
    }
    (folder / RUN_FILE_NAME).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def _version() -> str:
    """The installed distribution version, or the one declared in pyproject.toml."""
    try:
        return importlib_metadata.version("pureedgesim")
    except importlib_metadata.PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if pyproject.is_file():
            match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
            if match:
                return match.group(1)
        return "unknown"


def _git_commit() -> str:
    """The commit of the checkout the run was launched from, or ``unknown``."""
    folder = Path.cwd().resolve()
    for candidate in (folder, *folder.parents):
        dot_git = candidate / ".git"
        if dot_git.is_dir():
            return _commit_from_git_directory(dot_git)
        if dot_git.is_file():
            line = dot_git.read_text(encoding="utf-8").strip()
            if line.startswith("gitdir:"):
                git_directory = Path(line.split(":", 1)[1].strip())
                if not git_directory.is_absolute():
                    git_directory = candidate / git_directory
                return _commit_from_git_directory(git_directory)
            return "unknown"
    return "unknown"


def _commit_from_git_directory(git_directory: Path) -> str:
    head = git_directory / "HEAD"
    if not head.is_file():
        return "unknown"
    content = head.read_text(encoding="utf-8").strip()
    if not content.startswith("ref:"):
        return content
    reference = git_directory / content.split(":", 1)[1].strip()
    if not reference.is_file():
        return "unknown"
    return reference.read_text(encoding="utf-8").strip()
