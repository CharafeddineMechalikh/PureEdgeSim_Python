"""The provenance written next to the results: run.json and the settings snapshot."""
from __future__ import annotations

import json

import pytest
from conftest import SETTINGS

from pureedgesim.metadata import RUN_FILE_NAME, SETTINGS_FOLDER_NAME, SETTINGS_NAMES, write_run_metadata


def read_metadata(results):
    return json.loads((results / RUN_FILE_NAME).read_text(encoding="utf-8"))


def test_the_metadata_describes_the_resolved_run(tmp_path):
    results = tmp_path / "2026-10-25_20-00-00"

    write_run_metadata(SETTINGS, results, False, 99)

    metadata = read_metadata(results)
    assert metadata["version"]
    assert metadata["git_commit"]
    assert metadata["random_seed"] == 99
    assert metadata["parallelism"] is False
    assert metadata["output_folder"] == str(results.resolve())
    assert metadata["settings"]["edge_devices.xml"] == str((SETTINGS / "edge_devices.xml").resolve())


def test_every_settings_file_is_copied_next_to_the_results(tmp_path):
    results = tmp_path / "run"

    write_run_metadata(SETTINGS, results, True, None)

    snapshot = results / SETTINGS_FOLDER_NAME
    for name in SETTINGS_NAMES:
        assert (snapshot / name).read_bytes() == (SETTINGS / name).read_bytes(), name
    assert read_metadata(results)["random_seed"] is None
    assert read_metadata(results)["parallelism"] is True


def test_an_unseeded_run_records_a_null_seed(tmp_path):
    results = tmp_path / "run"

    write_run_metadata(SETTINGS, results, False, None)

    assert read_metadata(results)["random_seed"] is None


def test_a_missing_settings_file_stops_the_run(tmp_path):
    incomplete = tmp_path / "settings"
    incomplete.mkdir()
    (incomplete / "simulation_parameters.properties").write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="applications.xml"):
        write_run_metadata(incomplete, tmp_path / "results", False, None)
