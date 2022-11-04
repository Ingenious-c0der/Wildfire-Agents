
import gym



# class CustomPolicy(FeedForwardPolicy):
#     def __init__(self, *args, **kwargs):
#         super(CustomPolicy, self).__init__(*args, **kwargs,
#                                            layers=[64, 64],
#                                            layer_norm=False,
#                                            feature_extraction="mlp")

# register_policy("CustomPolicy", CustomPolicy)
env = gym.make('gym_forestfire:ForestFire-v0', world_size=(64, 64))
env.reset()

# policy_kwargs = dict(n_quantiles=50)
# model = QRDQN("CustomPolicy", env, policy_kwargs=policy_kwargs, verbose=1)
# model.learn(total_timesteps=10000, log_interval=4)
# model.save("qrdqn_forestfire")

# del model # remove to demonstrate saving and loading

# model = QRDQN.load("qrdqn_cartpole")

# obs = env.reset()
# while True:
#     action, _states = model.predict(obs, deterministic=True)
#     obs, reward, done, info = env.step(action)
#     env.render()
#     if done:
#       obs = env.reset()
#       break 

# env.close()


for _ in range(300):
    env.render()
    a = env.action_space.sample()
    s, r, d, _ = env.step(a)
env.close()










# import gym

# env = gym.make('gym_forestfire:ForestFire-v0', world_size=(64, 64))
# env.reset()
