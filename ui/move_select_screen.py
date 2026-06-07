"""
Pantalla de selección manual de movimientos.

Para cada Pokémon del equipo (uno a uno), permite al usuario escoger 4 de
los 8 movimientos disponibles. Sigue la paleta de la `ConfigScreen` (gold,
panel azul translúcido, fondo paisaje).

Uso:
    screen = MoveSelectScreen(surface, fonts, equipo, titulo='TU EQUIPO')
    # En el loop principal:
    res = screen.manejar_evento(event)
    if res == 'completo':  resultado = screen.get_resultado()
    elif res == 'volver':  ...
    screen.render()

`get_resultado()` devuelve list[list[int]]: una lista de índices (4 por
Pokémon) en el mismo orden que el equipo.
"""
import pygame

from config import SCREEN_WIDTH, SCREEN_HEIGHT
from ui.sprites import cargar_sprite, TIPO_COLORES


# ── Paleta (coherente con config_screen) ─────────────────────────────────────
_GOLD  = (255, 215,   0)
_WHITE = (255, 255, 255)
_MUTED = (148, 155, 172)
_GREEN = (60, 200, 82)
_GREY  = (90, 95, 110)
_RED   = (220, 80, 80)


# ── Cuántos movimientos selecciona el jugador ────────────────────────────────
N_SELECCIONAR = 4


class MoveSelectScreen:
    # Geometría
    PANEL_X = 30
    PANEL_Y = 60
    PANEL_W = SCREEN_WIDTH - 60
    PANEL_H = SCREEN_HEIGHT - 90

    # Layout de columnas
    LEFT_X  = PANEL_X + 20
    LEFT_W  = 240
    RIGHT_X = PANEL_X + 280
    RIGHT_W = PANEL_W - 300

    # Filas de movimientos (compacto para que 8 filas + footer entren limpiamente)
    ROW_H   = 44
    ROW_GAP = 4
    ROWS_Y0 = 110

    def __init__(self, surface, fonts, equipo, titulo='ELIGE MOVIMIENTOS'):
        """
        equipo: lista de Pokémon (cada uno con .movimientos de 8 items)
        titulo: cabecera (ej. 'TU EQUIPO' / 'EQUIPO DEL RIVAL')
        """
        self.surface = surface
        self.fonts   = fonts
        self.equipo  = equipo
        self.titulo  = titulo

        # Estado interno
        self._idx_pkm = 0                                  # Pokémon actual (0..len(equipo)-1)
        self._seleccion = [set() for _ in equipo]          # set de índices por Pokémon
        self._cursor_mov = 0                               # cursor en la lista de movs
        self._resultado = None                             # se setea al confirmar

        # Cache de sprites (por nombre)
        self._sprite_cache = {}

        # Fuentes
        self._font_titulo = self._make_font(22, bold=True)
        self._font_label  = self._make_font(16, bold=True)
        self._font_mov    = self._make_font(15, bold=True)
        self._font_info   = self._make_font(13)
        self._font_btn    = self._make_font(16, bold=True)
        self._font_tipo   = self._make_font(11, bold=True)

        # Rects para colisiones (se actualizan en render)
        self._rects_movs   = []   # list de Rect por movimiento
        self._rect_btn_sig = pygame.Rect(0, 0, 0, 0)
        self._rect_btn_vol = pygame.Rect(0, 0, 0, 0)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_font(size, bold=False):
        for nombre in ('couriernew', 'lucidaconsole', 'consolas'):
            try:
                return pygame.font.SysFont(nombre, size, bold=bold)
            except Exception:
                pass
        return pygame.font.Font(None, size + 6)

    def _pokemon_actual(self):
        return self.equipo[self._idx_pkm]

    def _seleccion_actual(self) -> set:
        return self._seleccion[self._idx_pkm]

    def _toggle_mov(self, i: int):
        sel = self._seleccion_actual()
        if i in sel:
            sel.discard(i)
        elif len(sel) < N_SELECCIONAR:
            sel.add(i)
        # si ya hay 4 y el item no está, no se añade (silencioso)

    def _puede_avanzar(self) -> bool:
        return len(self._seleccion_actual()) == N_SELECCIONAR

    def _es_ultimo(self) -> bool:
        return self._idx_pkm == len(self.equipo) - 1

    def _avanzar(self):
        """Avanza al siguiente Pokémon o marca como completado."""
        if not self._puede_avanzar():
            return
        if self._es_ultimo():
            self._resultado = [sorted(s) for s in self._seleccion]
        else:
            self._idx_pkm += 1
            self._cursor_mov = 0

    def _retroceder(self):
        """Vuelve al Pokémon anterior (sin perder selecciones)."""
        if self._idx_pkm > 0:
            self._idx_pkm -= 1
            self._cursor_mov = 0

    # ── API pública ──────────────────────────────────────────────────────────

    def get_resultado(self) -> 'list[list[int]] | None':
        """Devuelve la selección final (lista de listas de índices) o None
        si aún no se ha confirmado."""
        return self._resultado

    def manejar_evento(self, event) -> 'str | None':
        """Devuelve:
        - 'completo' cuando todos los Pokémon tienen 4 selecciones y se confirma
        - 'volver'   cuando el usuario quiere salir (Esc en el primer Pokémon)
        - None       en cualquier otro caso
        """
        pkm = self._pokemon_actual()
        n_movs = len(pkm.movimientos)

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self._cursor_mov = (self._cursor_mov - 1) % n_movs
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._cursor_mov = (self._cursor_mov + 1) % n_movs
            elif event.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_z):
                self._toggle_mov(self._cursor_mov)
            elif event.key == pygame.K_TAB:
                # Avanzar si se puede; si no, ignorar
                if self._puede_avanzar():
                    self._avanzar()
                    if self._resultado is not None:
                        return 'completo'
            elif event.key == pygame.K_BACKSPACE:
                self._retroceder()
            elif event.key == pygame.K_ESCAPE:
                # Si es el primer Pokémon, volver; si no, retroceder
                if self._idx_pkm == 0:
                    return 'volver'
                self._retroceder()
            # Teclas numéricas 1-8 toggle directo
            elif pygame.K_1 <= event.key <= pygame.K_9:
                i = event.key - pygame.K_1
                if i < n_movs:
                    self._cursor_mov = i
                    self._toggle_mov(i)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            # IMPORTANTE: los botones tienen prioridad sobre las filas (la fila 8
            # puede solaparse visualmente con el footer en pantallas pequeñas).
            if self._rect_btn_sig.collidepoint(mx, my):
                if self._puede_avanzar():
                    self._avanzar()
                    if self._resultado is not None:
                        return 'completo'
                return None
            if self._rect_btn_vol.collidepoint(mx, my):
                if self._idx_pkm == 0:
                    return 'volver'
                self._retroceder()
                return None
            # Click en algún movimiento (solo si no fue sobre un botón)
            for i, rect in enumerate(self._rects_movs):
                if rect.collidepoint(mx, my):
                    self._cursor_mov = i
                    self._toggle_mov(i)
                    return None

        return None

    # ── Renderizado ──────────────────────────────────────────────────────────

    def render(self):
        # Fondo paisaje (reusamos el de config_screen para consistencia)
        from ui.config_screen import dibujar_paisaje
        dibujar_paisaje(self.surface)

        # Panel principal
        panel = pygame.Surface((self.PANEL_W, self.PANEL_H), pygame.SRCALPHA)
        panel.fill((10, 18, 46, 200))
        self.surface.blit(panel, (self.PANEL_X, self.PANEL_Y))
        pygame.draw.rect(self.surface, _GOLD,
                         (self.PANEL_X, self.PANEL_Y, self.PANEL_W, self.PANEL_H),
                         2, border_radius=10)

        # Título superior
        pkm = self._pokemon_actual()
        prog = f"{self._idx_pkm + 1}/{len(self.equipo)}"
        tit = f"{self.titulo} — {pkm.nombre} ({prog})"
        s_tit_somb = self._font_titulo.render(tit, True, (50, 35, 0))
        s_tit = self._font_titulo.render(tit, True, _GOLD)
        tx = self.PANEL_X + self.PANEL_W // 2 - s_tit.get_width() // 2
        self.surface.blit(s_tit_somb, (tx + 2, self.PANEL_Y + 12))
        self.surface.blit(s_tit,      (tx,     self.PANEL_Y + 10))

        # Separador bajo el título
        sep_y = self.PANEL_Y + 48
        pygame.draw.line(self.surface, _GOLD,
                         (self.PANEL_X + 20, sep_y),
                         (self.PANEL_X + self.PANEL_W - 20, sep_y), 1)

        # ── Columna izquierda: sprite + datos del Pokémon ──
        self._render_panel_pokemon(pkm)

        # ── Columna derecha: lista de movimientos ──
        self._render_lista_movimientos(pkm)

        # ── Footer: contador + botones ──
        self._render_footer()

    def _render_panel_pokemon(self, pkm):
        # Sprite (centrado en columna izquierda)
        sprite_size = (180, 180)
        if pkm.nombre not in self._sprite_cache:
            tipo_principal = pkm.tipos[0] if pkm.tipos else 'Normal'
            self._sprite_cache[pkm.nombre] = cargar_sprite(
                pkm.nombre, es_espalda=False, tipo=tipo_principal, tamaño=sprite_size)
        sprite = self._sprite_cache[pkm.nombre]
        frame = sprite.get_frame(pygame.time.get_ticks()) if sprite else None
        if frame is not None:
            sx = self.LEFT_X + (self.LEFT_W - sprite_size[0]) // 2
            sy = self.PANEL_Y + 75
            self.surface.blit(frame, (sx, sy))

        # Nombre debajo del sprite
        y_info = self.PANEL_Y + 75 + sprite_size[1] + 14
        s_nombre = self._font_label.render(pkm.nombre, True, _WHITE)
        nx = self.LEFT_X + (self.LEFT_W - s_nombre.get_width()) // 2
        self.surface.blit(s_nombre, (nx, y_info))

        # Tipos como badges
        y_tipos = y_info + s_nombre.get_height() + 8
        tipos_str = ' · '.join(pkm.tipos) if pkm.tipos else 'Normal'
        # Color del primer tipo
        col_primer = TIPO_COLORES.get(pkm.tipos[0] if pkm.tipos else 'Normal', _MUTED)
        s_tipos = self._font_info.render(tipos_str, True, col_primer)
        tx2 = self.LEFT_X + (self.LEFT_W - s_tipos.get_width()) // 2
        self.surface.blit(s_tipos, (tx2, y_tipos))

        # Stats compactos
        y_stats = y_tipos + s_tipos.get_height() + 14
        stats_lines = [
            f"HP {pkm.hp_max}    Vel {pkm.velocidad}",
            f"Atk {pkm.ataque}    Def {pkm.defensa}",
            f"SpA {pkm.sp_atk}    SpD {pkm.sp_def}",
        ]
        for i, line in enumerate(stats_lines):
            s = self._font_info.render(line, True, _MUTED)
            sx = self.LEFT_X + (self.LEFT_W - s.get_width()) // 2
            self.surface.blit(s, (sx, y_stats + i * 18))

    def _render_lista_movimientos(self, pkm):
        self._rects_movs = []
        sel = self._seleccion_actual()

        for i, mov in enumerate(pkm.movimientos):
            ry = self.ROWS_Y0 + i * (self.ROW_H + self.ROW_GAP)
            rect = pygame.Rect(self.RIGHT_X, ry, self.RIGHT_W, self.ROW_H)
            self._rects_movs.append(rect)

            is_sel = (i in sel)
            is_cur = (i == self._cursor_mov)

            # Fondo de fila
            row_s = pygame.Surface((self.RIGHT_W, self.ROW_H), pygame.SRCALPHA)
            if is_sel:
                row_s.fill((40, 90, 50, 210))   # verde apagado para seleccionado
            elif is_cur:
                row_s.fill((88, 64, 0, 200))    # dorado para cursor
            else:
                row_s.fill((20, 30, 68, 160))
            self.surface.blit(row_s, (self.RIGHT_X, ry))
            if is_cur or is_sel:
                col_border = _GREEN if is_sel else _GOLD
                pygame.draw.rect(self.surface, col_border, rect, 2, border_radius=4)

            # Checkbox visual
            cx = self.RIGHT_X + 12
            cy = ry + self.ROW_H // 2 - 9
            pygame.draw.rect(self.surface, _WHITE, (cx, cy, 18, 18), 2, border_radius=2)
            if is_sel:
                # Tick verde
                pygame.draw.line(self.surface, _GREEN, (cx + 3, cy + 9), (cx + 8, cy + 14), 3)
                pygame.draw.line(self.surface, _GREEN, (cx + 8, cy + 14), (cx + 15, cy + 4), 3)

            # Número de atajo
            s_num = self._font_info.render(str(i + 1), True, _MUTED)
            self.surface.blit(s_num, (cx + 26, ry + 6))

            # Badge de tipo (color de fondo)
            badge_x = cx + 50
            badge_y = ry + 7
            badge_w = 70
            badge_h = 18
            col_tipo = TIPO_COLORES.get(mov.tipo, _MUTED)
            pygame.draw.rect(self.surface, col_tipo, (badge_x, badge_y, badge_w, badge_h), border_radius=3)
            s_tipo = self._font_tipo.render(mov.tipo.upper()[:8], True, _WHITE)
            self.surface.blit(s_tipo, (badge_x + (badge_w - s_tipo.get_width()) // 2,
                                       badge_y + (badge_h - s_tipo.get_height()) // 2))

            # Nombre del movimiento
            col_nombre = _WHITE if not is_sel else _GREEN
            s_nombre = self._font_mov.render(mov.nombre.replace('_', ' '), True, col_nombre)
            self.surface.blit(s_nombre, (badge_x + badge_w + 14, ry + 6))

            # Línea inferior: stats + efecto
            poder_str = f"Pod {int(mov.poder)}" if mov.poder > 0 else "—"
            prec_str  = f"Prec {int(mov.precision)}"
            pp_str    = f"PP {mov.pp_max}"
            cat_str   = mov.categoria[:3]
            stats_str = f"{cat_str}  {poder_str}  {prec_str}  {pp_str}"
            s_stats = self._font_info.render(stats_str, True, _MUTED)
            self.surface.blit(s_stats, (badge_x + badge_w + 14, ry + 28))

            # Efecto (si tiene), a la derecha
            if mov.efecto:
                tipo_ef = mov.efecto.get('tipo', '')
                prob = mov.efecto.get('probabilidad', 1.0)
                ef_str = f"[{tipo_ef}" + (f" {int(prob*100)}%]" if prob < 1.0 else "]")
                s_ef = self._font_info.render(ef_str, True, (200, 180, 100))
                ex = self.RIGHT_X + self.RIGHT_W - s_ef.get_width() - 14
                self.surface.blit(s_ef, (ex, ry + 28))

    def _render_footer(self):
        # Contador a la izquierda
        sel = self._seleccion_actual()
        n_sel = len(sel)
        col_cnt = _GREEN if n_sel == N_SELECCIONAR else _WHITE if n_sel > 0 else _MUTED
        s_cnt = self._font_label.render(
            f"Seleccionados: {n_sel}/{N_SELECCIONAR}", True, col_cnt)
        fy = self.PANEL_Y + self.PANEL_H - 50
        self.surface.blit(s_cnt, (self.PANEL_X + 20, fy + 12))

        # Botón "Volver"
        btn_w, btn_h = 130, 38
        bx_vol = self.PANEL_X + self.PANEL_W - btn_w * 2 - 30
        self._rect_btn_vol = pygame.Rect(bx_vol, fy, btn_w, btn_h)
        mx, my = pygame.mouse.get_pos()
        hover_vol = self._rect_btn_vol.collidepoint(mx, my)
        col_vol_bg = (90, 50, 50) if hover_vol else (60, 30, 30)
        pygame.draw.rect(self.surface, col_vol_bg, self._rect_btn_vol, border_radius=6)
        pygame.draw.rect(self.surface, _MUTED,    self._rect_btn_vol, 2, border_radius=6)
        label_vol = '◄ Volver' if self._idx_pkm == 0 else '◄ Anterior'
        s_vol = self._font_btn.render(label_vol, True, _WHITE)
        self.surface.blit(s_vol, (bx_vol + (btn_w - s_vol.get_width()) // 2,
                                   fy + (btn_h - s_vol.get_height()) // 2))

        # Botón "Siguiente" (o "Comenzar batalla" si es el último)
        bx_sig = self.PANEL_X + self.PANEL_W - btn_w - 20
        self._rect_btn_sig = pygame.Rect(bx_sig, fy, btn_w, btn_h)
        habilitado = self._puede_avanzar()
        hover_sig = self._rect_btn_sig.collidepoint(mx, my)
        if habilitado:
            col_bg = (60, 200, 82) if hover_sig else (38, 158, 62)
            col_border = _GOLD
        else:
            col_bg = (50, 50, 50)
            col_border = _GREY
        pygame.draw.rect(self.surface, col_bg,     self._rect_btn_sig, border_radius=6)
        pygame.draw.rect(self.surface, col_border, self._rect_btn_sig, 2, border_radius=6)
        label_sig = '¡Listo! ►' if self._es_ultimo() else 'Siguiente ►'
        col_text = _WHITE if habilitado else _GREY
        s_sig = self._font_btn.render(label_sig, True, col_text)
        self.surface.blit(s_sig, (bx_sig + (btn_w - s_sig.get_width()) // 2,
                                   fy + (btn_h - s_sig.get_height()) // 2))
