import matplotlib.pyplot as plt
from PyIOTech import daq, daqh
import numpy as np
import time

max_voltage = 10.0
bit_depth = 16
def convert(vals):
    vals = np.array(vals)
    return vals * max_voltage * 2 / (2 ** bit_depth) - max_voltage

""" Configuración del dispositivo. """

device_name = b'PersonalDaq3001{374679}'

dev = daq.daqDevice(device_name)

flags = daqh.DafAnalog | daqh.DafBipolar | daqh.DafDifferential | daqh.DafSettle1us 
gain = daqh.DgainX1
iters = int(20) 
freq = int(5e5)   

""" Armado y Adquisición. """

dev.AdcSetScan([0, 1], [gain, gain], [flags, flags])
dev.AdcSetFreq(freq)

actual_freq = dev.AdcGetFreq()
print(f"Frecuencia de sampleo real por canal: {actual_freq} Hz.")

dev.AdcSetAcq(daqh.DaamNShot, 0, iters)
dev.AdcSetTrig(daqh.DdtsImmediate, 0, 0, 0, 0)
dev.AdcTransferSetBuffer(daqh.DatmUpdateBlock | daqh.DatmCycleOff, iters)
dev.AdcArm()
dev.AdcTransferStart()
dev.WaitForEvent(daqh.DteAdcDone)
dev.Close()

""" Conversión a voltaje y procesado. """

data = np.array(dev.dataBuf)
canal_1 = convert(data[::2])
canal_2 = convert(data[1::2])
tiempos = np.arange(iters)/actual_freq

plt.plot(tiempos*1e6, canal_1, ".-", color="black", label = "Canal 1")
plt.plot((tiempos + 1e-6)*1e6, canal_2, ".-", color="orange", label = "Canal 2")
plt.xlabel("Tiempo [$\mu$s]")
plt.ylabel("Amplitud [V]")
plt.legend()
plt.show()
