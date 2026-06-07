import sys
import os
import random
import pygame

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SCREEN_WIDTH, SCREEN_HEIGHT, FPS, TITLE, COLOR_BG
from src.pokemon import cargar_pokemon, lista_nombres_pokemon, aplicar_modo_movimientos
from src.battle_engine import BattleEngine
from src.ai_agent import (
    RandomAgent, HeuristicAgent, MinimaxAgent,
    PESOS_EVAL_DEFAULT, cargar_pesos_entrenados,
)
from ui.battle_screen import BattleScreen
from ui.menu_screen import TeamSelectScreen
from ui.intro_screen import IntroScreen
from ui.config_screen import ConfigScreen
from ui.move_select_screen import MoveSelectScreen

import json
DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'pokemon_data.json')


def cargar_fuentes():
    pygame.font.init()
    fuentes = {}
    try:
        fuentes['title'] = pygame.font.SysFont('arial', 36, bold=True)
        fuentes['normal'] = pygame.font.SysFont('arial', 18, bold=True)
        fuentes['small'] = pygame.font.SysFont('arial', 14)
        fuentes['tiny'] = pygame.font.SysFont('arial', 11)
    except Exception:
        fuentes['title'] = pygame.font.Font(None, 42)
        fuentes['normal'] = pygame.font.Font(None, 24)
        fuentes['small'] = pygame.font.Font(None, 18)
        fuentes['tiny'] = pygame.font.Font(None, 14)
    return fuentes


def crear_agente(nivel):
    if nivel == 1:
        return RandomAgent()
    elif nivel == 2:
        return HeuristicAgent()
    elif nivel == 3:
        # Difícil siempre usa la mejor versión disponible del Minimax:
        # pesos entrenados por GA si existen, ajuste manual como fallback.
        # Nunca usa los uniformes (que pierden vs Heurístico — sería UX engañoso).
        pesos = cargar_pesos_entrenados() or PESOS_EVAL_DEFAULT
        return MinimaxAgent(pesos=pesos)
    return HeuristicAgent()


def _equipo_aleatorio(tam: int, excluir: list = None) -> list:
    excluir = excluir or []
    todos = lista_nombres_pokemon()
    disponibles = [n for n in todos if n not in excluir]
    random.shuffle(disponibles)
    return disponibles[:tam]


def _tam_from_config(cfg: dict) -> int:
    return 3 if cfg.get('tam_equipo', '4 vs 4').startswith('3') else 4


def _nivel_ia_from_config(cfg: dict) -> int:
    val = cfg.get('nivel_ia', 'Nivel 2  Heurístico')
    if 'Nivel 1' in val:
        return 1
    if 'Nivel 3' in val:
        return 3
    return 2


def _modo_movs(cfg: dict, key: str) -> str:
    """Devuelve 'predefinidos' | 'aleatorios' | 'manual' según el config."""
    val = cfg.get(key, 'Predefinidos').lower()
    if 'aleator' in val:
        return 'aleatorios'
    if 'manual' in val:
        return 'manual'
    return 'predefinidos'


def _aplicar_modo_a_equipo(equipo, modo, indices_por_pkm=None):
    """Aplica un modo de movimientos a todos los Pokémon del equipo.
    Para 'manual' espera una lista de listas de índices (uno por Pokémon)."""
    for i, pkm in enumerate(equipo):
        ind = indices_por_pkm[i] if (indices_por_pkm and modo == 'manual') else None
        aplicar_modo_movimientos(pkm, modo, indices=ind)


def _arrancar_batalla(equipo_j, equipo_ia, nivel_ia, screen, fonts):
    """Construye engine + agente + battle_screen. Se llama cuando los equipos
    ya tienen sus movimientos definitivos (4 cada Pokémon)."""
    engine        = BattleEngine(equipo_j, equipo_ia)
    agente_ia     = crear_agente(nivel_ia)
    battle_screen = BattleScreen(screen, fonts)
    return engine, agente_ia, battle_screen


def _msgs_inicio_batalla():
    """Devuelve los mensajes/colas iniciales de una batalla recién comenzada."""
    return ['¡Comienza la batalla!'], ['¡Comienza la batalla!']


def _iniciar_post_seleccion(nombres_j, nombres_ia, nivel_ia, cfg, screen, fonts):
    """Tras seleccionar equipos, construye Pokémon y aplica los modos
    Predefinidos/Aleatorios. Si algún lado es Manual, devuelve una MoveSelectScreen
    pendiente; si no, devuelve la batalla lista para arrancar.

    Devuelve un dict con la clave 'estado' = 'MOVE_SELECT' | 'BATTLE' y los
    objetos correspondientes."""
    equipo_j  = [cargar_pokemon(n) for n in nombres_j]
    equipo_ia = [cargar_pokemon(n) for n in nombres_ia]

    modo_j = _modo_movs(cfg, 'movs_jugador')
    modo_i = _modo_movs(cfg, 'movs_rival')
    if modo_j != 'manual':
        _aplicar_modo_a_equipo(equipo_j, modo_j)
    if modo_i != 'manual':
        _aplicar_modo_a_equipo(equipo_ia, modo_i)

    base = {'equipo_j': equipo_j, 'equipo_ia': equipo_ia}

    # Jugador con Manual tiene prioridad (se hace primero)
    if modo_j == 'manual':
        ms = MoveSelectScreen(screen, fonts, equipo_j, titulo='TUS MOVIMIENTOS')
        return {**base, 'estado': 'MOVE_SELECT', 'move_select': ms, 'lado': 'jugador'}
    if modo_i == 'manual':
        ms = MoveSelectScreen(screen, fonts, equipo_ia, titulo='MOVIMIENTOS DEL RIVAL')
        return {**base, 'estado': 'MOVE_SELECT', 'move_select': ms, 'lado': 'rival'}

    # Sin Manual: arrancar batalla directamente
    engine, agente_ia, battle_screen = _arrancar_batalla(
        equipo_j, equipo_ia, nivel_ia, screen, fonts)
    return {**base, 'estado': 'BATTLE',
            'engine': engine, 'agente_ia': agente_ia, 'battle_screen': battle_screen}


def main():
    pygame.init()
    pygame.display.set_caption(TITLE)
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    clock  = pygame.time.Clock()
    fonts  = cargar_fuentes()

    # Cargar datos JSON para TeamSelect
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        datos_json = json.load(f)
    datos_pokemon = datos_json['pokemon']

    # Estado de la aplicación
    estado_app = 'INTRO'  # INTRO | CONFIG | TEAM_SELECT | TEAM_SELECT_IA | BATTLE

    intro        = IntroScreen(screen, fonts)
    config_screen: ConfigScreen | None = None
    team_select:    TeamSelectScreen | None = None
    team_select_ia: TeamSelectScreen | None = None
    battle_screen:  BattleScreen | None = None
    move_select:    MoveSelectScreen | None = None
    move_select_lado: str = ''                # 'jugador' o 'rival'
    equipo_j_pre:    list = []                # equipos pre-construidos (durante MOVE_SELECT)
    equipo_ia_pre:   list = []
    engine     = None
    agente_ia  = None
    nivel_ia   = 2
    tam        = 4
    config: dict = {}
    nombres_jugador_pendiente: list = []

    # Estado de la batalla
    modo_batalla = 'luchar'
    seleccion_mov = 0
    modo_cambio_idx = 0
    mensajes_batalla = []
    ganador = None
    _ganador_pendiente = None   # se setea al terminar el turno; se aplica al vaciar mensajes
    esperando_turno = False
    delay_turno = 0

    # Estado visual (qué sprite se muestra; se actualiza con centinelas __SWITCH_*)
    _visual = {'activo_ia': 0, 'activo_j': 0}

    # Cola de diálogo (mensajes uno a uno)
    cola_mensajes   = []
    mensaje_dialogo = None
    t_mensaje_dial  = 0
    DIALOGO_DURACION_MS = 2500

    while True:
        dt = clock.tick(FPS)
        _cortar_eventos = False   # se activa tras confirmar acción para no procesar más eventos ese frame

        # === Eventos ===
        for event in pygame.event.get():
            if _cortar_eventos:   # un commit ya ocurrió → ignorar eventos restantes
                break
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            # INTRO
            if estado_app == 'INTRO':
                resultado = intro.manejar_evento(event)
                if resultado == 'siguiente':
                    config_screen = ConfigScreen(screen, fonts)
                    estado_app = 'CONFIG'

            # CONFIG
            elif estado_app == 'CONFIG':
                resultado = config_screen.manejar_evento(event)
                if resultado == 'confirmar':
                    config   = config_screen.get_config()
                    tam      = _tam_from_config(config)
                    nivel_ia = _nivel_ia_from_config(config)
                    eq_j = config['equipo_jugador']
                    eq_r = config['equipo_rival']

                    if eq_j == 'Elegir manual':
                        team_select = TeamSelectScreen(screen, fonts, tam=tam)
                        estado_app  = 'TEAM_SELECT'
                    elif eq_r == 'Elegir manual':
                        nombres_jugador_pendiente = _equipo_aleatorio(tam)
                        team_select_ia = TeamSelectScreen(
                            screen, fonts, tam=tam, titulo='EQUIPO DEL RIVAL')
                        estado_app = 'TEAM_SELECT_IA'
                    else:
                        # Ambos aleatorios → ir directo a batalla (o MoveSelect si Manual)
                        nombres_j  = _equipo_aleatorio(tam)
                        nombres_ia = _equipo_aleatorio(tam, excluir=nombres_j)
                        _post = _iniciar_post_seleccion(
                            nombres_j, nombres_ia, nivel_ia, config, screen, fonts)
                        equipo_j_pre  = _post['equipo_j']
                        equipo_ia_pre = _post['equipo_ia']
                        if _post['estado'] == 'MOVE_SELECT':
                            move_select      = _post['move_select']
                            move_select_lado = _post['lado']
                            estado_app       = 'MOVE_SELECT'
                        else:
                            engine        = _post['engine']
                            agente_ia     = _post['agente_ia']
                            battle_screen = _post['battle_screen']
                            _visual['activo_ia'] = 0
                            _visual['activo_j']  = 0
                            mensajes_batalla, cola_mensajes = _msgs_inicio_batalla()
                            mensaje_dialogo  = cola_mensajes.pop(0)
                            t_mensaje_dial   = pygame.time.get_ticks()
                            modo_batalla     = 'luchar'
                            seleccion_mov    = 0
                            ganador            = None
                            _ganador_pendiente = None
                            esperando_turno  = False
                            delay_turno      = 0
                            estado_app       = 'BATTLE'
                elif resultado == 'volver':
                    estado_app = 'INTRO'

            # TEAM_SELECT (equipo del jugador)
            elif estado_app == 'TEAM_SELECT':
                resultado = team_select.manejar_evento(event)
                if resultado == 'confirmar':
                    nombres_j = team_select.equipo_seleccionado()
                    eq_r = config.get('equipo_rival', 'Aleatorio')

                    if eq_r == 'Elegir manual':
                        nombres_jugador_pendiente = nombres_j
                        team_select_ia = TeamSelectScreen(
                            screen, fonts, tam=tam, titulo='EQUIPO DEL RIVAL')
                        estado_app = 'TEAM_SELECT_IA'
                    else:
                        nombres_ia = _equipo_aleatorio(tam, excluir=nombres_j)
                        _post = _iniciar_post_seleccion(
                            nombres_j, nombres_ia, nivel_ia, config, screen, fonts)
                        equipo_j_pre  = _post['equipo_j']
                        equipo_ia_pre = _post['equipo_ia']
                        if _post['estado'] == 'MOVE_SELECT':
                            move_select      = _post['move_select']
                            move_select_lado = _post['lado']
                            estado_app       = 'MOVE_SELECT'
                        else:
                            engine        = _post['engine']
                            agente_ia     = _post['agente_ia']
                            battle_screen = _post['battle_screen']
                            _visual['activo_ia'] = 0
                            _visual['activo_j']  = 0
                            mensajes_batalla, cola_mensajes = _msgs_inicio_batalla()
                            mensaje_dialogo  = cola_mensajes.pop(0)
                            t_mensaje_dial   = pygame.time.get_ticks()
                            modo_batalla     = 'luchar'
                            seleccion_mov    = 0
                            ganador            = None
                            _ganador_pendiente = None
                            esperando_turno  = False
                            delay_turno      = 0
                            estado_app       = 'BATTLE'
                elif resultado == 'volver':
                    estado_app = 'CONFIG'

            # TEAM_SELECT_IA (equipo del rival)
            elif estado_app == 'TEAM_SELECT_IA':
                resultado = team_select_ia.manejar_evento(event)
                if resultado == 'confirmar':
                    nombres_j  = nombres_jugador_pendiente
                    nombres_ia = team_select_ia.equipo_seleccionado()
                    _post = _iniciar_post_seleccion(
                        nombres_j, nombres_ia, nivel_ia, config, screen, fonts)
                    equipo_j_pre  = _post['equipo_j']
                    equipo_ia_pre = _post['equipo_ia']
                    if _post['estado'] == 'MOVE_SELECT':
                        move_select      = _post['move_select']
                        move_select_lado = _post['lado']
                        estado_app       = 'MOVE_SELECT'
                    else:
                        engine        = _post['engine']
                        agente_ia     = _post['agente_ia']
                        battle_screen = _post['battle_screen']
                        _visual['activo_ia'] = 0
                        _visual['activo_j']  = 0
                        mensajes_batalla, cola_mensajes = _msgs_inicio_batalla()
                        mensaje_dialogo  = cola_mensajes.pop(0)
                        t_mensaje_dial   = pygame.time.get_ticks()
                        modo_batalla     = 'luchar'
                        seleccion_mov    = 0
                        ganador          = None
                        _ganador_pendiente = None
                        esperando_turno  = False
                        delay_turno      = 0
                        estado_app       = 'BATTLE'
                elif resultado == 'volver':
                    # Si el jugador eligió manualmente, volver a su selección
                    if config.get('equipo_jugador') == 'Elegir manual':
                        estado_app = 'TEAM_SELECT'
                    else:
                        estado_app = 'CONFIG'

            # MOVE_SELECT (selección manual de movimientos del lado actual)
            elif estado_app == 'MOVE_SELECT':
                resultado = move_select.manejar_evento(event)
                if resultado == 'completo':
                    # Aplicar los índices seleccionados al equipo correspondiente
                    indices_list = move_select.get_resultado()
                    equipo_actual = equipo_j_pre if move_select_lado == 'jugador' else equipo_ia_pre
                    for i, pkm in enumerate(equipo_actual):
                        aplicar_modo_movimientos(pkm, 'manual', indices=indices_list[i])

                    # ¿Falta el otro lado?
                    modo_otro = _modo_movs(config, 'movs_rival' if move_select_lado == 'jugador' else 'movs_jugador')
                    if move_select_lado == 'jugador' and modo_otro == 'manual':
                        # Pasar a seleccionar movs del rival
                        move_select = MoveSelectScreen(
                            screen, fonts, equipo_ia_pre, titulo='MOVIMIENTOS DEL RIVAL')
                        move_select_lado = 'rival'
                    else:
                        # Todos los lados manuales ya están seleccionados → arrancar batalla
                        engine, agente_ia, battle_screen = _arrancar_batalla(
                            equipo_j_pre, equipo_ia_pre, nivel_ia, screen, fonts)
                        _visual['activo_ia'] = 0
                        _visual['activo_j']  = 0
                        mensajes_batalla, cola_mensajes = _msgs_inicio_batalla()
                        mensaje_dialogo  = cola_mensajes.pop(0)
                        t_mensaje_dial   = pygame.time.get_ticks()
                        modo_batalla     = 'luchar'
                        seleccion_mov    = 0
                        ganador            = None
                        _ganador_pendiente = None
                        esperando_turno  = False
                        delay_turno      = 0
                        estado_app       = 'BATTLE'
                elif resultado == 'volver':
                    # Simplificación: volver a CONFIG (más predecible que reconstruir el estado anterior)
                    estado_app = 'CONFIG'

            # BATTLE
            elif estado_app == 'BATTLE':
                if ganador:
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                        config_screen = ConfigScreen(screen, fonts)
                        _ganador_pendiente = None
                        estado_app = 'CONFIG'
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        config_screen = ConfigScreen(screen, fonts)
                        _ganador_pendiente = None
                        estado_app = 'CONFIG'
                    continue

                if esperando_turno:
                    continue

                # Diálogo activo: tecla o clic avanza al siguiente mensaje
                if mensaje_dialogo is not None:
                    avanzar = (
                        (event.type == pygame.KEYDOWN) or
                        (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1)
                    )
                    if avanzar:
                        sig = _pop_mensaje(cola_mensajes, battle_screen, _visual)
                        if sig is not None:
                            mensaje_dialogo = sig
                            t_mensaje_dial  = pygame.time.get_ticks()
                        else:
                            mensaje_dialogo = None
                            # Mostrar victoria ahora que se leyeron todos los mensajes
                            if _ganador_pendiente:
                                ganador = _ganador_pendiente
                    continue

                # ── Teclado ──────────────────────────────────────────────
                if event.type == pygame.KEYDOWN:
                    if modo_batalla == 'luchar':
                        if event.key in (pygame.K_LEFT, pygame.K_a):
                            seleccion_mov = (seleccion_mov - 1) % 4
                        elif event.key in (pygame.K_RIGHT, pygame.K_d):
                            seleccion_mov = (seleccion_mov + 1) % 4
                        elif event.key in (pygame.K_UP, pygame.K_w):
                            seleccion_mov = (seleccion_mov - 2) % 4
                        elif event.key in (pygame.K_DOWN, pygame.K_s):
                            seleccion_mov = (seleccion_mov + 2) % 4
                        elif event.key in (pygame.K_RETURN, pygame.K_z):
                            seleccion_mov, _ganador_pendiente = _confirmar_movimiento(
                                engine, agente_ia, seleccion_mov,
                                mensajes_batalla, cola_mensajes, battle_screen)
                            sig = _pop_mensaje(cola_mensajes, battle_screen, _visual)
                            if sig is not None:
                                mensaje_dialogo = sig
                                t_mensaje_dial  = pygame.time.get_ticks()
                            _cortar_eventos = True
                        elif event.key in (pygame.K_c, pygame.K_TAB):
                            modo_batalla    = 'cambiar'
                            modo_cambio_idx = engine.activos['jugador']

                    elif modo_batalla == 'cambiar':
                        equipo_j = engine.equipos['jugador']
                        if event.key in (pygame.K_LEFT, pygame.K_a):
                            modo_cambio_idx = (modo_cambio_idx - 1) % len(equipo_j)
                        elif event.key in (pygame.K_RIGHT, pygame.K_d):
                            modo_cambio_idx = (modo_cambio_idx + 1) % len(equipo_j)
                        elif event.key in (pygame.K_RETURN, pygame.K_z):
                            if (modo_cambio_idx != engine.activos['jugador'] and
                                    equipo_j[modo_cambio_idx].esta_vivo()):
                                accion_j = {'tipo': 'cambio', 'indice': modo_cambio_idx}
                                _encolar_turno(engine, agente_ia, accion_j,
                                               mensajes_batalla, cola_mensajes, battle_screen)
                                sig = _pop_mensaje(cola_mensajes, battle_screen, _visual)
                                if sig is not None:
                                    mensaje_dialogo = sig
                                    t_mensaje_dial  = pygame.time.get_ticks()
                                if engine.batalla_terminada():
                                    _ganador_pendiente = engine.ganador()
                                _cortar_eventos = True
                            modo_batalla = 'luchar'
                        elif event.key in (pygame.K_ESCAPE, pygame.K_c, pygame.K_TAB):
                            modo_batalla = 'luchar'

                    elif modo_batalla == 'cambio_forzado':
                        equipo_j = engine.equipos['jugador']
                        vivos = [i for i, p in enumerate(equipo_j) if p.esta_vivo()]
                        if vivos:
                            if event.key in (pygame.K_LEFT, pygame.K_a):
                                pos = vivos.index(modo_cambio_idx) if modo_cambio_idx in vivos else 0
                                modo_cambio_idx = vivos[(pos - 1) % len(vivos)]
                            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                                pos = vivos.index(modo_cambio_idx) if modo_cambio_idx in vivos else 0
                                modo_cambio_idx = vivos[(pos + 1) % len(vivos)]
                            elif event.key in (pygame.K_RETURN, pygame.K_z):
                                if equipo_j[modo_cambio_idx].esta_vivo():
                                    engine.cambiar_pokemon('jugador', modo_cambio_idx)
                                    engine.necesita_cambio_jugador = False
                                    nuevo_nombre = engine.pokemon_activo('jugador').nombre
                                    cola_mensajes.append(f"__SWITCH_J:{modo_cambio_idx}")
                                    cola_mensajes.append(f"¡Adelante, {nuevo_nombre}!")
                                    sig = _pop_mensaje(cola_mensajes, battle_screen, _visual)
                                    if sig is not None:
                                        mensaje_dialogo = sig
                                        t_mensaje_dial  = pygame.time.get_ticks()
                                    modo_batalla = 'luchar'
                                    _cortar_eventos = True
                        # No se puede cancelar: ESC/TAB ignorados en cambio_forzado

                # ── Ratón ─────────────────────────────────────────────────
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and battle_screen:
                    mx, my = event.pos
                    if modo_batalla == 'luchar':
                        # Clic en botón de movimiento → ejecutar turno
                        for i, rect in enumerate(battle_screen._mov_rects):
                            if rect.collidepoint(mx, my):
                                seleccion_mov = i
                                seleccion_mov, _ganador_pendiente = _confirmar_movimiento(
                                    engine, agente_ia, i,
                                    mensajes_batalla, cola_mensajes, battle_screen)
                                sig = _pop_mensaje(cola_mensajes, battle_screen, _visual)
                                if sig is not None:
                                    mensaje_dialogo = sig
                                    t_mensaje_dial  = pygame.time.get_ticks()
                                _cortar_eventos = True
                                break
                        # Clic en botón Cambiar
                        if battle_screen._btn_cambiar_rect.collidepoint(mx, my):
                            modo_batalla    = 'cambiar'
                            modo_cambio_idx = engine.activos['jugador']

                    elif modo_batalla == 'cambiar':
                        equipo_j = engine.equipos['jugador']
                        for i, rect in enumerate(battle_screen._cambio_rects):
                            if rect.collidepoint(mx, my):
                                if equipo_j[i].esta_vivo() and i != engine.activos['jugador']:
                                    if i == modo_cambio_idx:
                                        # segundo clic confirma el cambio
                                        accion_j = {'tipo': 'cambio', 'indice': i}
                                        _encolar_turno(engine, agente_ia, accion_j,
                                                       mensajes_batalla, cola_mensajes,
                                                       battle_screen)
                                        sig = _pop_mensaje(cola_mensajes, battle_screen, _visual)
                                        if sig is not None:
                                            mensaje_dialogo = sig
                                            t_mensaje_dial  = pygame.time.get_ticks()
                                        if engine.batalla_terminada():
                                            _ganador_pendiente = engine.ganador()
                                        modo_batalla = 'luchar'
                                        _cortar_eventos = True
                                    else:
                                        modo_cambio_idx = i   # primer clic selecciona
                                break
                        # Clic en botón Luchar
                        if battle_screen._btn_luchar_rect.collidepoint(mx, my):
                            modo_batalla = 'luchar'

                    elif modo_batalla == 'cambio_forzado':
                        equipo_j = engine.equipos['jugador']
                        for i, rect in enumerate(battle_screen._cambio_rects):
                            if rect.collidepoint(mx, my):
                                if equipo_j[i].esta_vivo():
                                    if i == modo_cambio_idx:
                                        # segundo clic (o clic en ya-seleccionado) confirma
                                        engine.cambiar_pokemon('jugador', i)
                                        engine.necesita_cambio_jugador = False
                                        nuevo_nombre = engine.pokemon_activo('jugador').nombre
                                        cola_mensajes.append(f"__SWITCH_J:{i}")
                                        cola_mensajes.append(f"¡Adelante, {nuevo_nombre}!")
                                        sig = _pop_mensaje(cola_mensajes, battle_screen, _visual)
                                        if sig is not None:
                                            mensaje_dialogo = sig
                                            t_mensaje_dial  = pygame.time.get_ticks()
                                        modo_batalla = 'luchar'
                                        _cortar_eventos = True
                                    else:
                                        modo_cambio_idx = i   # primer clic selecciona
                                break

        # Helper: ¿hay alguna animación de HP en curso? (bloquea avance del diálogo
        # y activación del banner de victoria para que se sincronice todo)
        def _hp_anim_en_curso():
            if not (engine and battle_screen):
                return False
            return (battle_screen.hp_animacion_pendiente(
                        engine.pokemon_activo('jugador'), 'jugador')
                    or battle_screen.hp_animacion_pendiente(
                        engine.pokemon_activo('ia'), 'ia'))

        # Auto-avance del diálogo por tiempo (solo si no hay HP animando)
        if (estado_app == 'BATTLE' and mensaje_dialogo is not None
                and not ganador
                and pygame.time.get_ticks() - t_mensaje_dial > DIALOGO_DURACION_MS):
            if _hp_anim_en_curso():
                # Resetear el timer: esperamos otro ciclo a que la barra termine
                t_mensaje_dial = pygame.time.get_ticks()
            else:
                sig = _pop_mensaje(cola_mensajes, battle_screen, _visual)
                if sig is not None:
                    mensaje_dialogo = sig
                    t_mensaje_dial  = pygame.time.get_ticks()
                else:
                    mensaje_dialogo = None
                    # Mostrar victoria ahora que se leyeron todos los mensajes
                    if _ganador_pendiente:
                        ganador = _ganador_pendiente

        # Activar victoria diferida solo si NO hay HP animando y no hay diálogos pendientes
        if (estado_app == 'BATTLE' and _ganador_pendiente and not ganador
                and not cola_mensajes and mensaje_dialogo is None
                and not _hp_anim_en_curso()):
            ganador = _ganador_pendiente

        # Activar cambio forzado del jugador cuando sus mensajes se hayan leído
        if (estado_app == 'BATTLE' and engine and not ganador and not _ganador_pendiente
                and engine.necesita_cambio_jugador
                and not cola_mensajes and mensaje_dialogo is None
                and modo_batalla != 'cambio_forzado'):
            modo_batalla = 'cambio_forzado'
            modo_cambio_idx = next(
                (i for i, p in enumerate(engine.equipos['jugador']) if p.esta_vivo()), 0)

        # === Render ===
        if estado_app == 'INTRO':
            resultado = intro.update()
            if resultado == 'siguiente':
                config_screen = ConfigScreen(screen, fonts)
                estado_app = 'CONFIG'
            else:
                intro.render()

        elif estado_app == 'CONFIG':
            config_screen.render()

        elif estado_app == 'TEAM_SELECT':
            team_select.render(datos_pokemon)

        elif estado_app == 'TEAM_SELECT_IA':
            team_select_ia.render(datos_pokemon)

        elif estado_app == 'MOVE_SELECT' and move_select:
            move_select.render()

        elif estado_app == 'BATTLE' and engine and battle_screen:
            # Sincronizar estado visual cuando el jugador está eligiendo (sin mensajes)
            if mensaje_dialogo is None and not cola_mensajes:
                _visual['activo_ia'] = engine.activos['ia']
                _visual['activo_j']  = engine.activos['jugador']

            estado_b = engine.get_estado()
            # Reemplazar Pokémon activo con el estado visual (sprites siguen a los diálogos)
            try:
                estado_b['ia']['activo']          = engine.equipos['ia'][_visual['activo_ia']]
                estado_b['ia']['activo_idx']      = _visual['activo_ia']
                estado_b['jugador']['activo']     = engine.equipos['jugador'][_visual['activo_j']]
                estado_b['jugador']['activo_idx'] = _visual['activo_j']
            except IndexError:
                pass  # índice inválido: usar estado real sin override

            battle_screen.render(
                estado_b,
                nivel_ia,
                modo_batalla,
                seleccion_mov,
                modo_cambio_idx=modo_cambio_idx if modo_batalla in ('cambiar', 'cambio_forzado') else None,
                mensajes=mensajes_batalla[-20:],
                ganador=ganador,
                mensaje_dialogo=mensaje_dialogo,
            )

        pygame.display.flip()


def _pop_mensaje(cola, battle_screen=None, visual_state=None):
    """Saca el siguiente mensaje visible, procesando centinelas en silencio.

    Centinelas reconocidos (nunca se muestran como diálogo):
      __HP_UPDATE_J__    → libera animación HP jugador
      __HP_UPDATE_IA__   → libera animación HP rival
      __SWITCH_J:<idx>   → actualiza sprite activo del jugador
      __SWITCH_IA:<idx>  → actualiza sprite activo del rival
    """
    while cola:
        msg = cola.pop(0)
        if msg == '__HP_UPDATE_J__':
            if battle_screen:
                battle_screen.unfreeze_hp_j()
        elif msg == '__HP_UPDATE_IA__':
            if battle_screen:
                battle_screen.unfreeze_hp_ia()
        elif msg.startswith('__SWITCH_J:'):
            if visual_state is not None:
                visual_state['activo_j'] = int(msg.split(':')[1])
        elif msg.startswith('__SWITCH_IA:'):
            if visual_state is not None:
                visual_state['activo_ia'] = int(msg.split(':')[1])
        else:
            return msg
    return None


def _confirmar_movimiento(engine, agente_ia, idx_solicitado, mensajes, cola,
                          battle_screen=None):
    """
    Ejecuta el turno usando el movimiento `idx_solicitado` (o el siguiente con PP).
    Devuelve (seleccion_mov_actualizada, ganador_pendiente_o_None).
    """
    poke_j = engine.pokemon_activo('jugador')
    mov_elegido = None
    for i in range(idx_solicitado, idx_solicitado + len(poke_j.movimientos)):
        idx = i % len(poke_j.movimientos)
        if poke_j.movimientos[idx].tiene_pp():
            mov_elegido = idx
            break
    if mov_elegido is None:
        mov_elegido = 0

    accion_j = {'tipo': 'movimiento', 'indice': mov_elegido}
    _encolar_turno(engine, agente_ia, accion_j, mensajes, cola, battle_screen)
    pendiente = engine.ganador() if engine.batalla_terminada() else None
    return mov_elegido, pendiente


def _encolar_turno(engine, agente_ia, accion_jugador, mensajes, cola,
                   battle_screen=None):
    """Ejecuta el turno, congela HP antes de correrlo y añade mensajes a la cola."""
    if battle_screen:
        battle_screen.freeze_hp(engine.equipos['jugador'], engine.equipos['ia'])
    prev = len(mensajes)
    _ejecutar_turno(engine, agente_ia, accion_jugador, mensajes)
    cola.extend(mensajes[prev:])


def _ejecutar_turno(engine, agente_ia, accion_jugador, mensajes):
    estado = engine.get_estado()
    estado['_engine'] = engine
    accion_ia = agente_ia.elegir_accion(estado)
    nuevos = engine.ejecutar_turno(accion_jugador, accion_ia)
    mensajes.extend(nuevos)
    # Limitar historial
    if len(mensajes) > 100:
        del mensajes[:50]


if __name__ == '__main__':
    main()
