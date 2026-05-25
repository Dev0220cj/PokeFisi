"""
Wrappers para permitir que cualquier agente (hardcoded a la perspectiva 'ia')
juegue en el lado 'jugador' viendo la información correcta de SU lado.

Problema que resuelve: todos los agentes (RandomAgent, HeuristicAgent,
MinimaxAgent) leen `estado['ia']` para decidir. Si los usas directamente en
el lado 'jugador', deciden basándose en información del oponente y aplican
acciones que no tienen sentido para su pokémon (índices de movimientos
incorrectos, etc.).

Uso típico:
    agente_j = AgenteVolteado(HeuristicAgent())  # juega como 'jugador'
    accion_j = agente_j.elegir_accion(estado)    # estado tal cual del engine
"""


class _EngineVolteado:
    """Envuelve un BattleEngine intercambiando los roles 'jugador' ↔ 'ia'.
    Usado por MinimaxAgent (que recibe `_engine` en el estado) cuando juega
    desde el bando del jugador."""

    def __init__(self, engine_real):
        self._e = engine_real

    def pokemon_activo(self, lado):
        return self._e.pokemon_activo('ia' if lado == 'jugador' else 'jugador')

    @property
    def equipos(self):
        return {'jugador': self._e.equipos['ia'],
                'ia':      self._e.equipos['jugador']}

    @property
    def activos(self):
        return {'jugador': self._e.activos['ia'],
                'ia':      self._e.activos['jugador']}

    def batalla_terminada(self):
        return self._e.batalla_terminada()

    def clonar(self):
        return _EngineVolteado(self._e.clonar())

    # Los args de ejecutar_turno también se invierten
    def ejecutar_turno(self, accion_jugador, accion_ia):
        return self._e.ejecutar_turno(accion_ia, accion_jugador)


class AgenteVolteado:
    """Permite que cualquier agente (diseñado para 'ia') tome decisiones
    desde la perspectiva del lado 'jugador'. Le voltea el estado antes
    de llamarlo."""

    def __init__(self, agente):
        self._agente = agente

    def elegir_accion(self, estado):
        estado_volteado = {
            'ia':      estado['jugador'],
            'jugador': estado['ia'],
        }
        # Para Minimax: proporcionar un engine con perspectiva volteada
        if '_engine' in estado and estado['_engine'] is not None:
            estado_volteado['_engine'] = _EngineVolteado(estado['_engine'])
        else:
            estado_volteado['_engine'] = None
        return self._agente.elegir_accion(estado_volteado)
