# Examples

Each runnable scenario has a folder here with its own README, and the settings
folder it uses:

| Example | Shows | Settings |
| --- | --- | --- |
| [Custom orchestrator](custom_orchestrator/README.md) | Replacing the placement policy with a subclass of `Orchestrator` | `default_settings/` |
| [Distributions and mobility](distributions_and_mobility/README.md) | Overriding constants by probability distributions and mobility models from Python | `default_settings/` |
| [Graph partitioning](graph_partitioning/README.md) | Cutting the subtasks of a service graph into balanced partitions with graph theory | `partitioning_settings/` |
| [Genetic partitioning](genetic_partitioning/README.md) | Searching the node of every subtask with a genetic algorithm | `partitioning_settings/` |

`default_settings/` holds the five PureEdgeSim settings files used by the first
two examples. `partitioning_settings/` adds a service graph application for the
last two, and both share the solvers in
`src/pureedgesim/partitioning.py`.

From the repository root, after `pip install -e .`:

```bash
python examples/custom_orchestrator/custom_orchestrator.py
```

The same scripts run without installing the package, as long as `src` is on the
path:

```bash
PYTHONPATH=src python examples/graph_partitioning/graph_partitioning.py
```

Start with [Custom orchestrator](custom_orchestrator/README.md) for the
orchestrator API, then [Graph partitioning](graph_partitioning/README.md) and
[Genetic partitioning](genetic_partitioning/README.md) for service graphs. The
main [README](../README.md) documents the settings files, the distributions, and
the output columns.
