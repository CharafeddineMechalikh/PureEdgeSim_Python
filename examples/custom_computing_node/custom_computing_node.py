"""A computing node that schedules and handles an event of its own.

    python examples/custom_computing_node/custom_computing_node.py

The class registered with ``set_custom_computing_node`` builds every node of the
simulation: cloud data center, edge data center and edge device alike. One
subclass therefore adds behaviour to the whole fleet, which is what this example
demonstrates with a node that sends an event to itself when the simulation starts.

``ReportingNode`` extends ``ComputingNode`` and only adds that event: the default
energy accounting, CPU tracking and status updates stay in place, because every
event it does not own is forwarded to ``super().process_event``. The custom tag is
just an integer the framework never uses, so a node can run one-off or periodic
work of its own - a heartbeat, a local measurement, a state machine - without
touching the framework. Dropping the forwarding line would stop the status updates
and silently corrupt the energy and CPU columns, so the printed energy is part of
the proof.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from pureedgesim import COLUMNS, ComputingNode, NodeType, Simulation, load_parameters, load_settings

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/custom_computing_node/output"

# The framework tags are EventType members and stop at 18, so any other integer
# is a private tag, exactly like the 12000 of the Java example.
DO_SOMETHING = 12000


class ReportingNode(ComputingNode):
    """A node that receives its own event, then behaves like a default one."""

    received: Counter = Counter()

    @property
    def type(self) -> NodeType:
        return self._type

    @type.setter
    def type(self, node_type: NodeType) -> None:
        # One class builds all the layers, so the generator assigns the type after
        # the constructor. is_peripheral is the only flag derived from it, and the
        # mobile devices need it to keep their list of reachable edge data centers.
        self._type = node_type
        self.is_peripheral = node_type == NodeType.EDGE_DATACENTER

    def on_simulation_start(self) -> None:
        super().on_simulation_start()
        self.schedule_now(self, DO_SOMETHING)

    def process_event(self, event) -> None:
        if event.tag == DO_SOMETHING:
            ReportingNode.received[self.type] += 1
            print(f"Event received by {self.name}, you can do any action here")
            return
        super().process_event(event)


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the scenario; the three arguments shrink it for the test suite."""
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    # The settings folder describes the ten minute, seven architecture sweep of
    # the Java example; a short scenario is enough to show the node behaviour.
    parameters.simulation_duration = duration if duration is not None else 300.0
    count = devices if devices is not None else 20
    parameters.min_number_of_devices = parameters.max_number_of_devices = count
    parameters.devices_increment = 1
    parameters.orchestration_architectures = ["ALL"]
    parameters.orchestration_algorithms = ["TRADE_OFF"]
    parameters.random_seed = seed if seed is not None else 7
    parameters.save_log_file = False

    # The counter is a class attribute, so it has to be emptied for the counts to
    # describe this run rather than every run the process has already done.
    ReportingNode.received.clear()
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    simulation.set_custom_computing_node(ReportingNode)
    row = simulation.launch()[0]

    layers = ", ".join(f"{layer.value.lower()}={ReportingNode.received[layer]}"
                       for layer in (NodeType.CLOUD, NodeType.EDGE_DATACENTER, NodeType.EDGE_DEVICE))
    print(f"\n{sum(ReportingNode.received.values())} nodes received the custom event: {layers}")
    print(f"custom_computing_node      tasks={row[COLUMNS[7]]:>5} ok={row[COLUMNS[8]]:>5} "
          f"avg_delay={row[COLUMNS[4]]:<8} energy={row[COLUMNS[32]]:<8} cpu={row[COLUMNS[28]]}%")
    return row


if __name__ == "__main__":
    # The optional arguments shrink the scenario: a device count and an output
    # folder, so the node event can be watched on a small map without editing the
    # settings.
    main(devices=int(sys.argv[1]) if len(sys.argv) > 1 else None,
         output=sys.argv[2] if len(sys.argv) > 2 else OUTPUT)
