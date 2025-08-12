# 🌍 Ecuador 3D - Selección, Vista Previa y Exportación de Terreno

Este proyecto permite **seleccionar un área del territorio ecuatoriano en un mapa 3D**, previsualizar su modelo tridimensional y exportarlo en distintos formatos (GLB o STL) para impresión 3D.  

Está construido con **Flask**, **CesiumJS**, **GeoPandas**, **Rasterio** y utilidades personalizadas para procesar datos de elevación (HGT).

---

## 🚀 Características

- *Visualización 3D interactiva* con [CesiumJS](https://cesium.com/cesiumjs/).
- *Selección de áreas* mediante dos clics en el mapa.
- *Vista previa instantánea* del modelo 3D sin necesidad de exportar.
- *Exportación a formatos* .glb y .stl para impresión 3D.
- *Recorte y suavizado de malla* para mejorar el detalle.
- Validación de que la selección esté *dentro de Ecuador* y no exceda un área máxima.
- Backend en *Flask* para procesar la selección y generar el modelo.

---

## 📂 Estructura del Proyecto
```bash
Proyecto/ 
│ 
├── server.py                   # Servidor Flask principal 
├── procesar_ecuador.py         # Funciones de suavizado, escalado y generación de malla 
├── processing.py               # Validaciones de datos y selección 
│ 
├── data/                       # Archivos de datos y GeoJSON 
│   ├── mosaic.tif              # Mosaico de elevaciones (DEM) 
│   └── geoBoundaries-ECU-ADM2_simplified.geojson 
│ 
├── hgt_files/                  # Archivos HGT descargados 
├── outputs/                    # Modelos generados 
│ 
├── web/                        # Interfaz web 
│   ├── index.html              # Visor y controles 
│   ├── viewer.html             # Visor a pantalla completa del modelo 
│   └── widgets.css             # Estilos Cesium 
│ 
└── README.md                   # Este archivo
```
---

## ⚙ Requisitos

### 📌 Dependencias Python
Instálalas con:

```bash
pip install flask flask-cors geopandas rasterio shapely trimesh numpy

```
---
▶ Uso

1. Clonar el repositorio
```bash
git clone https://github.com/tuusuario/ecuador-3d.git
cd ecuador-3d
```


2. Ejecutar el servidor
```
python server.py
```
El servidor estará en:
http://127.0.0.1:5000


4. Interfaz Web

- Botón Iniciar selección → Marca dos puntos en el mapa.

- Botón Vista Previa de Selección → Genera modelo temporal.

- Botón Exportar seleccionado a 3D → Guarda el modelo en /outputs.


---

🎯 Funcionalidades de la Interfaz

- Vista previa directa: Permite ver el modelo sin necesidad de exportar.

- Exportación STL: Compatible con impresión 3D.

- Pantalla completa: Ver el modelo en viewer.html.


---

📷 Capturas de Pantalla

![Imagen del proyecto](/assets/capture01.png)


---

🛠 Tecnologías Utilizadas

- Frontend: HTML, CSS, JavaScript, CesiumJS.

- Backend: Flask, Python.

- Procesamiento GIS: GeoPandas, Shapely, Rasterio.

- Generación de modelos: Trimesh, Numpy.

---