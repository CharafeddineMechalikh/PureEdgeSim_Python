# PureEdgeSim

<p align="center">
  <a href="https://github.com/CharafeddineMechalikh/PureEdgeSim"><img src="https://img.shields.io/badge/Java%20version-PureEdgeSim-blue?logo=openjdk" alt="PureEdgeSim, the Java version"></a>
  <a href="https://github.com/CharafeddineMechalikh/PureEdgeSim_Python/actions/workflows/tests.yml"><img src="https://github.com/CharafeddineMechalikh/PureEdgeSim_Python/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://www.gnu.org/licenses/gpl-3.0"><img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="GPL v3 license"></a>
  <img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-informational" alt="Python 3.10 to 3.13">
</p>

**PureEdgeSim is now available in Python.** This is the same simulator in another language,
not a redesign of it: the same discrete-event engine, the same task lifecycle, the same
orchestration algorithms, energy models and mobility models, the same five settings files
and the same 56-column CSV, so a study run here can be placed side by side with the same
study run in [PureEdgeSim (Java)](https://github.com/CharafeddineMechalikh/PureEdgeSim).

Install it with `pip`, import it as `pureedgesim`, and run it with the `pureedgesim`
command; the classes, parameters and reported columns keep their PureEdgeSim names. The
manual is at [charafeddinemechalikh.github.io/PureEdgeSim_Python/docs](https://charafeddinemechalikh.github.io/PureEdgeSim_Python/docs/).

The core needs the Python standard library only (Python 3.10 or later). The one optional
extra is pytest, to run the test suite. The live Swing charts of the Java framework are not
ported, so nothing here needs a plotting library; the output is a CSV you plot with your own
tools.

## Install

```bash
git clone https://github.com/CharafeddineMechalikh/PureEdgeSim_Python.git
cd PureEdgeSim_Python
pip install -e .            # the library and the "pureedgesim" command
pip install -e .[test]      # plus pytest, to run the test suite
```

Without installing, point `PYTHONPATH` at `src`:

```bash
PYTHONPATH=src python -m pureedgesim.cli models
```

## Command line

`pureedgesim run` executes every scenario of a settings folder, the way the Java
`Simulation` does, and writes the results under a timestamped output folder.

```bash
pureedgesim run --settings examples/default_settings --devices 50 --duration 10 \
              --architectures MIST_AND_EDGE,ALL,CLOUD_ONLY \
              --algorithms TRADE_OFF,ROUND_ROBIN --seed 7
```

```text
Ran 6 scenario(s), results in output\2026-10-27_15-27-55
  MIST_AND_EDGE  TRADE_OFF        50 tasks=  5330 ok=  1226 avg_delay=0.197 energy=30.977
  MIST_AND_EDGE  ROUND_ROBIN      50 tasks=  5330 ok=  1231 avg_delay=0.2101 energy=31.0616
  ALL            TRADE_OFF        50 tasks=  5330 ok=  1229 avg_delay=0.2274 energy=31.8876
  ALL            ROUND_ROBIN      50 tasks=  5330 ok=  1829 avg_delay=0.2074 energy=31.139
  CLOUD_ONLY     TRADE_OFF        50 tasks=  5330 ok=   630 avg_delay=0.1693 energy=36.4156
  CLOUD_ONLY     ROUND_ROBIN      50 tasks=  5330 ok=   630 avg_delay=0.1693 energy=36.4156
```

The two CLOUD_ONLY rows are not a coincidence: with a single cloud data center both
algorithms place every task on the same node.

| Option | Meaning |
| --- | --- |
| `--settings` | folder holding the five settings files (default `settings`) |
| `--output` | where the results go (default the `output_folder` property) |
| `--devices` | run only this edge devices count |
| `--architectures` | comma separated, overrides the properties file |
| `--algorithms` | comma separated, overrides the properties file |
| `--duration` | simulated minutes |
| `--seed` | `random_seed`, makes the run reproducible |
| `--parallel` | one worker process per scenario |

`pureedgesim models [--verbose]` lists the mobility models that a settings folder may
name.

## Library

Run a sweep, the settings folder deciding which scenarios are executed:

```python
from pureedgesim import COLUMNS, Simulation

simulation = Simulation("examples/default_settings", "output")
simulation.load()
simulation.parameters.simulation_duration = 300        # five simulated minutes
simulation.parameters.min_number_of_devices = simulation.parameters.max_number_of_devices = 20
simulation.parameters.orchestration_architectures = ["ALL", "MIST_ONLY"]
simulation.parameters.random_seed = 7
for row in simulation.launch():
    print(row[COLUMNS[0]], row[COLUMNS[1]], row[COLUMNS[7]], row[COLUMNS[4]])
```

Or drive one scenario yourself, which is what you want when you plot the metrics of
a single run:

```python
from pureedgesim import Engine, Randomness, Scenario, SimulationManager
from pureedgesim import load_parameters, load_settings

Randomness.set_seed(42)
Randomness.begin_scenario(0)
parameters = load_parameters("examples/default_settings/simulation_parameters.properties")
parameters.simulation_duration = 600          # seconds, in simulated time
files = load_settings("examples/default_settings")

engine = Engine(parameters.simulation_duration)
manager = SimulationManager(engine, parameters, files, Scenario("ALL", "TRADE_OFF", 50))
manager.start_simulation()
engine.start()

print(manager.metrics.generated_tasks, manager.metrics.succeeded_tasks)
print(manager.metrics.cloud_tasks, manager.metrics.edge_tasks, manager.metrics.mist_tasks)
```

`summarize(manager)` turns that manager into the same result row the sweep writes.

## Custom policies

Every runnable example has its own folder and README, indexed in
[`examples/`](examples/README.md). Subclass `Orchestrator` and hand the class to
`Simulation.set_custom_orchestrator`.
[`examples/custom_orchestrator/`](examples/custom_orchestrator/README.md) places
every task on the node closest to its device instead of balancing the load:

```text
TRADE_OFF (default)      tasks= 1035 ok=  775 avg_delay=0.2024   cloud= 135 edge= 436 mist= 464 energy=11.6066
nearest node             tasks= 1035 ok=  781 avg_delay=0.2037   cloud=   0 edge= 522 mist= 513 energy=11.4243
```

[`examples/distributions_and_mobility/`](examples/distributions_and_mobility/README.md)
replaces the constants of the settings files by probability distributions and
lets the devices move with the Gauss-Markov model:

```text
constants, static      tasks= 1035 ok=  775 delay=0.2024   failed(delay)= 260 failed(mobility)=   0 energy=11.6066
distributions, mobile  tasks= 1006 ok=  793 delay=0.2132   failed(delay)= 213 failed(mobility)=   0 energy=10.9223
```

[`examples/graph_partitioning/`](examples/graph_partitioning/README.md) and
[`examples/genetic_partitioning/`](examples/genetic_partitioning/README.md)
partition a service graph instead of treating one request as one task. Both run
their own copy of the video analytics pipeline, seven subtasks in
`settings/applications.xml`, and share the solvers in `src/pureedgesim/partitioning.py`:

- the first cuts every connected component into balanced partitions (heaviest step
  first, then Kernighan-Lin style pair swaps that remove dependency edges) and maps the
  partitions to mist, edge, and cloud;
- the second searches the node of every subtask with a genetic algorithm whose fitness
  estimates the pipeline makespan, the result transfers, and the load imbalance.

Each orchestrator clears the application placement after its decision, so every subtask
is routed on its own:

```text
GraphPartitioningOrchestrator - Application 0 (Soft Real-time): 3 partitions, cut 4 edges (720000 bits per request)
  P0.0 ['detect'] (4000 MI)
  P0.1 ['classify'] (2500 MI)
  P0.2 ['capture', 'preprocess', 'track', 'aggregate', 'notify'] (1950 MI)
tasks= 9600 ok= 9600 avg_delay=0.024    cloud=3537 edge=4350 mist=1713 failed(dependency)=   0 energy=49.3512

GeneticOrchestrator - Application 0 (Soft Real-time): fitness 0.0768 (makespan 0.0697 s, transfers 0.0011 s, imbalance 0.6244)
  {'capture': 'Mist#65', 'preprocess': 'Mist#65', 'detect': 'Mist#64', 'classify': 'Mist#54', 'track': 'Edge#2', 'aggregate': 'Mist#54', 'notify': 'Mist#54'}
tasks= 9600 ok= 9600 avg_delay=0.0252 cloud= 984 edge=5861 mist=2755 failed(dependency)=   0 energy=49.2382
```

## Settings folder

The five files are the PureEdgeSim ones, read by `load_settings` and
`load_parameters`:

| File | Content |
| --- | --- |
| `simulation_parameters.properties` | duration, network, energy, the scenario sweep |
| `edge_devices.xml` | device types, hardware, battery, mobility |
| `edge_datacenters.xml` | edge servers, their positions and MAN links |
| `cloud.xml` | the cloud data center |
| `applications.xml` | task rates, sizes, lengths, arrival patterns and service graphs |

Any numeric element may carry a distribution instead of a value, with the same
attributes as the Java framework:

```xml
<task_length distribution="lognormal" mean="5000" std="1500"/>
<request_size distribution="weibull" shape="1.5" scale="2000" min="100"/>
<arrival>poisson</arrival>
```

Supported names: `constant`, `uniform`, `triangular`, `normal`, `lognormal`,
`exponential`, `erlang`, `gamma`, `weibull`, `pareto`, `beta`, `bernoulli`,
`binomial`, `geometric`, `poisson`, `categorical`. Sizes are read in kilobytes and
stored in bits, task lengths in million instructions.

### Service graphs

An application can describe a multi-stage service with `<subtask>` elements instead
of a single task:

```xml
<application name="Video analytics">
    <type>Soft Real-time</type><rate>10</rate><usage_percentage>100</usage_percentage>
    <latency>0.5</latency><container_size>1500</container_size>
    <request_size>1500</request_size><results_size>50</results_size>
    <task_length>5000</task_length>
    <subtask name="capture" task_length="500"/>
    <subtask name="detect" depends_on="capture"/>
    <subtask name="alert" depends_on="detect" request_size="10"/>
</application>
```

Each request produces one task per subtask. Only the roots are submitted at the
request time; a subtask enters the simulation when every name in its `depends_on`
attribute has returned its results. `task_length`, `request_size`, `results_size`,
`container_size`, and `latency` override the application value for that subtask, and
omitted attributes inherit it. Names must be unique, every dependency must exist, and
the graph must be acyclic; a violation raises a `ValueError` naming the file,
application, and subtask.

The graph carries its data and its deadline. The `results_size` of each parent is
added to the `request_size` of its children, so the payload of a dependency travels
over the network, and the application `latency` is drawn once per request and shared
by every subtask as an end-to-end deadline: a result that returns at or after it fails
even when the subtask met its own bound.

When a subtask fails, its whole subtree fails with
`FAILED_BECAUSE_DEPENDENCY_FAILED` and is counted in the "Tasks not executed because a
dependency failed" column. A subtask marked `optional="true"` is skipped instead, with
status `SKIPPED`: its dependents are released without the missing input and the request
still counts as successful. An optional subtask must have at least one dependency,
because an optional root could never be skipped. Applications without `<subtask>`
elements produce exactly one independent task per request, as before.

The report measures requests as well as tasks: how many were generated, how many
completed, and the average end-to-end makespan of the successful ones, in four columns
appended at the end of the CSV row and in a `Requests` block of the text report.

The application placement is shared by default: the first subtask decides where the
application runs, and the following subtasks reuse that destination. An orchestrator
that routes subtasks to different nodes clears the placement after each decision with
`task.source_device.application_placed = False`. The two partitioning examples in
[Custom policies](#custom-policies) do that.

Mobility models are selected with the `model` attribute of the `<mobility>` element,
and their options are extra attributes:

| Model | Options, with their default |
| --- | --- |
| `random-waypoint`, `default` | none; speed and the pause and mobility durations come from the device element |
| `random-walk` | none |
| `gauss-markov` | `alpha` (0.7), `std` (30 degrees), `speed_std` (20% of the mean speed) |
| `manhattan` | `grid_size` (100 m) |
| `waypoint` | `waypoints` (required, `x1,y1;x2,y2`), `loop` (true) |
| `circular` | `radius` (required, must be > 0), `center_x` and `center_y` (the map centre), `clockwise` (true) |
| `levy-walk` | `min_step` (the step distance), `max_step` (the map diagonal), `shape` (1.5) |
| `brownian` | `std` (the step distance) |
| `group`, `rpgm` | `group` ("1"), `anchor_speed` (the device speed), `anchor_pause` (0) |

Devices of the same `group` follow one anchor path. Any dotted class path naming a
`MobilityModel` subclass also works.

## Reproducibility

Without a seed, the port draws from one shared, unseeded generator (the Java
framework uses a `SecureRandom` there), so no two runs are alike. Set `random_seed`
in the properties file, or pass `--seed`, and every scenario gets its own
reproducible stream: scenario *i* draws from `seed` mixed with `i`, so a sweep
replays itself and parallel workers agree with the sequential path.
`Randomness.set_seed()` and `Randomness.begin_scenario()` are the programmatic
equivalents.

## Output

`Sequential_simulation.csv` (or `Parallel_simulation.csv`) holds the 56 PureEdgeSim
columns, in the Java order, plus a `Sequential_simulation.txt` summary per scenario
when `save_log_file=true`. `pureedgesim.runner.COLUMNS` is that column list.

Every timestamped output folder also receives two provenance artifacts:

- `run.json`, with the package version, the git commit of the checkout, the random
  seed (`null` when the run was not seeded), the parallelism flag, the absolute output
  path, and the absolute path of each settings file.
- `settings/`, a snapshot of the five configuration files the run parsed. A run can
  therefore be replayed with `Simulation("path/to/results/<timestamp>/settings", ...)`
  after the original scenario files change.

An unreadable or invalid settings file stops the run with a message naming the file,
the element, and the cause; nothing is silently skipped.

## Tests

```bash
pip install -e .[test]
pytest              # 491 tests, the core, the settings readers, the CLI, and the examples
```

The integration tests build real managers and run them to the end, so the counters
they check are the ones the simulation actually produced.

## Citation

**If you use PureEdgeSim in your research, please cite the following papers. Kindly cite the papers rather than the GitHub repository.** This Python version is the same simulator, so it is cited with the same papers; add a link to the [Python repository](https://github.com/CharafeddineMechalikh/PureEdgeSim_Python) when you report which implementation you ran.

Mechalikh, C., Taktak, H., & Moussa, F. (2021). PureEdgeSim: A simulation framework for performance evaluation of cloud, edge and mist computing environments. *Computer Science and Information Systems*, 18(1), 43-66. https://doi.org/10.2298/CSIS200301042M

Mechalikh, C., Silem, A. E. H., Safavifar, Z., & Golpayegani, F. (2025). Quality matters: A comprehensive comparative study of edge computing simulators. *Simulation Modelling Practice and Theory*, 138, 103042. https://doi.org/10.1016/j.simpat.2024.103042

**BibTeX:**

```bibtex
@article{mechalikh2021pureedgesim,
  title   = {PureEdgeSim: A simulation framework for performance evaluation of cloud, edge and mist computing environments},
  author  = {Mechalikh, Charafeddine and Taktak, Hajer and Moussa, Faouzi},
  journal = {Computer Science and Information Systems},
  volume  = {18},
  number  = {1},
  pages   = {43--66},
  year    = {2021},
  doi     = {10.2298/CSIS200301042M}
}

@article{mechalikh2025quality,
  title   = {Quality matters: A comprehensive comparative study of edge computing simulators},
  author  = {Mechalikh, Charafeddine and Silem, Abd El Heq and Safavifar, Zahra and Golpayegani, Fatemeh},
  journal = {Simulation Modelling Practice and Theory},
  volume  = {138},
  pages   = {103042},
  year    = {2025},
  doi     = {10.1016/j.simpat.2024.103042}
}
```

## See also

- [PureEdgeSim (Java)](https://github.com/CharafeddineMechalikh/PureEdgeSim): the original
  framework, its live charts and its [documentation](https://charafeddinemechalikh.github.io/PureEdgeSim/docs/).
- [PureEdgeSim for Python documentation](https://charafeddinemechalikh.github.io/PureEdgeSim_Python/docs/):
  this manual, built from the `docs/` folder.
- [Issues](https://github.com/CharafeddineMechalikh/PureEdgeSim_Python/issues) for this port.

## License

GPL-3.0-or-later, the same license as PureEdgeSim (see [LICENSE](LICENSE)).
