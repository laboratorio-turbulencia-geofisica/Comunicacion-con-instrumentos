# Protocolo USB de la PersonalDaq/3000

Reconstruido a partir de capturas USB (USBPcap) del driver de Windows y del desensamblado de
`pdaq3kld.sys`, `pdaq3k.sys` y `DaqX64.dll`. Todo lo que sigue está implementado en
`PyIOTech/_pdaq3k.py`.

## Arranque

La placa tiene un microcontrolador **Cypress FX2LP** y una FPGA **Xilinx Spartan-3** (`3s400ft256`).

1. Recién enchufada, enumera **sin firmware** como `0622:0470` (bcdDevice `0x2Cxx`).
2. Se carga el firmware del 8051 en RAM con el vendor request `0xA0`: CPU en reset
   (`CPUCS = 0xE600 ← 1`), escritura de los registros Intel HEX, liberación del reset (`← 0`).
3. La placa re-enumera como `0622:2c01` ("IOtech USB2 Device"), con una interfaz con los endpoints
   bulk `0x01`, `0x81`, `0x82` y `0x06`.
4. Se carga el bitstream de la FPGA: `0xB2` (preparar) y bloques de 2048 bytes con `0xB3`
   (el último, de 1448 bytes, va sin relleno). En ese momento se encienden los LEDs.
5. Secuencia de inicialización de Windows y lectura de la tabla de calibración (`0xB8`).

## Vendor requests

| Request | Dirección | Uso |
|---|---|---|
| `0xA0` | OUT | escribir RAM del FX2 (sólo antes del firmware) |
| `0xB0` | IN | versión de firmware |
| `0xB2` / `0xB3` | OUT | preparar FPGA / bloque de bitstream |
| `0xB4` | OUT / IN | escribir / leer registro de la FPGA (`wIndex` = registro, `wValue` = valor) |
| `0xB8` | IN | leer EEPROM de calibración (`wValue` = offset) |
| `0xBB` | OUT | habilitar el streaming bulk (`wValue` = 1, `wIndex` = 2) |

## Registros de la FPGA (nombres de `pdaq3k.sys`)

| Reg. | Nombre | Uso |
|---|---|---|
| 0 | AcqControl / AcqStatus | control y estado de la adquisición |
| 1 | AcqScanListFIFO | lista de canales, entradas de 32 bits escritas como dos palabras |
| 2, 3, 5 | AcqPacerClockDiv Low/Med/High | divisor de 48 bits: f = 48 MHz / (N + 1) |
| 15 | VariableConvRate | sólo para rechazo de línea 50/60 Hz |
| 16, 28–31 | DacControl, DacSetting0–3 | salidas analógicas |
| 88 | DmaControl | habilitación del streaming |
| 89 | TrigControl / TrigStatus | disparo |

## Entrada de la lista de canales (32 bits)

```
bits 29-31  código de settling (5 µs → 1, 10 µs → 2, 1 µs / 20 µs → 0, 1 ms → 3, LCR → 4)
bits 24-27  ganancia (DgainPS3kX1..X100 = 0..6)
bit  22     modo diferencial
bits 4-10   canal
bit  3      DafSSHHold
bit  2      último canal de la lista
bit  1      siempre 1
```

## Datos

Enteros de 16 bits sin signo, little endian, intercalados según la lista de canales, por el endpoint
bulk `0x82`. Para el rango ±V_R: `V = c · 2V_R / 65536 − V_R`. Los canales se convierten en secuencia,
separados ~1,009 µs.

## Calibración de fábrica

La EEPROM empieza con `0x40010001` y guarda, para cada rango x1…x100, tres `float32`:
`(m₊ − 1, m₋ − 1, b)`. Igual que `DaqX64.dll`, se aplica `V = m·V_crudo + b` con
`m = 1 + ((m₊ − 1) + (m₋ − 1))/2` y `b` en volts.
