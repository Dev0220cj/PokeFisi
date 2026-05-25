"""
Entrenamiento del MinimaxAgent vía algoritmo genético.

Uso:
    py train_minimax.py                  # entrenamiento completo (~3-5 h con paralelismo)
    py train_minimax.py --rapido         # configuración rápida para iterar (~30 min)
    py train_minimax.py --sin-paralelo   # serial (debug)
    py train_minimax.py --seed 42        # reproducible

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

def _hacer_callback(t_inicio, optimizer=None, checkpoint_path=None):
    """Callback que imprime progreso Y opcionalmente guarda checkpoint cada gen.
    El checkpoint permite recuperar los mejores pesos hallados aunque el
    entrenamiento se interrumpa (timeout, crash, etc.).

    Muestra:
    - hist: mejor fitness HISTÓRICO (acumulado desde Gen 1)
    - gen:  mejor fitness DE ESTA GENERACIÓN (puede ser distinto al histórico)
    Si los pesos del mejor histórico coinciden con el mejor de la gen → "(elite)"
    Si no → "(challenger)" y muestra ambos sets de pesos para ver la dirección
    de exploración de la población.
    """
    def callback(gen, mejor_fitness, mejor_gen_fitness, media,
                 mejor_individuo, mejor_gen_individuo):
        elapsed = time.time() - t_inicio

        pesos_iguales = mejor_individuo == mejor_gen_individuo
        label = "(elite)" if pesos_iguales else "(challenger)"

        print(f"  Gen {gen+1:3d}  |  hist {mejor_fitness*100:5.1f}%  "
              f"gen {mejor_gen_fitness*100:5.1f}% {label}  "
              f"media {media*100:5.1f}%  |  {elapsed/60:5.1f} min", flush=True)

        hist_str = '[' + ', '.join(f'{w:.3f}' for w in mejor_individuo) + ']'
        if pesos_iguales:
            print(f"           {hist_str}", flush=True)
        else:
            gen_str = '[' + ', '.join(f'{w:.3f}' for w in mejor_gen_individuo) + ']'
            print(f"           hist: {hist_str}", flush=True)
            print(f"           gen:  {gen_str}", flush=True)

        # ── Checkpoint: persistir progreso después de cada generación ──
        if optimizer is not None and checkpoint_path is not None:
            try:
                optimizer.guardar_pesos(checkpoint_path, metadatos_extra={
                    'estado': 'en_progreso',
                    'gen_actual': gen + 1,
                    'tiempo_transcurrido_min': round(elapsed / 60, 2),
                })
            except Exception as e:
                print(f"  ⚠️  Error al guardar checkpoint: {e}", flush=True)
    return callback


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Entrenamiento GA de los pesos del MinimaxAgent")
    parser.add_argument('--rapido', action='store_true',
                        help='Configuración rápida (~30 min) para iterar')
    parser.add_argument('--sin-paralelo', action='store_true',
                        help='Desactivar paralelismo (debug)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Master seed para reproducibilidad completa')
    parser.add_argument('--tam', type=int, default=4, choices=[3, 4],
                        help='Tamaño de equipo (default: 4)')
    parser.add_argument('--out', type=str, default=RUTA_PESOS_ENTRENADOS,
                        help='Ruta del JSON de salida')
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
        # Quitamos Minimax-vs-Minimax del fitness porque cada batalla cuesta ~2x
        # y aporta menos señal — el Heurístico ya es buena vara de medir.
        # Compensamos subiendo n_batallas_heur de 30 → 40 (más señal por individuo).
        # Holdout sigue evaluando vs los 3 rivales (Random, Heurístico, Minimax).
        config = {
            'poblacion_size': 20,
            'generaciones': 20,        # antes 30 (rendimientos decrecientes)
            'n_batallas_heur': 40,     # antes 30 (más señal)
            'n_batallas_mini': 0,      # antes 10 (quitado del basket)
            'n_holdout': 50,
        }
        nombre_cfg = "PESADO"

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
    print(f"    Semilla inicial:  PESOS_EVAL_UNIFORME (con perturbación σ=0.05)")
    print(f"    Anclas inmortales: 2 (anti-regresión)")
    print(f"    Paralelismo:      {'OFF' if args.sin_paralelo else 'ON (auto)'}")
    if args.seed is not None:
        print(f"    Master seed:      {args.seed} (reproducible)")
    print()

    # Estimación grosera de tiempo
    total_batallas = (config['poblacion_size'] *
                      (config['n_batallas_heur'] + config['n_batallas_mini']) *
                      config['generaciones'])
    t_serial_est = total_batallas * 2.0 / 60  # ~2s/batalla, en minutos
    speedup_est = 1 if args.sin_paralelo else 4
    t_paralelo_est = t_serial_est / speedup_est
    print(f"  Estimación: {total_batallas:,} batallas totales")
    print(f"  Tiempo estimado: ~{t_paralelo_est:.0f} min (paralelo ~4x speedup)")
    print()

    # ── Entrenamiento ───────────────────────────────────────────────────────
    print("  ── Entrenando ─────────────────────────────────────────────────")
    t_inicio = time.time()

    optimizer = GeneticOptimizer(
        poblacion_size=config['poblacion_size'],
        generaciones=config['generaciones'],
        n_batallas_heur=config['n_batallas_heur'],
        n_batallas_mini=config['n_batallas_mini'],
        semilla=PESOS_EVAL_UNIFORME,
        sigma_semilla=0.05,
        n_anclas=2,
        tam_equipo=args.tam,
        usar_paralelismo=not args.sin_paralelo,
        master_seed=args.seed,
    )

    mejor_pesos = optimizer.evolucionar(
        callback=_hacer_callback(t_inicio, optimizer=optimizer, checkpoint_path=args.out)
    )
    t_entrenamiento = time.time() - t_inicio

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
    optimizer.guardar_pesos(args.out, metadatos_extra={
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
    mp_freeze_support_safe = True
    main()
