"""The extension points a scenario can replace, the counterpart of setCustom... ."""
from __future__ import annotations

import pytest

from conftest import SETTINGS
from pureedgesim import (ComputingNodesGenerator, DefaultMobilityModel, DefaultNetworkModel,
                         DefaultOrchestrator, DefaultTaskGenerator, DefaultTopologyCreator, Engine,
                         NodeType, Randomness, Scenario, Simulation, SimulationManager, run_scenario)
from pureedgesim.nodes import ComputingNode


def build(parameters, files, **models):
    """A manager built from the given custom classes, prepared but not run."""
    Randomness.set_seed(99)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, files, Scenario("ALL", "TRADE_OFF", 3), **models)
    manager.start_simulation()
    return engine, manager


class TrackingNetworkModel(DefaultNetworkModel):
    def __init__(self, manager) -> None:
        super().__init__(manager)
        manager.network_model_built = True


class TrackingNodesGenerator(ComputingNodesGenerator):
    def generate(self, files, device_count) -> None:
        super().generate(files, device_count)
        self.manager.nodes_generator_built = True


class TrackingTopologyCreator(DefaultTopologyCreator):
    def create(self) -> None:
        super().create()
        self.manager.topology_created = True


class TrackingTaskGenerator(DefaultTaskGenerator):
    def generate(self):
        tasks = super().generate()
        self.manager.task_generator_name = "custom"
        return tasks


class CustomNode(ComputingNode):
    def __init__(self, manager, mips_per_core, cores, storage, ram) -> None:
        super().__init__(manager, mips_per_core, cores, storage, ram)
        self.was_built_from_custom_class = True


class CustomManager(SimulationManager):
    instances: list["CustomManager"] = []

    def start_simulation(self) -> None:
        super().start_simulation()
        self.simulation_manager_built = True
        CustomManager.instances.append(self)


def test_the_custom_network_model_replaces_the_default(parameters, files):
    engine, manager = build(parameters, files, custom_network_model=TrackingNetworkModel)
    assert isinstance(manager.network, TrackingNetworkModel)
    assert manager.network_model_built is True
    engine.start()
    assert manager.metrics.succeeded_tasks > 0


def test_the_custom_nodes_generator_replaces_the_default(parameters, files):
    engine, manager = build(parameters, files, custom_nodes_generator=TrackingNodesGenerator)
    assert isinstance(manager.nodes_generator, TrackingNodesGenerator)
    assert manager.nodes_generator_built is True
    assert len(manager.computing_nodes) == len(manager.nodes_generator.all_nodes)


def test_the_custom_topology_creator_replaces_the_default(parameters, files):
    engine, manager = build(parameters, files, custom_topology_creator=TrackingTopologyCreator)
    assert manager.topology_created is True
    assert len(manager.network.graph.nodes_by_id) > 0
    assert len(manager.network.graph.links) > 0


def test_the_custom_task_generator_feeds_the_simulation(parameters, files):
    engine, manager = build(parameters, files, custom_task_generator=TrackingTaskGenerator)
    assert manager.task_generator_name == "custom"
    assert manager.tasks and manager.metrics.generated_tasks == len(manager.tasks)
    engine.start()
    assert manager.metrics.generated_tasks > 0


def test_every_custom_node_keeps_the_type_of_its_layer(parameters, files):
    engine, manager = build(parameters, files, custom_computing_node=CustomNode)
    devices = manager.nodes_generator.edge_devices
    cloud = manager.nodes_generator.cloud_nodes
    edge = manager.nodes_generator.edge_data_centers
    assert devices and cloud and edge
    assert all(isinstance(node, CustomNode) and node.was_built_from_custom_class
               for node in devices + cloud + edge)
    assert all(node.type == NodeType.EDGE_DEVICE for node in devices)
    assert all(node.type == NodeType.CLOUD for node in cloud)
    assert all(node.type == NodeType.EDGE_DATACENTER for node in edge)
    engine.start()
    assert manager.metrics.succeeded_tasks > 0


def test_the_custom_simulation_manager_is_used_by_a_run(parameters, files):
    Randomness.set_seed(99)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = CustomManager(engine, parameters, files, Scenario("ALL", "TRADE_OFF", 3))
    manager.start_simulation()
    engine.start()
    assert manager.simulation_manager_built is True
    assert manager.metrics.generated_tasks > 0


def test_the_simulation_setters_are_chainable_and_collected():
    simulation = Simulation(SETTINGS)
    chained = (simulation.set_custom_network_model(TrackingNetworkModel)
               .set_custom_computing_nodes_generator(TrackingNodesGenerator)
               .set_custom_topology_creator(TrackingTopologyCreator)
               .set_custom_task_generator(TrackingTaskGenerator)
               .set_custom_computing_node(CustomNode)
               .set_custom_simulation_manager(CustomManager))
    assert chained is simulation
    assert set(simulation.custom_models) == {"network_model", "nodes_generator", "topology_creator",
                                             "task_generator", "computing_node", "simulation_manager"}


def test_the_registered_models_reach_the_manager(parameters, files):
    CustomManager.instances.clear()
    simulation = Simulation(SETTINGS, parameters=parameters, files=files)
    simulation.set_custom_simulation_manager(CustomManager).set_custom_network_model(TrackingNetworkModel)
    row = run_scenario(parameters, files, Scenario("ALL", "TRADE_OFF", 3), 0,
                       custom_models=simulation.custom_models)
    assert len(CustomManager.instances) == 1
    manager = CustomManager.instances[0]
    assert isinstance(manager.network, TrackingNetworkModel)
    assert row["Orchestration architecture"] == "ALL"


def test_the_simulation_loads_its_settings_folder():
    simulation = Simulation(SETTINGS)
    simulation.load()
    assert simulation.parameters.simulation_duration > 0
    assert simulation.files.applications


def test_the_mobility_model_and_orchestrator_still_install(parameters, files):
    class CustomMobility(DefaultMobilityModel):
        pass

    class CustomOrchestrator(DefaultOrchestrator):
        pass

    engine, manager = build(parameters, files, custom_mobility_model=CustomMobility,
                            custom_orchestrator=CustomOrchestrator)
    engine.start()
    assert manager.default_mobility_model is CustomMobility
    assert isinstance(manager.orchestrator, CustomOrchestrator)
    assert all(isinstance(node.mobility_model, CustomMobility) for node in manager.edge_devices)
    assert manager.metrics.succeeded_tasks > 0
