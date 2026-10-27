---
description: "Answers to the questions researchers ask most about PureEdgeSim for Python: failures, empty results, reproducibility, parallelism, and the missing features."
---
# FAQ

## Why did my tasks fail?

Failures are counted in separate CSV columns, so start there. Each has a distinct cause and a distinct `TaskStatus`.

- `Tasks failed (delay)` (column 10): `total_delay` exceeded the task's `max_latency`, or the request missed its end-to-end `request_deadline`. Lower the `latency` in `applications.xml`, give nodes more `mips`, or reduce the workload `rate`.
- `Tasks failed (device dead)` (column 11): the source, orchestrator, or destination lost its battery. Check the battery fields in `edge_devices.xml` and the consumption parameters.
- `Tasks failed (mobility)` (column 12): an edge-device orchestrator or destination moved outside `edge_devices_range` or `edge_datacenters_coverage`. Raise the range, slow the devices, or move the edge DCs closer.
- `Task not executed (No resources available or long waiting time)` (column 9): the destination had insufficient RAM or storage (`INSUFFICIENT_RESOURCES`) or the orchestrator returned no eligible node (`NO_OFFLOADING_DESTINATIONS`). Add cores, RAM, or storage; widen the architecture.
- `Tasks not executed because a dependency failed` (column 14): a service-graph parent failed, so its required children never ran. Column 52 (`Tasks skipped ...`) counts the optional children that were skipped instead.

## Why are there no charts in the output?

The Python port has no visualizer. `display_real_time_charts` and `save_charts` are read and validated, but nothing renders a window or writes an image. The outputs are the CSV, the `.txt` report, and `run.json`. To plot results, read the CSV (`Sequential_simulation.csv`) or the dict returned by `Simulation.launch()`. This is a documented gap; see [Python vs Java](python-vs-java.md).

## Why did my run produce zero tasks?

Two common causes. First, `simulation_time` is in minutes in the properties file; a value below the first workload minute produces no tasks (the default task burst is per minute). Second, the workload is generated only for devices whose `generateTasks` is true and that are alive at generation time. A sensor type (zero `mips`/`cores`) still generates tasks but cannot execute them, so set `generateTasks` false for pure sensors if you do not want that traffic.

## Why did I get "unknown property" warnings?

The parser prints a warning to stderr for any `key` not in its known set, and suggests the closest name when the misspelling is within two edits. It never guesses silently. The warning names the file and the key. Fix the spelling or remove the line; a key the Java framework knows but the Python parser does not is a real difference worth checking against [Configuration](configuration.md).

## Are results reproducible?

Yes, when you set a seed. `random_seed` (in the properties file, or `--seed`, or `parameters.random_seed`) drives every random draw: task sizes and lengths, arrival times, node capacities, device positions, and mobility. Same seed plus same scenario gives the same rows. Leave it empty for a fresh run each time. Vary the seed to get independent repetitions.

## Is a parallel run the same as a sequential one?

It should be. `run_scenario` re-seeds `Randomness` from `parameters.random_seed` and the scenario index before each iteration, in both modes, so each worker derives the same stream the main thread would. The differences are the output filename (`Parallel_simulation.csv`) and that parallel results are appended in a batch at the end rather than as each scenario finishes.

## How many mobility models are there, and how do I pick one?

Nine classes behind eleven names (`random-waypoint`/`default` and `group`/`rpgm` are aliases). Set one per device type with a `<mobility model="...">` element, or override the default class in code with `Simulation.set_custom_mobility_model`. `pureedgesim models` prints every name; the full name-to-class mapping and each model's options are in [Simulation models](models.md).

## How do I add a service graph or optional subtask?

Add `<subtask>` children to an application. A subtask is optional when it can be dropped if a dependency fails; write `optional="true"` and give it at least one `depends_on`. When a parent returns, its `result_size` is added to the child's `request_size` so intermediate data crosses the network. See [Task lifecycle](task-lifecycle.md).

## Can I plug in my own network model, task generator, or topology?

Yes. `Simulation` has a setter for each of them: `set_custom_network_model`, `set_custom_computing_nodes_generator`, `set_custom_topology_creator`, `set_custom_task_generator`, `set_custom_computing_node`, and `set_custom_simulation_manager`, next to the older `set_custom_mobility_model` and `set_custom_orchestrator`. Pass a subclass of the default class, with the same constructor arguments, and the manager builds its models through it. The table of constructors each hook calls is in [Architecture](architecture.md).

## A mist device that is a good candidate is never chosen. Why?

`offloading_is_possible` requires a mist node to be within `edge_devices_range` of the source device (or, with `enable_orchestrators`, of the orchestrator), to be alive, and to not be a sensor. If `edge_devices_range` is small (the default is 10 m), most device pairs are out of range. Raise it, or place device types so they cluster.

## Where do I go next?

- Full parameter reference: [Configuration](configuration.md).
- The event flow that produces every counter: [Task lifecycle](task-lifecycle.md).
- Writing a placement policy: [Writing orchestrators](orchestrators.md).
