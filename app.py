from flask import Flask, render_template, request, redirect
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import os
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

SALARIO_MINIMO_2026 = 1750905
AUXILIO_TRANSPORTE_2026 = 249095
TOPE_AUXILIO_TRANSPORTE = SALARIO_MINIMO_2026 * 2

 
#s ==================================================
# CONEXIÓN DB
# ==================================================

def get_connection():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL no está configurada.")
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
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
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
        tipo_ingreso_id INTEGER REFERENCES tipos_ingreso(id),
        concepto_otro TEXT,
        valor_unitario REAL,
        auxilio_transporte REAL DEFAULT 0,
        cantidad INTEGER,
        total REAL,
        fecha DATE,
        mes TEXT
    )
    """)

    # ==================================================
    # TABLA GASTOS
    # ==================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS gastos (
        id SERIAL PRIMARY KEY,
        concepto TEXT NOT NULL,
        valor REAL NOT NULL,
        fecha DATE NOT NULL,
        mes TEXT NOT NULL
    )
    """)

    # Simple migration checks, not as complex as before
    # The following alter statements might fail if the columns already exist,
    # but that's okay in this simplified setup.
    try:
        cur.execute("ALTER TABLE ingresos ADD COLUMN mes TEXT")
    except psycopg2.errors.DuplicateColumn:
        conn.rollback() # Rollback the failed transaction
    try:
        cur.execute("ALTER TABLE ingresos ADD COLUMN auxilio_transporte REAL DEFAULT 0")
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()

    try:
        cur.execute("ALTER TABLE tipos_ingreso ADD COLUMN porcentaje_deduccion REAL DEFAULT 8")
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()
    try:
        cur.execute("ALTER TABLE tipos_ingreso ADD COLUMN deduccion_sobre_auxilio INTEGER DEFAULT 0")
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()
    try:
        cur.execute(f"ALTER TABLE tipos_ingreso ADD COLUMN auxilio_transporte_valor REAL DEFAULT {AUXILIO_TRANSPORTE_2026}")
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()
    try:
        cur.execute("ALTER TABLE tipos_ingreso ADD COLUMN recibe_auxilio_transporte INTEGER DEFAULT 0")
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()

    conn.commit() # Commit table creations and alterations

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
        INSERT INTO tipos_ingreso
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
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (nombre) DO NOTHING
        """, tipo)
    conn.commit()

    cur.execute("""
        UPDATE tipos_ingreso
        SET porcentaje_deduccion = COALESCE(porcentaje_deduccion, 8),
            deduccion_sobre_auxilio = COALESCE(deduccion_sobre_auxilio, 0),
            auxilio_transporte_valor = COALESCE(auxilio_transporte_valor, %s),
            recibe_auxilio_transporte = COALESCE(recibe_auxilio_transporte, 0)
        WHERE tipo_calculo = 'salario'
    """, (AUXILIO_TRANSPORTE_2026,))

    cur.execute("""
        UPDATE tipos_ingreso
        SET porcentaje_deduccion = COALESCE(porcentaje_deduccion, 0),
            deduccion_sobre_auxilio = 0,
            auxilio_transporte_valor = COALESCE(auxilio_transporte_valor, %s),
            recibe_auxilio_transporte = 0
        WHERE tipo_calculo != 'salario'
    """, (AUXILIO_TRANSPORTE_2026,))

    # This logic may need to be smarter if run multiple times
    cur.execute("""
        UPDATE tipos_ingreso
        SET recibe_auxilio_transporte = 1
        WHERE nombre = 'SALARIO ELI'
    """)
    
    conn.commit()

    recalcular_ingresos_salario(cur, conn)

    cur.close()
    conn.close()

SPANISH_MONTHS = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
MONTH_NAMES = {v: k for k, v in SPANISH_MONTHS.items()}
MONTH_ABBR = {
    1: "ENE", 2: "FEB", 3: "MAR", 4: "ABR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AGO", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DIC",
}

def parse_mes_label(mes_label):
    if not mes_label: return None
    try:
        name, year = mes_label.strip().upper().split()
        month = SPANISH_MONTHS.get(name)
        if not month: return None
        return datetime(int(year), month, 1)
    except (ValueError, KeyError):
        return None

def format_mes_label(date_obj):
    return f"{MONTH_NAMES[date_obj.month]} {date_obj.year}"

def format_fecha_corta(date_obj):
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.strptime(date_obj, "%Y-%m-%d")
        except (ValueError, TypeError):
            return date_obj # Return original string if parsing fails
    if not isinstance(date_obj, datetime):
        return date_obj

    return f"{str(date_obj.day).zfill(2)}-{MONTH_ABBR[date_obj.month].upper()}-{date_obj.year}"

def format_pesos_colombianos(valor):
    if valor is None: return "$0"
    return f"${valor:,.0f}".replace(",", ".")

def format_pesos_colombianos_decimal(valor):
    if valor is None: return "$0.00"
    return f"${valor:,.2f}".replace(",", ".")

def get_float_form(name, default=0):
    return float(request.form.get(name, default) or default)

def get_int_form(name, default=1):
    return int(request.form.get(name, default) or default)

def tipo_recibe_auxilio_transporte(tipo):
    return tipo.get("recibe_auxilio_transporte", 0) == 1

def calcular_auxilio_transporte(tipo, salario_base):
    if not tipo_recibe_auxilio_transporte(tipo) or salario_base > TOPE_AUXILIO_TRANSPORTE:
        return 0
    return tipo.get("auxilio_transporte_valor", AUXILIO_TRANSPORTE_2026) or 0

def calcular_total_salario(tipo, salario_base):
    porcentaje = tipo.get("porcentaje_deduccion", 8) or 0
    auxilio_transporte = calcular_auxilio_transporte(tipo, salario_base)
    base_deduccion = salario_base
    if tipo.get("deduccion_sobre_auxilio", 0) == 1:
        base_deduccion += auxilio_transporte
    descuento = base_deduccion * (porcentaje / 100)
    return salario_base + auxilio_transporte - descuento

def completar_ingreso_calculado(ingreso):
    if ingreso["tipo_calculo"] == "salario":
        ingreso["salario_quincenal"] = ingreso["total"] / 2 if ingreso["total"] else 0
    else:
        ingreso["salario_quincenal"] = None
    return ingreso

def recalcular_ingresos_salario(cur, conn, tipo_id=None):
    params = []
    filtro_tipo = ""
    if tipo_id:
        filtro_tipo = " AND tipos_ingreso.id = %s"
        params.append(tipo_id)

    cur.execute(f"""
        SELECT ingresos.id, ingresos.valor_unitario AS salario_base, tipos_ingreso.*
        FROM ingresos
        JOIN tipos_ingreso ON ingresos.tipo_ingreso_id = tipos_ingreso.id
        WHERE tipos_ingreso.tipo_calculo = 'salario' {filtro_tipo}
    """, params)
    salarios_guardados = cur.fetchall()

    for salario in salarios_guardados:
        salario_base = salario["salario_base"] or 0
        auxilio_transporte = calcular_auxilio_transporte(salario, salario_base)
        total = calcular_total_salario(salario, salario_base)
        cur.execute("""
            UPDATE ingresos SET auxilio_transporte = %s, total = %s WHERE id = %s
        """, (auxilio_transporte, total, salario["id"]))
    conn.commit()


def get_previous_month_label(mes_label):
    current = parse_mes_label(mes_label)
    if not current: return None
    prev = (current.replace(day=1) - timedelta(days=1)).replace(day=1)
    return format_mes_label(prev)

def build_available_meses(cur, default_mes, extra_mes=None):
    cur.execute("SELECT DISTINCT mes FROM gastos WHERE mes IS NOT NULL")
    gastos_meses = {row["mes"].strip() for row in cur.fetchall()}
    cur.execute("SELECT DISTINCT mes FROM ingresos WHERE mes IS NOT NULL")
    ingresos_meses = {row["mes"].strip() for row in cur.fetchall()}
    
    available_meses = gastos_meses.union(ingresos_meses)
    available_meses.add(default_mes)
    if extra_mes: available_meses.add(extra_mes)

    return sorted([m for m in available_meses if parse_mes_label(m)], key=parse_mes_label, reverse=True)

def get_redirect_mes(default_mes=None):
    mes = request.form.get("redirect_mes") or default_mes or format_mes_label(datetime.now())
    return mes if parse_mes_label(mes) else format_mes_label(datetime.now())

def redirect_ingresos_mensuales(mes):
    return redirect(f"/ingresos_mensuales?mes={quote(mes)}")

@app.route("/")
def index():
    conn = get_connection()
    cur = conn.cursor()
    default_mes = format_mes_label(datetime.now())
    mes_actual = request.args.get("mes") or default_mes
    if not parse_mes_label(mes_actual): mes_actual = default_mes

    formatted_months = build_available_meses(cur, default_mes)
    mes_anterior = get_previous_month_label(mes_actual)

    cur.execute("SELECT * FROM gastos WHERE mes = %s ORDER BY fecha DESC", (mes_actual,))
    gastos = cur.fetchall()
    cur.execute("""
        SELECT i.*, ti.nombre AS tipo_nombre, ti.tipo_calculo
        FROM ingresos i JOIN tipos_ingreso ti ON i.tipo_ingreso_id = ti.id
        WHERE i.mes = %s ORDER BY fecha DESC
    """, (mes_actual,))
    ingresos = cur.fetchall()

    total_gastos = sum(g["valor"] for g in gastos)
    total_ingresos = sum(i["total"] for i in ingresos)
    balance = total_ingresos - total_gastos

    prev_ingresos = 0
    prev_gastos = 0
    if mes_anterior:
        cur.execute("SELECT COALESCE(SUM(total), 0) AS ingresos FROM ingresos WHERE mes = %s", (mes_anterior,))
        prev_ingresos = cur.fetchone()["ingresos"]
        cur.execute("SELECT COALESCE(SUM(valor), 0) AS gastos FROM gastos WHERE mes = %s", (mes_anterior,))
        prev_gastos = cur.fetchone()["gastos"]

    prev_balance = prev_ingresos - prev_gastos
    balance_diff = balance - prev_balance
    
    comparacion_text = "No hay comparación con mes anterior disponible."
    if mes_anterior:
        if balance_diff > 0:
            comparacion_text = f"Mejor que {mes_anterior}: +{format_pesos_colombianos(balance_diff)}"
        elif balance_diff < 0:
            comparacion_text = f"Peor que {mes_anterior}: -{format_pesos_colombianos(abs(balance_diff))}"
        else:
            comparacion_text = f"Igual al mes anterior {mes_anterior}."

    cur.execute("""
        SELECT fecha, SUM(valor) AS total
        FROM gastos
        WHERE mes = %s
        GROUP BY fecha
        ORDER BY fecha ASC
    """, (mes_actual,))
    gastos_por_dia_rows = cur.fetchall()

    gastos_por_dia = []
    max_total = max((row["total"] for row in gastos_por_dia_rows), default=0)
    for row in gastos_por_dia_rows:
        fecha_obj = row['fecha']
        day_label = fecha_obj.strftime("%d")
        altura = int((row["total"] / max_total) * 120) if max_total > 0 else 10
        gastos_por_dia.append({
            "day": day_label,
            "total": row["total"],
            "height": altura
        })

    mayor_dia_gasto = max(gastos_por_dia, key=lambda item: item["total"]) if gastos_por_dia else None
    gasto_promedio = total_gastos / len(gastos_por_dia) if gastos_por_dia else 0

    cur.execute("SELECT * FROM tipos_ingreso ORDER BY nombre")
    tipos_ingreso = cur.fetchall()

    cur.close()
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

@app.route("/maestras")
def maestras():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tipos_ingreso ORDER BY nombre")
    tipos = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("maestras.html", tipos=tipos)

@app.route("/ingresos_mensuales")
def ingresos_mensuales():
    conn = get_connection()
    cur = conn.cursor()
    default_mes = format_mes_label(datetime.now())
    mes_actual = request.args.get("mes") or default_mes
    if not parse_mes_label(mes_actual): mes_actual = default_mes

    fecha_inicio = parse_mes_label(mes_actual).strftime("%Y-%m-%d")
    available_meses = build_available_meses(cur, default_mes, mes_actual)
    
    cur.execute("SELECT * FROM tipos_ingreso ORDER BY nombre")
    tipos = cur.fetchall()
    cur.execute("""
        SELECT i.*, ti.nombre AS tipo_nombre, ti.tipo_calculo
        FROM ingresos i JOIN tipos_ingreso ti ON i.tipo_ingreso_id = ti.id
        WHERE i.mes = %s ORDER BY ti.nombre
    """, (mes_actual,))
    ingresos = [completar_ingreso_calculado(ingreso) for ingreso in cur.fetchall()]

    cur.close()
    conn.close()
    return render_template("ingresos_mensuales.html", ingresos=ingresos, tipos=tipos, mes_actual=mes_actual, available_meses=available_meses, fecha_inicio=fecha_inicio)

@app.route("/gastos")
def gastos_view():
    conn = get_connection()
    cur = conn.cursor()
    default_mes = format_mes_label(datetime.now())
    mes_actual = request.args.get("mes") or default_mes
    if not parse_mes_label(mes_actual): mes_actual = default_mes

    available_meses = build_available_meses(cur, default_mes, mes_actual)
    fecha_inicio = parse_mes_label(mes_actual).strftime("%Y-%m-%d")

    cur.execute("SELECT * FROM gastos WHERE mes = %s ORDER BY fecha DESC", (mes_actual,))
    gastos_data = cur.fetchall()
    total_gastos = sum(g["valor"] for g in gastos_data)

    cur.close()
    conn.close()
    return render_template("gastos.html", gastos=gastos_data, mes_actual=mes_actual, available_meses=available_meses, fecha_inicio=fecha_inicio, total_gastos=total_gastos)

@app.route("/actualizar_maestra", methods=["POST"])
def actualizar_maestra():
    tipo_id = request.form["tipo_id"]
    valor_unitario = get_float_form("valor_unitario")
    porcentaje_deduccion = get_float_form("porcentaje_deduccion", 8)
    deduccion_sobre_auxilio = 1 if "deduccion_sobre_auxilio" in request.form else 0
    auxilio_transporte_valor = get_float_form("auxilio_transporte_valor", AUXILIO_TRANSPORTE_2026)
    recibe_auxilio_transporte = 1 if "recibe_auxilio_transporte" in request.form else 0
    
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE tipos_ingreso
        SET valor_unitario = %s, porcentaje_deduccion = %s, deduccion_sobre_auxilio = %s,
            auxilio_transporte_valor = %s, recibe_auxilio_transporte = %s
        WHERE id = %s
    """, (valor_unitario, porcentaje_deduccion, deduccion_sobre_auxilio, auxilio_transporte_valor, recibe_auxilio_transporte, tipo_id))
    
    recalcular_ingresos_salario(cur, conn, tipo_id)
    
    conn.commit()
    cur.close()
    conn.close()
    return redirect("/maestras")

@app.route("/guardar_gasto", methods=["POST"])
def guardar_gasto():
    concepto = request.form["concepto"]
    valor = get_float_form("valor")
    fecha = request.form["fecha"]
    mes = format_mes_label(datetime.strptime(fecha, "%Y-%m-%d"))
    
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO gastos (concepto, valor, fecha, mes) VALUES (%s, %s, %s, %s)",
                (concepto, valor, fecha, mes))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(f"/gastos?mes={quote(mes)}")

@app.route("/guardar_ingreso", methods=["POST"])
def guardar_ingreso():
    tipo_id = request.form["tipo_ingreso"]
    fecha = request.form["fecha"]
    concepto_otro = request.form.get("concepto_otro", "")
    valor_manual = get_float_form("valor_manual")
    cantidad = get_int_form("cantidad")
    mes = format_mes_label(datetime.strptime(fecha, "%Y-%m-%d"))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tipos_ingreso WHERE id = %s", (tipo_id,))
    tipo = cur.fetchone()

    valor_unitario = 0
    auxilio_transporte = 0
    
    if tipo["tipo_calculo"] == "salario":
        valor_unitario = valor_manual
        total = calcular_total_salario(tipo, valor_manual)
        auxilio_transporte = calcular_auxilio_transporte(tipo, valor_manual)
    elif tipo["tipo_calculo"] == "toques":
        valor_unitario = tipo["valor_unitario"]
        total = valor_unitario * cantidad
    else: # otro
        valor_unitario = valor_manual
        total = valor_manual

    cur.execute("""
        INSERT INTO ingresos (tipo_ingreso_id, concepto_otro, valor_unitario, auxilio_transporte, cantidad, total, fecha, mes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (tipo_id, concepto_otro, valor_unitario, auxilio_transporte, cantidad, total, fecha, mes))
    
    conn.commit()
    cur.close()
    conn.close()
    return redirect_ingresos_mensuales(mes)

@app.route("/borrar_gasto", methods=["POST"])
def borrar_gasto():
    gasto_id = request.form["gasto_id"]
    mes = get_redirect_mes()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM gastos WHERE id = %s", (gasto_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(f"/gastos?mes={quote(mes)}")

@app.route("/borrar_ingreso", methods=["POST"])
def borrar_ingreso():
    ingreso_id = request.form["ingreso_id"]
    mes = get_redirect_mes()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM ingresos WHERE id = %s", (ingreso_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect_ingresos_mensuales(mes)

@app.route("/actualizar_gasto", methods=["POST"])
def actualizar_gasto():
    gasto_id = request.form["gasto_id"]
    concepto = request.form["concepto"]
    valor = get_float_form("valor")
    fecha = request.form["fecha"]
    mes = format_mes_label(datetime.strptime(fecha, "%Y-%m-%d"))
    
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE gastos SET concepto = %s, valor = %s, fecha = %s, mes = %s WHERE id = %s
    """, (concepto, valor, fecha, mes, gasto_id))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(f"/gastos?mes={quote(mes)}")


@app.route("/actualizar_ingreso_mensual", methods=["POST"])
def actualizar_ingreso_mensual():
    ingreso_id = request.form["ingreso_id"]
    tipo_calculo = request.form["tipo_calculo"]
    concepto_otro = request.form.get("concepto_otro", "")
    valor_manual = get_float_form("valor_manual")
    valor_unitario = get_float_form("valor_unitario")
    cantidad = get_int_form("cantidad")
    fecha = request.form["fecha"]
    mes = format_mes_label(datetime.strptime(fecha, "%Y-%m-%d"))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT ti.* FROM ingresos i JOIN tipos_ingreso ti ON i.tipo_ingreso_id = ti.id WHERE i.id = %s
    """, (ingreso_id,))
    tipo = cur.fetchone()

    total = 0
    auxilio_transporte = 0
    if tipo_calculo == "salario":
        valor_unitario = valor_manual
        total = calcular_total_salario(tipo, valor_manual)
        auxilio_transporte = calcular_auxilio_transporte(tipo, valor_manual)
    elif tipo_calculo == "toques":
        auxilio_transporte = 0
        total = valor_unitario * cantidad
    else: # otro
        valor_unitario = valor_manual
        total = valor_manual
        auxilio_transporte = 0
        
    cur.execute("""
        UPDATE ingresos
        SET concepto_otro = %s, valor_unitario = %s, auxilio_transporte = %s,
            cantidad = %s, total = %s, fecha = %s, mes = %s
        WHERE id = %s
    """, (concepto_otro, valor_unitario, auxilio_transporte, cantidad, total, fecha, mes, ingreso_id))
    
    conn.commit()
    cur.close()
    conn.close()
    return redirect_ingresos_mensuales(mes)

@app.route("/analisis")
def analisis():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT mes FROM ingresos WHERE mes IS NOT NULL UNION SELECT DISTINCT mes FROM gastos WHERE mes IS NOT NULL")
    all_meses_rows = cur.fetchall()
    all_meses_set = {row['mes'] for row in all_meses_rows if row['mes']}
    all_meses = sorted([m for m in all_meses_set if parse_mes_label(m)], key=parse_mes_label, reverse=True)

    meses_seleccionados = request.args.getlist("meses")
    if not meses_seleccionados:
        meses_seleccionados = all_meses[:3]

    datos_meses = []
    for mes in meses_seleccionados:
        cur.execute("SELECT COALESCE(SUM(total), 0) as total FROM ingresos WHERE mes = %s", (mes,))
        ingresos_val = cur.fetchone()['total']
        cur.execute("SELECT COALESCE(SUM(valor), 0) as total FROM gastos WHERE mes = %s", (mes,))
        gastos_val = cur.fetchone()['total']
        balance_val = ingresos_val - gastos_val
        
        datos_meses.append({
            "mes": mes,
            "ingresos": ingresos_val,
            "gastos": gastos_val,
            "balance": balance_val
        })

    cur.close()
    conn.close()
    return render_template("analisis.html", all_meses=all_meses, meses_seleccionados=meses_seleccionados, datos_meses=datos_meses)


# ==================================================
# REGISTRO DE FILTROS JINJA2
# ==================================================
app.jinja_env.filters['fecha_corta'] = format_fecha_corta
app.jinja_env.filters['pesos'] = format_pesos_colombianos
app.jinja_env.filters['pesos_decimal'] = format_pesos_colombianos_decimal

# ==================================================
# INIT DB and RUN APP
# ==================================================
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
