// Configuración de SQLite y IndexedDB para persistencia en el navegador (GitHub Pages)

const DB_NAME = 'gastos_db_store';
const STORE_NAME = 'gastos_file';
const DB_FILE_KEY = 'db_file';

// URL del backend en Render (ej. 'https://control-gastos.onrender.com'). Deja vacío '' para usar solo almacenamiento local en IndexedDB.
const RENDER_BACKEND_URL = 'https://control-gastos.onrender.com';

const SALARIO_MINIMO_2026 = 1750905;
const AUXILIO_TRANSPORTE_2026 = 249095;
const TOPE_AUXILIO_TRANSPORTE = SALARIO_MINIMO_2026 * 2;

// --- INDEXED DB HELPERS ---
function openIndexedDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = function(e) {
            const db = e.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME);
            }
        };
        request.onsuccess = function(e) {
            resolve(e.target.result);
        };
        request.onerror = function(e) {
            reject(e.target.error);
        };
    });
}

function getDatabaseFile(idb) {
    return new Promise((resolve, reject) => {
        const transaction = idb.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.get(DB_FILE_KEY);
        request.onsuccess = function(e) {
            resolve(e.target.result);
        };
        request.onerror = function(e) {
            reject(e.target.error);
        };
    });
}

function saveDatabaseFile(idb, arrayBuffer) {
    return new Promise((resolve, reject) => {
        const transaction = idb.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.put(arrayBuffer, DB_FILE_KEY);
        request.onsuccess = function() {
            resolve();
        };
        request.onerror = function(e) {
            reject(e.target.error);
        };
    });
}

function deleteDatabaseStore(idb) {
    return new Promise((resolve, reject) => {
        const transaction = idb.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.delete(DB_FILE_KEY);
        request.onsuccess = function() {
            resolve();
        };
        request.onerror = function(e) {
            reject(e.target.error);
        };
    });
}

// --- SQLITE & PYODIDE HELPERS ---
let SQL;
let dbInstance;
let idbInstance;

async function initDatabase(forceReload = false) {
    if (dbInstance && !forceReload) return dbInstance;

    idbInstance = await openIndexedDB();

    if (!window.initSqlJs) {
        // Cargar script dinámicamente si no está en el HTML
        await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.8.0/sql-wasm.js";
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    SQL = await window.initSqlJs({
        locateFile: file => `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.8.0/${file}`
    });

    let dbBuffer = null;
    if (!forceReload) {
        dbBuffer = await getDatabaseFile(idbInstance);
    }

    if (!dbBuffer || forceReload) {
        dbBuffer = await downloadDatabaseFromServer();
    } else {
        // Cargar inmediatamente desde IndexedDB local para rapidez, 
        // y sincronizar en segundo plano en caso de que haya datos nuevos en Render.
        syncDatabaseFromServerInBackground();
    }

    dbInstance = new SQL.Database(new Uint8Array(dbBuffer));
    return dbInstance;
}

// --- FUNCIONES DE SINCRONIZACIÓN CON EL SERVIDOR RENDER ---

async function downloadDatabaseFromServer() {
    console.log("Descargando base de datos...");
    if (RENDER_BACKEND_URL) {
        try {
            const response = await fetch(`${RENDER_BACKEND_URL}/api/db`);
            if (response.ok) {
                const buffer = await response.arrayBuffer();
                await saveDatabaseFile(idbInstance, buffer);
                console.log("Base de datos descargada con éxito de Render.");
                return buffer;
            }
        } catch (err) {
            console.warn("Fallo la descarga desde Render, intentando desde GitHub...", err);
        }
    }
    
    // Descarga desde el propio repositorio GitHub Pages (gastos.db estático original)
    try {
        const response = await fetch('gastos.db');
        if (!response.ok) throw new Error("No se pudo obtener gastos.db");
        const buffer = await response.arrayBuffer();
        await saveDatabaseFile(idbInstance, buffer);
        console.log("Descargada base de datos original desde GitHub Pages.");
        return buffer;
    } catch (err) {
        console.warn("Fallo la descarga de gastos.db, creando base de datos vacía.", err);
        const tempDb = new SQL.Database();
        initTables(tempDb);
        const buffer = tempDb.export().slice().buffer;
        await saveDatabaseFile(idbInstance, buffer);
        return buffer;
    }
}

let isSyncing = false;
async function syncDatabaseFromServerInBackground() {
    if (isSyncing || !RENDER_BACKEND_URL) return;
    isSyncing = true;
    try {
        console.log("Sincronizando base de datos con Render en segundo plano...");
        const response = await fetch(`${RENDER_BACKEND_URL}/api/db`);
        if (response.ok) {
            const serverBuffer = await response.arrayBuffer();
            const localBuffer = await getDatabaseFile(idbInstance);
            
            if (!localBuffer || !areBuffersEqual(serverBuffer, localBuffer)) {
                console.log("Se detectaron cambios nuevos en Render. Actualizando base de datos local...");
                await saveDatabaseFile(idbInstance, serverBuffer);
                if (dbInstance) {
                    dbInstance = new SQL.Database(new Uint8Array(serverBuffer));
                    // Dispara un evento por si alguna vista activa quiere actualizarse
                    window.dispatchEvent(new Event('db-synced'));
                }
            } else {
                console.log("Base de datos local al día con Render.");
            }
        }
    } catch (e) {
        console.warn("No se pudo sincronizar con Render:", e);
    } finally {
        isSyncing = false;
    }
}

async function uploadDbToServer(arrayBuffer) {
    if (!RENDER_BACKEND_URL) return;
    try {
        const blob = new Blob([arrayBuffer], { type: "application/x-sqlite3" });
        const formData = new FormData();
        formData.append("file", blob, "gastos.db");
        
        console.log("Subiendo base de datos a Render...");
        const response = await fetch(`${RENDER_BACKEND_URL}/api/db`, {
            method: "POST",
            body: formData
        });
        if (!response.ok) throw new Error("Error HTTP " + response.status);
        console.log("Base de datos sincronizada y guardada en Render exitosamente.");
    } catch (e) {
        console.error("Error al subir base de datos a Render:", e);
    }
}

function areBuffersEqual(buf1, buf2) {
    if (buf1.byteLength !== buf2.byteLength) return false;
    const dv1 = new Uint8Array(buf1);
    const dv2 = new Uint8Array(buf2);
    for (let i = 0; i < dv1.byteLength; i++) {
        if (dv1[i] !== dv2[i]) return false;
    }
    return true;
}

function initTables(db) {
    db.run(`
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
    )`);

    db.run(`
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
        FOREIGN KEY(tipo_ingreso_id) REFERENCES tipos_ingreso(id)
    )`);

    db.run(`
    CREATE TABLE IF NOT EXISTS gastos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        concepto TEXT NOT NULL,
        valor REAL NOT NULL,
        fecha TEXT NOT NULL,
        mes TEXT NOT NULL
    )`);

    // Insertar maestras por defecto si está vacía
    const count = db.exec("SELECT COUNT(*) as count FROM tipos_ingreso")[0].values[0][0];
    if (count === 0) {
        db.run(`INSERT INTO tipos_ingreso (nombre, aplica_deduccion, tipo_calculo, valor_unitario, porcentaje_deduccion, deduccion_sobre_auxilio, auxilio_transporte_valor, recibe_auxilio_transporte) VALUES 
        ('SALARIO CRIS', 1, 'salario', 0, 8, 0, 249095, 0),
        ('SALARIO ELI', 1, 'salario', 0, 8, 0, 249095, 1),
        ('TOQUES', 0, 'toques', 350000, 0, 0, 249095, 0),
        ('OTRO INGRESO', 0, 'otro', 0, 0, 0, 249095, 0)`);
    }
}

// --- OPERACIONES DB ---
async function executeQuery(query, params = []) {
    const db = await initDatabase();
    const result = [];
    try {
        const stmt = db.prepare(query);
        stmt.bind(params);
        while (stmt.step()) {
            result.push(stmt.getAsObject());
        }
        stmt.free();
    } catch (e) {
        console.error("SQL Error en query:", query, e);
    }
    return result;
}

async function executeRun(query, params = []) {
    const db = await initDatabase();
    try {
        db.run(query, params);
        const binaryDb = db.export();
        const cleanBuffer = binaryDb.slice().buffer;
        await saveDatabaseFile(idbInstance, cleanBuffer);
        // Subir cambios a Render
        uploadDbToServer(cleanBuffer);
    } catch (e) {
        console.error("SQL Error en run:", query, e);
        throw e;
    }
}

// --- EXPORT / IMPORT DE BASE DE DATOS ---
async function exportDatabaseFile() {
    const db = await initDatabase();
    const binaryDb = db.export();
    const blob = new Blob([binaryDb], { type: "application/x-sqlite3" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "gastos.db";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function importDatabaseFile(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = async function(e) {
            try {
                const buffer = e.target.result;
                // Validar que se abra correctamente con sql.js
                const tempDb = new SQL.Database(new Uint8Array(buffer));
                tempDb.close(); // Cerrar base de datos temporal
                
                idbInstance = await openIndexedDB();
                await saveDatabaseFile(idbInstance, buffer);
                dbInstance = new SQL.Database(new Uint8Array(buffer));
                
                // Subir base de datos importada a Render
                uploadDbToServer(buffer);
                
                resolve(true);
            } catch (err) {
                reject(new Error("El archivo seleccionado no es una base de datos SQLite válida. " + err.message));
            }
        };
        reader.onerror = () => reject(new Error("Error al leer el archivo."));
        reader.readAsArrayBuffer(file);
    });
}

async function resetDatabaseFromGit() {
    await initDatabase(true);
}

// --- LÓGICA DE NEGOCIO ---
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
    // Corregir fecha ignorando zona horaria local
    const [year, month, day] = dateStr.split('-');
    const mNum = parseInt(month, 10);
    return `${String(parseInt(day, 10)).padStart(2, '0')}-${MONTH_ABBR[mNum].toUpperCase()}-${year}`;
}

function formatPesos(valor) {
    if (valor === null || valor === undefined || isNaN(valor)) return '$0';
    return '$' + Math.round(valor).toLocaleString('es-CO').replace(/,/g, '.');
}

function formatPesosDecimal(valor) {
    if (valor === null || valor === undefined || isNaN(valor)) return '$0,00';
    // es-CO usa comas para decimales y puntos para miles. En Javascript toLocaleString lo formatea así por defecto.
    return '$' + parseFloat(valor).toLocaleString('es-CO', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Recalcular salario para un ingreso de tipo salario
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

// Obtener meses disponibles
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

// --- MENÚ DE BASE DE DATOS COMPARTIDO ---
function addDatabaseMenu() {
    const topbar = document.querySelector('.topbar');
    if (!topbar) return;

    // Crear contenedor de dropdown
    const dropdown = document.createElement('div');
    dropdown.className = 'db-dropdown';
    dropdown.style.position = 'relative';
    dropdown.style.display = 'inline-block';

    const dbBtn = document.createElement('a');
    dbBtn.href = '#';
    dbBtn.innerHTML = '💾 Base de Datos ▼';
    dbBtn.style.color = '#00e5ff';
    dbBtn.style.fontWeight = 'bold';
    dropdown.appendChild(dbBtn);

    const dropdownContent = document.createElement('div');
    dropdownContent.className = 'db-dropdown-content';
    dropdownContent.style.display = 'none';
    dropdownContent.style.position = 'absolute';
    dropdownContent.style.backgroundColor = '#1e293b';
    dropdownContent.style.minWidth = '220px';
    dropdownContent.style.boxShadow = '0px 8px 16px 0px rgba(0,0,0,0.5)';
    dropdownContent.style.zIndex = '1000';
    dropdownContent.style.borderRadius = '8px';
    dropdownContent.style.top = '100%';
    dropdownContent.style.left = '0';
    dropdownContent.style.padding = '8px 0';
    dropdownContent.style.border = '1px solid #334155';

    const createLink = (text, onClick) => {
        const link = document.createElement('a');
        link.href = '#';
        link.textContent = text;
        link.style.color = '#e8ecf1';
        link.style.padding = '10px 16px';
        link.style.textDecoration = 'none';
        link.style.display = 'block';
        link.style.fontSize = '14px';
        link.style.transition = 'background 0.2s';
        link.onmouseover = () => link.style.backgroundColor = '#334155';
        link.onmouseout = () => link.style.backgroundColor = 'transparent';
        link.onclick = (e) => {
            e.preventDefault();
            dropdownContent.style.display = 'none';
            onClick();
        };
        return link;
    };

    // Botón exportar
    dropdownContent.appendChild(createLink('Exportar gastos.db (Descargar)', async () => {
        if (confirm("Se descargará tu base de datos gastos.db actual con todos los cambios que hayas guardado en el navegador. Reemplaza el archivo gastos.db en tu computadora local y súbelo a GitHub para actualizar tu repositorio.")) {
            await exportDatabaseFile();
        }
    }));

    // Botón importar
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.db';
    fileInput.style.display = 'none';
    fileInput.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        try {
            await importDatabaseFile(file);
            alert("¡Base de datos importada exitosamente! La página se recargará.");
            window.location.reload();
        } catch (err) {
            alert(err.message);
        }
    };
    dropdown.appendChild(fileInput);

    dropdownContent.appendChild(createLink('Importar gastos.db (Cargar)', () => {
        fileInput.click();
    }));

    // Botón restablecer
    dropdownContent.appendChild(createLink('Restablecer desde GitHub', async () => {
        if (confirm("¡ATENCIÓN! Se borrarán todos los cambios locales guardados en este navegador y se volverá a descargar la base de datos desde tu repositorio de GitHub. ¿Deseas continuar?")) {
            try {
                await resetDatabaseFromGit();
                alert("¡Restablecido con éxito! La página se recargará.");
                window.location.reload();
            } catch (err) {
                alert("Error al restablecer: " + err.message);
            }
        }
    }));

    dropdown.appendChild(dropdownContent);
    topbar.appendChild(dropdown);

    // Eventos para abrir/cerrar
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
    // Agregar menú de BD en todas las vistas estáticas
    setTimeout(addDatabaseMenu, 100);
});
