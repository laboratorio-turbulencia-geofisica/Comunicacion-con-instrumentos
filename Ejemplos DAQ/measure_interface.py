import tkinter as tk
from tkinter import ttk, filedialog
import threading
import time
import numpy as np
from PyIOTech import daq, daqh
from metadata import guardar_metadata, actualizar_metadata_final

class AcquisitionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Adquisición de Datos - DAQ")

        # Mapa de ganancias posibles
        self.gain_options = {
            "x1": daqh.DgainPS3kX1,
            "x2": daqh.DgainPS3kX2,
            "x5": daqh.DgainPS3kX5,
            "x10": daqh.DgainPS3kX10,
            "x20": daqh.DgainPS3kX20,
            "x50": daqh.DgainPS3kX50,
            "x100": daqh.DgainPS3kX100,
        }
        self.channel_gains_vars = []

        # Entradas
        ttk.Label(root, text="Frecuencia [Hz]:").grid(row=0, column=0, sticky='e')
        self.freq_entry = ttk.Entry(root)
        self.freq_entry.insert(0, "1000000")
        self.freq_entry.grid(row=0, column=1)

        self.quantity_frame = ttk.Frame(root)
        self.quantity_frame.grid(row=1, column=0, columnspan=2, sticky='w')
        ttk.Label(self.quantity_frame, text="Cantidad de").grid(row=0, column=0, sticky='e')
        self.mode_var = tk.StringVar(value="tiempo")
        self.mode_menu = ttk.OptionMenu(self.quantity_frame, self.mode_var, "tiempo", "tiempo", "iteraciones", command=self.toggle_buffer_entry)
        self.mode_menu.grid(row=0, column=1)
        ttk.Label(self.quantity_frame, text=":").grid(row=0, column=2)
        self.duration_entry = ttk.Entry(self.quantity_frame)
        self.duration_entry.insert(0, "10")
        self.duration_entry.grid(row=0, column=3)

        ttk.Label(root, text="Nombre del archivo:").grid(row=3, column=0, sticky='e')
        self.filename_entry = ttk.Entry(root)
        self.filename_entry.insert(0, "prueba.bin")
        self.filename_entry.grid(row=3, column=1)

        self.buffer_label = ttk.Label(root, text="Tamaño de buffer [scans] (infinito):")
        self.buffer_label.grid(row=4, column=0, sticky='e')
        self.buffer_entry = ttk.Entry(root)
        self.buffer_entry.insert(0, "50000")
        self.buffer_entry.grid(row=4, column=1)
        
        self.acq_mode_var = tk.StringVar(value="infinito")
        self.acq_mode_var.trace_add("write", self.toggle_buffer_entry)
        ttk.Label(root, text="Modo adquisición:").grid(row=2, column=0, sticky='e')
        self.acq_menu = ttk.OptionMenu(root, self.acq_mode_var, "infinito", "infinito", "finito")
        self.acq_menu.grid(row=2, column=1)

        self.channel_list = []
        self.channel_label = ttk.Label(root, text="Canales:")
        self.channel_label.grid(row=5, column=0, columnspan=2)

        self.add_channel_button = ttk.Button(root, text="Agregar canal", command=self.add_channel)
        self.add_channel_button.grid(row=6, column=0, columnspan=2)

        self.start_button = ttk.Button(root, text="Iniciar", command=self.start_acquisition)
        self.start_button.grid(row=7, column=0)

        self.stop_button = ttk.Button(root, text="Detener", command=self.stop_acquisition)
        self.stop_button.grid(row=7, column=1)

        self.status_label = ttk.Label(root, text="Esperando...")
        self.status_label.grid(row=8, column=0, columnspan=2)

        self.root.bind("<Return>", lambda event: self.start_acquisition())

        self.running = False
        self.dev = None
        self.toggle_buffer_entry()
        self.add_channel()

    def toggle_buffer_entry(self, *args):
        if self.acq_mode_var.get() == "finito":
            self.buffer_label.grid_remove()
            self.buffer_entry.grid_remove()
        else:
            self.buffer_label.grid()
            self.buffer_entry.grid()

    def add_channel(self):
        new_channel = self.channel_list[-1] + 1 if self.channel_list else 0
        if new_channel > 15:
            return
        self.channel_list.append(new_channel)
        self.channel_label.config(text=f"Canales: {self.channel_list}")

        gain_var = tk.StringVar(value="x1")
        self.channel_gains_vars.append(gain_var)
        row = 9 + len(self.channel_gains_vars)

        ttk.Label(self.root, text=f"Canal {new_channel} ganancia:").grid(row=row, column=0, sticky='e')
        ttk.OptionMenu(self.root, gain_var, "x1", *self.gain_options.keys()).grid(row=row, column=1)

    def start_acquisition(self):
        if self.running:
            return
        self.running = True
        self.status_label.config(text="Adquisición iniciada...")
        t = threading.Thread(target=self.run_acquisition)
        t.start()

    def stop_acquisition(self):
        self.running = False
        self.status_label.config(text="Adquisición detenida por usuario.")

    def run_acquisition(self):
        freq = int(self.freq_entry.get())
        file_name = self.filename_entry.get()
        mode = self.mode_var.get()
        acq_mode = self.acq_mode_var.get()
        try:
            duration_or_iters = float(self.duration_entry.get())
        except ValueError:
            duration_or_iters = None

        if acq_mode == "infinito":
            buf_size = int(self.buffer_entry.get())

        self.dev = daq.daqDevice(b'PersonalDaq3001{374679}')
        flags = daqh.DafAnalog | daqh.DafBipolar | daqh.DafDifferential | daqh.DafSettle1us
        gains = [self.gain_options[var.get()] for var in self.channel_gains_vars]
        flags_list = [flags] * len(self.channel_list)

        self.dev.AdcSetScan(self.channel_list, gains, flags_list)
        self.dev.AdcSetFreq(freq)
        actual_freq = self.dev.AdcGetFreq()
        print(f"Frecuencia real: {actual_freq} Hz")

        guardar_metadata(
            file_name=file_name,
            frecuencia=actual_freq,
            canales=self.channel_list,
            ganancias=[var.get() for var in self.channel_gains_vars],
            flags=flags_list
        )

        if acq_mode == "finito" and duration_or_iters is not None:
            iters = int(duration_or_iters) if mode == "iteraciones" else int(duration_or_iters * actual_freq)
            self.dev.AdcSetAcq(daqh.DaamNShot, 0, iters)
            self.dev.AdcSetTrig(daqh.DdtsImmediate, 0, 0, 0, 0)
            self.dev.AdcTransferSetBuffer(daqh.DatmUpdateBlock | daqh.DatmCycleOff, iters)
            self.dev.AdcArm()
            self.dev.AdcTransferStart()
            self.dev.WaitForEvent(daqh.DteAdcDone)
            data = np.array(self.dev.dataBuf, dtype=np.uint16)
            data.tofile(file_name)
            actualizar_metadata_final(file_name, iters)
            self.status_label.config(text=f"Finalizado. Total: {iters} scans")
        else:
            self.dev.AdcSetAcq(daqh.DaamInfinitePost, 0, 0)
            self.dev.AdcSetTrig(daqh.DatsSoftware, 0, 0, 0, 0)
            self.dev.AdcTransferSetBuffer(daqh.DatmUpdateBlock | daqh.DatmCycleOn, buf_size)
            self.dev.AdcSetDiskFile(file_name, daqh.DaomCreateFile, 0)
            self.dev.AdcArm()
            self.dev.AdcTransferStart()
            self.dev.AdcSoftTrig()

            start_time = time.time()
            total_count = 0

            while self.running:
                self.dev.WaitForEvent(daqh.DteAdcData)
                status = self.dev.AdcTransferGetStat()
                total_count = status['retCount']
                self.status_label.config(text=f"Scans transferidos: {total_count}")

                if duration_or_iters is not None:
                    if mode == "tiempo" and (time.time() - start_time) > duration_or_iters:
                        self.status_label.config(text="Adquisición detenida por duración.")
                        break
                    elif mode == "iteraciones" and total_count >= duration_or_iters:
                        self.status_label.config(text="Adquisición detenida por cantidad de iteraciones.")
                        break

            self.dev.AdcDisarm()
            final_status = self.dev.AdcTransferGetStat()
            self.status_label.config(text=f"Finalizado. Total: {final_status['retCount']} scans")
            actualizar_metadata_final(file_name, final_status['retCount'])

        self.dev.Close()
        self.running = False

# Lanzar interfaz
root = tk.Tk()
app = AcquisitionApp(root)
root.mainloop()
