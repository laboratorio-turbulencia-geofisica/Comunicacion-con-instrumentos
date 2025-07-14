import numpy as np
from PyIOTech import daq, daqh
from Formatter import get_converted_data, GAIN_MAP
import matplotlib.pyplot as plt

gain_options = {
    "x1": daqh.DgainPS3kX1,
    "x2": daqh.DgainPS3kX2,
    "x5": daqh.DgainPS3kX5,
    "x10": daqh.DgainPS3kX10,
    "x20": daqh.DgainPS3kX20,
    "x50": daqh.DgainPS3kX50,
    "x100": daqh.DgainPS3kX100,
}

freq = int(200000)
T = 1

dev = daq.daqDevice(b'PersonalDaq3001{374679}')
flags = daqh.DafAnalog | daqh.DafBipolar | daqh.DafDifferential | daqh.DafSettle1us
channels = [0, 1]
gains_times = ["x1", "x1"]
gains = [gain_options[i] for i in gains_times]
flags_list = [flags] * len(channels)

dev.AdcSetScan(channels, gains, flags_list)
dev.AdcSetFreq(freq)
actual_freq = int(dev.AdcGetFreq())
iters = T * actual_freq

dev.AdcSetAcq(daqh.DaamNShot, 0, iters)
dev.AdcSetTrig(daqh.DdtsImmediate, 0, 0, 0, 0)
dev.AdcTransferSetBuffer(daqh.DatmUpdateBlock | daqh.DatmCycleOff, iters)
dev.AdcArm()
dev.AdcTransferStart()
dev.WaitForEvent(daqh.DteAdcDone)
data = np.array(dev.dataBuf, dtype=np.uint16)
dev.Close()

gains = [GAIN_MAP[i] for i in gains_times]

ts, vs = get_converted_data(data, actual_freq, len(channels), gains)

plt.plot(ts[0], vs[0], label="channel 1.")
plt.plot(ts[1], vs[1], label="channel 2.")
plt.xlabel("Tiempo [s]")
plt.ylabel("Voltaje [V]")
plt.legend()
plt.show() 
