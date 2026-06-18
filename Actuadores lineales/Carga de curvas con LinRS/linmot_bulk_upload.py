#!/usr/bin/env python3
"""
linmot_bulk_upload.py
=====================
Carga masiva de curvas Position-vs-Time al LinMot E1100-RS
via protocolo LinRS (RS232).

Uso rápido:
    python linmot_bulk_upload.py /dev/ttyUSB0 ./curves/

Uso completo:
    python linmot_bulk_upload.py /dev/ttyUSB0 ./curves/ \
        --baud 19200 --id 0x11 --t-col t --x-col x --no-flash

Dependencias:
    pip install pyserial pandas numpy

Formato CSV esperado:
    - Columna 't': tiempo en segundos, equiespaciado, empezando en 0.
    - Columna 'x': posición en milimetros.
    Ejemplo:
        t,x
        0.000,0.0
        0.001,0.0003
        ...

Notas de configuración del drive:
    - Switch S3.4 = ON  → LinRS activo (RS232 ocupado por LinRS, no disponible
                          para LinMot Talk simultáneamente).
    - Switch S3.1       → RS232 (Off) o RS485 (On).
    - Switch S1         → Baud rate (3=19200, 4=38400, 5=57600, 6=115200).
    - Switch S2         → MACID del drive (0=0x00, 1=0x01, ..., F=0x0F).
                          Si el MACID fue configurado por parámetro puede ser
                          diferente; verificar en LinMot Talk → LinRS →
                          Protocol Config → MACID.

Unidades internas del drive:
    - Posición : 1 unidad = 0.1 µm = 1e-7 m   (int32)
    - Tiempo   : 1 unidad = 10 µs  = 1e-5 s   (uint32, X-Length)

Protocolo LinRS frame:
    01h | MACID | LEN | 02h | SubID | MainID | [data...] | 04h
    LEN = count de bytes desde 02h hasta el último dato, inclusive.
    Checksum desactivado por defecto.

Referencias:
    LinRS Interface User Manual, NTI AG / LinMot, Aug 2014.
    Sección 11 (Curve Configuration Message Group), p.31-37.
"""

import argparse
import glob
import os
import struct
import time

import numpy as np
import pandas as pd
import serial


# =============================================================================
# Driver LinMot E1100-RS
# =============================================================================

class LinMotRS:
    """
    Interfaz de bajo nivel para el LinMot E1100-RS via protocolo LinRS (RS232).

    Solo implementa las funciones necesarias para la gestión de curvas:
    borrar, escribir y persistir en FLASH.
    """

    # ---- Constantes de conversión ------------------------------------------
    POS_UNIT_M  = 1e-7   # 1 unidad interna de posición = 0.1 µm = 1e-7 m
    TIME_UNIT_S = 10e-6  # 1 unidad interna de tiempo   = 10 µs  = 1e-5 s

    INFO_BLOCK_BYTES = 70  # Tamaño fijo del info block (siempre 70 bytes)

    # ---- Main IDs del protocolo LinRS --------------------------------------
    MAIN_RESPONSE  = 0x00
    MAIN_CTRL_WORD = 0x01
    MAIN_MOTION    = 0x02
    MAIN_PARAM     = 0x03
    MAIN_CURVE     = 0x04   # ← lo que usamos aquí
    MAIN_PROG      = 0x06

    # ---- Sub IDs del Curve Configuration Group (Main ID = 0x04) -----------
    CURVE_SAVE_TO_FLASH   = 0x00
    CURVE_DELETE_ALL      = 0x01
    CURVE_DELETE_ONE      = 0x02
    CURVE_ADD             = 0x04   # declara tamaños de info block y data block
    CURVE_WRITE_INFO      = 0x05   # escribe info block, 4 bytes por llamada
    CURVE_WRITE_DATA      = 0x06   # escribe data block, 4 bytes por llamada

    # ---- Sub IDs del Program Handling Group (Main ID = 0x06) --------------
    PROG_STOP_MC          = 0x03
    PROG_START_MC         = 0x04   # con respuesta después de completar (~3s)

    def __init__(self, port: str, baud: int = 19200, drive_id: int = 0x11):
        """
        Parameters
        ----------
        port     : Puerto serial (e.g. '/dev/ttyUSB0', '/dev/cu.usbserial-XXX', 'COM3').
        baud     : Baud rate (debe coincidir con el switch S1 del drive).
        drive_id : MACID del drive (byte; verificar switch S2 o parámetro LinRS).
        """
        self.drive_id = drive_id
        self.ser = serial.Serial(
            port,
            baudrate  = baud,
            bytesize  = serial.EIGHTBITS,
            parity    = serial.PARITY_NONE,
            stopbits  = serial.STOPBITS_ONE,
            timeout   = 2.0,
        )
        time.sleep(0.1)  # esperar que el puerto termine de abrir

    # -------------------------------------------------------------------------
    # Nivel bajo: framing y comunicación
    # -------------------------------------------------------------------------

    def _frame(self, sub_id: int, main_id: int, data: bytes = b'') -> bytes:
        """
        Construye un frame LinRS.

        Estructura: 01h | drive_id | LEN | 02h | sub_id | main_id | data | 04h
        LEN cuenta desde 02h hasta el último byte de data, inclusive.
        """
        inner   = bytes([0x02, sub_id, main_id]) + data
        length  = len(inner)  # LEN = len(02h + SubID + MainID + data)
        return bytes([0x01, self.drive_id, length]) + inner + bytes([0x04])

    def _send(self, frame: bytes, timeout: float = 2.0) -> bytes:
        """
        Envía un frame y lee la respuesta completa.

        La respuesta tiene estructura:
            01h | ID | LEN | 02h | SubID | MainID | ... | 04h
        Se leen exactamente (LEN + 4) bytes.
        """
        self.ser.reset_input_buffer()
        self.ser.timeout = timeout
        self.ser.write(frame)

        # Leer los 3 primeros bytes del header para obtener LEN
        header = self.ser.read(3)
        if len(header) < 3:
            return b''  # timeout o sin respuesta

        length = header[2]                    # LEN
        body   = self.ser.read(length)        # LEN bytes de datos
        end    = self.ser.read(1)             # byte 0x04 de End Telegram

        return header + body + end

    def _comm_state(self, resp: bytes) -> int:
        """
        Extrae el byte Communication State de la respuesta (byte 6).
        0x00 = OK / último chunk.
        0x04 = hay más datos (chunk intermedio).
        -1   = respuesta inválida.
        """
        if len(resp) < 7:
            return -1
        return resp[6]

    def _ok(self, resp: bytes) -> bool:
        """True si la respuesta es válida (tiene al menos el header mínimo)."""
        return len(resp) >= 7 and resp[0] == 0x01 and resp[-1] == 0x04

    # -------------------------------------------------------------------------
    # Control del MC Software
    # -------------------------------------------------------------------------

    def stop_mc(self) -> bytes:
        """
        Para el MC-SW y Application SW del drive.
        Necesario antes de guardar curvas en FLASH.
        """
        return self._send(self._frame(self.PROG_STOP_MC, self.MAIN_PROG), timeout=10.0)
    def start_mc(self) -> bytes:
        """
        Reinicia el MC-SW y Application SW.
        Espera la respuesta de confirmación (~3 s).
        """
        return self._send(self._frame(self.PROG_START_MC, self.MAIN_PROG), timeout=6.0)

    # -------------------------------------------------------------------------
    # Gestión de curvas
    # -------------------------------------------------------------------------

    def delete_all_curves(self) -> bytes:
        """Borra todas las curvas de la RAM del drive."""
        return self._send(self._frame(self.CURVE_DELETE_ALL, self.MAIN_CURVE))

    def delete_curve(self, curve_id: int) -> bytes:
        """Borra la curva con el ID dado de la RAM."""
        return self._send(
            self._frame(self.CURVE_DELETE_ONE, self.MAIN_CURVE,
                        struct.pack('<H', curve_id))
        )

    def save_curves_to_flash(self) -> bytes:
        """
        Persiste las curvas de RAM en FLASH.
        El MC-SW debe estar parado antes de llamar esto.
        """
        return self._send(
            self._frame(self.CURVE_SAVE_TO_FLASH, self.MAIN_CURVE),
            timeout=15.0
        )

    def write_curve(self, curve_id: int, name: str,
                    t_s: np.ndarray, x_m: np.ndarray) -> None:
        """
        Escribe una curva Position-vs-Time al drive vía LinRS.

        Parameters
        ----------
        curve_id : int
            ID único de la curva (1..99).
        name : str
            Nombre descriptivo de la curva (máx 22 caracteres ASCII).
        t_s : np.ndarray
            Tiempos equiespaciados en segundos. Debe comenzar en t=0 o
            la duración es t[-1]-t[0].
        x_m : np.ndarray
            Posiciones en metros. Mismo largo que t_s.
        """
        n              = len(x_m)
        duration_s     = float(t_s[-1]) - float(t_s[0])
        x_len_10us     = int(round(duration_s / self.TIME_UNIT_S))
        data_block_size = n * 4  # int32 × n setpoints

        # ---- Construir Info Block (70 bytes) --------------------------------
        # Layout (little-endian, offset en bytes):
        #   0- 1  word  : INFO_BLOCK_BYTES (= 70 = 0x46)
        #   2- 3  word  : Object Type (0x0003 = Position vs Time)
        #   4- 5  word  : N setpoints
        #   6- 7  word  : Data Type Size (0x0004 = int32)
        #   8-29  bytes : Nombre (22 bytes, nul-padded)
        #  30-31  word  : Curve ID
        #  32-35  dword : X-Length en unidades de 10 µs
        #  36-37  word  : XDimUUID (0x001A = tiempo)
        #  38-69  bytes : zeros (campos adicionales no requeridos para tablas de puntos)

        info     = bytearray(self.INFO_BLOCK_BYTES)
        name_enc = name.encode('ascii')[:22].ljust(22, b'\x00')

        struct.pack_into('<H', info,  0, self.INFO_BLOCK_BYTES)   # 0x0046
        struct.pack_into('<H', info,  2, 0x0003)                   # Pos vs Time
        struct.pack_into('<H', info,  4, n)                         # N setpoints
        struct.pack_into('<H', info,  6, 0x0004)                   # int32
        info[8:30] = name_enc                                       # nombre
        struct.pack_into('<H', info, 30, curve_id)                 # Curve ID
        struct.pack_into('<I', info, 32, x_len_10us)               # X-Length
        struct.pack_into('<H', info, 36, 0x001A)                   # XDimUUID
        struct.pack_into('<H', info, 38, 0x0005)                   # YDimUUID 
        # bytes 38-69 quedan en cero (bytearray inicializado en 0)

        # ---- Construir Data Block (N × int32) ------------------------------
        # Unidad de posición: 1 unit = 0.1 µm = 1e-7 m → multiplicar por 1e7
        positions  = np.round(np.asarray(x_m, dtype=float) / self.POS_UNIT_M).astype(np.int32) # np.asarray(x_m, dtype=float) #  
        data_block = positions.tobytes()
        # print("\n", positions) 
        
        cid = struct.pack('<H', curve_id)  # curve ID para encabezado de cada mensaje

        # ---- Paso 1: declarar tamaños (Sub ID 0x04) ------------------------
        # Tx: 01 ID 09 02 04 04 [curveID lo hi] [infoSize lo hi] [dataSize lo hi] 04
        size_payload = cid + struct.pack('<HH', self.INFO_BLOCK_BYTES, data_block_size)
        resp = self._send(self._frame(self.CURVE_ADD, self.MAIN_CURVE, size_payload))
        if not self._ok(resp):
            raise RuntimeError(f"Curva {curve_id} '{name}': sin respuesta al declarar tamaños")

        # ---- Paso 2: enviar info block de a 4 bytes (Sub ID 0x05) ----------
        # Son ceil(70/4) = 18 llamadas; el último chunk puede tener < 4 bytes (se rellena con 00)
        # El drive indica "último chunk" con Communi  cation State = 0x00 en la respuesta.
        for i in range(0, self.INFO_BLOCK_BYTES, 4):
            chunk = bytes(info[i:i+4]).ljust(4, b'\x00')
            resp  = self._send(self._frame(self.CURVE_WRITE_INFO, self.MAIN_CURVE, cid + chunk))
            if not self._ok(resp):
                raise RuntimeError(
                    f"Curva {curve_id} '{name}': error en info block chunk {i//4+1}/18"
                )

        # ---- Paso 3: enviar data block de a 4 bytes (Sub ID 0x06) ----------
        # Cada llamada envía exactamente 1 setpoint (int32 = 4 bytes).
        for i in range(0, data_block_size, 4):
            chunk = data_block[i:i+4]
            resp  = self._send(self._frame(self.CURVE_WRITE_DATA, self.MAIN_CURVE, cid + chunk))
            if not self._ok(resp):
                raise RuntimeError(
                    f"Curva {curve_id} '{name}': error en data block setpoint {i//4+1}/{n}"
                )

    def close(self):
        """Cierra el puerto serial."""
        if self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# =============================================================================
# Carga masiva
# =============================================================================

def bulk_upload(
    port:     str,
    csv_dir:  str,
    baud:     int  = 19200,
    drive_id: int  = 0x11,
    t_col:    str  = 't',
    x_col:    str  = 'x',
    to_flash: bool = True, 
    delete_all_curves: bool = True,
):
    """
    Carga masiva de curvas CSV al LinMot E1100-RS.

    Parameters
    ----------
    port     : Puerto serial ('/dev/ttyUSB0', '/dev/cu.usbserial-XXX', 'COM3', …).
    csv_dir  : Directorio que contiene los archivos .csv.
    baud     : Baud rate (debe coincidir con S1 del drive; default 19200 = S1=3).
    drive_id : MACID del drive en hex (default 0x11; ver S2 o LinMot Talk).
    t_col    : Nombre de la columna de tiempo [s] en los CSVs.
    x_col    : Nombre de la columna de posición [m] en los CSVs.
    to_flash : True → para el MC SW, guarda en FLASH y lo reinicia.
               False → las curvas quedan solo en RAM (se pierden al apagar).
    """
    files = sorted(glob.glob(os.path.join(csv_dir, '*.csv')))
    if not files:
        raise FileNotFoundError(f"No se encontraron archivos .csv en '{csv_dir}'")
    if len(files) > 99:
        raise ValueError(f"Se encontraron {len(files)} archivos pero el drive soporta máximo 99 curvas.")

    print(f"{'='*60}")
    print(f"  LinMot E1100-RS — Carga masiva de curvas")
    print(f"  Puerto:   {port}   Baud: {baud}   Drive ID: 0x{drive_id:02X}")
    print(f"  Curvas:   {len(files)} archivos CSV en '{csv_dir}'")
    print(f"  Destino:  {'FLASH (permanente)' if to_flash else 'RAM (volátil)'}")
    print(f"{'='*60}")

    with LinMotRS(port, baud=baud, drive_id=drive_id) as lm:

        if to_flash:
            print("\n[1/3] Parando MC SW ...")
            resp = lm.stop_mc()
            if not lm._ok(resp):
                raise RuntimeError("El drive no respondió al comando Stop MC SW. "
                                   "Verificar conexión, MACID y baud rate.") 
            time.sleep(0.3)
            print("      MC SW parado.") 

        if delete_all_curves: 
            print("\n[1.5] Borrando todas las curvas") 
            lm.delete_all_curves() 

        print(f"\n[{'2' if to_flash else '1'}/{'3' if to_flash else '2'}] "
              f"Escribiendo {len(files)} curvas ...\n")
        
        errors = []
        for i, fpath in enumerate(files):
            curve_id = i + 1
            stem     = os.path.splitext(os.path.basename(fpath))[0]

            try:
                df = pd.read_csv(fpath)

                if t_col not in df.columns or x_col not in df.columns:
                    raise KeyError(
                        f"Columnas '{t_col}' y/o '{x_col}' no encontradas. "
                        f"Columnas disponibles: {list(df.columns)}"
                    )

                t = df[t_col].to_numpy(dtype=float)
                x = df[x_col].to_numpy(dtype=float) * 1e-3 # Pasa de milímetros a metros. 

                # Verificar equiespaciado; si no, interpolar
                dt = np.diff(t)
                if not np.allclose(dt, dt[0], rtol=5e-3):
                    print(f"  ⚠  '{stem}': tiempos no equiespaciados → interpolando ...")
                    t_eq = np.linspace(t[0], t[-1], len(t))
                    x    = np.interp(t_eq, t, x)
                    t    = t_eq

                print(f"  [{curve_id:02d}/{len(files):02d}]  ID={curve_id:2d}  "
                      f"'{stem[:22]}'  "
                      f"N={len(t):4d} pts  "
                      f"T={t[-1]-t[0]:.4f} s  "
                      f"x=[{x.min()*1e3:+.3f}, {x.max()*1e3:+.3f}] mm",
                      end='', flush=True)
                # print(x) 
                lm.write_curve(curve_id, stem, t, x)
                print("  ✓")

            except Exception as e:
                print(f"  ✗  ERROR: {e}")
                errors.append((curve_id, stem, str(e)))

        if to_flash:
            print(f"\n[3/3] Guardando en FLASH ...")
            resp = lm.save_curves_to_flash()
            if lm._ok(resp):
                print("      Guardado en FLASH OK.")
            else:
                print("      ⚠  Sin respuesta de Save-to-FLASH (puede haber timeout).")

            print("      Reiniciando MC SW (esperar ~3 s) ...")
            resp = lm.start_mc()
            if lm._ok(resp):
                print("      MC SW activo.")
            else:
                print("      ⚠  Sin respuesta de Start MC SW — reiniciar manualmente.")

    print()
    if errors:
        print(f"✗  Completado con {len(errors)} error(es):")
        for cid, name, msg in errors:
            print(f"     ID={cid} '{name}': {msg}")
    else:
        print(f"✓  {len(files)} curvas cargadas correctamente.")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Carga masiva de curvas CSV al LinMot E1100-RS via LinRS.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Linux/macOS, baud 19200, MACID 0x11 (default)
  python linmot_bulk_upload.py /dev/ttyUSB0 ./curves/

  # Windows, baud 38400, MACID 0x00 (S2=0)
  python linmot_bulk_upload.py COM3 ./curves/ --baud 38400 --id 0x00

  # Solo RAM (no guardar en FLASH)
  python linmot_bulk_upload.py /dev/ttyUSB0 ./curves/ --no-flash

  # Columnas personalizadas en CSV: tiempo [s] y posicion [mm → convertir a m vía preproceso]
  python linmot_bulk_upload.py /dev/ttyUSB0 ./curves/ --t-col tiempo --x-col pos

Baud rates (switch S1 del drive):
  S1=2 → 9600   S1=3 → 19200   S1=4 → 38400
  S1=5 → 57600  S1=6 → 115200

MACID (switch S2 del drive):
  S2=0 → 0x00, S2=1 → 0x01, ..., S2=F → 0x0F
  Si fue configurado por parámetro: ver LinMot Talk →
  LinRS → Protocol Config → MACID → MACID Parameter Value.
        """
    )

    parser.add_argument(
        'port',
        help="Puerto serial (e.g. /dev/ttyUSB0  o  COM3)"
    )
    parser.add_argument(
        'csv_dir',
        help="Directorio con los archivos .csv"
    )
    parser.add_argument(
        '--baud', type=int, default=19200,
        help="Baud rate (default: 19200 = S1=3)"
    )
    parser.add_argument(
        '--id', dest='drive_id',
        type=lambda x: int(x, 0), default=0x11,
        help="MACID del drive en hex (default: 0x11)"
    )
    parser.add_argument(
        '--t-col', default='t',
        help="Columna de tiempo [s] en los CSVs (default: 't')"
    )
    parser.add_argument(
        '--x-col', default='x',
        help="Columna de posición [m] en los CSVs (default: 'x')"
    )
    parser.add_argument(
        '--no-flash', action='store_true',
        help="No guardar en FLASH — curvas solo en RAM (volátiles)"
    )
    parser.add_argument(
        '--delete-all-curves', action='store_true',
        help="Borrar todas las curvas presentes en la memoria del drive."
    )

    args = parser.parse_args()

    bulk_upload(
        port     = args.port,
        csv_dir  = args.csv_dir,
        baud     = args.baud,
        drive_id = args.drive_id,
        t_col    = args.t_col,
        x_col    = args.x_col,
        to_flash = not args.no_flash,
        delete_all_curves = args.delete_all_curves, 
    )


if __name__ == '__main__':
    main()
