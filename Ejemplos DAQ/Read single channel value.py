from PyIOTech import daq, daqh

device_name = b'PersonalDaq3001{374679}' # <-- Your device here.
channel = 0
gain = daqh.DgainX1
flags = daqh.DafAnalog | daqh.DafUnsigned | daqh.DafBipolar | daqh.DafDifferential
max_voltage = 10.0
bit_depth = 16

try:
    dev = daq.daqDevice(device_name)
    data = dev.AdcRd(channel, gain, flags)
    # Convert sample from unsigned integer value to bipolar voltage.
    data = data*max_voltage*2/(2**bit_depth) - max_voltage
    print(data)
finally:
    dev.Close()

