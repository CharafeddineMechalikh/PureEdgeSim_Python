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
and the same 51-column CSV, so a study run here can be placed side by side with the same
study run in [PureEdgeSim (Java)](https://github.com/CharafeddineMechalikh/PureEdgeSim).

Install it with `pip`, import it as `pureedgesim`, and run it with the `pureedgesim`
command; the classes, parameters and reported columns keep their PureEdgeSim names.

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

```
Ran 6 scenario(s), results in output\2026-10-25_13-03-51
  MIST_AND_EDGE  TRADE_OFF        50 tasks=  5800 ok=  4415 avg_delay=0.1749 energy=28.9179
  MIST_AND_EDGE  ROUND_ROBIN      50 tasks=  5800 ok=  4621 avg_delay=0.1901 energy=29.2087
  ALL            TRADE_OFF        50 tasks=  5800 ok=  4688 avg_delay=0.1935 energy=29.6809
  ALL            ROUND_ROBIN      50 tasks=  5800 ok=  4670 avg_delay=0.1969 energy=29.8658
  CLOUD_ONLY     TRADE_OFF        50 tasks=  5800 ok=   600 avg_delay=0.1586 energy=34.0703
  CLOUD_ONLY     ROUND_ROBIN      50 tasks=  5800 ok=   600 avg_delay=0.1586 energy=34.0703
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

Subclass `Orchestrator` and hand the class to `Simulation.set_custom_orchestrator`.
`examples/custom_orchestrator.py` places every task on the node closest to its
device instead of balancing the load:

```
TRADE_OFF (default)      tasks= 1035 ok=  776 avg_delay=0.1816   cloud= 116 edge= 739 mist= 180 energy=11.5143
nearest node             tasks= 1035 ok=  781 avg_delay=0.2097   cloud=   0 edge= 640 mist= 395 energy=11.3705
```

`examples/distributions_and_mobility.py` replaces the constants of the settings
files by probability distributions and lets the devices move with the Gauss-Markov
model:

```
constants, static      tasks= 1035 ok=  776 delay=0.1816   failed(delay)= 259 failed(mobility)=   0 energy=11.5143
distributions, mobile  tasks= 1006 ok=  742 delay=0.2045   failed(delay)= 263 failed(mobility)=   1 energy=10.8892
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
| `applications.xml` | task rates, sizes, lengths and arrival patterns |

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

`Sequential_simulation.csv` (or `Parallel_simulation.csv`) holds the 51 PureEdgeSim
columns, in the Java order, plus a `Sequential_simulation.txt` summary per scenario
when `save_log_file=true`. `pureedgesim.runner.COLUMNS` is that column list.

## Faithfulness notes

The port keeps a few behaviours of the Java framework that look like bugs but are
load-bearing for comparability, each marked with a comment where it is implemented:

- the wireless energy model charges a transmitting device with the *reception* rate
  and the other way round (`EnergyModelComputingNode.updateWirelessEnergyConsumption`);
- the CSV column "Network usage (s)" holds the LAN usage only, while the text report
  prints LAN, MAN and WAN together;
- "Tasks not generated due to the death of devices" is always 0, because the whole
  workload is generated before the simulation starts;
- the number of devices of each type is truncated, and the missing devices are
  filled with instances of the last device type;
- a device that runs out of battery stops updating and dies exactly once; the report
  scans the devices instead of using a counter.

Deliberate differences: there are no live Swing charts (the `display_real_time_charts`
property is ignored, and `save_charts` is not implemented), parallel mode uses
processes rather than threads, and a custom mobility model or orchestrator is a
Python class instead of a Java one.

## Tests

```bash
pip install -e .[test]
pytest              # 225 tests, the core plus the settings readers and the CLI
```

The integration tests build real managers and run them to the end, so the counters
they check are the ones the simulation actually produced.

## Citation

**If you use PureEdgeSim in your research, please cite the following papers. Kindly cite the papers rather than the GitHub repository.** This Python version is the same simulator, so it is cited with the same papers; add a link to the [Python repository](https://github.com/CharafeddineMechalikh/PureEdgeSim_Python) when you report which implementation you ran.

Mechalikh, C., Taktak, H., & Moussa, F. (2021). PureEdgeSim: A simulation framework for performance evaluation of cloud, edge and mist computing environments. *Computer Science and Information Systems*, 18(1), 43-66. https://doi.org/10.2298/CSIS200301042M

Mechalikh, C., Silem, A. E. H., Safavifar, Z., & Golpayegani, F. (2025). Quality matters: A comprehensive comparative study of edge computing simulators. *Simulation Modelling Practice and Theory*, 138, 103042. https://doi.org/10.1016/j.simpat.2024.103042

BibTeX:

```gradle
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
  framework, its live charts and its [documentation](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/docs).
- [Issues](https://github.com/CharafeddineMechalikh/PureEdgeSim_Python/issues) for this port.

## License

GPL-3.0-or-later, the same license as PureEdgeSim (see [LICENSE](LICENSE)).
