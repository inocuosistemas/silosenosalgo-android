#!/usr/bin/env python3
"""
El horario PREVISTO de Rodalies de Catalunya, para la pestaña Trenes:
`public/datos/rodalies.json`.

Es el plan B: los horarios de ahora salen del servicio de Rodalies
(`serveisgrs.rodalies.gencat.cat`), y cuando ese servicio falla (el 5/10/2026
contestaba «Dades no disponibles» a todo) se usan estos, los oficiales
previstos, sin tiempo real propio.

Sale del GTFS abierto de Renfe Cercanías (todas las Cercanías de España en un
zip de unos 13 MB): https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip
(catálogo: https://data.renfe.com/dataset/horarios-cercanias; licencia: la de
datos abiertos de Renfe, reutilización libre citando la fuente). Se queda solo
con Rodalies de Catalunya (las líneas cuyo `route_id` empieza por `51`), y
compacto como el de FGC (ver `genera-fgc.py`): cada viaje es una fila corta
que apunta a un PATRÓN (las estaciones con el tiempo desde la primera). Los
códigos de estación del GTFS son los mismos que usa Rodalies (`71802`
Passeig de Gràcia): no hace falta traducirlos.

Uso:  python3 scripts/genera-rodalies.py [carpeta-con-los-txt]
Se rehace cada dos o tres semanas: los servicios van por fechas.
"""
import collections, csv, datetime, io, json, os, sys, urllib.request, zipfile

ZIP = 'https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip'
DIAS = 21
SALIDA = os.environ.get('SALIDA', 'public/datos/rodalies.json')
NUCLEO = '51'  # Rodalies de Catalunya


def abre(origen):
    if origen:
        return lambda n: open(f'{origen}/{n}', encoding='utf-8-sig')
    with urllib.request.urlopen(ZIP, timeout=300) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    return lambda n: io.TextIOWrapper(z.open(n), encoding='utf-8-sig')


def filas(abrir, nombre):
    for r in csv.DictReader(abrir(nombre)):
        yield {k.strip(): (v or '').strip() for k, v in r.items()}


def segundos(h):
    p = [int(x) for x in h.split(':')]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


def main():
    abrir = abre(sys.argv[1] if len(sys.argv) > 1 else None)
    lineas = {r['route_id']: r for r in filas(abrir, 'routes.txt') if r['route_id'].startswith(NUCLEO)}
    viajes = {r['trip_id']: r for r in filas(abrir, 'trips.txt') if r['route_id'] in lineas}

    hoy = datetime.date.today()
    dias = [hoy + datetime.timedelta(days=i) for i in range(DIAS)]
    nombres = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    # Los días en que circula cada servicio, de verdad (por su calendario).
    reales = collections.defaultdict(set)
    for r in filas(abrir, 'calendar.txt'):
        ini = datetime.datetime.strptime(r['start_date'], '%Y%m%d').date()
        fin = datetime.datetime.strptime(r['end_date'], '%Y%m%d').date()
        d = ini
        while d <= fin:
            # Renfe pone servicios de un solo día; algunos, sin ningún día
            # marcado: cuenta la fecha.
            if r[nombres[d.weekday()]] == '1' or ini == fin:
                reales[r['service_id']].add(d)
            d += datetime.timedelta(days=1)
    try:
        for r in filas(abrir, 'calendar_dates.txt'):
            f = datetime.datetime.strptime(r['date'], '%Y%m%d').date()
            (reales[r['service_id']].add if r['exception_type'] == '1' else reales[r['service_id']].discard)(f)
    except (KeyError, FileNotFoundError):
        pass  # Renfe no lo publica: todo va en calendar.txt.

    # Los servicios que de verdad llevan viajes. El 5/10/2026 Renfe solo
    # publicaba los de Rodalies del 1 al 4 de octubre (los días siguientes
    # tenían servicio, pero sin un solo viaje): los días sin horario
    # publicado toman el HABITUAL, el del último día publicado del mismo tipo
    # (el mismo día de la semana; si no, otro laborable o el del mismo fin de
    # semana), y se marcan para decirlo.
    con_viajes = {v['service_id'] for v in viajes.values()}
    fecha_de = {s: max(ds) for s, ds in reales.items() if s in con_viajes and ds}
    def tipo(d):
        return 'L' if d.weekday() < 5 else ('S' if d.weekday() == 5 else 'D')
    dias_de = collections.defaultdict(list)
    habituales = []
    for i, d in enumerate(dias):
        propios = [s for s in con_viajes if d in reales.get(s, ())]
        if propios:
            for s in propios:
                dias_de[s].append(i)
            continue
        candidatos = sorted(fecha_de.items(), key=lambda x: x[1], reverse=True)
        # De lunes a jueves suelen ser iguales; el viernes, a veces con más
        # trenes de noche: un lunes toma antes el de un jueves que el de un viernes.
        elegido = next((s for s, f in candidatos if f.weekday() == d.weekday()), None) \
            or (next((s for s, f in candidatos if f.weekday() < 4), None) if d.weekday() < 4 else None) \
            or next((s for s, f in candidatos if tipo(f) == tipo(d)), None)
        if elegido:
            dias_de[elegido].append(i)
            habituales.append(i)

    pasos = collections.defaultdict(list)
    for r in filas(abrir, 'stop_times.txt'):
        v = viajes.get(r['trip_id'])
        if not v or not dias_de.get(v['service_id']):
            continue
        pasos[r['trip_id']].append((int(r['stop_sequence']), r['stop_id'],
                                    # La LLEGADA a cada parada: así la hora de llegada es
                                    # la exacta, y la de salida, si acaso, un minuto
                                    # antes (lo que se para el tren): del lado seguro.
                                    segundos(r['arrival_time'] or r['departure_time'])))

    paradas = {r['stop_id']: r for r in filas(abrir, 'stops.txt')}
    lista_est, idx_est = [], {}
    lista_lin, idx_lin = [], {}
    lista_serv, idx_serv = [], {}
    lista_pat, idx_pat = [], {}
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
                lista_est.append({'id': est, 'nombre': p['stop_name']})
            patron.append((idx_est[est], seg - inicio))
        patron = tuple(patron)
        if patron not in idx_pat:
            idx_pat[patron] = len(lista_pat)
            lista_pat.append([list(x) for x in patron])
        r = lineas[t['route_id']]
        nombre = r['route_short_name']
        if nombre not in idx_lin:
            idx_lin[nombre] = len(lista_lin)
            lista_lin.append({'nombre': nombre, 'color': '#' + (r.get('route_color') or '6b7280')})
        if t['service_id'] not in idx_serv:
            idx_serv[t['service_id']] = len(lista_serv)
            lista_serv.append(dias_de[t['service_id']])
        # El número de tren («5172J25601R1» → 25601): el mismo con el que el
        # tiempo real de Renfe da los retrasos (ver `/api/rodalies/retrasos`).
        cola = tid[len(t['service_id']):] if tid.startswith(t['service_id']) else ''
        numero = cola[:len(cola) - len(cola.lstrip('0123456789'))]
        salida_viajes.append([idx_lin[nombre], idx_serv[t['service_id']], inicio, idx_pat[patron], numero])

    salida = {
        'generado': hoy.isoformat(),
        # Cuándo se generó, con hora (UTC): la web dice «actualizado el 5/10 a las 03:12».
        'generadoEn': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'desde': dias[0].isoformat(),
        'estaciones': lista_est,
        'lineas': lista_lin,
        # Por servicio, los días (desde `desde`, 0 = ese día) en que circula.
        'servicios': lista_serv,
        # Los días (como arriba) sin horario publicado: llevan el habitual.
        'habituales': habituales,
        # [[estación, segundos desde la salida del viaje], …]
        'patrones': lista_pat,
        # [línea, servicio, salida (s desde medianoche), patrón, número de tren]
        'viajes': salida_viajes,
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print(f"{SALIDA}: {len(lista_est)} estaciones, {len(lista_lin)} líneas, "
          f"{len(lista_pat)} patrones, {len(salida_viajes)} viajes")


if __name__ == '__main__':
    main()
