---
description: "The map from the Java PureEdgeSim API to the Python port: which class becomes which module, how the build and test commands change, and what the Python port does not have yet."
---
# Python vs Java

PureEdgeSim for Python is a faithful port of the Java simulator: same scenario model, same parameter names, same CSV columns. This page is for readers coming from Java. It maps the API, translates the commands, and lists the honest gaps.

## Class to module map

Java uses many small classes; Python groups them into modules. The table lists the notable ones.

| Java package and class | Python module and name |
| --- | --- |
| `simulationengine.PureEdgeSim` | `engine.Engine` |
| `simulationengine.Event`, `FutureQueue`, `SimEntity` | `engine.Event`, `engine.FutureQueue`, `engine.SimEntity` |
| `distribution.Distribution` and its subclasses | `distribution.Distribution` and matching subclasses |
| `distribution.Randomness` | `randomness.Randomness` |
| `scenariomanager.SimulationParameters` | `parameters.SimulationParameters` (a dataclass) |
| `scenariomanager.ParametersParser`, `FileParserAbstract`, `XmlFileParser`, `DistributionReader` | `parameters.load_parameters`, `distribution.distribution_from_element` |
| `scenariomanager.ApplicationFileParser`, `ComputingNodesParser`, `DatacentersParser`, `EdgeDevicesParser` | `config.load_settings`, `config.load_applications`, `config.load_cloud`, `config.load_edge_datacenters`, `config.load_devices` |
| `scenariomanager.Scenario` | `manager.Scenario` |
| `taskgenerator.Application`, `Subtask` | `config.Application`, `config.Subtask` |
| `taskgenerator.Task`, `DefaultTask`, `TaskAbstract` | `tasks.Task` |
| `taskgenerator.DefaultTaskGenerator`, `TaskGenerator` | `tasks.DefaultTaskGenerator` |
| `datacentersmanager.ComputingNode`, `DefaultComputingNode`, `AbstractNode`, `EnergyAwareNode`, `LocationAwareNode`, `NetworkingNode` | `nodes.ComputingNode` |
| `datacentersmanager.ComputingNodeNull` | `nodes.ComputingNode.NULL` |
| `datacentersmanager.DefaultComputingNodesGenerator`, `ComputingNodesGenerator`, `DataCentersManager` | `topology.ComputingNodesGenerator` |
| `datacentersmanager.DefaultTopologyCreator`, `TopologyCreator` | `topology.DefaultTopologyCreator` |
| `datacentersmanager.Router` | `nodes.Router` |
| `energy.EnergyModelComputingNode` | `nodes.EnergyModelComputingNode` |
| `locationmanager.MobilityModel` and subclasses, `Location` | `mobility.MobilityModel`, its subclasses, `mobility.Location` |
| `network.NetworkModel`, `DefaultNetworkModel` | `network.DefaultNetworkModel` |
| `network.NetworkLink` and its up/down/type subclasses (`NetworkLinkWifiUp`, `NetworkLinkCellularDown`, ...) | `network.NetworkLink` plus the `LinkType` (`WAN`, `MAN`, `LAN`, `IGNORE`) and `LinkTechnology` enums |
| `network.InfrastructureGraph`, `TransferProgress` | `network.InfrastructureGraph`, `network.TransferProgress` |
| `taskorchestrator.Orchestrator`, `DefaultOrchestrator` | `orchestrator.Orchestrator`, `orchestrator.DefaultOrchestrator` |
| `simulationmanager.Simulation`, `SimulationAbstract` | `runner.Simulation` |
| `simulationmanager.DefaultSimulationManager`, `SimulationManager` | `manager.SimulationManager` |
| `simulationmanager.RunMetadata` | `metadata.write_run_metadata` |
| `MainApplication` | `cli.main` |
| `simulationmanager.ChartsGenerator`, all of `simulationvisualizer.*` | not ported (see gaps) |
| `simulationmanager.SimLog` | not ported (see gaps) |
| `simulationmanager.SimulationThread` | replaced by `runner.Simulation._run_parallel` with a `ProcessPoolExecutor` |

A few naming differences worth knowing:

- Java `getMips()` maps to the Python attribute `mips_per_core` (it is always per core; `total_mips` is the product with `cores`).
- An application's result size is `results_size` in `config.Application` (mirroring the XML) but `result_size` on a `tasks.Task` (singular).
- The Java `TaskType`/tier concept is the Python `NodeType` enum: `CLOUD`, `EDGE_DATACENTER`, `EDGE_DEVICE`, `ROUTER`.
- Java's integer event tags are the Python `EventType` enum in `nodes`.

## Build and run commands

| Task | Java | Python |
| --- | --- | --- |
| Install/build | `mvn install` (or `mvn package`) | `pip install -e ".[test]"` |
| Run the bundled scenario | `mvn exec:java -Dexec.mainClass="com.mechalikh.pureedgesim.MainApplication"` | `pureedgesim run --settings examples/default_settings` |
| Run one example | `mvn exec:java -Dexec.mainClass="...Example1"` | `python examples/custom_orchestrator/custom_orchestrator.py` |
| Configure the scenario | edit `PureEdgeSim/settings/` | edit `examples/default_settings/` (or pass `--settings <folder>`) |

The Python package has no runtime dependencies (Maven pulls in libraries; here the standard library is enough). Each example folder carries the settings it runs with, so a scenario is self-contained; [Examples](../examples/README.md) lists the runnable scripts and the Java example each one mirrors.

## Tests

| Task | Java | Python |
| --- | --- | --- |
| Framework | JUnit | `pytest` |
| Run the suite | `mvn test` | `pytest` |
| Coverage | JaCoCo (`jacoco.xml`) | `pytest --cov=pureedgesim` (needs `pytest-cov`) |
| Shared fixtures | test utility classes | `tests/conftest.py` fixtures (`parameters`, `files`, `manager`) |

The Python tests build a real `SimulationManager` from `examples/default_settings/` and assert on the resulting `Task` states and metrics, the same spirit as the JUnit suite. See [Contributing](contributing-guide.md).

## What the Python port does not have yet

These are real gaps against the Java simulator, verified against `src/pureedgesim/`.

- **No visualizer or charts.** There is no `simulationvisualizer` equivalent and no `ChartsGenerator`. The properties `display_real_time_charts`, `auto_close_real_time_charts`, `charts_update_interval`, and `save_charts` are parsed and validated but do nothing. No live map/CPU/WAN/tasks charts and no saved chart images.
- **No per-event log.** `deep_log_enabled` is parsed but there is no `SimLog`; nothing reads the flag.
- **No pluggable registry model.** Container download is modeled in the core, but only in `registry_mode = CLOUD` over the default network (the first cloud node is the registry, and a node that has run an app caches it in `installed_containers`). The `CACHE` mode is accepted by the validator and implemented in the [`container_cache` example](../examples/container_cache/README.md) instead of in the core, because there is no separate registry class to subclass the way Java has one.
- **No fuzzy logic orchestrator.** The two Java examples that need the jFuzzyLogic jar, `Example5` and `Example8`, have no Python counterpart; the package takes no third-party dependency. [`custom_orchestrator`](../examples/custom_orchestrator/README.md) exercises the same injection point with a distance rule.
- **Two `SimulationParameters` fields are not read from properties.** `enable_location_updates` and `settings_folder` exist on the dataclass (defaults `True` and `"settings"`), but `load_parameters` never assigns them from the file.
- **The two device-list columns are written differently.** Columns 50 and 51 hold the remaining battery of each device and the death times. Java wraps them in brackets, `[99.13- 99.77- ...]`, and writes `[]` when empty; Python joins with `-` and writes an empty field. The numbers are the same, the punctuation is not, so compare those two columns by parsing rather than by diffing the text.
- **A heuristic example settles on a nearby, not identical, mix.** Both simulators draw placement decisions from a random stream, and the two streams are not the same generator. Run the same settings and seed side by side and the totals, the energy and the traffic agree to within a few percent, while the split between the three tiers and the count of delay failures move with the sample. The deterministic scenario, the [trace replay](../examples/trace_replay/README.md) in its recorded mode, draws nothing and gives the same 8819 requests, the same 3180 successes, the same compute total and the same traffic as Java. Two columns are not identical: the total waiting time differs by a hundredth of a percent and the energy of the run by two hundredths.

What the Python port does have, matching Java:

- A parallel executor (`--parallel`, ProcessPoolExecutor), producing `Parallel_simulation.csv` and pooled `run.json`.
- Nine mobility models, sixteen distributions, service graphs with dependencies and optional subtasks, request deadline accounting, battery and static/dynamic energy, and the full WAN/MAN/LAN Wi-Fi/cellular/Ethernet network model.
- Eight `set_custom_...` injection points, one per pluggable class in Java: mobility model, orchestrator, network model, computing-nodes generator, topology creator, task generator, computing node, and simulation manager. See [Architecture](architecture.md).

## Cross-links

- The Java manual home: [Java docs](https://charafeddinemechalikh.github.io/PureEdgeSim/docs/).
- Replacing the mobility model or orchestrator in Python: [Simulation models](models.md) and [Writing orchestrators](orchestrators.md).
