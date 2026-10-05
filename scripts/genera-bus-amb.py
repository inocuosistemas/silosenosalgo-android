#!/usr/bin/env python3
"""
Los autobuses del AMB que llegan a las estaciones de Rodalies de la zona, para
la pestaña Trenes (ir a la estación en bus): `public/datos/bus-amb.json`.

Sale del GTFS abierto del AMB (https://www.ambmobilitat.cat/OpenData/google_transit.zip),
pero solo lo que hace falta: las líneas que paran a menos de 200 m de alguna de
las estaciones de `ESTACIONES` y las de `LINEAS_SIEMPRE`, sus paradas, y las
salidas de las próximas tres semanas. La red entera son ~900.000 pasos; esto, unos cientos de KB.

Uso:  python3 scripts/genera-bus-amb.py [google_transit.zip]
Se rehace cada semana o dos (los servicios del AMB van casi por fecha).
"""
import csv, io, json, math, os, sys, urllib.request, zipfile, datetime, collections

# Las estaciones de Rodalies donde se mira: código de Adif, lat, lon. De
# momento, la de Viladecans; se añaden aquí.
ESTACIONES = {'71709': (41.3095086, 2.02741857)}
CERCA_M = 200
# Y las líneas que se cargan siempre, pasen o no junto a una estación (para un
# tramo de bus entre dos paradas cualesquiera). Se añaden aquí por su nombre.
LINEAS_SIEMPRE = {'L97'}
DIAS = 21
SALIDA = os.environ.get('SALIDA', 'public/datos/bus-amb.json')


def dist(a, b, c, d):
    r = math.pi / 180
    x = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def lee(z, nombre):
    return csv.DictReader(io.TextIOWrapper(z.open(nombre), encoding='utf-8-sig'))


def segundos(h):
    p = [int(x) for x in h.split(':')]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


def main():
    if len(sys.argv) > 1:
        z = zipfile.ZipFile(sys.argv[1])
    else:
        datos = urllib.request.urlopen('https://www.ambmobilitat.cat/OpenData/google_transit.zip', timeout=120).read()
        z = zipfile.ZipFile(io.BytesIO(datos))

    paradas = {r['stop_id']: r for r in lee(z, 'stops.txt')}
    lineas = {r['route_id']: r for r in lee(z, 'routes.txt')}
    viajes = {r['trip_id']: r for r in lee(z, 'trips.txt')}

    # Las paradas de cada estación.
    de_estacion = {}
    for sid, p in paradas.items():
        for est, (la, lo) in ESTACIONES.items():
            if dist(la, lo, float(p['stop_lat']), float(p['stop_lon'])) <= CERCA_M:
                de_estacion[sid] = est

    # Los pasos de cada viaje, y qué viajes tocan una estación.
    pasos = collections.defaultdict(list)
    for r in lee(z, 'stop_times.txt'):
        pasos[r['trip_id']].append((int(r['stop_sequence']), r['stop_id'], segundos(r['departure_time'] or r['arrival_time'])))
    rutas = {viajes[t]['route_id'] for t, v in pasos.items() if t in viajes and any(s in de_estacion for _, s, _ in v)}
    rutas |= {rid for rid, l in lineas.items() if l['route_short_name'] in LINEAS_SIEMPRE}

    # Los días de servicio, desde hoy.
    hoy = datetime.date.today()
    dias = [hoy + datetime.timedelta(days=i) for i in range(DIAS)]
    nombres_dia = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    calendario = {r['service_id']: r for r in lee(z, 'calendar.txt')}
    excepciones = collections.defaultdict(dict)
    for r in lee(z, 'calendar_dates.txt'):
        excepciones[r['service_id']][r['date']] = r['exception_type']

    def activo(servicio, d):
        k = d.strftime('%Y%m%d')
        e = excepciones[servicio].get(k)
        if e == '1':
            return True
        if e == '2':
            return False
        c = calendario.get(servicio)
        return bool(c) and c[nombres_dia[d.weekday()]] == '1' and c['start_date'] <= k <= c['end_date']

    # Lo que se guarda: paradas usadas, líneas, servicios con sus días, y
    # viajes como [línea, servicio, destino, [[parada, segundos], …]].
    usadas, lista_paradas, idx_parada = set(), [], {}
    lista_lineas, idx_linea = [], {}
    lista_servicios, idx_servicio = [], {}
    salida_viajes = []
    for tid, v in pasos.items():
        t = viajes.get(tid)
        if not t or t['route_id'] not in rutas:
            continue
        dias_activo = [i for i, d in enumerate(dias) if activo(t['service_id'], d)]
        if not dias_activo:
            continue
        v.sort()
        for _, s, _ in v:
            if s not in idx_parada:
                p = paradas[s]
                idx_parada[s] = len(lista_paradas)
                lista_paradas.append({
                    'id': s, 'nombre': p['stop_name'],
                    'lat': round(float(p['stop_lat']), 6), 'lon': round(float(p['stop_lon']), 6),
                    **({'estacion': de_estacion[s]} if s in de_estacion else {}),
                })
        r = lineas[t['route_id']]
        if t['route_id'] not in idx_linea:
            idx_linea[t['route_id']] = len(lista_lineas)
            lista_lineas.append({'nombre': r['route_short_name'], 'color': '#' + (r.get('route_color') or 'ffaa00')})
        if t['service_id'] not in idx_servicio:
            idx_servicio[t['service_id']] = len(lista_servicios)
            lista_servicios.append(dias_activo)
        salida_viajes.append([idx_linea[t['route_id']], idx_servicio[t['service_id']], t.get('trip_headsign', ''),
                              [[idx_parada[s], seg] for _, s, seg in v]])

    salida = {
        'generado': hoy.isoformat(),
        # Cuándo se generó, con hora (UTC): la web dice «actualizado el 5/10 a las 03:12».
        'generadoEn': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'desde': dias[0].isoformat(),
        'estaciones': list(ESTACIONES.keys()),
        'paradas': lista_paradas,
        'lineas': lista_lineas,
        # Por servicio, los días (desde `desde`, 0 = ese día) en que circula.
        'servicios': lista_servicios,
        'viajes': salida_viajes,
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print(f"{SALIDA}: {len(lista_lineas)} líneas ({', '.join(sorted(l['nombre'] for l in lista_lineas))}), "
          f"{len(lista_paradas)} paradas, {len(salida_viajes)} viajes")


if __name__ == '__main__':
    main()
