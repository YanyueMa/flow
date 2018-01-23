"""
Script used to train test platooning on a single lane.

RL vehicles are bunched together. The emergent behavior we are hoping to witness
is that rl-vehicles group together in other to allow non rl-vehicles a larger headway,
and thus larger equilibrium speeds.

One concern is whether rl-vehicles will start tail-gating human vehicles.

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

import json
import logging
import os

import gym
import numpy as np

import ray
import ray.rllib.ppo as ppo
from ray.tune.registry import get_registry, register_env as register_rllib_env
from ray.rllib.models import ModelCatalog
from ray.tune.result import DEFAULT_RESULTS_DIR as results_dir

from flow.core.util import register_env, NameEncoder
from flow.utils.tuple_preprocessor import TuplePreprocessor

from flow.core.params import SumoParams, EnvParams, InitialConfig, NetParams
from flow.scenarios.loop.gen import CircleGenerator
from flow.scenarios.loop.loop_scenario import LoopScenario
from flow.controllers.rlcarfollowingcontroller import RLCarFollowingController
from flow.controllers.car_following_models import IDMController
from flow.controllers.routing_controllers import ContinuousRouter
from flow.core.vehicles import Vehicles

HORIZON = 100

additional_env_params = {"target_velocity": 8, "max-deacc": -1,
                         "max-acc": 1, "num_steps": HORIZON,
                         "scenario_type": LoopScenario} # Any way to avoid specifying this here? - nish
additional_net_params = {"length": 260, "lanes": 1, "speed_limit": 30,
                         "resolution": 40}
vehicle_params = [dict(veh_id="rl",
                       acceleration_controller=(RLCarFollowingController, {}),
                       routing_controller=(ContinuousRouter, {}),
                       num_vehicles=1),
                  dict(veh_id="idm",
                       acceleration_controller=(IDMController, {}),
                       routing_controller=(ContinuousRouter, {}),
                       num_vehicles=21)
                 ]

flow_params = dict(
                sumo=dict(
                    sim_step=0.1
                  ),
                env=dict(
                    additional_params=additional_env_params
                  ),
                net=dict(
                    no_internal_links=False,
                    additional_params=additional_net_params
                  ),
                veh=vehicle_params,
                initial=dict(
                    spacing="uniform", bunching=30, min_gap=0
                  )
              )


def make_create_env(flow_env_name, flow_params=flow_params, version=0, exp_tag="example", sumo="sumo"):
    env_name = flow_env_name+'-v%s' % version

    sumo_params_dict = flow_params['sumo']
    sumo_params_dict['sumo_binary'] = sumo
    sumo_params = SumoParams(**sumo_params_dict)

    env_params_dict = flow_params['env']
    env_params = EnvParams(**env_params_dict)

    net_params_dict = flow_params['net']
    net_params = NetParams(**net_params_dict)

    veh_params = flow_params['veh']

    init_params = flow_params['initial']

    def create_env(env_config):
        import flow.envs as flow_envs

        # note that the vehicles are added sequentially by the generator,
        # so place the merging vehicles after the vehicles in the ring
        vehicles = Vehicles()
        for i in range(len(vehicle_params)):
            vehicles.add(**vehicle_params[i])

        initial_config = InitialConfig(**init_params)

        scenario = LoopScenario(exp_tag, CircleGenerator, vehicles, net_params,
                                initial_config=initial_config)

        pass_params = (flow_env_name, sumo_params, vehicles, env_params,
                       net_params, initial_config, scenario, version)

        register_env(*pass_params)
        env = gym.envs.make(env_name)

        return env
    return create_env, env_name

if __name__ == "__main__":
    config = ppo.DEFAULT_CONFIG.copy()
    horizon = HORIZON
    num_cpus = 3
    n_rollouts = 3

    ray.init(num_cpus=num_cpus, redirect_output=True)
    # ray.init(redis_address="172.31.92.24:6379", redirect_output=True)

    config["num_workers"] = num_cpus
    config["timesteps_per_batch"] = horizon * n_rollouts
    config["gamma"] = 0.999  # discount rate
    config["model"].update({"fcnet_hiddens": [16, 16]})

    config["lambda"] = 0.97
    config["sgd_batchsize"] = min(16 * 1024, config["timesteps_per_batch"])
    config["kl_target"] = 0.02
    config["num_sgd_iter"] = 10
    config["horizon"] = horizon

    flow_env_name = "WaveAttenuationPOEnv"
    exp_tag = "stabilizing_the_ring_example"  # experiment prefix

    flow_params['flowenv'] = flow_env_name
    flow_params['exp_tag'] = exp_tag
    flow_params['module'] = os.path.basename(__file__)[:-3]  # filename without '.py'

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
