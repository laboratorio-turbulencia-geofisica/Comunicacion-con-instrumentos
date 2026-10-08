"""
pcap_to_ops.py — Convierte una captura USBPcap (Windows) en una lista de
operaciones USB replicables (JSON), para reproducirlas con replay.py.

Uso:  python pcap_to_ops.py captura.pcapng salida.json [--addr N]

Toma sólo el dispositivo de la placa (VID 0622) y descarta los requests
estándar (GET_DESCRIPTOR, SET_CONFIGURATION), que libusb ya resuelve.
"""
import json
import subprocess
import sys


def walk(d, out):
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                walk(v, out)
            else:
                out.setdefault(k, v)
    elif isinstance(d, list):
        for x in d:
            walk(x, out)
    return out


def hexdata(s):
    return bytes.fromhex(s.replace(':', '')) if s else b''


def main(path, out_path, addr=None):
    js = json.loads(subprocess.run(
        ['tshark', '-r', path, '-T', 'json', '-x'],
        capture_output=True, check=True, text=True).stdout)
    pkts = []
    for p in js:
        f = walk(p['_source']['layers'], {})
        pkts.append(f)

    if addr is None:   # dispositivo con VID 0622
        for f in pkts:
            if f.get('usb.idVendor') == '0x0622':
                addr = int(f['usb.device_address'])
        if addr is None:
            sys.exit("No encontré el dispositivo 0622 en la captura")

    pending = {}
    ops = []
    for f in pkts:
        if int(f.get('usb.device_address', -1)) != addr:
            continue
        frame = int(f['frame.number'])
        irp = f['usb.irp_id']
        func = int(f['usb.function'], 16)
        ep = int(f['usb.endpoint_address'], 16)
        submit = f['usb.irp_info.direction'] == '0x00'
        if submit:
            pending[irp] = (frame, f)
            continue
        sframe, s = pending.pop(irp, (None, {}))
        status = f.get('usb.usbd_status')
        if func == 0x0008 or func == 0x0017 or 'usb.setup.bRequest' in s:   # control
            bm = int(s.get('usb.bmRequestType', '0'), 16)
            if bm & 0x60 == 0:          # estándar: lo hace libusb
                continue
            op = dict(frame=sframe, kind='ctrl', bm=bm,
                      req=int(s['usb.setup.bRequest']),
                      wValue=int(s['usb.setup.wValue'], 16),
                      wIndex=int(s['usb.setup.wIndex']),
                      wLength=int(s['usb.setup.wLength']))
            if bm & 0x80:
                op['expect'] = f.get('usb.control.Response', '').replace(':', '')
            else:
                op['data'] = (s.get('usb.data_fragment') or '').replace(':', '')
            ops.append(op)
        elif func == 0x0009:            # bulk / interrupt
            n = int(f.get('usb.data_len', 0))
            if ep & 0x80:
                ops.append(dict(frame=frame, kind='bulk_in', ep=ep, n=n,
                                status=status,
                                head=(f.get('usb.capdata') or '').replace(':', '')[:64]))
            else:
                ops.append(dict(frame=sframe, kind='bulk_out', ep=ep,
                                data=(s.get('usb.capdata') or '').replace(':', '')))
        elif func in (0x0002, 0x001e, 0x0030):   # abort / reset / sync_reset pipe
            ops.append(dict(frame=sframe, kind='abort' if func == 2 else 'reset_pipe', ep=ep))
        else:
            ops.append(dict(frame=sframe, kind='unknown', func=func, ep=ep))
    ops.sort(key=lambda o: o['frame'] or 0)
    json.dump(dict(source=path, addr=addr, ops=ops), open(out_path, 'w'), indent=0)
    kinds = {}
    for o in ops:
        kinds[o['kind']] = kinds.get(o['kind'], 0) + 1
    print(f"{path}: dispositivo {addr}, {len(ops)} ops {kinds}")


if __name__ == '__main__':
    a = None
    if '--addr' in sys.argv:
        a = int(sys.argv[sys.argv.index('--addr') + 1])
    main(sys.argv[1], sys.argv[2], a)
