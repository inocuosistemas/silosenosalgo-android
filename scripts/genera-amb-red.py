#!/usr/bin/env python3
"""
La red entera de buses del AMB, para su tiempo real (ver functions/lib/ambEnVivo.ts):
`public/datos/amb-red.json`.

El tiempo real del AMB (GTFS-RT, sus datos abiertos) dice, de cada bus en marcha,
su viaje (trip_id) y la hora prevista en sus próximas paradas, pero no dónde
está. Con esto se sabe el resto: la línea de cada viaje (lo que va antes del
primer punto del trip_id es su route_id), su destino, sus paradas en orden con
dónde está cada una, y lo que se tarda de una a otra según el horario. Con eso,
los buses en el mapa, aproximados (entre la parada que dejaron y la siguiente),
y el panel de cada parada.

Cada recorrido es el trip_id sin su último número («129.20.1.3» de
«129.20.1.3.102»): mismas paradas y mismo destino en todos sus viajes. Los que
acortan (empiezan o acaban a medio camino) numeran sus paradas igual, así que
se juntan en uno.

Sale del GTFS abierto del AMB (https://www.ambmobilitat.cat/OpenData/google_transit.zip).

Uso:  python3 scripts/genera-amb-red.py [google_transit.zip]
Se rehace cada semana con los demás horarios: cuando el AMB cambia de horario,
cambian los trip_id. Lo hace `genera-bus-amb.py` con el mismo zip (ver `genera`):
así la tarea semanal no necesita otro paso.
"""
import csv, io, json, os, sys, urllib.request, zipfile, datetime, collections, statistics

SALIDA = os.environ.get('SALIDA', 'public/datos/amb-red.json')


def lee(z, nombre):
    return csv.DictReader(io.TextIOWrapper(z.open(nombre), encoding='utf-8-sig'))


def segundos(h):
    p = [int(x) for x in h.split(':')]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


def recorrido(trip_id):
    return trip_id.rsplit('.', 1)[0]


def genera(z, salida_fichero):
    """La red, del GTFS ya abierto (`z`), en `salida_fichero`."""
    paradas = {r['stop_id']: r for r in lee(z, 'stops.txt')}
    rutas = {r['route_id']: r for r in lee(z, 'routes.txt')}
    viajes = {r['trip_id']: r for r in lee(z, 'trips.txt')}

    pasos = collections.defaultdict(list)
    for r in lee(z, 'stop_times.txt'):
        pasos[r['trip_id']].append((int(r['stop_sequence']), r['stop_id'], segundos(r['departure_time'] or r['arrival_time'])))

    # Por recorrido: su línea, su destino, qué parada va en cada número de
    # secuencia (los que acortan, juntos) y, de cada una, los segundos desde la
    # primera de su viaje en todos los viajes que empiezan donde el recorrido.
    linea_de, destino_de = {}, {}
    parada_en = collections.defaultdict(dict)
    tiempos = collections.defaultdict(lambda: collections.defaultdict(list))
    for tid, ps in pasos.items():
        t = viajes.get(tid)
        if not t:
            continue
        k = recorrido(tid)
        ps.sort()
        linea_de[k] = t['route_id']
        destino_de.setdefault(k, t.get('trip_headsign', ''))
        for seq, s, _ in ps:
            parada_en[k].setdefault(seq, s)
        t0 = ps[0][2]
        for seq, _, seg in ps:
            tiempos[(k, ps[0][0])][seq].append(seg - t0)

    usadas = sorted({s for m in parada_en.values() for s in m.values()})
    idx_parada = {s: i for i, s in enumerate(usadas)}
    lista_rutas = sorted({linea_de[k] for k in parada_en}, key=lambda rid: (rutas[rid]['route_short_name'], rid))
    idx_ruta = {rid: i for i, rid in enumerate(lista_rutas)}

    salida_recorridos = {}
    for k, mapa in parada_en.items():
        seqs = sorted(mapa)
        # Los tiempos, de los viajes que empiezan en la primera del recorrido; si
        # no hay (raro), de los que empiezan más tarde, sumando lo que falta.
        tabla = tiempos.get((k, seqs[0])) or {}
        fila = []
        for seq in seqs:
            ts = tabla.get(seq)
            fila.append([seq, idx_parada[mapa[seq]], int(statistics.median(ts)) if ts else -1])
        # Las que no salen en esos viajes (de los que acortan), entre sus vecinas.
        for i, f in enumerate(fila):
            if f[2] >= 0:
                continue
            antes = next((g for g in reversed(fila[:i]) if g[2] >= 0), None)
            despues = next((g for g in fila[i + 1:] if g[2] >= 0), None)
            f[2] = antes[2] if antes and not despues else despues[2] if despues and not antes else \
                (antes[2] + despues[2]) // 2 if antes and despues else 0
        salida_recorridos[k] = [idx_ruta[linea_de[k]], destino_de[k], fila]

    def color(c, defecto):
        c = (c or '').strip().lstrip('#')
        return '#' + (c if len(c) == 6 else defecto)

    salida = {
        'generado': datetime.date.today().isoformat(),
        'generadoEn': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        # [route_id, nombre, color, color del texto]
        'lineas': [[rid, rutas[rid]['route_short_name'], color(rutas[rid].get('route_color'), 'ffaa00'),
                    color(rutas[rid].get('route_text_color'), '343434')] for rid in lista_rutas],
        # [stop_id, nombre, lat, lon]
        'paradas': [[s, paradas[s]['stop_name'], round(float(paradas[s]['stop_lat']), 5),
                     round(float(paradas[s]['stop_lon']), 5)] for s in usadas],
        # recorrido → [línea, destino, [[secuencia, parada, segundos desde la primera], …]]
        'recorridos': salida_recorridos,
    }
    with open(salida_fichero, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, separators=(',', ':'))
    print(f'{salida_fichero}: {len(lista_rutas)} líneas, {len(usadas)} paradas, {len(salida_recorridos)} recorridos')


def main():
    if len(sys.argv) > 1:
        z = zipfile.ZipFile(sys.argv[1])
    else:
        datos = urllib.request.urlopen('https://www.ambmobilitat.cat/OpenData/google_transit.zip', timeout=120).read()
        z = zipfile.ZipFile(io.BytesIO(datos))
    genera(z, SALIDA)


if __name__ == '__main__':
    main()
