import pygame
from config import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_BG, COLOR_PANEL, COLOR_BORDER,
    COLOR_TEXT, COLOR_TEXT_MUTED,
    COLOR_HP_HIGH, COLOR_HP_MID, COLOR_HP_LOW,
    COLOR_WHITE, COLOR_BLACK,
)
from src.pokemon import lista_nombres_pokemon
from ui.sprites import cargar_sprite
from ui.config_screen import dibujar_paisaje

# ---------------------------------------------------------------------------
# Colores compartidos
# ---------------------------------------------------------------------------
TIPO_COLORES = {
    'Fuego':    (220,  80,  40), 'Agua':     ( 40, 120, 220),
    'Planta':   ( 60, 180,  60), 'Electrico':(240, 200,  20),
    'Psiquico': (200,  60, 180), 'Fantasma': (100,  60, 160),
    'Dragon':   ( 80,  60, 220), 'Siniestro':( 80,  50, 100),
    'Acero':    (160, 170, 180), 'Lucha':    (180,  80,  40),
    'Tierra':   (180, 140,  60), 'Roca':     (140, 120,  80),
    'Hielo':    (140, 210, 230), 'Veneno':   (140,  60, 160),
    'Volador':  (140, 170, 230), 'Bicho':    (100, 160,  40),
    'Hada':     (240, 160, 200), 'Normal':   (160, 160, 140),
}

# ---------------------------------------------------------------------------
# Colores específicos de TeamSelect (carta clara sobre fondo oscuro)
# ---------------------------------------------------------------------------
C_CARD_BG      = (228, 232, 246)   # blanco-azulado neutro
C_CARD_HOVER   = (255, 210,  38)   # amarillo/dorado — cursor actual
C_CARD_CHOSEN  = (195, 242, 210)   # verde menta — ya en el equipo
C_CARD_TEXT    = ( 18,  20,  40)   # texto oscuro sobre carta clara
C_CARD_BORDER  = (170, 185, 215)   # borde neutro
C_HOVER_BRD    = (195, 148,   0)   # borde dorado oscuro
C_CHOSEN_BRD   = ( 30, 155,  65)   # borde verde fuerte
C_BADGE_BG     = ( 38, 168,  70)   # círculo del badge de equipo

# Colores de barras de estadísticas (HP, ATK, DEF, AT.E, DF.E, VEL)
STAT_INFO = [
    ('HP',   'hp',        (218,  55,  55)),
    ('ATK',  'ataque',    (218, 128,  38)),
    ('DEF',  'defensa',   (200, 178,  38)),
    ('AT.E', 'sp_atk',   ( 95,  75, 218)),
    ('DF.E', 'sp_def',   ( 38, 158, 158)),
    ('VEL',  'velocidad', ( 55, 196,  75)),
]
STAT_MAX = 160   # valor máximo de referencia para normalizar barras

# ---------------------------------------------------------------------------
# Constantes de layout para TeamSelectScreen
# ---------------------------------------------------------------------------
LEFT_W   = 716          # 70 % de 1024
RIGHT_X  = LEFT_W
RIGHT_W  = SCREEN_WIDTH - LEFT_W   # 308 px

# Grilla: 6 cols × 5 rows = 30 Pokémon sin scroll
COLS   = 6
ROWS   = 5
CELL   = 104            # celda cuadrada (px)
GRID_X = (LEFT_W - COLS * CELL) // 2   # 46 — centrado horizontalmente
GRID_Y = 44             # bajo el encabezado
CARD_W = CELL - 2       # 102 — carta visible (2 px de gap)
CARD_H = CELL - 2       # 102

SPR_CARD   = (76, 76)   # sprite en carta de grilla
SPR_DETAIL = (128, 128) # sprite en panel de detalle


# ===========================================================================
# TeamSelectScreen
# ===========================================================================
class TeamSelectScreen:
    """
    Pantalla de selección de equipo.
    Izquierda (70 %): grilla 6×5 con cartas cuadradas claras sobre fondo oscuro.
    Derecha (30 %):   detalle del Pokémon bajo el cursor + barras de stats.
    """

    def __init__(self, surface, fonts, tam: int = 4, titulo: str = 'SELECCIONA TU EQUIPO'):
        self.surface = surface
        self.fonts = fonts
        self.tam   = tam
        self.titulo = titulo
        self.todos = lista_nombres_pokemon()   # exactamente 30
        self.seleccionados: list[int] = []
        self.cursor = 0
        self.cols = COLS
        # Rect del botón Confirmar (se actualiza en render)
        self._confirm_rect = pygame.Rect(RIGHT_X + 14, 377, RIGHT_W - 28, 48)

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _card_rect(self, idx: int) -> pygame.Rect:
        col = idx % COLS
        row = idx // COLS
        return pygame.Rect(
            GRID_X + col * CELL + 1,
            GRID_Y + row * CELL + 1,
            CARD_W, CARD_H,
        )

    def _blit_centered(self, surf, cx, y):
        self.surface.blit(surf, (cx - surf.get_width() // 2, y))

    def _render_nombre_carta(self, nombre: str, card: pygame.Rect):
        """Dibuja el nombre centrado en la carta, cambiando a fuente tiny si no cabe."""
        max_w = card.width - 8
        surf = self.fonts['small'].render(nombre, True, C_CARD_TEXT)
        if surf.get_width() > max_w:
            surf = self.fonts['tiny'].render(nombre, True, C_CARD_TEXT)
        self._blit_centered(surf, card.centerx, card.y + 4 + SPR_CARD[1] + 3)

    # ------------------------------------------------------------------
    # Panel izquierdo: grilla
    # ------------------------------------------------------------------

    def _render_grid(self, datos_pokemon: dict):
        # Overlay semitransparente sobre el área de la grilla
        _panel_l = pygame.Surface((LEFT_W, SCREEN_HEIGHT), pygame.SRCALPHA)
        _panel_l.fill((10, 15, 30, 130))
        self.surface.blit(_panel_l, (0, 0))

        # Encabezado
        cx_left = LEFT_W // 2
        title = self.fonts['normal'].render(self.titulo, True, COLOR_TEXT)
        self.surface.blit(title, (cx_left - title.get_width() // 2, 6))

        n = len(self.seleccionados)
        cnt_color = COLOR_HP_HIGH if n == self.tam else COLOR_TEXT_MUTED
        cnt_surf = self.fonts['small'].render(f'{n}/{self.tam} Pokémon elegidos', True, cnt_color)
        self.surface.blit(cnt_surf, (cx_left - cnt_surf.get_width() // 2, 26))

        # Cartas
        for idx, nombre in enumerate(self.todos):
            card = self._card_rect(idx)
            sel   = idx in self.seleccionados
            hover = idx == self.cursor

            # Fondo y borde según estado
            if hover and sel:
                bg, brd, brd_w = C_CARD_HOVER,  C_CHOSEN_BRD,  2
            elif hover:
                bg, brd, brd_w = C_CARD_HOVER,  C_HOVER_BRD,   2
            elif sel:
                bg, brd, brd_w = C_CARD_CHOSEN, C_CHOSEN_BRD,  2
            else:
                bg, brd, brd_w = C_CARD_BG,     C_CARD_BORDER, 1

            pygame.draw.rect(self.surface, bg,  card, border_radius=8)
            pygame.draw.rect(self.surface, brd, card, brd_w, border_radius=8)

            # Sprite (primer frame)
            pdata = datos_pokemon.get(nombre, {})
            tipo  = pdata.get('tipo', ['Normal'])[0]
            spr   = cargar_sprite(nombre, es_espalda=False, tipo=tipo, tamaño=SPR_CARD)
            frame = spr.get_frame(0)
            spr_x = card.x + (CARD_W - SPR_CARD[0]) // 2   # centrado horizontal
            self.surface.blit(frame, (spr_x, card.y + 4))

            # Nombre debajo del sprite
            self._render_nombre_carta(nombre, card)

            # Badge de número de equipo (esquina superior derecha)
            if sel:
                num     = self.seleccionados.index(idx) + 1
                bcx     = card.right - 11
                bcy     = card.y + 11
                pygame.draw.circle(self.surface, C_BADGE_BG,    (bcx, bcy), 10)
                pygame.draw.circle(self.surface, COLOR_WHITE,   (bcx, bcy), 10, 1)
                ns = self.fonts['small'].render(str(num), True, COLOR_WHITE)
                self.surface.blit(ns, (bcx - ns.get_width() // 2,
                                       bcy - ns.get_height() // 2))

        # Instrucciones bajo la grilla
        tip = ('Flechas / ratón: mover  |  '
               'Clic / ESPACIO: elegir o quitar  |  '
               'ENTER / botón: confirmar')
        ts = self.fonts['tiny'].render(tip, True, COLOR_TEXT_MUTED)
        ty = GRID_Y + ROWS * CELL + (SCREEN_HEIGHT - GRID_Y - ROWS * CELL - ts.get_height()) // 2
        self.surface.blit(ts, (cx_left - ts.get_width() // 2, ty))

    # ------------------------------------------------------------------
    # Panel derecho: detalle del Pokémon en el cursor
    # ------------------------------------------------------------------

    def _render_detail(self, datos_pokemon: dict):
        rx = RIGHT_X
        rw = RIGHT_W
        cx = rx + rw // 2
        pad = 14

        # Panel derecho: overlay semitransparente oscuro sobre el fondo de imagen
        _panel_r = pygame.Surface((rw, SCREEN_HEIGHT), pygame.SRCALPHA)
        _panel_r.fill((14, 18, 38, 205))
        self.surface.blit(_panel_r, (rx, 0))
        pygame.draw.line(self.surface, COLOR_BORDER, (rx, 0), (rx, SCREEN_HEIGHT), 1)

        nombre = self.todos[self.cursor]
        pdata  = datos_pokemon.get(nombre, {})
        tipos  = pdata.get('tipo', ['Normal'])

        # -- Sprite grande --
        tipo_p = tipos[0]
        spr    = cargar_sprite(nombre, es_espalda=False, tipo=tipo_p, tamaño=SPR_DETAIL)
        frame  = spr.get_frame(0)
        self._blit_centered(frame, cx, 8)

        y = 8 + SPR_DETAIL[1] + 6   # 142

        # -- Nombre --
        ns = self.fonts['normal'].render(nombre, True, COLOR_WHITE)
        self._blit_centered(ns, cx, y)
        y += ns.get_height() + 5     # ~162

        # -- Badges de tipo --
        bw, bgap = 58, 5
        total_bw = len(tipos) * bw + (len(tipos) - 1) * bgap
        tx = cx - total_bw // 2
        for tipo in tipos:
            tc = TIPO_COLORES.get(tipo, (100, 100, 100))
            pygame.draw.rect(self.surface, tc, (tx, y, bw, 18), border_radius=5)
            ts = self.fonts['small'].render(tipo[:7], True, COLOR_WHITE)
            self.surface.blit(ts, (tx + (bw - ts.get_width()) // 2, y + 3))
            tx += bw + bgap
        y += 18 + 8                  # ~188

        # -- Separador "ESTADÍSTICAS" --
        sep = self.fonts['tiny'].render('─── ESTADÍSTICAS ───', True, COLOR_TEXT_MUTED)
        self._blit_centered(sep, cx, y)
        y += sep.get_height() + 5   # ~204+

        # -- Barras de estadísticas --
        label_w  = 40
        val_w    = 36
        bar_x    = rx + pad + label_w + 4
        bar_end  = rx + rw - pad - val_w - 4
        bar_w    = bar_end - bar_x            # ~198 px
        bar_h    = 10

        for label, key, color in STAT_INFO:
            val = pdata.get(key, 0)
            fill = int(bar_w * min(1.0, val / STAT_MAX))

            # Etiqueta (alineada a la derecha del espacio de label)
            ls = self.fonts['small'].render(label, True, COLOR_TEXT_MUTED)
            self.surface.blit(ls, (bar_x - label_w - 4 + (label_w - ls.get_width()), y + 1))

            # Riel de la barra
            rail_rect = pygame.Rect(bar_x, y, bar_w, bar_h)
            pygame.draw.rect(self.surface, (38, 42, 68), rail_rect, border_radius=4)
            if fill > 0:
                pygame.draw.rect(self.surface, color,
                                 (bar_x, y, fill, bar_h), border_radius=4)

            # Valor numérico
            vs = self.fonts['small'].render(str(val), True, COLOR_TEXT)
            self.surface.blit(vs, (bar_end + 4, y + 1))

            y += 26   # 6 stats × 26 = 156 px → ends at ~367

        y += 8   # ~375

        # -- Botón Confirmar --
        elegidos    = len(self.seleccionados)
        can_confirm = elegidos == self.tam

        # Detectar hover del ratón sobre el botón
        mx, my = pygame.mouse.get_pos()
        btn_rect = pygame.Rect(rx + pad, y, rw - pad * 2, 48)
        self._confirm_rect = btn_rect
        hovered = btn_rect.collidepoint(mx, my)

        if can_confirm:
            btn_bg  = (55, 210, 90) if hovered else (38, 175, 70)
            btn_txt = 'Confirmar  ▶'
            btn_fg  = COLOR_WHITE
        else:
            btn_bg  = (48, 52, 72)
            btn_txt = f'Elige {self.tam - elegidos} más...'
            btn_fg  = (110, 115, 140)

        pygame.draw.rect(self.surface, btn_bg, btn_rect, border_radius=10)
        pygame.draw.rect(self.surface, COLOR_BORDER, btn_rect, 1, border_radius=10)
        bs = self.fonts['normal'].render(btn_txt, True, btn_fg)
        self._blit_centered(bs, cx, btn_rect.y + (btn_rect.height - bs.get_height()) // 2)

        # -- Hint ESC --
        esc = self.fonts['tiny'].render('ESC: volver al menú', True, COLOR_TEXT_MUTED)
        self._blit_centered(esc, cx, SCREEN_HEIGHT - 18)

    # ------------------------------------------------------------------
    # Render principal
    # ------------------------------------------------------------------

    def render(self, datos_pokemon: dict):
        dibujar_paisaje(self.surface)
        self._render_grid(datos_pokemon)
        self._render_detail(datos_pokemon)

    # ------------------------------------------------------------------
    # Eventos (teclado + ratón)
    # ------------------------------------------------------------------

    def manejar_evento(self, event):
        total = len(self.todos)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RIGHT:
                self.cursor = min(total - 1, self.cursor + 1)
            elif event.key == pygame.K_LEFT:
                self.cursor = max(0, self.cursor - 1)
            elif event.key == pygame.K_DOWN:
                self.cursor = min(total - 1, self.cursor + COLS)
            elif event.key == pygame.K_UP:
                self.cursor = max(0, self.cursor - COLS)
            elif event.key == pygame.K_SPACE:
                self._toggle(self.cursor)
            elif event.key == pygame.K_RETURN:
                if len(self.seleccionados) == self.tam:
                    return 'confirmar'
            elif event.key == pygame.K_ESCAPE:
                return 'volver'

        elif event.type == pygame.MOUSEMOTION:
            idx = self._idx_en_grid(event.pos)
            if idx is not None:
                self.cursor = idx

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if mx < LEFT_W:
                idx = self._idx_en_grid(event.pos)
                if idx is not None:
                    self.cursor = idx
                    self._toggle(idx)
            else:
                if self._confirm_rect.collidepoint(mx, my) and len(self.seleccionados) == self.tam:
                    return 'confirmar'

        return None

    def _toggle(self, idx: int):
        if idx in self.seleccionados:
            self.seleccionados.remove(idx)
        elif len(self.seleccionados) < self.tam:
            self.seleccionados.append(idx)

    def _idx_en_grid(self, pos) -> int | None:
        """Retorna el índice global del Pokémon bajo las coordenadas pos, o None."""
        mx, my = pos
        if mx < GRID_X or my < GRID_Y:
            return None
        col = (mx - GRID_X) // CELL
        row = (my - GRID_Y) // CELL
        if col < 0 or col >= COLS or row < 0 or row >= ROWS:
            return None
        idx = row * COLS + col
        return idx if idx < len(self.todos) else None

    def equipo_seleccionado(self) -> list[str]:
        return [self.todos[i] for i in self.seleccionados]
