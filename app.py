from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import datetime, timedelta
import os
from urllib.parse import quote

app = Flask(__name__)

DB_DEFAULT = "gastos.db"
DB = os.environ.get("DATABASE_PATH", DB_DEFAULT)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_neon_connection():
    if not DATABASE_URL:
        return None
    try:
        import pg8000
        import ssl
        from urllib.parse import urlparse
        result = urlparse(DATABASE_URL)
        ssl_context = ssl.create_default_context()
        return pg8000.connect(
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port or 5432,
            database=result.path[1:],
            ssl_context=ssl_context
        )
    except Exception as e:
        print(f"Error connecting to Neon PostgreSQL: {e}")
        return None

def pull_db_from_neon():
    if not DATABASE_URL:
        return
    conn = get_neon_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS sqlite_sync (id INT PRIMARY KEY, db_file BYTEA, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.commit()
        
        cur.execute("SELECT db_file FROM sqlite_sync WHERE id = 1")
        row = cur.fetchone()
        if row and row[0]:
            with open(DB, "wb") as f:
                f.write(row[0])
            print("Base de datos SQLite sincronizada desde Neon PostgreSQL.")
        else:
            print("No se encontro base de datos en Neon. Subiendo base de datos local inicial.")
            push_db_to_neon()
    except Exception as e:
        print(f"Error al jalar la BD desde Neon: {e}")
    finally:
        conn.close()

def push_db_to_neon():
    if not DATABASE_URL:
        return
    if not os.path.exists(DB):
        return
    conn = get_neon_connection()
    if not conn:
        return
    try:
        with open(DB, "rb") as f:
            db_data = f.read()
        
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS sqlite_sync (id INT PRIMARY KEY, db_file BYTEA, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("""
            INSERT INTO sqlite_sync (id, db_file, updated_at)
            VALUES (1, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET db_file = EXCLUDED.db_file, updated_at = CURRENT_TIMESTAMP
        """, (db_data,))
        conn.commit()
        print("Base de datos SQLite subida exitosamente a Neon PostgreSQL.")
    except Exception as e:
        print(f"Error al subir la BD a Neon: {e}")
    finally:
        conn.close()


# Si estamos usando un disco persistente y la BD no existe allí todavía,
# copiamos la base de datos local inicial para no perder los datos.
if DB != DB_DEFAULT and not os.path.exists(DB):
    import shutil
    db_dir = os.path.dirname(DB)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    if os.path.exists(DB_DEFAULT):
        shutil.copy2(DB_DEFAULT, DB)

# Sincronizar desde Neon al iniciar
pull_db_from_neon()


SALARIO_MINIMO_2026 = 1750905
AUXILIO_TRANSPORTE_2026 = 249095
TOPE_AUXILIO_TRANSPORTE = SALARIO_MINIMO_2026 * 2


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

        valor_unitario REAL DEFAULT 0,

        porcentaje_deduccion REAL DEFAULT 8,

        deduccion_sobre_auxilio INTEGER DEFAULT 0,

        auxilio_transporte_valor REAL DEFAULT 249095,

        recibe_auxilio_transporte INTEGER DEFAULT 0
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

        auxilio_transporte REAL DEFAULT 0,

        cantidad INTEGER,

        total REAL,

        fecha TEXT,

        mes TEXT,

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

    existing_columns = [row[1] for row in cur.execute("PRAGMA table_info(ingresos)")]
    if "mes" not in existing_columns:
        cur.execute("ALTER TABLE ingresos ADD COLUMN mes TEXT")
    if "auxilio_transporte" not in existing_columns:
        cur.execute("ALTER TABLE ingresos ADD COLUMN auxilio_transporte REAL DEFAULT 0")

    tipo_columns = [row[1] for row in cur.execute("PRAGMA table_info(tipos_ingreso)")]
    if "porcentaje_deduccion" not in tipo_columns:
        cur.execute("ALTER TABLE tipos_ingreso ADD COLUMN porcentaje_deduccion REAL DEFAULT 8")
    if "deduccion_sobre_auxilio" not in tipo_columns:
        cur.execute("ALTER TABLE tipos_ingreso ADD COLUMN deduccion_sobre_auxilio INTEGER DEFAULT 0")
    if "auxilio_transporte_valor" not in tipo_columns:
        cur.execute(f"ALTER TABLE tipos_ingreso ADD COLUMN auxilio_transporte_valor REAL DEFAULT {AUXILIO_TRANSPORTE_2026}")
    added_recibe_auxilio = "recibe_auxilio_transporte" not in tipo_columns
    if added_recibe_auxilio:
        cur.execute("ALTER TABLE tipos_ingreso ADD COLUMN recibe_auxilio_transporte INTEGER DEFAULT 0")

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
    # INSERTAR MAESTRAS DEFAULT
    # ==================================================

    tipos = [

        ("SALARIO CRIS", 1, "salario", 0, 8, 0, AUXILIO_TRANSPORTE_2026, 0),

        ("SALARIO ELI", 1, "salario", 0, 8, 0, AUXILIO_TRANSPORTE_2026, 1),

        ("TOQUES", 0, "toques", 350000, 0, 0, AUXILIO_TRANSPORTE_2026, 0),

        ("OTRO INGRESO", 0, "otro", 0, 0, 0, AUXILIO_TRANSPORTE_2026, 0)
    ]

    for tipo in tipos:

        cur.execute("""
        INSERT OR IGNORE INTO tipos_ingreso
        (
            nombre,
            aplica_deduccion,
            tipo_calculo,
            valor_unitario,
            porcentaje_deduccion,
            deduccion_sobre_auxilio,
            auxilio_transporte_valor,
            recibe_auxilio_transporte
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, tipo)

    cur.execute("""
        UPDATE tipos_ingreso
        SET porcentaje_deduccion = COALESCE(porcentaje_deduccion, 8),
            deduccion_sobre_auxilio = COALESCE(deduccion_sobre_auxilio, 0),
            auxilio_transporte_valor = COALESCE(auxilio_transporte_valor, ?),
            recibe_auxilio_transporte = COALESCE(recibe_auxilio_transporte, 0)
        WHERE tipo_calculo = 'salario'
    """, (AUXILIO_TRANSPORTE_2026,))

    cur.execute("""
        UPDATE tipos_ingreso
        SET porcentaje_deduccion = COALESCE(porcentaje_deduccion, 0),
            deduccion_sobre_auxilio = 0,
            auxilio_transporte_valor = COALESCE(auxilio_transporte_valor, ?),
            recibe_auxilio_transporte = 0
        WHERE tipo_calculo != 'salario'
    """, (AUXILIO_TRANSPORTE_2026,))

    if added_recibe_auxilio:
        cur.execute("""
            UPDATE tipos_ingreso
            SET recibe_auxilio_transporte = 1
            WHERE nombre = 'SALARIO ELI'
        """)

    recalcular_ingresos_salario(cur)

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

MONTH_ABBR = {
    1: "ENE",
    2: "FEB",
    3: "MAR",
    4: "ABR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AGO",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DIC",
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

def format_fecha_corta(date_obj):
    return f"{str(date_obj.day).zfill(2)}-{MONTH_ABBR[date_obj.month].upper()}-{date_obj.year}"

def format_pesos_colombianos(valor):
    return f"${valor:,.0f}".replace(",", ".")

def format_pesos_colombianos_decimal(valor):
    return f"${valor:,.2f}".replace(",", ".")


def get_float_form(name, default=0):
    return float(request.form.get(name, default) or default)


def get_int_form(name, default=1):
    return int(request.form.get(name, default) or default)


def tipo_recibe_auxilio_transporte(tipo):
    return (
        "recibe_auxilio_transporte" in tipo.keys()
        and tipo["recibe_auxilio_transporte"]
    )


def calcular_auxilio_transporte(tipo, salario_base):
    if not tipo_recibe_auxilio_transporte(tipo):
        return 0
    if salario_base > TOPE_AUXILIO_TRANSPORTE:
        return 0
    if "auxilio_transporte_valor" in tipo.keys():
        return tipo["auxilio_transporte_valor"] or 0
    return AUXILIO_TRANSPORTE_2026


def calcular_total_salario(tipo, salario_base):
    porcentaje = tipo["porcentaje_deduccion"] if "porcentaje_deduccion" in tipo.keys() else 8
    porcentaje = porcentaje or 0
    auxilio_transporte = calcular_auxilio_transporte(tipo, salario_base)
    base_deduccion = salario_base
    if "deduccion_sobre_auxilio" in tipo.keys() and tipo["deduccion_sobre_auxilio"]:
        base_deduccion += auxilio_transporte
    descuento = base_deduccion * (porcentaje / 100)
    return salario_base + auxilio_transporte - descuento


def calcular_salario_quincenal(tipo, salario_base):
    return calcular_total_salario(tipo, salario_base) / 2


def completar_ingreso_calculado(ingreso):
    ingreso_dict = dict(ingreso)
    if ingreso_dict["tipo_calculo"] == "salario":
        ingreso_dict["salario_quincenal"] = ingreso_dict["total"] / 2
    else:
        ingreso_dict["salario_quincenal"] = None
    return ingreso_dict


def recalcular_ingresos_salario(cur, tipo_id=None):
    params = []
    filtro_tipo = ""
    if tipo_id:
        filtro_tipo = " AND tipos_ingreso.id = ?"
        params.append(tipo_id)

    salarios_guardados = cur.execute(f"""
        SELECT
            ingresos.id,
            ingresos.valor_unitario AS salario_base,
            tipos_ingreso.*
        FROM ingresos
        INNER JOIN tipos_ingreso
        ON ingresos.tipo_ingreso_id = tipos_ingreso.id
        WHERE tipos_ingreso.tipo_calculo = 'salario'
        {filtro_tipo}
    """, params).fetchall()

    for salario in salarios_guardados:
        salario_base = salario["salario_base"] or 0
        auxilio_transporte = calcular_auxilio_transporte(salario, salario_base)
        total = calcular_total_salario(salario, salario_base)
        cur.execute("""
            UPDATE ingresos
            SET auxilio_transporte = ?,
                total = ?
            WHERE id = ?
        """, (auxilio_transporte, total, salario["id"]))


def get_previous_month_label(mes_label):
    current = parse_mes_label(mes_label)
    if not current:
        return None

    prev = (current.replace(day=1) - timedelta(days=1)).replace(day=1)
    return format_mes_label(prev)


def build_available_meses(cur, default_mes, extra_mes=None):
    available_meses = set()
    for row in cur.execute("SELECT mes FROM gastos").fetchall():
        if row["mes"]:
            available_meses.add(row["mes"].strip())
    for row in cur.execute("SELECT mes FROM ingresos").fetchall():
        if row["mes"]:
            available_meses.add(row["mes"].strip())
    available_meses.add(default_mes)
    if extra_mes:
        available_meses.add(extra_mes)

    return sorted(
        [m for m in available_meses if parse_mes_label(m)],
        key=lambda m: parse_mes_label(m),
        reverse=True
    )


def get_redirect_mes(default_mes=None):
    mes = request.form.get("redirect_mes") or default_mes or format_mes_label(datetime.now())
    if not parse_mes_label(mes):
        mes = format_mes_label(datetime.now())
    return mes


def redirect_ingresos_mensuales(mes):
    return redirect(f"/ingresos_mensuales?mes={quote(mes)}")


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

    formatted_months = build_available_meses(cur, default_mes)

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
def maestras():

    conn = get_connection()
    cur = conn.cursor()

    tipos = cur.execute("""
        SELECT *
        FROM tipos_ingreso
        ORDER BY nombre
    """).fetchall()

    conn.close()

    return render_template("maestras.html", tipos=tipos)


@app.route("/ingresos_mensuales")
def ingresos_mensuales():

    conn = get_connection()
    cur = conn.cursor()

    requested_mes = request.args.get("mes")
    default_mes = format_mes_label(datetime.now())
    mes_actual = requested_mes or default_mes
    if not parse_mes_label(mes_actual):
        mes_actual = default_mes

    fecha_inicio = parse_mes_label(mes_actual).strftime("%Y-%m-%d")
    available_meses = build_available_meses(cur, default_mes, mes_actual)

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
    ingresos = [completar_ingreso_calculado(ingreso) for ingreso in ingresos]

    conn.close()

    return render_template(
        "ingresos_mensuales.html",
        ingresos=ingresos,
        tipos=tipos,
        mes_actual=mes_actual,
        available_meses=available_meses,
        fecha_inicio=fecha_inicio
    )


@app.route("/gastos")
def gastos():

    conn = get_connection()
    cur = conn.cursor()

    requested_mes = request.args.get("mes")
    default_mes = format_mes_label(datetime.now())
    mes_actual = requested_mes or default_mes
    if not parse_mes_label(mes_actual):
        mes_actual = default_mes

    available_meses = build_available_meses(cur, default_mes, mes_actual)
    fecha_inicio = parse_mes_label(mes_actual).strftime("%Y-%m-%d")

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
        available_meses=available_meses,
        fecha_inicio=fecha_inicio,
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
    porcentaje_deduccion = float(
        request.form.get("porcentaje_deduccion", 0) or 0
    )
    deduccion_sobre_auxilio = 1 if request.form.get("deduccion_sobre_auxilio") else 0
    auxilio_transporte_valor = float(
        request.form.get("auxilio_transporte_valor", AUXILIO_TRANSPORTE_2026) or 0
    )
    recibe_auxilio_transporte = 1 if request.form.get("recibe_auxilio_transporte") else 0

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tipos_ingreso
        SET valor_unitario = ?,
            porcentaje_deduccion = ?,
            deduccion_sobre_auxilio = ?,
            auxilio_transporte_valor = ?,
            recibe_auxilio_transporte = ?
        WHERE id = ?
    """, (
        valor_unitario,
        porcentaje_deduccion,
        deduccion_sobre_auxilio,
        auxilio_transporte_valor,
        recibe_auxilio_transporte,
        tipo_id
    ))

    recalcular_ingresos_salario(cur, tipo_id)

    conn.commit()
    conn.close()

    return redirect("/maestras")


@app.route("/actualizar_gasto", methods=["POST"])
def actualizar_gasto():

    gasto_id = request.form["gasto_id"]
    concepto = request.form["concepto"]
    valor = float(request.form["valor"])
    fecha = request.form["fecha"]
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
    mes = format_mes_label(fecha_obj)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE gastos
        SET concepto = ?,
            valor = ?,
            fecha = ?,
            mes = ?
        WHERE id = ?
    """, (
        concepto,
        valor,
        fecha,
        mes,
        gasto_id
    ))

    conn.commit()
    conn.close()

    return redirect(f"/gastos?mes={quote(mes)}")


@app.route("/borrar_gasto", methods=["POST"])
def borrar_gasto():

    gasto_id = request.form["gasto_id"]
    mes = get_redirect_mes()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM gastos WHERE id = ?", (gasto_id,))

    conn.commit()
    conn.close()

    return redirect(f"/gastos?mes={quote(mes)}")


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

    return redirect(f"/gastos?mes={quote(mes)}")


# ==================================================
# ACTUALIZAR INGRESOS MENSUALES

@app.route("/actualizar_ingreso_mensual", methods=["POST"])
def actualizar_ingreso_mensual():

    ingreso_id = request.form["ingreso_id"]
    tipo_calculo = request.form["tipo_calculo"]
    concepto_otro = request.form.get("concepto_otro", "")
    valor_manual = get_float_form("valor_manual")
    valor_unitario = get_float_form("valor_unitario")
    cantidad = get_int_form("cantidad")
    fecha = request.form["fecha"]

    conn = get_connection()
    cur = conn.cursor()

    tipo = cur.execute("""
        SELECT tipos_ingreso.*
        FROM ingresos
        INNER JOIN tipos_ingreso
        ON ingresos.tipo_ingreso_id = tipos_ingreso.id
        WHERE ingresos.id = ?
    """, (ingreso_id,)).fetchone()

    if tipo_calculo == "salario":
        valor_unitario = valor_manual
        auxilio_transporte = calcular_auxilio_transporte(tipo, valor_manual)
        total = calcular_total_salario(tipo, valor_manual)
    elif tipo_calculo == "toques":
        auxilio_transporte = 0
        total = valor_unitario * cantidad
    else:
        auxilio_transporte = 0
        valor_unitario = valor_manual
        total = valor_manual

    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
    mes = format_mes_label(fecha_obj)

    cur.execute("""
        UPDATE ingresos
        SET concepto_otro = ?,
            valor_unitario = ?,
            auxilio_transporte = ?,
            cantidad = ?,
            total = ?,
            fecha = ?,
            mes = ?
        WHERE id = ?
    """, (
        concepto_otro,
        valor_unitario,
        auxilio_transporte,
        cantidad,
        total,
        fecha,
        mes,
        ingreso_id
    ))

    conn.commit()
    conn.close()

    return redirect_ingresos_mensuales(mes)


@app.route("/borrar_ingreso", methods=["POST"])
def borrar_ingreso():

    ingreso_id = request.form["ingreso_id"]
    mes = get_redirect_mes()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM ingresos WHERE id = ?", (ingreso_id,))

    conn.commit()
    conn.close()

    return redirect_ingresos_mensuales(mes)


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

    # Calcular mes a partir de la fecha
    mes = format_mes_label(datetime.strptime(fecha, "%Y-%m-%d"))

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

        auxilio_transporte = calcular_auxilio_transporte(tipo, valor_manual)

        total = calcular_total_salario(tipo, valor_manual)

    # ==================================================
    # TOQUES
    # ==================================================

    elif tipo["tipo_calculo"] == "toques":

        auxilio_transporte = 0

        valor_unitario = tipo["valor_unitario"]

        total = valor_unitario * cantidad

    # ==================================================
    # OTROS INGRESOS
    # ==================================================

    elif tipo["tipo_calculo"] == "otro":

        auxilio_transporte = 0

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

            auxilio_transporte,

            cantidad,

            total,

            fecha,

            mes

        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)

    """, (

        tipo_id,

        concepto_otro,

        valor_unitario,

        auxilio_transporte,

        cantidad,

        total,

        fecha,

        mes
    ))

    conn.commit()
    conn.close()

    return redirect_ingresos_mensuales(mes)


# ==================================================
# ANÁLISIS COMPARATIVO DE MESES
# ==================================================

@app.route("/analisis")
def analisis():

    conn = get_connection()
    cur = conn.cursor()

    # Obtener lista de meses disponibles
    all_meses_ingresos = cur.execute("SELECT DISTINCT mes FROM ingresos WHERE mes IS NOT NULL ORDER BY mes DESC").fetchall()
    all_meses_gastos = cur.execute("SELECT DISTINCT mes FROM gastos WHERE mes IS NOT NULL ORDER BY mes DESC").fetchall()
    
    all_meses_set = set()
    for row in all_meses_ingresos:
        if row["mes"]:
            all_meses_set.add(row["mes"])
    for row in all_meses_gastos:
        if row["mes"]:
            all_meses_set.add(row["mes"])
    
    all_meses = sorted(
        [m for m in all_meses_set if parse_mes_label(m)],
        key=lambda m: parse_mes_label(m),
        reverse=True
    )

    # Parámetros de filtro
    meses_seleccionados = request.args.getlist("meses")
    if not meses_seleccionados:
        meses_seleccionados = all_meses[:3] if len(all_meses) >= 3 else all_meses

    # Recopilar datos para cada mes
    datos_meses = []
    for mes in meses_seleccionados:
        ingresos_total = cur.execute("SELECT SUM(total) as total FROM ingresos WHERE mes = ?", (mes,)).fetchone()
        gastos_total = cur.execute("SELECT SUM(valor) as total FROM gastos WHERE mes = ?", (mes,)).fetchone()
        
        ingresos_val = ingresos_total["total"] or 0
        gastos_val = gastos_total["total"] or 0
        balance_val = ingresos_val - gastos_val
        
        datos_meses.append({
            "mes": mes,
            "ingresos": ingresos_val,
            "gastos": gastos_val,
            "balance": balance_val
        })

    conn.close()

    return render_template(
        "analisis.html",
        all_meses=all_meses,
        meses_seleccionados=meses_seleccionados,
        datos_meses=datos_meses
    )


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
# REGISTRO DE FILTROS JINJA2
# ==================================================

def format_fecha_filtro(value):
    if not value:
        return ''
    try:
        fecha_obj = datetime.strptime(value, "%Y-%m-%d")
        return format_fecha_corta(fecha_obj)
    except:
        return value

app.jinja_env.filters['fecha_corta'] = format_fecha_filtro
app.jinja_env.filters['pesos'] = format_pesos_colombianos
app.jinja_env.filters['pesos_decimal'] = format_pesos_colombianos_decimal


# ==================================================
# INIT DB
# ==================================================





# ==================================================
# INIT DB
# ==================================================

init_db()


# ==================================================
# CORS & API ENDPOINTS FOR GITHUB PAGES SYNC
# ==================================================

@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        response.headers.update({
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, PUT, DELETE',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        })
        return response

@app.after_request
def add_cors_headers(response):
    response.headers.update({
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, PUT, DELETE',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    })
    return response

@app.route("/api/db", methods=["GET"])
def get_db_file():
    from flask import send_file
    pull_db_from_neon()  # Asegurar que jalamos la última versión desde Neon
    if not os.path.exists(DB):
        return {"error": "Database not found"}, 404
    return send_file(DB, mimetype="application/x-sqlite3", as_attachment=True, download_name="gastos.db")

@app.route("/api/db", methods=["POST"])
def save_db_file():
    if 'file' not in request.files:
        return {"error": "No file part"}, 400
    file = request.files['file']
    if file.filename == '':
        return {"error": "No selected file"}, 400
    
    file.save(DB)
    push_db_to_neon()  # Subir la base de datos actualizada a Neon
    return {"status": "success", "message": "Database updated successfully"}

@app.route("/api/status", methods=["GET"])
def get_status():
    status_info = {
        "database_url_configured": DATABASE_URL is not None and len(DATABASE_URL) > 0,
        "local_db_exists": os.path.exists(DB),
        "db_path": DB
    }
    
    if DATABASE_URL:
        try:
            import pg8000
            import ssl
            from urllib.parse import urlparse
            result = urlparse(DATABASE_URL)
            ssl_context = ssl.create_default_context()
            conn = pg8000.connect(
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port or 5432,
                database=result.path[1:],
                ssl_context=ssl_context
            )
            cur = conn.cursor()
            cur.execute("SELECT * FROM information_schema.tables WHERE table_name = 'sqlite_sync'")
            exists = cur.fetchone() is not None
            status_info["neon_connection"] = "success"
            status_info["sqlite_sync_table_exists"] = exists
            if exists:
                cur.execute("SELECT id, updated_at, octet_length(db_file) FROM sqlite_sync")
                row = cur.fetchone()
                status_info["sqlite_sync_row"] = str(row) if row else "no row"
            conn.close()
        except Exception as e:
            status_info["neon_connection"] = f"failed: {str(e)}"
    else:
        status_info["neon_connection"] = "not configured"
        
    return status_info


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
