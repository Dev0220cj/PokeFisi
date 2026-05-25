"""
Algoritmo genético para optimizar los pesos de la función `evaluar()` del MinimaxAgent.

Diseño clave:
- **CRN (Common Random Numbers)**: todos los individuos de una misma generación juegan
  los mismos escenarios con los mismos seeds → la diferencia de fitness refleja casi
  solo diferencias de estrategia, no de suerte. Reduce varianza dramáticamente.
- **Basket de fitness**: 30 batallas vs HeuristicAgent + 10 vs MinimaxAgent(manual).
  Sin Random porque es señal saturada (todo individuo decente gana ~85 %+).
- **Semilla inicial**: la población se siembra alrededor de un vector de pesos dado
  (típicamente PESOS_EVAL_UNIFORME) con ruido gaussiano. Búsqueda local + anclas.
- **Paralelismo**: evaluación de la población en multiprocessing.Pool (~3-4x speedup
  con 8-12 workers en Windows).
"""
import json
import os
import random
import multiprocessing as mp
from datetime import datetime

from config import GENETIC_POPULATION, GENETIC_GENERATIONS, GENETIC_BATTLES_PER_EVAL
from src.pokemon import cargar_pokemon, lista_nombres_pokemon
from src.battle_engine import BattleEngine
from src.ai_agent import (
    RandomAgent, HeuristicAgent, MinimaxAgent,
    N_FACTORES_EVAL, PESOS_EVAL_DEFAULT, PESOS_EVAL_UNIFORME,
)
from src.agent_utils import AgenteVolteado


# ── Utilidades de pesos ──────────────────────────────────────────────────────

def _normalizar(pesos):
    """Normaliza un vector de pesos para que sumen 1 (en valor absoluto).
    Si todos son cero, devuelve uniforme."""
    total = sum(abs(w) for w in pesos)
    if total == 0:
        return [1.0 / N_FACTORES_EVAL] * N_FACTORES_EVAL
    return [abs(w) / total for w in pesos]


# ── Generación de escenarios reproducibles ───────────────────────────────────

def generar_escenarios(n, seed=None, tam_equipo=4):
    """Genera n escenarios reproducibles. Cada escenario es una tupla:
        (nombres_jugador, nombres_ia, battle_seed)
    donde `battle_seed` se usa dentro de _jugar_batalla para sembrar el RNG
    antes de simular (CRN — Common Random Numbers).

    Si `seed` se pasa, la lista de escenarios es determinista (mismo seed →
    misma lista). Esto es crítico para que todos los individuos de una
    generación enfrenten EXACTAMENTE los mismos rivales y dados.
    """
    rng = random.Random(seed) if seed is not None else random
    nombres_all = lista_nombres_pokemon()
    escenarios = []
    for _ in range(n):
        muestra = rng.sample(nombres_all, tam_equipo * 2)
        battle_seed = rng.randint(0, 2**31 - 1)
        escenarios.append((muestra[:tam_equipo], muestra[tam_equipo:], battle_seed))
    return escenarios


# ── Factory de rivales (todos picklables para multiprocessing) ───────────────

def _crear_rival_random():
    return RandomAgent()


def _crear_rival_heuristic():
    return HeuristicAgent()


def _crear_rival_minimax_default():
    """Minimax con pesos manuales — el "sparring fuerte" del basket."""
    return MinimaxAgent(pesos=PESOS_EVAL_DEFAULT)


_AGENTES_RIVALES = {
    'random':           _crear_rival_random,
    'heuristic':        _crear_rival_heuristic,
    'minimax_default':  _crear_rival_minimax_default,
}


# ── Simulación de una batalla individual ─────────────────────────────────────

def _jugar_batalla(pesos_ia, nombres_j, nombres_i, rival='heuristic',
                   battle_seed=None, lado_trainee='ia'):
    """Simula una batalla con el escenario dado. Devuelve True si gana el trainee.

    `lado_trainee`:
      - 'ia'      → trainee juega como ia (lado con auto-cambio mid-turn).
                    Modo default, coincide con el deployment en main.py.
      - 'jugador' → trainee juega como jugador (con AgenteVolteado).
                    Útil para validación: alternando ambos lados cancela
                    la asimetría estructural del engine.

    Si `battle_seed` se pasa, siembra `random.seed()` antes de empezar (CRN).
    """
    if battle_seed is not None:
        random.seed(battle_seed)

    equipo_j = [cargar_pokemon(n) for n in nombres_j]
    equipo_i = [cargar_pokemon(n) for n in nombres_i]

    engine = BattleEngine(equipo_j, equipo_i)
    trainee = MinimaxAgent(pesos=pesos_ia, profundidad=2)
    rival_agent = _AGENTES_RIVALES[rival]()

    # CRÍTICO: el agente que esté del lado 'jugador' DEBE estar envuelto en
    # AgenteVolteado. Los agentes están hardcoded a leer estado['ia']; sin
    # el wrapper deciden con la información del oponente y juegan a ciegas.
    if lado_trainee == 'ia':
        agente_ia = trainee
        agente_j = AgenteVolteado(rival_agent)
    else:  # lado_trainee == 'jugador'
        agente_ia = rival_agent
        agente_j = AgenteVolteado(trainee)

    for _ in range(200):
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

    return engine.ganador() == lado_trainee


def simular_batalla(pesos_ia, n_batallas=None, escenarios=None, rival='heuristic',
                    tam_equipo=4, alternar_lados=False):
    """Calcula win rate de MinimaxAgent(pesos_ia) vs el agente `rival`.

    Si `alternar_lados=True`, cada escenario se juega DOS veces (una por cada
    lado), cancelando la asimetría estructural del engine (la IA tiene ventaja
    al auto-cambiar mid-turn cuando muere un Pokémon). Usado en validación para
    obtener números honestos comparables al benchmark.

    Si se pasan `escenarios` (tuplas (nombres_j, nombres_i, battle_seed)),
    los usa fielmente. Si no, genera n_batallas escenarios aleatorios.
    """
    if escenarios is None:
        n = n_batallas if n_batallas is not None else GENETIC_BATTLES_PER_EVAL
        escenarios = generar_escenarios(n, tam_equipo=tam_equipo)

    victorias = 0
    total = 0
    for esc in escenarios:
        bs = esc[2] if len(esc) >= 3 else None
        # Trainee como ia
        if _jugar_batalla(pesos_ia, esc[0], esc[1], rival,
                          battle_seed=bs, lado_trainee='ia'):
            victorias += 1
        total += 1
        if alternar_lados:
            # Trainee como jugador (con seed shifted para variar los dados)
            bs2 = (bs + 1) if bs is not None else None
            if _jugar_batalla(pesos_ia, esc[0], esc[1], rival,
                              battle_seed=bs2, lado_trainee='jugador'):
                victorias += 1
            total += 1

    return victorias / max(1, total)


# ── Worker para multiprocessing.Pool (debe ser picklable a nivel módulo) ────

def _evaluar_basket_worker(args):
    """Evalúa un individuo contra el basket completo. Devuelve win rate combinado.
    Cada batalla del basket vale lo mismo (proporcional al número de batallas
    por rival), lo cual es estadísticamente sano sin sobre-ponderar al rival
    de menor muestra.
    """
    pesos, escenarios_heur, escenarios_mini = args
    wins_h = sum(
        1 for esc in escenarios_heur
        if _jugar_batalla(pesos, esc[0], esc[1], 'heuristic', battle_seed=esc[2])
    )
    wins_m = sum(
        1 for esc in escenarios_mini
        if _jugar_batalla(pesos, esc[0], esc[1], 'minimax_default', battle_seed=esc[2])
    )
    total = len(escenarios_heur) + len(escenarios_mini)
    return (wins_h + wins_m) / max(1, total)


# ── Optimizador Genético ─────────────────────────────────────────────────────

class GeneticOptimizer:
    """GA con población sembrada, CRN, basket de rivales y paralelismo opcional.

    Parámetros principales:
        poblacion_size:    individuos por generación
        generaciones:      número de generaciones
        n_batallas_heur:   batallas vs HeuristicAgent por individuo (default 30)
        n_batallas_mini:   batallas vs MinimaxAgent-default por individuo (default 10)
        semilla:           vector base para sembrar la población inicial
                           (None = aleatoria; recomendado: PESOS_EVAL_UNIFORME)
        sigma_semilla:     desviación gaussiana al perturbar la semilla
        n_anclas:          cuántas copias exactas de la semilla se mantienen
                           inmortales en la población (anti-regresión)
        tam_equipo:        4 vs 4 (default) o 3 vs 3
        usar_paralelismo:  True → multiprocessing.Pool con n_workers procesos
        n_workers:         número de procesos (None = mp.cpu_count())
        master_seed:       seed maestro para reproducibilidad COMPLETA
                           (incluyendo escenarios, mutaciones, selección)
    """

    def __init__(self,
                 poblacion_size=None, generaciones=None,
                 n_batallas_heur=30, n_batallas_mini=10,
                 semilla=None, sigma_semilla=0.05, n_anclas=2,
                 tam_equipo=4,
                 usar_paralelismo=True, n_workers=None,
                 master_seed=None):
        self.poblacion_size = poblacion_size or GENETIC_POPULATION
        self.generaciones = generaciones or GENETIC_GENERATIONS
        self.n_batallas_heur = n_batallas_heur
        self.n_batallas_mini = n_batallas_mini
        self.semilla = list(semilla) if semilla is not None else None
        self.sigma_semilla = sigma_semilla
        self.n_anclas = n_anclas
        self.tam_equipo = tam_equipo
        self.usar_paralelismo = usar_paralelismo
        self.n_workers = n_workers if n_workers is not None else mp.cpu_count()
        self.master_seed = master_seed

        # RNG propio para todas las decisiones del GA (selección, mutación,
        # generación de seeds de escenarios). Independiente de random global.
        self._rng = random.Random(master_seed)

        # Resultados
        self.mejor_individuo = None
        self.mejor_fitness = -1.0
        self.historial = []

    # ── Operadores genéticos ────────────────────────────────────────────────

    def _crear_individuo(self):
        """Si hay semilla → perturbación gaussiana alrededor de ella.
        Si no → vector aleatorio (comportamiento original)."""
        if self.semilla is not None:
            pesos = [s + self._rng.gauss(0, self.sigma_semilla) for s in self.semilla]
        else:
            pesos = [self._rng.random() for _ in range(N_FACTORES_EVAL)]
        return _normalizar(pesos)

    def _seleccion_torneo(self, poblacion, fitnesses, k=3):
        candidatos = self._rng.sample(range(len(poblacion)), min(k, len(poblacion)))
        mejor = max(candidatos, key=lambda i: fitnesses[i])
        return poblacion[mejor]

    def _cruzamiento(self, padre1, padre2):
        punto = self._rng.randint(1, len(padre1) - 1)
        hijo = padre1[:punto] + padre2[punto:]
        return _normalizar(hijo)

    def _mutar(self, individuo, prob=0.2, sigma=0.08):
        nuevo = list(individuo)
        for i in range(len(nuevo)):
            if self._rng.random() < prob:
                nuevo[i] += self._rng.gauss(0, sigma)
        return _normalizar(nuevo)

    # ── Evaluación de la población (paralela o serial) ──────────────────────

    def _evaluar_poblacion(self, poblacion, escenarios_heur, escenarios_mini, pool=None):
        """Evalúa todos los individuos contra el mismo basket (CRN)."""
        tasks = [(ind, escenarios_heur, escenarios_mini) for ind in poblacion]
        if pool is not None:
            return list(pool.map(_evaluar_basket_worker, tasks))
        return [_evaluar_basket_worker(t) for t in tasks]

    # ── Ciclo evolutivo principal ───────────────────────────────────────────

    def evolucionar(self, callback=None):
        """Corre el GA. Devuelve el mejor individuo encontrado."""
        gens = self.generaciones

        # ── Población inicial: anclas + individuos sembrados/aleatorios ─────
        poblacion = []
        if self.semilla is not None:
            # n_anclas copias exactas de la semilla (anti-regresión)
            for _ in range(min(self.n_anclas, self.poblacion_size)):
                poblacion.append(list(self.semilla))
        while len(poblacion) < self.poblacion_size:
            poblacion.append(self._crear_individuo())

        # ── Pool de workers (uno solo para todo el entrenamiento) ───────────
        pool_ctx = None
        if self.usar_paralelismo and self.n_workers > 1:
            pool_ctx = mp.Pool(self.n_workers)

        try:
            # Escenarios para la primera evaluación
            scen_seed = self._rng.randint(0, 2**31 - 1)
            esc_h = generar_escenarios(self.n_batallas_heur, seed=scen_seed,
                                        tam_equipo=self.tam_equipo)
            esc_m = generar_escenarios(self.n_batallas_mini, seed=scen_seed + 1,
                                        tam_equipo=self.tam_equipo)
            fitnesses = self._evaluar_poblacion(poblacion, esc_h, esc_m, pool_ctx)

            for gen in range(gens):
                # Actualizar mejor histórico
                mejor_idx = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
                if fitnesses[mejor_idx] > self.mejor_fitness:
                    self.mejor_fitness = fitnesses[mejor_idx]
                    self.mejor_individuo = list(poblacion[mejor_idx])

                media = sum(fitnesses) / len(fitnesses)
                self.historial.append({
                    'gen': gen,
                    'mejor': self.mejor_fitness,
                    'mejor_gen': fitnesses[mejor_idx],
                    'media': media,
                })

                if callback:
                    callback(gen, self.mejor_fitness, media, self.mejor_individuo)

                # ── Construir nueva generación ──────────────────────────────
                # Escenarios nuevos (renueva la presión selectiva entre generaciones)
                scen_seed = self._rng.randint(0, 2**31 - 1)
                esc_h = generar_escenarios(self.n_batallas_heur, seed=scen_seed,
                                            tam_equipo=self.tam_equipo)
                esc_m = generar_escenarios(self.n_batallas_mini, seed=scen_seed + 1,
                                            tam_equipo=self.tam_equipo)

                # Elitismo: el campeón pasa directo (re-evaluado con escenarios nuevos
                # para no arrastrar fitness "suertudos")
                nueva_poblacion = [list(poblacion[mejor_idx])]
                # Las anclas se mantienen si hay semilla (anti-regresión)
                if self.semilla is not None:
                    for _ in range(self.n_anclas):
                        if len(nueva_poblacion) < self.poblacion_size:
                            nueva_poblacion.append(list(self.semilla))

                while len(nueva_poblacion) < self.poblacion_size:
                    p1 = self._seleccion_torneo(poblacion, fitnesses)
                    p2 = self._seleccion_torneo(poblacion, fitnesses)
                    hijo = self._cruzamiento(p1, p2)
                    hijo = self._mutar(hijo)
                    nueva_poblacion.append(hijo)

                poblacion = nueva_poblacion
                fitnesses = self._evaluar_poblacion(poblacion, esc_h, esc_m, pool_ctx)
        finally:
            if pool_ctx is not None:
                pool_ctx.close()
                pool_ctx.join()

        return self.mejor_individuo

    # ── Persistencia ────────────────────────────────────────────────────────

    def guardar_pesos(self, path, metadatos_extra=None):
        """Guarda los mejores pesos en JSON con metadatos para trazabilidad."""
        data = {
            'pesos': self.mejor_individuo,
            'fitness': self.mejor_fitness,
            'historial': self.historial,
            'fecha': datetime.now().isoformat(timespec='seconds'),
            'hiperparametros': {
                'poblacion_size': self.poblacion_size,
                'generaciones': self.generaciones,
                'n_batallas_heur': self.n_batallas_heur,
                'n_batallas_mini': self.n_batallas_mini,
                'sigma_semilla': self.sigma_semilla,
                'n_anclas': self.n_anclas,
                'tam_equipo': self.tam_equipo,
                'master_seed': self.master_seed,
                'semilla': self.semilla,
            },
        }
        if metadatos_extra:
            data.update(metadatos_extra)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def cargar_pesos(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.mejor_individuo = data.get('pesos')
        self.mejor_fitness = data.get('fitness', -1.0)
        self.historial = data.get('historial', [])
        return self.mejor_individuo
