# Genetic partitioning: searching a subtask placement

## What it shows

The same service graph as the [graph partitioning example](../graph_partitioning/README.md),
solved differently. Instead of deriving a cut from the structure of the graph,
`GeneticPartitioner` searches the node of every subtask:

- a chromosome holds one gene per subtask, and a gene names a candidate node
  (a mist device, an edge data center, or the cloud);
- fitness is the estimated makespan of the pipeline, plus part of the time spent
  transferring results between nodes and of the excess work of the busiest node
  over the average of the nodes actually used;
- selection is by tournament, crossover is uniform, mutation flips one gene, and
  the best chromosome of each generation is kept.

Subtasks that receive the same node form the same partition, so the search
implicitly decides where to cut the graph.

The plan is static: it is computed once, from the mean task lengths and result
sizes, before any device moves. When the chosen node is not eligible for a
request (a mist device that is now out of range, for example), the subtask falls
back to `TRADE_OFF`.

`GeneticOrchestrator` clears the application placement after each decision, as
the graph example does, so every subtask is routed on its own.

## The scenario

`examples/partitioning_settings` is the scenario of the graph example: 150
devices on a 2000 by 2000 meters map, four linked edge data centers, the `ALL`
architecture, five simulated minutes, and the same 60/40 split between the graph
application and a monolithic one.

The solver seed comes from `random_seed` in the settings file, and defaults to
`20261026` when the file leaves it empty. With seed 42 the run is reproducible.

## Run it

From the repository root, after `pip install -e .`:

```bash
python examples/genetic_partitioning/genetic_partitioning.py
```

## What to look for

The console prints the estimated fitness and the node chosen for every subtask:

```text
GeneticOrchestrator - Application 0 (Soft Real-time): fitness 0.0768 (makespan 0.0697 s, transfers 0.0011 s, imbalance 0.6244)
  {'capture': 'Mist#65', 'preprocess': 'Mist#65', 'detect': 'Mist#64', 'classify': 'Mist#54', 'track': 'Edge#2', 'aggregate': 'Mist#54', 'notify': 'Mist#54'}
tasks= 9600 ok= 9600 avg_delay=0.0252 cloud= 984 edge=5861 mist=2755 failed(dependency)=   0 energy=49.2382
```

- The fitness is an estimate made before the run, so compare it with the cut of
  the graph example rather than with the measured delay.
- The search keeps most of the pipeline close to the devices and sends stages to
  the edge only when the estimated transfer cost pays off.
- Every generated task succeeds, and no task is lost to a failed dependency.
- Results go to `output/partitioning/`.

Set `random_seed` in the settings file and remove it again to see the plan
change for the same scenario.

## Files

- `genetic_partitioning.py` with the orchestrator and the run
- `../../src/pureedgesim/partitioning.py` with `Candidate` and
  `GeneticPartitioner`, shared with the graph example
- `../partitioning_settings/applications.xml` with the service graph

## Where to go next

- [Graph partitioning](../graph_partitioning/README.md) for the cut-based
  solution to the same problem
- The service graph section of the [main README](../../README.md#service-graphs)
  for the XML syntax and the dependency semantics
