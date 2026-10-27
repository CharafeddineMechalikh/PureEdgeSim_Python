"""Loading a private settings folder and sweeping the whole grid in parallel.

    python examples/custom_settings_parallel/custom_settings_parallel.py

Two things that are easy to mix up: where a scenario comes from, and how its
grid is executed. The settings folder of this example is not the default one,
and its `simulation_parameters.properties` asks for parallel mode, so the
architectures, the algorithms and the device counts declared there are run as
independent scenarios by worker processes instead of one after another.

The grid is swept twice here, once sequentially and once in parallel, with the
same seed. The rows must be identical, only the wall time changes. That is the
claim this example tests: a scenario draws from a stream derived from the seed
and its own index, so a worker process cannot disagree with the main thread.
"""
from __future__ import annotations

import time
from pathlib import Path

from pureedgesim import COLUMNS, Simulation, load_parameters, load_settings

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/custom_settings_parallel/output"
SEED = 42


def main(label: str = "", parallel: bool = False, output: str = OUTPUT, devices: int | None = None,
         duration: float | None = None) -> list[dict]:
    """Sweeps the grid of `settings/`, sequentially or in parallel, and prints one line per row."""
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    parameters.parallel_simulation = parallel
    # The shipped scenario leaves the seed empty; fix one so the two sweeps are
    # comparable instead of two independent samples of the same workload.
    parameters.random_seed = SEED
    if devices:
        parameters.min_number_of_devices = parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration:
        parameters.simulation_duration = duration
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    started = time.perf_counter()
    rows = simulation.launch()
    elapsed = time.perf_counter() - started
    for row in rows:
        print(f"{label:<11} {row[COLUMNS[0]]:<14} {row[COLUMNS[1]]:<12} "
              f"devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} ok={row[COLUMNS[8]]:>5} "
              f"avg_delay={row[COLUMNS[4]]:<8} energy={row[COLUMNS[32]]}")
    print(f"{label:<11} {len(rows)} scenario(s) in {elapsed:.2f} s wall time\n")
    return rows


if __name__ == "__main__":
    print(f"settings folder: {SETTINGS}\n")
    sequential = main("sequential", parallel=False)
    parallel_rows = main("parallel", parallel=True)
    same = all(left == right for left, right in zip(sequential, parallel_rows))
    print(f"the two sweeps produced {len(sequential)} rows each, identical: {same}")
