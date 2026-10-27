---
description: "How to implement a placement policy in PureEdgeSim for Python by subclassing Orchestrator and overriding find_computing_node and results_returned."
---
# Writing orchestrators

The orchestrator decides where each task executes. The built-in `DefaultOrchestrator` implements two policies, `TRADE_OFF` and `ROUND_ROBIN`. To use your own, subclass `Orchestrator` from `pureedgesim/orchestrator.py` and pass the class to `Simulation.set_custom_orchestrator`.

The orchestrator is constructed by the manager after the topology exists and before the workload runs, and it sees the whole scenario.

## The base class

```python
class Orchestrator:
    def __init__(self, manager): ...
    def initialize(self, architecture: str): ...
    def orchestrate(self, task, application_id: int = 0) -> ComputingNode | None: ...
    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int: ...
    def trade_off(self, eligible, task) -> int: ...
    @staticmethod
    def score(node, task, assigned: int = 0) -> float: ...
    def offloading_is_possible(self, node, task) -> bool: ...
    def results_returned(self, task) -> None: ...
```

State you can rely on after `initialize`:

- `self.manager`, the `SimulationManager`, giving `computing_nodes`, `scenario`, `parameters`, `applications`, `network`, and `edge_devices`.
- `self.architecture_layers`, the tuple of `NodeType`s for the scenario architecture.
- `self.candidates`, every node whose type is in those layers and is not a sensor.
- `self.history`, a dict mapping each candidate's index to how many tasks this algorithm placed on it.

`orchestrate` is what the manager calls at the decision step. It calls `find_computing_node([task], algorithm, application_id)`, and on a non-negative index sets `task.destination`, caches the placement on the source device, and returns the node. A return of `-1` becomes a `None` destination and an `NO_OFFLOADING_DESTINATIONS` failure.

## The built-in scoring

`find_computing_node` filters `self.candidates` by `offloading_is_possible`, then:

- `ROUND_ROBIN` picks the eligible node with the smallest `history` count.
- anything else falls through to `trade_off`, which picks the lowest `score`. On a tie, the candidate earliest in `self.candidates` wins.

`score(node, task, assigned)` is:

```text
(assigned + 1) * weight * task.length / node.mips_per_core
```

The per-tier `weight` is `{CLOUD: 1.8, EDGE_DATACENTER: 1.2, EDGE_DEVICE: 1.3}` (the `WEIGHTS` map). Lower is better, so a fast, lightly loaded node scores low. `assigned` is the node's placement count under this algorithm.

`offloading_is_possible(node, task)` encodes eligibility:

- A `CLOUD` node is eligible if cloud is in the architecture layers.
- An `EDGE_DATACENTER` is eligible only if it is the device's serving edge DC or the orchestrator's serving edge DC, and edge is in the layers.
- An `EDGE_DEVICE` is eligible if mist is in the layers, it is not a sensor, it is alive, and it is within `edge_devices_range` of the device (or, with `enable_orchestrators`, of the orchestrator).

## A minimal custom policy

This is the complete "nearest node" example from `examples/custom_orchestrator/`. It overrides only `find_computing_node`, keeping everything else from the base class.

```python
from pureedgesim import Orchestrator, NodeType

CLOUD_IS_FAR = 1e9

class NearestNodeOrchestrator(Orchestrator):
    """The closest eligible node, the least loaded one breaking the tie."""

    def find_computing_node(self, tasks, algorithm, application_id):
        task = tasks[0]
        device = task.source_device
        eligible = [(index, node) for index, node in enumerate(self.candidates)
                    if self.offloading_is_possible(node, task)]
        if not eligible:
            return -1
        index, _ = min(eligible, key=lambda pair: (
            CLOUD_IS_FAR if pair[1].type == NodeType.CLOUD else device.distance_to(pair[1]),
            self.history[pair[0]],
        ))
        self.history[index] += 1
        return index
```

Plug it in and run the default scenario:

```python
from pathlib import Path
from pureedgesim import Simulation, load_parameters, load_settings

settings = Path("examples/default_settings")
parameters = load_parameters(settings / "simulation_parameters.properties")
parameters.min_number_of_devices = parameters.max_number_of_devices = 20
parameters.devices_increment = 1
parameters.orchestration_architectures = ["ALL"]
parameters.orchestration_algorithms = ["TRADE_OFF"]
parameters.random_seed = 7
parameters.save_log_file = False

simulation = Simulation(settings, "output", parameters, load_settings(settings))
simulation.set_custom_orchestrator(NearestNodeOrchestrator)
rows = simulation.launch()
```

Pass the class, not an instance. The manager calls `your_class(self)` itself, so the constructor signature must stay `__init__(self, manager)`.

## Reacting to results

Override `results_returned(task)` to update state when a task completes. It is called from `_results_returned` after the success/failure bookkeeping, with the task's final `status`, `destination`, and delays populated. It returns nothing and is the right place to track, for instance, which nodes meet latency and bias future placements.

## Placing service-graph subtasks

For a service graph, each subtask is a separate `orchestrate` call, and the manager reuses a device's cached placement (`application_placed`) until it is invalidated. If you want each subtask of one request decided on its own, clear the cache in `orchestrate`:

```python
class PerSubtaskOrchestrator(Orchestrator):
    def orchestrate(self, task, application_id: int = 0):
        destination = super().orchestrate(task, application_id)
        task.source_device.application_placed = False
        return destination

    def find_computing_node(self, tasks, algorithm, application_id):
        task = tasks[0]
        # Decide per subtask, for example using task.subtask_name and the
        # dependency graph from pureedgesim.partitioning.ServiceGraph.
        return super().find_computing_node(tasks, algorithm, application_id)
```

The two example orchestrators under `examples/graph_partitioning/` and `examples/genetic_partitioning/` do exactly this: they read the application's `ServiceGraph`, compute a static partition plan in `initialize`, and place each subtask by its `subtask_name`, falling back to `trade_off` when the planned node is no longer eligible.

## Available algorithm names

The `algorithm` argument is `scenario.orchestration_algorithm`, so it is one of the strings in `orchestration_algorithms`. `TRADE_OFF` and `ROUND_ROBIN` are handled by the base class. A custom orchestrator can recognize its own names by branching inside `find_computing_node`, and you list those names in the properties file or with `--algorithms` on the CLI.

## Cross-links

- The Java orchestrator model (`taskorchestrator` package): [Java Writing orchestrators](https://charafeddinemechalikh.github.io/PureEdgeSim/docs/writing-orchestrators.html).
- Where in the event flow the decision happens: [Task lifecycle](task-lifecycle.md).
- The gap list for pluggable models beyond the orchestrator and mobility hook: [Python vs Java](python-vs-java.md).
