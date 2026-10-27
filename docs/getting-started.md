---
description: "Install PureEdgeSim for Python with pip, run your first scenario from the command line or from a script, and read the results."
---
# Getting started

This page takes you from an empty terminal to a finished simulation run with a CSV of results. It assumes Python 3.10 or newer (the package declares `requires-python = ">=3.10"`).

## Install

The package has no runtime dependencies. Install it from the repository in editable mode so the examples and tests import it from `src/`:

```bash
git clone https://github.com/CharafeddineMechalikh/PureEdgeSim_Python.git
cd PureEdgeSim_Python
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[test]"
```

The `.[test]` extra pulls in `pytest`, which you only need if you plan to run the test suite. A plain `pip install -e .` is enough to run simulations.

Editable install exposes the console script `pureedgesim`, declared in `pyproject.toml` as `pureedgesim = "pureedgesim.cli:main"`. If you skip the install, you can still reach the same entry point with `python -m pureedgesim.cli`, but the `examples/` scripts import `pureedgesim` directly, so installing once is simplest.

## A scenario is a folder of five files

PureEdgeSim reads a scenario from a settings folder. The parser (`load_settings`) refuses to run unless all five files are present, and names the missing ones in the error:

- `simulation_parameters.properties`, the timing, network, orchestration, and sweep settings.
- `applications.xml`, the workload (task sizes, rates, latencies, and optional service graphs).
- `cloud.xml`, the cloud data centers.
- `edge_datacenters.xml`, the edge data centers and the MAN links between them.
- `edge_devices.xml`, the device types (compute, battery, mobility, connectivity).

The repository ships several ready folders under `examples/`. The ones used in the examples and tests, and stable enough to point at directly, are `examples/default_settings/` and `examples/partitioning_settings/`.

## Your first run

From the repository root, run the default scenario. By default `examples/default_settings/` sweeps seven architectures and two algorithms over device counts 100, 200, and 300, so a full run is 42 iterations. For a quick first run, narrow the sweep with CLI flags:

```bash
pureedgesim run --settings examples/default_settings --devices 100 --architectures ALL --algorithms TRADE_OFF --seed 42
```

What this does:

- `--settings examples/default_settings` points at the folder holding the five files.
- `--devices 100` pins `min`, `max`, and increment so only one device count is run.
- `--architectures ALL` and `--algorithms TRADE_OFF` override the comma-separated lists in the properties file.
- `--seed 42` makes the run reproducible: task sizes, arrival times, node capacities, and device positions are all drawn from this seed.

The CLI prints a one-line summary per scenario (architecture, algorithm, device count, then the generated-task, success, average-delay, and energy figures from columns 7, 8, 4, and 32). With the flags above the output has this shape:

```text
Ran 1 scenario(s), results in output/<timestamp>
  ALL            TRADE_OFF       100 tasks=   ... ok=   ... avg_delay=... energy=...
```

The exact task and success counts depend on the seed and the workload; run the command to see them.

Results are written under the `output_folder` from the properties file (default `output`), inside a timestamped subfolder. The CSV is named `Sequential_simulation.csv` for a sequential run and `Parallel_simulation.csv` for a `--parallel` run. The same subfolder also holds a `run.json` and a snapshot copy of the five settings files, so the result folder is self-contained.

### Other CLI flags

| Flag | Effect |
| --- | --- |
| `--output <dir>` | Override the output folder instead of the `output_folder` property. |
| `--duration <minutes>` | Override `simulation_time`, in minutes. |
| `--algorithms A,B` | Comma-separated orchestration algorithms to sweep. |
| `--parallel` | Run the scenarios in separate processes (`parallel_simulation = True`). |

Configuration errors (a missing file, an unknown value) print `error: <message>` to stderr and exit with status 1.

## Listing mobility models

The second CLI subcommand lists the built-in mobility models by name:

```bash
pureedgesim models
```

It prints the comma-separated names the factory knows, sorted:

```text
brownian, circular, default, gauss-markov, group, levy-walk, manhattan, random-walk, random-waypoint, rpgm, waypoint
```

That is eleven names for nine classes: `random-waypoint` and `default` are aliases, and `group` and `rpgm` are aliases. The `--verbose` flag prints the class behind each name, one per line:

```text
brownian       BrownianMobilityModel
circular       CircularMobilityModel
default        DefaultMobilityModel
gauss-markov   GaussMarkovMobilityModel
```

The full model-to-class mapping and each model's options are in [Simulation models](models.md).

## Running from a Python script

The CLI is a thin wrapper over the `Simulation` class. Doing the same thing in code, for a custom orchestrator or a programmatic parameter change, looks like this:

```python
from pathlib import Path
from pureedgesim import Simulation, load_parameters, load_settings

settings = Path("examples/default_settings")
parameters = load_parameters(settings / "simulation_parameters.properties")
parameters.simulation_duration = 300.0          # seconds, inside Python (not minutes)
parameters.min_number_of_devices = 50
parameters.max_number_of_devices = 50
parameters.devices_increment = 1
parameters.orchestration_architectures = ["ALL"]
parameters.orchestration_algorithms = ["TRADE_OFF"]
parameters.random_seed = 42
parameters.save_log_file = False

simulation = Simulation(settings, "output/first", parameters, load_settings(settings))
rows = simulation.launch()
print(rows[0])
```

Note the units difference. In `simulation_parameters.properties`, `simulation_time` is written in minutes and the parser multiplies it by 60. In Python you set `parameters.simulation_duration` directly, in seconds. Both end up in the same attribute.

`launch()` returns a list of result dicts, one per scenario, keyed by the CSV column names. See [Output and metrics](output-and-metrics.md) for the full list.

## Next steps

- Change the workload or the topology: [Configuration](configuration.md).
- Understand what runs between `launch()` and the CSV: [Architecture](architecture.md) and [Task lifecycle](task-lifecycle.md).
- Write your own placement policy: [Writing orchestrators](orchestrators.md).
- Compare against the Java manual: [Python vs Java](python-vs-java.md).
