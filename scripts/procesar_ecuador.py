import os
import datetime
import rasterio
import numpy as np
from scipy.ndimage import gaussian_filter
import trimesh
import geopandas as gpd
from rasterio.mask import mask

# === CONFIGURACIÓN ===
DATA_DIR = "data"
OUTPUT_DIR = "outputs"
GEOJSON_ECUADOR = os.path.join(DATA_DIR, "geoBoundaries-ECU-ADM2_simplified.geojson")
MOSAIC_PATH = os.path.join(DATA_DIR, "mosaic.tif")
SIGMA = 1.5        # suavizado
VSCALE = 1.5       # exageración vertical
MAXDIM = 2000      # tamaño máximo para evitar modelos muy pesados

os.makedirs(OUTPUT_DIR, exist_ok=True)

# === FUNCIONES ===
def recortar_tif():
    """Recorta el mosaico usando el contorno de Ecuador del GeoJSON, sin usar gdalwarp."""
    out_path = os.path.join(DATA_DIR, "ecuador.tif")

    # Leer shapefile/geojson con geopandas
    gdf = gpd.read_file(GEOJSON_ECUADOR)
    gdf = gdf.to_crs("EPSG:4326")  # Asegurar coordenadas geográficas

    # Abrir el mosaico
    with rasterio.open(MOSAIC_PATH) as src:
        # Máscara para recortar
        shapes = [feature["geometry"] for feature in gdf.__geo_interface__["features"]]
        out_image, out_transform = mask(src, shapes, crop=True)
        out_meta = src.meta.copy()

    # Actualizar metadata
    out_meta.update({
        "driver": "GTiff",
        "height": out_image.shape[1],
        "width": out_image.shape[2],
        "transform": out_transform
    })

    # Guardar recorte
    with rasterio.open(out_path, "w", **out_meta) as dest:
        dest.write(out_image)

    return out_path


def suavizar_y_escalar(tif_path):
    with rasterio.open(tif_path) as src:
        arr = src.read(1).astype(np.float32)
        profile = src.profile
        transform = src.transform

    arr[arr == profile.get("nodata", -32768)] = np.nan

    # Downsample si es muy grande
    nrows, ncols = arr.shape
    factor = max(1, int(max(nrows, ncols) / MAXDIM))
    arr_ds = arr[::factor, ::factor]
    new_transform = rasterio.Affine(
        transform.a * factor, transform.b, transform.c,
        transform.d, transform.e * factor, transform.f
    )

    # Suavizado
    smoothed = gaussian_filter(arr_ds, sigma=SIGMA)

    return smoothed, profile, new_transform


def generar_malla(arr, transform):
    nrows, ncols = arr.shape
    a, e, c, f = transform.a, transform.e, transform.c, transform.f
    xs = c + np.arange(ncols) * a
    ys = f + np.arange(nrows) * e

    lat_m = 111320.0
    lon_m = 111320.0 * np.cos(np.deg2rad(ys.mean()))
    xs_m = (xs - xs[0]) * lon_m
    ys_m = (ys - ys[0]) * lat_m

    xx, yy = np.meshgrid(xs_m, ys_m)
    zz = np.where(np.isnan(arr), np.nanmin(arr), arr) * VSCALE

    verts = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
    faces = []
    for i in range(nrows - 1):
        for j in range(ncols - 1):
            v0 = i * ncols + j
            v1 = v0 + 1
            v2 = v0 + ncols
            v3 = v2 + 1
            faces.append([v0, v2, v1])
            faces.append([v1, v2, v3])

    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    mesh.remove_duplicate_faces()
    mesh.remove_unreferenced_vertices()
    return mesh


# === PROCESO PRINCIPAL ===
if __name__ == "__main__":
    print("📍 Recortando Ecuador...")
    tif_ecuador = recortar_tif()

    print("🔄 Suavizando y escalando...")
    arr, profile, transform = suavizar_y_escalar(tif_ecuador)

    print("🛠 Generando malla...")
    mesh = generar_malla(arr, transform)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stl_path = os.path.join(OUTPUT_DIR, f"ecuador_{ts}.stl")
    glb_path = os.path.join(OUTPUT_DIR, f"ecuador_{ts}.glb")

    print(f"💾 Exportando STL: {stl_path}")
    mesh.export(stl_path)

    print(f"💾 Exportando GLB: {glb_path}")
    mesh.export(glb_path)

    print("✅ Proceso completado.")
