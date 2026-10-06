#!/usr/bin/env python3
"""
Los horarios del metro de Barcelona (TMB), para la pestaña Trenes:
`public/datos/tmb.json`, con el MISMO formato que `fgc.json` (estaciones,
líneas, servicios, patrones y viajes), para que la web lo calcule igual.

Sale del GTFS de TMB (https://developer.tmb.cat, conjunto `static`), que pide
clave: TMB_APP_ID y TMB_APP_KEY en el entorno (en GitHub, sus secretos; nunca
en el repositorio). Solo el metro (route_type 1) y las próximas tres semanas.
Las estaciones son las «padre» (sin andenes), con id `tmb:<código>`: así no
se confunden con las de Rodalies (números) ni FGC (letras). `codi` es el
código de la estación en el tiempo real de TMB (iMetro).

Uso:  TMB_APP_ID=… TMB_APP_KEY=… python3 scripts/genera-tmb.py [gtfs.zip]
Se rehace cada semana (tarea de GitHub del repositorio público).
"""
import csv, io, json, os, sys, urllib.request, zipfile, datetime, collections

DIAS = 21
SALIDA = os.environ.get('SALIDA', 'public/datos/tmb.json')


def segundos(h):
    p = [int(x) for x in h.split(':')]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


def codifica(puntos):
    """La polilínea de Google (precisión 5), como en genera-trazados.py."""
    out, plat, plon = [], 0, 0
    for lat, lon in puntos:
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        for d in (ilat - plat, ilon - plon):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return ''.join(out)


def main():
    if len(sys.argv) > 1:
        z = zipfile.ZipFile(sys.argv[1])
    else:
        ident, clave = os.environ.get('TMB_APP_ID'), os.environ.get('TMB_APP_KEY')
        if not ident or not clave:
            sys.exit('Faltan TMB_APP_ID y TMB_APP_KEY en el entorno.')
        url = f'https://api.tmb.cat/v1/static/datasets/gtfs.zip?app_id={ident}&app_key={clave}'
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url, timeout=300).read()))

    def lee(nombre):
        return [{k.strip(): (v or '').strip() for k, v in f.items()}
                for f in csv.DictReader(io.TextIOWrapper(z.open(nombre), encoding='utf-8-sig'))]

    paradas = {r['stop_id']: r for r in lee('stops.txt')}
    padre = {sid: (p['parent_station'] or sid) for sid, p in paradas.items()}
    lineas = {r['route_id']: r for r in lee('routes.txt') if r['route_type'] == '1'}
    viajes = {r['trip_id']: r for r in lee('trips.txt') if r['route_id'] in lineas}

    # Los días de servicio, desde hoy: calendar.txt y sus excepciones.
    hoy = datetime.date.today()
    dias = [hoy + datetime.timedelta(days=i) for i in range(DIAS)]
    nombres_dia = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    calendario = {r['service_id']: r for r in lee('calendar.txt')} if 'calendar.txt' in z.namelist() else {}
    excepciones = collections.defaultdict(dict)
    for r in lee('calendar_dates.txt'):
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

    servicios = {t['service_id'] for t in viajes.values()}
    dias_de = {s: [i for i, d in enumerate(dias) if activo(s, d)] for s in servicios}

    pasos = collections.defaultdict(list)
    for r in lee('stop_times.txt'):
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
                codigo = p.get('stop_code') or est.split('.')[-1]
                lista_est.append({'id': f'tmb:{codigo}', 'nombre': p['stop_name'], 'codi': int(codigo) % 1000 if codigo.isdigit() else None,
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
        salida_viajes.append([idx_lin[t['route_id']], idx_serv[t['service_id']], t.get('trip_headsign', ''),
                              inicio, idx_pat[patron], ''])

    # Los trazados de cada línea (para el mapa del trayecto en directo), aquí
    # y no en trazados.json: solo esta tarea tiene la clave de TMB.
    forma_linea = {t['shape_id']: lineas[t['route_id']]['route_short_name'] for t in viajes.values() if t.get('shape_id')}
    puntos = collections.defaultdict(list)
    for p in lee('shapes.txt'):
        if p['shape_id'] in forma_linea:
            puntos[p['shape_id']].append((int(p['shape_pt_sequence']), float(p['shape_pt_lat']), float(p['shape_pt_lon'])))
    trazados = collections.defaultdict(list)
    for sid, ps in puntos.items():
        c = codifica([(a, b) for _, a, b in sorted(ps)])
        if c not in trazados[forma_linea[sid]]:
            trazados[forma_linea[sid]].append(c)

    por_id = {e['id']: e for e in lista_est}
    for est, i in idx_est.items():
        lista_est[i]['lineas'] = sorted(lineas_de[est])
    salida = {
        'generado': hoy.isoformat(),
        'generadoEn': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'desde': dias[0].isoformat(),
        'estaciones': lista_est,
        'lineas': lista_lin,
        'servicios': lista_serv,
        'patrones': lista_pat,
        'viajes': salida_viajes,
        # Por línea, sus trazados (polilínea de Google).
        'trazados': dict(sorted(trazados.items())),
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print(f"{SALIDA}: {len(por_id)} estaciones, {len(lista_lin)} líneas, "
          f"{len(lista_pat)} patrones, {len(salida_viajes)} viajes")


if __name__ == '__main__':
    main()
