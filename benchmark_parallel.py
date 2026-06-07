"""
Pokefisi — Benchmark de Agentes IA (versión paralela)
======================================================
Versión de benchmark.py paralelizada con multiprocessing.Pool.

Cada batalla es una tarea independiente que se despacha a un worker. Speedup
esperado: ~3-4x en máquinas de 4 cores, ~6-8x en 12 cores. Las batallas
Minimax-vs-Minimax (las más caras) se benefician más.

Uso:
    py benchmark_parallel.py                     # 100 batallas por enfrentamiento
    py benchmark_parallel.py -n 50              # 50 batallas
    py benchmark_parallel.py -n 200 --seed 42   # selección de escenarios reproducible
    py benchmark_parallel.py --tam 3            # equipos de 3
    py benchmark_parallel.py --workers 4        # número de workers (default: cpu_count)

Nota sobre --seed: solo afecta a la SELECCIÓN de equipos por batalla (en proceso
principal). El RNG interno de cada batalla queda libre — para reproducibilidad
total del lado del engine, usar el benchmark sequencial (`benchmark.py`).
"""

import argparse
import random
import signal
import sys
import os
import time
import multiprocessing as mp

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pokemon import lista_nombres_pokemon, cargar_pokemon, aplicar_modo_movimientos
from src.battle_engine import BattleEngine
from src.ai_agent import (
    RandomAgent, HeuristicAgent, MinimaxAgent,
    PESOS_EVAL_UNIFORME, PESOS_EVAL_DEFAULT, cargar_pesos_entrenados,
)
from src.agent_utils import AgenteVolteado


def _init_worker_suppress_sigint():
    signal.signal(signal.SIGINT, signal.SIG_IGN)


# ── Specs picklables para agentes ────────────────────────────────────────────

def _crear_agente_de_spec(spec):
    """Construye un agente desde su spec tuple. Picklable (a diferencia de lambdas).

    Specs aceptados:
        ('random',)
        ('heuristic',)
        ('minimax', pesos_list)
    """
    kind = spec[0]
    if kind == 'random':
        return RandomAgent()
    if kind == 'heuristic':
        return HeuristicAgent()
    if kind == 'minimax':
        return MinimaxAgent(pesos=list(spec[1]))
    raise ValueError(f"Spec desconocido: {spec}")


# ── Worker para mp.Pool — top-level y picklable ──────────────────────────────

def _battle_worker(args):
    """Juega una batalla y devuelve 'a', 'b' o 'empate' (perspectiva relativa
    al matchup, no al engine).

    args = (spec_a, spec_b, nombres_j, nombres_ia, a_is_ia, max_turnos)
    """
    spec_a, spec_b, nombres_j, nombres_ia, a_is_ia, max_turnos = args

    agent_a = _crear_agente_de_spec(spec_a)
    agent_b = _crear_agente_de_spec(spec_b)

    equipo_j = [cargar_pokemon(n) for n in nombres_j]
    equipo_ia = [cargar_pokemon(n) for n in nombres_ia]

    # Reducir 8 → 4 movs (matching entrenamiento y deployment del juego).
    for pkm in equipo_j + equipo_ia:
        aplicar_modo_movimientos(pkm, 'aleatorios')

    engine = BattleEngine(equipo_j, equipo_ia)

    # A juega como 'ia' o como 'jugador' según a_is_ia. El que juega como
    # 'jugador' se envuelve en AgenteVolteado para corregir la perspectiva.
    if a_is_ia:
        agente_ia = agent_a
        agente_j = AgenteVolteado(agent_b)
    else:
        agente_ia = agent_b
        agente_j = AgenteVolteado(agent_a)

    for _ in range(max_turnos):
        if engine.batalla_terminada():
            break
        if engine.necesita_cambio_jugador:
            for i, p in enumerate(engine.equipos['jugador']):
                if p.esta_vivo():
                    engine.cambiar_pokemon('jugador', i)
                    engine.necesita_cambio_jugador = False
                    break
            continue
        estado = engine.get_estado()
        estado['_engine'] = engine
        accion_ia = agente_ia.elegir_accion(estado)
        accion_j = agente_j.elegir_accion(estado)
        engine.ejecutar_turno(accion_j, accion_ia)

    if not engine.batalla_terminada():
        return 'empate'  # timeout
    ganador_raw = engine.ganador()
    if ganador_raw == 'empate':
        return 'empate'
    # Traducir perspectiva engine → matchup
    if a_is_ia:
        return 'a' if ganador_raw == 'ia' else 'b'
    else:
        return 'a' if ganador_raw == 'jugador' else 'b'


# ── Generación de tasks ──────────────────────────────────────────────────────

def _generar_tasks(spec_a, spec_b, n_batallas, tam, nombres_pool, max_turnos=150):
    """Pre-genera los argumentos para n batallas (con alternancia de lados).
    Se ejecuta en el proceso principal — los workers solo procesan."""
    tasks = []
    mitad = n_batallas // 2
    for i in range(n_batallas):
        nombres_copy = list(nombres_pool)
        random.shuffle(nombres_copy)
        nombres_j = nombres_copy[:tam]
        nombres_ia = nombres_copy[tam:tam * 2]
        a_is_ia = (i < mitad)
        tasks.append((spec_a, spec_b, nombres_j, nombres_ia, a_is_ia, max_turnos))
    return tasks


# ── Benchmark paralelo de un par ─────────────────────────────────────────────

def _benchmark_par_paralelo(etiqueta, spec_a, spec_b, n_batallas, tam,
                            nombres_pool, pool):
    """Ejecuta n_batallas en paralelo. Devuelve (victorias_a, victorias_b, empates).
    Progreso visible vía imap_unordered (se actualiza conforme terminan workers)."""
    tasks = _generar_tasks(spec_a, spec_b, n_batallas, tam, nombres_pool)

    t0 = time.time()
    completados = 0
    victorias_a = victorias_b = empates = 0

    for r in pool.imap_unordered(_battle_worker, tasks):
        completados += 1
        if r == 'a':
            victorias_a += 1
        elif r == 'b':
            victorias_b += 1
        else:
            empates += 1

        bar = _barra(completados, n_batallas)
        elapsed = time.time() - t0
        print(f'\r  {etiqueta:<30} [{bar}] {completados:>4}/{n_batallas}  {elapsed:6.1f}s',
              end='', flush=True)

    print()
    return victorias_a, victorias_b, empates


# ── Helpers visuales (idénticos a benchmark.py) ──────────────────────────────

def _barra(actual, total, ancho=30):
    lleno = int(ancho * actual / total)
    return '#' * lleno + '.' * (ancho - lleno)


NAME_W = 24  # ancho de la columna de nombres (acomoda "Nv.3  Minimax (uniforme)")
BAR_W  = 24  # ancho de la barra de victorias

# Ancho interno del box (entre los ║):
#   3 (indent)  +  NAME_W  +  2  +  BAR_W  +  2  +  6 (pct)  +  2
#                                                  + 15 ("(NNN victorias)") + 2
W = 3 + NAME_W + 2 + BAR_W + 2 + 6 + 2 + 15 + 2  # = 80


def _win_bar(pct):
    lleno = round(BAR_W * pct / 100)
    return '█' * lleno + '░' * (BAR_W - lleno)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Benchmark paralelo de agentes IA de Pokefisi')
    parser.add_argument('-n', '--batallas', type=int, default=100,
                        help='Número de batallas por enfrentamiento (default: 100)')
    parser.add_argument('--tam', type=int, default=4, choices=[3, 4],
                        help='Tamaño de equipo (default: 4)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Semilla para selección de escenarios (no afecta dados del engine)')
    parser.add_argument('--workers', type=int, default=None,
                        help='Número de procesos paralelos (default: cpu_count)')
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    n = args.batallas
    tam = args.tam
    n_workers = args.workers if args.workers else mp.cpu_count()

    # Specs picklables (vs lambdas en benchmark.py)
    pesos_ga = cargar_pesos_entrenados()

    agentes = [
        ('Random',     'Nv.1  Random',                  ('random',)),
        ('Heurístico', 'Nv.2  Heurístico',              ('heuristic',)),
        ('M-Uniforme', 'Nv.3  Minimax (uniforme)',      ('minimax', PESOS_EVAL_UNIFORME)),
        ('M-Manual',   'Nv.3  Minimax (manual)',        ('minimax', PESOS_EVAL_DEFAULT)),
    ]
    if pesos_ga is not None:
        agentes.append(('M-GA', 'Nv.3  Minimax (GA)', ('minimax', pesos_ga)))

    idx = {nombre: i for i, (nombre, _, _) in enumerate(agentes)}

    matchups_def = [
        ('Random',     'Heurístico'),
        ('Random',     'M-Uniforme'),
        ('Heurístico', 'M-Uniforme'),
        ('Heurístico', 'M-Manual'),
        ('M-Uniforme', 'M-Manual'),
    ]
    if pesos_ga is not None:
        matchups_def += [
            ('Heurístico', 'M-GA'),
            ('M-Uniforme', 'M-GA'),
            ('M-Manual',   'M-GA'),
        ]

    matchups = [(agentes[idx[a]], agentes[idx[b]]) for a, b in matchups_def]

    nombres_pool = lista_nombres_pokemon()

    blank = f'  ║{"":<{W}}║'

    # ── Header ──────────────────────────────────────────────────────────────
    print()
    print(f'  ╔{"═" * W}╗')
    print(f'  ║{"POKEFISI  —  Benchmark Paralelo de Agentes IA":^{W}}║')
    print(f'  ╠{"═" * W}╣')
    print(blank)
    info = f'   {n} batallas por enfrentamiento   │   equipos {tam} vs {tam}'
    print(f'  ║{info:<{W}}║')
    workers = f'   workers: {n_workers}'
    print(f'  ║{workers:<{W}}║')
    if args.seed is not None:
        semilla = f'   semilla: {args.seed}'
        print(f'  ║{semilla:<{W}}║')
    print(blank)
    print(f'  ╚{"═" * W}╝')
    print()

    resultados = []
    t_total = time.time()

    # Una sola Pool reusada para todos los matchups (sin overhead de spawn)
    with mp.Pool(n_workers, initializer=_init_worker_suppress_sigint) as pool:
        for (ca, nom_a, spec_a), (cb, nom_b, spec_b) in matchups:
            etiqueta = f'{ca} vs {cb}'
            va, vb, emp = _benchmark_par_paralelo(
                etiqueta, spec_a, spec_b, n, tam, nombres_pool, pool)
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
    # IMPORTANTE: el guard if __name__ == '__main__' es OBLIGATORIO en Windows
    # para que multiprocessing funcione correctamente.
    main()
