import copy
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def init_weights(m):
    if isinstance(m, (nn.Conv2d, nn.Linear)):
        nn.init.orthogonal_(m.weight)


class Actor(nn.Module):
    def __init__(self, state_dim, action_dim, max_action, image_obs, cnn):
        super(Actor, self).__init__()

        self.image_obs = image_obs
        self.cnn = cnn
        self.cnn_out = state_dim * 4 * 4
        if image_obs:
            state_dim = state_dim ** 2

        if image_obs and cnn:
            self.cnn = nn.Sequential(
                nn.Conv2d(1, 32, 8, stride=4, padding=0),
                nn.ReLU(),
                nn.Conv2d(32, 64, 4, stride=2, padding=0),
                nn.ReLU(),
                nn.Conv2d(64, 64, 3, stride=1, padding=0),
                nn.ReLU(),
            )
            self.fcn = nn.Sequential(
                nn.Linear(self.cnn_out, 512),
                nn.ReLU(),
                nn.Linear(512, 256)
            )
            self.cnn.apply(init_weights)
        else:
            self.fcn = nn.Sequential(
                nn.Linear(state_dim, 256),
                nn.ReLU()
            )

        self.l1 = nn.Linear(256, 256)
        self.l2 = nn.Linear(256, action_dim)

        self.max_action = max_action

    def forward(self, state):
        if self.image_obs and self.cnn:
            state = self.cnn(state)
            state = state.view(-1, self.cnn_out)
        state = self.fcn(state)
        a = F.relu(self.l1(state))
        return self.max_action * torch.tanh(self.l2(a))


class Critic(nn.Module):
    def __init__(self, state_dim, action_dim, image_obs, cnn):
        super(Critic, self).__init__()

        self.image_obs = image_obs
        self.cnn = cnn
        self.cnn_out = state_dim * 4 * 4
        if image_obs:
            state_dim = state_dim ** 2

        if image_obs and cnn:
            self.cnn = nn.Sequential(
                nn.Conv2d(1, 32, 8, stride=4, padding=0),
                nn.ReLU(),
                nn.Conv2d(32, 64, 4, stride=2, padding=0),
                nn.ReLU(),
                nn.Conv2d(64, 64, 3, stride=1, padding=0),
                nn.ReLU()
            )
            self.fcn_1 = nn.Sequential(
                nn.Linear(self.cnn_out + action_dim, 512),
                nn.ReLU(),
                nn.Linear(512, 256)
            )
            self.fcn_2 = nn.Sequential(
                nn.Linear(self.cnn_out + action_dim, 512),
                nn.ReLU(),
                nn.Linear(512, 256)
            )
            self.cnn.apply(init_weights)
        else:
            self.fcn_1 = nn.Sequential(
                nn.Linear(state_dim + action_dim, 256),
                nn.ReLU()
            )
            self.fcn_2 = nn.Sequential(
                nn.Linear(state_dim + action_dim, 256),
                nn.ReLU()
            )

        # Q1 architecture
        self.l1 = nn.Linear(256, 256)
        self.l2 = nn.Linear(256, 1)

        # Q2 architecture
        self.l3 = nn.Linear(256, 256)
        self.l4 = nn.Linear(256, 1)

    def forward(self, state, action):
        if self.image_obs and self.cnn:
            state = self.cnn(state)
            state = state.view(-1, self.cnn_out)
            sa = torch.cat([state, action], 1)
        else:
            sa = torch.cat([state, action], 1)

        q1 = self.fcn_1(sa)
        q1 = F.relu(self.l1(q1))
        q1 = self.l2(q1)

        q2 = self.fcn_2(sa)
        q2 = F.relu(self.l3(q2))
        q2 = self.l4(q2)
        return q1, q2

    def Q1(self, state, action):
        if self.image_obs and self.cnn:
            state = self.cnn(state)
            state = state.view(-1, self.cnn_out)
            sa = torch.cat([state, action], 1)
        else:
            sa = torch.cat([state, action], 1)

        q1 = self.fcn_1(sa)
        q1 = F.relu(self.l1(q1))
        q1 = self.l2(q1)
        return q1


# Vanilla Variational Auto-Encoder
class VAE(nn.Module):
    def __init__(self, state_dim, action_dim, latent_dim, max_action, device):
        super(VAE, self).__init__()
        self.e1 = nn.Linear(state_dim + action_dim, 750)
        self.e2 = nn.Linear(750, 750)

        self.mean = nn.Linear(750, latent_dim)
        self.log_std = nn.Linear(750, latent_dim)

        self.d1 = nn.Linear(state_dim + latent_dim, 750)
        self.d2 = nn.Linear(750, 750)
        self.d3 = nn.Linear(750, action_dim)

        self.max_action = max_action
        self.latent_dim = latent_dim
        self.device = device

    def forward(self, state, action):
        z = F.relu(self.e1(torch.cat([state, action], 1)))
        z = F.relu(self.e2(z))

        mean = self.mean(z)
        # Clamped for numerical stability
        log_std = self.log_std(z).clamp(-4, 15)
        std = torch.exp(log_std)
        z = mean + std * torch.randn_like(std)

        u = self.decode(state, z)

        return u, mean, std

    def decode(self, state, z=None):
        # When sampling from the VAE, the latent vector is clipped to [-0.5, 0.5]
        if z is None:
            z = torch.randn((state.shape[0], self.latent_dim)).to(
                self.device).clamp(-0.5, 0.5)

        a = F.relu(self.d1(torch.cat([state, z], 1)))
        a = F.relu(self.d2(a))
        return self.max_action * torch.tanh(self.d3(a))


class BCQ(object):
    def __init__(self,
                 state_dim,
                 action_dim, max_action, discount=0.99, tau=0.005, lmbda=0.75, phi=0.05,
                 policy_noise=0.2,
                 noise_clip=0.5,
                 policy_freq=2,
                 cnn=False, image_obs=False):
        latent_dim = action_dim * 2

        self.actor = Actor(state_dim, action_dim, max_action,image_obs,cnn).to(device)
        self.actor_target = copy.deepcopy(self.actor)
        self.actor_optimizer = torch.optim.Adam(
            self.actor.parameters(), lr=1e-3)

        self.critic = Critic(state_dim, action_dim,image_obs,cnn).to(device)
        self.critic_target = copy.deepcopy(self.critic)
        self.critic_optimizer = torch.optim.Adam(
            self.critic.parameters(), lr=1e-3)

        self.vae = VAE(state_dim, action_dim, latent_dim,
                       max_action, device).to(device)
        self.vae_optimizer = torch.optim.Adam(self.vae.parameters())

        self.max_action = max_action
        self.image_obs = image_obs
        self.cnn = cnn
        self.action_dim = action_dim
        self.discount = discount
        self.tau = tau
        self.lmbda = lmbda
        self.device = device
        self.policy_noise = policy_noise
        self.noise_clip = noise_clip
        self.policy_freq = policy_freq
        self.total_it = 0

    def select_action(self, state):
        with torch.no_grad():
            state = torch.FloatTensor(state.reshape(
                1, -1)).repeat(100, 1).to(self.device)
            action = self.actor(state, self.vae.decode(state))
            q1 = self.critic.q1(state, action)
            ind = q1.argmax(0)
        return action[ind].cpu().data.numpy().flatten()

    def train(self, replay_buffer, iterations, batch_size=100):

        for it in range(iterations):
            # Sample replay buffer / batch
            state, action, next_state, reward, not_done = replay_buffer.sample(
                batch_size)

            # Variational Auto-Encoder Training
            recon, mean, std = self.vae(state, action)
            recon_loss = F.mse_loss(recon, action)
            KL_loss = -0.5 * (1 + torch.log(std.pow(2)) -
                              mean.pow(2) - std.pow(2)).mean()
            vae_loss = recon_loss + 0.5 * KL_loss

            self.vae_optimizer.zero_grad()
            vae_loss.backward()
            self.vae_optimizer.step()

            # Critic Training
            with torch.no_grad():
                # Duplicate next state 10 times
                next_state = torch.repeat_interleave(next_state, 10, 0)

                # Compute value of perturbed actions sampled from the VAE
                target_Q1, target_Q2 = self.critic_target(
                    next_state, self.actor_target(next_state, self.vae.decode(next_state)))

                # Soft Clipped Double Q-learning
                target_Q = self.lmbda * \
                    torch.min(target_Q1, target_Q2) + (1. -
                                                       self.lmbda) * torch.max(target_Q1, target_Q2)
                # Take max over each action sampled from the VAE
                target_Q = target_Q.reshape(
                    batch_size, -1).max(1)[0].reshape(-1, 1)

                target_Q = reward + not_done * self.discount * target_Q

            current_Q1, current_Q2 = self.critic(state, action)
            critic_loss = F.mse_loss(
                current_Q1, target_Q) + F.mse_loss(current_Q2, target_Q)

            self.critic_optimizer.zero_grad()
            critic_loss.backward()
            self.critic_optimizer.step()

            # Pertubation Model / Action Training
            sampled_actions = self.vae.decode(state)
            perturbed_actions = self.actor(state, sampled_actions)

            # Update through DPG
            actor_loss = -self.critic.q1(state, perturbed_actions).mean()

            self.actor_optimizer.zero_grad()
            actor_loss.backward()
            self.actor_optimizer.step()

            # Update Target Networks
            for param, target_param in zip(self.critic.parameters(), self.critic_target.parameters()):
                target_param.data.copy_(
                    self.tau * param.data + (1 - self.tau) * target_param.data)

            for param, target_param in zip(self.actor.parameters(), self.actor_target.parameters()):
                target_param.data.copy_(
                    self.tau * param.data + (1 - self.tau) * target_param.data)
    
    def save(self, filename):
        
        torch.save(self.critic.state_dict(), filename + "_critic")
        torch.save(self.critic_optimizer.state_dict(), filename + "_critic_optimizer")

        torch.save(self.actor.state_dict(), filename + "_actor")
        torch.save(self.actor_optimizer.state_dict(), filename + "_actor_optimizer")

    def load(self, filename):
        self.critic.load_state_dict(torch.load(filename + "_critic"))
        self.critic_optimizer.load_state_dict(torch.load(filename + "_critic_optimizer"))
        self.critic_target = copy.deepcopy(self.critic)

        self.actor.load_state_dict(torch.load(filename + "_actor"))
        self.actor_optimizer.load_state_dict(torch.load(filename + "_actor_optimizer"))
        self.actor_target = copy.deepcopy(self.actor)
        print("\nloaded the model successfully\n")
