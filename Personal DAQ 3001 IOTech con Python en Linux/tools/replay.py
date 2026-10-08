"""
replay.py — Reproduce en Linux una secuencia de operaciones extraída de una
captura de Windows (ver pcap_to_ops.py) y compara las respuestas.

Uso:  python replay.py ops/init_plugin.json [ops/single_value.json ...]
"""
import json
import sys
import usb.core
import usb.util

VID, PID = 0x0622, 0x2c01


def open_dev():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("No encuentro 0622:2c01 (¿falta cargar el firmware FX2 con fx2_load.py?)")
    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        if e.errno != 16:
            raise
    usb.util.claim_interface(dev, 0)
    return dev


def replay(dev, path, verbose=False):
    ops = json.load(open(path))['ops']
    mism = 0
    bulk = []
    for o in ops:
        k = o['kind']
        if k == 'ctrl':
            if o['bm'] & 0x80:
                r = bytes(dev.ctrl_transfer(o['bm'], o['req'], o['wValue'], o['wIndex'],
                                            o['wLength'], timeout=2000)).hex()
                ok = r == o['expect']
                if not ok:
                    mism += 1
                if verbose or not ok:
                    print(f"  f{o['frame']:>4} IN  req=0x{o['req']:02x} v=0x{o['wValue']:04x} "
                          f"i={o['wIndex']:>3} -> {r}  (Windows: {o['expect']}){'' if ok else '  <-- distinto'}")
            else:
                dev.ctrl_transfer(o['bm'], o['req'], o['wValue'], o['wIndex'],
                                  bytes.fromhex(o['data']) or None, timeout=2000)
                if verbose:
                    print(f"  f{o['frame']:>4} OUT req=0x{o['req']:02x} v=0x{o['wValue']:04x} i={o['wIndex']:>3}")
        elif k == 'bulk_in':
            if o['n'] == 0:
                continue          # URB cancelado en Windows
            try:
                data = bytes(dev.read(o['ep'], o['n'], timeout=3000))
            except usb.core.USBError as e:
                print(f"  f{o['frame']:>4} BULK IN ep=0x{o['ep']:02x} n={o['n']}: ERROR {e}")
                mism += 1
                continue
            bulk.append(data)
            print(f"  f{o['frame']:>4} BULK IN ep=0x{o['ep']:02x} pedí {o['n']}, llegaron {len(data)}: "
                  f"{data[:16].hex()}  (Windows: {o['head'][:32]})")
        elif k == 'reset_pipe':
            dev.clear_halt(o['ep'])
        # 'abort' sólo cancela URBs pendientes en el host: nada que hacer
    print(f"{path}: {len(ops)} ops, {mism} diferencias")
    return bulk


if __name__ == '__main__':
    verbose = '-v' in sys.argv
    files = [a for a in sys.argv[1:] if a != '-v']
    dev = open_dev()
    for f in files:
        replay(dev, f, verbose)
    usb.util.release_interface(dev, 0)
