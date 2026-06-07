"""
Optimización de pesos del MinimaxAgent con Simulated Annealing (SA).

No modifica ningún archivo existente. Reutiliza la infraestructura de
batalla de src/genetic_algorithm.py (generar_escenarios, _jugar_batalla,
_normalizar, simular_batalla) tal cual está.

Ventaja clave frente al GA: en cada paso del SA se evalúan AMBAS soluciones
(actual y vecina) sobre los MISMOS escenarios (CRN — Common Random Numbers).
La diferencia de fitness es mucho menos ruidosa que cada estimación por
separado, lo que permite usar menos batallas por paso y dar más pasos con el
mismo presupuesto total de simulaciones.

Uso:
    py train_sa.py                              # full (~25-50 min)
    py train_sa.py --rapido                     # rápido (~5 min) para iterar
    py train_sa.py --seed 42                    # reproducible
    py train_sa.py --semilla-file data/best_weights_sa.json   # fine-tune
    py train_sa.py --sigma 0.05                 # perturbación más fina
"""
import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ai_agent import (
    N_FACTORES_EVAL, PESOS_EVAL_DEFAULT, PESOS_EVAL_UNIFORME,
)
from src.genetic_algorithm import (
    _normalizar, _jugar_batalla, generar_escenarios, simular_batalla,
)

RUTA_PESOS_SA = os.path.join('data', 'best_weights_sa.json')


# ── Evaluación con escenarios fijos (CRN) ───────────────────────────────────

def _evaluar(pesos, escenarios_heur, escenarios_mini):
    """Win rate combinado del basket (igual que _evaluar_basket_worker del GA).
    Pensado para ser llamado dos veces con los MISMOS escenarios por paso SA."""
    wins_h = sum(
        1 for esc in escenarios_heur
        if _jugar_batalla(pesos, esc[0], esc[1], 'heuristic', battle_seed=esc[2])
    )
    wins_m = sum(
        1 for esc in escenarios_mini
        if _jugar_batalla(pesos, esc[0], esc[1], 'minimax_default', battle_seed=esc[2])
    ) if escenarios_mini else 0
    total = len(escenarios_heur) + len(escenarios_mini)
    return (wins_h + wins_m) / max(1, total)


# ── Perturbación gaussiana ───────────────────────────────────────────────────

def _perturbar(pesos, sigma, rng):
    """Ruido gaussiano componente a componente + renormalización.
    Análogo a _mutar() del GA pero sobre un único individuo."""
    nuevo = [p + rng.gauss(0, sigma) for p in pesos]
    return _normalizar(nuevo)


# ── Algoritmo principal ──────────────────────────────────────────────────────

def simulated_annealing(
    semilla=None,
    n_iter=400,
    n_batallas_heur=20,
    n_batallas_mini=7,
    T_inicial=0.15,
    T_final=0.005,
    sigma=0.08,
    master_seed=None,
    callback=None,
):
    """Optimiza los pesos del MinimaxAgent con SA.

    Esquema de temperatura: cooling geométrico
        T(k) = T_inicial × (T_final / T_inicial)^(k / (n_iter-1))

    CRN por paso: en cada iteración se generan nuevos escenarios y se evalúan
    AMBAS soluciones (actual y vecina) sobre ellos. La diferencia delta es mucho
    menos ruidosa que cada estimación por separado → el criterio Metropolis
    acepta/rechaza con señal más limpia.

    Returns:
        (pesos_mejor, fitness_mejor, historial)
    """
    rng = random.Random(master_seed)

    # Solución de partida
    if semilla is not None:
        pesos_actual = _normalizar(list(semilla))
    else:
        pesos_actual = list(PESOS_EVAL_UNIFORME)

    # Evaluación inicial (escenarios propios, no CRN — solo para el primer display)
    esc_seed0 = rng.randint(0, 2**31 - 1)
    esc_h0 = generar_escenarios(n_batallas_heur, seed=esc_seed0)
    esc_m0 = generar_escenarios(n_batallas_mini, seed=esc_seed0 + 1) if n_batallas_mini > 0 else []
    fitness_actual = _evaluar(pesos_actual, esc_h0, esc_m0)

    pesos_mejor = list(pesos_actual)
    fitness_mejor = fitness_actual

    historial = []
    aceptaciones = 0

    for k in range(n_iter):
        # Temperatura actual (cooling geométrico Kirkpatrick)
        T = T_inicial * (T_final / T_inicial) ** (k / max(1, n_iter - 1))

        # Vecino candidato
        pesos_vecino = _perturbar(pesos_actual, sigma, rng)

        # CRN: mismos escenarios para actual y vecino → delta menos ruidoso
        esc_seed = rng.randint(0, 2**31 - 1)
        esc_h = generar_escenarios(n_batallas_heur, seed=esc_seed)
        esc_m = generar_escenarios(n_batallas_mini, seed=esc_seed + 1) if n_batallas_mini > 0 else []

        fitness_actual_crn = _evaluar(pesos_actual, esc_h, esc_m)
        fitness_vecino = _evaluar(pesos_vecino, esc_h, esc_m)

        delta = fitness_vecino - fitness_actual_crn

        # Criterio de aceptación Metropolis
        if delta > 0 or rng.random() < math.exp(delta / T):
            pesos_actual = pesos_vecino
            fitness_actual = fitness_vecino
            aceptaciones += 1
        else:
            fitness_actual = fitness_actual_crn  # actualizar con la estimación fresca

        # Mejor histórico
        if fitness_actual > fitness_mejor:
            pesos_mejor = list(pesos_actual)
            fitness_mejor = fitness_actual

        historial.append({
            'iter': k,
            'T': round(T, 6),
            'fitness_actual': round(fitness_actual, 4),
            'fitness_mejor': round(fitness_mejor, 4),
            'delta': round(delta, 4),
            'aceptado': delta > 0 or fitness_vecino == fitness_actual,
        })

        if callback:
            callback(k, T, fitness_actual, fitness_mejor,
                     pesos_actual, pesos_mejor, aceptaciones)

    return pesos_mejor, fitness_mejor, historial


# ── Validación holdout ───────────────────────────────────────────────────────

def validar(pesos, n_holdout=50, seed_holdout=999999, tam_equipo=4):
    """Evalúa pesos en escenarios holdout (no vistos durante el SA).
    Alterna lados para cancelar la asimetría estructural del engine.
    Misma lógica que validar() en train_minimax.py."""
    escenarios = generar_escenarios(n_holdout, seed=seed_holdout, tam_equipo=tam_equipo)
    print(f"\n  Validando contra {n_holdout} escenarios × 2 (alternando lados) vs cada rival...")
    resultados = {}
    for rival in ('random', 'heuristic', 'minimax_default'):
        t0 = time.time()
        wr = simular_batalla(pesos, escenarios=escenarios, rival=rival,
                             tam_equipo=tam_equipo, alternar_lados=True)
        resultados[rival] = wr
        print(f"    vs {rival:18s} {wr*100:5.1f}%   ({time.time()-t0:5.1f}s)")
    return resultados


# ── Guardar resultados ───────────────────────────────────────────────────────

def guardar_pesos(path, pesos, fitness, historial, hiperparametros,
                  metadatos_extra=None):
    data = {
        'pesos': pesos,
        'fitness': fitness,
        'historial': historial,
        'fecha': datetime.now().isoformat(timespec='seconds'),
        'algoritmo': 'simulated_annealing',
        'hiperparametros': hiperparametros,
    }
    if metadatos_extra:
        data.update(metadatos_extra)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


# ── Callback de progreso ─────────────────────────────────────────────────────

def _hacer_callback(n_iter, t_inicio):
    prev_mejor = [None]

    def callback(k, T, fitness_actual, fitness_mejor, pesos_actual,
                 pesos_mejor, aceptaciones):
        elapsed = time.time() - t_inicio
        tasa_ac = aceptaciones / max(1, k + 1) * 100

        mejora = ""
        if prev_mejor[0] is not None and fitness_mejor > prev_mejor[0]:
            mejora = " ← nuevo récord"
        prev_mejor[0] = fitness_mejor

        print(f"  Iter {k+1:4d}/{n_iter}  |  "
              f"T={T:.4f}  actual {fitness_actual*100:5.1f}%  "
              f"mejor {fitness_mejor*100:5.1f}%{mejora}  "
              f"ac.rate {tasa_ac:4.0f}%  |  {elapsed/60:5.1f} min",
              flush=True)

        pesos_str = '[' + ', '.join(f'{w:.3f}' for w in pesos_mejor) + ']'
        print(f"           mejor: {pesos_str}", flush=True)

    return callback


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Optimización SA de los pesos del MinimaxAgent")
    parser.add_argument('--rapido', action='store_true',
                        help='Configuración rápida (~5 min) para iterar')
    parser.add_argument('--seed', type=int, default=None,
                        help='Master seed para reproducibilidad')
    parser.add_argument('--semilla-file', type=str, default=None,
                        help='JSON con pesos previos como punto de partida')
    parser.add_argument('--sigma', type=float, default=None,
                        help='Desviación gaussiana de la perturbación (default: 0.08)')
    parser.add_argument('--out', type=str, default=RUTA_PESOS_SA,
                        help='Ruta del JSON de salida')
    parser.add_argument('--T-ini', type=float, default=None,
                        help='Temperatura inicial (default: 0.15)')
    parser.add_argument('--T-fin', type=float, default=None,
                        help='Temperatura final (default: 0.005)')
    parser.add_argument('--iteraciones', type=int, default=None,
                        help='Número de iteraciones SA (override de config)')
    args = parser.parse_args()

    # ── Hiperparámetros ──────────────────────────────────────────────────────
    if args.rapido:
        config = {
            'n_iter': 100,
            'n_batallas_heur': 10,
            'n_batallas_mini': 0,
            'n_holdout': 20,
        }
        nombre_cfg = "RÁPIDO"
    else:
        config = {
            'n_iter': 400,
            'n_batallas_heur': 20,
            'n_batallas_mini': 7,
            'n_holdout': 50,
        }
        nombre_cfg = "COMPLETO"

    if args.iteraciones is not None:
        config['n_iter'] = args.iteraciones

    T_ini = args.T_ini if args.T_ini is not None else 0.15
    T_fin = args.T_fin if args.T_fin is not None else 0.005
    sigma = args.sigma if args.sigma is not None else 0.08

    # ── Semilla inicial ──────────────────────────────────────────────────────
    semilla_inicial = list(PESOS_EVAL_UNIFORME)
    semilla_label = "PESOS_EVAL_UNIFORME"
    if args.semilla_file is not None:
        try:
            with open(args.semilla_file, 'r', encoding='utf-8') as f:
                semilla_inicial = json.load(f)['pesos']
            semilla_label = args.semilla_file
        except Exception as e:
            print(f"  ⚠️  No se pudo cargar semilla: {e}  →  usando PESOS_EVAL_UNIFORME")

    # ── Presupuesto estimado (para comparar con GA) ──────────────────────────
    # Cada paso: 2 evaluaciones CRN × (heur + mini) batallas
    batallas_por_paso = 2 * (config['n_batallas_heur'] + config['n_batallas_mini'])
    total_batallas = config['n_iter'] * batallas_por_paso
    # GA rapido:   10 pop × 16 batallas × 12 gens =  1,920 batallas
    # GA completo: 20 pop × 80 batallas × 40 gens = 64,000 batallas
    t_est = total_batallas * 0.5 / 60  # ~0.5s por batalla Minimax-vs-Heurístico

    # ── Banner ───────────────────────────────────────────────────────────────
    print()
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print(f"  ║  POKEFISI — Simulated Annealing del MinimaxAgent  [{nombre_cfg:^8}] ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Configuración:")
    print(f"    Iteraciones:      {config['n_iter']}")
    basket_str = f"{config['n_batallas_heur']} vs Heurístico"
    if config['n_batallas_mini'] > 0:
        basket_str += f" + {config['n_batallas_mini']} vs Minimax-manual"
    print(f"    Basket por paso:  {basket_str}  (× 2 con CRN = {batallas_por_paso} batallas/paso)")
    print(f"    Total batallas:   {total_batallas:,}  (vs GA rapido ~1,920 / GA full ~64,000)")
    print(f"    T: {T_ini} → {T_fin}  (cooling geométrico)")
    print(f"    σ perturbación:   {sigma}")
    print(f"    Punto de partida: {semilla_label}")
    if args.seed is not None:
        print(f"    Master seed:      {args.seed}")
    print(f"    Salida:           {args.out}")
    print()
    print(f"  Tiempo estimado:  ~{t_est:.0f} min (serial, sin paralelismo)")
    print()

    # ── SA ───────────────────────────────────────────────────────────────────
    print("  ── Optimizando ────────────────────────────────────────────────")
    t_inicio = time.time()

    mejor_pesos, mejor_fitness, historial = simulated_annealing(
        semilla=semilla_inicial,
        n_iter=config['n_iter'],
        n_batallas_heur=config['n_batallas_heur'],
        n_batallas_mini=config['n_batallas_mini'],
        T_inicial=T_ini,
        T_final=T_fin,
        sigma=sigma,
        master_seed=args.seed,
        callback=_hacer_callback(config['n_iter'], t_inicio),
    )

    t_total = time.time() - t_inicio
    print()
    print(f"  SA completado en {t_total/60:.1f} min")
    print(f"  Mejor fitness SA: {mejor_fitness*100:.1f}%")
    print(f"  Pesos finales:    {[f'{w:.4f}' for w in mejor_pesos]}")

    # ── Validación holdout ───────────────────────────────────────────────────
    print()
    print("  ── Validación honesta (escenarios holdout) ────────────────────")
    print(f"\n  SA (pesos encontrados):")
    val_sa = validar(mejor_pesos, n_holdout=config['n_holdout'])

    print(f"\n  Baseline uniforme (referencia):")
    val_uni = validar(PESOS_EVAL_UNIFORME, n_holdout=config['n_holdout'])

    print(f"\n  Baseline manual (referencia):")
    val_man = validar(PESOS_EVAL_DEFAULT, n_holdout=config['n_holdout'])

    # ── Comparativa ──────────────────────────────────────────────────────────
    print()
    print("  ── Comparativa final (vs Heurístico, métrica principal) ────────")
    print(f"    Uniforme:  {val_uni['heuristic']*100:5.1f}%")
    print(f"    Manual:    {val_man['heuristic']*100:5.1f}%")
    print(f"    SA:        {val_sa['heuristic']*100:5.1f}%")
    delta_uni = (val_sa['heuristic'] - val_uni['heuristic']) * 100
    delta_man = (val_sa['heuristic'] - val_man['heuristic']) * 100
    print(f"    Mejora SA vs Uniforme:  {delta_uni:+.1f} pp")
    print(f"    Diferencia SA vs Manual: {delta_man:+.1f} pp")

    # Si existe resultado del GA, comparar directamente
    ga_path = os.path.join('data', 'best_weights.json')
    if os.path.exists(ga_path):
        try:
            with open(ga_path, 'r', encoding='utf-8') as f:
                ga_data = json.load(f)
            ga_pesos = ga_data.get('pesos')
            if ga_pesos:
                print()
                print(f"\n  GA (pesos guardados en {ga_path}):")
                val_ga = validar(ga_pesos, n_holdout=config['n_holdout'])
                delta_sa_ga = (val_sa['heuristic'] - val_ga['heuristic']) * 100
                print()
                print(f"    SA vs GA (vs Heurístico): {delta_sa_ga:+.1f} pp  "
                      f"({'SA gana' if delta_sa_ga > 0 else 'GA gana' if delta_sa_ga < 0 else 'empate'})")
        except Exception:
            pass

    # ── Persistencia ─────────────────────────────────────────────────────────
    hiperparametros = {
        'n_iter': config['n_iter'],
        'n_batallas_heur': config['n_batallas_heur'],
        'n_batallas_mini': config['n_batallas_mini'],
        'T_inicial': T_ini,
        'T_final': T_fin,
        'sigma': sigma,
        'master_seed': args.seed,
        'semilla': semilla_label,
    }
    guardar_pesos(
        args.out, mejor_pesos, mejor_fitness, historial, hiperparametros,
        metadatos_extra={
            'validacion_holdout': {
                'sa':      val_sa,
                'uniforme': val_uni,
                'manual':  val_man,
                'n_holdout': config['n_holdout'],
            },
            'tiempo_entrenamiento_min': round(t_total / 60, 2),
            'total_batallas': total_batallas,
        }
    )
    print()
    print(f"  Pesos guardados en: {args.out}")
    print()


if __name__ == '__main__':
    main()
