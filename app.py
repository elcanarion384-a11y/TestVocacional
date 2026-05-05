from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__)
CORS(app)
contador=0
# --- CONFIGURACIÓN DE BASE DE DATOS ---
DB_DIR = os.environ.get("DB_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DB_DIR, "vocacional.db")

def get_db():
    """Abre una conexion a la base de datos SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- RUTAS DE NAVEGACIÓN Y RECEPCIÓN ---

@app.route('/')
def index():
    """Carga la página principal del test."""
    return render_template('test.html')

@app.route('/api/guardar_test', methods=['POST'])
def guardar_test():
    global contador
    if contador==0:

        """Recibe los datos finales del test y los guarda en la base de datos."""
        datos = request.get_json()
        if not datos:
            return jsonify({"error": "No se recibieron datos"}), 400
        
        # Extraemos los datos del JSON
        genero = datos.get('genero')
        isla = datos.get('isla')
        curso = datos.get('curso')
        respuestas = datos.get('respuestas', {}) # Es un diccionario tipo {'salud-0': 5, 'artes-1': 2...}
        especialidad= datos.get('especialidad')
        print(f"--- GUARDANDO TEST: Usuario {genero} de {isla} ---")
        
        conn = get_db()
        try:
            cur = conn.cursor()

            # PASO 1: Insertar en la tabla "Padre" (Cuestionarios)
            # Dejamos que SQLite genere el ID autoincremental
            cur.execute("""
                INSERT INTO cuestionarios (genero, isla, curso, especialidad)
                VALUES (?, ?, ?, ?)
            """, (datos.get('genero'), datos.get('isla'), datos.get('curso'), datos.get('especialidad')))

            # PASO 2: Recuperar el ID que se acaba de crear
            cuestionario_id = cur.lastrowid 

            # PASO 3: Insertar todas las respuestas usando ese ID
            respuestas = datos.get('respuestas', {})
            for clave, valor in respuestas.items():
                cat, idx = clave.split('-')
                
                cur.execute("""
                    INSERT INTO respuestas (cuestionario_id, categoria, pregunta_idx, puntuacion)
                    VALUES (?, ?, ?, ?)
                """, (cuestionario_id, cat, idx, valor))

            conn.commit()
                
            return jsonify({
                "status": "success", 
                "mensaje": f"Test guardado con éxito. Se procesaron {len(respuestas)} respuestas."
            }), 200

        except Exception as e:
            print(f"ERROR AL GUARDAR EN DB: {e}")
            return jsonify({"error": "Error interno al guardar los datos"}), 500
        finally:
            conn.close()

# --- TUS FUNCIONES ORIGINALES DE LA BASE DE DATOS ---

@app.route("/api/islas", methods=["GET"])
def get_islas():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, nombre FROM islas ORDER BY id")
        islas = [{"id": row["id"], "nombre": row["nombre"]} for row in cur.fetchall()]
        return jsonify(islas)
    finally:
        conn.close()

@app.route("/api/estudios", methods=["GET"])
def get_estudios():
    isla_nombre = request.args.get("isla")
    categoria = request.args.get("cat")
    if not isla_nombre:
        return jsonify({"error": "El parametro 'isla' es requerido"}), 400
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM islas WHERE LOWER(nombre) = LOWER(?)", (isla_nombre,))
        isla_row = cur.fetchone()
        if not isla_row:
            return jsonify({"error": f"Isla '{isla_nombre}' no encontrada"}), 404
        isla_id = isla_row["id"]
        if categoria:
            cur.execute("""
                SELECT e.nombre AS estudio, t.nombre AS tipo, e.categoria
                FROM estudios e
                JOIN tipos_estudio t ON e.tipo_id = t.id
                WHERE e.isla_id = ? AND LOWER(e.categoria) = LOWER(?)
                ORDER BY t.id, e.nombre
            """, (isla_id, categoria))
        else:
            cur.execute("""
                SELECT e.nombre AS estudio, t.nombre AS tipo, e.categoria
                FROM estudios e
                JOIN tipos_estudio t ON e.tipo_id = t.id
                WHERE e.isla_id = ?
                ORDER BY t.id, e.nombre
            """, (isla_id,))
        rows = cur.fetchall()
        grouped = {}
        for row in rows:
            tipo = row["tipo"]
            if tipo not in grouped: grouped[tipo] = []
            grouped[tipo].append({"nombre": row["estudio"], "categoria": row["categoria"]})
        return jsonify({"isla": isla_nombre, "categoria": categoria, "total": len(rows), "estudios_por_tipo": grouped})
    finally:
        conn.close()

@app.route("/api/estudios/recomendados", methods=["GET"])
def get_recomendados():
    # 1. Ya no validamos 'isla_nombre' como obligatorio
    cats_param = request.args.get("cats", "")
    
    if not cats_param:
        return jsonify({"error": "Faltan parámetro cats"}), 400
        
    categorias = [c.strip().lower() for c in cats_param.split(",") if c.strip()]
    conn = get_db()
    try:
        cur = conn.cursor()
        
        # 2. Preparamos la lógica de orden (esto se queda igual para priorizar tus tops)
        placeholders = ",".join(["?" for _ in categorias])
        case_logic = " ".join([f"WHEN LOWER(e.categoria) = ? THEN {i}" for i, _ in enumerate(categorias)])
        
        # 3. Consulta SQL simplificada: Quitamos el JOIN con islas y el WHERE de isla_id
        # Filtramos para que solo traiga estudios de las categorías solicitadas
        query = f"""
            SELECT e.nombre AS estudio, t.nombre AS tipo, e.categoria
            FROM estudios e
            JOIN tipos_estudio t ON e.tipo_id = t.id
            WHERE LOWER(e.categoria) IN ({placeholders})
            ORDER BY
                CASE 
                    {case_logic}
                    ELSE {len(categorias)}
                END,
                t.id, e.nombre
        """
        
        # Ejecutamos pasando las categorías dos veces (una para el IN y otra para el CASE)
        cur.execute(query, categorias + categorias)
        
        rows = cur.fetchall()
        by_category = {}
        for row in rows:
            cat = row["categoria"]
            if cat not in by_category: by_category[cat] = []
            by_category[cat].append({"nombre": row["estudio"], "tipo": row["tipo"]})
            
        return jsonify({
            "categorias_solicitadas": categorias, 
            "total": len(rows), 
            "recomendados_por_categoria": by_category
        })
    except Exception as e:
        print(f"Error en recomendados: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "db_exists": os.path.exists(DB_PATH)})

# --- INICIO DEL SERVIDOR ---

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"AVISO: No se encontro la base de datos en {DB_PATH}")
    else:
        print(f"Base de datos detectada en: {DB_PATH}")

    app.run(host="127.0.0.1", port=5000, debug=True)
