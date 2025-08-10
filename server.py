from flask import Flask, send_from_directory, request, jsonify
from flask_cors import CORS
import os
import logging
import geopandas as gpd
from shapely.geometry import shape, mapping
import glob

# processing.py debe exponer clip_and_process_job(...), validar_archivos_hgt(...), validar_seleccion_ecuador(...)
from processing import clip_and_process_job, validar_archivos_hgt, validar_seleccion_ecuador

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
HGT_DIR = os.path.join(BASE_DIR, "hgt_files")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

GEOJSON_FILENAME = "geoBoundaries-ECU-ADM2_simplified.geojson"
ECUADOR_GEOJSON = os.path.join(DATA_DIR, GEOJSON_FILENAME)
MAX_AREA_KM2 = 2000

for path in [STATIC_DIR, DATA_DIR, HGT_DIR, OUTPUTS_DIR]:
    os.makedirs(path, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
CORS(app)
app.logger.setLevel(logging.DEBUG)

if not os.path.exists(ECUADOR_GEOJSON):
    app.logger.error(f"No existe {ECUADOR_GEOJSON}")
    raise FileNotFoundError(f"Falta archivo {ECUADOR_GEOJSON}")

frontera_ecuador = gpd.read_file(ECUADOR_GEOJSON).to_crs("EPSG:4326").unary_union
app.logger.info("Frontera de Ecuador cargada correctamente.")

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)

@app.route("/data/<path:filename>")
def data_files(filename):
    return send_from_directory(DATA_DIR, filename)

@app.route("/outputs/<job_id>/<path:filename>")
def outputs_files(job_id, filename):
    # sirve outputs/<job_id>/<filename>
    folder = os.path.join(OUTPUTS_DIR, job_id)
    return send_from_directory(folder, filename)

@app.route("/api/clip", methods=["POST"])
def api_clip():
    try:
        data = request.get_json(force=True)
        app.logger.debug(f"POST /api/clip payload: {data}")

        if not data:
            return jsonify({"error": "No JSON body"}), 400

        # aceptar geometry ó Feature
        geom_json = None
        if "geometry" in data:
            geom_json = data["geometry"]
        elif "geojson" in data:
            # accept feature or geometry inside geojson
            g = data["geojson"]
            if isinstance(g, dict) and g.get("type") == "Feature":
                geom_json = g.get("geometry")
            else:
                geom_json = g
        elif data.get("type") == "Feature":
            geom_json = data.get("geometry")
        else:
            return jsonify({"error": "Falta geometría (envía 'geometry' o 'geojson')"}), 400

        geom = shape(geom_json)

        # validar archivos HGT
        try:
            validar_archivos_hgt(HGT_DIR)
        except Exception as e:
            return jsonify({"error": f"HGT check failed: {str(e)}"}), 400

        # validar seleccion en Ecuador y tamaño
        try:
            inter_geom = validar_seleccion_ecuador(geom, frontera_ecuador, MAX_AREA_KM2)
        except Exception as e:
            return jsonify({"error": f"Validación selección: {str(e)}"}), 400

        # procesar (síncrono). Devuelve (job_id, glb_filename)
        try:
            job_id, glb_filename = clip_and_process_job(inter_geom, HGT_DIR)
        except Exception as e:
            app.logger.exception("Error en clip_and_process_job")
            return jsonify({"error": f"Error procesando selección: {str(e)}"}), 500

        glb_url = f"/outputs/{job_id}/{glb_filename}"
        return jsonify({"status": "ok", "job_id": job_id, "glb_url": glb_url, "inter_geojson": mapping(inter_geom)}), 200

    except Exception as e:
        app.logger.exception("Error inesperado en /api/clip")
        return jsonify({"error": str(e)}), 500

@app.route("/api/status/<job_id>", methods=["GET"])
def api_status(job_id):
    try:
        job_dir = os.path.join(OUTPUTS_DIR, job_id)
        if not os.path.exists(job_dir):
            return jsonify({"status": "error", "message": "Job no encontrado"}), 404
        glb_files = glob.glob(os.path.join(job_dir, "*.glb"))
        if glb_files:
            name = os.path.basename(glb_files[0])
            return jsonify({"status": "done", "glb_url": f"/outputs/{job_id}/{name}"}), 200
        return jsonify({"status": "processing"}), 200
    except Exception as e:
        app.logger.exception("Error en /api/status")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
