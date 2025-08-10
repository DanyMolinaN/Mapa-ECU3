#!/usr/bin/env python3
"""
prepare_merge.py
Unir todos los .hgt en hgt_files/ a data/mosaic.tif y mostrar/guardar preview.
"""

import os
import glob
import numpy as np
import rasterio
from rasterio.merge import merge
import matplotlib.pyplot as plt

# RUTAS (ajusta si quieres)
ROOT = os.path.dirname(os.path.dirname(__file__))  # carpeta proyecto/scripts/.. => proyecto
HGT_DIR = os.path.join(ROOT, "hgt_files")
OUT_DIR = os.path.join(ROOT, "data")
os.makedirs(OUT_DIR, exist_ok=True)

# Buscar .hgt
hgt_files = sorted(glob.glob(os.path.join(HGT_DIR, "*.hgt")))
if not hgt_files:
    raise SystemExit(f"No se encontraron archivos .hgt en {HGT_DIR}. Colócalos ahí y vuelve a correr.")

print(f"Encontrados {len(hgt_files)} archivos .hgt. Haciendo merge...")

# Abrir y agregar a lista
src_files_to_mosaic = [rasterio.open(fp) for fp in hgt_files]

# Hacer merge (mosaic)
mosaic, out_trans = merge(src_files_to_mosaic)
# mosaic shape: (bands, rows, cols)
arr = mosaic[0].astype("float32")

# Intentar detectar nodata (común: -32768)
nodata = src_files_to_mosaic[0].nodata
if nodata is None:
    nodata = -32768
arr[arr == nodata] = np.nan

# Metadata de salida (GeoTIFF)
out_meta = src_files_to_mosaic[0].meta.copy()
out_meta.update({
    "driver": "GTiff",
    "height": arr.shape[0],
    "width": arr.shape[1],
    "transform": out_trans,
    "count": 1,
    "dtype": "float32",
    "crs": src_files_to_mosaic[0].crs
})

out_tif = os.path.join(OUT_DIR, "mosaic.tif")
with rasterio.open(out_tif, "w", **out_meta) as dest:
    dest.write(arr, 1)

print("Mosaic guardado en:", out_tif)
# No optimizaodo
'''''
# --- Preview gráfico y guardado ---
left = out_trans.c
top = out_trans.f
right = left + out_trans.a * arr.shape[1]
bottom = top + out_trans.e * arr.shape[0]

plt.figure(figsize=(10,6))
plt.imshow(arr, extent=(left, right, bottom, top))
plt.xlabel("Longitud")
plt.ylabel("Latitud")
plt.title("Vista previa del mosaico (elevación [m])")
cbar = plt.colorbar()
cbar.set_label("Elevación (m)")
preview_png = os.path.join(OUT_DIR, "mosaic_preview.png")
plt.savefig(preview_png, dpi=150, bbox_inches='tight')
print("Preview guardado en:", preview_png)
plt.show()
'''
# Otimizado
# --- Preview gráfico y guardado ---
left = out_trans.c
top = out_trans.f
right = left + out_trans.a * arr.shape[1]
bottom = top + out_trans.e * arr.shape[0]

# Reducir resolución para evitar consumir mucha RAM
factor_preview = 10  # aumenta este número para reducir más
arr_preview = arr[::factor_preview, ::factor_preview]

plt.figure(figsize=(10, 6))
plt.imshow(arr_preview, extent=(left, right, bottom, top))
plt.xlabel("Longitud")
plt.ylabel("Latitud")
plt.title("Vista previa del mosaico (elevación [m])")
cbar = plt.colorbar()
cbar.set_label("Elevación (m)")
preview_png = os.path.join(OUT_DIR, "mosaic_preview.png")
plt.savefig(preview_png, dpi=150, bbox_inches='tight')
print("Preview guardado en:", preview_png)
plt.show()