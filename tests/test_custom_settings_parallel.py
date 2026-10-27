"""The private settings folder and the parallel sweep of ``custom_settings_parallel``.

The example claims two things: the scenario comes from its own folder rather than
the default one, and running that grid in worker processes gives the same rows as
running it in the main process. Both are checked here on a shrunk grid, six devices
and two simulated minutes, so the six scenarios stay quick.
"""
from __future__ import annotations

import csv

from examples.custom_settings_parallel import custom_settings_parallel as sweep
from pureedgesim import COLUMNS, load_parameters


def test_the_shipped_settings_ask_for_parallel_mode():
    parameters = load_parameters(sweep.SETTINGS / "simulation_parameters.properties")
    assert parameters.parallel_simulation
    # The grid this example teaches: three architectures and two algorithms.
    assert parameters.orchestration_architectures == ["MIST_AND_EDGE", "ALL", "CLOUD_ONLY"]
    assert parameters.orchestration_algorithms == ["ROUND_ROBIN", "TRADE_OFF"]


def test_the_parallel_sweep_gives_the_same_rows_as_the_sequential_one(tmp_path):
    sequential = sweep.main("sequential", parallel=False, output=str(tmp_path / "sequential"),
                            devices=6, duration=120.0)
    parallel = sweep.main("parallel", parallel=True, output=str(tmp_path / "parallel"),
                          devices=6, duration=120.0)
    assert len(sequential) == 6 == len(parallel)
    keys = [(row[COLUMNS[0]], row[COLUMNS[1]]) for row in sequential]
    assert keys == [(row[COLUMNS[0]], row[COLUMNS[1]]) for row in parallel]
    for left, right in zip(sequential, parallel):
        assert left == right


def test_both_sweeps_write_their_csv_under_the_requested_output_folder(tmp_path):
    parallel = sweep.main("parallel", parallel=True, output=str(tmp_path / "parallel"),
                          devices=6, duration=120.0)
    files = list((tmp_path / "parallel").glob("*/Parallel_simulation.csv"))
    assert len(files) == 1
    rows = list(csv.DictReader(files[0].open(encoding="utf-8")))
    assert len(rows) == len(parallel)
    assert {row[COLUMNS[0]] for row in rows} == {"MIST_AND_EDGE", "ALL", "CLOUD_ONLY"}
