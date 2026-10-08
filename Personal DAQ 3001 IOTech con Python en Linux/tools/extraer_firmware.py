#!/usr/bin/env python3
"""
extraer_firmware.py — Extrae el firmware de la PersonalDaq/3000 de los drivers de Windows.

La placa necesita dos archivos que son propiedad de IOtech/Measurement Computing y por eso
NO se distribuyen en este repositorio:

  * pdaq3k_fx2.ihx     firmware del microcontrolador Cypress FX2LP  (sale de pdaq3kld.sys)
  * pdaq3001_fpga.bin  bitstream de la FPGA Xilinx Spartan-3          (sale de pdaq3k.sys)

Ambos .sys se instalan con DAQView / DaqX en Windows (por ejemplo en
C:\\Windows\\System32\\drivers\\ o en la carpeta DaqX\\Drivers\\USB_x64).

Uso:
    python tools/extraer_firmware.py ruta/a/pdaq3kld.sys ruta/a/pdaq3k.sys

Los archivos se escriben en PyIOTech/ y se verifican contra los hashes de la versión probada.
"""
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, '..', 'PyIOTech')
SHA_IHX = '75696388a7a004111a27c190053ad0b22efd416f6d6a70c54ef274efa0a6bf2e'
SHA_BIN = 'b0112fb2e8561e8de5e2adbe67d115ced92d4b59258990fe48eb9536fe026bb4'


def secciones_pe(d):
    """[(rva, offset_en_archivo, tamaño)] de las secciones de un ejecutable PE."""
    pe = struct.unpack_from('<I', d, 0x3C)[0]
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    opt = struct.unpack_from('<H', d, pe + 20)[0]
    base = pe + 24 + opt
    out = []
    for i in range(nsec):
        vsize, rva, rawsize, rawptr = struct.unpack_from('<IIII', d, base + 40*i + 8)
        out.append((rva, rawptr, max(vsize, rawsize)))
    return out


def rva_a_offset(secs, rva):
    for va, off, size in secs:
        if va <= rva < va + size:
            return off + rva - va
    return None


def leer_registros(d, off):
    """Tabla de registros Intel HEX de los ejemplos de Cypress: {len u8, pad, addr u16, type u8, data[16], pad}."""
    recs = []
    while off + 22 <= len(d):
        n, addr, typ = d[off], struct.unpack_from('<H', d, off + 2)[0], d[off + 4]
        if typ == 1:
            return recs
        if typ != 0 or not 1 <= n <= 16:
            return None
        recs.append((addr, d[off + 5:off + 5 + n]))
        off += 22
    return None


def extraer_fx2(path):
    d = open(path, 'rb').read()
    secs = secciones_pe(d)
    # Tabla de selección de firmware: entradas de 0x28 bytes
    # {VID, PID, bcdDevice, máscaras...; puntero a la tabla Intel HEX en +0x10}. Se busca la entrada
    # VID 0622 / PID 0470 / bcdDevice 0x2Cxx (PersonalDaq/3000).
    clave = struct.pack('<HHHH', 0x0622, 0x0470, 0xFFFF, 0x2C00)
    i = d.find(clave)
    if i < 0:
        sys.exit('No encontré la entrada de la PersonalDaq/3000 en ' + path)
    ptr = struct.unpack_from('<Q', d, i + 0x10)[0]
    off = rva_a_offset(secs, ptr) or rva_a_offset(secs, ptr - struct.unpack_from('<Q', d, struct.unpack_from('<I', d, 0x3C)[0] + 48)[0])
    recs = leer_registros(d, off) if off is not None else None
    if not recs:
        sys.exit('No pude leer la tabla de firmware del FX2 en ' + path)
    lineas = []
    for addr, data in recs:
        r = bytes([len(data), addr >> 8, addr & 255, 0]) + data
        lineas.append(':' + r.hex().upper() + '%02X' % ((-sum(r)) & 255))
    lineas.append(':00000001FF')
    return ('\n'.join(lineas) + '\n').encode()


def extraer_fpga(path):
    d = open(path, 'rb').read()
    magic = bytes.fromhex('00090ff00ff00ff00ff00000')
    i = d.find(magic + b'\x01a')
    if i < 0:
        sys.exit('No encontré el bitstream de la FPGA en ' + path)
    j = i + len(magic) + 1                         # campos a, b, c, d, e del encabezado .bit
    while True:
        campo = d[j:j + 1]; j += 1
        if campo == b'e':
            n = struct.unpack_from('>I', d, j)[0]
            return d[j + 4:j + 4 + n]
        n = struct.unpack_from('>H', d, j)[0]; j += 2 + n


def guardar(nombre, datos, sha):
    ruta = os.path.join(DEST, nombre)
    open(ruta, 'wb').write(datos)
    h = hashlib.sha256(datos).hexdigest()
    estado = 'OK (coincide con la versión probada)' if h == sha else 'ATENCIÓN: hash distinto a la versión probada'
    print(f'{ruta}: {len(datos)} bytes, sha256 {h[:16]}…  {estado}')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    guardar('pdaq3k_fx2.ihx', extraer_fx2(sys.argv[1]), SHA_IHX)
    guardar('pdaq3001_fpga.bin', extraer_fpga(sys.argv[2]), SHA_BIN)
