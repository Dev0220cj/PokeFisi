import os
import pygame
from config import SCREEN_WIDTH, SCREEN_HEIGHT

# ── Paleta ───────────────────────────────────────────────────────────────────
_GOLD  = (255, 215,   0)
_WHITE = (255, 255, 255)
_MUTED = (148, 155, 172)

# ── Definición de opciones ────────────────────────────────────────────────────
_OPCIONES_DEF = [
    {'label': 'Tamaño del equipo',  'key': 'tam_equipo',
     'valores': ['3 vs 3', '4 vs 4'],                                                 'idx': 1},
    {'label': 'Tu equipo',          'key': 'equipo_jugador',
     'valores': ['Elegir manual', 'Aleatorio'],                                       'idx': 0},
    {'label': 'Equipo rival',       'key': 'equipo_rival',
     'valores': ['Aleatorio', 'Elegir manual'],                                       'idx': 0},
    {'label': 'Tus movimientos',    'key': 'movs_jugador',
     'valores': ['Predefinidos', 'Aleatorios'],                                       'idx': 0},
    {'label': 'Movs del rival',     'key': 'movs_rival',
     'valores': ['Predefinidos', 'Aleatorios'],                                       'idx': 1},
    {'label': 'Inteligencia rival', 'key': 'nivel_ia',
     'valores': ['Nivel 1  Aleatorio', 'Nivel 2  Heurístico', 'Nivel 3  Minimax'],   'idx': 1},
]

# ── Fondo: imagen de intro ────────────────────────────────────────────────────
_INTRO_DIR     = os.path.join(os.path.dirname(__file__), '..', 'assets', 'sprites', 'Intro')
_fondo_cache:   'pygame.Surface | None' = None
_overlay_cache: 'pygame.Surface | None' = None


def _cargar_fondo() -> 'pygame.Surface | None':
    """Carga la primera imagen de la carpeta Intro, escalada a pantalla completa."""
    if not os.path.isdir(_INTRO_DIR):
        return None
    for archivo in sorted(os.listdir(_INTRO_DIR)):
        ruta = os.path.join(_INTRO_DIR, archivo)
        if not os.path.isfile(ruta):
            continue
        # Intento 1: pygame nativo
        try:
            img = pygame.image.load(ruta).convert()
            return pygame.transform.scale(img, (SCREEN_WIDTH, SCREEN_HEIGHT))
        except Exception:
            pass
        # Intento 2: Pillow (AVIF, WEBP, etc.)
        try:
            from PIL import Image as _PILImage
            pil = _PILImage.open(ruta).convert('RGB')
            pil = pil.resize((SCREEN_WIDTH, SCREEN_HEIGHT), _PILImage.LANCZOS)
            surf = pygame.image.fromstring(pil.tobytes(), (SCREEN_WIDTH, SCREEN_HEIGHT), 'RGB')
            return surf.convert()
        except Exception:
            pass
    return None


def dibujar_paisaje(dest: pygame.Surface) -> None:
    """Dibuja el fondo (imagen de intro) sobre `dest`. Cacheado."""
    global _fondo_cache, _overlay_cache
    if _fondo_cache is None:
        _fondo_cache = _cargar_fondo()
    if _overlay_cache is None:
        _overlay_cache = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        _overlay_cache.fill((0, 0, 0, 70))    # ligero oscurecimiento para legibilidad
    if _fondo_cache:
        dest.blit(_fondo_cache, (0, 0))
        dest.blit(_overlay_cache, (0, 0))
    else:
        dest.fill((26, 26, 46))               # fallback si la imagen no carga


# ── Pantalla de configuración ─────────────────────────────────────────────────
class ConfigScreen:
    # Geometría
    PANEL_X = SCREEN_WIDTH // 2 - 350
    PANEL_W = 700
    PANEL_Y = 66
    PANEL_H = 482

    ROW_X   = SCREEN_WIDTH // 2 - 310
    ROW_W   = 620
    ROW_H   = 46
    ROW_GAP = 8
    ROW_Y0  = 130

    # Offsets relativos a ROW_X para flechas y valor
    ARROW_L_OFF  = 352
    VALUE_CX_OFF = 490
    ARROW_R_OFF  = 606

    def __init__(self, surface, fonts):
        self.surface  = surface
        self.fonts    = fonts
        self.cursor   = 0
        self.opciones = [dict(o) for o in _OPCIONES_DEF]

        self._font_titulo = self._make_font(26, bold=True)
        self._font_opcion = self._make_font(18, bold=True)
        self._font_valor  = self._make_font(18)
        self._font_hint   = self._make_font(12)

        # Ensure cache is populated while pygame is active
        dibujar_paisaje(surface)

        # Rects para colisión con ratón (se actualizan cada frame en render)
        self._rects_filas: list = []
        self._rect_btn = pygame.Rect(0, 0, 0, 0)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _make_font(size: int, bold: bool = False) -> pygame.font.Font:
        for nombre in ('couriernew', 'lucidaconsole', 'consolas'):
            try:
                return pygame.font.SysFont(nombre, size, bold=bold)
            except Exception:
                pass
        return pygame.font.Font(None, size + 8)

    # ── API pública ───────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        """Devuelve un dict con la configuración actual."""
        return {o['key']: o['valores'][o['idx']] for o in self.opciones}

    def manejar_evento(self, event) -> 'str | None':
        n = len(self.opciones)

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self.cursor = (self.cursor - 1) % n
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.cursor = (self.cursor + 1) % n
            elif event.key in (pygame.K_LEFT, pygame.K_a):
                op = self.opciones[self.cursor]
                op['idx'] = (op['idx'] - 1) % len(op['valores'])
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                op = self.opciones[self.cursor]
                op['idx'] = (op['idx'] + 1) % len(op['valores'])
            elif event.key in (pygame.K_RETURN, pygame.K_z):
                return 'confirmar'
            elif event.key == pygame.K_ESCAPE:
                return 'volver'

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            for i, rect in enumerate(self._rects_filas):
                if rect.collidepoint(mx, my):
                    if self.cursor == i:
                        # mitad izquierda → decrementar, derecha → incrementar
                        op = self.opciones[i]
                        mid = rect.x + (self.ARROW_L_OFF + self.ARROW_R_OFF) // 2
                        op['idx'] = (op['idx'] + (-1 if mx < mid else 1)) % len(op['valores'])
                    else:
                        self.cursor = i
                    return None
            if self._rect_btn.collidepoint(mx, my):
                return 'confirmar'

        return None

    def render(self) -> None:
        # Fondo paisaje
        dibujar_paisaje(self.surface)

        cx = SCREEN_WIDTH // 2

        # Panel semitransparente
        panel = pygame.Surface((self.PANEL_W, self.PANEL_H), pygame.SRCALPHA)
        panel.fill((10, 18, 46, 190))
        self.surface.blit(panel, (self.PANEL_X, self.PANEL_Y))
        pygame.draw.rect(self.surface, _GOLD,
                         (self.PANEL_X, self.PANEL_Y, self.PANEL_W, self.PANEL_H),
                         2, border_radius=10)

        # Título
        s_somb = self._font_titulo.render('Configuración del combate', True, (50, 35, 0))
        s_tit  = self._font_titulo.render('Configuración del combate', True, _GOLD)
        ty = self.PANEL_Y + 10
        self.surface.blit(s_somb, (cx - s_tit.get_width() // 2 + 3, ty + 3))
        self.surface.blit(s_tit,  (cx - s_tit.get_width() // 2, ty))

        # Separador bajo el título
        sep_y = ty + s_tit.get_height() + 6
        pygame.draw.line(self.surface, _GOLD,
                         (self.PANEL_X + 20, sep_y), (self.PANEL_X + self.PANEL_W - 20, sep_y), 1)

        # Filas de opciones
        self._rects_filas = []
        for i, op in enumerate(self.opciones):
            ry   = self.ROW_Y0 + i * (self.ROW_H + self.ROW_GAP)
            rect = pygame.Rect(self.ROW_X, ry, self.ROW_W, self.ROW_H)
            self._rects_filas.append(rect)
            sel  = (i == self.cursor)

            # Fondo de fila
            row_s = pygame.Surface((self.ROW_W, self.ROW_H), pygame.SRCALPHA)
            row_s.fill((88, 64, 0, 188) if sel else (20, 30, 68, 148))
            self.surface.blit(row_s, (self.ROW_X, ry))
            if sel:
                pygame.draw.rect(self.surface, _GOLD, rect, 2, border_radius=4)

            cy_txt = ry + (self.ROW_H - self._font_opcion.get_height()) // 2

            # Etiqueta
            col_l = _GOLD if sel else _WHITE
            s_lbl = self._font_opcion.render(op['label'], True, col_l)
            self.surface.blit(s_lbl, (self.ROW_X + 14, cy_txt))

            # Flecha izquierda ◄
            if sel:
                s_al = self._font_opcion.render('◄', True, _GOLD)
                self.surface.blit(s_al, (self.ROW_X + self.ARROW_L_OFF, cy_txt))

            # Valor centrado
            col_v = _GOLD if sel else (210, 215, 228)
            s_val = self._font_valor.render(op['valores'][op['idx']], True, col_v)
            vx = self.ROW_X + self.VALUE_CX_OFF - s_val.get_width() // 2
            self.surface.blit(s_val, (vx, cy_txt))

            # Flecha derecha ►
            if sel:
                s_ar = self._font_opcion.render('►', True, _GOLD)
                self.surface.blit(s_ar, (self.ROW_X + self.ARROW_R_OFF, cy_txt))

        # Botón ¡Comenzar!
        btn_w, btn_h = 240, 46
        btn_y = self.ROW_Y0 + len(self.opciones) * (self.ROW_H + self.ROW_GAP) + 12
        btn_x = cx - btn_w // 2
        self._rect_btn = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

        mx, my = pygame.mouse.get_pos()
        hover  = self._rect_btn.collidepoint(mx, my)
        btn_bg = (60, 200, 82) if hover else (38, 158, 62)
        pygame.draw.rect(self.surface, btn_bg,  self._rect_btn, border_radius=8)
        pygame.draw.rect(self.surface, _GOLD,   self._rect_btn, 2, border_radius=8)
        s_btn = self._font_opcion.render('¡Comenzar!', True, _WHITE)
        self.surface.blit(s_btn, (cx - s_btn.get_width() // 2,
                                  btn_y + (btn_h - s_btn.get_height()) // 2))

        # Hints de teclado
        hint = '↑↓  Navegar    ◄►  Cambiar valor    ENTER  Confirmar    ESC  Volver'
        s_h  = self._font_hint.render(hint, True, _MUTED)
        self.surface.blit(s_h, (cx - s_h.get_width() // 2, SCREEN_HEIGHT - 20))
