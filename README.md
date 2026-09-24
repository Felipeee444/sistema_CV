# Sistema de Compra y Venta

Versión en Python del `SistemaCompraVenta.java`, con interfaz en la terminal
(**Textual**) y sincronización a **Supabase**. Incluye una API web con **Flask**.

## Archivos

| Archivo | Descripción |
|---|---|
| `sistema_compra_venta.py` | Programa principal (interfaz en la terminal) |
| `app.py` | API/página web Flask |
| `SistemaCompraVenta.exe` | Ejecutable del programa de terminal |
| `SistemaVentaAPI.exe` | Ejecutable del servidor web |
| `.env` | URL y clave de Supabase |
| `Productos.txt` | Respaldo local del inventario |
| `ventas.txt` | Respaldo local del historial de ventas |
| `requirements.txt` | Dependencias (`textual`, `flask`, `supabase`, `python-dotenv`) |

## Cómo ejecutar

**Opción A — ejecutable** (no requiere Python ni VS Code):

```
SistemaCompraVenta.exe
```

**Opción B — desde el código:**

```
.venv\Scripts\Activate.ps1
python sistema_compra_venta.py
```

Servidor web (opcional):

```
python app.py        →  http://127.0.0.1:5000/
```

## Opciones del menú (botones o teclas 1-6)

| Tecla | Opción | Descripción |
|-------|----------------------|-----------------------------------------------|
| 1 | Agregar producto | Agrega producto nuevo o suma stock si existe |
| 2 | Inventario | Muestra la lista enlazada de productos |
| 3 | Modificar producto | Cambia precio y cantidad de un producto |
| 4 | Registrar venta | Cliente, carrito, control de stock y total |
| 5 | Historial de ventas | Muestra ventas en memoria + `ventas.txt` |
| 6 | Guardar y salir | Graba los datos y cierra |

`Ctrl+Q` también guarda antes de cerrar.

## Base de datos (Supabase)

Tres tablas creadas en el SQL Editor de Supabase:

- **`productos`** → inventario (`codigo`, `nombre`, `precio`, `cantidad`)
- **`ventas`** → cabecera de cada venta (`cliente`, `telefono`, `dni`, `total`, `fecha`)
- **`detalle_ventas`** → productos de cada venta (`venta_id`, `producto_codigo`, `cantidad`, `precio_unitario`, `subtotal`)

El programa carga desde Supabase **y fusiona** lo que haya solo en el `.txt`
(nunca pierde datos locales). Al guardar, escribe siempre el `.txt` (respaldo)
y sincroniza con la nube. Si Supabase no responde, funciona 100% en modo local.

## API de Flask

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Página web con inventario y últimas ventas |
| GET | `/api/productos` | Lista el inventario |
| POST | `/api/productos` | Agrega producto o suma stock |
| PUT | `/api/productos/<codigo>` | Modifica precio/cantidad |
| GET | `/api/ventas` | Historial con detalle de ventas |
| POST | `/api/ventas` | Registra venta (valida stock y lo descuenta) |

## Estructura

- `Producto` / `ListaProductos` → lista enlazada (misma lógica que en Java)
- `Archivo` → guardar/cargar productos (Supabase + `.txt`)
- `Ventas` → registrar venta + historial (pila en memoria + archivo + nube)
- `SistemaCompraVentaApp` → app Textual con pantallas modales para cada opción

## Regenerar los .exe

```
pyinstaller --noconfirm --onefile --name SistemaCompraVenta --add-data ".env;." sistema_compra_venta.py
pyinstaller --noconfirm --onefile --name SistemaVentaAPI --add-data ".env;." app.py
copy dist\SistemaCompraVenta.exe .
copy dist\SistemaVentaAPI.exe .
```
