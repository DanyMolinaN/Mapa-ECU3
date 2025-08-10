import os
import uuid
import geopandas as gpd
from shapely.geometry import box, mapping
import rasterio
from rasterio.mask import mask
import numpy as np
import trimesh
from datetime import datetime
from pyproj import Transformer

# Config (puedes ajustarlo)
OUTPUTS_DIR = "outputs"

# ------------------------------
# Validar que existan archivos HGT
# ------------------------------
def validar_archivos_hgt(hgt_dir):
    archivos = [f for f in os.listdir(hgt_dir) if f.lower().endswith(".hgt")]
    if not archivos:
        raise Exception("No se encontraron archivos .hgt en la carpeta hgt_files.")
    return archivos

# ------------------------------
# Validar que selección esté en Ecuador y no sea muy grande
# ------------------------------
def validar_seleccion_ecuador(geom, frontera_ecuador, max_area_km2):
    inter = geom.intersection(frontera_ecuador)
    if inter.is_empty:
        raise Exception("La selección está fuera de Ecuador.")
    # área aproximada (grados -> km2)
    area_km2 = inter.area * (111 ** 2)
    if area_km2 > max_area_km2:
        raise Exception(f"Área demasiado grande: {area_km2:.1f} km² (máx {max_area_km2} km²)")
    return inter

# ------------------------------
# Convertir raster recortado a malla (y centrarla)
# ------------------------------
def raster_to_mesh_and_center(elev_array, transform, geo_transform_crs_lat):
    """
    elev_array: 2D numpy (rows, cols) en metros (altura)
    transform: affine transform del raster recortado (rasterio transform)
    geo_transform_crs_lat: latitud media para convertir grados->metros si es necesario (no usado si transform está en metros)
    """
    rows, cols = elev_array.shape
    # generar coordenadas x,y en lon/lat usando transform
    # transform * (col, row) -> (x, y) (en CRS del raster -- normalmente degrees)
    xs = np.arange(cols)
    ys = np.arange(rows)
    xv, yv = np.meshgrid(xs, ys)

    # calcular coordenadas geográficas (xg, yg) usando transform
    # transform.c, transform.a etc. are available via rasterio.transform
    from rasterio.transform import xy
    coords = [xy(transform, r, c) for r, c in zip(yv.ravel(), xv.ravel())]
    xs_geo = np.array([c[0] for c in coords])
    ys_geo = np.array([c[1] for c in coords])

    # convertir lon/lat (deg) a metros aproximados relativos (usamos proyección local)
    # si la unidad del raster es grados, convertir a metros usando una proyección local basada en latitud media
    # estimar latitud media:
    lat_mean = np.mean(ys_geo)
    # metros por grado aproximado
    meters_per_deg = 111320 * np.cos(np.deg2rad(lat_mean))
    xs_m = (xs_geo - np.mean(xs_geo)) * meters_per_deg
    ys_m = (ys_geo - np.mean(ys_geo)) * meters_per_deg

    zs = np.nan_to_num(elev_array.ravel(), nan=0.0)

    verts = np.column_stack((xs_m, ys_m, zs))
    faces = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            i = r * cols + c
            faces.append([i, i + 1, i + cols])
            faces.append([i + 1, i + cols + 1, i + cols])

    return verts, np.array(faces)

# ------------------------------
# Procesar y exportar selección a GLB
# ------------------------------
def clip_and_process_job(geom, hgt_dir):
    """
    geom in EPSG:4326 (Shapely geometry)
    Busca HGT que intersecten, recorta, genera malla y exporta GLB.
    Devuelve (job_id, glb_filename)
    """
    job_id = str(uuid.uuid4())
    output_dir = os.path.join(OUTPUTS_DIR, job_id)
    os.makedirs(output_dir, exist_ok=True)

    # GeoDataFrame con la geometría (en EPSG:4326)
    gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")

    merged = None
    merged_transform = None
    used_any = False

    # Recorrer archivos .hgt
    for fn in os.listdir(hgt_dir):
        if not fn.lower().endswith(".hgt"):
            continue
        path = os.path.join(hgt_dir, fn)
        try:
            with rasterio.open(path) as src:
                # asegurarse de que la geometría esté en la misma CRS que el raster
                raster_crs = src.crs.to_string() if src.crs else "EPSG:4326"
                if raster_crs.upper() != "EPSG:4326":
                    gdf_in_src = gdf.to_crs(src.crs)
                    geom_in_src = gdf_in_src.geometry.values[0]
                else:
                    geom_in_src = gdf.geometry.values[0]

                tile_box = box(*src.bounds)
                # transform geom to raster CRS when comparing
                if src.crs and src.crs.to_string().upper() != "EPSG:4326":
                    # ensure tile_box and geom_in_src are same CRS already above
                    pass

                if not geom_in_src.intersects(tile_box):
                    continue

                # intentar recorte - pasar lista de geometrías como mapping()
                try:
                    out_image, out_transform = mask(src, [mapping(geom_in_src)], crop=True, all_touched=False)
                except Exception as e:
                    # si falla el mask para este tile, continuar
                    print(f"[processing] mask failed for {fn}: {e}")
                    continue

                # out_image shape: (bands, rows, cols), HGT suele tener 1 banda
                band = out_image[0].astype(float)

                # manejar nodata
                nod = src.nodatavals[0] if src.nodatavals else None
                if nod is not None:
                    band[band == nod] = np.nan

                if merged is None:
                    merged = band
                    merged_transform = out_transform
                else:
                    # alinear shapes si difieren (sencillo: pad arrays to same shape)
                    # aquí asumimos mismos tamaños por crop similar; si difieren, hacemos pad
                    if band.shape != merged.shape:
                        # compute new shape
                        rmax = max(merged.shape[0], band.shape[0])
                        cmax = max(merged.shape[1], band.shape[1])
                        mnew = np.full((rmax, cmax), np.nan)
                        bnew = np.full((rmax, cmax), np.nan)
                        # place merged at top-left
                        mnew[:merged.shape[0], :merged.shape[1]] = merged
                        bnew[:band.shape[0], :band.shape[1]] = band
                        merged = np.nanmax(np.stack([mnew, bnew], axis=0), axis=0)
                    else:
                        merged = np.nanmax(np.stack([merged, band], axis=0), axis=0)
                used_any = True
        except Exception as e:
            print(f"[processing] error reading {path}: {e}")
            continue

    if not used_any or merged is None:
        raise Exception("No se encontraron datos HGT para la selección (merged empty).")

    # comprobar si hay valores válidos
    if np.isnan(merged).all():
        raise Exception("Los datos resultantes contienen solo nodata/NaN. Selección sin cobertura HGT.")

    # reducir resolución si muy grande para evitar mallado enorme (opcional)
    max_pixels = 1200 * 1200  # límite
    rows, cols = merged.shape
    if rows * cols > max_pixels:
        factor = np.sqrt((rows * cols) / max_pixels)
        new_rows = max(2, int(rows / factor))
        new_cols = max(2, int(cols / factor))
        # remuestrear por simple rebin (media)
        merged = resize_array_by_mean(merged, new_rows, new_cols)
        # NOTE: transform loses exactness; acceptable para preview/export reduced

    # crear malla y exportar glb
    verts, faces = raster_to_mesh_and_center(merged, merged_transform, None)
    # evitar malla degenerada
    if verts.shape[0] < 4 or faces.shape[0] < 1:
        raise Exception("La malla generada es degenerada (pocos vértices).")

    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    if not mesh.is_watertight and mesh.vertices.shape[0] < 100000:
        # ok, no es requisito watertight para GLB, sigue
        pass

    glb_filename = f"ecuador_{datetime.now().strftime('%Y%m%d_%H%M%S')}.glb"
    glb_path = os.path.join(output_dir, glb_filename)
    mesh.export(glb_path)

    return job_id, glb_filename

# helper: simple downsample by block mean
def resize_array_by_mean(arr, new_r, new_c):
    r, c = arr.shape
    rr = np.linspace(0, r, new_r+1, dtype=int)
    cc = np.linspace(0, c, new_c+1, dtype=int)
    out = np.full((new_r, new_c), np.nan)
    for i in range(new_r):
        for j in range(new_c):
            block = arr[rr[i]:rr[i+1], cc[j]:cc[j+1]]
            if block.size == 0:
                out[i,j] = np.nan
            else:
                val = np.nanmean(block)
                out[i,j] = val
    return out
