from operator import itemgetter
from fractions import Fraction

from artiq import *
from artiq.sim import devices as sim_devices
from artiq.test.hardware_testbench import ExperimentCase


def _run_on_host(k_class, **arguments):
    dmgr = dict()
    dmgr["core"] = sim_devices.Core(dmgr)
    k_inst = k_class(dmgr, **arguments)
    k_inst.run()
    return k_inst


class _Primes(EnvExperiment):
    def build(self):
        self.attr_device("core")
        self.attr_argument("output_list")
        self.attr_argument("maximum")

    @kernel
    def run(self):
        for x in range(1, self.maximum):
            d = 2
            prime = True
            while d*d <= x:
                if x % d == 0:
                    prime = False
                    break
                d += 1
            if prime:
                self.output_list.append(x)


class _Misc(EnvExperiment):
    def build(self):
        self.attr_device("core")

        self.input = 84
        self.al = [1, 2, 3, 4, 5]
        self.list_copy_in = [2*Hz, 10*MHz]

    @kernel
    def run(self):
        self.half_input = self.input//2
        self.decimal_fraction = Fraction("1.2")
        self.acc = 0
        for i in range(len(self.al)):
            self.acc += self.al[i]
        self.list_copy_out = self.list_copy_in


class _PulseLogger(EnvExperiment):
    def build(self):
        self.attr_device("core")
        self.attr_argument("output_list")
        self.attr_argument("name")

    def _append(self, t, l, f):
        if not hasattr(self, "first_timestamp"):
            self.first_timestamp = t
        self.output_list.append((self.name, t-self.first_timestamp, l, f))

    def int_usec(self, mu):
        return round(mu_to_seconds(mu, self.core)*1000000)

    def on(self, t, f):
        self._append(self.int_usec(t), True, f)

    def off(self, t):
        self._append(self.int_usec(t), False, 0)

    @kernel
    def pulse(self, f, duration):
        self.on(now_mu(), f)
        delay(duration)
        self.off(now_mu())


class _Pulses(EnvExperiment):
    def build(self):
        self.attr_device("core")
        self.attr_argument("output_list")

        for name in "a", "b", "c", "d":
            pl = _PulseLogger(*self.dbs(),
                              output_list=self.output_list,
                              name=name)
            setattr(self, name, pl)

    @kernel
    def run(self):
        for i in range(3):
            with parallel:
                with sequential:
                    self.a.pulse(100+i, 20*us)
                    self.b.pulse(200+i, 20*us)
                with sequential:
                    self.c.pulse(300+i, 10*us)
                    self.d.pulse(400+i, 20*us)


class _MyException(Exception):
    pass


class _Exceptions(EnvExperiment):
    def build(self):
        self.attr_device("core")
        self.attr_argument("trace")

    @kernel
    def run(self):
        for i in range(10):
            self.trace.append(i)
            if i == 4:
                try:
                    self.trace.append(10)
                    try:
                        self.trace.append(11)
                        break
                    except:
                        pass
                    else:
                        self.trace.append(12)
                    try:
                        self.trace.append(13)
                    except:
                        pass
                except _MyException:
                    self.trace.append(14)

        for i in range(4):
            try:
                self.trace.append(100)
                if i == 1:
                    raise _MyException
                elif i == 2:
                    raise IndexError
            except (TypeError, IndexError):
                self.trace.append(101)
                raise
            except:
                self.trace.append(102)
            else:
                self.trace.append(103)
            finally:
                self.trace.append(104)


class _RPCExceptions(EnvExperiment):
    def build(self):
        self.attr_device("core")
        self.attr_argument("catch", FreeValue(False))

        self.success = False

    def exception_raiser(self):
        raise _MyException

    @kernel
    def run(self):
        if self.catch:
            self.do_catch()
        else:
            self.do_not_catch()

    @kernel
    def do_not_catch(self):
        self.exception_raiser()

    @kernel
    def do_catch(self):
        try:
            self.exception_raiser()
        except _MyException:
            self.success = True


class HostVsDeviceCase(ExperimentCase):
    def test_primes(self):
        l_device, l_host = [], []
        self.execute(_Primes, maximum=100, output_list=l_device)
        _run_on_host(_Primes, maximum=100, output_list=l_host)
        self.assertEqual(l_device, l_host)

    def test_misc(self):
        for f in self.execute, _run_on_host:
            uut = f(_Misc)
            self.assertEqual(uut.half_input, 42)
            self.assertEqual(uut.decimal_fraction, Fraction("1.2"))
            self.assertEqual(uut.acc, sum(uut.al))
            self.assertEqual(uut.list_copy_in, uut.list_copy_out)

    def test_pulses(self):
        l_device, l_host = [], []
        self.execute(_Pulses, output_list=l_device)
        _run_on_host(_Pulses, output_list=l_host)
        l_host = sorted(l_host, key=itemgetter(1))
        for channel in "a", "b", "c", "d":
            c_device = [x for x in l_device if x[0] == channel]
            c_host = [x for x in l_host if x[0] == channel]
            self.assertEqual(c_device, c_host)

    def test_exceptions(self):
        t_device, t_host = [], []
        with self.assertRaises(IndexError):
            self.execute(_Exceptions, trace=t_device)
        with self.assertRaises(IndexError):
            _run_on_host(_Exceptions, trace=t_host)
        self.assertEqual(t_device, t_host)

    def test_rpc_exceptions(self):
        for f in self.execute, _run_on_host:
            with self.assertRaises(_MyException):
                f(_RPCExceptions, catch=False)
            uut = self.execute(_RPCExceptions, catch=True)
            self.assertTrue(uut.success)
