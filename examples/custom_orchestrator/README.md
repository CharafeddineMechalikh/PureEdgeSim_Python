# Custom orchestrator: nearest node

## What it shows

How to replace the placement policy of PureEdgeSim by subclassing
`Orchestrator`. The built-in `TRADE_OFF` algorithm balances the load of each
candidate against its CPU speed. This example implements the opposite instinct:
give the task to the node closest to the requesting device, so a mist neighbour
wins whenever one is within radio range and the cloud is only a last resort.

`NearestNodeOrchestrator` overrides `find_computing_node`. It filters the
candidates with `offloading_is_possible`, then keeps the nearest one, using the
load counter in `self.history` to break ties. The cloud has no meaningful
distance in this model, so it is pushed to the end of the ordering.

## The scenario

The script runs the same workload twice, with the same seed, so the only
difference is the policy:

- `examples/default_settings`, 20 devices, five simulated minutes;
- the `ALL` architecture, so mist, edge, and cloud are all candidates;
- `TRADE_OFF` as the algorithm name, `random_seed=7`, no log file;
- the first run uses `DefaultOrchestrator`, the second the custom one.

## Run it

From the repository root, after `pip install -e .`:

```bash
python examples/custom_orchestrator/custom_orchestrator.py
```

## What to look for

```text
orchestration strategy, same seed and same workload:
TRADE_OFF (default)      tasks= 1035 ok=  775 avg_delay=0.2024   cloud= 135 edge= 436 mist= 464 energy=11.6066
nearest node             tasks= 1035 ok=  781 avg_delay=0.2037   cloud=   0 edge= 522 mist= 513 energy=11.4243
```

- The nearest-node policy never selects the cloud, because an edge data center
  or a neighbour is always closer.
- The average delay moves little: the policy saves the WAN round trip but sends
  more tasks to slower mist devices.
- The energy drops slightly, the Wi-Fi and Ethernet links costing less than the
  WAN link per bit.
- Results go to `output/examples/`.

Change the ordering key to see the trade-off: prefer the fastest node instead of
the closest one, and the cloud returns while mist usage falls.

## Files

- `custom_orchestrator.py` with the orchestrator and the two runs
- `../default_settings/` for the scenario files

## Where to go next

- [Distributions and mobility](../distributions_and_mobility/README.md) for a
  scenario configured entirely from Python
- [Graph partitioning](../graph_partitioning/README.md) for a policy that routes
  the subtasks of one request to different nodes
