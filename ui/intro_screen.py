import os
import wave
import pygame

from config import SCREEN_WIDTH, SCREEN_HEIGHT
from ui.sprites import cargar_sprite

_SOUNDS_DIR = os.path.join(os.path.dirname(__file__), '..', 'assets', 'sounds')
_INTRO_DIR  = os.path.join(os.path.dirname(__file__), '..', 'assets', 'sprites', 'Intro')


def _cargar_fondo_intro():
    """Carga la primera imagen de la carpeta Intro y la escala a pantalla completa.
    Usa Pillow como fallback para formatos no soportados por Pygame (ej. AVIF)."""
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

_DURACION_MS  = 5000   # auto-avance tras 5 s
_FADE_IN_MS   = 1000   # duración del fade-in del fondo
_SPRITE_IN_MS = 1800   # tiempo que tarda el sprite en llegar a su posición final


# ---------------------------------------------------------------------------
# Música
# ---------------------------------------------------------------------------

def _ruta_musica_intro():
    """Devuelve la ruta a intro.ogg / intro.mp3, o genera un WAV silencioso."""
    for nombre in ('intro.ogg', 'intro.mp3'):
        ruta = os.path.join(_SOUNDS_DIR, nombre)
        if os.path.exists(ruta):
            return ruta

    # Fallback: 2 segundos de silencio estéreo en WAV
    ruta_sil = os.path.join(_SOUNDS_DIR, '_silencio_intro.wav')
    if not os.path.exists(ruta_sil):
        try:
            os.makedirs(_SOUNDS_DIR, exist_ok=True)
            with wave.open(ruta_sil, 'w') as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                # 2 s × 44100 muestras × 2 bytes × 2 canales
                wf.writeframes(b'\x00' * 44100 * 2 * 2 * 2)
        except Exception:
            return None
    return ruta_sil


def iniciar_musica():
    """Carga y reproduce la música de intro en loop."""
    ruta = _ruta_musica_intro()
    if ruta is None:
        return
    try:
        pygame.mixer.music.load(ruta)
        pygame.mixer.music.set_volume(0.7)
        pygame.mixer.music.play(-1)
    except Exception:
        pass


def detener_musica():
    """Detiene la música actual."""
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pantalla de intro
# ---------------------------------------------------------------------------

class IntroScreen:
    """
    Pantalla de presentación antes del menú principal.

    Fases:
      0 – 1 s   : fade-in del fondo negro + título
      0 – 1.8 s : sprite entra desde la derecha (ease-out)
      1.5 s+    : texto parpadeante 'Presiona cualquier tecla'
      0 – 5 s   : barra de progreso dorada
      5 s        : transición automática a MENU
    """

    def __init__(self, surface, fonts):
        self.surface   = surface
        self.fonts     = fonts
        self._inicio   = pygame.time.get_ticks()
        self.terminado = False

        # Fuente grande monoespacia para el título (aspecto pixel-art)
        for nombre_f in ('couriernew', 'lucidaconsole', 'consolas', 'monospace'):
            try:
                self._font_titulo = pygame.font.SysFont(nombre_f, 82, bold=True)
                break
            except Exception:
                pass
        else:
            self._font_titulo = pygame.font.Font(None, 96)

        try:
            self._font_sub = pygame.font.SysFont('couriernew', 15)
        except Exception:
            self._font_sub = pygame.font.Font(None, 20)

        # Sprite animado: Charizard (o Gengar si Charizard no carga)
        self._sprite = None
        for nombre, tipo in (('charizard', 'Fuego'), ('gengar', 'Fantasma')):
            self._sprite = cargar_sprite(nombre, es_espalda=False,
                                         tipo=tipo, tamaño=(220, 220))
            break  # intenta siempre Charizard primero

        # Posición final del sprite: tercio derecho de la pantalla
        self._sprite_dest_x = int(SCREEN_WIDTH * 0.68)
        self._sprite_y      = int(SCREEN_HEIGHT * 0.24)

        # Fondo de la pantalla de intro
        self._fondo = _cargar_fondo_intro()

        # Overlay oscuro semi-transparente sobre el fondo (mejora legibilidad del título)
        self._overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        self._overlay.fill((0, 0, 0, 110))   # negro al ~43 %

        # Superficie negra reutilizable para el overlay de fade-in
        self._negro = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        self._negro.fill((0, 0, 0))

        iniciar_musica()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _elapsed(self):
        return pygame.time.get_ticks() - self._inicio

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def manejar_evento(self, event):
        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            self.terminado = True
            return 'siguiente'
        return None

    def update(self):
        if self._elapsed() >= _DURACION_MS:
            self.terminado = True
            return 'siguiente'
        return None

    def render(self):
        elapsed = self._elapsed()
        ticks   = pygame.time.get_ticks()

        # ── Fondo: imagen de intro o negro si no cargó
        if self._fondo:
            self.surface.blit(self._fondo, (0, 0))
            self.surface.blit(self._overlay, (0, 0))
        else:
            self.surface.fill((0, 0, 0))

        # ── Alpha global (0→255 durante el fade-in)
        alpha = min(255, int(255 * elapsed / _FADE_IN_MS))

        # ── Sprite animado entrando desde la derecha con ease-out cuadrático
        if self._sprite:
            p = min(1.0, elapsed / _SPRITE_IN_MS)
            t = 1.0 - (1.0 - p) ** 2                     # ease-out
            inicio_x = SCREEN_WIDTH + 40
            sprite_x = int(inicio_x - (inicio_x - self._sprite_dest_x) * t)

            frame = self._sprite.get_frame(ticks).copy()
            frame.set_alpha(alpha)
            self.surface.blit(frame, (sprite_x, self._sprite_y))

        # ── Título "POKEFISI" con sombra (color dorado Pokémon)
        cx      = SCREEN_WIDTH // 2
        titulo_y = int(SCREEN_HEIGHT * 0.18)

        surf_sombra = self._font_titulo.render('POKEFISI', True, (90, 55, 0))
        surf_titulo = self._font_titulo.render('POKEFISI', True, (255, 215, 0))

        surf_sombra.set_alpha(alpha)
        surf_titulo.set_alpha(alpha)

        tx = cx - surf_titulo.get_width() // 2
        self.surface.blit(surf_sombra, (tx + 5, titulo_y + 5))
        self.surface.blit(surf_titulo, (tx, titulo_y))

        # ── Subtítulo
        subtitulo = 'Simulador de Combates Pokemon'
        surf_sub = self._font_sub.render(subtitulo, True, (185, 185, 185))
        surf_sub.set_alpha(alpha)
        sub_y = titulo_y + surf_titulo.get_height() + 6
        self.surface.blit(surf_sub, (cx - surf_sub.get_width() // 2, sub_y))

        # ── Línea separadora decorativa
        if alpha > 60:
            sep_y = sub_y + surf_sub.get_height() + 10
            sep_surf = pygame.Surface((340, 2), pygame.SRCALPHA)
            sep_surf.fill((255, 215, 0, alpha))
            self.surface.blit(sep_surf, (cx - 170, sep_y))

        # ── Texto parpadeante (aparece tras 1.5 s, alterna cada 500 ms)
        if elapsed > 1500 and (elapsed // 500) % 2 == 0:
            txt = 'Presiona cualquier tecla para continuar'
            surf_cont = self.fonts['small'].render(txt, True, (210, 210, 210))
            self.surface.blit(surf_cont,
                              (cx - surf_cont.get_width() // 2,
                               SCREEN_HEIGHT - 62))

        # ── Barra de progreso dorada (indica tiempo restante)
        bx       = cx - 200
        bw_total = 400
        bw_fill  = int(bw_total * min(1.0, elapsed / _DURACION_MS))
        pygame.draw.rect(self.surface, (35, 35, 35),
                         (bx, SCREEN_HEIGHT - 26, bw_total, 5),
                         border_radius=3)
        if bw_fill > 0:
            bar = pygame.Surface((bw_fill, 5), pygame.SRCALPHA)
            bar.fill((255, 215, 0, alpha))
            self.surface.blit(bar, (bx, SCREEN_HEIGHT - 26))

        # ── Overlay de fade-in: negro que se desvanece al inicio
        if elapsed < _FADE_IN_MS:
            self._negro.set_alpha(255 - alpha)
            self.surface.blit(self._negro, (0, 0))
