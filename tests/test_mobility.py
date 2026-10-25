"""Mobility models, path generation and the model factory."""
from __future__ import annotations

import math

import pytest

from pureedgesim import (BrownianMobilityModel, CircularMobilityModel, DefaultMobilityModel,
                       GaussMarkovMobilityModel, LevyWalkMobilityModel, Location, ManhattanMobilityModel,
                       MobilityModel, MobilityModelFactory, RandomWalkMobilityModel,
                       ReferencePointGroupMobilityModel, WaypointMobilityModel)

from conftest import build_manager


class CustomMobilityModel(MobilityModel):
    """Always jumps to the middle of the map."""

    def get_next_location(self, location):
        return Location(self.map_width / 2, self.map_length / 2)


def make(parameters, files, name="random-walk", options=None, start=Location(20.0, 20.0), speed=2.0,
         mobile=True, seed=3):
    _, manager = build_manager(parameters, files, seed=seed)
    model = MobilityModelFactory.create(name, manager, start)
    model.speed = speed
    model.is_mobile = mobile
    model.set_parameters(options)
    return manager, model


def test_factory_lists_every_built_in_model():
    names = MobilityModelFactory.known_names()
    for expected in ("brownian", "circular", "default", "gauss-markov", "group", "levy-walk", "manhattan",
                     "random-waypoint", "random-walk", "rpgm", "waypoint"):
        assert expected in names


def test_factory_aliases_point_at_the_same_class():
    assert MobilityModelFactory.resolve("default") is MobilityModelFactory.resolve("random-waypoint")
    assert MobilityModelFactory.resolve("group") is MobilityModelFactory.resolve("RPGM")


def test_factory_is_case_insensitive():
    assert MobilityModelFactory.resolve("Random-Walk") is RandomWalkMobilityModel


def test_factory_resolves_a_dotted_class_path():
    assert MobilityModelFactory.resolve("test_mobility.CustomMobilityModel") is CustomMobilityModel
    model = MobilityModelFactory.create("test_mobility.CustomMobilityModel", None, Location(1, 1))
    assert isinstance(model, CustomMobilityModel)


def test_factory_rejects_an_unknown_short_name():
    with pytest.raises(ValueError, match="is not supported"):
        MobilityModelFactory.resolve("flat-earth")


def test_factory_rejects_a_missing_name():
    with pytest.raises(ValueError, match="No mobility model given"):
        MobilityModelFactory.resolve("   ")


def test_factory_rejects_a_class_that_is_not_a_mobility_model():
    with pytest.raises(ValueError, match="does not extend MobilityModel"):
        MobilityModelFactory.resolve("pureedgesim.Location")


def test_factory_rejects_an_unknown_class_path():
    with pytest.raises(ValueError, match="was not found"):
        MobilityModelFactory.resolve("pureedgesim.NopeMobilityModel")


@pytest.mark.parametrize("name,options", [
    ("random-waypoint", {}), ("random-walk", {}), ("gauss-markov", {}), ("manhattan", {}),
    ("circular", {"radius": "40"}), ("levy-walk", {}), ("brownian", {}), ("group", {"group": "7"}),
    ("waypoint", {"waypoints": "10,10;190,10;190,190;10,190"}),
])
def test_paths_stay_inside_the_simulation_area(parameters, files, name, options):
    parameters.simulation_map_width = parameters.simulation_map_length = 200.0
    manager, model = make(parameters, files, name, options)
    model.generate_path()
    assert model.path
    for location in model.path.values():
        assert 0 <= location.x_pos <= model.map_width
        assert 0 <= location.y_pos <= model.map_length


def test_random_walk_moves_one_step_per_tick(parameters, files):
    manager, model = make(parameters, files, "random-walk", speed=5.0)
    start = Location(50.0, 50.0)
    nxt = model.get_next_location(start)
    assert math.hypot(nxt.x_pos - start.x_pos, nxt.y_pos - start.y_pos) == pytest.approx(5.0)


def test_immobile_device_never_generates_a_path(parameters, files):
    manager, model = make(parameters, files, "random-walk", mobile=False)
    model.generate_path()
    assert model.path == {}
    assert model.update_location(10.0) == model.current_location


def test_default_model_alternates_pause_and_move(parameters, files):
    manager, model = make(parameters, files, "random-waypoint", speed=5.0)
    model.min_pause_duration = model.max_pause_duration = 4.0
    model.min_mobility_duration = model.max_mobility_duration = 2.0
    model.generate_path()
    values = [model.path[key] for key in sorted(model.path)]
    repeats = sum(1 for a, b in zip(values, values[1:]) if a == b)
    assert repeats > 0


def test_waypoint_model_visits_the_route_in_order(parameters, files):
    parameters.simulation_duration = 60.0
    manager, model = make(parameters, files, "waypoint", {"waypoints": "20,20;50,20;50,40"}, speed=1.0)
    model.generate_path()
    visited = list(model.path.values())
    route = ((20, 20), (50, 20), (50, 40))

    def closest_index(point):
        return min(range(len(visited)), key=lambda i: math.hypot(visited[i].x_pos - point[0],
                                                                 visited[i].y_pos - point[1]))

    indexes = [closest_index(point) for point in route]
    tolerance = model.get_step_distance() + 1e-6
    for point, index in zip(route, indexes):
        assert math.hypot(visited[index].x_pos - point[0], visited[index].y_pos - point[1]) <= tolerance
    assert indexes[0] < indexes[1] < indexes[2]


def test_waypoint_model_stops_at_the_end_without_loop(parameters, files):
    manager, model = make(parameters, files, "waypoint",
                          {"waypoints": "10,10;30,10", "loop": "false"}, speed=5.0)
    model.generate_path()
    assert model.finished
    assert list(model.path.values())[-1] == Location(30.0, 10.0)


def test_waypoint_model_waits_at_each_point(parameters, files):
    manager, model = make(parameters, files, "waypoint", {"waypoints": "10,10;30,10"}, speed=5.0)
    model.min_pause_duration = 3.0
    path_positions = [model.get_next_location(Location(10.0, 10.0)) for _ in range(4)]
    assert path_positions[0] == Location(10.0, 10.0)


@pytest.mark.parametrize("options,message", [
    ({}, "waypoints\" option is required"),
    ({"waypoints": "10,10"}, "at least two points"),
    ({"waypoints": "10,10;20"}, "x1,y1"),
    ({"waypoints": "10,10;a,b"}, "must only contain numbers"),
])
def test_waypoint_model_validates_the_option(parameters, files, options, message):
    manager, model = make(parameters, files, "waypoint", options, speed=1.0)
    with pytest.raises(ValueError, match=message):
        model.generate_path()


def test_circular_model_keeps_the_radius(parameters, files):
    manager, model = make(parameters, files, "circular", {"radius": "50", "center_x": "100",
                                                          "center_y": "100"}, speed=7.0)
    start = Location(150.0, 100.0)
    location = start
    for _ in range(30):
        location = model.get_next_location(location)
        assert math.hypot(location.x_pos - 100, location.y_pos - 100) == pytest.approx(50.0, abs=1e-6)


def test_circular_model_can_run_counter_clockwise(parameters, files):
    manager, model = make(parameters, files, "circular", {"radius": "50", "center_x": "100",
                                                          "center_y": "100", "clockwise": "false"},
                          speed=7.0)
    first = model.get_next_location(Location(150.0, 100.0))
    assert first.y_pos < 100.0


def test_circular_model_requires_a_radius(parameters, files):
    manager, model = make(parameters, files, "circular", {}, speed=1.0)
    with pytest.raises(ValueError, match="radius\" option must be > 0"):
        model.generate_path()


def test_manhattan_model_moves_one_axis_at_a_time(parameters, files):
    manager, model = make(parameters, files, "manhattan", speed=4.0)
    location = Location(50.0, 50.0)
    for _ in range(20):
        nxt = model.get_next_location(location)
        if nxt.x_pos != location.x_pos:
            # The horizontal leg only ever advances toward the target column.
            assert (nxt.x_pos - location.x_pos) * (model.target.x_pos - location.x_pos) > 0
            assert nxt.y_pos == location.y_pos or nxt.x_pos == model.target.x_pos
        location = nxt


def test_gauss_markov_bounds_alpha(parameters, files):
    manager, model = make(parameters, files, "gauss-markov", {"alpha": "1.5"})
    with pytest.raises(ValueError, match="alpha\" option must be >= 0"):
        model.generate_path()


def test_gauss_markov_keeps_a_positive_speed(parameters, files):
    manager, model = make(parameters, files, "gauss-markov", {"speed_std": "0.1"}, speed=3.0)
    model.generate_path()
    values = list(model.path.values())
    assert len(values) > 1
    distances = [math.hypot(b.x_pos - a.x_pos, b.y_pos - a.y_pos) for a, b in zip(values, values[1:])]
    assert max(distances) < 3.6 * model.update_interval


def test_levy_walk_uses_a_bounded_flight_length(parameters, files):
    manager, model = make(parameters, files, "levy-walk", {"min_step": "5", "max_step": "60"}, speed=1.0)
    starts = [model.pick_flight_end(Location(100.0, 100.0)) for _ in range(50)]
    assert all(math.hypot(p.x_pos - 100, p.y_pos - 100) <= 60.01 for p in starts)


def test_levy_walk_rejects_a_negative_shape(parameters, files):
    manager, model = make(parameters, files, "levy-walk", {"shape": "0"})
    with pytest.raises(ValueError, match="shape\" option must be > 0"):
        model.pick_flight_end(Location(10.0, 10.0))


def test_brownian_spread_follows_the_standard_deviation(parameters, files):
    manager, model = make(parameters, files, "brownian", {"std": "3"}, speed=0.0)
    start = Location(100.0, 100.0)
    drawn = [model.get_next_location(start) for _ in range(3000)]
    spread = math.sqrt(sum((p.x_pos - start.x_pos) ** 2 for p in drawn) / len(drawn))
    assert spread == pytest.approx(3.0, rel=0.1)


def test_group_models_share_one_anchor_path(parameters, files):
    first_manager, first = make(parameters, files, "group", {"group": "4"}, start=Location(30.0, 30.0))
    second = MobilityModelFactory.create("group", first_manager, Location(35.0, 30.0))
    second.speed = first.speed
    second.is_mobile = True
    second.set_parameters({"group": "4"})
    first.generate_path()
    second.generate_path()
    assert first.anchor_path == second.anchor_path
    for key in sorted(first.path):
        first_point, second_point = first.path[key], second.path[key]
        assert second_point.y_pos == pytest.approx(first_point.y_pos)
        gap = second_point.x_pos - first_point.x_pos
        at_border = first_point.x_pos < 5.0 or first.map_width - first_point.x_pos < 5.0
        assert abs(gap) == pytest.approx(5.0) or at_border


def test_different_groups_follow_different_anchors(parameters, files):
    manager, first = make(parameters, files, "group", {"group": "1"}, start=Location(30.0, 30.0))
    second = MobilityModelFactory.create("group", manager, Location(40.0, 40.0))
    second.speed = first.speed
    second.is_mobile = True
    second.set_parameters({"group": "2"})
    first.generate_path()
    second.generate_path()
    assert first.anchor_path != second.anchor_path


def test_update_location_reads_the_precomputed_path(parameters, files):
    manager, model = make(parameters, files, "random-walk", speed=5.0)
    model.generate_path()
    assert model.update_location(5.0) == model.path[5000]


def test_reflection_folds_a_location_back_inside(parameters, files):
    parameters.simulation_map_width = parameters.simulation_map_length = 100.0
    manager, model = make(parameters, files, "random-walk")
    assert model.reflect_location(Location(-10.0, 120.0)) == Location(10.0, 80.0)


def test_move_towards_never_overshoots():
    origin, target = Location(0.0, 0.0), Location(10.0, 0.0)
    assert MobilityModel.move_towards(origin, target, 30.0) == target
    assert MobilityModel.move_towards(origin, target, 4.0) == Location(4.0, 0.0)


def test_device_knows_its_closest_edge_data_center(parameters, files):
    parameters.simulation_map_width = parameters.simulation_map_length = 200.0
    parameters.edge_data_centers_range = 500.0
    manager, model = make(parameters, files, "random-walk", start=Location(100.0, 100.0))
    model.generate_path()
    closest = model.get_closest_edge_data_center()
    assert closest in manager.edge_only_list
    assert closest.mobility_model.current_location == Location(100.0, 100.0)


def test_a_device_outside_the_coverage_has_no_data_center(parameters, files):
    parameters.simulation_map_width = parameters.simulation_map_length = 2000.0
    parameters.edge_data_centers_range = 5.0
    manager, model = make(parameters, files, "random-walk", start=Location(1500.0, 1500.0))
    model.generate_path()
    from pureedgesim.nodes import ComputingNode
    assert model.get_closest_edge_data_center() is ComputingNode.NULL


def test_option_parsing_errors(parameters, files):
    manager, model = make(parameters, files, "random-walk")
    model.set_parameters({"speed": "fast"})
    with pytest.raises(ValueError, match="must be a number"):
        model.get_parameter("speed", 1.0)
    model.set_parameters({"ticks": "2.5"})
    with pytest.raises(ValueError, match="must be an integer"):
        model.get_parameter_int("ticks", 1)
    model.set_parameters({})
    assert model.get_parameter_bool("loop", True) is True
    assert model.get_parameter("radius", 12.0) == 12.0
