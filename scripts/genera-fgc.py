#!/usr/bin/env python3
"""
Los horarios de FGC (Ferrocarrils de la Generalitat de Catalunya), para la
pestaña Trenes: `public/datos/fgc.json`.

Sale del GTFS abierto de FGC (https://dadesobertes.fgc.cat, conjunto
`gtfs_zip`), pero solo lo que hace falta y compacto: las estaciones (las
«padre», sin andenes), las líneas y los viajes de las próximas tres semanas.
El GTFS entero son 14 MB de horarios; aquí cada viaje es una fila corta que
apunta a un PATRÓN (la lista de estaciones con el tiempo desde la primera),
porque miles de viajes repiten el mismo patrón a otras horas.

Uso:  python3 scripts/genera-fgc.py [carpeta-con-los-txt]
Se rehace cada semana o dos: los servicios de FGC van por fecha.
"""
import csv, io, json, os, sys, urllib.request, datetime, collections

API = 'https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets/gtfs_zip'
DIAS = 21
SALIDA = os.environ.get('SALIDA', 'public/datos/fgc.json')


def ficheros_de_la_api():
    """Los .txt del GTFS, por nombre, tal como los sirve la API de FGC."""
    with urllib.request.urlopen(f'{API}/records?limit=20', timeout=60) as r:
        lista = json.load(r)['results']
    return {x['file']['filename']: x['file']['url'] for x in lista}


def lee(origen, nombre):
    if isinstance(origen, dict):
        with urllib.request.urlopen(origen[nombre], timeout=180) as r:
            return list(csv.DictReader(io.TextIOWrapper(r, encoding='utf-8-sig')))
    return list(csv.DictReader(open(f'{origen}/{nombre}', encoding='utf-8-sig')))


def segundos(h):
    p = [int(x) for x in h.split(':')]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


def main():
    origen = sys.argv[1] if len(sys.argv) > 1 else ficheros_de_la_api()

    paradas = {r['stop_id']: r for r in lee(origen, 'stops.txt')}
    # Cada andén, a su estación: el viaje se cuenta por estaciones.
    padre = {sid: (p['parent_station'] or sid) for sid, p in paradas.items()}
    lineas = {r['route_id']: r for r in lee(origen, 'routes.txt')}
    viajes = {r['trip_id']: r for r in lee(origen, 'trips.txt')}

    hoy = datetime.date.today()
    dias = [hoy + datetime.timedelta(days=i) for i in range(DIAS)]
    activos = collections.defaultdict(set)
    for r in lee(origen, 'calendar_dates.txt'):
        if r['exception_type'] == '1':
            activos[r['service_id']].add(r['date'])
    dias_de = {s: [i for i, d in enumerate(dias) if d.strftime('%Y%m%d') in ds] for s, ds in activos.items()}

    pasos = collections.defaultdict(list)
    for r in lee(origen, 'stop_times.txt'):
        v = viajes.get(r['trip_id'])
        if not v or not dias_de.get(v['service_id']):
            continue
        pasos[r['trip_id']].append((int(r['stop_sequence']), padre.get(r['stop_id'], r['stop_id']),
                                    segundos(r['departure_time'] or r['arrival_time'])))

    lista_est, idx_est = [], {}
    lista_lin, idx_lin = [], {}
    lista_serv, idx_serv = [], {}
    lista_pat, idx_pat = [], {}
    lineas_de = collections.defaultdict(set)
    salida_viajes = []
    for tid, v in pasos.items():
        t = viajes[tid]
        v.sort()
        inicio = v[0][2]
        patron = []
        for _, est, seg in v:
            if est not in idx_est:
                p = paradas[est]
                idx_est[est] = len(lista_est)
                lista_est.append({'id': est, 'nombre': p['stop_name'],
                                  'lat': round(float(p['stop_lat']), 6), 'lon': round(float(p['stop_lon']), 6)})
            lineas_de[est].add(lineas[t['route_id']]['route_short_name'])
            patron.append((idx_est[est], seg - inicio))
        patron = tuple(patron)
        if patron not in idx_pat:
            idx_pat[patron] = len(lista_pat)
            lista_pat.append([list(x) for x in patron])
        r = lineas[t['route_id']]
        if t['route_id'] not in idx_lin:
            idx_lin[t['route_id']] = len(lista_lin)
            lista_lin.append({'nombre': r['route_short_name'], 'color': '#' + (r.get('route_color') or '6b7280')})
        if t['service_id'] not in idx_serv:
            idx_serv[t['service_id']] = len(lista_serv)
            lista_serv.append(dias_de[t['service_id']])
        # El final del id del viaje: con él se cruzan los retrasos en directo
        # (el id entero es `servicio|final`, y el servicio ya va aparte).
        salida_viajes.append([idx_lin[t['route_id']], idx_serv[t['service_id']], t.get('trip_headsign', ''),
                              inicio, idx_pat[patron], tid.split('|')[-1]])

    for e in lista_est:
        e['lineas'] = sorted(lineas_de[e['id']])
    salida = {
        'generado': hoy.isoformat(),
        # Cuándo se generó, con hora (UTC): la web dice «actualizado el 5/10 a las 03:12».
        'generadoEn': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'desde': dias[0].isoformat(),
        'estaciones': lista_est,
        'lineas': lista_lin,
        # Por servicio, los días (desde `desde`, 0 = ese día) en que circula.
        'servicios': lista_serv,
        # [[estación, segundos desde la salida del viaje], …]
        'patrones': lista_pat,
        # [línea, servicio, destino, salida (s desde medianoche), patrón, id]
        'viajes': salida_viajes,
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print(f"{SALIDA}: {len(lista_est)} estaciones, {len(lista_lin)} líneas, "
          f"{len(lista_pat)} patrones, {len(salida_viajes)} viajes")


if __name__ == '__main__':
    main()
