import matplotlib.pyplot as plt
import numpy as np
import json
import os

# Mapa textual -> valor numérico de ganancia
GAIN_MAP = {
    "x1": 1,
    "x2": 2,
    "x5": 5,
    "x10": 10,
    "x20": 20,
    "x50": 50,
    "x100": 100,
}

def convert(binary_data, max_voltage=10.0, bit_depth=16, gain=1):
    """Convierte datos binarios a voltaje para un solo canal y ganancia."""
    return np.array(binary_data) * max_voltage * 2 / (2 ** bit_depth) / gain - max_voltage / gain

def get_converted_data(binary_data, sample_frequency, n_channels, gains, max_voltage=10.0, bit_depth=16):
    """Devuelve tiempos y voltajes por canal, aplicando ganancia adecuada."""
    voltages = np.array(binary_data)

    channels_data = [voltages[i::n_channels] for i in range(n_channels)]
    n_samples = len(channels_data[0])

    times = [np.arange(n_samples) / sample_frequency + i * 1e-6 for i in range(n_channels)]
    voltages_converted = [convert(ch_data, max_voltage, bit_depth, gain=gains[i]) for i, ch_data in enumerate(channels_data)]

    times_arr = np.vstack(times)
    voltages_arr = np.vstack(voltages_converted)
    return times_arr, voltages_arr

def read(filename, max_voltage=10.0, bit_depth=16, plot_values=False, check_metadata=False):
    """Lee archivo binario y metadata, devuelve tiempos y voltajes convertidos."""
    metadata_path = os.path.splitext(filename)[0] + "_metadata.json"
    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"Metadata not found: {metadata_path}")

    with open(metadata_path, 'r') as f:
        metadata = json.load(f)

    sample_frequency = metadata.get("frecuencia_Hz", 1_000_000)
    channels = metadata.get("canales", [0])
    scans = metadata.get("scans_totales", "Unknown")
    gains_txt = metadata.get("ganancias", ["x1"] * len(channels))
    gains = [GAIN_MAP.get(g, 1) for g in gains_txt]
    n_channels = len(channels)

    binary_data = np.fromfile(filename, dtype=np.uint16)

    if check_metadata:
        if scans != (saved_scans := len(binary_data) // n_channels):
            print(f"Warning! The number of scans transferred by the DAQ ({scans}) does not match the number of scans saved to disk ({saved_scans}). Maybe a buffer overrun occurred.")
        print(f"The file '{filename}' contains {saved_scans} scans, each for {n_channels} channels, sampled at {sample_frequency} Hz per channel.")

    times_arr, voltages_arr = get_converted_data(binary_data, sample_frequency, n_channels, gains, max_voltage, bit_depth)

    if plot_values:
        for i, (ts, vs) in enumerate(zip(times_arr, voltages_arr)):
            plt.plot(ts, vs, ".-", label=f"Canal {i+1}")
        plt.xlabel("Tiempo [s]")
        plt.ylabel("Voltaje [V]")
        plt.legend()
        plt.show()

    return times_arr, voltages_arr

if __name__ == "__main__":
    from tkinter import filedialog
    filename = filedialog.askopenfilename()# "prueba_5Hz_x1_x2_1Vpp.bin" 
    read(filename, check_metadata=True, plot_values=True)
