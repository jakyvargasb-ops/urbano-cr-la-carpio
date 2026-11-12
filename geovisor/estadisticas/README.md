# Tablas base para estadísticas de riesgo y amenaza

Estos CSV se generan desde `geovisor/capas/indice_multiamenaza_local.geojson` mediante:

```bash
python scripts/build_risk_statistics.py
```

## Archivos

- `poblacion_por_hexagono.csv`: tabla base espacial, una fila por celda; conserva la población estimada, categoría del índice, porcentajes de amenazas y banderas de exposición.
- `poblacion_por_categoria_riesgo.csv`: hexágonos, población y porcentaje del total por clase (incluye Sin dato).
- `poblacion_por_sector.csv`: población y celdas por sector. Cada hexágono se asigna al sector con mayor área de intersección para evitar contar su población más de una vez.
- `poblacion_por_combinacion_amenazas.csv`: población por combinación de protección de río, deslizamiento alto/muy alto e inundación potencial. Las combinaciones son mutuamente excluyentes y suman el total.
- `indicadores_principales.csv`: cuatro indicadores resumidos para alimentar un dashboard.

## Indicadores

1. Población por categoría multiamenaza.
2. Población en categoría Alta/Muy Alta o dentro de protección de río.
3. Población dentro de áreas de protección de ríos.
4. Población por combinación de amenazas.

El total de población debe sumar 30.252. Son estimaciones espaciales derivadas del escenario sectorial; no son un censo geocodificado. Las áreas de protección se heredan de la capa de fuente y su inclusión no constituye una delimitación jurídica nueva. Las clases se ordenan del nivel más alto al más bajo. El porcentaje por categorías usa como denominador el total, incluidos los habitantes asociados a celdas Sin dato.
