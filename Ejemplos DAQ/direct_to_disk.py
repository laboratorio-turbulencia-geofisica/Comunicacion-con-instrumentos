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
freq = int(1e6)
buf_size = int(10e4) 
file_name = "prueba.bin"

""" Armado y Adquisición. """

dev.AdcSetScan([0, 1], [gain, gain], [flags, flags])
dev.AdcSetFreq(freq)

actual_freq = dev.AdcGetFreq()
print(f"Frecuencia de sampleo real por canal: {actual_freq} Hz.")

dev.AdcSetAcq(daqh.DaamInfinitePost, 0, 0)
dev.AdcSetTrig(daqh.DatsSoftware, 0, 0, 0, 0)
dev.AdcTransferSetBuffer(daqh.DatmUpdateBlock | daqh.DatmCycleOn, buf_size) #  | daqh.DatmIgnoreOverruns 
dev.AdcSetDiskFile(file_name, daqh.DaomCreateFile, 0)
dev.AdcArm()
dev.AdcTransferStart()
dev.AdcSoftTrig()

# Loop para esperar datos y contarlos
start_time = time.time()
timeout = 1.0  # segundos de adquisición deseada
acqTermination = False

while not acqTermination:
    dev.WaitForEvent(daqh.DteAdcData)  # Espera evento de datos nuevos

    status = dev.AdcTransferGetStat()
    print(f"Transferidos: {status['retCount']} scans.")

    if time.time() - start_time > timeout:
        acqTermination = True

dev.AdcDisarm()
print(dev.AdcTransferGetStat())
# plt.plot(convert(dev.dataBuf))
dev.Close()

plt.show()


