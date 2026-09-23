"""
API web (Flask) del Sistema de Compra y Venta conectada a Supabase.
"""

import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request
from supabase import Client, create_client
from dotenv import load_dotenv

# Rutas según se ejecute como script o como .exe (PyInstaller)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = BASE_DIR

load_dotenv(BASE_DIR / ".env")
if BUNDLE_DIR != BASE_DIR:
    load_dotenv(BUNDLE_DIR / ".env")

app = Flask(__name__)

supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")
)


@app.route('/')
def index():
    productos = supabase.table('productos').select('*').order('codigo').execute().data
    ventas = (supabase.table('ventas')
              .select('*, detalle_ventas(*)')
              .order('fecha', desc=True)
              .limit(20)
              .execute().data)

    html = ['<h1>Sistema de Compra y Venta</h1>']

    html.append('<h2>Inventario</h2>')
    html.append("<table border='1' cellpadding='6'>"
                "<tr><th>Código</th><th>Nombre</th><th>Precio</th><th>Stock</th></tr>")
    for p in productos:
        html.append(f"<tr><td>{p['codigo']}</td><td>{p['nombre']}</td>"
                    f"<td>${p['precio']}</td><td>{p['cantidad']}</td></tr>")
    html.append('</table>')
    if not productos:
        html.append('<p>No hay productos registrados.</p>')

    html.append('<h2>Últimas ventas</h2>')
    if not ventas:
        html.append('<p>No hay ventas registradas.</p>')
    for v in ventas:
        html.append(f"<p><b>{v['cliente']}</b> | Tel: {v['telefono']} | DNI: {v['dni']} "
                    f"| <b>TOTAL: ${v['total']}</b> | {v['fecha']}<br>")
        for d in v.get('detalle_ventas') or []:
            html.append(f"&nbsp;&nbsp;&#8226; {d['nombre_producto']} x{d['cantidad']}"
                        f" = ${d['subtotal']}<br>")
        html.append('</p>')

    return ''.join(html)


@app.get('/api/productos')
def listar_productos():
    try:
        productos = supabase.table('productos').select('*').order('codigo').execute().data
        return jsonify(productos)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.post('/api/productos')
def crear_producto():
    data = request.get_json(silent=True) or {}
    codigo = (data.get('codigo') or '').strip()
    nombre = (data.get('nombre') or '').strip()
    if not codigo or not nombre:
        return jsonify({'error': 'codigo y nombre son obligatorios'}), 400
    try:
        precio = float(data.get('precio', 0))
        cantidad = int(data.get('cantidad', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'precio o cantidad no válidos'}), 400

    try:
        existente = (supabase.table('productos').select('*')
                     .eq('codigo', codigo).execute().data)
        if existente:
            nueva = existente[0]['cantidad'] + cantidad
            supabase.table('productos').update(
                {'cantidad': nueva, 'precio': precio}
            ).eq('codigo', codigo).execute()
            producto = supabase.table('productos').select('*') \
                .eq('codigo', codigo).execute().data[0]
            return jsonify({'mensaje': 'Producto existente. Cantidad actualizada.',
                            'producto': producto})

        producto = (supabase.table('productos')
                    .insert({'codigo': codigo, 'nombre': nombre,
                             'precio': precio, 'cantidad': cantidad})
                    .execute().data[0])
        return jsonify({'mensaje': 'Producto agregado correctamente.',
                        'producto': producto}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.put('/api/productos/<codigo>')
def modificar_producto(codigo):
    data = request.get_json(silent=True) or {}
    campos = {}
    if 'precio' in data:
        try:
            campos['precio'] = float(data['precio'])
        except (TypeError, ValueError):
            return jsonify({'error': 'precio no válido'}), 400
    if 'cantidad' in data:
        try:
            campos['cantidad'] = int(data['cantidad'])
        except (TypeError, ValueError):
            return jsonify({'error': 'cantidad no válida'}), 400
    if not campos:
        return jsonify({'error': 'envíe precio y/o cantidad'}), 400

    try:
        resultado = (supabase.table('productos').update(campos)
                     .eq('codigo', codigo).execute().data)
        if not resultado:
            return jsonify({'error': 'Producto no encontrado'}), 404
        return jsonify({'mensaje': 'Producto modificado correctamente.',
                        'producto': resultado[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.post('/api/ventas')
def crear_venta():
    data = request.get_json(silent=True) or {}
    cliente = (data.get('cliente') or '').strip()
    items = data.get('items') or []
    if not cliente or not items:
        return jsonify({'error': 'cliente e items son obligatorios'}), 400

    try:
        codigos = [str(i.get('codigo', '')) for i in items]
        productos = (supabase.table('productos').select('*')
                     .in_('codigo', codigos).execute().data)
        por_codigo = {p['codigo']: p for p in productos}

        total = 0.0
        detalles = []
        for item in items:
            codigo = str(item.get('codigo', ''))
            p = por_codigo.get(codigo)
            if p is None:
                return jsonify({'error': f'Producto no encontrado: {codigo}'}), 404
            try:
                unidades = int(item.get('cantidad', 0))
            except (TypeError, ValueError):
                return jsonify({'error': 'cantidad no válida'}), 400
            if unidades <= 0:
                return jsonify({'error': 'cantidad debe ser mayor a 0'}), 400
            if unidades > p['cantidad']:
                return jsonify({'error': f"Stock insuficiente de {p['nombre']}. "
                                         f"Disponible: {p['cantidad']}"}), 409
            subtotal = float(p['precio']) * unidades
            total += subtotal
            detalles.append({
                'producto_codigo': codigo,
                'nombre_producto': p['nombre'],
                'cantidad': unidades,
                'precio_unitario': float(p['precio']),
                'subtotal': subtotal,
                '_nuevo_stock': p['cantidad'] - unidades,
            })

        venta = (supabase.table('ventas')
                 .insert({'cliente': cliente,
                          'telefono': data.get('telefono'),
                          'dni': data.get('dni'),
                          'total': total})
                 .execute().data[0])

        filas = [{'venta_id': venta['id'],
                  'producto_codigo': d['producto_codigo'],
                  'nombre_producto': d['nombre_producto'],
                  'cantidad': d['cantidad'],
                  'precio_unitario': d['precio_unitario'],
                  'subtotal': d['subtotal']} for d in detalles]
        supabase.table('detalle_ventas').insert(filas).execute()

        for d in detalles:
            supabase.table('productos').update({'cantidad': d['_nuevo_stock']}) \
                .eq('codigo', d['producto_codigo']).execute()

        venta['detalle_ventas'] = filas
        return jsonify({'mensaje': 'Venta registrada con éxito.',
                        'venta': venta}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.get('/api/ventas')
def listar_ventas():
    try:
        ventas = (supabase.table('ventas')
                  .select('*, detalle_ventas(*)')
                  .order('fecha', desc=True)
                  .execute().data)
        return jsonify(ventas)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
