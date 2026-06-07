"""
Pokefisi — Benchmark de Agentes IA
====================================
Ejecuta N batallas entre cada par de agentes y muestra las tasas de victoria.

Uso:
    python benchmark.py                     # 100 batallas por enfrentamiento
    python benchmark.py -n 50              # 50 batallas por enfrentamiento
    python benchmark.py -n 200 --seed 42   # reproducible
    python benchmark.py --tam 3            # Equipos de 3
"""

import argparse
import random
import sys
import os
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pokemon import lista_nombres_pokemon, cargar_pokemon, aplicar_modo_movimientos
from src.battle_engine import BattleEngine
from src.ai_agent import (
    RandomAgent, HeuristicAgent, MinimaxAgent,
    PESOS_EVAL_UNIFORME, PESOS_EVAL_DEFAULT, cargar_pesos_entrenados,
)
from src.agent_utils import AgenteVolteado


# ── Lógica de batalla ────────────────────────────────────────────────────────

def _jugar_batalla(agente_j, agente_ia, nombres_pool, tam=4, max_turnos=150):
    """
    Juega una batalla completa.
    agente_j  → juega como jugador  (se usa AgenteVolteado si es necesario)
    agente_ia → juega como ia
    Devuelve 'jugador', 'ia' o None (empate por límite de turnos).
    """
    random.shuffle(nombres_pool)
    equipo_j  = [cargar_pokemon(n) for n in nombres_pool[:tam]]
    equipo_ia = [cargar_pokemon(n) for n in nombres_pool[tam:tam * 2]]

    # Reducir 8 → 4 movs (matching entrenamiento y deployment del juego).
    for pkm in equipo_j + equipo_ia:
        aplicar_modo_movimientos(pkm, 'aleatorios')

    engine = BattleEngine(equipo_j, equipo_ia)

    for _ in range(max_turnos):
        if engine.batalla_terminada():
            break

        # Cambio forzado del jugador: elegir automáticamente el primero vivo
        if engine.necesita_cambio_jugador:
            for i, p in enumerate(engine.equipos['jugador']):
                if p.esta_vivo():
                    engine.cambiar_pokemon('jugador', i)
                    engine.necesita_cambio_jugador = False
                    break
            continue

        estado = engine.get_estado()
        estado['_engine'] = engine

        accion_j  = agente_j.elegir_accion(estado)
        accion_ia = agente_ia.elegir_accion(estado)
        engine.ejecutar_turno(accion_j, accion_ia)

    if not engine.batalla_terminada():
        return None      # empate por timeout
    return engine.ganador()


# ── Barra de progreso simple ─────────────────────────────────────────────────

def _barra(actual, total, ancho=30):
    lleno = int(ancho * actual / total)
    return '#' * lleno + '.' * (ancho - lleno)


# ── Benchmark de un par de agentes ──────────────────────────────────────────

def _benchmark_par(etiqueta, fab_a, fab_b, n_batallas, tam, nombres_pool):
    """
    Ejecuta n_batallas entre A y B, alternando quién juega como 'ia'.
    Devuelve (victorias_a, victorias_b, empates).
    """
    victorias_a = victorias_b = empates = 0
    mitad = n_batallas // 2
    t0 = time.time()

    for i in range(n_batallas):
        # Mitad de batallas A como 'ia', otra mitad B como 'ia'
        if i < mitad:
            agente_ia = fab_a()
            agente_j  = AgenteVolteado(fab_b())
            ganador_raw = _jugar_batalla(agente_j, agente_ia, nombres_pool, tam)
            # 'ia' = A ganó; 'jugador' = B ganó
            if   ganador_raw == 'ia':      victorias_a += 1
            elif ganador_raw == 'jugador': victorias_b += 1
            else:                          empates    += 1
        else:
            agente_ia = fab_b()
            agente_j  = AgenteVolteado(fab_a())
            ganador_raw = _jugar_batalla(agente_j, agente_ia, nombres_pool, tam)
            # 'ia' = B ganó; 'jugador' = A ganó
            if   ganador_raw == 'ia':      victorias_b += 1
            elif ganador_raw == 'jugador': victorias_a += 1
            else:                          empates    += 1

        # Progreso en línea
        completado = i + 1
        bar = _barra(completado, n_batallas)
        elapsed = time.time() - t0
        print(f'\r  {etiqueta:<30} [{bar}] {completado:>4}/{n_batallas}  {elapsed:6.1f}s',
              end='', flush=True)

    print()  # salto de línea al terminar
    return victorias_a, victorias_b, empates


# ── Punto de entrada ─────────────────────────────────────────────────────────

NAME_W = 24  # ancho de la columna de nombres (acomoda "Nv.3  Minimax (uniforme)")
BAR_W  = 24  # ancho de la barra de victorias

# Ancho interno del box (entre los ║):
#   3 (indent)  +  NAME_W  +  2  +  BAR_W  +  2  +  6 (pct)  +  2
#                                                  + 15 ("(NNN victorias)") + 2
W = 3 + NAME_W + 2 + BAR_W + 2 + 6 + 2 + 15 + 2  # = 80


def _win_bar(pct):
    """Barra horizontal proporcional al porcentaje."""
    lleno = round(BAR_W * pct / 100)
    return '█' * lleno + '░' * (BAR_W - lleno)


def main():
    parser = argparse.ArgumentParser(
        description='Benchmark de agentes IA de Pokefisi')
    parser.add_argument('-n', '--batallas', type=int, default=100,
                        help='Número de batallas por enfrentamiento (default: 100)')
    parser.add_argument('--tam', type=int, default=4, choices=[3, 4],
                        help='Tamaño de equipo (default: 4)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Semilla aleatoria para reproducibilidad')
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    n   = args.batallas
    tam = args.tam

    # (nombre_corto, nombre_display, fabrica)
    # Las 3 variantes del Minimax se exponen como agentes distintos para poder
    # comparar la contribución del entrenamiento (GA) frente al baseline neutro
    # (uniforme) y al ajuste experto (manual).
    pesos_ga = cargar_pesos_entrenados()  # None si aún no se ha entrenado

    agentes = [
        ('Random',     'Nv.1  Random',                  RandomAgent),
        ('Heurístico', 'Nv.2  Heurístico',              HeuristicAgent),
        ('M-Uniforme', 'Nv.3  Minimax (uniforme)',      lambda: MinimaxAgent(pesos=PESOS_EVAL_UNIFORME)),
        ('M-Manual',   'Nv.3  Minimax (manual)',        lambda: MinimaxAgent(pesos=PESOS_EVAL_DEFAULT)),
    ]
    if pesos_ga is not None:
        agentes.append(('M-GA', 'Nv.3  Minimax (GA)', lambda: MinimaxAgent(pesos=pesos_ga)))

    # Índices fijos para construir matchups con claridad
    idx = {nombre: i for i, (nombre, _, _) in enumerate(agentes)}

    # Matchups curados (no all-vs-all para no inflar el tiempo).
    # La narrativa cubre: jerarquía Nv1<Nv2<Nv3 + contribución del entrenamiento.
    matchups_def = [
        ('Random',     'Heurístico'),  # Nv1 vs Nv2
        ('Random',     'M-Uniforme'),  # Nv1 vs Nv3 sin entrenar
        ('Heurístico', 'M-Uniforme'),  # ¿Minimax sin entrenar ya supera a Nv2?
        ('Heurístico', 'M-Manual'),    # Nv2 vs Nv3 con ajuste experto
        ('M-Uniforme', 'M-Manual'),    # Mejora del ajuste manual sobre uniforme
    ]
    if pesos_ga is not None:
        matchups_def += [
            ('Heurístico', 'M-GA'),    # Nv2 vs Nv3 entrenado
            ('M-Uniforme', 'M-GA'),    # Contribución del GA (clave del proyecto)
            ('M-Manual',   'M-GA'),    # ¿El GA alcanza/supera al manual?
        ]

    matchups = [(agentes[idx[a]], agentes[idx[b]]) for a, b in matchups_def]

    nombres_pool = lista_nombres_pokemon()

    blank = f'  ║{"":<{W}}║'

    # ── Header ──────────────────────────────────────────────────────────────
    print()
    print(f'  ╔{"═" * W}╗')
    print(f'  ║{"POKEFISI  —  Benchmark de Agentes IA":^{W}}║')
    print(f'  ╠{"═" * W}╣')
    print(blank)
    info = f'   {n} batallas por enfrentamiento   │   equipos {tam} vs {tam}'
    print(f'  ║{info:<{W}}║')
    if args.seed is not None:
        semilla = f'   semilla: {args.seed}'
        print(f'  ║{semilla:<{W}}║')
    print(blank)
    print(f'  ╚{"═" * W}╝')
    print()

    # ── Progreso ────────────────────────────────────────────────────────────
    resultados = []
    t_total = time.time()

    for (ca, nom_a, fab_a), (cb, nom_b, fab_b) in matchups:
        etiqueta = f'{ca} vs {cb}'
        va, vb, emp = _benchmark_par(etiqueta, fab_a, fab_b,
                                      n, tam, nombres_pool)
        resultados.append((nom_a, nom_b, va, vb, emp))

    elapsed_total = time.time() - t_total

    # ── Resultados ──────────────────────────────────────────────────────────
    print()
    print(f'  ╔{"═" * W}╗')
    print(f'  ║{"R E S U L T A D O S":^{W}}║')

    for nom_a, nom_b, va, vb, emp in resultados:
        total = va + vb + emp
        pct_a = va / total * 100 if total else 0
        pct_b = vb / total * 100 if total else 0

        bar_a = _win_bar(pct_a)
        bar_b = _win_bar(pct_b)

        titulo = f'   {nom_a}   vs   {nom_b}'

        print(f'  ╠{"═" * W}╣')
        print(blank)
        print(f'  ║{titulo:<{W}}║')
        print(blank)
        print(f'  ║   {nom_a:<{NAME_W}}  {bar_a}  {pct_a:5.1f}%  ({va:>3} victorias)  ║')
        print(f'  ║   {nom_b:<{NAME_W}}  {bar_b}  {pct_b:5.1f}%  ({vb:>3} victorias)  ║')
        if emp:
            fila_emp = f'   {"Empates":<{NAME_W}}  {"":<{BAR_W}}         ({emp:>3} empates)'
            print(f'  ║{fila_emp:<{W}}║')
        print(blank)

    print(f'  ╠{"═" * W}╣')
    print(blank)
    tiempo = f'   Tiempo total: {elapsed_total:.1f}s'
    print(f'  ║{tiempo:<{W}}║')
    print(blank)
    print(f'  ╚{"═" * W}╝')
    print()


if __name__ == '__main__':
    main()
