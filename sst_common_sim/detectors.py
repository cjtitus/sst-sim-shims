from ophyd import Device, Signal, Component as Cpt, DeviceStatus
from ophyd.sim import SynSignal, EnumSignal
import numpy as np
from scipy.special import erf
import time as ttime
import threading


def norm_erf(x, width=1):
    return 0.5*(erf(2.0*x/width) + 1)


class SynSignalDelayed(SynSignal):

    def trigger(self):
        st = DeviceStatus(device=self)
        delay_time = self.exposure_time
        if delay_time:

            def sleep_and_finish():
                self.log.debug('sleep_and_finish %s', self)
                ttime.sleep(delay_time)
                st.set_finished()
            threading.Thread(target=sleep_and_finish, daemon=True).start()
        else:
            st.set_finished()
        return st

    def read(self):
        self.put(self._func())
        return super().read()


class SynErf(Device):
    val = Cpt(SynSignal, kind='hinted')
    Imax = Cpt(Signal, value=1, kind='config')
    center = Cpt(Signal, value=0, kind='config')
    width = Cpt(Signal, value=1, kind='config')
    noise = Cpt(EnumSignal, value='none', kind='config',
                enum_strings=('none', 'uniform', 'normal'))
    noise_multiplier = Cpt(Signal, value=0.1, kind='config')
    noise_sigma = Cpt(Signal, value=0.1, kind='config')

    def _compute(self):
        dist = self._distance()*self.sign
        width = self.width.get()
        center = self.center.get()
        Imax = self.Imax.get()
        noise = self.noise.get()

        v = Imax*norm_erf(dist, width)
        if noise == "normal":
            noise_sigma = self.noise_sigma.get()
            v = self.random_state.normal(v, noise_sigma)
        elif noise == "uniform":
            noise_multiplier = self.noise_multiplier.get()
            v += self.random_state.uniform(-1, 1)*noise_multiplier
        return v

    def __init__(self, name, distance_function, width=1, noise="none",
                 noise_sigma=0.1, noise_multiplier=0.1,
                 random_state=None, transmission=False, **kwargs):
        super().__init__(name=name, **kwargs)
        self._distance = distance_function
        self.sign = 1 if transmission else -1
        self.center.put(0)
        self.Imax.put(1)
        self.width.put(width)
        self.noise.put(noise)
        self.noise_sigma.put(noise_sigma)
        self.noise_multiplier.put(noise_multiplier)

        if random_state is None:
            random_state = np.random
        self.random_state = random_state
        self.val.name = self.name
        self.val.sim_set_func(self._compute)
        # Don't trigger during __init__, manipulator may not be set up yet
        # self.trigger()

    def trigger(self, *args, **kwargs):
        return self.val.trigger(*args, **kwargs)


class SynLinear(Device):
    val = Cpt(SynSignal, kind="hinted")
    offset = Cpt(Signal, value=0, kind="config")
    slope = Cpt(Signal, value=1, kind="config")

    def _compute(self):
        x = self._x()
        m = self.slope.get()
        b = self.offset.get()
        return m*x + b

    def __init__(self, name, x, offset=0, slope=1, **kwargs):
        super().__init__(name=name, **kwargs)
        self.offset.put(offset)
        self.slope.put(slope)
        self._x = x
        self.val.sim_set_func(self._compute)
        self.trigger()

    def trigger(self, *args, **kwargs):
        return self.val.trigger(*args, **kwargs)


class SynNormal(Device):
    val = Cpt(SynSignal, kind='hinted')
    center = Cpt(Signal, value=0, kind='config')
    width = Cpt(Signal, value=1, kind='config')

    def _compute(self):
        width = self.width.get()
        center = self.center.get()
        v = np.random.normal(center, width)
        return v

    def __init__(self, name, width=1, center=0, **kwargs):
        super().__init__(name=name, **kwargs)
        self.center.put(center)
        self.width.put(width)
        self.val.name = self.name
        self.val.sim_set_func(self._compute)
        self.trigger()

    def trigger(self, *args, **kwargs):
        return self.val.trigger(*args, **kwargs)


class SynCompound(Device):
    val = Cpt(SynSignalDelayed, kind="hinted")

    def _compute(self):
        vals = []
        for s in self.signal_list:
            vals.append(s.val.get())
        return self._func(*vals)

    def __init__(self, name, *, signal_list, func, **kwargs):
        super().__init__(name=name, **kwargs)
        self.signal_list = signal_list
        self._func = func
        self.val.sim_set_func(self._compute)

    def trigger(self, *args, **kwargs):
        return self.val.trigger(*args, **kwargs)


class SynMult(SynCompound):

    def __init__(self, name, *, signal_list, **kwargs):
        def func(*args):
            return np.prod(args)

        super().__init__(name, signal_list=signal_list, func=func, **kwargs)


class DerivedSynDevice(Device):
    val = Cpt(SynSignalDelayed, kind='hinted')

    def _compute(self):
        return self.signal.val.get()

    def __init__(self, name, signal, **kwargs):
        super().__init__(name=name, **kwargs)
        self.signal = signal
        self.val.sim_set_func(self._compute)

    def trigger(self, *args, **kwargs):
        return self.val.trigger(*args, **kwargs)


class SimI400Base(Device):
    exposure_sp = Cpt(Signal, name="exposure_time", kind="config")

    def set_exposure(self, exp_time):
        self.exposure_sp.set(f"{exp_time}")

    def _acquire(self, status):
        t = float(self.exposure_sp.get())
        ttime.sleep(t)
        status.set_finished()
        return

    def trigger(self, *args, **kwargs):
        status = DeviceStatus(self)
        threading.Thread(target=self._acquire, args=(status,), daemon=True).start()
        return status
