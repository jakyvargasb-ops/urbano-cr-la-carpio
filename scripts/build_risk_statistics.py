#!/usr/bin/env python3
"""Build reproducible dashboard base tables from the current local index."""
import csv, json
from collections import defaultdict, Counter
from pathlib import Path
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as geom_transform

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'geovisor'/'estadisticas'
INDEX=ROOT/'geovisor'/'capas'/'indice_multiamenaza_local.geojson'
SECTORS=ROOT/'geovisor'/'capas'/'sectores_estimacion_geojson.geojson'
ORDER=['Muy alto','Alto','Moderado','Bajo','Muy bajo','Sin dato']

def write_csv(name, fields, rows):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def main():
    fc=json.loads(INDEX.read_text(encoding='utf-8')); sectors=json.loads(SECTORS.read_text(encoding='utf-8'))
    features=fc['features']; total=sum(int((x['properties'].get('pob_esc_5_4_hab') or 0)) for x in features)
    if total != 30252: raise ValueError(f'Total poblacional inesperado: {total}')
    tr=Transformer.from_crs('EPSG:4326','EPSG:5367',always_xy=True)
    sector_shapes=[]
    for sf in sectors['features']:
        sp=sf.get('properties') or {}; sector_shapes.append((str(sp.get('id','')),str(sp.get('nombre','')),geom_transform(tr.transform,shape(sf['geometry']))))
    cell_rows=[]; category_pop=Counter(); combo_pop=Counter(); sector_pop=Counter(); sector_cells=Counter()
    n_river=n_slide=n_flood=0; pop_river=pop_slide=pop_flood=pop_exposed=0
    for feat in features:
        p=feat['properties']; pop=int(p.get('pob_esc_5_4_hab') or 0); geom=geom_transform(tr.transform,shape(feat['geometry']))
        intersections=[(g.intersection(geom).area, sid,name) for sid,name,g in sector_shapes]
        best=max(intersections,key=lambda x:x[0]) if intersections else (0,'','')
        sid,name=best[1],best[2]
        cls=p.get('clase_multiamenaza') or 'Sin dato'; river=bool(p.get('restriccion_proteccion_rio')); slide=float(p.get('desliz_alta_muy_alta_pct') or 0)>0; flood=float(p.get('inundacion_potencial_pct') or 0)>0
        category_pop[cls]+=pop; sector_pop[(sid,name)]+=pop; sector_cells[(sid,name)]+=1
        combo='; '.join(label for yes,label in [(river,'Protección de río'),(slide,'Deslizamiento alto/muy alto'),(flood,'Inundación potencial') ] if yes) or 'Sin intersección identificada'
        combo_pop[combo]+=pop
        n_river+=river; n_slide+=slide; n_flood+=flood; pop_river+=pop if river else 0; pop_slide+=pop if slide else 0; pop_flood+=pop if flood else 0
        exposed=cls in ('Alto','Muy alto') or river; pop_exposed+=pop if exposed else 0
        cell_rows.append({'hex_id':p.get('hex_id'),'sector_id':sid,'sector':name,'poblacion_estimada':pop,'indice_0_100':p.get('indice_multiamenaza_0_100'),'categoria_multiamenaza':cls,'deslizamiento_alto_muy_alto_pct':p.get('desliz_alta_muy_alta_pct'),'inundacion_potencial_pct':p.get('inundacion_potencial_pct'),'proteccion_rio_pct':p.get('proteccion_rio_pct'),'en_proteccion_rio':river,'expuesto_alto_muy_alto_o_proteccion':exposed,'combinacion_amenazas':combo,'estado_cobertura_deslizamientos':p.get('estado_cobertura_deslizamientos')})
    write_csv('poblacion_por_hexagono.csv',list(cell_rows[0]),cell_rows)
    rows=[]
    for c in ORDER:
        n=sum(1 for x in features if (x['properties'].get('clase_multiamenaza') or 'Sin dato')==c); pop=category_pop[c]
        rows.append({'categoria':c,'hexagonos':n,'poblacion':pop,'porcentaje_poblacion':round(100*pop/total,2)})
    write_csv('poblacion_por_categoria_riesgo.csv',['categoria','hexagonos','poblacion','porcentaje_poblacion'],rows)
    sr=[{'sector_id':sid,'sector':name,'hexagonos':sector_cells[(sid,name)],'poblacion':pop,'porcentaje_total':round(100*pop/total,2)} for (sid,name),pop in sorted(sector_pop.items())]
    write_csv('poblacion_por_sector.csv',['sector_id','sector','hexagonos','poblacion','porcentaje_total'],sr)
    cr=[{'combinacion_amenazas':key,'poblacion':val,'porcentaje_total':round(100*val/total,2)} for key,val in sorted(combo_pop.items())]
    write_csv('poblacion_por_combinacion_amenazas.csv',['combinacion_amenazas','poblacion','porcentaje_total'],cr)
    indicators=[
      {'id':'I1','indicador':'Población por categoría multiamenaza','valor':json.dumps(dict((c,category_pop[c]) for c in ORDER),ensure_ascii=False),'unidad':'habitantes por categoría','denominador':total},
      {'id':'I2','indicador':'Población expuesta a riesgo Alto/Muy alto o protección de río','valor':pop_exposed,'unidad':'habitantes','denominador':total},
      {'id':'I3','indicador':'Población dentro de protección de ríos','valor':pop_river,'unidad':'habitantes','denominador':total},
      {'id':'I4','indicador':'Población por combinación de amenazas','valor':json.dumps(dict(combo_pop),ensure_ascii=False),'unidad':'habitantes por combinación no excluyente','denominador':total},
    ]
    write_csv('indicadores_principales.csv',['id','indicador','valor','unidad','denominador'],indicators)
    print(f'Hexágonos: {len(features)}; población: {total}; expuesta: {pop_exposed}; protección de ríos: {pop_river}; slide alto/muy alto: {pop_slide}; inundación: {pop_flood}')
    print(f'Categorias: {dict((c,category_pop[c]) for c in ORDER)}')
if __name__=='__main__': main()
