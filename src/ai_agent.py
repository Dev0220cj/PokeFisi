import json
import os
import random
import copy

from src.battle_engine import BattleEngine, calcular_efectividad
from config import MINIMAX_DEPTH, MINIMAX_SAMPLES, MINIMAX_SAMPLES_DEEP


# ---------------------------------------------------------------------------
# Nivel 1: Agente Aleatorio
# ---------------------------------------------------------------------------

class RandomAgent:
    """Elige movimientos y cambios completamente al azar."""

    def elegir_accion(self, estado):
        activo = estado['ia']['activo']
        equipo = estado['ia']['equipo']
        activo_idx = estado['ia']['activo_idx']

        opciones = []

        # Movimientos disponibles
        for i, mov in enumerate(activo.movimientos):
            if mov.tiene_pp():
                opciones.append({'tipo': 'movimiento', 'indice': i})

        # Cambios posibles
        for i, p in enumerate(equipo):
            if p.esta_vivo() and i != activo_idx:
                opciones.append({'tipo': 'cambio', 'indice': i})

        if not opciones:
            return {'tipo': 'movimiento', 'indice': 0}

        return random.choice(opciones)


# ---------------------------------------------------------------------------
# Nivel 2: Agente Heurístico
# ---------------------------------------------------------------------------

class HeuristicAgent:
    """Nivel 2 — Heurística básica basada en diferencia de HP.

    Score de cada movimiento ofensivo: `poder × efectividad × STAB × (precision/100)`.
    Movimientos de estado: score fijo bajo (priorizan daño directo).
    Cambia de Pokémon solo si el activo tiene HP bajo (< 30 %), eligiendo al
    candidato con más HP relativo y mejor matchup ofensivo sencillo.
    """

    def elegir_accion(self, estado):
        activo_ia = estado['ia']['activo']
        activo_j = estado['jugador']['activo']
        equipo_ia = estado['ia']['equipo']
        activo_idx = estado['ia']['activo_idx']

        mejor_score = float('-inf')
        mejor_accion = None

        # ---- Evaluar movimientos: poder × ef × STAB × precisión ----
        for i, mov in enumerate(activo_ia.movimientos):
            if not mov.tiene_pp():
                continue
            score = self._score_movimiento(activo_ia, activo_j, mov)
            if score > mejor_score:
                mejor_score = score
                mejor_accion = {'tipo': 'movimiento', 'indice': i}

        # ---- Evaluar cambio solo cuando HP del activo es bajo ----
        hp_ratio = activo_ia.hp / activo_ia.hp_max
        if hp_ratio < 0.3:
            for i, p in enumerate(equipo_ia):
                if not p.esta_vivo() or i == activo_idx:
                    continue
                cambio_score = self._score_cambio(p, activo_j)
                if cambio_score > mejor_score:
                    mejor_score = cambio_score
                    mejor_accion = {'tipo': 'cambio', 'indice': i}

        # Fallback: si no hay ningún movimiento válido (todo sin PP), elegir uno al azar
        if mejor_accion is None:
            movs_validos = [i for i, m in enumerate(activo_ia.movimientos) if m.tiene_pp()]
            if movs_validos:
                mejor_accion = {'tipo': 'movimiento', 'indice': random.choice(movs_validos)}
            else:
                mejor_accion = {'tipo': 'movimiento', 'indice': 0}

        return mejor_accion

    def _score_movimiento(self, atacante, defensor, mov):
        """Heurística simple: poder × efectividad × STAB × precisión."""
        if mov.poder > 0:
            ef = calcular_efectividad(mov.tipo, defensor.tipos)
            stab = 1.5 if mov.tipo in atacante.tipos else 1.0
            return mov.poder * ef * stab * (mov.precision / 100)

        # Movimientos de estado: score fijo bajo (no es el foco del Nivel 2)
        if mov.efecto:
            return 25 * (mov.precision / 100)
        return 0

    def _score_cambio(self, candidato, rival):
        """Cambio simple: preferir candidato con más HP y ventaja de tipo básica."""
        # Ventaja de tipo: efectividad del primer tipo del rival sobre el candidato
        # (más alto = más vulnerable; queremos resistir, por eso invertimos)
        tipo_rival = rival.tipos[0] if rival.tipos else 'Normal'
        vulnerabilidad = calcular_efectividad(tipo_rival, candidato.tipos)
        # Score = 20 base + HP relativo del candidato + bonus por resistir al rival
        return 20 + (candidato.hp / candidato.hp_max) * 30 + (1.0 / max(0.1, vulnerabilidad)) * 10


# ---------------------------------------------------------------------------
# Helpers para la función de evaluación del Minimax (factor severity)
# Cada uno devuelve un escalar en [0, 1] que indica "cuán mal" está el Pokémon.
# ---------------------------------------------------------------------------

def gravedad_estado(p):
    """Severidad del estado principal del Pokémon, normalizada a [0, 1]."""
    if p.estado == 'dormir':
        # Más grave si quedan más turnos de sueño (turnos_dormido ∈ {2..5})
        return min(1.0, 0.3 + 0.1 * p.turnos_dormido)
    if p.estado == 'congelar':
        return 0.7   # 80 % de no moverse
    if p.estado == 'paralizar':
        return 0.3   # 25 % de no moverse + velocidad /2
    if p.estado == 'envenenar':
        return 0.2   # -1/8 HP por turno
    if p.estado == 'envenenar_grave':
        return min(0.6, 0.2 + 0.08 * p.contador_veneno)  # daño creciente
    if p.estado == 'quemar':
        return 0.25  # -1/8 HP + daño físico /2
    return 0.0


def dot_residual(p):
    """Daño residual NO causado por estado principal: drenadoras, maldición, confusión.
    Devuelve [0, 1]."""
    score = 0.0
    if p.tiene_drenadoras:
        score += 0.25  # -1/8 HP por turno
    if p.tiene_maldicion:
        score += 0.40  # -1/4 HP por turno
    if p.turnos_confundido > 0:
        # Confusión: 33 % auto-daño por turno restante (escalado al máximo de 5 turnos)
        score += 0.08 * p.turnos_confundido
    return min(1.0, score)


def pp_disponible(p):
    """Fracción de PP disponible del activo: [0, 1]. Un Pokémon sin PP es inútil."""
    pp = sum(m.pp for m in p.movimientos)
    pp_max = sum(m.pp_max for m in p.movimientos)
    return pp / max(1, pp_max)


# ---------------------------------------------------------------------------
# Nivel 3: Minimax con poda alfa-beta
# ---------------------------------------------------------------------------

# Factores de la función de evaluación, en orden. Los pesos default suman 1.
# El GeneticOptimizer usa N_FACTORES_EVAL para crear individuos del tamaño correcto.
N_FACTORES_EVAL = 7

# Pesos de referencia ajustados a mano (ground truth experto, expuestos vía benchmark).
PESOS_EVAL_DEFAULT = [
    0.35,   # 0: hp_ratio          - diferencia de HP normalizado total
    0.25,   # 1: vivos_ratio       - diferencia de Pokémon vivos
    0.15,   # 2: type_advantage    - mejor efectividad del activo
    0.05,   # 3: speed_ratio       - ventaja de velocidad
    0.10,   # 4: estado_ratio      - gravedad de estados (rival - propio)
    0.07,   # 5: dot_ratio         - DoT residual (rival - propio)
    0.03,   # 6: pp_ratio          - PP disponible del activo (propio - rival)
]

# Pesos uniformes — Minimax "sin entrenar" (no asume prior sobre qué factor importa más).
# Es el baseline neutro desde el que el GA evoluciona y la referencia honesta
# para medir la contribución del entrenamiento.
PESOS_EVAL_UNIFORME = [1.0 / N_FACTORES_EVAL] * N_FACTORES_EVAL

# Ruta donde el GA persiste los pesos optimizados.
RUTA_PESOS_ENTRENADOS = os.path.join('data', 'best_weights.json')


def cargar_pesos_entrenados(path=RUTA_PESOS_ENTRENADOS):
    """Devuelve la lista de pesos guardada por el GA, o None si no existe.
    El JSON tiene formato {'pesos': [...], 'fitness': ..., 'historial': [...], ...}."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        pesos = data.get('pesos')
        if pesos and len(pesos) == N_FACTORES_EVAL:
            return list(pesos)
    except (json.JSONDecodeError, OSError):
        pass
    return None


class MinimaxAgent:
    """Minimax con poda alfa-beta y función de evaluación compuesta.

    El motor de batalla es estocástico (precisión, status, parálisis, confusión...).
    Para evitar que minimax tome decisiones basándose en un único rollout ruidoso,
    cada par (accion_ia, accion_j) se evalúa promediando `n_samples` rollouts.
    """

    def __init__(self, pesos=None, profundidad=None, n_samples=None, n_samples_deep=None):
        # Pesos: si no se pasan, el agente arranca "sin entrenar" (uniformes).
        # Cada call site (UI, benchmark, train) decide explícitamente qué variante usar:
        #   MinimaxAgent(pesos=PESOS_EVAL_UNIFORME)        → sin entrenamiento
        #   MinimaxAgent(pesos=cargar_pesos_entrenados())  → entrenado por GA
        #   MinimaxAgent(pesos=PESOS_EVAL_DEFAULT)         → referencia manual
        self.pesos = list(pesos) if pesos is not None else list(PESOS_EVAL_UNIFORME)
        self.profundidad = profundidad if profundidad is not None else MINIMAX_DEPTH
        self.n_samples = n_samples if n_samples is not None else MINIMAX_SAMPLES
        self.n_samples_deep = n_samples_deep if n_samples_deep is not None else MINIMAX_SAMPLES_DEEP

    def _rollout_promedio(self, engine, accion_j, accion_ia, profundidad, alpha, beta, n_samples):
        """Ejecuta `n_samples` rollouts del par de acciones y devuelve la evaluación promedio.
        En la raíz se usa n_samples=self.n_samples para suavizar la decisión final;
        en niveles profundos n_samples=1 (rollout único) para no multiplicar el costo."""
        if n_samples == 1:
            engine_clon = engine.clonar()
            engine_clon.ejecutar_turno(accion_j, accion_ia)
            return self.minimax(engine_clon, profundidad, alpha, beta)
        suma = 0.0
        for _ in range(n_samples):
            engine_clon = engine.clonar()
            engine_clon.ejecutar_turno(accion_j, accion_ia)
            suma += self.minimax(engine_clon, profundidad, alpha, beta)
        return suma / n_samples

    def evaluar(self, engine):
        """Función de evaluación normalizada desde la perspectiva de la IA.
        Todos los factores caen en [-1, 1] para evitar saturación entre términos."""
        equipo_ia = engine.equipos['ia']
        equipo_j = engine.equipos['jugador']
        activo_ia = engine.pokemon_activo('ia')
        activo_j = engine.pokemon_activo('jugador')

        # Factor 0: HP total normalizado (rival pierde HP → bueno para IA)
        hp_ia = sum(p.hp for p in equipo_ia)
        hp_max_ia = sum(p.hp_max for p in equipo_ia)
        hp_j = sum(p.hp for p in equipo_j)
        hp_max_j = sum(p.hp_max for p in equipo_j)
        hp_ratio = (hp_ia / max(1, hp_max_ia)) - (hp_j / max(1, hp_max_j))

        # Factor 1: Pokémon vivos
        vivos_ia = sum(1 for p in equipo_ia if p.esta_vivo())
        vivos_j = sum(1 for p in equipo_j if p.esta_vivo())
        total = len(equipo_ia)
        vivos_ratio = (vivos_ia - vivos_j) / max(1, total)

        # Factor 2: ventaja de tipo del activo (mejor mov ofensivo IA → rival)
        mejor_ventaja = 0.0
        for mov in activo_ia.movimientos:
            if mov.poder > 0 and mov.tiene_pp():
                ef = calcular_efectividad(mov.tipo, activo_j.tipos)
                mejor_ventaja = max(mejor_ventaja, ef)
        type_advantage = (mejor_ventaja - 1.0) / 3.0  # [0,4] → [-1/3, 1]

        # Factor 3: velocidad relativa
        vel_ia = activo_ia.get_velocidad_efectiva()
        vel_j = activo_j.get_velocidad_efectiva()
        speed_ratio = (vel_ia - vel_j) / max(vel_ia, vel_j, 1)

        # Factor 4: estados principales (rival con estado malo → bueno para IA)
        estado_ratio = gravedad_estado(activo_j) - gravedad_estado(activo_ia)

        # Factor 5: DoT residual (drenadoras, maldición, confusión)
        dot_ratio = dot_residual(activo_j) - dot_residual(activo_ia)

        # Factor 6: PP disponible del activo (yo con PP > rival sin PP es ventaja)
        pp_ratio = pp_disponible(activo_ia) - pp_disponible(activo_j)

        w = self.pesos
        score = (w[0] * hp_ratio +
                 w[1] * vivos_ratio +
                 w[2] * type_advantage +
                 w[3] * speed_ratio +
                 w[4] * estado_ratio +
                 w[5] * dot_ratio +
                 w[6] * pp_ratio)
        return score

    def _acciones_posibles(self, engine, lado):
        activo = engine.pokemon_activo(lado)
        equipo = engine.equipos[lado]
        activo_idx = engine.activos[lado]
        acciones = []

        for i, mov in enumerate(activo.movimientos):
            if mov.tiene_pp():
                acciones.append({'tipo': 'movimiento', 'indice': i})

        for i, p in enumerate(equipo):
            if p.esta_vivo() and i != activo_idx:
                acciones.append({'tipo': 'cambio', 'indice': i})

        if not acciones:
            acciones.append({'tipo': 'movimiento', 'indice': 0})
        return acciones

    def minimax(self, engine, profundidad, alpha, beta):
        """
        Minimax para juego de acciones simultáneas (como Pokémon).
        IA maximiza; jugador minimiza.
        Para cada acción de IA, se evalúa el peor caso sobre todas las
        acciones posibles del jugador (maximin).
        """
        if engine.batalla_terminada() or profundidad == 0:
            return self.evaluar(engine)

        acciones_ia = self._acciones_posibles(engine, 'ia')
        acciones_j  = self._acciones_posibles(engine, 'jugador')

        max_eval = float('-inf')
        for accion_ia in acciones_ia:
            # Peor caso para esta acción de IA: jugador elige la respuesta óptima
            min_eval = float('inf')
            beta_local = beta
            for accion_j in acciones_j:
                # En niveles profundos usamos menos rollouts que en la raíz, pero >1
                # para no basar la respuesta del rival simulado en una sola tirada de dados.
                val = self._rollout_promedio(engine, accion_j, accion_ia,
                                             profundidad - 1, alpha, beta_local,
                                             n_samples=self.n_samples_deep)
                if val < min_eval:
                    min_eval = val
                if val < beta_local:
                    beta_local = val
                if beta_local <= alpha:
                    break  # poda alpha
            if min_eval > max_eval:
                max_eval = min_eval
            if max_eval > alpha:
                alpha = max_eval
            if alpha >= beta:
                break  # poda beta
        return max_eval

    def elegir_accion(self, estado):
        engine = estado.get('_engine')
        if engine is None:
            return HeuristicAgent().elegir_accion(estado)

        acciones_ia = self._acciones_posibles(engine, 'ia')
        acciones_j  = self._acciones_posibles(engine, 'jugador')

        mejor_score  = float('-inf')
        mejor_accion = None
        alpha = float('-inf')

        for accion_ia in acciones_ia:
            # Peor caso: jugador responde óptimamente a esta acción
            min_eval = float('inf')
            beta_local = float('inf')
            for accion_j in acciones_j:
                # Sampling solo aquí (raíz): suaviza la decisión final
                score = self._rollout_promedio(engine, accion_j, accion_ia,
                                               self.profundidad - 1, alpha, beta_local,
                                               n_samples=self.n_samples)
                if score < min_eval:
                    min_eval = score
                if score < beta_local:
                    beta_local = score
                if beta_local <= alpha:
                    break
            if min_eval > mejor_score:
                mejor_score  = min_eval
                mejor_accion = accion_ia
            if min_eval > alpha:
                alpha = min_eval

        return mejor_accion if mejor_accion is not None else HeuristicAgent().elegir_accion(estado)
