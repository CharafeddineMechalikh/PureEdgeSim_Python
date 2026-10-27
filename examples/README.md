# Examples

Every runnable scenario is a self-contained folder: its Python script, a
`README.md` that explains the mechanism and reads out the measured results, the
`settings/` it runs with, and an `output/` folder for its CSVs. The table gives
the Java example each one mirrors, so a scenario can be compared across the two
implementations.

| Example | Shows | Settings | Java counterpart |
| --- | --- | --- | --- |
| [extension_points](extension_points/README.md) | All eight `set_custom_...` hooks in one scenario | `extension_points/settings/` | [Example 1](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example1) |
| [distributions_and_mobility](distributions_and_mobility/README.md) | Distributions and a mobility model driven from Python | `distributions_and_mobility/settings/` | [Example 2](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example2) |
| [edge_cooperation](edge_cooperation/README.md) | Edge data centers that cooperate through orchestrators | `edge_cooperation/settings/` | [Example 3](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example3) |
| [custom_computing_node](custom_computing_node/README.md) | A custom computing node with its own events | `custom_computing_node/settings/` | [Example 4](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example4) |
| [custom_orchestrator](custom_orchestrator/README.md) | Replacing the placement policy with a subclass of `Orchestrator` | `custom_orchestrator/settings/` | [Example 5](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example5) |
| [custom_settings_parallel](custom_settings_parallel/README.md) | Custom settings files and a parallel sweep | `custom_settings_parallel/settings/` | [Example 6](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example6) |
| [clustering_and_caching](clustering_and_caching/README.md) | Clustering and cooperative container caching | `clustering_and_caching/settings/` | [Example 7](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example7) |
| [graph_partitioning](graph_partitioning/README.md) | Cutting a service graph into balanced partitions with graph theory | `graph_partitioning/settings/` | [Example 9](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example9) |
| [genetic_partitioning](genetic_partitioning/README.md) | Searching the node of every subtask with a genetic algorithm | `genetic_partitioning/settings/` | [Example 10](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example10) |
| [q_learning](q_learning/README.md) | Tabular Q-learning orchestration | `q_learning/settings/` | [Example 11](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example11) |
| [multi_access_mec](multi_access_mec/README.md) | Multi-access MEC with an access-aware orchestrator | `multi_access_mec/settings/` | [Example 12](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example12) |
| [fog_layers](fog_layers/README.md) | Multi-layer fog for a smart home | `fog_layers/settings/` | [Example 13](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example13) |
| [mist_only_q_learning](mist_only_q_learning/README.md) | Q-learning with the cloud and edge actions removed | `mist_only_q_learning/settings/` | [Example 14](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example14) |
| [edge_orchestrated_q_learning](edge_orchestrated_q_learning/README.md) | Guided reinforcement learning over several layers | `edge_orchestrated_q_learning/settings/` | [Example 15](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example15) |
| [softmax_orchestrator](softmax_orchestrator/README.md) | A Boltzmann policy over the same value table | `softmax_orchestrator/settings/` | [Example 16](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example16) |
| [contextaware_drl](contextaware_drl/README.md) | Context-aware deep reinforcement offloading | `contextaware_drl/settings/` | [Example 17](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example17) |
| [ant_colony](ant_colony/README.md) | Ant colony offloading over pheromone scores | `ant_colony/settings/` | [Example 18](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example18) |
| [priority_placement](priority_placement/README.md) | Deadline-aware placement by task criticality | `priority_placement/settings/` | [Example 19](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example19) |
| [multi_objective](multi_objective/README.md) | Multi-objective reinforcement learning | `multi_objective/settings/` | [Example 20](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example20) |
| [container_cache](container_cache/README.md) | Storage-aware container caching with LRU eviction | `container_cache/settings/` | [Example 21](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example21) |
| [self_clustering](self_clustering/README.md) | Self-organizing device clusters with an elected head | `self_clustering/settings/` | [Example 22](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example22) |
| [custom_models](custom_models/README.md) | A custom nodes generator, task generator, topology creator and simulation manager | `custom_models/settings/` | [Example 23](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example23) |
| [dynamic_repartition](dynamic_repartition/README.md) | Repartitioning a service graph while the simulation runs | `dynamic_repartition/settings/` | [Example 24](https://github.com/CharafeddineMechalikh/PureEdgeSim/tree/master/PureEdgeSim/examples/Example24) |

Java `Example8` (fuzzy logic orchestration) has no Python counterpart: it needs the
jFuzzyLogic jar that the Java build bundles, and this package takes no third-party
dependency. [custom_orchestrator](custom_orchestrator/README.md) exercises the same
injection point with a distance rule.

Two settings folders are shared rather than owned by an example:
`default_settings/` is the reference scenario the CLI and the test fixtures load,
and `partitioning_settings/` is the service-graph scenario the docs pages cite.

From the repository root, after `pip install -e .`:

```bash
python examples/q_learning/q_learning.py
```

The same scripts run without installing the package, as long as `src` is on the
path:

```bash
PYTHONPATH=src python examples/graph_partitioning/graph_partitioning.py
```

Add `--parallel` to sweep several scenarios at once, as
[custom_settings_parallel](custom_settings_parallel/README.md) does.

Start with [extension_points](extension_points/README.md) for the structure of a
simulation, [edge_cooperation](edge_cooperation/README.md) for edge coordination,
and [graph_partitioning](graph_partitioning/README.md) with
[genetic_partitioning](genetic_partitioning/README.md) for service graphs. The
main [README](../README.md) documents the settings files, the distributions and
the output columns; [docs/](../docs/README.md) is the full manual.
