from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)

DB = "gastos.db"


# ==================================================
# CONEXIÓN DB
# ==================================================

def get_connection():

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    return conn


# ==================================================
# INICIALIZAR BASE DE DATOS
# ==================================================

def init_db():

    conn = get_connection()
    cur = conn.cursor()

    # ==================================================
    # TABLA MAESTRA TIPOS INGRESO
    # ==================================================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tipos_ingreso (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        nombre TEXT UNIQUE NOT NULL,

        aplica_deduccion INTEGER NOT NULL,

        tipo_calculo TEXT NOT NULL,

        valor_unitario REAL DEFAULT 0
    )
    """)

    # ==================================================
    # TABLA INGRESOS
    # ==================================================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ingresos (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        tipo_ingreso_id INTEGER,

        concepto_otro TEXT,

        valor_unitario REAL,

        cantidad INTEGER,

        total REAL,

        fecha TEXT,

        FOREIGN KEY(tipo_ingreso_id)
        REFERENCES tipos_ingreso(id)
    )
    """)

    # ==================================================
    # TABLA GASTOS
    # ==================================================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gastos (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        concepto TEXT NOT NULL,

        valor REAL NOT NULL,

        fecha TEXT NOT NULL,

        mes TEXT NOT NULL
    )
    """)

    # ==================================================
    # INSERTAR MAESTRAS DEFAULT
    # ==================================================

    tipos = [

        ("SALARIO CRIS", 1, "salario", 0),

        ("SALARIO ELI", 1, "salario", 0),

        ("TOQUES", 0, "toques", 350000),

        ("OTRO INGRESO", 0, "otro", 0)
    ]

    for tipo in tipos:

        cur.execute("""
        INSERT OR IGNORE INTO tipos_ingreso
        (
            nombre,
            aplica_deduccion,
            tipo_calculo,
            valor_unitario
        )
        VALUES (?, ?, ?, ?)
        """, tipo)

    conn.commit()
    conn.close()


# ==================================================
# HOME
# ==================================================

@app.route("/")
def index():

    conn = get_connection()
    cur = conn.cursor()

    mes_actual = datetime.now().strftime("%B %Y").upper()

    # ==================================================
    # GASTOS MES ACTUAL
    # ==================================================

    gastos = cur.execute("""
        SELECT *
        FROM gastos
        WHERE mes = ?
        ORDER BY fecha DESC
    """, (mes_actual,)).fetchall()

    # ==================================================
    # INGRESOS
    # ==================================================

    ingresos = cur.execute("""
        SELECT

            ingresos.*,

            tipos_ingreso.nombre AS tipo_nombre,

            tipos_ingreso.tipo_calculo

        FROM ingresos

        INNER JOIN tipos_ingreso
        ON ingresos.tipo_ingreso_id = tipos_ingreso.id

        ORDER BY fecha DESC

    """).fetchall()

    # ==================================================
    # TIPOS INGRESO
    # ==================================================

    tipos_ingreso = cur.execute("""
        SELECT *
        FROM tipos_ingreso
        ORDER BY nombre
    """).fetchall()

    # ==================================================
    # TOTALES
    # ==================================================

    total_gastos = sum(g["valor"] for g in gastos)

    total_ingresos = sum(i["total"] for i in ingresos)

    balance = total_ingresos - total_gastos

    conn.close()

    return render_template(

        "index.html",

        gastos=gastos,

        ingresos=ingresos,

        tipos_ingreso=tipos_ingreso,

        mes_actual=mes_actual,

        total_gastos=total_gastos,

        total_ingresos=total_ingresos,

        balance=balance
    )


# ==================================================
# VISTA MAESTRAS
# ==================================================

@app.route("/maestras")
def maestras():

    conn = get_connection()
    cur = conn.cursor()

    tipos = cur.execute("""
        SELECT *
        FROM tipos_ingreso
        ORDER BY nombre
    """).fetchall()

    conn.close()

    return render_template(
        "maestras.html",
        tipos=tipos
    )


# ==================================================
# ACTUALIZAR MAESTRAS
# ==================================================

@app.route("/actualizar_maestra", methods=["POST"])
def actualizar_maestra():

    tipo_id = request.form["tipo_id"]

    valor_unitario = float(
        request.form["valor_unitario"] or 0
    )

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tipos_ingreso
        SET valor_unitario = ?
        WHERE id = ?
    """, (
        valor_unitario,
        tipo_id
    ))

    conn.commit()
    conn.close()

    return redirect("/maestras")


# ==================================================
# GUARDAR GASTO
# ==================================================

@app.route("/guardar_gasto", methods=["POST"])
def guardar_gasto():

    concepto = request.form["concepto"]

    valor = float(
        request.form["valor"]
    )

    fecha = request.form["fecha"]

    fecha_obj = datetime.strptime(
        fecha,
        "%Y-%m-%d"
    )

    mes = fecha_obj.strftime(
        "%B %Y"
    ).upper()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO gastos (

            concepto,

            valor,

            fecha,

            mes

        )
        VALUES (?, ?, ?, ?)
    """, (
        concepto,
        valor,
        fecha,
        mes
    ))

    conn.commit()
    conn.close()

    return redirect("/")


# ==================================================
# GUARDAR INGRESO
# ==================================================

@app.route("/guardar_ingreso", methods=["POST"])
def guardar_ingreso():

    tipo_id = request.form["tipo_ingreso"]

    fecha = request.form["fecha"]

    concepto_otro = request.form.get(
        "concepto_otro", ""
    )

    valor_manual = float(
        request.form.get(
            "valor_manual", 0
        ) or 0
    )

    cantidad = int(
        request.form.get(
            "cantidad", 1
        ) or 1
    )

    conn = get_connection()
    cur = conn.cursor()

    # ==================================================
    # OBTENER MAESTRA
    # ==================================================

    tipo = cur.execute("""
        SELECT *
        FROM tipos_ingreso
        WHERE id = ?
    """, (tipo_id,)).fetchone()

    total = 0
    valor_unitario = 0

    # ==================================================
    # SALARIOS
    # ==================================================

    if tipo["tipo_calculo"] == "salario":

        valor_unitario = valor_manual

        total = valor_manual * 0.92

    # ==================================================
    # TOQUES
    # ==================================================

    elif tipo["tipo_calculo"] == "toques":

        valor_unitario = tipo["valor_unitario"]

        total = valor_unitario * cantidad

    # ==================================================
    # OTROS INGRESOS
    # ==================================================

    elif tipo["tipo_calculo"] == "otro":

        valor_unitario = valor_manual

        total = valor_manual

    # ==================================================
    # GUARDAR
    # ==================================================

    cur.execute("""
        INSERT INTO ingresos (

            tipo_ingreso_id,

            concepto_otro,

            valor_unitario,

            cantidad,

            total,

            fecha

        )
        VALUES (?, ?, ?, ?, ?, ?)

    """, (

        tipo_id,

        concepto_otro,

        valor_unitario,

        cantidad,

        total,

        fecha
    ))

    conn.commit()
    conn.close()

    return redirect("/")


# ==================================================
# LIMPIAR DB
# ==================================================

# @app.route("/limpiar_db")
# def limpiar_db():

#     conn = get_connection()
#     cur = conn.cursor()

#     cur.execute("DELETE FROM gastos")
#     cur.execute("DELETE FROM ingresos")

#     conn.commit()
#     conn.close()

#     return "Base de datos limpiada"


# ==================================================
# INIT DB
# ==================================================

init_db()


# ==================================================
# RUN APP
# ==================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )