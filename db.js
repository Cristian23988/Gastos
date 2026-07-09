// Conectividad de Base de Datos para Neon Postgres a través de Render Flask API

// Detección automática del backend
const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const isRender = window.location.hostname.endsWith('onrender.com');

// URL por defecto del backend en Render (modifica si tu aplicación tiene un dominio diferente)
const DEFAULT_RENDER_URL = 'https://gastos-uq90.onrender.com';

// Permite sobrescribir la URL desde la consola del navegador con:
// localStorage.setItem('BACKEND_URL', 'https://tu-app.onrender.com')
const RENDER_BACKEND_URL = localStorage.getItem('BACKEND_URL') || DEFAULT_RENDER_URL;

// Detección del API URL
let API_BASE_URL = "";
if (isLocal) {
    // Si corre local, y no es el puerto de Flask (5000), apunta al Flask local
    if (window.location.port !== "5000") {
        API_BASE_URL = "http://127.0.0.1:5000";
    } else {
        API_BASE_URL = "";
    }
} else if (isRender) {
    API_BASE_URL = "";
} else {
    API_BASE_URL = RENDER_BACKEND_URL;
}

const SALARIO_MINIMO_2026 = 1750905;
const AUXILIO_TRANSPORTE_2026 = 249095;
const TOPE_AUXILIO_TRANSPORTE = SALARIO_MINIMO_2026 * 2;

// --- INICIALIZACIÓN ---
async function initDatabase() {
    console.log("Conectado al backend de base de datos en:", API_BASE_URL || "Origen local/Render");
    return true;
}

// --- EJECUCIÓN DE CONSULTAS EN NEON POSTGRES (A TRAVÉS DE RENDER) ---
async function executeQuery(query, params = []) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/query`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ query, params })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || `Error HTTP ${response.status}`);
        }
        
        return await response.json();
    } catch (e) {
        console.error("Error en executeQuery:", e);
        throw e;
    }
}

async function executeRun(query, params = []) {
    // Para la API Flask unificada en Postgres, SELECT y UPDATE/INSERT usan el mismo endpoint
    return await executeQuery(query, params);
}

// --- LÓGICA DE NEGOCIO Y FORMATO ---
const SPANISH_MONTHS = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12
};
const MONTH_NAMES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO",
    7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE"
};
const MONTH_ABBR = {
    1: "ENE", 2: "FEB", 3: "MAR", 4: "ABR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AGO", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DIC"
};

function parseMesLabel(mesLabel) {
    if (!mesLabel) return null;
    const parts = mesLabel.trim().toUpperCase().split(/\s+/);
    if (parts.length !== 2) return null;
    const [name, yearStr] = parts;
    const month = SPANISH_MONTHS[name];
    const year = parseInt(yearStr, 10);
    if (!month || isNaN(year)) return null;
    return new Date(year, month - 1, 1);
}

function formatMesLabel(dateObj) {
    return `${MONTH_NAMES[dateObj.getMonth() + 1]} ${dateObj.getFullYear()}`;
}

function formatFechaCorta(dateStr) {
    if (!dateStr) return '';
    // Formato de fecha ignorando la zona horaria del navegador
    const [year, month, day] = dateStr.split('-');
    const mNum = parseInt(month, 10);
    return `${String(parseInt(day, 10)).padStart(2, '0')}-${MONTH_ABBR[mNum].toUpperCase()}-${year}`;
}

function formatPesos(valor) {
    if (valor === null || valor === undefined || isNaN(valor)) return '$0';
    return '$' + Math.round(valor).toLocaleString('es-CO').replace(/,/g, '.');
}

// Recalcular salario para ingresos tipo nómina
function calcularAuxilioTransporte(tipo, salarioBase) {
    if (!tipo.recibe_auxilio_transporte) return 0;
    if (salarioBase > TOPE_AUXILIO_TRANSPORTE) return 0;
    return tipo.auxilio_transporte_valor || 0;
}

function calcularTotalSalario(tipo, salarioBase) {
    const porcentaje = tipo.porcentaje_deduccion !== undefined ? tipo.porcentaje_deduccion : 8;
    const auxTransporte = calcularAuxilioTransporte(tipo, salarioBase);
    let baseDeduccion = salarioBase;
    if (tipo.deduccion_sobre_auxilio) {
        baseDeduccion += auxTransporte;
    }
    const descuento = baseDeduccion * (porcentaje / 100);
    return salarioBase + auxTransporte - descuento;
}

async function recalcularIngresosSalario(tipoId = null) {
    let query = `
        SELECT ingresos.id, ingresos.valor_unitario AS salario_base, tipos_ingreso.*
        FROM ingresos
        INNER JOIN tipos_ingreso ON ingresos.tipo_ingreso_id = tipos_ingreso.id
        WHERE tipos_ingreso.tipo_calculo = 'salario'
    `;
    let params = [];
    if (tipoId) {
        query += " AND tipos_ingreso.id = ?";
        params.push(tipoId);
    }
    
    const salarios = await executeQuery(query, params);
    for (const sal of salarios) {
        const aux = calcularAuxilioTransporte(sal, sal.salario_base);
        const total = calcularTotalSalario(sal, sal.salario_base);
        await executeRun(`
            UPDATE ingresos 
            SET auxilio_transporte = ?, total = ?
            WHERE id = ?
        `, [aux, total, sal.id]);
    }
}

// Cargar meses disponibles dinámicamente
async function buildAvailableMeses(defaultMes) {
    const meses = new Set();
    const rowsGastos = await executeQuery("SELECT DISTINCT mes FROM gastos");
    rowsGastos.forEach(r => r.mes && meses.add(r.mes.trim()));
    const rowsIngresos = await executeQuery("SELECT DISTINCT mes FROM ingresos");
    rowsIngresos.forEach(r => r.mes && meses.add(r.mes.trim()));
    meses.add(defaultMes);
    
    return Array.from(meses)
        .filter(m => parseMesLabel(m) !== null)
        .sort((a, b) => parseMesLabel(b) - parseMesLabel(a));
}

function getPreviousMonthLabel(mesLabel) {
    const current = parseMesLabel(mesLabel);
    if (!current) return null;
    const prev = new Date(current.getFullYear(), current.getMonth() - 1, 1);
    return formatMesLabel(prev);
}

// --- MENÚ DE INFORMACIÓN DE LA BASE DE DATOS (NUBE) ---
function addDatabaseMenu() {
    const topbar = document.querySelector('.topbar');
    if (!topbar) return;

    const dropdown = document.createElement('div');
    dropdown.className = 'db-dropdown';
    dropdown.style.position = 'relative';
    dropdown.style.display = 'inline-block';

    const dbBtn = document.createElement('a');
    dbBtn.href = '#';
    dbBtn.innerHTML = '☁️ BD: Neon Postgres (Cloud) ✓';
    dbBtn.style.color = '#00ff88';
    dbBtn.style.fontWeight = 'bold';
    dropdown.appendChild(dbBtn);

    const dropdownContent = document.createElement('div');
    dropdownContent.className = 'db-dropdown-content';
    dropdownContent.style.display = 'none';
    dropdownContent.style.position = 'absolute';
    dropdownContent.style.backgroundColor = '#1e293b';
    dropdownContent.style.minWidth = '260px';
    dropdownContent.style.boxShadow = '0px 8px 16px 0px rgba(0,0,0,0.5)';
    dropdownContent.style.zIndex = '1000';
    dropdownContent.style.borderRadius = '8px';
    dropdownContent.style.top = '100%';
    dropdownContent.style.left = '0';
    dropdownContent.style.padding = '12px';
    dropdownContent.style.border = '1px solid #334155';
    dropdownContent.style.color = '#e8ecf1';
    dropdownContent.style.fontSize = '13px';
    dropdownContent.style.lineHeight = '1.4';

    dropdownContent.innerHTML = `
        <div style="margin-bottom: 8px; font-weight: bold; color: #00ff88;">Base de Datos Conectada</div>
        <div style="margin-bottom: 6px;"><strong>Proveedor:</strong> Neon AWS PostgreSQL</div>
        <div style="margin-bottom: 6px;"><strong>Backend:</strong> Render (API Flask)</div>
        <div style="margin-bottom: 6px;"><strong>Estado:</strong> Activo y Seguro</div>
        <hr style="border: 0; border-top: 1px solid #334155; margin: 8px 0;">
        <div style="font-size: 11px; color: #94a3b8; font-style: italic;">
            Tus datos se guardan permanentemente en la nube de Neon. No se borrarán al reiniciar el servidor en Render.
        </div>
    `;

    dropdown.appendChild(dropdownContent);
    topbar.appendChild(dropdown);

    dbBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropdownContent.style.display = dropdownContent.style.display === 'none' ? 'block' : 'none';
    };

    document.addEventListener('click', () => {
        dropdownContent.style.display = 'none';
    });
}

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(addDatabaseMenu, 100);
});
