"""Network: access links, routing, bandwidth sharing, per-hop accounting and energy."""
from __future__ import annotations

import pytest

from conftest import build_manager, run_until
from pureedgesim import LinkTechnology, LinkType, Task
from pureedgesim.nodes import NodeType
from pureedgesim.topology import access_link_parameters


@pytest.fixture
def network(parameters, files):
    engine, manager = build_manager(parameters, files, devices=100)
    return engine, manager, manager.network


def make_task(device):
    return Task(id=1, type="test", application_id=0, length=1000.0, container_size=8e6,
                request_size=8e3, result_size=8e3, max_latency=1e9, time=0.0,
                source_device=device, registry=device)


def send(engine, manager, size, route, description="task to destination", task=None):
    """Sends a transfer and returns the progress object once it completed."""
    outcome = {}
    device = route[0].source if route[0].source.type == NodeType.EDGE_DEVICE else route[0].destination
    holder = task or make_task(device)

    def callback(finished_task, progress):
        outcome["task"] = finished_task
        outcome["progress"] = progress

    manager.network.send(holder, size, route, callback, description)
    run_until(engine, lambda: bool(outcome))
    return holder, outcome["progress"]


def test_every_device_gets_an_access_link_and_a_wan_link(network):
    engine, manager, model = network
    device = next(n for n in manager.edge_devices if n.serving_edge_data_center is not None)
    assert device.up_link.type == LinkType.LAN
    assert device.up_link.destination is device.serving_edge_data_center
    assert device.down_link.source is device.serving_edge_data_center
    assert device.wan_up_link.type == LinkType.WAN
    assert device.wan_up_link.destination.type == NodeType.ROUTER


def test_access_link_parameters_follow_the_connectivity(parameters, files):
    engine, manager = build_manager(parameters, files, devices=100)
    wifi = next(n for n in manager.edge_devices if n.energy_model.connectivity == "wifi")
    assert wifi.up_link.bandwidth == parameters.wifi_bandwidth
    assert wifi.up_link.delay == parameters.wifi_delay
    assert wifi.up_link.technology == LinkTechnology.WIFI
    assert wifi.wan_up_link.bandwidth == parameters.wan_bandwidth


@pytest.mark.parametrize("connectivity", ["wifi", "cellular", "ethernet"])
def test_an_access_link_charges_both_of_its_ends(parameters, connectivity):
    """The Java link classes sum the transmitter and the receiver of every hop."""
    _, _, up, down = access_link_parameters(parameters, connectivity)
    if connectivity == "cellular":
        assert up == pytest.approx(parameters.cellular_device_transmission_energy
                                   + parameters.cellular_base_station_uplink_energy)
        assert down == pytest.approx(parameters.cellular_device_reception_energy
                                     + parameters.cellular_base_station_downlink_energy)
    elif connectivity == "ethernet":
        assert up == down == pytest.approx(parameters.ethernet_energy_per_bit)
    else:
        assert up == pytest.approx(parameters.wifi_device_transmission_energy
                                   + parameters.wifi_access_point_reception_energy)
        assert down == pytest.approx(parameters.wifi_access_point_transmission_energy
                                     + parameters.wifi_device_reception_energy)
        assert up > down


def test_man_links_come_only_from_the_network_links_element(files, network):
    engine, manager, model = network
    assert len(files.man_links) == 0
    assert [link for link in model.graph.links if link.type == LinkType.MAN] == []


def test_route_from_a_device_to_the_cloud_leaves_through_the_wan(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    cloud = manager.nodes_generator.cloud_nodes[0]
    route = model.route_for(device, cloud)
    assert route[0] is device.wan_up_link
    assert [link.type for link in route] == [LinkType.WAN, LinkType.IGNORE]
    assert route[-1].destination is cloud


def test_a_device_reaches_another_edge_data_center_over_its_access_link(network):
    """The radio hop comes first, as it does in Java, then the graph carries the rest."""
    engine, manager, model = network
    device = manager.edge_devices[0]
    edge = manager.nodes_generator.edge_data_centers[0]
    manager.connect_with(device, manager.nodes_generator.cloud_nodes[0])
    route = model.route_for(device, edge)
    assert route[0] is device.up_link
    assert route[-1].destination is edge


def test_the_wan_access_link_keeps_the_radio_and_adds_the_wan_cost(parameters, files):
    engine, manager = build_manager(parameters, files, devices=100)
    wifi = next(n for n in manager.edge_devices if n.energy_model.connectivity == "wifi")
    _, _, up_energy, _ = access_link_parameters(parameters, "wifi")
    assert wifi.wan_up_link.technology == LinkTechnology.WIFI
    assert wifi.wan_up_link.delay == parameters.wan_delay
    assert wifi.wan_up_link.energy_per_bit == pytest.approx(up_energy + parameters.wan_energy_per_bit)


def test_an_infrastructure_link_belongs_to_no_radio_category(network):
    engine, manager, model = network
    router = manager.nodes_generator.routers[0]
    cloud = manager.nodes_generator.cloud_nodes[0]
    link = next(link for link in model.graph.links
                if link.source is router and link.destination is cloud)
    assert link.technology is None


def test_an_edge_device_is_never_an_intermediate_hop(network):
    engine, manager, model = network
    cloud = manager.nodes_generator.cloud_nodes[0]
    edge = manager.nodes_generator.edge_data_centers[0]
    path = model.graph.shortest_path(cloud, edge)
    assert all(link.destination.type != NodeType.EDGE_DEVICE for link in path)


def test_a_node_never_routes_to_itself(network):
    engine, manager, model = network
    assert model.route_for(manager.edge_devices[0], manager.edge_devices[0]) == []


def test_device_to_device_routes_stay_inside_the_radio_range(network):
    engine, manager, model = network
    far = [device for device in manager.edge_devices
           if manager.edge_devices[0].distance_to(device) > manager.parameters.edge_devices_range]
    assert model.route_for(manager.edge_devices[0], far[0]) == []
    close = [device for device in manager.edge_devices if device is not manager.edge_devices[0]]
    manager.parameters.edge_devices_range = 1e9
    route = model.route_for(manager.edge_devices[0], close[0])
    assert [link.type for link in route] == [LinkType.LAN]
    assert route[0].destination is close[0]


def test_the_unreachable_null_node_has_no_route(network):
    engine, manager, model = network
    assert model.route_for(manager.nodes_generator.routers[0], manager.edge_devices[0]) != []


def test_a_non_realistic_link_clears_the_whole_payload_at_its_current_clock(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    size = 10 * device.wan_up_link.bandwidth
    task, progress = send(engine, manager, size, model.route_for(device, manager.nodes_generator.cloud_nodes[0]))
    assert progress.hop_times[0] == pytest.approx(size / device.wan_up_link.bandwidth)
    assert task.total_network_time == pytest.approx(sum(link.delay for link in progress.route)
                                                    + sum(progress.hop_times))


def test_a_hop_advances_the_clock_only_by_its_propagation_latency(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    route = model.route_for(device, manager.nodes_generator.cloud_nodes[0])
    before = engine.clock
    send(engine, manager, 10 * route[0].bandwidth, route)
    assert engine.clock - before == pytest.approx(route[-1].delay)


def test_two_transfers_sent_at_once_share_one_link_bandwidth(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    route = model.route_for(device, manager.nodes_generator.cloud_nodes[0])
    link = route[0]
    first, second = make_task(device), make_task(device)
    model.send(first, link.bandwidth, route, lambda *_: None, "task to destination")
    model.send(second, link.bandwidth, route, lambda *_: None, "task to destination")
    run_until(engine, lambda: first.network_hops[0].hop_times)
    assert first.network_hops[0].hop_times[0] == pytest.approx(2.0)
    assert second.network_hops[0].hop_times[0] == pytest.approx(2.0)


def test_two_transfers_share_one_link_bandwidth(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    cloud = manager.nodes_generator.cloud_nodes[0]
    route = model.route_for(device, cloud)
    link = route[0]
    manager.parameters.realistic_network_model = True
    interval = model.parameters.network_update_interval
    first, second = make_task(device), make_task(device)
    model.send(first, link.bandwidth * interval * 2, route, lambda *_: None, "task to destination")
    model.send(second, link.bandwidth * interval * 2, route, lambda *_: None, "task to destination")
    run_until(engine, lambda: first.network_hops[0].transferred_bits > 0)
    assert link.allocated_bandwidth() == pytest.approx(link.bandwidth / 2)
    assert first.network_hops[0].transferred_bits == pytest.approx(link.bandwidth * interval / 2)


def test_a_multi_hop_transfer_recharges_every_hop(network):
    """The ignored hop still delays the task, it just does not show up in the counters."""
    engine, manager, model = network
    device = manager.edge_devices[0]
    cloud = manager.nodes_generator.cloud_nodes[0]
    route = model.route_for(device, cloud)
    before = model.network_usage[LinkType.WAN]
    task, progress = send(engine, manager, 8e9, route)
    assert len(progress.hop_times) == 2
    assert model.network_usage[LinkType.WAN] - before == pytest.approx(progress.hop_times[0])
    assert task.total_network_time == pytest.approx(sum(link.delay for link in route)
                                                    + sum(progress.hop_times))
    assert model.total_traffic_bits == pytest.approx(8e9)
    assert task.network_hops == [progress]


def test_hop_delays_are_counted_once_per_transfer(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    route = model.route_for(device, manager.nodes_generator.cloud_nodes[0])
    task, _progress = send(engine, manager, 8e3, route)
    assert task.total_network_time == pytest.approx(sum(link.delay for link in route)
                                                    + 8e3 / route[0].bandwidth + 8e3 / route[1].bandwidth)


def test_link_energy_is_booked_per_type_and_technology(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    size = 1e6
    route = [device.up_link]
    send(engine, manager, size, route)
    assert model.link_energy[LinkType.LAN] == pytest.approx(size * device.up_link.energy_per_bit)
    assert model.technology_energy[LinkTechnology.WIFI] == pytest.approx(size * device.up_link.energy_per_bit)
    assert device.up_link.total_energy_consumption == pytest.approx(size * device.up_link.energy_per_bit)


def test_a_wireless_uplink_energes_the_device(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    before = device.energy_model.network_energy_consumption
    send(engine, manager, 1e6, [device.up_link])
    # A transmitting device is charged with the transmission rate.
    assert device.energy_model.network_energy_consumption - before == pytest.approx(
        1e6 * device.energy_model.transmission_energy_per_bit)


def test_container_downloads_are_tracked_separately(network):
    engine, manager, model = network
    device = manager.edge_devices[0]
    before = model.container_usage[LinkType.LAN]
    send(engine, manager, 1e6, [device.up_link], description="container download")
    assert model.container_usage[LinkType.LAN] - before == pytest.approx(1e6 / device.up_link.bandwidth)
    after = model.container_usage[LinkType.LAN]
    send(engine, manager, 1e6, [device.up_link])
    assert model.container_usage[LinkType.LAN] == after


def test_average_bandwidth_is_reported_in_megabits(network):
    engine, manager, model = network
    assert model.get_average_bandwidth_per_task() == 0.0
    device = manager.edge_devices[0]
    send(engine, manager, 1e6, [device.up_link])
    assert model.get_average_bandwidth_per_task() == pytest.approx(device.up_link.bandwidth / 1e6)


def test_an_empty_route_completes_immediately(network):
    engine, manager, model = network
    called = []
    task = make_task(manager.edge_devices[0])
    model.send(task, 1000.0, [], lambda finished, progress: called.append((finished, progress)), "nothing")
    assert called == [(task, None)]
    assert model.active_transfers == set()
