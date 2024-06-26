import gym
import torch
from gym import spaces
import numpy as np
import math
import pygame
import einops
from pygame.locals import *


class SaccadeEnv(gym.Env):
    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 20}

    def __init__(
        self, images, num_box_per_side=4, seq_len=100, device="cpu", render_mode=None
    ):
        self.width, self.height = 64, 64  # The size of the mmnist image
        self.window_size = 108
        self.mnist_width, self.mnist_height = 28, 28  # The size of the mnist patch
        self.num_box_per_side = num_box_per_side
        self.box_side_length = self.width // self.num_box_per_side

        self.peri_size = (
            self.num_box_per_side,
            self.num_box_per_side,
        )  # The size of the pheripheral vision observation
        self.central_size = (
            self.box_side_length,
            self.box_side_length,
        )  # The size of the central vision observation
        self.loc_size = (
            self.num_box_per_side**2
        )  # The apction space size as the location coordinate
        self.nums_per_image = 2

        self.lims = (x_lim, y_lim) = (
            self.width - self.mnist_width,
            self.height - self.mnist_height,
        )
        self.lims = torch.tensor(self.lims)
        self.images = images
        self.device = device
        self.num_images = len(images)
        self.seq_len = seq_len

        self.observation_space = spaces.Dict(
            {
                "central": spaces.Box(0, 255, shape=self.central_size, dtype=np.uint8),
                "peripheral": spaces.Box(0, 255, shape=self.peri_size, dtype=np.uint8),
                # "loc": spaces.Discrete(self.loc_size),
            }
        )
        self.action_space = spaces.Discrete(self.loc_size)

        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode
        self.window = None
        self.clock = None

    def reset(self, seed=None):
        # super().reset(seed=seed)
        self._reset()
        self.observation = self._get_obsv()
        self.info = self._get_info()

        if self.render_mode == "human":
            self._render_frame()

        return self.observation

    def _reset(self):
        direcs = math.pi * (torch.rand((self.nums_per_image,)) * 2 - 1)
        indexes = np.random.randint(self.num_images, size=(self.nums_per_image))
        self.patches = torch.tensor(self.images[indexes])
        speeds = np.random.randint(1, 5, size=(self.nums_per_image,))
        self.velocs = torch.tensor(
            [(s * torch.cos(d), s * torch.sin(d)) for d, s in zip(direcs, speeds)]
        )
        self.loc = torch.randint(self.loc_size, (1,))[0]
        self.positions = torch.mul(
            torch.rand(
                (
                    self.nums_per_image,
                    2,
                )
            ),
            self.lims,
        )
        self.step_count = 0

    def _get_obsv(self):
        canvas = torch.zeros(self.width, self.height)
        for patch, pos in zip(self.patches, self.positions):
            canvas += self._build_canvas(patch, pos)
        canvas = torch.where(canvas > 255.0, 255.0, canvas)
        self.canvas = canvas

        rearranged_canvas = einops.rearrange(
            canvas,
            "(w1 w2) (h1 h2) -> (w1 h1) w2 h2",
            w1=self.num_box_per_side,
            h1=self.num_box_per_side,
        )

        self.central_vision = rearranged_canvas[self.loc]
        # self.central_vision = einops.rearrange(central, "1 w h -> w h")

        self.peri_vision = einops.reduce(
            rearranged_canvas, "(l1 l2) w h -> l1 l2", "mean", l1=self.num_box_per_side
        )
        observation = {
            "central": self.central_vision,
            "peripheral": self.peri_vision,
            # "loc": self.loc,
        }
        return observation

    def _get_info(self):
        return {"canvas": self.canvas}

    def _build_canvas(self, patch, pos):
        x, y = pos.to(dtype=torch.int)
        x = torch.clamp(x, min=0, max=self.lims[0])
        y = torch.clamp(y, min=0, max=self.lims[1])
        canvas = torch.zeros((self.width, self.height), dtype=torch.uint8)
        canvas[x : x + self.mnist_width, y : y + self.mnist_height] = patch
        return canvas

    def step(self, action):
        next_pos = self.positions + self.velocs
        self.velocs = torch.where(
            ((next_pos < -2) | (next_pos > self.lims + 1)),
            -1.0 * self.velocs,
            self.velocs,
        )
        self.positions = self.positions + self.velocs
        self.step_count += 1
        reward = 1.0

        if self.step_count > self.seq_len:
            done = True
        else:
            done = False

        self.loc = action
        self.observation = self._get_obsv()
        self.info = self._get_info()

        if self.render_mode == "human":
            self._render_frame()

        return self.observation, reward, done, self.info

    def render(self):
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def get_surface(self, image):
        w, h = image.shape

        buf = np.zeros((w, h, 3), dtype=np.uint8)
        buf[:, :, 2] = buf[:, :, 1] = buf[:, :, 0] = image
        buf = einops.rearrange(buf, "h w c -> w h c")

        surf = pygame.surfarray.make_surface(buf)
        return surf

    def _render_frame(self):
        if self.window is None and self.render_mode == "human":
            pygame.init()
            pygame.display.init()
            self.window = pygame.display.set_mode(
                (self.window_size, self.window_size), HWSURFACE | DOUBLEBUF | RESIZABLE
            )
            self.draw_screen = self.window.copy()
        if self.clock is None and self.render_mode == "human":
            self.clock = pygame.time.Clock()

        canvas = pygame.Surface((self.window_size, self.window_size))
        self.draw_screen.fill((100, 100, 100))
        pygame.display.flip()

        image = self.canvas.numpy()
        surf = self.get_surface(image)
        self.draw_screen.blit(surf, (0, 0))

        peri = self.peri_vision.numpy()
        surf = self.get_surface(peri)
        # self.draw_screen.blit(surf, (30 + self.box_side_length, 72))
        self.draw_screen.blit(
            pygame.transform.scale(surf, (self.box_side_length, self.box_side_length)),
            (30 + self.box_side_length, 72),
        )

        central = self.central_vision.numpy()
        surf = self.get_surface(central)
        self.draw_screen.blit(surf, (10, 72))

        # Draw red line around loc
        top = self.loc // self.num_box_per_side * self.box_side_length
        left = self.loc % self.num_box_per_side * self.box_side_length
        pygame.draw.rect(
            self.draw_screen,
            (255, 0, 0),
            pygame.Rect(left, top, self.box_side_length, self.box_side_length),
            width=1,
        )

        if self.render_mode == "human":
            self.window.blit(
                pygame.transform.scale(self.draw_screen, self.window.get_rect().size),
                (0, 0),
            )
            pygame.event.pump()
            pygame.display.update()
            self.clock.tick(self.metadata["render_fps"])
        else:
            return np.transpose(
                np.array(pygame.surfarray.pixels3d(self.draw_screen)), axes=(1, 0, 2)
            )

    def close(self):
        if self.window is not None:
            pygame.display.quit()
            pygame.quit()
            self.window = None


class SaccadeEnvAdapter:
    def __init__(self, images):
        self._env = SaccadeEnv(images)
        self._obs_is_dict = hasattr(self._env.observation_space, "spaces")

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return getattr(self._env, name)
        except AttributeError:
            raise ValueError(name)

    @property
    def observation_space(self):
        if self._obs_is_dict:
            spaces = self._env.observation_space.spaces.copy()
        else:
            spaces = {self._obs_key: self._env.observation_space}
        return gym.spaces.Dict(
            {
                "central": gym.spaces.Box(
                    0, 255, (np.prod(spaces["central"].shape),), dtype=np.uint8
                ),
                "peripheral": gym.spaces.Box(
                    0, 255, (np.prod(spaces["peripheral"].shape),), dtype=np.uint8
                ),
                "is_first": gym.spaces.Box(0, 1, (), dtype=bool),
                "is_last": gym.spaces.Box(0, 1, (), dtype=bool),
                "is_terminal": gym.spaces.Box(0, 1, (), dtype=bool),
            }
        )

    @property
    def action_space(self):
        action_space = self._env.action_space
        action_space.discrete = True
        return action_space

    def step(self, action):
        obs, reward, done, info = self._env.step(action)
        if not self._obs_is_dict:
            obs = {self._obs_key: obs}
        obs = self.flatten_obs(obs)
        obs["is_first"] = False
        obs["is_last"] = done
        obs["is_terminal"] = done
        return obs, reward, done, info

    def reset(self):
        obs = self._env.reset()
        if not self._obs_is_dict:
            obs = {self._obs_key: obs}
        obs = self.flatten_obs(obs)
        obs["is_first"] = True
        obs["is_last"] = False
        obs["is_terminal"] = False
        return obs

    def flatten_obs(self, obs):
        obs = {k: torch.flatten(v) for k, v in obs.items()}
        return obs
