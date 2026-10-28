---
description: "Every simulation parameter the Python parser accepts, the five settings files, and the XML element structure of a scenario."
---
# Configuration

A scenario lives in a folder of five files. The parameter names are the same as the Java framework, so an existing settings folder is read as-is. This page documents what the Python parser accepts, the units, the defaults, and which parameters the Python port actually acts on.

The properties parser is `load_parameters` in `pureedgesim/parameters.py`. The XML parsers are in `pureedgesim/config.py`, entered through `load_settings(folder)`.

## How properties are read

`simulation_parameters.properties` is a plain `key=value` file. The loader ignores blank lines, lines starting with `#`, and lines without `=`. Keys are case-sensitive. There are no inline comments: everything after the `=` is part of the value.

Two behaviors are worth knowing:

- A missing or empty value falls back to the documented default. The one exception is `registry_mode`, which raises if the key is present but empty.
- An unknown key is not silently dropped. The loader prints a warning to stderr and, when the misspelling is within two edits of a known key, suggests the correct name. If you never want that warning, use only the keys listed below.

## Simulation, execution, and output

| Property | Attribute it sets | Default | Units and notes |
| --- | --- | --- | --- |
| `simulation_time` | `simulation_duration` | 10 | Minutes; the parser multiplies by 60. Must be > 0. |
| `update_interval` | `update_interval` | 1 | Seconds between a node's status tick (mobility, static energy, battery). >= 0.01. |
| `pause_length` | `pause_length` | 3 | Wall-clock seconds between sequential iterations. Cosmetic; >= 0. |
| `batch_size` | `batch_size` | 100 | Root tasks pushed into the event queue at once. > 0. |
| `random_seed` | `random_seed` | none | Whole number. Set it for reproducible runs; leave empty for a fresh run each time. |
| `parallel_simulation` | `parallel_simulation` | false | Runs scenarios in separate processes. Writes `Parallel_simulation.csv`. |
| `wait_for_all_tasks` | `wait_for_all_tasks` | true | Continue past `simulation_time` until every task is terminal (bounded). |
| `save_log_file` | `save_log_file` | true | Write the per-scenario `.txt` report. The CSV is always written. |
| `clear_output_folder` | `clear_output_folder` | false | Delete the output folder before the first iteration (skipped if it is the CWD). |
| `output_folder` | `output_folder` | `output` | Base results folder; a timestamped subfolder is created inside it. |

## Charts and logging (parsed, no effect in Python)

These keys are read and validated so a Java settings folder parses cleanly, but the Python port has no visualizer or per-event logger, so they do nothing:

| Property | State in Python |
| --- | --- |
| `display_real_time_charts` | Accepted, ignored. There is no Swing/chart window. |
| `auto_close_real_time_charts` | Accepted, ignored. |
| `charts_update_interval` | Accepted, validated (0.01 to 60), otherwise ignored. |
| `save_charts` | Accepted, ignored. No chart images are produced. |
| `deep_log_enabled` | Accepted, ignored. There is no `SimLog` equivalent. |

See [Python vs Java](python-vs-java.md) for the full gap list.

## Map and wireless range

| Property | Attribute it sets | Default | Units |
| --- | --- | --- | --- |
| `length` | `simulation_map_length` | 200 | Meters. The map spans `[0, width] x [0, length]`. > 0. |
| `width` | `simulation_map_width` | 200 | Meters. > 0. |
| `edge_devices_range` | `edge_devices_range` | 10 | Meters; device-to-device (mist) and orchestrator reach. > 0. |
| `edge_datacenters_coverage` | `edge_data_centers_range` | 200 | Meters; max device-to-edge-DC distance. > 0. |

## Orchestration

| Property | Attribute it sets | Default | Notes |
| --- | --- | --- | --- |
| `enable_orchestrators` | `enable_orchestrators` | false | False: each device decides locally. True: delegate to the node chosen by `deploy_orchestrator`. |
| `deploy_orchestrator` | `deploy_orchestrator` | `CLOUD` | `MIST` (the device), `CLOUD` (first cloud DC), `EDGE` (device's serving edge DC), or any other string picks the nearest node marked as an orchestrator. |
| `orchestration_architectures` | `orchestration_architectures` | `ALL` | Comma list. Valid: `CLOUD_ONLY`, `EDGE_ONLY`, `MIST_ONLY`, `MIST_AND_CLOUD`, `EDGE_AND_CLOUD`, `MIST_AND_EDGE`, `ALL`. |
| `orchestration_algorithms` | `orchestration_algorithms` | `TRADE_OFF` | Comma list. Built-in: `TRADE_OFF`, `ROUND_ROBIN`. A custom orchestrator may accept others. |

The sweep runs the cross product of architectures, then algorithms, then device counts. Each combination is one scenario, one CSV row.

## Edge device sweep

| Property | Attribute it sets | Default | Notes |
| --- | --- | --- | --- |
| `min_number_of_edge_devices` | `min_number_of_devices` | 100 | Start of the device sweep. > 0. |
| `max_number_of_edge_devices` | `max_number_of_devices` | 300 | End of the sweep, inclusive. >= min. |
| `edge_device_counter_size` | `devices_increment` | 100 | Step between counts. > 0. |

`SimulationParameters.device_counts` produces the list; if the range is empty it falls back to `[max]`.

## Registry (container download)

| Property | Attribute it sets | Default | Notes |
| --- | --- | --- | --- |
| `enable_registry` | `enable_registry` | false | When true and `registry_mode` is `CLOUD`, a non-cloud destination downloads the application container before running the first task of that app. |
| `registry_mode` | `registry_mode` | `CLOUD` | Validated to `CLOUD` or `CACHE`. Only `CLOUD` has an effect; `CACHE` performs no download in the default network model. |

The container transfer is modeled as a network send of size `container_size` over the route from the registry (first cloud node) to the destination. Once a node has run an application its id is added to `installed_containers`, so later tasks of the same app skip the download.

## Network model

| Property | Attribute it sets | Default | Notes |
| --- | --- | --- | --- |
| `realistic_network_model` | `realistic_network_model` | false | False: each hop is served in one step, at the clock of the second that sent it. True: transfers progress one interval at a time and share the link. |
| `network_update_interval` | `network_update_interval` | 1 | Seconds between the progress ticks of a busy link, in realistic mode. >= 0.001. |
| `one_shared_wan_network` | `one_shared_wan_network` | true | True: a WAN router fronts the cloud, and the hop from that router to the cloud data center is typed `IGNORE`, so it moves no counter. False: devices link straight to the cloud data center. Either way only the gateway edge data center (the one named `dc1`) hangs on the WAN, and the others reach it through the MAN ring. |

## Link rates and energies

Bandwidths are read in Mbps (the parser multiplies by 1e6), latencies in seconds, and energies in nanojoules per bit (converted to Watt-hours by `NANOJOULES_TO_WATT_HOURS = 2.7778e-13`). These are the values behind the LEAF network model.

| Property | Default (raw) | Attribute |
| --- | --- | --- |
| `wan_bandwidth`, `wan_latency`, `wan_nanojoules_per_bit` | 20, 0.06, 46.7 | `wan_bandwidth`, `wan_delay`, `wan_energy_per_bit` |
| `man_bandwidth`, `man_latency`, `man_nanojoules_per_bit` | 1000, 0.01, 0 | `man_bandwidth`, `man_delay`, `man_energy_per_bit` |
| `wifi_bandwidth`, `wifi_latency` | 1300, 0.005 | `wifi_bandwidth`, `wifi_delay` |
| `wifi_device_transmission_nanojoules_per_bit` | 283.17 | `wifi_device_transmission_energy` |
| `wifi_device_reception_nanojoules_per_bit` | 137.01 | `wifi_device_reception_energy` |
| `wifi_access_point_transmission_nanojoules_per_bit` | 23.8 | `wifi_access_point_transmission_energy` |
| `wifi_access_point_reception_nanojoules_per_bit` | 23.8 | `wifi_access_point_reception_energy` |
| `ethernet_bandwidth`, `ethernet_nanojoules_per_bit`, `ethernet_latency` | 1000, 40000, 0.002 | `ethernet_*` |
| `cellular_bandwidth`, `cellular_latency` | 100, 0.03 | `cellular_bandwidth`, `cellular_delay` |
| `cellular_device_transmission_nanojoules_per_bit` | 438.4 | `cellular_device_transmission_energy` |
| `cellular_device_reception_nanojoules_per_bit` | 51.97 | `cellular_device_reception_energy` |
| `cellular_base_station_nanojoules_per_bit_up_link` | 6200 | `cellular_base_station_uplink_energy` |
| `cellular_base_station_nanojoules_per_bit_down_link` | 20500 | `cellular_base_station_downlink_energy` (scaled by `CELLULAR_DOWNLINK_FACTOR`) |

## Validation rules

After parsing, `validate` raises `ValueError` (naming the file and the property) if any of these fails: `simulation_time` > 0; `update_interval` >= 0.01; `pause_length` >= 0; `batch_size` > 0; `length` > 0; `width` > 0; `edge_devices_range` > 0; `edge_datacenters_coverage` > 0; `min_number_of_edge_devices` > 0; `max` >= `min`; `edge_device_counter_size` > 0; `network_update_interval` >= 0.001; `charts_update_interval` in [0.01, 60]; `registry_mode` in {CLOUD, CACHE}; `orchestration_algorithms` not empty; every architecture in the allowed set.

## applications.xml

The root is `<applications>` with one or more `<application>` elements. Each application:

```xml
<application name="Health">
  <type>Hard Real-time</type>
  <rate>20</rate>
  <usage_percentage>20</usage_percentage>
  <latency>0.02</latency>
  <container_size>20</container_size>
  <request_size>20</request_size>
  <results_size>20</results_size>
  <task_length>500</task_length>
</application>
```

| Element | Meaning | Units |
| --- | --- | --- |
| `name` (attribute) | Application label; falls back to `id` then a positional name. | |
| `type` | Free text, usable by a custom orchestrator to branch. Default `Unknown`. | |
| `rate` | Tasks generated per minute per device. Must be > 0 (mean). | tasks/min |
| `usage_percentage` | Share of devices using this app. The last application may omit it and takes the remainder. | % |
| `latency` | Maximum tolerable end-to-end delay, the task deadline. | seconds |
| `container_size` | Application image size. | KB |
| `request_size` | Offloading request payload. | KB |
| `results_size` | Task result payload. | KB |
| `task_length` | Work per task. | MI (million instructions) |

Every numeric element may instead be a distribution element (see [Simulation models](models.md)):

```xml
<task_length distribution="lognormal" mean="25000" std="8000" min="5000"/>
```

An optional `<arrival>` element turns the workload into an inter-arrival model instead of evenly-spaced bursts:

```xml
<arrival>poisson</arrival>
<arrival>uniform</arrival>
<arrival distribution="weibull" shape="2" scale="3"/>
```

`poisson`/`exponential` give gaps with mean `60 / rate` seconds; `uniform`/`random` give gaps in `[0, 2 * mean]`; a distribution element gives gaps in seconds directly. An empty `<arrival>`, or `constant`/`even`, is the same as omitting it.

### Subtasks (service graphs)

An application may declare `<subtask>` children to become a multi-stage service graph instead of a single task. Each subtask is one `Task`; the whole set is one request that shares a deadline.

```xml
<subtask name="capture"    task_length="200"  results_size="5"   latency="2"/>
<subtask name="preprocess" depends_on="capture" task_length="600" results_size="20" latency="5"/>
<subtask name="detect"     depends_on="preprocess" task_length="4000" results_size="10" latency="10"/>
<subtask name="aggregate"  depends_on="classify,track" task_length="300" results_size="20" latency="15"/>
<subtask name="enhance"    depends_on="detect" task_length="100" optional="true"/>
```

Recognized attributes (anything else is an error): `name`, `depends_on`, `task_length`, `request_size`, `results_size`, `container_size`, `latency`, `optional`.

- `depends_on` is a comma-separated list of sibling subtask names. A subtask with no `depends_on` is a root and is released at generation time; the rest are released when all their parents return (see [Task lifecycle](task-lifecycle.md)).
- A numeric attribute overrides the application value for that subtask; an empty one inherits the application default. Values must be positive and finite.
- `optional="true"` marks a subtask that is skipped (not failed) when one of its dependencies fails. An optional subtask must have at least one dependency, or the parser rejects it.
- The parser rejects duplicate names, unknown dependencies, self-dependencies, and dependency cycles.

## cloud.xml

The root is `<cloud_data_centers>` with `<datacenter>` elements. A cloud data center may omit `<location>` (it defaults to the origin). All fields may be distributions.

```xml
<datacenter>
  <idleConsumption>0</idleConsumption>
  <maxConsumption>5776</maxConsumption>
  <isOrchestrator>false</isOrchestrator>
  <cores>200</cores>
  <mips>40000</mips>
  <ram>16000</ram>
  <storage>1000000</storage>
</datacenter>
```

| Element | Meaning | Units |
| --- | --- | --- |
| `periphery` | Only meaningful for edge DCs; a cloud DC is never peripheral. | bool |
| `isOrchestrator` | Mark this node as a candidate orchestrator. | bool |
| `cores`, `mips` | Compute capacity. `mips` is per core, in MI/s. | |
| `ram`, `storage` | Memory and cache, in MB. | MB |
| `idleConsumption`, `maxConsumption` | Idle and full-load power, in Watts (per hour in the energy model). | W |
| `location/x_pos`, `location/y_pos` | Fixed position on the map. | meters |

## edge_datacenters.xml

Same `<datacenter>` structure, but `<location>` is required (a missing one is an error), and two edge DCs may not share a location. An optional `<network_links>` block lists MAN links between edge DCs by name:

```xml
<network_links>
  <link><from>dc1</from><to>dc2</to></link>
</network_links>
```

Unmatched names are skipped when the topology is built. A `<datacenter>` with `<periphery>true</periphery>` can serve nearby devices.

## edge_devices.xml

The root is `<edge_devices>` with `<device>` elements, one per device type. The `<percentage>` of all types must sum to 100.

```xml
<device>
  <connectivity>wifi</connectivity>
  <mobility>true</mobility>
  <speed>1.8</speed>
  <minPauseDuration>100</minPauseDuration>
  <maxPauseDuration>400</maxPauseDuration>
  <minMobilityDuration>60</minMobilityDuration>
  <maxMobilityDuration>100</maxMobilityDuration>
  <battery>true</battery>
  <percentage>18</percentage>
  <batteryCapacity>18.75</batteryCapacity>
  <initialBatteryLevel>100</initialBatteryLevel>
  <idleConsumption>0.2</idleConsumption>
  <maxConsumption>5</maxConsumption>
  <isOrchestrator>false</isOrchestrator>
  <generateTasks>true</generateTasks>
  <cores>8</cores>
  <mips>25000</mips>
  <ram>4000</ram>
  <storage>256</storage>
</device>
```

| Element | Meaning | Units / allowed values |
| --- | --- | --- |
| `connectivity` | Access technology. | `wifi`, `cellular`, `ethernet` |
| `mobility` | Move the device. `<mobility>` may be a bool or a `<mobility model="...">` element. | bool |
| `speed` | Movement speed. | m/s |
| `min/maxPauseDuration` | Pause length before a move. | seconds |
| `min/maxMobilityDuration` | Move length before a pause. | seconds |
| `battery`, `batteryCapacity`, `initialBatteryLevel` | Battery model. | Wh and % |
| `percentage` | Share of devices of this type. | % (sum = 100) |
| `idleConsumption`, `maxConsumption` | Power draw. | W |
| `isOrchestrator`, `generateTasks` | Role flags. | bool |
| `cores`, `mips`, `ram`, `storage` | Compute. A device with `mips` or `cores` or `storage` of 0 is a sensor (generates tasks but cannot execute). | |
| `location/x_pos`, `location/y_pos` | Optional clustering position; may be distributions. Without it, devices scatter uniformly. | meters |

A `<mobility model="...">` element selects a named mobility model and passes options as attributes:

```xml
<mobility model="gauss-markov" alpha="0.8" std="15">true</mobility>
<mobility model="waypoint" waypoints="50,50;250,150;150,250">true</mobility>
```

See [Simulation models](models.md) for each model's options.

## Cross-links

- The same parameter list in the Java manual (identical names and units): [Java Configuration](https://charafeddinemechalikh.github.io/PureEdgeSim/docs/configuration.html).
- The distribution attribute grammar: [Simulation models](models.md).
