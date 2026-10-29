#!/usr/bin/env python3
"""
Los autobuses exprés de Sagalés (e4, e7, e9, e10, e12, e13, e19, e21 y e26;
https://www.sagales.com/es/lineas/4/lineas-expres), para la pestaña Trenes:
`public/datos/bus-expres.json`, con el MISMO formato que `bus-amb.json`
(paradas, líneas, servicios y viajes), para que la web los junte con los del
AMB y los use igual (ver `juntaBuses` en `src/lib/transporte/busAmb.ts`).

Sagalés no tiene API abierta, pero sus exprés son líneas de la Generalitat
(exprés.cat) y salen en el GTFS abierto de los autobuses interurbanos de la
Generalitat (Departament de Territori; Llicència oberta d'ús d'informació de
Catalunya: se cita la fuente y la fecha de sus datos, que van en el fichero).
Lo publican una vez al mes: https://territori.gencat.cat/ca/serveis/visors-cartografia/bases-cartografiques/infraestructures-mobilitat/autobusos-interurbans/
Solo las líneas de `LINEAS` y las salidas de las próximas tres semanas, con
los trazados de cada línea (su `shapes.txt`) para el mapa.

Uso:  python3 scripts/genera-bus-expres.py [busos-interurbans-GTFS.zip]
Se rehace cada semana (las salidas van por fecha y cubren tres semanas).
"""
import csv, io, json, os, re, sys, urllib.request, zipfile, datetime, collections, email.utils

GTFS = ('https://territori.gencat.cat/web/.content/home/serveis/visors-cartografia/bases-cartografiques/'
        'infraestructures-mobilitat/autobusos-interurbans/busos-interurbans-GTFS.zip')
FUENTE = 'Generalitat de Catalunya. Departament de Territori, Habitatge i Transició Ecològica'
# Las exprés de la web de Sagalés, por su código de línea en la Generalitat
# (route_id; el route_short_name es «L» y el código) y con el nombre que
# lleva el bus. Dos códigos pueden ser la misma línea: las e9 a Sant Feliu de
# Codines y a Santa Maria d'Oló, que la Generalitat aún llama «212 213».
LINEAS = {
    '0885': 'e4',   # Girona - Vidreres - Lloret de Mar
    '1614': 'e7',   # Barcelona - la Vall del Tenes
    '0199': 'e9',   # Barcelona - Caldes de Montbui
    '0128': 'e9',   # Barcelona - Sant Feliu de Codines - Santa Maria d'Oló
    '0687': 'e10',  # Barcelona - Santa Perpètua - Sentmenat
    '1691': 'e12',  # Barcelona - Vic
    '0494': 'e13',  # Mataró - Granollers - Sabadell
    '0786': 'e19',  # Barcelona - Alella - Vallromanes - Vilanova del Vallès
    '0310': 'e21',  # Barcelona - Mollet del Vallès
    '2161': 'e26',  # Parets del Vallès - Mollet del Vallès - Barcelona
}
# El GTFS no trae colores: uno para todas (blanco encima se lee bien).
COLOR = '#c8102e'
DIAS = 21
SALIDA = os.environ.get('SALIDA', 'public/datos/bus-expres.json')


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


def aclara(puntos, m=8):
    """Sin los puntos a menos de `m` metros del anterior (y siempre el último): el mapa no los nota."""
    out = []
    for p in puntos:
        if out:
            dy = (p[0] - out[-1][0]) * 111_195
            dx = (p[1] - out[-1][1]) * 83_500
            if dx * dx + dy * dy < m * m:
                continue
        out.append(p)
    if puntos and out[-1] != puntos[-1]:
        out.append(puntos[-1])
    return out


# Lo que el nombre de la parada lleva de más: el código del poste («MB0395»,
# «PNL», «MNG», «Ms») y el lado de la calle («(A)», «(D)»). Sin el lado, los
# dos postes de la parada se llaman igual y la web los junta (como en el AMB).
CODIGOS = re.compile(r'\s+(?:MB\d+|PNL|MNG|Ms)\b')
LADO = re.compile(r'\s*\([AD]\)')


def limpia(nombre):
    n = re.sub(r'\s+', ' ', LADO.sub('', CODIGOS.sub('', nombre))).strip()
    return n[:1].upper() + n[1:]


def descripcion(nombre_largo):
    """«(e9) Barcelona - Caldes de Montbui» → «Barcelona - Caldes de Montbui»."""
    return re.sub(r'^(?:\([^)]*\)\s*|Expres\.cat\s+E\d+\s+)', '', nombre_largo).strip()


def main():
    if len(sys.argv) > 1:
        z = zipfile.ZipFile(sys.argv[1])
        # Sin la fecha del servidor, la de los ficheros de dentro.
        fecha_fuente = max(datetime.date(*i.date_time[:3]) for i in z.infolist())
    else:
        req = urllib.request.Request(GTFS, headers={'User-Agent': 'Mozilla/5.0 (SiLoSeNoSalgo)'})
        with urllib.request.urlopen(req, timeout=300) as r:
            datos = r.read()
            modificado = r.headers.get('Last-Modified')
        z = zipfile.ZipFile(io.BytesIO(datos))
        fecha_fuente = (email.utils.parsedate_to_datetime(modificado).date() if modificado
                        else max(datetime.date(*i.date_time[:3]) for i in z.infolist()))

    def lee(nombre):
        return csv.DictReader(io.TextIOWrapper(z.open(nombre), encoding='utf-8-sig'))

    rutas = {r['route_id']: r for r in lee('routes.txt') if r['route_id'] in LINEAS}
    faltan = sorted(set(LINEAS) - set(rutas))
    if faltan:
        # La Generalitat ha cambiado algún código: se sigue con las demás.
        print(f'Aviso: no están en el GTFS las líneas {", ".join(faltan)}', file=sys.stderr)
    viajes = {t['trip_id']: t for t in lee('trips.txt') if t['route_id'] in rutas}
    # Algún viaje de estas líneas lleva otro número en el bus («Aquesta
    # expedició constitueix el codi comercial 644», en su `nota.txt`): ese no
    # es un exprés.
    if 'nota.txt' in z.namelist():
        otro = {r['trip_id'] for r in lee('nota.txt') if r['trip_id'] in viajes and 'codi comercial' in (r.get('nota') or '')}
        viajes = {k: t for k, t in viajes.items() if k not in otro}
    paradas = {r['stop_id']: r for r in lee('stops.txt')}

    # Los días de servicio, desde hoy (como en genera-bus-amb.py).
    hoy = datetime.date.today()
    dias = [hoy + datetime.timedelta(days=i) for i in range(DIAS)]
    nombres_dia = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    calendario = {r['service_id']: r for r in lee('calendar.txt')}
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

    # Los pasos de cada viaje. `prohibition` (columna suya, sin documentar):
    # por lo que se ve, las paradas seguidas con el mismo valor —que no sea el
    # 3, el de las líneas normales— son un tramo sin trayectos internos (en un
    # exprés no se va de una parada de Barcelona a otra de Barcelona, ni de una
    # de Vic a otra de Vic). Se guarda como un tercer número del paso, el mismo
    # en todo el tramo; sin él, se sube y se baja donde se quiera.
    pasos = collections.defaultdict(list)
    for r in lee('stop_times.txt'):
        hora = r['departure_time'] or r['arrival_time']
        # Alguna parada viene sin hora: esa no cuenta (el viaje sigue con las demás).
        if r['trip_id'] in viajes and hora:
            pasos[r['trip_id']].append((int(r['stop_sequence']), r['stop_id'], segundos(hora), r.get('prohibition') or '3'))

    lista_paradas, idx_parada = [], {}
    lista_lineas, idx_linea = [], {}
    lista_servicios, idx_servicio = [], {}
    formas = collections.defaultdict(set)
    salida_viajes = []
    for tid in sorted(pasos, key=lambda t: (LINEAS[viajes[t]['route_id']], min(s for _, _, s, _ in pasos[t]))):
        t = viajes[tid]
        dias_activo = [i for i, d in enumerate(dias) if activo(t['service_id'], d)]
        if not dias_activo or len(pasos[tid]) < 2:
            continue
        v = sorted(pasos[tid])
        nombre = LINEAS[t['route_id']]
        for _, s, _, _ in v:
            if s not in idx_parada:
                p = paradas[s]
                idx_parada[s] = len(lista_paradas)
                lista_paradas.append({
                    'id': s, 'nombre': limpia(p['stop_name']),
                    'lat': round(float(p['stop_lat']), 6), 'lon': round(float(p['stop_lon']), 6),
                })
        if nombre not in idx_linea:
            idx_linea[nombre] = len(lista_lineas)
            lista_lineas.append({'nombre': nombre, 'color': COLOR, 'descripciones': []})
        d = descripcion(rutas[t['route_id']]['route_long_name'])
        if d and d not in lista_lineas[idx_linea[nombre]]['descripciones']:
            lista_lineas[idx_linea[nombre]]['descripciones'].append(d)
        if t['service_id'] not in idx_servicio:
            idx_servicio[t['service_id']] = len(lista_servicios)
            lista_servicios.append(dias_activo)
        # Los tramos sin trayectos internos, numerados en el viaje (1, 2…).
        zonas, zona, antes = [], 0, None
        for _, _, _, pro in v:
            if pro == '3':
                zonas.append(0)
            else:
                if pro != antes:
                    zona += 1
                zonas.append(zona)
            antes = pro
        salida_viajes.append([idx_linea[nombre], idx_servicio[t['service_id']], limpia(paradas[v[-1][1]]['stop_name']),
                              [[idx_parada[s], seg] + ([z] if z else []) for (_, s, seg, _), z in zip(v, zonas)]])
        if t.get('shape_id'):
            formas[t['shape_id']].add(nombre)

    # Los trazados de cada línea (polilínea de Google), para el mapa.
    puntos = collections.defaultdict(list)
    for p in lee('shapes.txt'):
        if p['shape_id'] in formas:
            puntos[p['shape_id']].append((int(p['shape_pt_sequence']), float(p['shape_pt_lat']), float(p['shape_pt_lon'])))
    trazados = collections.defaultdict(list)
    for sid, ps in sorted(puntos.items()):
        c = codifica(aclara([(a, b) for _, a, b in sorted(ps)]))
        for nombre in sorted(formas[sid]):
            if c not in trazados[nombre]:
                trazados[nombre].append(c)

    lineas = sorted(lista_lineas, key=lambda l: int(l['nombre'][1:]))
    orden = {l['nombre']: i for i, l in enumerate(lineas)}
    salida = {
        'generado': hoy.isoformat(),
        # Cuándo se generó, con hora (UTC): la web dice «actualizado el 5/10 a las 03:12».
        'generadoEn': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'desde': dias[0].isoformat(),
        # Lo que pide la licencia: de quién son los datos y de cuándo.
        'fuente': FUENTE,
        'fuenteFecha': fecha_fuente.isoformat(),
        'paradas': lista_paradas,
        'lineas': [{'nombre': l['nombre'], 'color': l['color'], 'descripcion': ' · '.join(l['descripciones'])} for l in lineas],
        # Por servicio, los días (desde `desde`, 0 = ese día) en que circula.
        'servicios': lista_servicios,
        # [línea, servicio, destino, [[parada, segundos(, tramo sin trayectos internos)], …]]
        'viajes': [[orden[lista_lineas[l]['nombre']], s, dest, ps] for l, s, dest, ps in salida_viajes],
        'trazados': {k: trazados[k] for k in sorted(trazados, key=lambda n: int(n[1:]))},
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print(f"{SALIDA}: {len(lineas)} líneas ({', '.join(l['nombre'] for l in lineas)}), "
          f"{len(lista_paradas)} paradas, {len(salida_viajes)} viajes, "
          f"{sum(len(v) for v in trazados.values())} trazados; datos de la Generalitat del {fecha_fuente.isoformat()}")


if __name__ == '__main__':
    main()
