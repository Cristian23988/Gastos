
from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)

DB = "gastos.db"

def get_connection():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS salarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        concepto TEXT NOT NULL,
        valor REAL NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gastos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        concepto TEXT NOT NULL,
        valor REAL NOT NULL,
        fecha TEXT NOT NULL,
        mes TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()

@app.route("/")
def index():
    conn = get_connection()
    cur = conn.cursor()

    meses = cur.execute("""
        SELECT DISTINCT mes FROM gastos
        ORDER BY id DESC
    """).fetchall()

    mes_actual = datetime.now().strftime("%B %Y").upper()

    gastos = cur.execute("""
        SELECT * FROM gastos
        WHERE mes = ?
        ORDER BY fecha DESC
    """, (mes_actual,)).fetchall()

    salarios = cur.execute("""
        SELECT * FROM salarios
    """).fetchall()

    total_gastos = sum(g["valor"] for g in gastos)
    total_salarios = sum(s["valor"] for s in salarios)

    balance = total_salarios - total_gastos

    conn.close()

    return render_template(
        "index.html",
        gastos=gastos,
        salarios=salarios,
        meses=meses,
        mes_actual=mes_actual,
        total_gastos=total_gastos,
        total_salarios=total_salarios,
        balance=balance
    )

@app.route("/guardar_gasto", methods=["POST"])
def guardar_gasto():
    concepto = request.form["concepto"]
    valor = float(request.form["valor"])
    fecha = request.form["fecha"]

    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d")
    mes = fecha_obj.strftime("%B %Y").upper()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO gastos (concepto, valor, fecha, mes)
        VALUES (?, ?, ?, ?)
    """, (concepto, valor, fecha, mes))

    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/guardar_salario", methods=["POST"])
def guardar_salario():
    concepto = request.form["concepto"]
    valor = float(request.form["valor"])

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO salarios (concepto, valor)
        VALUES (?, ?)
    """, (concepto, valor))

    conn.commit()
    conn.close()

    return redirect("/")

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
