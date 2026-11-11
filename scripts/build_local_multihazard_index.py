#!/usr/bin/env python3
"""Build a local exploratory multi-hazard index for La Carpio's population hexagons."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from pyproj import Transformer
from shapely import STRtree, make_valid, transform, union_all
from shapely.geometry import Polygon, shape


ROOT = Path(__file__).resolve().parents[1]
CAPAS = ROOT / "geovisor" / "capas"
CRS_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:5367", always_xy=True)
DROP_POPULATION_FIELDS = ("DIRECCION", "POBL_MENOR", "POBL_ADULT", "ADULTO_MAY")


def read_geojson(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el insumo requerido: {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def metric_geometries(features: list[dict[str, Any]]) -> tuple[np.ndarray, list[int]]:
    geometries: list[Any] = []
    valid_indexes: list[int] = []
    for idx, feature in enumerate(features):
        raw = feature.get("geometry")
        if not raw:
            continue
        geom = shape(raw)
        if geom.is_empty:
            continue
        geometries.append(geom)
        valid_indexes.append(idx)
    projected = transform(np.asarray(geometries, dtype=object), CRS_METRIC.transform, interleaved=False)
    invalid = ~shapely.is_valid(projected)
    for idx in np.flatnonzero(invalid):
        try:
            repaired = make_valid(projected[idx], method="structure", keep_collapsed=False)
        except Exception:
            try:
                repaired = projected[idx].buffer(0)
            except Exception:
                repaired = Polygon()
        parts = []
        pending = list(getattr(repaired, "geoms", (repaired,)))
        while pending:
            part = pending.pop()
            if part.geom_type in ("Polygon", "MultiPolygon"):
                parts.append(part)
            elif part.geom_type == "GeometryCollection":
                pending.extend(part.geoms)
        projected[idx] = union_all(parts) if parts else Polygon()
    keep = ~shapely.is_empty(projected)
    return projected[keep], [src for src, include in zip(valid_indexes, keep) if include]


def intersected_areas(tree: STRtree, geometries: np.ndarray, target: Any) -> tuple[np.ndarray, np.ndarray]:
    indexes = tree.query(target)
    if len(indexes) == 0:
        return indexes, np.asarray([], dtype=float)
    intersections = shapely.intersection(geometries[indexes], target)
    areas = shapely.area(intersections)
    keep = areas > 1e-7
    return indexes[keep], areas[keep]


def largest_remainder(total: int, weighted_shares: dict[int, float]) -> dict[int, int]:
    weight_sum = sum(weighted_shares.values())
    if total < 0 or weight_sum <= 0:
        raise ValueError("No hay pesos positivos para asignar la población de un sector.")
    exact = {idx: total * weight / weight_sum for idx, weight in weighted_shares.items()}
    allocated = {idx: math.floor(value) for idx, value in exact.items()}
    remainder = total - sum(allocated.values())
    ranked = sorted(exact, key=lambda idx: (-(exact[idx] - allocated[idx]), idx))
    for idx in ranked[:remainder]:
        allocated[idx] += 1
    return allocated


def classify_index(value: float | None) -> str:
    if value is None:
        return "Sin dato"
    if value < 20:
        return "Muy bajo"
    if value < 40:
        return "Bajo"
    if value < 60:
        return "Moderado"
    if value < 80:
        return "Alto"
    return "Muy alto"


def main() -> None:
    hex_fc = read_geojson(CAPAS / "malla_hexagonal_poblacion.geojson")
    landslide_fc = read_geojson(CAPAS / "deslizamientos.geojson")
    flood_fc = read_geojson(CAPAS / "inundaciones.geojson")
    river_fc = read_geojson(CAPAS / "proteccion_rios.geojson")
    sectors_fc = read_geojson(CAPAS / "sectores_estimacion_geojson.geojson")
    incident_fc = read_geojson(CAPAS / "incidentes_cme_2019_2026.geojson")

    hex_features = hex_fc.get("features", [])
    if not hex_features:
        raise ValueError("La malla hexagonal no contiene entidades.")
    hex_geometries, hex_feature_indexes = metric_geometries(hex_features)
    if len(hex_geometries) != len(hex_features):
        raise ValueError("Hay hexágonos sin geometría; no es posible asignar el índice a todos.")
    hex_tree = STRtree(hex_geometries)
    hex_areas = shapely.area(hex_geometries)
    if np.any(hex_areas <= 0):
        raise ValueError("La malla contiene hexágonos con área nula.")

    # Stable IDs: sort projected centroids north-to-south, then west-to-east.
    centroids = shapely.centroid(hex_geometries)
    centroid_xy = shapely.get_coordinates(centroids)
    stable_order = sorted(range(len(hex_features)), key=lambda i: (-round(centroid_xy[i, 1], 2), round(centroid_xy[i, 0], 2)))
    hex_ids = [""] * len(hex_features)
    for sequence, idx in enumerate(stable_order, 1):
        hex_ids[idx] = f"CAR-H{sequence:04d}"

    # Allocate each sector's selected 5.4-persons-per-dwelling estimate to
    # hexagons by existing estimated dwellings, split at sector boundaries.
    sector_features = sectors_fc.get("features", [])
    sector_geometries, sector_source_indexes = metric_geometries(sector_features)
    sector_tree = STRtree(sector_geometries)
    weights_by_sector: dict[str, dict[int, float]] = {}
    population_by_sector: dict[str, int] = {}
    sector_names: dict[str, str] = {}
    for feature_idx in sector_source_indexes:
        props = sector_features[feature_idx].get("properties") or {}
        sector_id = str(props.get("id"))
        name = str(props.get("nombre") or sector_id)
        raw_population = float(props.get("pob_alta_5_4_hab") or 0)
        population = int(round(raw_population))
        if abs(raw_population - population) > 1e-6:
            raise ValueError(f"La población del sector {name} no es un entero: {raw_population}")
        population_by_sector[sector_id] = population
        sector_names[sector_id] = name
        weights_by_sector[sector_id] = {}

    for hex_idx, (hex_geom, hex_area) in enumerate(zip(hex_geometries, hex_areas)):
        properties = hex_features[hex_idx].get("properties") or {}
        homes = max(0.0, float(properties.get("viviendas_estimadas") or 0))
        if homes == 0:
            continue
        sector_indexes, areas = intersected_areas(sector_tree, sector_geometries, hex_geom)
        covered_area = float(areas.sum())
        if covered_area <= 0:
            raise ValueError(f"El hexágono {hex_ids[hex_idx]} tiene viviendas pero no intersecta sectores.")
        for sector_geom_idx, area in zip(sector_indexes, areas):
            source_idx = sector_source_indexes[int(sector_geom_idx)]
            sector_props = sector_features[source_idx].get("properties") or {}
            sector_id = str(sector_props.get("id"))
            # Normalize across intersected sectors so every cell's estimated
            # dwellings are allocated, even where it crosses a sector edge.
            weight = homes * float(area) / covered_area
            weights_by_sector[sector_id][hex_idx] = weights_by_sector[sector_id].get(hex_idx, 0.0) + weight

    population_by_hex = [0] * len(hex_features)
    for sector_id, population in population_by_sector.items():
        sector_weights = weights_by_sector.get(sector_id, {})
        if population > 0 and not sector_weights:
            raise ValueError(f"El sector {sector_names[sector_id]} no tiene hexágonos ponderables.")
        allocation = largest_remainder(population, sector_weights) if population else {}
        for hex_idx, value in allocation.items():
            population_by_hex[hex_idx] += value

    sector_population_total = sum(population_by_sector.values())
    if sector_population_total != 30252:
        raise ValueError(
            f"El campo pob_alta_5_4_hab suma {sector_population_total}, no el total acordado de 30.252."
        )
    if sum(population_by_hex) != sector_population_total:
        raise ValueError("La población asignada a hexágonos no conserva el total sectorial.")

    # Only moderate, high and very-high landslide classes enter the index.
    # Very-low/low classes remain part of mapped coverage but score zero.
    landslide_geometries, landslide_source_indexes = metric_geometries(landslide_fc.get("features", []))
    landslide_categories = np.asarray(
        [
            float((landslide_fc["features"][src_idx].get("properties") or {}).get("CATEGORIA_"))
            for src_idx in landslide_source_indexes
        ],
        dtype=float,
    )
    if np.any((landslide_categories < 1) | (landslide_categories > 5)):
        raise ValueError("CATEGORIA_ de deslizamientos debe estar entre 1 y 5.")
    landslide_scores = np.where(landslide_categories >= 3, (landslide_categories - 1.0) / 4.0, 0.0)
    landslide_tree = STRtree(landslide_geometries)

    # Flood indicator is the fraction of each hex intersecting the mapped
    # potential-inundation polygons; the source does not encode severity.
    flood_geometries, _ = metric_geometries(flood_fc.get("features", []))
    flood_union = union_all(flood_geometries)

    # River-protection polygons are natural-conservation areas.
    river_geometries, river_source_indexes = metric_geometries(river_fc.get("features", []))
    river_tree = STRtree(river_geometries)

    # Historical events are counts for validation, not a score component:
    # 44 records are sparse and do not establish absence of hazard.
    event_geometries: list[Any] = []
    event_properties: list[dict[str, Any]] = []
    for feature in incident_fc.get("features", []):
        raw_geom = feature.get("geometry")
        if not raw_geom:
            continue
        event_geometries.append(transform(shape(raw_geom), CRS_METRIC.transform, interleaved=False))
        event_properties.append(feature.get("properties") or {})
    event_counts = [Counter() for _ in hex_features]
    events_outside_hex = 0
    for point, props in zip(event_geometries, event_properties):
        candidate_indexes = hex_tree.query(point)
        containing = [int(idx) for idx in candidate_indexes if hex_geometries[int(idx)].covers(point)]
        if not containing:
            events_outside_hex += 1
            continue
        hex_idx = min(containing, key=lambda idx: (point.distance(centroids[idx]), idx))
        kind = str(props.get("TIPO_EVENT") or "").strip().upper()
        event_counts[hex_idx]["total"] += 1
        if "DESLIZ" in kind or "DESPRENDIMIENTO" in kind:
            event_counts[hex_idx]["deslizamiento"] += 1
        if "INUNDAC" in kind:
            event_counts[hex_idx]["inundacion"] += 1
        if "INCENDIO" in kind or "CHARRAL" in kind:
            event_counts[hex_idx]["incendio"] += 1

    output_features: list[dict[str, Any]] = []
    restriction_features: list[dict[str, Any]] = []
    land_coverage_values: list[float] = []
    index_values: list[float] = []
    classes: Counter[str] = Counter()
    for hex_idx, (feature, geom, area) in enumerate(zip(hex_features, hex_geometries, hex_areas)):
        candidate_indexes, intersect_areas = intersected_areas(landslide_tree, landslide_geometries, geom)
        covered_area = float(intersect_areas.sum())
        land_coverage_pct = min(100.0, covered_area / float(area) * 100.0) if covered_area > 0 else 0.0
        if covered_area > 0:
            weighted_hazard_area = float(np.dot(intersect_areas, landslide_scores[candidate_indexes]))
            qualifying_area = float(intersect_areas[landslide_categories[candidate_indexes] >= 3].sum())
            land_score_mapped = weighted_hazard_area / qualifying_area if qualifying_area > 0 else None
            land_score = weighted_hazard_area / float(area)
            qualifying_indexes = landslide_categories[candidate_indexes] >= 3
            qualifying_area_pct = min(100.0, float(intersect_areas[qualifying_indexes].sum()) / float(area) * 100.0)
            moderate_indexes = landslide_categories[candidate_indexes] == 3
            high_indexes = landslide_categories[candidate_indexes] == 4
            very_high_indexes = landslide_categories[candidate_indexes] == 5
            moderate_area_pct = min(100.0, float(intersect_areas[moderate_indexes].sum()) / float(area) * 100.0)
            high_area_pct = min(100.0, float(intersect_areas[high_indexes].sum()) / float(area) * 100.0)
            very_high_area_pct = min(100.0, float(intersect_areas[very_high_indexes].sum()) / float(area) * 100.0)
        else:
            land_score_mapped = None
            land_score = None
            high_area_pct = 0.0
            moderate_area_pct = 0.0
            very_high_area_pct = 0.0
            qualifying_area_pct = 0.0

        flood_area = float(shapely.area(shapely.intersection(geom, flood_union))) if not flood_union.is_empty else 0.0
        flood_pct = min(100.0, max(0.0, flood_area / float(area) * 100.0))

        river_indexes, river_areas = intersected_areas(river_tree, river_geometries, geom)
        river_area = float(river_areas.sum())
        river_pct = min(100.0, river_area / float(area) * 100.0)
        river_types: set[str] = set()
        river_distances: set[str] = set()
        for river_geometry_idx in river_indexes:
            src_idx = river_source_indexes[int(river_geometry_idx)]
            river_props = river_fc["features"][src_idx].get("properties") or {}
            if river_props.get("TIPO"):
                river_types.add(str(river_props["TIPO"]))
            if river_props.get("DIST_PROTE"):
                river_distances.add(str(river_props["DIST_PROTE"]))

        river_restriction = river_area > 1e-7
        landslide_restriction = qualifying_area_pct > 0
        if river_restriction and landslide_restriction:
            development_type = "Conservación natural y amenaza por deslizamiento"
        elif river_restriction:
            development_type = "Conservación natural"
        elif landslide_restriction:
            development_type = "Amenaza por deslizamiento"
        else:
            development_type = "No identificada"
        if river_restriction and landslide_restriction:
            development_status = "Conservación natural y deslizamiento moderado/alto/muy alto"
        elif river_restriction:
            development_status = "Conservación natural: protección de río"
        elif landslide_restriction:
            development_status = "Deslizamiento moderado/alto/muy alto"
        elif land_coverage_pct == 0:
            development_status = "Sin cobertura de deslizamientos"
        else:
            development_status = "Sin restricción identificada en las capas revisadas"
        if land_score is None:
            index_value = None
        else:
            index_value = 100.0 * (0.5 * land_score + 0.5 * (flood_pct / 100.0))
            index_values.append(index_value)
        class_name = classify_index(index_value)
        classes[class_name] += 1
        land_coverage_values.append(land_coverage_pct)
        coverage_status = "Sin cobertura" if land_coverage_pct == 0 else ("Completa" if land_coverage_pct >= 99.9 else "Parcial")

        props = dict(feature.get("properties") or {})
        # Keep the requested 5.4 scenario while preventing address and
        # person-count fields from being copied into the output by accident.
        for key in DROP_POPULATION_FIELDS:
            props.pop(key, None)
        props.update(
            {
                "hex_id": hex_ids[hex_idx],
                "pob_esc_5_4_hab": population_by_hex[hex_idx],
                "desliz_score_0_1": round(land_score, 6) if land_score is not None else None,
                "desliz_score_mapeado_0_1": round(land_score_mapped, 6) if land_score_mapped is not None else None,
                "desliz_cobertura_pct": round(land_coverage_pct, 3),
                "estado_cobertura_deslizamientos": coverage_status,
                "desliz_considerada_pct": round(qualifying_area_pct, 3),
                "desliz_alta_pct": round(high_area_pct, 3),
                "desliz_muy_alta_pct": round(very_high_area_pct, 3),
                "desliz_alta_muy_alta_pct": round(high_area_pct + very_high_area_pct, 3),
                "desliz_moderada_pct": round(moderate_area_pct, 3),
                "inundacion_potencial_pct": round(flood_pct, 3),
                "proteccion_rio_pct": round(river_pct, 3),
                "restriccion_proteccion_rio": river_restriction,
                "restriccion_deslizamiento": landslide_restriction,
                "restriccion_desarrollo": development_type,
                "estado_desarrollo": development_status,
                "proteccion_rio_tipo": "; ".join(sorted(river_types)) if river_types else None,
                "proteccion_rio_distancias": "; ".join(sorted(river_distances)) if river_distances else None,
                "incidentes_cme_total_19_26": event_counts[hex_idx]["total"],
                "incidentes_deslizamiento": event_counts[hex_idx]["deslizamiento"],
                "incidentes_inundacion": event_counts[hex_idx]["inundacion"],
                "incidentes_incendio": event_counts[hex_idx]["incendio"],
                "indice_multiamenaza_0_100": round(index_value, 3) if index_value is not None else None,
                "clase_multiamenaza": class_name,
            }
        )
        output_features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": props,
            }
        )
        if river_restriction or landslide_restriction:
            restriction_features.append(
                {
                    "type": "Feature",
                    "geometry": feature["geometry"],
                    "properties": {
                        "hex_id": hex_ids[hex_idx],
                        "estado_desarrollo": development_status,
                        "restriccion_desarrollo": props["restriccion_desarrollo"],
                        "proteccion_rio_pct": props["proteccion_rio_pct"],
                        "proteccion_rio_tipo": props["proteccion_rio_tipo"],
                        "proteccion_rio_distancias": props["proteccion_rio_distancias"],
                        "desliz_alta_muy_alta_pct": props["desliz_alta_muy_alta_pct"],
                        "desliz_considerada_pct": props["desliz_considerada_pct"],
                        "desliz_moderada_pct": props["desliz_moderada_pct"],
                        "pob_esc_5_4_hab": props["pob_esc_5_4_hab"],
                        "indice_multiamenaza_0_100": props["indice_multiamenaza_0_100"],
                    },
                }
            )

    total_homes = sum(float((f.get("properties") or {}).get("viviendas_estimadas") or 0) for f in hex_features)
    if len(output_features) != 304:
        raise ValueError(f"Se esperaban 304 hexágonos y se generaron {len(output_features)}.")
    out = {
        "type": "FeatureCollection",
        "name": "indice_multiamenaza_local_la_carpio",
        "features": output_features,
    }
    output_path = CAPAS / "indice_multiamenaza_local.geojson"
    output_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    restriction_path = CAPAS / "restricciones_desarrollo_hex.geojson"
    restriction_fc = {
        "type": "FeatureCollection",
        "name": "restricciones_desarrollo_hex_la_carpio",
        "features": restriction_features,
    }
    restriction_path.write_text(
        json.dumps(restriction_fc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )

    print(f"Hexágonos generados: {len(output_features)}")
    print(f"Población asignada (escenario 5,4): {sum(population_by_hex):,} hab.; viviendas ponderadas de origen: {total_homes:,.0f}")
    print(f"Cobertura media de deslizamientos: {float(np.mean(land_coverage_values)):.2f}%")
    if index_values:
        print(f"Índice local 0–100: mínimo {min(index_values):.2f}; máximo {max(index_values):.2f}; media {float(np.mean(index_values)):.2f}")
    print("Clases:", json.dumps(dict(classes), ensure_ascii=False))
    print(f"Eventos CME asignados: {sum(c['total'] for c in event_counts)}; fuera de hexágonos: {events_outside_hex}")
    river_count = sum(f["properties"]["restriccion_proteccion_rio"] for f in output_features)
    landslide_count = sum(f["properties"]["restriccion_deslizamiento"] for f in output_features)
    both_count = sum(f["properties"]["restriccion_desarrollo"] == "Conservación natural y amenaza por deslizamiento" for f in output_features)
    print(f"Celdas: conservación natural {river_count}; con deslizamiento moderado/alto/muy alto {landslide_count}; ambas {both_count}; capa de alertas {len(restriction_features)}")
    print(f"Salida: {output_path.relative_to(ROOT)}")
    print(f"Restricciones: {restriction_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
