import math
import gym
from gym import spaces, logger
from gym.utils import seeding
import numpy as np


def runge_kutta4(y, fy, h):
    """
    Fourth order Runge Kutta to estimate dy(t)/dt
    http://lpsa.swarthmore.edu/NumInt/NumIntFourth.html
    """

    k1 = fy(y)
    y1 = y + k1 * h / 2

    k2 = fy(y1)
    y2 = y + k2 * h / 2

    k3 = fy(y2)
    y3 = y + k3 * h

    k4 = fy(y3)

    y_dot = y + (k1 + 2*k2 + 2*k3 + k4)*h/6

    return y_dot


class DoublePole710(gym.Env):
    """
    Description:
        Two pole is attached by an un-actuated joint to a cart, which moves along
        a frictionless track. The pendulum starts upright, and the goal is to
        prevent it from falling over by increasing and reducing the cart's
        velocity.
    Source:
        This environment corresponds to the version of the cart-pole problem
        described by Barto, Sutton, and Anderson
    Observation:
        Type: Box(4)
        Num     Observation                 Min                     Max
        0       Cart Position               -4.8                    4.8
        1       Cart Velocity               -Inf                    Inf
        2       Pole 1 Angle                -0.418 rad (-24 deg)    0.418 rad (24 deg)
        3       Pole 1 Angular Velocity     -Inf                    Inf
        4       Pole 2 Angle                -0.418 rad (-24 deg)    0.418 rad (24 deg)
        5       Pole 2 Angular Velocity     -Inf                    Inf
    Actions:
        Type: Discrete(2)
        Num   Action
        0     Push cart to the left
        1     Push cart to the right
        Note: The amount the velocity that is reduced or increased is not
        fixed; it depends on the angle the pole is pointing. This is because
        the center of gravity of the pole increases the amount of energy needed
        to move the cart underneath it
    Reward:
        Reward is 1 for every step taken, including the termination step
    Starting State:
        All observations are assigned a uniform random value in [-0.05..0.05]
    Episode Termination:
        Pole Angle is more than 12 degrees.
        Cart Position is more than 2.4 (center of the cart reaches the edge of
        the display).
        Episode length is greater than 200.
        Solved Requirements:
        Considered solved when the average return is greater than or equal to
        195.0 over 100 consecutive trials.
    """

    metadata = {
        'render.modes': ['human', 'rgb_array'],
        'video.frames_per_second': 50
    }

    def __init__(self):
        self.gravity = 9.8
        self.masscart = 1.0

        # length and mass of pole 1
        # actually half the pole's length
        self.length_1 = 0.35
        self.masspole_1 = 0.1

        # length and mass of pole 2
        self.length_2 = 0.5
        self.masspole_2 = 0.1

        self.force_mag = 10.0
        self.tau = 0.02  # seconds between state updates
        # self.kinematics_integrator = 'euler'

        # changing parameter
        self.time = 0
        self.xacc = 0

        # Angle at which to fail the episode
        self.theta_threshold_radians = 12 * 2 * math.pi / 360
        self.x_threshold = 2.4

        # Angle limit set to 2 * theta_threshold_radians so failing observation
        # is still within bounds.
        high = np.array([
            # Cart position threshold
            self.x_threshold * 2,
            # Cart velocity threshold
            np.finfo(np.float32).max,
            # Poll 1 angle threshold
            self.theta_threshold_radians * 2,
            # Poll 1 Angular Velocity threshold
            np.finfo(np.float32).max,
            # Poll 2 angle threshold
            self.theta_threshold_radians * 2,
            # Poll 2 Angular Velocity threshold
            np.finfo(np.float32).max,
        ], dtype=np.float32)

        self.action_space = spaces.Discrete(2)
        self.observation_space = spaces.Box(-high, high, dtype=np.float32)

        self.seed()
        self.viewer = None
        self.state = None

        self.steps_beyond_done = None

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def step(self, action):
        self.time += self.tau
        err_msg = "%r (%s) invalid" % (action, type(action))
        assert self.action_space.contains(action), err_msg

        x, x_dot, theta_1, theta_1_dot, theta_2, theta_2_dot = self.state
        force = self.force_mag if action == 1 else -self.force_mag
        costheta_1 = math.cos(theta_1)
        sintheta_1 = math.sin(theta_1)
        polemass_length_1 = self.length_1 * self.masspole_1

        costheta_2 = math.cos(theta_2)
        sintheta_2 = math.sin(theta_2)
        polemass_length_2 = self.length_1 * self.masspole_1

        xdd = self.xacc

        def cart_acc(vc):
            # calculate force generated by each pole
            f1 = polemass_length_1 * theta_1_dot**2 * sintheta_1 +\
                (3/4)*self.masspole_1*costheta_1 * \
                (self.gravity * math.sin(theta_1_dot))

            f2 = polemass_length_2 * theta_2_dot**2 * sintheta_2 +\
                (3/4)*self.masspole_2*costheta_2 * \
                (self.gravity * math.sin(theta_2_dot))

            # calculate effective mass of each pole
            em1 = self.masspole_1*(1 - 0.75*costheta_1**2)
            em2 = self.masspole_2*(1 - 0.75*costheta_2**2)

            F = force+f1+f2
            total_mass = self.masscart + em1 + em2
            return F/(total_mass)

        def pole_acc_1(vp1):
            pa = (-3/4)*(1/self.length_1)*(xdd*costheta_1 +
                                           self.gravity*sintheta_1)
            return pa

        def pole_acc_2(vp2):
            pa = (-3/4)*(1/self.length_2)*(xdd*costheta_2 +
                                           self.gravity*sintheta_2)
            return pa

        new_x_dot = runge_kutta4(x_dot, cart_acc, self.time)
        new_x = x + self.tau * x_dot

        new_theta_1_dot = runge_kutta4(theta_1_dot, pole_acc_1, self.time)
        new_theta_1 = theta_1 + self.tau * theta_1_dot

        new_theta_2_dot = runge_kutta4(theta_2_dot, pole_acc_2, self.time)
        new_theta_2 = theta_2 + self.tau * theta_2_dot

        self.xacc = cart_acc(new_x_dot)

        self.state = (new_x, new_x_dot, new_theta_1,
                      new_theta_1_dot, new_theta_2, new_theta_2_dot)

        done = bool(
            new_x < -self.x_threshold
            or new_x > self.x_threshold
            or new_theta_1 < -self.theta_threshold_radians
            or new_theta_1 > self.theta_threshold_radians
            or new_theta_2 < -self.theta_threshold_radians
            or new_theta_2 > self.theta_threshold_radians
        )

        if not done:
            reward = 1.0
        elif self.steps_beyond_done is None:
            # Pole just fell!
            self.steps_beyond_done = 0
            reward = 1.0
        else:
            if self.steps_beyond_done == 0:
                logger.warn(
                    "You are calling 'step()' even though this "
                    "environment has already returned done = True. You "
                    "should always call 'reset()' once you receive 'done = "
                    "True' -- any further steps are undefined behavior."
                )
            self.steps_beyond_done += 1
            reward = 0.0

        return np.array(self.state), reward, done, {}

    def reset(self):
        self.state = self.np_random.uniform(low=-0.05, high=0.05, size=(6,))
        self.xacc = 0
        self.time = 0
        self.steps_beyond_done = None
        return np.array(self.state)

    def render(self, mode='human'):
        screen_width = 600
        screen_height = 400

        world_width = self.x_threshold * 2
        scale = screen_width/world_width
        carty = 100  # TOP OF CART
        polewidth = 10.0
        pole1len = scale * (2 * self.length_1)
        pole2len = scale * (2 * self.length_2)
        cartwidth = 50.0
        cartheight = 30.0

        if self.viewer is None:
            from gym.envs.classic_control import rendering
            self.viewer = rendering.Viewer(screen_width, screen_height)

            # add render cart
            l, r, t, b = -cartwidth / 2, cartwidth / 2, cartheight / 2, -cartheight / 2
            axleoffset = cartheight / 4.0
            cart = rendering.FilledPolygon([(l, b), (l, t), (r, t), (r, b)])
            self.carttrans = rendering.Transform()
            cart.add_attr(self.carttrans)
            self.viewer.add_geom(cart)

            # add render pole 1
            l, r, t, b = -polewidth / 2, polewidth / \
                2, pole1len - polewidth / 2, -polewidth / 2
            pole1 = rendering.FilledPolygon([(l, b), (l, t), (r, t), (r, b)])
            pole1.set_color(.8, .6, .4)
            self.pole1_trans = rendering.Transform(translation=(0, axleoffset))
            pole1.add_attr(self.pole1_trans)
            pole1.add_attr(self.carttrans)
            self.viewer.add_geom(pole1)

            # add render pole 2
            l, r, t, b = -polewidth / 2, polewidth / \
                2, pole2len - polewidth / 2, -polewidth / 2
            pole2 = rendering.FilledPolygon([(l, b), (l, t), (r, t), (r, b)])
            pole2.set_color(.8, .6, .4)
            self.pole2_trans = rendering.Transform(translation=(0, axleoffset))
            pole2.add_attr(self.pole2_trans)
            pole2.add_attr(self.carttrans)
            self.viewer.add_geom(pole2)

            self.axle = rendering.make_circle(polewidth/2)
            self.axle.add_attr(self.pole1_trans)
            self.axle.add_attr(self.pole2_trans)
            self.axle.add_attr(self.carttrans)
            self.axle.set_color(.5, .5, .8)
            self.viewer.add_geom(self.axle)
            self.track = rendering.Line((0, carty), (screen_width, carty))
            self.track.set_color(0, 0, 0)
            self.viewer.add_geom(self.track)

            self._pole1_geom = pole1
            self._pole2_geom = pole2

        if self.state is None:
            return None

        # Edit the pole polygon vertex
        pole1 = self._pole1_geom
        l, r, t, b = -polewidth / 2, polewidth / \
            2, pole1len - polewidth / 2, -polewidth / 2
        pole1.v = [(l, b), (l, t), (r, t), (r, b)]

        pole2 = self._pole2_geom
        l, r, t, b = -polewidth / 2, polewidth / \
            2, pole2len - polewidth / 2, -polewidth / 2
        pole2.v = [(l, b), (l, t), (r, t), (r, b)]

        # x = self.state
        x, x_dot, theta_1, theta_1_dot, theta_2, theta_2_dot = self.state

        cartx = x * scale + screen_width / 2.0  # MIDDLE OF CART
        self.carttrans.set_translation(cartx, carty)
        self.pole1_trans.set_rotation(theta_1)
        self.pole2_trans.set_rotation(theta_2)

        return self.viewer.render(return_rgb_array=mode == 'rgb_array')

    def close(self):
        if self.viewer:
            self.viewer.close()
            self.viewer = None
