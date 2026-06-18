# Carga de curvas al drive E1100-RS (LinRS + Python)

Este documento describe el procedimiento para la carga de curvas al drive **E1100-RS** utilizando **linRS mediante Python**.

En este caso se utilizó **Python 3.8** en un entorno de Windows 7.  
Los paquetes mínimos necesarios son:

- pandas  
- numpy  
- pyserial  

---

## Procedimiento

Para poder correr el script y cargar las curvas hay que seguir los siguientes pasos:

---

### 1) Preparación del sistema

1. Cerrar LinMot Talk si está abierto, para liberar la comunicación con el puerto `COM3`.
2. Desenchufar la lógica y potencia del drive.
3. Cambiar el switch `S3.4` del costado del drive a `On`. En nuestro caso todos están en `Off` por defecto.

![switches](/Assets/switches.jpg)

---

### 2) Alimentación

4. Enchufar la potencia y la lógica.

---

### 3) Ejecución del script

5. Correr el script desde **Windows 7 (CMD)**:

```bat
conda activate pdaqenv
python linmot_bulk_upload.py COM3 ./Curvas_random/ --id 0x3f --baud 57600 --delete-all-curves``` 

Con esto se especifica:

- **Puerto del drive:** `COM3`  
- **Directorio de curvas:** carpeta que contiene los `.csv` a subir  
- **MACID del drive:** identificador del dispositivo configurado en LinMot Talk  

Para esto, en LinMot Talk debe configurarse que el MACID se defina por parámetro:

![MACID source](/Assets/MACID_source.jpg)

El parámetro utilizado se puede revisar acá:

![MACID ID](/Assets/MACID_id.jpg)

En este caso `003Fh` corresponde a `0x3f` en hexadecimal.

- **Baud Rate de la comunicación:**

![Baud rate](/Assets/Baud_rate_definition.jpg)

En este caso es **57600**.

- El flag `--delete-all-curves` indica que se borren las curvas previamente cargadas.  
  Si no se usa, las curvas se agregan (append). 
  
### 4) Cierre del procedimiento

6. Desenchufar la lógica y la potencia una vez que termine.
7. Volver a poner el switch `S3.4` en `Off` como el resto.
8. Volver a enchufar la potencia y la lógica.
9. Abrir LinMot Talk y utilizar las curvas. En nuestro caso cargamos la Command Table con el orden de ejecución.

---

## Nota importante sobre unidades

Dentro del código (en la función `lm.write_curve()`) se convierten los valores de la curva a pasos del motor (de `0.1 µm`), en formato de enteros de 32 bits, que luego se envían en paquetes de 4 bytes al drive.

Para que LinMot Talk interprete correctamente estas unidades como milímetros durante el control del motor, es necesario setear la unidad mediante:

```python
import struct
struct.pack_into('<H', info, 38, 0x0005)  # YDimUUID``` 
