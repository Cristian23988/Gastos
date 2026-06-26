from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import datetime, timedelta
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

        mes TEXT,

        FOREIGN KEY(tipo_ingreso_id)
        REFERENCES tipos_ingreso(id)
    )
    """)

    existing_columns = [row[1] for row in cur.execute("PRAGMA table_info(ingresos)")]
    if "mes" not in existing_columns:
        cur.execute("ALTER TABLE ingresos ADD COLUMN mes TEXT")

    rows = cur.execute("SELECT id, fecha FROM ingresos WHERE mes IS NULL OR mes = ''").fetchall()
    for row in rows:
        fecha_obj = datetime.strptime(row[1], "%Y-%m-%d")
        mes = format_mes_label(fecha_obj)
        cur.execute("UPDATE ingresos SET mes = ? WHERE id = ?", (mes, row[0]))

    # Normalizar valores existentes de 'mes' (ingresos y gastos) a formato en español
    distinct_ingresos = [r[0] for r in cur.execute("SELECT DISTINCT mes FROM ingresos WHERE mes IS NOT NULL AND mes != ''").fetchall()]
    for m in distinct_ingresos:
        parsed = parse_mes_label(m)
        if parsed:
            normalized = format_mes_label(parsed)
            if normalized != m:
                cur.execute("UPDATE ingresos SET mes = ? WHERE mes = ?", (normalized, m))

    distinct_gastos = [r[0] for r in cur.execute("SELECT DISTINCT mes FROM gastos WHERE mes IS NOT NULL AND mes != ''").fetchall()]
    for m in distinct_gastos:
        parsed = parse_mes_label(m)
        if parsed:
            normalized = format_mes_label(parsed)
            if normalized != m:
                cur.execute("UPDATE gastos SET mes = ? WHERE mes = ?", (normalized, m))

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

SPANISH_MONTHS = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}

ENGLISH_MONTHS = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}

MONTH_NAMES = {
    1: "ENERO",
    2: "FEBRERO",
    3: "MARZO",
    4: "ABRIL",
    5: "MAYO",
    6: "JUNIO",
    7: "JULIO",
    8: "AGOSTO",
    9: "SEPTIEMBRE",
    10: "OCTUBRE",
    11: "NOVIEMBRE",
    12: "DICIEMBRE",
}


def parse_mes_label(mes_label):
    if not mes_label:
        return None

    parts = mes_label.strip().upper().split()
    if len(parts) != 2:
        return None

    name, year = parts
    month = SPANISH_MONTHS.get(name) or ENGLISH_MONTHS.get(name)
    if not month:
        return None

    try:
        return datetime(int(year), month, 1)
    except ValueError:
        return None


def format_mes_label(date_obj):
    return f"{MONTH_NAMES[date_obj.month]} {date_obj.year}"


def get_previous_month_label(mes_label):
    current = parse_mes_label(mes_label)
    if not current:
        return None

    prev = (current.replace(day=1) - timedelta(days=1)).replace(day=1)
    return format_mes_label(prev)


# ==================================================
# HOME
# ==================================================

@app.route("/")
def index():

    conn = get_connection()
    cur = conn.cursor()

    requested_mes = request.args.get("mes")
    default_mes = format_mes_label(datetime.now())
    mes_actual = requested_mes or default_mes

    available_meses = set()
    for row in cur.execute("SELECT mes FROM gastos").fetchall():
        if row["mes"]:
            available_meses.add(row["mes"].strip())
    for row in cur.execute("SELECT mes FROM ingresos").fetchall():
        if row["mes"]:
            available_meses.add(row["mes"].strip())
    available_meses.add(default_mes)

    formatted_months = sorted(
        [m for m in available_meses if parse_mes_label(m)],
        key=lambda m: parse_mes_label(m),
        reverse=True
    )

    if not parse_mes_label(mes_actual):
        mes_actual = default_mes

    mes_anterior = get_previous_month_label(mes_actual)

    gastos = cur.execute("""
        SELECT *
        FROM gastos
        WHERE mes = ?
        ORDER BY fecha DESC
    """, (mes_actual,)).fetchall()

    ingresos = cur.execute("""
        SELECT
            ingresos.*,
            tipos_ingreso.nombre AS tipo_nombre,
            tipos_ingreso.tipo_calculo
        FROM ingresos
        INNER JOIN tipos_ingreso
        ON ingresos.tipo_ingreso_id = tipos_ingreso.id
        WHERE ingresos.mes = ?
        ORDER BY fecha DESC
    """, (mes_actual,)).fetchall()

    total_gastos = sum(g["valor"] for g in gastos)
    total_ingresos = sum(i["total"] for i in ingresos)
    balance = total_ingresos - total_gastos

    prev_totals = cur.execute("""
        SELECT
            SUM(total) AS ingresos,
            (SELECT SUM(valor) FROM gastos WHERE mes = ?) AS gastos
        FROM ingresos
        WHERE mes = ?
    """, (mes_anterior, mes_anterior)).fetchone()

    prev_ingresos = prev_totals["ingresos"] or 0
    prev_gastos = prev_totals["gastos"] or 0
    prev_balance = prev_ingresos - prev_gastos
    balance_diff = balance - prev_balance

    if mes_anterior:
        if balance_diff > 0:
            comparacion_text = f"Mejor que {mes_anterior}: +${balance_diff:,.0f}"
        elif balance_diff < 0:
            comparacion_text = f"Peor que {mes_anterior}: -${abs(balance_diff):,.0f}"
        else:
            comparacion_text = f"Igual al mes anterior {mes_anterior}."
    else:
        comparacion_text = "No hay comparación con mes anterior disponible."

    gastos_por_dia_rows = cur.execute("""
        SELECT fecha, SUM(valor) AS total
        FROM gastos
        WHERE mes = ?
        GROUP BY fecha
        ORDER BY fecha ASC
    """, (mes_actual,)).fetchall()

    gastos_por_dia = []
    max_total = max((row["total"] for row in gastos_por_dia_rows), default=0)
    for row in gastos_por_dia_rows:
        fecha_obj = datetime.strptime(row["fecha"], "%Y-%m-%d")
        day_label = fecha_obj.strftime("%d")
        altura = int((row["total"] / max_total) * 120) if max_total > 0 else 10
        gastos_por_dia.append({
            "day": day_label,
            "total": row["total"],
            "height": altura
        })

    mayor_dia_gasto = None
    if gastos_por_dia:
        mayor_dia_gasto = max(gastos_por_dia, key=lambda item: item["total"])

    dias_con_gasto = len(gastos_por_dia)
    gasto_promedio = total_gastos / dias_con_gasto if dias_con_gasto else 0

    tipos_ingreso = cur.execute("SELECT * FROM tipos_ingreso ORDER BY nombre").fetchall()

    conn.close()

    return render_template(
        "index.html",
        gastos=gastos,
        ingresos=ingresos,
        tipos_ingreso=tipos_ingreso,
        mes_actual=mes_actual,
        available_meses=formatted_months,
        total_gastos=total_gastos,
        total_ingresos=total_ingresos,
        balance=balance,
        mes_anterior=mes_anterior,
        prev_ingresos=prev_ingresos,
        prev_gastos=prev_gastos,
        prev_balance=prev_balance,
        comparacion_text=comparacion_text,
        gastos_por_dia=gastos_por_dia,
        mayor_dia_gasto=mayor_dia_gasto,
        gasto_promedio=gasto_promedio
    )


# ==================================================
# VISTA INGRESOS MENSUALES
# ==================================================

@app.route("/maestras")
def maestras_redirect():
    return redirect("/ingresos_mensuales")


@app.route("/ingresos_mensuales")
def ingresos_mensuales():

    conn = get_connection()
    cur = conn.cursor()

    mes_actual = format_mes_label(datetime.now())
    fecha_inicio = datetime.now().replace(day=1).strftime("%Y-%m-%d")

    tipos = cur.execute("""
        SELECT *
        FROM tipos_ingreso
        ORDER BY nombre
    """).fetchall()

    ingresos = cur.execute("""
        SELECT
            ingresos.*,
            tipos_ingreso.nombre AS tipo_nombre,
            tipos_ingreso.tipo_calculo
        FROM ingresos
        INNER JOIN tipos_ingreso
        ON ingresos.tipo_ingreso_id = tipos_ingreso.id
        WHERE ingresos.mes = ?
        ORDER BY tipos_ingreso.nombre
    """, (mes_actual,)).fetchall()

    existing_tipo_ids = {ingreso["tipo_ingreso_id"] for ingreso in ingresos}

    if len(ingresos) != len(tipos):
        for tipo in tipos:
            if tipo["id"] not in existing_tipo_ids:
                valor_unitario = tipo["valor_unitario"] if tipo["tipo_calculo"] == "toques" else 0
                cantidad = 1
                total = valor_unitario * cantidad if tipo["tipo_calculo"] == "toques" else 0

                cur.execute("""
                    INSERT INTO ingresos (
                        tipo_ingreso_id,
                        concepto_otro,
                        valor_unitario,
                        cantidad,
                        total,
                        fecha,
                        mes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    tipo["id"],
                    "" if tipo["tipo_calculo"] == "otro" else "",
                    valor_unitario,
                    cantidad,
                    total,
                    fecha_inicio,
                    mes_actual
                ))

        conn.commit()

        ingresos = cur.execute("""
            SELECT
                ingresos.*,
                tipos_ingreso.nombre AS tipo_nombre,
                tipos_ingreso.tipo_calculo
            FROM ingresos
            INNER JOIN tipos_ingreso
            ON ingresos.tipo_ingreso_id = tipos_ingreso.id
            WHERE ingresos.mes = ?
            ORDER BY tipos_ingreso.nombre
        """, (mes_actual,)).fetchall()

    conn.close()

    return render_template(
        "ingresos_mensuales.html",
        ingresos=ingresos,
        tipos=tipos,
        mes_actual=mes_actual
    )


@app.route("/gastos")
def gastos():

    conn = get_connection()
    cur = conn.cursor()

    mes_actual = format_mes_label(datetime.now())

    gastos = cur.execute("""
        SELECT *
        FROM gastos
        WHERE mes = ?
        ORDER BY fecha DESC
    """, (mes_actual,)).fetchall()

    total_gastos = sum(g["valor"] for g in gastos)

    conn.close()

    return render_template(
        "gastos.html",
        gastos=gastos,
        mes_actual=mes_actual,
        total_gastos=total_gastos
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

    return redirect("/ingresos_mensuales")


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

    # Calcular mes a partir de la fecha proporcionada
    try:
        fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
        mes = format_mes_label(fecha_obj)
    except Exception:
        mes = format_mes_label(datetime.now())

    fecha_obj = datetime.strptime(
        fecha,
        "%Y-%m-%d"
    )

    mes = format_mes_label(fecha_obj)

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

    return redirect("/gastos")


# ==================================================
# ACTUALIZAR INGRESOS MENSUALES

@app.route("/actualizar_ingreso_mensual", methods=["POST"])
def actualizar_ingreso_mensual():

    ingreso_id = request.form["ingreso_id"]
    tipo_calculo = request.form["tipo_calculo"]
    concepto_otro = request.form.get("concepto_otro", "")
    valor_manual = float(request.form.get("valor_manual", 0) or 0)
    valor_unitario = float(request.form.get("valor_unitario", 0) or 0)
    cantidad = int(request.form.get("cantidad", 1) or 1)

    if tipo_calculo == "salario":
        valor_unitario = valor_manual
        total = valor_manual * 0.92
    elif tipo_calculo == "toques":
        total = valor_unitario * cantidad
    else:
        valor_unitario = valor_manual
        total = valor_manual

    mes_actual = format_mes_label(datetime.now())
    fecha_inicio = datetime.now().replace(day=1).strftime("%Y-%m-%d")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE ingresos
        SET concepto_otro = ?,
            valor_unitario = ?,
            cantidad = ?,
            total = ?,
            fecha = ?,
            mes = ?
        WHERE id = ?
    """, (
        concepto_otro,
        valor_unitario,
        cantidad,
        total,
        fecha_inicio,
        mes_actual,
        ingreso_id
    ))

    conn.commit()
    conn.close()

    return redirect("/ingresos_mensuales")


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

            fecha,

            mes

        )
        VALUES (?, ?, ?, ?, ?, ?, ?)

    """, (

        tipo_id,

        concepto_otro,

        valor_unitario,

        cantidad,

        total,

        fecha,

        mes
    ))

    conn.commit()
    conn.close()

    return redirect("/ingresos_mensuales")


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