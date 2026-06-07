import os
import io
import urllib.request

import pygame
from PIL import Image

from config import SPRITE_BASE_URL, SPRITE_BACK_URL

SPRITES_DIR       = os.path.join(os.path.dirname(__file__), '..', 'assets', 'sprites')
SPRITES_FRONT_DIR = os.path.join(SPRITES_DIR, 'front')
SPRITES_BACK_DIR  = os.path.join(SPRITES_DIR, 'back')
os.makedirs(SPRITES_FRONT_DIR, exist_ok=True)
os.makedirs(SPRITES_BACK_DIR,  exist_ok=True)


def _migrar_sprites_planos():
    """Mueve GIFs del formato antiguo ({n}_front.gif / {n}_back.gif) a las subcarpetas."""
    import glob
    for ruta in glob.glob(os.path.join(SPRITES_DIR, '*.gif')):
        base = os.path.basename(ruta)
        if base.endswith('_front.gif'):
            destino = os.path.join(SPRITES_FRONT_DIR, base[:-len('_front.gif')] + '.gif')
            try:
                os.rename(ruta, destino)
            except Exception:
                pass
        elif base.endswith('_back.gif'):
            destino = os.path.join(SPRITES_BACK_DIR, base[:-len('_back.gif')] + '.gif')
            try:
                os.rename(ruta, destino)
            except Exception:
                pass

_migrar_sprites_planos()

# (nombre, es_espalda, tamaño) -> SpriteAnimado
_cache = {}

TIPO_COLORES = {
    'Fuego': (220, 80, 40),
    'Agua': (40, 120, 220),
    'Planta': (60, 180, 60),
    'Electrico': (240, 200, 20),
    'Psiquico': (200, 60, 180),
    'Fantasma': (100, 60, 160),
    'Dragon': (80, 60, 220),
    'Siniestro': (60, 40, 80),
    'Acero': (160, 170, 180),
    'Lucha': (180, 80, 40),
    'Tierra': (180, 140, 60),
    'Roca': (140, 120, 80),
    'Hielo': (140, 210, 230),
    'Veneno': (140, 60, 160),
    'Volador': (140, 170, 230),
    'Bicho': (100, 160, 40),
    'Hada': (240, 160, 200),
    'Normal': (160, 160, 140),
}


class SpriteAnimado:
    """Contiene todos los frames de un GIF y avanza según el tiempo de Pygame."""

    def __init__(self, frames: list, duraciones: list):
        self.frames = frames          # list[pygame.Surface]
        self.duraciones = duraciones  # list[int] ms por frame

        # Tiempos acumulados para lookup O(n) simple
        self._acumulado = []
        total = 0
        for d in duraciones:
            total += d
            self._acumulado.append(total)
        self.total_ms = max(total, 1)

    def get_frame(self, ticks: int) -> pygame.Surface:
        """Retorna el frame correcto para el instante `ticks` (ms desde inicio)."""
        if len(self.frames) == 1:
            return self.frames[0]
        t = ticks % self.total_ms
        for i, acum in enumerate(self._acumulado):
            if t < acum:
                return self.frames[i]
        return self.frames[-1]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _nombre_archivo(nombre: str, es_espalda: bool) -> str:
    n = nombre.lower().replace(' ', '-').replace('_', '-')
    subdir = SPRITES_BACK_DIR if es_espalda else SPRITES_FRONT_DIR
    return os.path.join(subdir, f"{n}.gif")


def _url_sprite(nombre: str, es_espalda: bool) -> str:
    n = nombre.lower().replace(' ', '-').replace('_', '-')
    base = SPRITE_BACK_URL if es_espalda else SPRITE_BASE_URL
    return f"{base}{n}.gif"


def _scale_pixel_art(surf: pygame.Surface, target: tuple) -> pygame.Surface:
    """Escala pixel art a `target` usando scale2x iterativo + smoothscale final.
    scale2x dobla el tamaño preservando bordes nítidos; smoothscale solo hace
    el ajuste fino final (mucho menor que escalar desde el tamaño original)."""
    s = surf
    while s.get_width() * 2 <= target[0] or s.get_height() * 2 <= target[1]:
        s = pygame.transform.scale2x(s)
    return pygame.transform.smoothscale(s, target)


def _gif_a_frames(raw_bytes: bytes):
    """
    Extrae todos los frames de un GIF con Pillow a su tamaño ORIGINAL.
    El escalado final lo hace _scale_pixel_art en cargar_sprite.
    Retorna (list[pygame.Surface], list[int]) o (None, None) si falla.
    """
    pil_img = Image.open(io.BytesIO(raw_bytes))
    frames = []
    duraciones = []

    frame_idx = 0
    try:
        while True:
            pil_img.seek(frame_idx)
            # Convertir a RGBA para preservar transparencia
            frame_rgba = pil_img.convert('RGBA')
            # PIL -> bytes -> pygame.Surface (tamaño nativo del GIF)
            surf = pygame.image.fromstring(
                frame_rgba.tobytes(), frame_rgba.size, 'RGBA'
            ).convert_alpha()
            frames.append(surf)
            # 'duration' está en ms; Pillow lo expone en info del frame
            dur = pil_img.info.get('duration', 100)
            duraciones.append(max(16, int(dur)))  # mínimo 16 ms (~60 fps)
            frame_idx += 1
    except EOFError:
        pass

    if not frames:
        return None, None
    return frames, duraciones


def _placeholder(nombre: str, tipo: str = 'Normal', tamaño: tuple = (96, 96)) -> SpriteAnimado:
    surf = pygame.Surface(tamaño, pygame.SRCALPHA)
    color = TIPO_COLORES.get(tipo, (160, 160, 160))
    pygame.draw.ellipse(surf, color, (0, 0, tamaño[0], tamaño[1]))
    pygame.draw.ellipse(surf, (255, 255, 255), (0, 0, tamaño[0], tamaño[1]), 2)
    if pygame.font.get_init():
        font = pygame.font.SysFont('arial', 11, bold=True)
        txt = font.render(nombre[:3].upper(), True, (255, 255, 255))
        surf.blit(txt, ((tamaño[0] - txt.get_width()) // 2,
                        (tamaño[1] - txt.get_height()) // 2))
    return SpriteAnimado([surf], [1000])


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def cargar_sprite(nombre: str, es_espalda: bool = False,
                  tipo: str = 'Normal', tamaño: tuple = (96, 96)) -> SpriteAnimado:
    """
    Carga el sprite animado de un Pokémon.
    Descarga el GIF de Pokémon Showdown, extrae frames con Pillow,
    guarda el GIF en caché local y retorna un SpriteAnimado.
    Fallback: placeholder de color si no hay conexión o el GIF falla.
    """
    cache_key = (nombre, es_espalda, tamaño)
    if cache_key in _cache:
        return _cache[cache_key]

    ruta_cache = _nombre_archivo(nombre, es_espalda)

    # 1. Intentar leer desde caché local (GIF previo)
    if os.path.exists(ruta_cache):
        try:
            with open(ruta_cache, 'rb') as f:
                raw = f.read()
            frames, duraciones = _gif_a_frames(raw)
            if frames:
                frames = [_scale_pixel_art(f, tamaño) for f in frames]
                anim = SpriteAnimado(frames, duraciones)
                _cache[cache_key] = anim
                return anim
        except Exception:
            pass

    # 2. Descargar el GIF de Pokémon Showdown
    url = _url_sprite(nombre, es_espalda)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()

        frames, duraciones = _gif_a_frames(raw)
        if frames:
            frames = [pygame.transform.smoothscale(f, tamaño) for f in frames]
            # Guardar GIF crudo para futuras sesiones
            try:
                with open(ruta_cache, 'wb') as f:
                    f.write(raw)
            except Exception:
                pass
            anim = SpriteAnimado(frames, duraciones)
            _cache[cache_key] = anim
            return anim
    except Exception:
        pass

    # 3. Fallback: placeholder estático
    anim = _placeholder(nombre, tipo, tamaño)
    _cache[cache_key] = anim
    return anim


def limpiar_cache():
    _cache.clear()
