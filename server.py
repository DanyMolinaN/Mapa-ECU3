from flask import Flask, send_from_directory, request, jsonify
from flask_cors import CORS
import os
import logging
import geopandas as gpd
from shapely.geometry import shape, mapping
import glob
import datetime
import rasterio.mask

# Importar funciones desde procesar_ecuador.py
from procesar_ecuador import suavizar_y_escalar, generar_malla_solida
# Importar funciones de validación desde processing.py
from processing import validar_archivos_hgt, validar_seleccion_ecuador

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
HGT_DIR = os.path.join(BASE_DIR, "hgt_files")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

GEOJSON_FILENAME = "geoBoundaries-ECU-ADM2_simplified.geojson"
ECUADOR_GEOJSON = os.path.join(DATA_DIR, GEOJSON_FILENAME)
MAX_AREA_KM2 = 100000

# Crear carpetas si no existen
for path in [STATIC_DIR, DATA_DIR, HGT_DIR, OUTPUTS_DIR]:
    os.makedirs(path, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
CORS(app)
app.logger.setLevel(logging.DEBUG)

# Comprobar existencia de GeoJSON
if not os.path.exists(ECUADOR_GEOJSON):
    app.logger.error(f"No existe {ECUADOR_GEOJSON}")
    raise FileNotFoundError(f"Falta archivo {ECUADOR_GEOJSON}")

# Cargar frontera de Ecuador
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
    folder = os.path.join(OUTPUTS_DIR, job_id)
    return send_from_directory(folder, filename)

@app.route("/api/clip", methods=["POST"])
def api_clip():
    try:
        # Leer JSON enviado
        data = request.get_json(force=True)
        app.logger.debug(f"POST /api/clip payload: {data}")

        if not data:
            return jsonify({"error": "No JSON body"}), 400

        # Aceptar geometry o Feature
        geom_json = None
        if "geometry" in data:
            geom_json = data["geometry"]
        elif "geojson" in data:
            g = data["geojson"]
            if isinstance(g, dict) and g.get("type") == "Feature":
                geom_json = g.get("geometry")
            else:
                geom_json = g
        elif data.get("type") == "Feature":
            geom_json = data.get("geometry")
        else:
            return jsonify({"error": "Falta geometría"}), 400

        geom = shape(geom_json)

        # Validar archivos HGT
        validar_archivos_hgt(HGT_DIR)

        # Validar que esté dentro de Ecuador y no exceda el tamaño
        inter_geom = validar_seleccion_ecuador(geom, frontera_ecuador, MAX_AREA_KM2)

        # ============================
        # 1️⃣ Recortar usando la geometría seleccionada
        MOSAIC_PATH = os.path.join(DATA_DIR, "mosaic.tif")
        if not os.path.exists(MOSAIC_PATH):
            return jsonify({"error": "No se encuentra mosaic.tif en data/"}), 500

        tif_temp = os.path.join(OUTPUTS_DIR, "temp_clip.tif")
        with rasterio.open(MOSAIC_PATH) as src:
            out_image, out_transform = rasterio.mask.mask(src, [mapping(inter_geom)], crop=True)
            profile = src.profile
            profile.update({
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform
            })
            with rasterio.open(tif_temp, "w", **profile) as dest:
                dest.write(out_image)

        # ============================
        # 2️⃣ Suavizar y escalar
        arr, profile, transform = suavizar_y_escalar(tif_temp)

        # ============================
        # 3️⃣ Generar malla
        mesh = generar_malla_solida(arr, transform)

        # ============================
        # 4️⃣ Guardar con un job_id único
        job_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        job_dir = os.path.join(OUTPUTS_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        # Guardar GLB (vista previa en Cesium)
        glb_filename = f"ecuador_{job_id}.glb"
        glb_path = os.path.join(job_dir, glb_filename)
        mesh.export(glb_path)

        # Guardar STL (descarga para impresión 3D)
        stl_filename = f"ecuador_{job_id}.stl"
        stl_path = os.path.join(job_dir, stl_filename)
        mesh.export(stl_path, file_type="stl")

        # ============================
        # 5️⃣ Respuesta
        return jsonify({
            "status": "ok",
            "job_id": job_id,
            "glb_url": f"/outputs/{job_id}/{glb_filename}",  # para previsualizar
            "stl_url": f"/outputs/{job_id}/{stl_filename}",  # para descargar
            "inter_geojson": mapping(inter_geom)
        }), 200

    except Exception as e:
        app.logger.exception("Error procesando selección")
        return jsonify({"error": f"Error procesando selección: {str(e)}"}), 500

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

@app.route("/api/preview", methods=["POST"])
def preview_model():
    import json, numpy as np
    try:
        data = request.get_json(force=True)
        if not data or "geometry" not in data:
            return jsonify({"error": "Falta geometría"}), 400

        geom = shape(data["geometry"])
        validar_archivos_hgt(HGT_DIR)
        inter_geom = validar_seleccion_ecuador(geom, frontera_ecuador, MAX_AREA_KM2)

        MOSAIC_PATH = os.path.join(DATA_DIR, "mosaic.tif")
        if not os.path.exists(MOSAIC_PATH):
            return jsonify({"error": "No se encuentra mosaic.tif"}), 500

        with rasterio.open(MOSAIC_PATH) as src:
            out_image, out_transform = rasterio.mask.mask(src, [mapping(inter_geom)], crop=True)
            profile = src.profile
            profile.update({
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform
            })

            temp_tif = os.path.join(OUTPUTS_DIR, "temp_preview.tif")
            with rasterio.open(temp_tif, "w", **profile) as dest:
                dest.write(out_image)

        arr, profile, transform = suavizar_y_escalar(temp_tif)
        mesh = generar_malla_solida(arr, transform)

        job_id = f"preview_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        job_dir = os.path.join(OUTPUTS_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        glb_filename = f"preview_{job_id}.glb"
        glb_path = os.path.join(job_dir, glb_filename)
        mesh.export(glb_path)

        return jsonify({
            "status": "ok",
            "glb_url": f"/outputs/{job_id}/{glb_filename}"
        }), 200
    except Exception as e:
        app.logger.exception("Error en preview_model")
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
