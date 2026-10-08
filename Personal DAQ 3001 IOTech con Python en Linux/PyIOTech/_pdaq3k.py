"""
_pdaq3k.py — Acceso USB de bajo nivel a la IOtech PersonalDaq/3000 (3001) en Linux.

Reemplaza a pdaq3kld.sys + pdaq3k.sys. Todo lo de acá sale de:
  * capturas USBPcap del driver de Windows (Pruebas definitivas/*.pcapng)
  * desensamblado de pdaq3k.sys (mapa de registros, formato de la scan list)

Arranque de la placa:
  1. Al enchufarla es un Cypress FX2LP sin firmware (0622:0470). Se le carga el
     firmware del 8051 (pdaq3k_fx2.ihx, extraído de pdaq3kld.sys) y re-enumera
     como 0622:2c01.
  2. Se carga el bitstream del FPGA (pdaq3001_fpga.bin) con 0xB2 + 0xB3.

Protocolo (vendor requests):
  0xB0 IN   versión de firmware
  0xB2 OUT  preparar FPGA        0xB3 OUT  bloque de bitstream
  0xB4 OUT  escribir registro (wIndex=registro, wValue=valor)
  0xB4 IN   leer registro (2 bytes LE)
  0xB8 IN   leer EEPROM de calibración (wValue=offset)
  0xBB OUT  habilitar el streaming bulk (wValue=1, wIndex=2)
Los datos del ADC llegan por el endpoint bulk 0x82 como uint16 LE, intercalados
según la scan list. El pacer corre a 48 MHz / (divisor + 1).
"""
import os
import struct
import threading
import time

import usb1

VID = 0x0622
PID_LOADER = 0x0470      # FX2 sin firmware
PID_RUN = 0x2C01         # con firmware FX2 cargado

EP_ADC = 0x82
MASTER_CLOCK = 48_000_000

# Registros del FPGA (nombres de pdaq3k.sys)
R_ACQ_CONTROL = 0        # AcqControl/AcqStatus
R_SCANLIST = 1           # AcqScanListFIFO
R_PACER_LOW = 2          # AcqPacerClockDivLow
R_PACER_MED = 3          # AcqPacerClockDivMed
R_PACER_HIGH = 5         # AcqPacerClockDivHigh
R_CONV_RATE = 15         # VariableConvRate (sólo para rechazo de línea 50/60 Hz)
R_DAC_CONTROL = 16       # DacControl/DacStatus
R_DAC_SETTING0 = 28      # DacSetting0..3 = 28..31
R_DMA_CONTROL = 88       # DmaControl
R_TRIG_CONTROL = 89      # TrigControl/TrigStatus
R_DIGITAL_MARK = 93      # DigitalMark

_HERE = os.path.dirname(os.path.abspath(__file__))
FX2_FIRMWARE = os.path.join(_HERE, 'pdaq3k_fx2.ihx')
FPGA_BITSTREAM = os.path.join(_HERE, 'pdaq3001_fpga.bin')

# Valores de 0 V de los DAC que escribe Windows al abrir (placa 374683)
DAC_ZERO = (0x7ffb, 0x7ffe, 0x7ffd, 0x7fff)

# Código de settling de la scan list según los flags DafSettle* (adcSetScanSeq3K)
_SETTLE_CODE = {0x0000000: 1,   # DafSettle5us (default)
                0x0800000: 2,   # DafSettle10us
                0x1000000: 0,   # DafSettle20us
                0x1800000: 0,   # DafSettle1us
                0x2000000: 3,   # DafSettle1ms
                0x2800000: 4,   # DafSettle50HzLCR
                0x3000000: 4}   # DafSettle60HzLCR


class PDaqUSBError(Exception):
    pass


GAIN_RANGE = {0: 10.0, 1: 5.0, 2: 2.0, 3: 1.0, 4: 0.5, 5: 0.2, 6: 0.1}   # DgainPS3kX1..X100


def parse_cal_table(cal):
    """Coeficientes de fábrica de la EEPROM: {código de ganancia: (m, b)}.

    Formato (verificado con DaqX64.dll y con barridos de CC del AFG3021B):
    encabezado 0x40010001 y luego, por cada rango x1..x100, tres float32
    (m+ - 1, m- - 1, b[V]). Igual que la DLL, m = 1 + (m+ + m-)/2 y
    V_corregido = m * V_crudo + b.
    """
    if len(cal) < 88 or cal[:4] != bytes.fromhex('40010001'):
        return {}
    f = struct.unpack('<21f', cal[4:88])
    out = {}
    for g in range(7):
        mp, mn, b = f[3 * g:3 * g + 3]
        if abs(mp) > 0.1 or abs(mn) > 0.1 or abs(b) > 0.1:      # tabla corrupta
            return {}
        out[g] = (1.0 + (mp + mn) / 2.0, b)
    return out


def scan_entry(chan, gain, flags, last):
    """Entrada de 32 bits de la scan list para un canal analógico local.

    Reproduce adcSetScanSeq3K/GetScanSeq3KInfo de pdaq3k.sys:
      bits 29-31 settling, 24-27 ganancia, 22 diferencial, 4-10 canal,
      bit 3 SSH hold, bit 2 último canal, bit 1 siempre 1.
    """
    settle = _SETTLE_CODE.get(flags & 0x3800000, 0)
    e = (settle << 29) | ((gain & 0xF) << 24) | ((chan & 0x7F) << 4) | 0x2
    if flags & 0x08:            # DafDifferential
        e |= 0x400000
    if flags & 0x10:            # DafSSHHold
        e |= 0x8
    if flags & 0x8000000:
        e |= 0x800
    if last:
        e |= 0x4
    return e


def _read_ihx(path):
    recs = []
    for line in open(path):
        line = line.strip()
        if not line.startswith(':'):
            continue
        raw = bytes.fromhex(line[1:])
        if sum(raw) & 0xFF:
            raise PDaqUSBError(f"checksum inválido en {path}: {line}")
        n, addr, rtype = raw[0], (raw[1] << 8) | raw[2], raw[3]
        if rtype == 1:
            break
        if rtype == 0:
            recs.append((addr, raw[4:4 + n]))
    return recs


class PDaq3000:
    """Conexión USB con la placa: firmware, registros y streaming del ADC."""

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.ctx = usb1.USBContext()
        self.ctx.open()
        self._ensure_fx2_firmware()
        self.handle = self._open_run_device()
        if not self._fpga_alive():
            self._log("Cargando bitstream del FPGA...")
            self._load_fpga()
            if not self._fpga_alive():
                raise PDaqUSBError("El FPGA no respondió después de cargar el bitstream")
        self.version = self._ctrl_in(0xB0, 0, 0, 2)
        self.cal_table = b''
        self.cal = {}
        self._stream = None

    # ── utilidades ─────────────────────────────────────────────────────────
    def _log(self, msg):
        if self.verbose:
            print(f"[PDaq3000] {msg}")

    def _ctrl_out(self, req, value, index, data=b''):
        self.handle.controlWrite(0x40, req, value, index, data, timeout=2000)

    def _ctrl_in(self, req, value, index, length):
        return bytes(self.handle.controlRead(0xC0, req, value, index, length, timeout=2000))

    def w(self, reg, value):
        self._ctrl_out(0xB4, value & 0xFFFF, reg)

    def r(self, reg):
        return struct.unpack('<H', self._ctrl_in(0xB4, 0, reg, 2))[0]

    # ── arranque ──────────────────────────────────────────────────────────
    def _ensure_fx2_firmware(self):
        dev = self.ctx.getByVendorIDAndProductID(VID, PID_LOADER)
        if dev is None:
            return
        self._log("Placa sin firmware (0622:0470): cargando firmware FX2...")
        h = dev.open()
        try:
            recs = _read_ihx(FX2_FIRMWARE)
            h.controlWrite(0x40, 0xA0, 0xE600, 0, b'\x01', timeout=1000)   # 8051 en reset
            for addr, data in recs:
                h.controlWrite(0x40, 0xA0, addr, 0, data, timeout=1000)
            h.controlWrite(0x40, 0xA0, 0xE600, 0, b'\x00', timeout=1000)   # arrancar
        finally:
            try:
                h.close()
            except usb1.USBError:
                pass
        # esperar la re-enumeración
        for _ in range(100):
            time.sleep(0.1)
            if self.ctx.getByVendorIDAndProductID(VID, PID_RUN) is not None:
                time.sleep(0.3)
                return
        raise PDaqUSBError("La placa no re-enumeró como 0622:2c01 después de cargar el firmware FX2")

    def _open_run_device(self):
        h = None
        for _ in range(20):
            try:
                h = self.ctx.openByVendorIDAndProductID(VID, PID_RUN)
            except usb1.USBErrorAccess:
                raise PDaqUSBError(
                    "Sin permiso sobre 0622:2c01. Instalar la regla udev:\n"
                    "  sudo cp 99-pdaq3000.rules /etc/udev/rules.d/ && "
                    "sudo udevadm control --reload-rules && sudo udevadm trigger")
            if h is not None:
                break
            time.sleep(0.2)
        if h is None:
            raise PDaqUSBError("No se encontró la PersonalDaq/3000 (0622:0470 ni 0622:2c01). ¿Está conectada?")
        try:
            if h.kernelDriverActive(0):
                h.detachKernelDriver(0)
        except (usb1.USBError, NotImplementedError):
            pass
        h.claimInterface(0)
        return h

    def _fpga_alive(self):
        try:
            for v in (0x5A, 0xA5):
                self.w(R_DIGITAL_MARK, v)
                if self.r(R_DIGITAL_MARK) != v:
                    return False
            return True
        except usb1.USBError:
            return False

    def _load_fpga(self):
        bit = open(FPGA_BITSTREAM, 'rb').read()
        self._ctrl_out(0xB2, 0, 0)
        for off in range(0, len(bit), 2048):
            self._ctrl_out(0xB3, 0, 0, bit[off:off + 2048])   # el último va sin relleno
        time.sleep(0.1)

    def initialize(self):
        """Secuencia de apertura de Windows (daqOpen)."""
        for v in (0xFE, 0x02, 0xFB, 0x08, 0xEF, 0x20, 0xBF, 0x80):
            self.w(R_DIGITAL_MARK, v)
            self.r(R_DIGITAL_MARK)
        self.w(7, 0x0100)
        self.r(7)
        self.w(R_DAC_CONTROL, 0x0010)
        self.w(R_DMA_CONTROL, 0x0000)
        for _ in range(5):
            self.w(R_DAC_CONTROL, 0x0000)
        self.w(R_DAC_CONTROL, 0x0004)
        self._reset_acq()
        self.cal_table = (self._ctrl_in(0xB8, 0x0000, 0, 320) +
                          self._ctrl_in(0xB8, 0x0140, 0, 320) +
                          self._ctrl_in(0xB8, 0x0280, 0, 168))
        self.cal = parse_cal_table(self.cal_table)
        if not self.cal:
            self._log("Aviso: tabla de calibración inválida; los datos van sin corregir")
        # Windows hace una adquisición corta de calentamiento (canal 0, 1 kHz) y la descarta
        self.load_scan_list([scan_entry(0, 0, 0, True)])
        self._start_hw(47999)
        self._stop_hw()
        for k, val in enumerate(DAC_ZERO):
            self.dac_write(k, val)

    def close(self):
        try:
            self.stop_stream()
            self.w(R_DAC_CONTROL, 0x0010)
            self.w(R_DMA_CONTROL, 0x0000)
            for v in (0x20, 0x30, 0x40, 0x50, 0x60):
                self.w(R_DAC_CONTROL, v)
            self._reset_acq()
        except usb1.USBError:
            pass
        try:
            self.handle.releaseInterface(0)
            self.handle.close()
        except usb1.USBError:
            pass
        self.ctx.close()

    # ── DAC estático ──────────────────────────────────────────────────────
    def dac_write(self, chan, counts):
        sel = 0x20 + 0x10 * chan
        self.w(R_DAC_CONTROL, sel)
        self.w(R_DAC_CONTROL, sel)
        self.w(R_DAC_SETTING0 + chan, counts)
        self.r(R_DAC_CONTROL)

    # ── adquisición ───────────────────────────────────────────────────────
    def _reset_acq(self):
        self.w(R_TRIG_CONTROL, 0x0000)
        self.w(R_TRIG_CONTROL, 0x0010)
        self.w(R_ACQ_CONTROL, 0x0030)
        self.w(R_ACQ_CONTROL, 0x0010)
        self.w(R_ACQ_CONTROL, 0x0003)
        self.w(R_DMA_CONTROL, 0x0010)

    def load_scan_list(self, entries):
        for _ in range(2):              # Windows la escribe dos veces
            self.w(R_ACQ_CONTROL, 0x0004)
            for e in entries:
                self.w(R_SCANLIST, e & 0xFFFF)
                self.w(R_SCANLIST, e >> 16)
            self.w(R_ACQ_CONTROL, 0x0054)
            self.w(R_ACQ_CONTROL, 0x0040)
            self.w(R_CONV_RATE, 0x0000)

    @staticmethod
    def pacer_divisor(freq):
        return max(1, int(round(MASTER_CLOCK / float(freq)))) - 1

    def _start_hw(self, divisor, before_dma=None):
        self._reset_acq()
        self._drain()
        self.r(R_ACQ_CONTROL)
        self.w(R_ACQ_CONTROL, 0x0060)
        self.w(R_PACER_LOW, divisor & 0xFFFF)
        self.w(R_PACER_MED, (divisor >> 16) & 0xFFFF)
        self.w(R_PACER_HIGH, (divisor >> 32) & 0xFFFF)
        self.w(R_ACQ_CONTROL, 0x0003)
        self._ctrl_out(0xBB, 0x0001, 0x0002)
        if before_dma:
            before_dma()                 # Windows encola las lecturas bulk acá
        self.w(R_DMA_CONTROL, 0x0011)
        self.w(R_ACQ_CONTROL, 0x0071)
        self.w(R_ACQ_CONTROL, 0x0011)
        self.r(R_ACQ_CONTROL)
        self.w(R_ACQ_CONTROL, 0x0031)

    def _stop_hw(self):
        self.w(R_TRIG_CONTROL, 0x0000)
        self.w(R_TRIG_CONTROL, 0x0010)
        self._reset_acq()

    def _drain(self, max_bytes=1 << 22):
        """Descarta lo que haya quedado en el FIFO del FX2."""
        total = 0
        while total < max_bytes:
            try:
                data = self.handle.bulkRead(EP_ADC, 16384, timeout=30)
            except usb1.USBErrorTimeout:
                break
            except usb1.USBError:
                break
            if not data:
                break
            total += len(data)
        return total

    # ── streaming asíncrono ──────────────────────────────────────────────
    def start_stream(self, divisor, on_data, bytes_per_sec):
        """Arranca el pacer y entrega los bytes recibidos a on_data(bytes)."""
        self.stop_stream()
        # transferencias de ~20 ms de datos, múltiplos de 512, entre 512 B y 64 KB
        size = int(bytes_per_sec * 0.02) // 512 * 512
        size = max(512, min(65536, size))
        nxfer = 32
        st = _Stream(self.ctx, self.handle, on_data, size, nxfer)
        self._stream = st
        self._start_hw(divisor, before_dma=st.submit_all)
        st.start_thread()

    def stop_stream(self):
        st = self._stream
        if st is None:
            return
        self._stream = None
        try:
            self._stop_hw()
        except usb1.USBError:
            pass
        st.stop()
        self._drain()

    @property
    def stream_error(self):
        return self._stream.error if self._stream else None


class _Stream:
    def __init__(self, ctx, handle, on_data, size, nxfer):
        self.ctx = ctx
        self.on_data = on_data
        self.running = True
        self.error = None
        self.pending = 0
        self.lock = threading.Lock()
        self.transfers = []
        for _ in range(nxfer):
            t = handle.getTransfer()
            t.setBulk(EP_ADC, size, callback=self._cb, timeout=0)
            self.transfers.append(t)
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def submit_all(self):
        for t in self.transfers:
            t.submit()
            with self.lock:
                self.pending += 1

    def start_thread(self):
        self.thread.start()

    def _cb(self, t):
        status = t.getStatus()
        if status in (usb1.TRANSFER_COMPLETED, usb1.TRANSFER_TIMED_OUT):
            n = t.getActualLength()
            if n and self.running:
                try:
                    self.on_data(bytes(t.getBuffer()[:n]))
                except Exception as e:          # no matar el hilo de eventos
                    self.error = e
            if self.running:
                try:
                    t.submit()
                    return
                except usb1.USBError as e:
                    self.error = e
        elif status != usb1.TRANSFER_CANCELLED and self.running:
            self.error = PDaqUSBError(f"transferencia bulk terminó con estado {status}")
        with self.lock:
            self.pending -= 1

    def _loop(self):
        while True:
            with self.lock:
                if not self.running and self.pending <= 0:
                    break
            try:
                self.ctx.handleEventsTimeout(0.05)
            except usb1.USBErrorInterrupted:
                pass

    def stop(self):
        self.running = False
        for t in self.transfers:
            try:
                t.cancel()
            except usb1.USBError:
                pass
        self.thread.join(timeout=3)
        for t in self.transfers:
            try:
                t.close()
            except Exception:
                pass
