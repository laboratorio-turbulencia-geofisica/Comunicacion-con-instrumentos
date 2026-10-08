"""
PyIOTech/daq.py — Reemplazo para Linux de PyIOTech (que usaba DaqX64.dll de Windows).

Misma API que el PyIOTech original, así los scripts existentes funcionan sin
cambios (from PyIOTech import daq, daqh). Habla directo con la placa por USB
a través de _pdaq3k.py.

Implementado: daqDevice, Close, AdcSetScan/AdcGetScan, AdcSetFreq/AdcGetFreq,
AdcSetRate, AdcSetAcq (NShot / Infinite), AdcSetTrig (Immediate / Software),
AdcSoftTrig, AdcTransferSetBuffer (CycleOn = buffer circular), AdcSetDiskFile,
AdcArm/AdcDisarm, AdcTransferStart/Stop, AdcTransferGetStat, WaitForEvent
(DteAdcData / DteAdcDone), AdcRd, AdcRdScan, SetTimeout, DacWt (experimental),
GetDeviceList/GetDeviceCount, GetDeviceProperties.

Los datos son cuentas de 16 bits sin signo (0x8000 = 0 V), igual que con DaqX
y DafUnsigned: voltaje = cuentas * 2*Vmax / 65536 - Vmax. Por defecto se les
aplica la calibración de fábrica de la EEPROM (ganancia y offset por rango);
daqDevice(..., calibrate=False) entrega las cuentas crudas.
"""
import threading
import time

import numpy as np

from . import daqh
from ._pdaq3k import PDaq3000, PDaqUSBError, scan_entry

MAX_AGGREGATE_RATE = 1_000_000      # muestras/s totales del ADC

_ERRORS = {
    0x10: "Timeout esperando el evento",
    0x11: "Parámetro inválido",
    0x12: "No hay scan configurada (AdcSetScan)",
    0x13: "No hay buffer configurado (AdcTransferSetBuffer)",
    0x14: "Función no soportada en el driver Linux",
    0x15: "Error de comunicación USB",
}


class DaqError(Exception):
    def __init__(self, errcode, detail=None):
        self.errcode = errcode
        self.msg = FormatError(errcode) + (f": {detail}" if detail else "")
        self.args = (self.errcode, self.msg)

    def __str__(self):
        return '%i ' % self.errcode + self.msg

    def __getitem__(self, key):
        return self.args[key]


def FormatError(errNum):
    return _ERRORS.get(errNum, f"Error {errNum}")


def GetDeviceCount():
    return len(GetDeviceList())


def GetDeviceList():
    import usb1
    with usb1.USBContext() as ctx:
        for pid in (0x2C01, 0x0470):
            if ctx.getByVendorIDAndProductID(0x0622, pid) is not None:
                return [b'PersonalDaq3001']
    return []


def GetDriverVersion():
    return 0x0300


class daqDevice(object):

    def __init__(self, deviceName=b'PersonalDaq3001', verbose=True, calibrate=True):
        # Hay una sola placa; el nombre (p.ej. b'PersonalDaq3001{374679}') se ignora.
        self.deviceName = deviceName
        try:
            self._hw = PDaq3000(verbose=verbose)
            self._hw.initialize()
        except PDaqUSBError as e:
            raise DaqError(0x15, str(e)) from e
        self.handle = 1
        self.calibrate = calibrate        # aplicar la calibración de fábrica de la EEPROM
        self._lock = threading.Condition()
        self._timeout_ms = None          # None = sin timeout (Ctrl+C sigue funcionando)
        self.chanCount = 0
        self._channels, self._gains, self._flags = [], [], []
        self._freq = 1000.0
        self._acq_mode = daqh.DaamNShot
        self._post_count = 0
        self._trig_source = daqh.DatsImmediate
        self._transfer_mask = 0
        self.scanCount = 0
        self.dataBuf = None
        self._disk_file = None
        self._disk_name = None
        self._armed = False
        self._running = False
        self._done = False
        self._total = 0                  # muestras recibidas (no scans)
        self._wanted = 0                 # muestras a guardar en NShot
        self._last_seen = 0
        self._last_data_time = 0.0
        self.props = self.GetDeviceProperties()

    def __del__(self):
        try:
            self.Close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.Close()

    def CloseDevice(self):
        self.Close()

    def Online(self):
        return self.handle is not None

    def Close(self):
        if getattr(self, 'handle', None) is None:
            return
        self._stop()
        self._hw.close()
        self.handle = None

    def GetDeviceProperties(self):
        return {
            'deviceType': 0x31, 'basePortAddress': 0, 'dmaChannel': 0,
            'socket': 0, 'interruptLevel': 0, 'protocol': 0,
            'alias': self.deviceName, 'maxAdChannels': 16, 'maxDaChannels': 4,
            'maxDigInputBits': 24, 'maxDigOutputBits': 24,
            'maxCtrChannels': 4, 'mainUnitAdChannels': 16,
            'mainUnitDaChannels': 4, 'mainUnitDigInputBits': 24,
            'mainUnitDigOutputBits': 24, 'mainUnitCtrChannels': 4,
            'adFifoSize': 2048, 'daFifoSize': 2048, 'adResolution': 16,
            'daResolution': 16, 'adMinFreq': 0.0001, 'adMaxFreq': 1_000_000.0,
            'daMinFreq': 0.0001, 'daMaxFreq': 1_000_000.0,
        }

    def SetTimeout(self, mSecTimeout):
        self._timeout_ms = int(mSecTimeout) if mSecTimeout else None

    # ── configuración del ADC ─────────────────────────────────────────────
    def AdcSetScan(self, channels, gains, flags):
        if type(flags) != list:
            flags = [flags] * len(channels)
        if type(gains) != list:
            gains = [gains] * len(channels)
        if not (len(channels) == len(gains) == len(flags)) or not channels:
            raise DaqError(0x11, "channels, gains y flags deben tener el mismo largo")
        for c in channels:
            if not 0 <= int(c) <= 15:
                raise DaqError(0x11, f"canal inválido {c}")
        self._channels = [int(c) for c in channels]
        self._gains = [int(g) for g in gains]
        self._flags = [int(f) for f in flags]
        self.chanCount = len(channels)

    def AdcGetScan(self):
        return {'channels': list(self._channels), 'gains': list(self._gains),
                'flags': list(self._flags), 'chanCount': self.chanCount}

    def AdcSetFreq(self, freq):
        freq = float(freq)
        if freq <= 0:
            raise DaqError(0x11, "frecuencia debe ser > 0")
        self._freq = freq

    def AdcGetFreq(self):
        div = PDaq3000.pacer_divisor(self._freq)
        return 48_000_000.0 / (div + 1)

    def AdcSetRate(self, mode, state, reqValue):
        if mode == daqh.DarmFrequency:
            self.AdcSetFreq(reqValue)
        elif mode == daqh.DarmPeriod:
            self.AdcSetFreq(1.0 / reqValue)
        return self.AdcGetFreq()

    def AdcSetClockSource(self, clockSettings):
        pass                                   # sólo pacer interno

    def AdcSetAcq(self, mode, preTrigCount=0, postTrigCount=0):
        if mode not in (daqh.DaamNShot, daqh.DaamInfinitePost):
            raise DaqError(0x14, f"modo de adquisición {mode}")
        self._acq_mode = mode
        self._post_count = int(postTrigCount or 0)

    def AdcSetTrig(self, triggerSource, rising, level, hysteresis, channel):
        if triggerSource not in (daqh.DatsImmediate, daqh.DatsSoftware):
            raise DaqError(0x14, f"fuente de trigger {triggerSource}")
        self._trig_source = triggerSource

    def AdcSetDiskFile(self, filename, openMode, preWrite):
        if isinstance(filename, bytes):
            filename = filename.decode()
        mode = 'ab' if openMode == daqh.DaomAppendFile else 'wb'
        self._disk_name = (filename, mode)

    def AdcTransferSetBuffer(self, transferMask, scanCount, buf=1):
        if not self.chanCount:
            raise DaqError(0x12)
        self.scanCount = int(scanCount)
        self._transfer_mask = transferMask
        self.dBufSz = self.scanCount * self.chanCount
        self.dataBuf = np.zeros(self.dBufSz, dtype=np.uint16) if buf else None

    # ── control ───────────────────────────────────────────────────────────
    def AdcArm(self):
        if not self.chanCount:
            raise DaqError(0x12)
        self._armed = True
        if self._trig_source == daqh.DatsImmediate:
            self._start()

    def AdcTransferStart(self):
        if not self._armed:
            self.AdcArm()

    def AdcSoftTrig(self):
        if self._armed and not self._running:
            self._start()

    def AdcDisarm(self):
        self._stop()
        self._armed = False

    def AdcTransferStop(self):
        self._stop()

    def AdcTransferGetStat(self):
        with self._lock:
            self._raise_stream_error()
            return {'active': self._status_flags(),
                    'retCount': self._ret_count()}

    def WaitForEvent(self, event):
        deadline = None if self._timeout_ms is None else time.time() + self._timeout_ms / 1000.0
        with self._lock:
            if event == daqh.DteAdcDone:
                cond = lambda: self._done or not self._running
            elif event == daqh.DteAdcData:
                cond = lambda: self._total > self._last_seen or not self._running
            else:
                raise DaqError(0x14, f"evento {event}")
            while not cond():
                self._raise_stream_error()
                if deadline is not None and time.time() > deadline:
                    raise DaqError(0x10)
                if self._running and time.time() - self._last_data_time > 5.0:
                    raise DaqError(0x15, "la placa dejó de mandar datos")
                self._lock.wait(0.1)
            self._last_seen = self._total
        if event == daqh.DteAdcDone and self._done:
            self._stop()

    # ── lectura simple ────────────────────────────────────────────────────
    def AdcRd(self, chan, gain, flags, convert=None):
        vals = self.AdcRdScan(chan, chan, gain, flags)
        sample = vals[0]
        return convert(sample) if convert else sample

    def AdcRdScan(self, startChan, endChan, gain, flags, convert=None):
        chans = list(range(int(startChan), int(endChan) + 1))
        n_scans = 32
        data = self._quick_acq(chans, [gain] * len(chans), [flags] * len(chans),
                               200_000.0 / len(chans), n_scans)
        # descartamos el comienzo (asentamiento de la entrada) y tomamos la mediana
        tail = data.reshape(n_scans, len(chans))[n_scans // 2:]
        vals = [int(np.median(tail[:, i])) for i in range(len(chans))]
        return [convert(v) for v in vals] if convert else vals

    def _quick_acq(self, chans, gains, flags, freq, n_scans):
        saved = (self._channels, self._gains, self._flags, self.chanCount, self._freq,
                 self._acq_mode, self._post_count, self._trig_source, self._transfer_mask,
                 self.scanCount, self.dataBuf, self._disk_name)
        try:
            self.AdcSetScan(chans, gains, flags)
            self.AdcSetFreq(freq)
            self.AdcSetAcq(daqh.DaamNShot, 0, n_scans)
            self.AdcSetTrig(daqh.DatsImmediate, 0, 0, 0, 0)
            self.AdcTransferSetBuffer(daqh.DatmCycleOff, n_scans)
            self._disk_name = None
            self.AdcArm()
            self.WaitForEvent(daqh.DteAdcDone)
            return self.dataBuf.copy()
        finally:
            (self._channels, self._gains, self._flags, self.chanCount, self._freq,
             self._acq_mode, self._post_count, self._trig_source, self._transfer_mask,
             self.scanCount, self.dataBuf, self._disk_name) = saved
            self._armed = False

    # ── DAC ───────────────────────────────────────────────────────────────
    def DacWt(self, deviceType, chan, dataVal):
        """EXPERIMENTAL: misma conversión que el PyIOTech original (dataVal en volts)."""
        if dataVal >= 10.0:
            counts = 65535
        elif dataVal <= -10.0:
            counts = 0
        else:
            counts = int((dataVal + 10.0) / (20.0 / 65535))
        self._hw.dac_write(int(chan), counts)

    def __getattr__(self, name):
        if name.startswith(('Dac', 'Cal', 'Cvt', 'IO', 'Ctr', 'Tmr', 'Set')):
            def _unsupported(*a, **k):
                raise DaqError(0x14, f"{name} todavía no está implementada en el driver Linux")
            return _unsupported
        raise AttributeError(name)

    # ── interno ───────────────────────────────────────────────────────────
    def _ret_count(self):
        return self._total // self.chanCount if self.chanCount else 0

    def _status_flags(self):
        f = 0
        if self._armed:
            f |= daqh.DaafAcqArmed
        if self._running:
            f |= daqh.DaafAcqActive | daqh.DaafTransferActive
        return f

    def _raise_stream_error(self):
        err = self._hw.stream_error
        if err is not None:
            raise DaqError(0x15, str(err))

    def _start(self):
        if self._running:
            return
        if self.dataBuf is None and self._disk_name is None:
            raise DaqError(0x13)
        nch = self.chanCount
        rate = self.AdcGetFreq() * nch
        if rate > MAX_AGGREGATE_RATE * 1.001:
            print(f"[PDaq3000] Aviso: {rate:.0f} muestras/s totales supera el máximo "
                  f"de la placa ({MAX_AGGREGATE_RATE}); puede haber overrun.")
        entries = [scan_entry(c, g, f, i == nch - 1)
                   for i, (c, g, f) in enumerate(zip(self._channels, self._gains, self._flags))]
        self._hw.load_scan_list(entries)
        self._total = 0
        self._last_seen = 0
        self._done = False
        self._cyclic = bool(self._transfer_mask & daqh.DatmCycleOn) or \
            self._acq_mode == daqh.DaamInfinitePost
        if self._acq_mode == daqh.DaamNShot:
            n = self._post_count or self.scanCount
            self._wanted = n * nch
        else:
            self._wanted = None
        self._cal_coefs(entries)
        self._disk_file = open(*self._disk_name) if self._disk_name else None
        self._carry = b''
        self._running = True
        self._last_data_time = time.time()
        self._hw.start_stream(PDaq3000.pacer_divisor(self._freq), self._on_data, rate * 2)

    def _cal_coefs(self, entries):
        """Coeficientes por posición en la scan list: cuentas_corr = A*cuentas + B."""
        nch = self.chanCount
        self._calA = np.ones(nch); self._calB = np.zeros(nch)
        if not self.calibrate or not self._hw.cal:
            self._calA = None
            return
        for i, g in enumerate(self._gains):
            m, b = self._hw.cal.get(g, (1.0, 0.0))
            R = {0: 10.0, 1: 5.0, 2: 2.0, 3: 1.0, 4: 0.5, 5: 0.2, 6: 0.1}.get(g, 10.0)
            k = 2 * R / 65536                       # volts por cuenta
            self._calA[i] = m
            self._calB[i] = (R * (1 - m) + b) / k   # V=m*(c*k-R)+b  ->  c' = m*c + (R(1-m)+b)/k

    def _apply_cal(self, samples):
        if self._calA is None or not len(samples):
            return samples
        nch = self.chanCount
        pos = (self._total + np.arange(len(samples))) % nch
        c = self._calA[pos] * samples + self._calB[pos]
        return np.clip(np.rint(c), 0, 65535).astype(np.uint16)

    def _stop(self):
        if self._running or self._hw._stream is not None:
            self._hw.stop_stream()
        with self._lock:
            self._running = False
            self._lock.notify_all()
        if self._disk_file is not None:
            self._disk_file.close()
            self._disk_file = None
            # el archivo vale para una sola adquisición: si siguiera configurado, la
            # próxima lo reabriría con 'wb' y pisaría los datos
            self._disk_name = None

    def _on_data(self, raw):
        """Se llama desde el hilo de libusb con los bytes recibidos."""
        with self._lock:
            if not self._running or self._done:
                return
            # sólo se entregan scans completos; el resto queda para el próximo bloque
            raw = self._carry + raw
            scan_bytes = 2 * self.chanCount
            usable = len(raw) - len(raw) % scan_bytes
            self._carry, raw = raw[usable:], raw[:usable]
            samples = np.frombuffer(raw, dtype='<u2')
            if self._wanted is not None:
                samples = samples[:self._wanted - self._total]
            samples = self._apply_cal(samples)
            n = len(samples)
            if self._disk_file is not None:
                self._disk_file.write(samples.tobytes())
            buf = self.dataBuf
            if buf is not None and n:
                size = len(buf)
                pos = self._total % size if self._cyclic else self._total
                if not self._cyclic:
                    m = min(n, size - pos)
                    buf[pos:pos + m] = samples[:m]
                else:
                    buf[(pos + np.arange(n)) % size] = samples
            self._total += n
            self._last_data_time = time.time()
            if self._wanted is not None and self._total >= self._wanted:
                self._done = True
            self._lock.notify_all()
