# Índice local de multiamenaza por hexágono — La Carpio

**Estado:** cálculo exploratorio en revisión técnica. No equivale a una clasificación oficial ni a un mapa completo de todos los peligros.

## Insumos

- `malla_hexagonal_poblacion.geojson`: 2.470 hexágonos de 20 m entre vértices opuestos, recortados al perímetro de estudio.
- `deslizamientos.geojson`: polígonos con categorías `CATEGORIA_` (1–5) y nombres `AMENAZ_DES` (muy baja a muy alta).
- `inundaciones.geojson`: huellas de inundación potencial (`ORIGEN_COB`); no contiene severidad ni periodo de retorno.
- `proteccion_rios.geojson`: polígonos de protección con `TIPO` y `DIST_PROTE`; se usan como restricción urbana, no como puntaje de amenaza.
- `sectores_estimacion_geojson.geojson`: población sectorial del escenario alto `pob_alta_5_4_hab`, cuya suma acordada es 30.252.
- `incidentes_cme_2019_2026.geojson`: puntos de incidentes con `TIPO_EVENT`, `FECHA` y geometría.

Todos los cálculos de área se realizan en CRTM05 (EPSG:5367); el GeoJSON de salida conserva las geometrías de la malla en EPSG:4326.

## Cálculo del índice

Para cada hexágono se calcula:

1. **Susceptibilidad a deslizamientos.** Solo entran al índice las categorías `CATEGORIA_` 4 y 5 (ALTA y MUY ALTA), con puntajes 0,75 y 1. Las categorías 1, 2 y 3 no aportan puntaje, aunque sí cuentan en `desliz_cobertura_pct`. `desliz_score_mapeado_0_1` promedia las categorías consideradas, ponderadas por área. `desliz_score_0_1` pondera por el área completa del hexágono, por lo que una intersección parcial aporta solo en su proporción. Se reportan `desliz_considerada_pct`, los porcentajes moderada/alta/muy alta y el estado de cobertura.
2. **Inundación potencial (`inundacion_potencial_pct`).** Porcentaje del área del hexágono que intersecta los polígonos de inundación. Es cobertura cartográfica, no profundidad ni intensidad.
3. **Puntaje compuesto exploratorio:**

   `indice_multiamenaza_0_100 = 100 × (0,5 × desliz_score_0_1 + 0,5 × inundacion_potencial_pct / 100)`

   Se usan pesos iguales como escenario inicial transparente, no como ponderación institucional aprobada. Se aplican clases fijas: 0–<20 muy bajo, 20–<40 bajo, 40–<60 moderado, 60–<80 alto y 80–100 muy alto. Si no hay intersección con el mapa de deslizamientos, el índice queda nulo y la clase es `Sin dato`; la falta de cobertura no se interpreta como amenaza cero. Si la cobertura es parcial, el campo `estado_cobertura_deslizamientos` permite advertirlo al interpretar la puntuación.
4. **Incidentes CME.** Se cuentan por tipo y hexágono (`incidentes_cme_total_19_26`, `incidentes_deslizamiento`, `incidentes_inundacion`, `incidentes_incendio`). Son evidencia histórica para contraste, no componente del puntaje, por la cantidad limitada de registros y su dependencia de la notificación.

## Restricciones para el desarrollo urbano

Las zonas de protección de río se incorporan al índice como condición MUY ALTA (puntaje 100) porque existe población asentada en estos espacios. La población de esas celdas se incluye en el total expuesto; la cartografía usada es la capa recibida, no un deslinde jurídico nuevo. Las categorías de deslizamiento ALTA y MUY ALTA (4–5) se consideran en el índice y se marcan en la capa de alertas para planificación. Las categorías MUY BAJA y BAJA (1–2) no se consideran para el puntaje ni activan esta alerta. Los incidentes CME siguen siendo conteos de contraste, no componentes del índice.

La capa `restricciones_desarrollo_hex.geojson` incluye celdas que intersectan protección de río o deslizamiento categoría 4–5: verde para protección de río, rojo para deslizamiento y morado para el solape. Si la intersección es parcial, se resalta el hexágono completo; los porcentajes de solape y las capas fuente permiten consultar el alcance real. Este criterio de planificación no sustituye delimitaciones normativas ni validación legal de las autoridades competentes.
## Distribución de población de 30.252

La malla original no contiene un campo por hexágono para el escenario 5,4. Se distribuye la población de cada sector desde `pob_alta_5_4_hab` usando como peso las `viviendas_estimadas` de los hexágonos que intersectan su polígono. Cuando un hexágono cruza sectores, sus viviendas se reparten según la proporción de área de intersección. Dentro de cada sector se normalizan los pesos y se aplica el método de mayores restos para que las asignaciones sean enteras y conserven exactamente el total sectorial. El nuevo campo es `pob_esc_5_4_hab`.

La asignación se realiza por geometría porque el atributo `sector` está vacío en algunas celdas y no constituye una llave espacial completa. El valor 30.252 es un escenario estimado, no un censo observado a nivel de hexágono. Por ello, `pob_esc_5_4_hab` representa una distribución del total sectorial y no una medición independiente de cada celda.

## Límites y decisiones pendientes

- El índice combina solo las dos amenazas cartografiadas con atributos utilizables en la escala de la malla: susceptibilidad a deslizamientos e inundación potencial.
- La capa de inundación solo permite medir superposición. No proporciona clases de intensidad, frecuencia o periodo de retorno.
- Los incidentes 2019–2026 son escasos respecto de los 304 hexágonos; cero incidentes reportados no significa ausencia de peligro.
- `Pendientes_AID.GRIDCODE` toma valores 0–89, pero su significado y unidades no están documentados en los insumos revisados. Se excluye hasta confirmar su semántica y su posible redundancia con la capa de deslizamientos.
- No se encontró una capa local de amenaza sísmica. El índice no representa todas las amenazas posibles.
- Las clases y el peso 50/50 son exploratorios y deben someterse a revisión y sensibilidad antes de usarse para asignar recursos o declarar niveles oficiales.

## Reproducir el resultado

Desde la raíz del repositorio:

```bash
python scripts/build_local_multihazard_index.py
```

El script genera `geovisor/capas/indice_multiamenaza_local.geojson`, que se declara en `geovisor/layers.json`.
También genera `geovisor/capas/restricciones_desarrollo_hex.geojson` para visualizar conservación natural y celdas con amenaza por deslizamiento moderada, alta o muy alta.


## Tablas estadísticas para dashboard

Las tablas base se encuentran en `geovisor/estadisticas/`. Incluyen población por hexágono, categoría de multiamenaza, sector y combinación de amenazas, además de `indicadores_principales.csv`. Se regeneran con `python scripts/build_risk_statistics.py`. La asignación por sector usa el sector con mayor área de intersección por celda para no duplicar población; las combinaciones de amenazas son excluyentes. La población en protección de ríos forma parte de Muy Alta y del total expuesto.
