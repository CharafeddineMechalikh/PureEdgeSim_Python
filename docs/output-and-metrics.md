---
description: "How to read the output of PureEdgeSim for Python: the 56 CSV columns, the per-scenario text report, and the run.json metadata."
---
# Output and metrics

After a run, the output folder holds a CSV of results, an optional text report, a `run.json`, and a snapshot copy of the five settings files. The column list lives in `pureedgesim/runner.py` as `COLUMNS`; import it with `from pureedgesim import COLUMNS`.

`launch()` returns one dict per scenario, keyed by these exact column names, so you can read results without touching the CSV:

```python
from pureedgesim import Simulation, COLUMNS

rows = Simulation("examples/default_settings").launch()
best = min(rows, key=lambda r: r["Average execution delay (s)"])
print(best["Orchestration architecture"], best["Average execution delay (s)"])
```

## Files written

- `Sequential_simulation.csv` for a sequential run, or `Parallel_simulation.csv` for a `--parallel` run. One header row plus one row per scenario.
- `Sequential_simulation.txt` / `Parallel_simulation.txt`, the per-scenario text report. Written only when `save_log_file` is true (the default).
- `run.json`, provenance for the run.
- `settings/`, a byte-for-byte snapshot of the five settings files, so the result folder is reproducible even if the originals later change.

Everything goes inside a timestamped subfolder of `output_folder` (named `%Y-%m-%d_%H-%M-%S`).

## The 56 CSV columns

The names are verbatim from `COLUMNS`. Values are rounded to four decimals where they are floats.

| # | Column | Meaning |
| --- | --- | --- |
| 0 | `Orchestration architecture` | The architecture of this scenario. |
| 1 | `Orchestration algorithm` | The algorithm name. |
| 2 | `Edge devices count` | The device count of this scenario. |
| 3 | `Total tasks execution delay (s)` | Sum of executed tasks' CPU time. |
| 4 | `Average execution delay (s)` | Column 3 divided by executed tasks. |
| 5 | `Total tasks waiting time (s)` | Sum of time spent in a node's queue before execution. |
| 6 | `Average waiting time (s)` | Column 5 divided by executed tasks. |
| 7 | `Number of generated tasks` | Total pre-generated tasks. |
| 8 | `Tasks successfully executed` | Status `SUCCESS`. |
| 9 | `Task not executed (No resources available or long waiting time)` | `INSUFFICIENT_RESOURCES` or `NO_OFFLOADING_DESTINATIONS`. |
| 10 | `Tasks failed (delay)` | `FAILED_DUE_TO_DELAY`. |
| 11 | `Tasks failed (device dead)` | `FAILED_DUE_TO_DEVICE_DEATH`. |
| 12 | `Tasks failed (mobility)` | `FAILED_DUE_TO_DEVICE_MOBILITY`. |
| 13 | `Tasks not generated due to the death of devices` | Tasks whose source device died before offloading (phase 0). |
| 14 | `Tasks not executed because a dependency failed` | `FAILED_BECAUSE_DEPENDENCY_FAILED` in a service graph. |
| 15 | `Total tasks executed (Cloud)` | Tasks whose destination is a cloud node. |
| 16 | `Successful tasks executed (Cloud)` | Cloud tasks that reached `SUCCESS`. |
| 17 | `Total tasks executed (Edge)` | Edge data center tasks. |
| 18 | `Successful tasks executed (Edge)` | Successful edge tasks. |
| 19 | `Total tasks executed (Mist)` | Mist (edge device) tasks. |
| 20 | `Successful tasks executed (Mist)` | Successful mist tasks. |
| 21 | `Network usage (s)` | Total link occupancy across WAN, MAN, and LAN. |
| 22 | `Wan usage (s)` | WAN link occupancy. |
| 23 | `Lan usage (s)` | LAN link occupancy. |
| 24 | `Total network traffic (MBytes)` | All transferred bits converted to megabytes. |
| 25 | `Containers wan usage (s)` | WAN time spent on container downloads. |
| 26 | `Containers lan usage (s)` | LAN time spent on container downloads. |
| 27 | `Average bandwidth per task (Mbps)` | Mean of the bandwidth samples seen during transfers. |
| 28 | `Average CPU usage (%)` | Mean CPU across non-sensor computing nodes. |
| 29 | `Average CPU usage (Cloud) (%)` | Mean CPU across cloud nodes. |
| 30 | `Average CPU usage (Edge) (%)` | Mean CPU across edge data centers. |
| 31 | `Average CPU usage (Mist) (%)` | Mean CPU across edge devices. |
| 32 | `Energy consumption of computing nodes (Wh)` | Total node energy: cloud plus edge plus mist. |
| 33 | `Average energy consumption (Wh/Computing node)` | Column 32 divided by (data centers plus devices). |
| 34 | `Cloud energy consumption (Wh)` | Sum over cloud nodes. |
| 35 | `Average Cloud energy consumption (Wh/Data center)` | Cloud energy per cloud DC. |
| 36 | `Edge energy consumption (Wh)` | Sum over edge data centers. |
| 37 | `Average Edge energy consumption (Wh/Data center)` | Edge energy per edge DC. |
| 38 | `Mist energy consumption (Wh)` | Sum over edge devices. |
| 39 | `Average Mist energy consumption (Wh/Device)` | Mist energy per device. |
| 40 | `WAN energy consumption (Wh)` | Energy charged on WAN links. |
| 41 | `MAN energy consumption (Wh)` | Energy charged on MAN links. |
| 42 | `LAN energy consumption (Wh)` | Energy charged on LAN links. |
| 43 | `WiFi energy consumption (Wh)` | Energy charged on Wi-Fi links. |
| 44 | `LTE energy consumption (Wh)` | Energy charged on cellular links. |
| 45 | `Ethernet energy consumption (Wh)` | Energy charged on Ethernet links. |
| 46 | `Dead devices count` | Devices whose battery emptied. |
| 47 | `Average remaining power (Wh)` | Mean remaining battery across alive battery devices. |
| 48 | `Average remaining power (%)` | Mean remaining percentage across alive battery devices. |
| 49 | `First edge device death time (s)` | Earliest `death_time`; `-1` if none died. |
| 50 | `List of remaining power (%) (only battery powered devices / 0 = dead)` | `-`-joined remaining percent per battery device. |
| 51 | `List of the time when each device died (s)` | `-`-joined death times of dead devices. |
| 52 | `Tasks skipped because their optional input failed` | Optional subtasks set to `SKIPPED`. |
| 53 | `Requests generated` | Distinct service-graph (or single-task) requests. |
| 54 | `Successful requests` | Requests with no failed subtask. |
| 55 | `Average request makespan (s)` | Mean completion time of successful requests. |

Columns 52 to 55 are the service-graph additions. For plain applications each task is one request, so 53 equals the generated-task count and 54 equals successes.

## The text report

When `save_log_file` is true, one block per scenario is appended to the `.txt`:

```text
Scenario: ALL / TRADE_OFF / 100 devices
  Generated tasks      : 6000
  Successful tasks     : 5998
  Failed (delay)       : 2
  Failed (death)       : 0
  Failed (mobility)    : 0
  Failed (dependency)  : 0
  Skipped (optional)   : 0
  Not executed         : 0
  Average delay (s)    : 0.0143
  Average CPU (%)      : 6.2
  Energy (Wh)          : 18.9
  Dead devices         : 0

Requests
  Generated            : 6000
  Successful           : 5998
  Average makespan (s) : 0.0201
```

The CLI prints a short one-line-per-scenario summary to stdout (architecture, algorithm, device count, tasks, successes, average delay, energy); the numbers it shows are columns 0, 1, 2, 4, 7, 8, and 32.

## run.json

`write_run_metadata` (`pureedgesim/metadata.py`) writes provenance next to the CSV:

```json
{
  "version": "0.3.0",
  "git_commit": "<sha of the checkout the run started from>",
  "random_seed": 42,
  "parallelism": false,
  "output_folder": "<absolute results folder>",
  "settings": {
    "simulation_parameters.properties": "<absolute source path>",
    "applications.xml": "...",
    "cloud.xml": "...",
    "edge_datacenters.xml": "...",
    "edge_devices.xml": "..."
  }
}
```

`version` is the installed package version, falling back to the one in `pyproject.toml`. `git_commit` is read from the checkout and is `"unknown"` outside a git tree. Because the five settings files are also copied into `settings/` beside it, a result folder records exactly what produced it. If any settings file is missing at copy time, the run stops with a `FileNotFoundError`.

## Cross-links

- The Java column set (the Python CSV keeps the same names and order): [Java Output and metrics](https://charafeddinemechalikh.github.io/PureEdgeSim/docs/output-and-metrics.html).
- Where each counter is incremented: [Task lifecycle](task-lifecycle.md).
