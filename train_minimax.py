"""
Entrenamiento del MinimaxAgent vía algoritmo genético.

Uso:
    py train_minimax.py                  # entrenamiento completo (~3-5 h con paralelismo)
    py train_minimax.py --rapido         # configuración rápida para iterar (~30 min)
    py train_minimax.py --sin-paralelo   # serial (debug)
    py train_minimax.py --workers 4      # limitar a 4 cores (deja CPU libre para uso)
    py train_minimax.py --seed 42        # reproducible
    py train_minimax.py --resume         # reanudar desde checkpoint anterior

Estrategia:
- Población sembrada alrededor de PESOS_EVAL_UNIFORME (no aleatoria).
- 2 anclas inmortales: copias exactas del uniforme → garantiza que el GA
  nunca evoluciona pesos PEORES que el baseline neutro.
- Basket de fitness: 30 batallas vs HeuristicAgent + 10 vs MinimaxAgent(manual).
- CRN entre individuos de la misma generación.
- Paralelismo con multiprocessing.Pool (12 workers en máquina del usuario).
- Al final: validación en holdout (escenarios NO vistos durante el GA) vs los 3
  rivales para obtener un win rate honesto reportable.
"""
import argparse
import os
import sys
import time

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ai_agent import (
    PESOS_EVAL_UNIFORME, PESOS_EVAL_DEFAULT, RUTA_PESOS_ENTRENADOS,
)
from src.genetic_algorithm import (
    GeneticOptimizer, generar_escenarios, simular_batalla,
)


# ── Validación holdout ──────────────────────────────────────────────────────

def validar(pesos, n_holdout=50, seed_holdout=999999, tam_equipo=4):
    """Evalúa pesos contra los 3 rivales en escenarios separados (no usados
    durante el GA). ALTERNA LADOS para cancelar la asimetría estructural del
    engine (la IA auto-cambia mid-turn, el jugador no) — así los win rates son
    honestos y comparables a benchmark.py.

    Nota: alternar duplica el número de batallas (cada escenario se juega 2
    veces), por eso la validación tarda más que con asimetría.

    Devuelve dict con win rates por rival.
    """
    escenarios = generar_escenarios(n_holdout, seed=seed_holdout, tam_equipo=tam_equipo)

    print(f"\n  Validando contra {n_holdout} escenarios × 2 (alternando lados) vs cada rival...")
    resultados = {}
    for rival in ('random', 'heuristic', 'minimax_default'):
        t0 = time.time()
        wr = simular_batalla(pesos, escenarios=escenarios, rival=rival,
                             tam_equipo=tam_equipo, alternar_lados=True)
        elapsed = time.time() - t0
        resultados[rival] = wr
        print(f"    vs {rival:18s} {wr*100:5.1f}%   ({elapsed:5.1f}s)")
    return resultados


# ── Callback de progreso ────────────────────────────────────────────────────

def _hacer_callback(t_inicio_sesion, t_acumulado_previo=0):
    """Callback que imprime progreso al inicio de cada generación.

    El checkpoint completo (incluye población + RNG state para resume) lo
    persiste `GeneticOptimizer.evolucionar` directamente — el callback solo
    se ocupa del display.

    Display:
    - hist: mejor fitness HISTÓRICO (acumulado desde Gen 1)
    - gen:  mejor fitness DE ESTA GENERACIÓN
    - label distingue 3 situaciones:
        (elite)         → mismo campeón que la gen anterior, sin cambios
        (nuevo récord)  → un individuo NUEVO acaba de superar al histórico
        (challenger)    → el mejor de la gen NO es el histórico (alguien intentó pero
                          no logró superarlo) — muestra ambos pesos para ver exploración
    """
    # Estado de closure para detectar cambios entre generaciones
    prev_hist_pesos = [None]

    def callback(gen, mejor_fitness, mejor_gen_fitness, media,
                 mejor_individuo, mejor_gen_individuo):
        elapsed = t_acumulado_previo + (time.time() - t_inicio_sesion)

        gen_es_hist = (mejor_individuo == mejor_gen_individuo)
        hist_cambio_pesos = (prev_hist_pesos[0] is not None and
                             mejor_individuo != prev_hist_pesos[0])

        if gen_es_hist:
            label = "(nuevo récord)" if hist_cambio_pesos else "(elite)"
        else:
            label = "(challenger)"

        prev_hist_pesos[0] = list(mejor_individuo)

        print(f"  Gen {gen+1:3d}  |  hist {mejor_fitness*100:5.1f}%  "
              f"gen {mejor_gen_fitness*100:5.1f}% {label}  "
              f"media {media*100:5.1f}%  |  {elapsed/60:5.1f} min", flush=True)

        hist_str = '[' + ', '.join(f'{w:.3f}' for w in mejor_individuo) + ']'
        if gen_es_hist:
            print(f"           {hist_str}", flush=True)
        else:
            gen_str = '[' + ', '.join(f'{w:.3f}' for w in mejor_gen_individuo) + ']'
            print(f"           hist: {hist_str}", flush=True)
            print(f"           gen:  {gen_str}", flush=True)
    return callback


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Entrenamiento GA de los pesos del MinimaxAgent")
    parser.add_argument('--rapido', action='store_true',
                        help='Configuración rápida (~30 min) para iterar')
    parser.add_argument('--sin-paralelo', action='store_true',
                        help='Desactivar paralelismo (debug)')
    parser.add_argument('--workers', type=int, default=None,
                        help='Número de procesos paralelos (default: todos los cores). '
                             'Usar menos para dejar CPU libre para otro trabajo.')
    parser.add_argument('--seed', type=int, default=None,
                        help='Master seed para reproducibilidad completa')
    parser.add_argument('--tam', type=int, default=4, choices=[3, 4],
                        help='Tamaño de equipo (default: 4)')
    parser.add_argument('--generaciones', type=int, default=None,
                        help='Sobreescribir número de generaciones. '
                             'Combinable con --resume para extender un run previo.')
    parser.add_argument('--out', type=str, default=RUTA_PESOS_ENTRENADOS,
                        help='Ruta del JSON de salida (y checkpoint para --resume)')
    parser.add_argument('--resume', action='store_true',
                        help='Reanudar entrenamiento desde el checkpoint en --out. '
                             'Si no hay checkpoint o ya está completado, falla.')
    parser.add_argument('--semilla-file', type=str, default=None,
                        help='JSON con pesos previos para usar como semilla inicial '
                             '(útil para fine-tuning alrededor de un run anterior). '
                             'Reemplaza PESOS_EVAL_UNIFORME como centro de la población.')
    parser.add_argument('--sigma', type=float, default=None,
                        help='Desviación gaussiana al perturbar la semilla (default: 0.05). '
                             'Usar valores pequeños (0.02-0.03) para fine-tuning fino.')
    args = parser.parse_args()

    # ── Hiperparámetros ─────────────────────────────────────────────────────
    if args.rapido:
        config = {
            'poblacion_size': 10,
            'generaciones': 12,
            'n_batallas_heur': 12,
            'n_batallas_mini': 4,
            'n_holdout': 20,
        }
        nombre_cfg = "RÁPIDO"
    else:
        # Basket simplificado: solo vs Heurístico (rival más informativo).
        # Basket mixto: 60 vs Heurístico + 20 vs Minimax-manual.
        # Heurístico solo daba fitness 65-95% para casi cualquier individuo →
        # señal demasiado ruidosa y baja diferenciación.
        # Minimax-manual (win rate real ~35-50%) discrimina mucho mejor entre
        # pesos buenos y muy buenos. 80 batallas totales reduce la varianza al
        # punto donde el GA tiene señal real para seleccionar.
        config = {
            'poblacion_size': 20,
            'generaciones': 40,
            'n_batallas_heur': 60,
            'n_batallas_mini': 20,
            'n_holdout': 50,
        }
        nombre_cfg = "PESADO"

    # Override de generaciones desde CLI (útil para extender runs con --resume)
    if args.generaciones is not None:
        config['generaciones'] = args.generaciones

    # ── Workers ─────────────────────────────────────────────────────────────
    import multiprocessing as _mp
    cores_total = _mp.cpu_count()
    if args.sin_paralelo:
        workers_str = "OFF"
    elif args.workers is not None:
        workers_str = f"{args.workers} / {cores_total} cores"
    else:
        workers_str = f"{cores_total} / {cores_total} cores (todos)"

    # ── Banner ──────────────────────────────────────────────────────────────
    print()
    print("  ╔════════════════════════════════════════════════════════════╗")
    print(f"  ║   POKEFISI — Entrenamiento GA del MinimaxAgent  [{nombre_cfg:^6}] ║")
    print("  ╚════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Configuración:")
    print(f"    Población:        {config['poblacion_size']}")
    print(f"    Generaciones:     {config['generaciones']}")
    basket_str = f"{config['n_batallas_heur']} vs Heurístico"
    if config['n_batallas_mini'] > 0:
        basket_str += f" + {config['n_batallas_mini']} vs Minimax-manual"
    print(f"    Basket por ind.:  {basket_str}")
    print(f"    Tamaño equipos:   {args.tam} vs {args.tam}")
    semilla_label = args.semilla_file if args.semilla_file else "PESOS_EVAL_UNIFORME"
    sigma_label = args.sigma if args.sigma is not None else 0.05
    print(f"    Semilla inicial:  {semilla_label} (σ={sigma_label})")
    print(f"    Anclas inmortales: 2 (anti-regresión)")
    print(f"    Workers:          {workers_str}")
    if args.seed is not None:
        print(f"    Master seed:      {args.seed} (reproducible)")
    if args.resume:
        print(f"    Modo:             RESUME desde {args.out}")
    print()

    # Estimación grosera de tiempo
    total_batallas = (config['poblacion_size'] *
                      (config['n_batallas_heur'] + config['n_batallas_mini']) *
                      config['generaciones'])
    t_serial_est = total_batallas * 0.5 / 60  # ~0.5s/batalla Minimax-vs-Heurístico (post opt.)
    if args.sin_paralelo:
        speedup_est = 1
    else:
        speedup_est = max(1, args.workers if args.workers is not None else cores_total)
        # Speedup real es sublineal; descontamos overhead aproximado
        speedup_est = speedup_est * 0.75
    t_paralelo_est = t_serial_est / speedup_est
    print(f"  Estimación: {total_batallas:,} batallas totales")
    print(f"  Tiempo estimado: ~{t_paralelo_est:.0f} min (paralelo ~{speedup_est:.1f}x speedup)")
    print()

    # ── Semilla inicial ──────────────────────────────────────────────────────
    import json as _json
    semilla_inicial = PESOS_EVAL_UNIFORME
    if args.semilla_file is not None:
        try:
            with open(args.semilla_file, 'r', encoding='utf-8') as _f:
                semilla_inicial = _json.load(_f)['pesos']
            print(f"  Semilla cargada desde: {args.semilla_file}")
            print(f"  Pesos semilla: {[f'{w:.4f}' for w in semilla_inicial]}")
            print()
        except Exception as _e:
            print(f"  ⚠️  No se pudo cargar semilla desde {args.semilla_file}: {_e}")
            print(f"     Usando PESOS_EVAL_UNIFORME como fallback.")
            print()

    sigma = args.sigma if args.sigma is not None else 0.05

    # ── Optimizer ───────────────────────────────────────────────────────────
    optimizer = GeneticOptimizer(
        poblacion_size=config['poblacion_size'],
        generaciones=config['generaciones'],
        n_batallas_heur=config['n_batallas_heur'],
        n_batallas_mini=config['n_batallas_mini'],
        semilla=semilla_inicial,
        sigma_semilla=sigma,
        n_anclas=2,
        tam_equipo=args.tam,
        usar_paralelismo=not args.sin_paralelo,
        n_workers=args.workers,
        master_seed=args.seed,
    )

    # ── Resume desde checkpoint ─────────────────────────────────────────────
    estado_inicial = None
    if args.resume:
        estado_inicial = optimizer.cargar_estado_completo(args.out)
        if estado_inicial is None:
            print(f"  ⚠️  No se pudo reanudar desde {args.out}")
            print(f"     (archivo inexistente, ya completado, o sin estado evolutivo)")
            sys.exit(1)
        gen_completada = estado_inicial['gen_completada']
        restantes = config['generaciones'] - (gen_completada + 1)
        if restantes <= 0:
            print(f"  ✓ Checkpoint en {args.out} ya tiene todas las generaciones.")
            print(f"     Eliminá el archivo o aumentá --generaciones para entrenar más.")
            sys.exit(0)
        print(f"  ✓ Reanudando desde gen {gen_completada + 1}/{config['generaciones']} "
              f"({restantes} gens restantes, tiempo previo: "
              f"{estado_inicial['t_acumulado']/60:.1f} min)")
        print(f"  ✓ Mejor histórico: {optimizer.mejor_fitness*100:.1f}%")
        print()

    # ── Entrenamiento ───────────────────────────────────────────────────────
    print("  ── Entrenando ─────────────────────────────────────────────────")
    t_inicio = time.time()
    t_acumulado_previo = estado_inicial['t_acumulado'] if estado_inicial else 0

    mejor_pesos = optimizer.evolucionar(
        callback=_hacer_callback(t_inicio, t_acumulado_previo=t_acumulado_previo),
        checkpoint_path=args.out,
        estado_inicial=estado_inicial,
    )
    t_entrenamiento = time.time() - t_inicio + t_acumulado_previo

    print()
    print(f"  Entrenamiento completado en {t_entrenamiento/60:.1f} min")
    print(f"  Mejor fitness GA: {optimizer.mejor_fitness*100:.1f}%")
    print(f"  Pesos finales:    {[f'{w:.4f}' for w in mejor_pesos]}")

    # ── Validación holdout ──────────────────────────────────────────────────
    print()
    print("  ── Validación honesta (escenarios holdout) ────────────────────")
    print(f"\n  Mejor pesos GA:")
    val_ga = validar(mejor_pesos, n_holdout=config['n_holdout'], tam_equipo=args.tam)

    print(f"\n  Baseline uniforme (referencia):")
    val_uni = validar(PESOS_EVAL_UNIFORME, n_holdout=config['n_holdout'], tam_equipo=args.tam)

    print(f"\n  Baseline manual (referencia):")
    val_man = validar(PESOS_EVAL_DEFAULT, n_holdout=config['n_holdout'], tam_equipo=args.tam)

    # ── Veredicto ───────────────────────────────────────────────────────────
    print()
    print("  ── Comparativa final (vs Heurístico, métrica principal) ──────")
    print(f"    Uniforme:  {val_uni['heuristic']*100:5.1f}%")
    print(f"    Manual:    {val_man['heuristic']*100:5.1f}%")
    print(f"    GA:        {val_ga['heuristic']*100:5.1f}%")
    delta_uni = (val_ga['heuristic'] - val_uni['heuristic']) * 100
    delta_man = (val_ga['heuristic'] - val_man['heuristic']) * 100
    print(f"    Mejora GA vs Uniforme:  {delta_uni:+.1f} pp")
    print(f"    Diferencia GA vs Manual: {delta_man:+.1f} pp")

    # ── Persistencia ────────────────────────────────────────────────────────
    # Guardamos el JSON final con la validación, marcando estado='completado'
    # para que un --resume futuro sobre este archivo no intente continuar.
    optimizer.guardar_pesos(args.out, metadatos_extra={
        'estado': 'completado',
        'validacion_holdout': {
            'ga':       val_ga,
            'uniforme': val_uni,
            'manual':   val_man,
            'n_holdout': config['n_holdout'],
        },
        'tiempo_entrenamiento_min': round(t_entrenamiento / 60, 2),
    })
    print()
    print(f"  Pesos guardados en: {args.out}")
    print(f"  El juego ahora usará estos pesos en modo Difícil.")
    print()


if __name__ == '__main__':
    # IMPORTANTE: este guard es OBLIGATORIO en Windows para multiprocessing
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  [Entrenamiento interrumpido. El checkpoint de la última generación "
              "completada está guardado — podés reanudar con --resume]\n", flush=True)
