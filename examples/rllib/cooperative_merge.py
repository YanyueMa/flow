"""
Cooperative merging example, consisting of 1 learning agent and 6 additional
vehicles in an inner ring, and 10 vehicles in an outer ring attempting to
merge into the inner ring.

Attributes
----------
additional_env_params : dict
    Extra environment params
additional_net_params : dict
    Extra network parameters
flow_params : dict
    Large dictionary of flow parameters for experiment,
    passed in to `make_create_env` and used to create
    `flow_params.json` file used by exp visualizer
HORIZON : int
    Length of rollout, in steps
vehicle_params : list of dict
    List of dictionaries specifying vehicle characteristics
    and the number of each vehicle
"""

import gym
import json
import os

import ray
import ray.rllib.ppo as ppo
from ray.tune.registry import get_registry, register_env as register_rllib_env

from flow.core.util import register_env, NameEncoder
from flow.core.params import SumoParams, EnvParams, InitialConfig, NetParams
from flow.core.params import SumoCarFollowingParams, SumoLaneChangeParams
from flow.core.vehicles import Vehicles

from flow.controllers.rlcarfollowingcontroller import RLCarFollowingController
from flow.controllers.car_following_models import *
from flow.controllers.lane_change_controllers import *
from flow.controllers.routing_controllers import ContinuousRouter

from flow.scenarios.two_loops_one_merging_new.gen \
    import TwoLoopOneMergingGenerator
from flow.scenarios.two_loops_one_merging_new.scenario \
    import TwoLoopsOneMergingScenario

HORIZON = 100
RING_RADIUS = 100
NUM_MERGE_HUMANS = 9
NUM_MERGE_RL = 1
additional_env_params = {"target_velocity": 20, "max-deacc": -1.5,
                         "max-acc": 1, "num_steps": HORIZON}
additional_net_params = {"ring_radius": RING_RADIUS, "lanes": 1,
                         "inner_lanes": 3, "outer_lanes": 2,
                         "lane_length": 75, "speed_limit": 30,
                         "resolution": 40}
vehicle_params = [dict(veh_id="human",
                       acceleration_controller=(SumoCarFollowingController,
                                                {}),
                       lane_change_controller=(SumoLaneChangeController,
                                               {}),
                       routing_controller=(ContinuousRouter, {}),
                       lane_change_mode="strategic",
                       num_vehicles=10,
                       sumo_car_following_params=SumoCarFollowingParams(
                           minGap=1.0, tau=0.5),
                       sumo_lc_params=SumoLaneChangeParams()),
                  dict(veh_id="on-rl",
                       acceleration_controller=(RLController,
                                                {"fail_safe": "safe_velocity"}),
                       lane_change_controller=(SumoLaneChangeController,
                                               {}),
                       routing_controller=(ContinuousRouter, {}),
                       speed_mode="no_collide",
                       lane_change_mode="strategic",
                       num_vehicles=1,
                       sumo_car_following_params=SumoCarFollowingParams(
                           minGap=0.01, tau=0.5),
                       sumo_lc_params=SumoLaneChangeParams()),
                  dict(veh_id="merge-human",
                       acceleration_controller=(SumoCarFollowingController, {}),
                       lane_change_controller=(SumoLaneChangeController, {}),
                       routing_controller=(ContinuousRouter, {}),
                       lane_change_mode="strategic",
                       num_vehicles=NUM_MERGE_HUMANS,
                       sumo_car_following_params=SumoCarFollowingParams(
                           minGap=1.0, tau=0.5),
                       sumo_lc_params=SumoLaneChangeParams()),
                  dict(veh_id="merge-rl",
                       acceleration_controller=(RLCarFollowingController, {"fail_safe": "safe_velocity"}),
                       lane_change_controller=(SumoLaneChangeController, {}),
                       routing_controller=(ContinuousRouter, {}),
                       speed_mode="no_collide",
                       lane_change_mode="strategic",
                       num_vehicles=NUM_MERGE_RL,
                       sumo_car_following_params=SumoCarFollowingParams(
                           minGap=0.01, tau=0.5),
                       sumo_lc_params=SumoLaneChangeParams())
                  ]

merge_ids = []
for i in range(NUM_MERGE_HUMANS):
    merge_ids.append('merge-human_' + str(i))
for i in range(NUM_MERGE_RL):
    merge_ids.append('merge-rl_' + str(i))
merge_list = [merge_ids]

flow_params = dict(
    sumo=dict(
        sim_step=0.1
    ),
    env=dict(vehicle_arrangement_shuffle=True,
             additional_params=additional_env_params
             ),
    net=dict(
        no_internal_links=False,
        additional_params=additional_net_params
    ),
    veh=vehicle_params,
    initial=dict(
        x0=50,
        spacing="custom",
        lanes_distribution=1,
        # shuffle=False,
        # TODO add a consistent set of values for the bunching params
        # TODO add some non-uniformity
        additional_params={"merge_bunching": 300,
                           "merge_shuffle": True,
                           "gaussian_scale": 2,
                           "merge_from_top": True,
                           "shuffle_ids": merge_list}
    )
)


def make_create_env(flow_env_name, flow_params, version=0,
                    exp_tag="example", sumo="sumo"):
    env_name = flow_env_name + '-v%s' % version

    sumo_params_dict = flow_params['sumo']
    sumo_params_dict['sumo_binary'] = sumo
    sumo_params = SumoParams(**sumo_params_dict)

    env_params_dict = flow_params['env']
    env_params = EnvParams(**env_params_dict)

    net_params_dict = flow_params['net']
    net_params = NetParams(**net_params_dict)

    init_params = flow_params['initial']

    def create_env(env_config):

        # note that the vehicles are added sequentially by the generator,
        # so place the merging vehicles after the vehicles in the ring
        vehicles = Vehicles()
        for i in range(len(vehicle_params)):
            vehicles.add(**vehicle_params[i])

        initial_config = InitialConfig(**init_params)

        scenario = TwoLoopsOneMergingScenario(
            name=exp_tag,
            generator_class=TwoLoopOneMergingGenerator,
            vehicles=vehicles,
            net_params=net_params,
            initial_config=initial_config
        )

        pass_params = (flow_env_name, sumo_params, vehicles, env_params,
                       net_params, initial_config, scenario, version)

        register_env(*pass_params)
        env = gym.envs.make(env_name)

        return env

    return create_env, env_name


if __name__ == "__main__":
    config = ppo.DEFAULT_CONFIG.copy()
    horizon = HORIZON
    num_cpus = 2
    n_rollouts = 3

    ray.init(num_cpus=num_cpus, redirect_output=False)
    # ray.init(redis_address="172.31.92.24:6379", redirect_output=True)

    config["num_workers"] = num_cpus
    config["timesteps_per_batch"] = horizon * n_rollouts
    config["gamma"] = 0.999  # discount rate
    config["model"].update({"fcnet_hiddens": [16, 16, 16]})

    config["lambda"] = 0.97
    config["sgd_batchsize"] = min(16 * 1024, config["timesteps_per_batch"])
    config["kl_target"] = 0.02
    config["num_sgd_iter"] = 10
    config["horizon"] = horizon

    flow_env_name = "TwoLoopsMergePOEnv"
    exp_tag = "cooperative_merge_example"  # experiment prefix

    flow_params['flowenv'] = flow_env_name
    flow_params['exp_tag'] = exp_tag
    # filename without '.py'
    flow_params['module'] = os.path.basename(__file__)[:-3]

    create_env, env_name = make_create_env(flow_env_name, flow_params, version=0,
                                           exp_tag=exp_tag)

    # Register as rllib env
    register_rllib_env(env_name, create_env)

    alg = ppo.PPOAgent(env=env_name, registry=get_registry(), config=config)

    # Logging out flow_params to ray's experiment result folder
    json_out_file = alg.logdir + '/flow_params.json'
    with open(json_out_file, 'w') as outfile:
        json.dump(flow_params, outfile, cls=NameEncoder, sort_keys=True, indent=4)

    for i in range(2):
        alg.train()
        if i % 20 == 0:
            alg.save()  # save checkpoint
