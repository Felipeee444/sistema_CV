from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog

# Rutas según se ejecute como script o como .exe (PyInstaller)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = BASE_DIR

ARCHIVO_PRODUCTOS = BASE_DIR / "Productos.txt"
ARCHIVO_VENTAS = BASE_DIR / "ventas.txt"

# .env junto al .exe o incrustado dentro de él
load_dotenv(BASE_DIR / ".env")
if BUNDLE_DIR != BASE_DIR:
    load_dotenv(BUNDLE_DIR / ".env")

_SB_ESTADO = {"cliente": None, "probado": False}

FORMATO_FECHA = "%d/%m/%Y %H:%M:%S"


def supabase_client() -> Client | None:
    """Cliente de Supabase o None si no está configurado."""
    if _SB_ESTADO["probado"]:
        return _SB_ESTADO["cliente"]
    _SB_ESTADO["probado"] = True
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        _SB_ESTADO["cliente"] = create_client(url, key)
    except Exception:
        _SB_ESTADO["cliente"] = None
    return _SB_ESTADO["cliente"]


def error_corto(e: Exception) -> str:
    """Mensajes de error de Supabase"""
    texto = str(e)
    if "PGRST205" in texto or "Could not find the table" in texto:
        return "no existe la tabla (ejecute el SQL en Supabase > SQL Editor)"
    return texto[:120]


class Producto:
    def __init__(self, codigo: str, nombre: str, precio: float, cantidad: int):
        self.codigo = codigo
        self.nombre = nombre
        self.precio = precio
        self.cantidad = cantidad
        self.siguiente: Producto | None = None


class ListaProductos:
    def __init__(self):
        self.cabeza: Producto | None = None

    def agregar(self, codigo: str, nombre: str, precio: float, cantidad: int) -> str:
        existente = self.buscar(codigo)
        if existente is not None:
            existente.cantidad += cantidad
            return "Producto existente. Cantidad actualizada."

        nuevo = Producto(codigo, nombre, precio, cantidad)
        if self.cabeza is None:
            self.cabeza = nuevo
        else:
            actual = self.cabeza
            while actual.siguiente is not None:
                actual = actual.siguiente
            actual.siguiente = nuevo
        return "Producto agregado correctamente."

    def buscar(self, codigo: str) -> Producto | None:
        actual = self.cabeza
        while actual is not None:
            if actual.codigo.lower() == codigo.lower():
                return actual
            actual = actual.siguiente
        return None

    def modificar(self, codigo: str, nuevo_precio: float, nueva_cantidad: int) -> str:
        p = self.buscar(codigo)
        if p is None:
            return "Producto no encontrado."
        p.precio = nuevo_precio
        p.cantidad = nueva_cantidad
        return "Producto modificado correctamente."

    def __iter__(self):
        actual = self.cabeza
        while actual is not None:
            yield actual
            actual = actual.siguiente

    def __len__(self) -> int:
        return sum(1 for _ in self)


class Archivo:
    @staticmethod
    def guardar(lista: ListaProductos) -> str:
        try:
            with open(ARCHIVO_PRODUCTOS, "w", encoding="utf-8") as writer:
                for p in lista:
                    writer.write(f"{p.codigo},{p.nombre},{p.precio},{p.cantidad}\n")
        except OSError as e:
            return f"Error al guardar el archivo: {e}"

        sb = supabase_client()
        if sb is None:
            return "Productos guardados localmente (Supabase no configurado)."
        try:
            filas = [{"codigo": p.codigo, "nombre": p.nombre,
                      "precio": p.precio, "cantidad": p.cantidad} for p in lista]
            if filas:
                sb.table("productos").upsert(filas, on_conflict="codigo").execute()
            else:
                sb.table("productos").delete().neq("codigo", "").execute()
            return "Productos sincronizados con Supabase + guardados localmente."
        except Exception as e:
            return f"Productos guardados solo localmente (Supabase: {error_corto(e)})."

    @staticmethod
    def cargar() -> tuple[ListaProductos, str]:
        sb = supabase_client()
        if sb is not None:
            try:
                filas = sb.table("productos").select("*").order("codigo").execute().data
                if filas:
                    lista = ListaProductos()
                    for f in filas:
                        lista.agregar(str(f["codigo"]), str(f["nombre"]),
                                      float(f["precio"]), int(f["cantidad"]))
                    # fusiona productos locales que aún no estén en la nube
                    locales = Archivo._leer_local()
                    extras = 0
                    for p in locales:
                        if lista.buscar(p.codigo) is None:
                            lista.agregar(p.codigo, p.nombre, p.precio, p.cantidad)
                            extras += 1
                    msg = f"Inventario cargado desde Supabase ({len(filas)} productos)."
                    if extras:
                        msg += f" +{extras} local(es) pendientes de sincronizar."
                    return lista, msg
            except Exception:
                pass  # sin conexión o sin tablas: usar archivo local

        lista = Archivo._leer_local()
        if len(lista) == 0 and not ARCHIVO_PRODUCTOS.exists():
            return lista, "No se encontró archivo previo, se iniciará vacío."
        return lista, "Productos cargados desde el archivo local."

    @staticmethod
    def _leer_local() -> ListaProductos:
        lista = ListaProductos()
        if not ARCHIVO_PRODUCTOS.exists():
            return lista
        try:
            with open(ARCHIVO_PRODUCTOS, encoding="utf-8") as br:
                for linea in br:
                    partes = linea.strip().split(",")
                    if len(partes) == 4:
                        try:
                            lista.agregar(partes[0], partes[1], float(partes[2]), int(partes[3]))
                        except ValueError:
                            continue
        except OSError:
            pass
        return lista


class Ventas:
    @staticmethod
    def guardar_venta(detalle: str) -> str:
        try:
            with open(ARCHIVO_VENTAS, "a", encoding="utf-8") as writer:
                writer.write(detalle + "\n")
                writer.write("----------------------------------------\n")
            return "Venta registrada con éxito."
        except OSError as e:
            return f"Error al guardar la venta: {e}"

    @staticmethod
    def registrar(venta: dict) -> str:
        """Guarda la venta en Supabase (ventas + detalle_ventas) y en el archivo local."""
        mensaje = Ventas.guardar_venta(venta["detalle"])

        sb = supabase_client()
        if sb is None:
            return mensaje + " (solo local: Supabase no configurado)"
        try:
            cabecera = (sb.table("ventas")
                        .insert({"cliente": venta["cliente"],
                                 "telefono": venta["telefono"],
                                 "dni": venta["dni"],
                                 "total": venta["total"]})
                        .execute().data[0])
            filas = [{"venta_id": cabecera["id"],
                      "producto_codigo": i["codigo"],
                      "nombre_producto": i["nombre"],
                      "cantidad": i["cantidad"],
                      "precio_unitario": i["precio"],
                      "subtotal": i["subtotal"]} for i in venta["items"]]
            if filas:
                sb.table("detalle_ventas").insert(filas).execute()
            return mensaje + " + Supabase"
        except Exception as e:
            return mensaje + f" (Supabase: {error_corto(e)})"

    @staticmethod
    def historial(pila_ventas: list[str]) -> list[str]:
        lineas: list[str] = ["--- HISTORIAL DE VENTAS ---", ""]

        if pila_ventas:
            for detalle in reversed(pila_ventas):
                lineas.extend(detalle.splitlines())
                lineas.append("")

        if ARCHIVO_VENTAS.exists():
            try:
                with open(ARCHIVO_VENTAS, encoding="utf-8") as br:
                    contenido = br.read().rstrip("\n")
                if contenido:
                    lineas.extend(contenido.splitlines())
                elif not pila_ventas:
                    lineas.append("No hay ventas registradas.")
            except OSError:
                lineas.append("No se encontró el archivo de ventas o está vacío.")
        elif not pila_ventas:
            lineas.append("No hay ventas registradas.")

        return lineas


class AgregarProductoScreen(ModalScreen[dict | None]):
    """Modal para agregar un producto o aumentar su stock."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("Agregar producto / aumentar stock", classes="titulo")
            yield Input(placeholder="Código", id="codigo")
            yield Input(placeholder="Nombre", id="nombre")
            with Horizontal(classes="fila"):
                yield Input(placeholder="Precio", id="precio", type="number")
                yield Input(placeholder="Cantidad", id="cantidad", type="number")
            yield Label("", id="error", classes="error")
            with Horizontal(classes="botones"):
                yield Button("Aceptar", variant="primary", id="ok")
                yield Button("Cancelar", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return

        codigo = self.query_one("#codigo", Input).value.strip()
        nombre = self.query_one("#nombre", Input).value.strip()
        precio_txt = self.query_one("#precio", Input).value.strip()
        cantidad_txt = self.query_one("#cantidad", Input).value.strip()
        error = self.query_one("#error", Label)

        if not codigo or not nombre:
            error.update("Código y nombre son obligatorios.")
            return
        try:
            precio = float(precio_txt)
            cantidad = int(cantidad_txt)
            if precio < 0 or cantidad < 0:
                raise ValueError
        except ValueError:
            error.update("Precio o cantidad no válidos.")
            return

        self.dismiss({"codigo": codigo, "nombre": nombre, "precio": precio, "cantidad": cantidad})


class ModificarProductoScreen(ModalScreen[dict | None]):
    """Modal para modificar precio y cantidad de un producto."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("Modificar producto", classes="titulo")
            yield Input(placeholder="Código del producto", id="codigo")
            with Horizontal(classes="fila"):
                yield Input(placeholder="Nuevo precio", id="precio", type="number")
                yield Input(placeholder="Nueva cantidad", id="cantidad", type="number")
            yield Label("", id="error", classes="error")
            with Horizontal(classes="botones"):
                yield Button("Aceptar", variant="primary", id="ok")
                yield Button("Cancelar", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return

        codigo = self.query_one("#codigo", Input).value.strip()
        precio_txt = self.query_one("#precio", Input).value.strip()
        cantidad_txt = self.query_one("#cantidad", Input).value.strip()
        error = self.query_one("#error", Label)

        if not codigo:
            error.update("Ingrese el código del producto.")
            return
        try:
            precio = float(precio_txt)
            cantidad = int(cantidad_txt)
            if precio < 0 or cantidad < 0:
                raise ValueError
        except ValueError:
            error.update("Precio o cantidad no válidos.")
            return

        self.dismiss({"codigo": codigo, "precio": precio, "cantidad": cantidad})


class RegistrarVentaScreen(ModalScreen[dict | None]):
    """Modal para registrar una venta (cliente + productos)."""

    def __init__(self, lista: ListaProductos):
        super().__init__()
        self.lista = lista
        self.lineas: list[str] = []
        self.items: list[dict] = []
        self.total: float = 0.0
        self._descuentos: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal", id="venta"):
            with VerticalScroll(id="venta_scroll"):
                yield Label("--- DATOS DEL CLIENTE ---", classes="titulo")
                yield Input(placeholder="Nombre del cliente", id="cliente")
                yield Input(placeholder="Teléfono", id="telefono")
                yield Input(placeholder="DNI", id="dni")

                yield Label("--- PRODUCTOS EN STOCK ---", classes="titulo")
                tabla = DataTable(id="inv_venta")
                tabla.add_columns("Código", "Nombre", "Precio", "Cantidad")
                for p in self.lista:
                    tabla.add_row(p.codigo, p.nombre, f"${p.precio}", str(p.cantidad))
                yield tabla

                yield Label("Carrito vacío.", id="carrito", classes="carrito")
                yield Label("", id="error", classes="error")
            with Horizontal(classes="fila"):
                yield Input(placeholder="Código del producto (o 'fin')", id="cod_venta")
                yield Input(placeholder="Unidades", id="unidades", type="number")
            with Horizontal(classes="botones"):
                yield Button("Agregar al carrito", variant="success", id="agregar")
                yield Button("Finalizar venta", variant="primary", id="fin")
                yield Button("Cancelar", id="cancel")

    def actualizar_carrito(self) -> None:
        carrito = self.query_one("#carrito", Label)
        if not self.lineas:
            carrito.update("Carrito vacío.")
        else:
            carrito.update("\n".join(self.lineas) + f"\nTOTAL: ${self.total:.2f}")

    def refrescar_inventario(self) -> None:
        tabla = self.query_one("#inv_venta", DataTable)
        tabla.clear()
        if not tabla.columns:
            tabla.add_columns("Código", "Nombre", "Precio", "Cantidad")
        for p in self.lista:
            tabla.add_row(p.codigo, p.nombre, f"${p.precio}", str(p.cantidad))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        error = self.query_one("#error", Label)

        if event.button.id == "cancel":
            for codigo, cantidad in self._descuentos.items():
                prod = self.lista.buscar(codigo)
                if prod:
                    prod.cantidad += cantidad
            self.dismiss(None)
            return

        if event.button.id == "fin":
            if self.total <= 0:
                error.update("No se registró ninguna venta.")
                return
            self._finalizar_venta()
            return

        if event.button.id == "agregar":
            codigo = self.query_one("#cod_venta", Input).value.strip()
            if codigo.lower() == "fin":
                if self.total <= 0:
                    error.update("No se registró ninguna venta.")
                else:
                    self._finalizar_venta()
                return

            p = self.lista.buscar(codigo)
            if p is None:
                error.update("Producto no encontrado.")
                return
            try:
                unidades = int(self.query_one("#unidades", Input).value.strip())
                if unidades <= 0:
                    raise ValueError
            except ValueError:
                error.update("Ingrese una cantidad válida.")
                return

            if unidades > p.cantidad:
                error.update(f"Stock insuficiente. Disponible: {p.cantidad}")
                return

            p.cantidad -= unidades
            self._descuentos.setdefault(p.codigo, 0)
            self._descuentos[p.codigo] += unidades
            subtotal = p.precio * unidades
            self.total += subtotal
            self.lineas.append(f"{p.nombre} x{unidades} - ${subtotal}")
            self.items.append({"codigo": p.codigo, "nombre": p.nombre,
                               "cantidad": unidades, "precio": p.precio,
                               "subtotal": subtotal})
            error.update("")
            self.query_one("#cod_venta", Input).value = ""
            self.query_one("#unidades", Input).value = ""
            self.actualizar_carrito()
            self.refrescar_inventario()

    def _finalizar_venta(self) -> None:
        cliente = self.query_one("#cliente", Input).value.strip()
        telefono = self.query_one("#telefono", Input).value.strip()
        dni = self.query_one("#dni", Input).value.strip()
        detalle = f"Cliente: {cliente} | Tel: {telefono} | DNI: {dni}\n"
        detalle += "\n".join(self.lineas) + "\n"
        detalle += f"TOTAL: ${self.total}\n"
        detalle += f"Fecha: {datetime.now().strftime(FORMATO_FECHA)}\n"
        self.dismiss({
            "cliente": cliente,
            "telefono": telefono,
            "dni": dni,
            "total": self.total,
            "items": self.items,
            "detalle": detalle,
        })


class HistorialScreen(ModalScreen[None]):
    """Modal con el historial de ventas (memoria + archivo)."""

    def __init__(self, pila_ventas: list[str]):
        super().__init__()
        self.pila_ventas = pila_ventas

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal", id="historial_modal"):
            yield Label("--- HISTORIAL DE VENTAS ---", classes="titulo")
            with VerticalScroll(id="historial_scroll"):
                yield RichLog(id="historial", wrap=True, auto_scroll=False)
            with Horizontal(classes="botones"):
                yield Button("Cerrar", variant="primary", id="cerrar")

    def on_mount(self) -> None:
        log = self.query_one("#historial", RichLog)
        for linea in Ventas.historial(self.pila_ventas):
            log.write(linea)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cerrar":
            self.dismiss(None)


class SistemaCompraVentaApp(App):
    """Aplicación TUI del Sistema de Compra y Venta."""

    TITLE = "Sistema de Compra y Venta"
    SUB_TITLE = "Parcial 2 - Python + Textual"

    CSS = """
    Screen {
        align: center top;
    }
    #menu {
        height: auto;
        padding: 1 2;
        align-horizontal: center;
    }
    #menu Button {
        margin: 0 1;
    }
    #inventario {
        height: 1fr;
        margin: 0 2;
    }
    #salida {
        height: 12;
        margin: 0 2 1 2;
        border: round $accent;
        background: $surface;
    }
    ModalScreen {
        align: center middle;
    }
    .modal {
        width: 72;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    .modal Input {
        margin: 0 0 1 0;
    }
    .fila {
        height: auto;
    }
    .fila Input {
        width: 1fr;
        margin: 0 1 1 0;
    }
    .titulo {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .error {
        color: $error;
        min-height: 1;
        margin-bottom: 1;
    }
    .carrito {
        height: auto;
        max-height: 6;
        border: round $primary;
        padding: 0 1;
        margin-bottom: 1;
    }
    .botones {
        height: auto;
        align-horizontal: center;
    }
    .botones Button {
        margin: 0 1;
    }
    #venta {
        height: 90%;
    }
    #venta_scroll {
        height: 1fr;
    }
    #inv_venta {
        height: 5;
        margin-bottom: 1;
    }
    #historial_modal {
        width: 80;
        height: 90%;
    }
    #historial_scroll {
        height: 1fr;
        min-height: 10;
    }
    """

    BINDINGS = [
        ("1", "agregar", "Agregar"),
        ("2", "inventario", "Inventario"),
        ("3", "modificar", "Modificar"),
        ("4", "venta", "Venta"),
        ("5", "historial", "Historial"),
        ("6", "salir", "Guardar y salir"),
    ]

    def __init__(self):
        super().__init__()
        self.lista, mensaje = Archivo.cargar()
        self.pila_ventas: list[str] = []
        self._mensaje_carga = mensaje

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="menu"):
            yield Button("1. Agregar producto", id="btn_agregar", variant="primary")
            yield Button("2. Inventario", id="btn_inventario")
            yield Button("3. Modificar", id="btn_modificar")
            yield Button("4. Registrar venta", id="btn_venta", variant="success")
            yield Button("5. Historial", id="btn_historial")
            yield Button("6. Guardar y salir", id="btn_salir", variant="error")
        yield DataTable(id="inventario")
        yield RichLog(id="salida", wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.actualizar_inventario()
        salida = self.query_one("#salida", RichLog)
        salida.write("[bold green]--- SISTEMA DE COMPRA Y VENTA ---[/bold green]")
        salida.write(self._mensaje_carga)
        salida.write("Use los botones o las teclas 1-6 para operar.")

    def actualizar_inventario(self) -> None:
        tabla = self.query_one("#inventario", DataTable)
        if not tabla.columns:
            tabla.add_columns("Código", "Nombre", "Precio", "Cantidad")
        tabla.clear()
        productos = list(self.lista)
        if not productos:
            tabla.add_row("-", "No hay productos registrados.", "-", "-")
        else:
            for p in productos:
                tabla.add_row(p.codigo, p.nombre, f"${p.precio}", str(p.cantidad))

    def escribir_log(self, mensaje: str) -> None:
        self.query_one("#salida", RichLog).write(mensaje)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        acciones = {
            "btn_agregar": self.action_agregar,
            "btn_inventario": self.action_inventario,
            "btn_modificar": self.action_modificar,
            "btn_venta": self.action_venta,
            "btn_historial": self.action_historial,
            "btn_salir": self.action_salir,
        }
        accion = acciones.get(event.button.id or "")
        if accion:
            accion()

    def action_agregar(self) -> None:
        self.push_screen(AgregarProductoScreen(), self.finalizar_agregar)

    def finalizar_agregar(self, datos: dict | None) -> None:
        if datos is None:
            self.escribir_log("Operación cancelada.")
            return
        mensaje = self.lista.agregar(datos["codigo"], datos["nombre"], datos["precio"], datos["cantidad"])
        self.escribir_log(mensaje)
        self.actualizar_inventario()

    def action_inventario(self) -> None:
        productos = list(self.lista)
        if not productos:
            self.escribir_log("[yellow]No hay productos registrados.[/yellow]")
            return
        self.escribir_log("[bold]--- INVENTARIO ---[/bold]")
        for p in productos:
            self.escribir_log(
                f"Código: {p.codigo} | {p.nombre} | Precio: ${p.precio} | Cantidad: {p.cantidad}"
            )

    def action_modificar(self) -> None:
        self.push_screen(ModificarProductoScreen(), self.finalizar_modificar)

    def finalizar_modificar(self, datos: dict | None) -> None:
        if datos is None:
            self.escribir_log("Operación cancelada.")
            return
        mensaje = self.lista.modificar(datos["codigo"], datos["precio"], datos["cantidad"])
        self.escribir_log(mensaje)
        self.actualizar_inventario()

    def action_venta(self) -> None:
        if len(self.lista) == 0:
            self.escribir_log("[yellow]No hay productos registrados para vender.[/yellow]")
            return
        self.push_screen(RegistrarVentaScreen(self.lista), self.finalizar_venta)

    def finalizar_venta(self, venta: dict | None) -> None:
        if venta is None:
            self.escribir_log("Venta cancelada.")
            self.actualizar_inventario()
            return
        self.pila_ventas.append(venta["detalle"])
        mensaje = Ventas.registrar(venta)
        self.escribir_log(f"[bold green]{mensaje}[/bold green]")
        for linea in venta["detalle"].splitlines():
            self.escribir_log(linea)
        self.escribir_log(Archivo.guardar(self.lista))
        self.actualizar_inventario()

    def action_historial(self) -> None:
        self.push_screen(HistorialScreen(self.pila_ventas))

    def action_salir(self) -> None:
        mensaje = Archivo.guardar(self.lista)
        self.escribir_log(mensaje)
        self.escribir_log("Saliendo del sistema...")
        self.exit()

    def action_quit(self) -> None:
        Archivo.guardar(self.lista)
        self.exit()


if __name__ == "__main__":
    SistemaCompraVentaApp().run()
