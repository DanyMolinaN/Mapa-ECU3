# procesar_ecuador.py
import os
import datetime
import rasterio
import numpy as np
from scipy.ndimage import gaussian_filter
import trimesh
import geopandas as gpd
import rasterio.mask
from rasterio.transform import Affine
import matplotlib.pyplot as plt

# === CONFIGURACIÓN ===
DATA_DIR = "data"
OUTPUT_DIR = "outputs"
GEOJSON_ECUADOR = os.path.join(DATA_DIR, "geoBoundaries-ECU-ADM2_simplified.geojson")
MOSAIC_PATH = os.path.join(DATA_DIR, "mosaic.tif")
SIGMA = 1.5      # valor por defecto para suavizado (0 = sin suavizado)
VSCALE = 1.5       # exageración vertical
MAXDIM = 100000      # tamaño máximo (en pixels) para evitar modelos muy pesados

os.makedirs(OUTPUT_DIR, exist_ok=True)


# === FUNCIONES ===

def recortar_tif_by_geojson(geojson_path=GEOJSON_ECUADOR, out_name="ecuador.tif"):
    """Recorta mosaic.tif usando todo el geojson (Ecuador) y guarda data/ecuador.tif"""
    if not os.path.exists(MOSAIC_PATH):
        raise FileNotFoundError(f"No se encuentra {MOSAIC_PATH}")

    gdf = gpd.read_file(geojson_path)
    shapes = [feature["geometry"] for feature in gdf.__geo_interface__["features"]]

    with rasterio.open(MOSAIC_PATH) as src:
        out_image, out_transform = rasterio.mask.mask(src, shapes, crop=True)
        out_meta = src.meta.copy()

    out_meta.update({
        "driver": "GTiff",
        "height": out_image.shape[1],
        "width": out_image.shape[2],
        "transform": out_transform,
        "count": out_image.shape[0]
    })

    out_path = os.path.join(DATA_DIR, out_name)
    with rasterio.open(out_path, "w", **out_meta) as dest:
        dest.write(out_image)
    return out_path


def suavizar_y_escalar(tif_path, sigma=SIGMA):
    """
    Lee tif_path y devuelve (arr, profile, transform).
    - arr: 2D float32 (posible downsample)
    - profile: profile original (actualizado si hubo downsample)
    - transform: transform actualizado
    """
    with rasterio.open(tif_path) as src:
        arr = src.read(1).astype(np.float32)
        profile = src.profile.copy()
        transform = src.transform

    # nodata -> NaN
    nod = profile.get("nodata", None)
    if nod is None:
        # intentar heurística común
        nod = -32768
    arr[arr == nod] = np.nan

    # Downsample si arr muy grande (por dimensión mayor)
    nrows, ncols = arr.shape
    factor = max(1, int(max(nrows, ncols) / MAXDIM))
    if factor > 1:
        # re-sample por rebin simple (media ignorando NaN)
        new_rows = int(np.ceil(nrows / factor))
        new_cols = int(np.ceil(ncols / factor))
        arr_ds = np.full((new_rows, new_cols), np.nan, dtype=np.float32)
        rr = np.linspace(0, nrows, new_rows + 1, dtype=int)
        cc = np.linspace(0, ncols, new_cols + 1, dtype=int)
        for i in range(new_rows):
            for j in range(new_cols):
                block = arr[rr[i]:rr[i+1], cc[j]:cc[j+1]]
                if block.size == 0:
                    arr_ds[i, j] = np.nan
                else:
                    arr_ds[i, j] = np.nanmean(block)
        arr = arr_ds
        new_transform = Affine(
            transform.a * factor, transform.b, transform.c,
            transform.d, transform.e * factor, transform.f
        )
    else:
        new_transform = transform

    # Suavizado opcional
    if sigma and sigma > 0:
        # gaussian_filter preserva NaN? No, por eso aplicamos en máscara
        nan_mask = np.isnan(arr)
        arr_filled = np.where(nan_mask, np.nanmedian(arr) if np.isfinite(np.nanmedian(arr)) else 0.0, arr)
        sm = gaussian_filter(arr_filled, sigma=sigma)
        # re-aplicar mask para mantener NaN donde no hay datos
        sm[nan_mask] = np.nan
        arr = sm.astype(np.float32)

    return arr, profile, new_transform


def generar_color_por_altura(arr):
    """
    Devuelve un array (N,3) float (0..1) con colores por altura para la superficie.
    arr es 2D (rows, cols).
    """
    flat = arr.ravel()
    # manejar NaN: sustituir por min-valor para coloreado coherente
    nan_mask = np.isnan(flat)
    if nan_mask.all():
        # todo NaN: devolvemos gris
        return np.tile(np.array([0.6, 0.6, 0.6]), (flat.size, 1))

    minv = np.nanmin(flat)
    maxv = np.nanmax(flat)
    if maxv - minv <= 0:
        norm = np.zeros_like(flat, dtype=np.float32)
    else:
        norm = (flat - minv) / (maxv - minv)
    cmap = plt.get_cmap("terrain")
    rgba = cmap(norm)  # shape (N,4)
    rgb = rgba[:, :3]
    # for NaNs, you may want a transparent or special color; we'll keep them mapped to low color
    rgb[nan_mask] = np.array([0.9, 0.9, 0.9])  # light gray for no-data
    return rgb.astype(np.float32)


def generar_malla_solida(arr, transform, base_altura=None, vs=VSCALE, vertex_color=True):
    """
    Genera una malla sólida con base plana y caras laterales.
    - arr: 2D elevation array (meters)
    - transform: affine transform (rasterio)
    - base_altura: si None -> min(zz) - 10% rango; si número, se fija.
    - vs: vertical scale
    - vertex_color: si True, añade vertex_colors (top+bottom)
    Retorna: trimesh.Trimesh (con vertex_colors si vertex_color True)
    """
    nrows, ncols = arr.shape
    a, e, c, f = transform.a, transform.e, transform.c, transform.f
    xs = c + np.arange(ncols) * a
    ys = f + np.arange(nrows) * e

    # metros por grado (aprox) en lon según lat medio
    lat_mean = np.nanmean(ys)
    meters_per_deg = 111320.0 * np.cos(np.deg2rad(lat_mean))
    xs_m = (xs - xs[0]) * meters_per_deg
    ys_m = (ys - ys[0]) * 111320.0  # lat to meters approx

    xx, yy = np.meshgrid(xs_m, ys_m)
    zz = np.where(np.isnan(arr), np.nanmin(arr), arr) * vs
    # determinar base_altura
    if base_altura is None:
        finite = zz[np.isfinite(zz)]
        if finite.size == 0:
            base_alt = 0.0
        else:
            minv = np.min(finite)
            maxv = np.max(finite)
            base_alt = minv - 0.10 * max(1.0, (maxv - minv))
    else:
        base_alt = base_altura

    # Vértices top
    verts_top = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
    N = verts_top.shape[0]

    # Vértices bottom (base plana)
    verts_bottom = np.column_stack((xx.ravel(), yy.ravel(), np.full(N, base_alt)))
    verts = np.vstack((verts_top, verts_bottom))
    offset = N

    faces = []
    # caras top (triangulación regular)
    for r in range(nrows - 1):
        for c in range(ncols - 1):
            v0 = r * ncols + c
            v1 = v0 + 1
            v2 = v0 + ncols
            v3 = v2 + 1
            faces.append([v0, v2, v1])
            faces.append([v1, v2, v3])

    # caras base (usar la misma triangulación, pero referida a bottom y con orientación invertida)
    for r in range(nrows - 1):
        for c in range(ncols - 1):
            v0 = offset + r * ncols + c
            v1 = v0 + 1
            v2 = v0 + ncols
            v3 = v2 + 1
            # invertir orientación para que la normal apunte hacia abajo
            faces.append([v0, v1, v2])
            faces.append([v1, v3, v2])

    # generar borde ordenado (perímetro) y crear caras laterales
    perimeter = []
    # top row left->right
    for j in range(0, ncols):
        perimeter.append(0 * ncols + j)
    # right col top->bottom (skip first)
    for i in range(1, nrows):
        perimeter.append(i * ncols + (ncols - 1))
    # bottom row right->left (skip last)
    for j in range(ncols - 2, -1, -1):
        perimeter.append((nrows - 1) * ncols + j)
    # left col bottom->top (skip last and first)
    for i in range(nrows - 2, 0, -1):
        perimeter.append(i * ncols + 0)

    # crear caras laterales uniendo cada arista (t0->t1) con su correspond. bottom
    P = len(perimeter)
    for k in range(P):
        t0 = perimeter[k]
        t1 = perimeter[(k + 1) % P]
        b0 = t0 + offset
        b1 = t1 + offset
        # dos triángulos por cara lateral
        faces.append([t0, b0, t1])
        faces.append([t1, b0, b1])

    faces = np.array(faces, dtype=np.int64)

    # Colores por vértice (opcional)
    vertex_colors = None
    if vertex_color:
        top_colors = generar_color_por_altura(arr)  # returns N x 3
        # top_colors is based on arr.ravel() order
        if top_colors.shape[0] != N:
            # seguridad: recalc
            top_colors = generar_color_por_altura(arr.reshape((nrows, ncols)))
        # bottom use a uniform earthy color
        bottom_color = np.array([0.36, 0.28, 0.18], dtype=np.float32)  # brown-ish
        bottom_colors = np.tile(bottom_color, (N, 1))
        vertex_colors = np.vstack((top_colors, bottom_colors))

    mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_colors=vertex_colors, process=False)
    mesh.remove_duplicate_faces()
    mesh.remove_unreferenced_vertices()
    return mesh


# === PROCESO PRINCIPAL (para pruebas locales) ===
if __name__ == "__main__":
    print("📍 Recortando Ecuador (geojson completo)...")
    tif_ecuador = recortar_tif_by_geojson()

    print("🔄 Suavizando y escalando...")
    arr, profile, transform = suavizar_y_escalar(tif_ecuador, sigma=SIGMA)

    print("🛠 Generando malla sólida y coloreada...")
    mesh = generar_malla_solida(arr, transform, base_altura=None, vs=VSCALE, vertex_color=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = os.path.join(OUTPUT_DIR, ts)
    os.makedirs(job_dir, exist_ok=True)
    stl_path = os.path.join(job_dir, f"ecuador_{ts}.stl")
    glb_path = os.path.join(job_dir, f"ecuador_{ts}.glb")

    print(f"💾 Exportando STL: {stl_path}")
    mesh.export(stl_path)

    print(f"💾 Exportando GLB: {glb_path}")
    mesh.export(glb_path)

    print("✅ Proceso completado.")
