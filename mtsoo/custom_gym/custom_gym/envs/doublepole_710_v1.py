import math
import gym
from gym import spaces, logger
from gym.utils import seeding
import numpy as np


class DoublePole710v1(gym.Env):
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
        self.length_1 = 1
        self.masspole_1 = 0.1

        # length and mass of pole 2
        self.length_2 = 0.7
        self.masspole_2 = 0.05

        self.force_mag = 10.0
        self.tau = 0.01  # seconds between state updates
        self.fric = 0
        self.cart_fric = 0
        # self.kinematics_integrator = 'euler'
        self.kinematics_integrator = 'RK4'

        # changing parameter
        self.T = 0
        self.cart_v = 0
        self.pole1_v = 0
        self.pole2_v = 0

        self.past_result = []

        # Angle at which to fail the episode
        self.theta_threshold_radians = 12 * 2 * math.pi / 360
        self.x_threshold = 2.4

        # Angle limit set to 2 * theta_threshold_radians so failing observation
        # is still within bounds.
        high = np.array([
            # Cart position threshold
            self.x_threshold * 2,
            # Poll 1 angle threshold
            self.theta_threshold_radians * 2,
            # Poll 2 angle threshold
            self.theta_threshold_radians * 2,
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

    def _cal_acc(self, force, state):
        x, xd, theta1, theta1d, theta2, theta2d = state

        costheta_1 = math.cos(theta1)
        sintheta_1 = math.sin(theta1)
        polemass_length_1 = self.length_1 * self.masspole_1

        costheta_2 = math.cos(theta2)
        sintheta_2 = math.sin(theta2)
        polemass_length_2 = self.length_2 * self.masspole_2

        fric1 = (self.fric * theta1)/polemass_length_1
        fric2 = (self.fric * theta2)/polemass_length_2

        # calculate force generated by each pole
        f1 = polemass_length_1 * (theta1d**2) * sintheta_1 +\
            0.75*self.masspole_1*costheta_1 * \
            (fric1 + self.gravity * sintheta_1)

        f2 = polemass_length_2 * theta2d**2 * sintheta_2 +\
            0.75*self.masspole_2*costheta_2 * \
            (fric2 + self.gravity * sintheta_2)

        # calculate effective mass of each pole
        em1 = self.masspole_1*(1 - 0.75*costheta_1**2)
        em2 = self.masspole_2*(1 - 0.75*costheta_2**2)

        F = force+f1+f2 - self.cart_fric*np.sign(xd)
        total_mass = self.masscart + em1 + em2
        ca = F/(total_mass)

        pa1 = (-0.75)*(ca * costheta_1 + self.gravity*sintheta_1)/self.length_1
        pa2 = (-0.75)*(ca * costheta_2 + self.gravity*sintheta_2)/self.length_2

        return [ca, pa1, pa2]

    def step(self, action):
        self.T += 1
        err_msg = "%r (%s) invalid" % (action, type(action))
        assert self.action_space.contains(action), err_msg

        x,  theta1, theta2 = self.state
        xd = self.cart_v
        theta1d = self.pole1_v
        theta2d = self.pole2_v

        self.past_result.append([x, xd, theta1, theta1d])

        force = self.force_mag if action == 1 else -self.force_mag

        if self.kinematics_integrator == 'euler':
            s = np.array([x, xd, theta1, theta1d, theta2, theta2d])
            xdd, theta1dd, theta2dd = self._cal_acc()
            new_x = x + xd*self.tau
            new_x_dot = xd + xdd*self.tau
            new_theta_1 = theta1 + theta1d*self.tau
            new_theta_1_dot = theta1d + theta1dd*self.tau
            new_theta_2 = theta2 + theta2d*self.tau
            new_theta_2_dot = theta2d + theta2dd*self.tau
        else:
            h = 0.01
            h2 = h/2
            h6 = h/6
            k1 = k2 = k3 = k4 = np.zeros((6, ))

            s = np.array([x, xd, theta1, theta1d, theta2, theta2d])
            k1[1], k1[3], k1[5] = self._cal_acc(force, s)
            k1[0] = s[1]
            k1[2] = s[3]
            k1[4] = s[5]

            ns = s + h2*k1
            k2[1], k2[3], k2[5] = self._cal_acc(force, ns)
            k2[0] = ns[1]
            k2[2] = ns[3]
            k2[4] = ns[5]

            nns = s + h2*k2
            k3[1], k3[3], k3[5] = self._cal_acc(force, nns)
            k3[0] = nns[1]
            k3[2] = nns[3]
            k3[4] = nns[5]

            nnns = s + h*k3
            k4[1], k4[3], k4[5] = self._cal_acc(force, nnns)
            k4[0] = nnns[1]
            k4[2] = nnns[3]
            k4[4] = nnns[5]

            next_state = s + h6*(k1+2*(k2+k3)+k4)

            new_x, new_x_dot, new_theta_1, new_theta_1_dot, new_theta_2, new_theta_2_dot = next_state
        self.cart_v = new_x_dot
        self.pole1_v = new_theta_1_dot
        self.pole2_v = new_theta_2_dot

        self.state = (new_x, new_theta_1, new_theta_2)

        f1 = self.T/1000
        f2 = 0
        if self.T >= 100:
            vp = 0
            for i in range(100):
                vp += np.sum(np.abs(self.past_result[i]))
            f2 = 0.75/vp
            self.past_result.pop(0)

        done = bool(
            new_x < -self.x_threshold
            or new_x > self.x_threshold
            or new_theta_1 < -self.theta_threshold_radians
            or new_theta_1 > self.theta_threshold_radians
            or new_theta_2 < -self.theta_threshold_radians
            or new_theta_2 > self.theta_threshold_radians
        )

        if not done:
            reward = 0.1*f1 + 0.9*f2
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
        self.state = self.np_random.uniform(low=-0.05, high=0.05, size=(3,))
        self.T = 0
        self.cart_v, self.pole1_v, self.pole2_v = self.np_random.uniform(
            low=-0.05, high=0.05, size=(3,))

        self.past_result = [
            [self.state[0], self.cart_v, self.state[1], self.pole1_v]]

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
            pole2.set_color(.8, .3, .8)
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
        x,  theta_1, theta_2 = self.state

        cartx = x * scale + screen_width / 2.0  # MIDDLE OF CART
        self.carttrans.set_translation(cartx, carty)
        self.pole1_trans.set_rotation(theta_1)
        self.pole2_trans.set_rotation(theta_2)

        return self.viewer.render(return_rgb_array=mode == 'rgb_array')

    def close(self):
        if self.viewer:
            self.viewer.close()
            self.viewer = None
