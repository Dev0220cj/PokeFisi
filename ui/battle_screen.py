import os
import random
import pygame
from config import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_BG, COLOR_PANEL, COLOR_PANEL_DARK, COLOR_BORDER,
    COLOR_TEXT, COLOR_TEXT_MUTED,
    COLOR_HP_HIGH, COLOR_HP_MID, COLOR_HP_LOW,
    COLOR_WHITE, COLOR_BLACK,
)
from ui.sprites import cargar_sprite

TIPO_COLORES = {
    'Fuego': (220, 80, 40),
    'Agua': (40, 120, 220),
    'Planta': (60, 180, 60),
    'Electrico': (240, 200, 20),
    'Psiquico': (200, 60, 180),
    'Fantasma': (100, 60, 160),
    'Dragon': (80, 60, 220),
    'Siniestro': (80, 50, 100),
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

ESTADO_COLORES = {
    'quemar': (220, 80, 40),
    'paralizar': (240, 200, 20),
    'congelar': (140, 210, 230),
    'envenenar': (140, 60, 160),
    'envenenar_grave': (100, 20, 120),
    'dormir': (80, 80, 140),
}

ESTADO_ABREV = {
    'quemar': 'QEM',
    'paralizar': 'PAR',
    'congelar': 'CON',
    'envenenar': 'VEN',
    'envenenar_grave': 'TOX',
    'dormir': 'DOR',
}

# ── Paleta verde del panel de batalla ──────────────────────────────────────
_PANEL_BG  = ( 30,  72,  38)  # fondo panel inferior y diálogos
_BTN_BG    = ( 48, 118,  58)  # botón / slot normal
_BTN_SEL   = ( 75, 175,  88)  # botón seleccionado o con hover
_BTN_DEAD  = ( 22,  46,  26)  # slot de Pokémon debilitado
_PANEL_BD  = (140, 225, 100)  # borde y detalles del panel
_HUD_BG    = ( 34,  85,  45)  # fondo de HUDs (jugador y rival)


class BattleScreen:
    def __init__(self, surface, fonts):
        self.surface = surface
        self.fonts = fonts  # dict: 'title', 'normal', 'small', 'tiny'

        # Animación HP
        self._hp_anim_j = {}   # nombre -> [hp_mostrado, last_ticks]
        self._hp_anim_i = {}

        # Snapshots para congelar la animación hasta que aparezca el mensaje de daño
        # {nombre: hp_congelado}  –  vacío = sin congelar
        self._hp_snapshot_j  = {}
        self._hp_snapshot_ia = {}

        # Log de mensajes visible
        self.mensajes = []
        self.mensajes_scroll = 0

        # Estado UI
        self.seleccion_mov = 0
        self.modo = 'luchar'  # 'luchar' | 'cambiar'
        self.resultado_texto = None

        # Rects para detección de mouse (actualizados en cada render)
        self._mov_rects:    list[pygame.Rect] = [pygame.Rect(0,0,0,0)] * 4
        self._cambio_rects: list[pygame.Rect] = []
        self._btn_luchar_rect  = pygame.Rect(0, 0, 0, 0)
        self._btn_cambiar_rect = pygame.Rect(0, 0, 0, 0)

        self._bg = self._cargar_fondo_aleatorio()
        self._iniciar_musica()

    _BACKGROUNDS_DIR = os.path.join(
        os.path.dirname(__file__), '..', 'assets', 'sprites', 'backgrounds'
    )

    def _cargar_fondo_aleatorio(self):
        try:
            archivos = [f for f in os.listdir(self._BACKGROUNDS_DIR)
                        if f.lower().endswith('.png')]
            if archivos:
                ruta = os.path.join(self._BACKGROUNDS_DIR, random.choice(archivos))
                img = pygame.image.load(ruta).convert()
                return pygame.transform.scale(img, (SCREEN_WIDTH, SCREEN_HEIGHT))
        except Exception:
            pass
        return None

    def _iniciar_musica(self):
        """Reproduce battle.mp3 en loop. Silencioso si el archivo no existe o el mixer falla."""
        ruta = os.path.join(os.path.dirname(__file__), '..', 'assets', 'sounds', 'battle.mp3')
        if not os.path.exists(ruta):
            return
        try:
            pygame.mixer.music.load(ruta)
            pygame.mixer.music.set_volume(0.7)
            pygame.mixer.music.play(-1)
        except Exception:
            pass

    def detener_musica(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    def _get_hp_animado(self, anim_dict, pokemon, snapshot=None):
        """
        Devuelve el HP que se debe mostrar (float) con drenado suave.
        Si se pasa `snapshot` y el pokemon está en él, usa ese HP congelado
        como objetivo (no anima hacia el HP real hasta que se libere el snapshot).
        """
        nombre   = pokemon.nombre
        # HP objetivo: congelado si hay snapshot, real si no
        real_hp  = float(snapshot[nombre]) if (snapshot and nombre in snapshot) \
                   else float(pokemon.hp)
        ticks    = pygame.time.get_ticks()

        if nombre not in anim_dict:
            anim_dict[nombre] = [real_hp, ticks]
            return real_hp

        entry = anim_dict[nombre]
        displayed, last_ticks = entry
        dt_s = min((ticks - last_ticks) / 1000.0, 0.05)  # tope 50 ms para evitar saltos
        entry[1] = ticks

        if displayed > real_hp:
            speed = pokemon.hp_max / 2.5          # recorre todo el HP en 2.5 s
            entry[0] = max(real_hp, displayed - speed * dt_s)
        else:
            entry[0] = real_hp                    # curación o sin cambio: inmediato

        return entry[0]

    # ── Control de animación HP ───────────────────────────────────────────────

    def freeze_hp(self, equipo_j, equipo_ia):
        """Congela las barras de HP al valor actual; la animación arranca sólo
        cuando aparezca el mensaje de daño correspondiente."""
        self._hp_snapshot_j  = {p.nombre: float(p.hp) for p in equipo_j}
        self._hp_snapshot_ia = {p.nombre: float(p.hp) for p in equipo_ia}

    def unfreeze_hp_j(self):
        """Libera la animación de HP del lado jugador."""
        self._hp_snapshot_j = {}

    def unfreeze_hp_ia(self):
        """Libera la animación de HP del lado rival."""
        self._hp_snapshot_ia = {}

    def _color_hp(self, ratio):
        if ratio > 0.5:
            return COLOR_HP_HIGH
        elif ratio > 0.2:
            return COLOR_HP_MID
        return COLOR_HP_LOW

    def _dibujar_barra_hp(self, x, y, w, h, ratio, animar=True):
        pygame.draw.rect(self.surface, COLOR_PANEL_DARK, (x, y, w, h), border_radius=4)
        fill_w = int(w * max(0, min(1, ratio)))
        color = self._color_hp(ratio)
        if fill_w > 0:
            pygame.draw.rect(self.surface, color, (x, y, fill_w, h), border_radius=4)
        pygame.draw.rect(self.surface, COLOR_BORDER, (x, y, w, h), 1, border_radius=4)

    def _dibujar_pokeball(self, cx, cy, r=7, vivo=True):
        """Dibuja una mini Pokéball centrada en (cx, cy) con radio r."""
        color_top = (220, 40, 40)   if vivo else (80,  80,  80)
        color_bot = (245, 245, 245) if vivo else (110, 110, 110)
        dark      = (20,  20,  20)

        sz  = r * 2 + 2
        lc  = r + 1           # centro local dentro de la superficie

        surf = pygame.Surface((sz, sz), pygame.SRCALPHA)

        # Mitad superior (roja / gris)
        pygame.draw.circle(surf, color_top, (lc, lc), r)

        # Mitad inferior (blanca / gris claro): dibujar círculo completo y borrar la mitad superior
        bot = pygame.Surface((sz, sz), pygame.SRCALPHA)
        pygame.draw.circle(bot, color_bot, (lc, lc), r)
        bot.fill((0, 0, 0, 0), (0, 0, sz, lc))   # transparentar mitad superior
        surf.blit(bot, (0, 0))

        # Contorno y franja central
        pygame.draw.circle(surf, dark, (lc, lc), r, 1)
        pygame.draw.line(surf, dark, (lc - r + 1, lc), (lc + r - 1, lc), 1)

        # Botón central
        br = max(2, r // 3)
        pygame.draw.circle(surf, (240, 240, 240), (lc, lc), br)
        pygame.draw.circle(surf, dark,             (lc, lc), br, 1)

        self.surface.blit(surf, (cx - lc, cy - lc))

    def _dibujar_panel(self, rect, color=None, border=True, radius=8, border_color=None):
        c = color or COLOR_PANEL
        pygame.draw.rect(self.surface, c, rect, border_radius=radius)
        if border:
            bc = border_color or COLOR_BORDER
            pygame.draw.rect(self.surface, bc, rect, 1, border_radius=radius)

    def _texto(self, txt, x, y, font_key='normal', color=None, centrado=False):
        c = color or COLOR_TEXT
        font = self.fonts[font_key]
        surf = font.render(str(txt), True, c)
        if centrado:
            x -= surf.get_width() // 2
        self.surface.blit(surf, (x, y))
        return surf.get_width()

    def dibujar_fondo(self):
        if self._bg:
            self.surface.blit(self._bg, (0, 0))
        else:
            self.surface.fill(COLOR_BG)
        # Plataforma enemigo (arriba-derecha)
        pygame.draw.ellipse(self.surface, (35, 35, 60), (620, 195, 180, 35))
        # Plataforma jugador (abajo-izquierda)
        pygame.draw.ellipse(self.surface, (35, 35, 60), (110, 425, 200, 40))

    def dibujar_hud_enemigo(self, pokemon, equipo=None, x=80, y=30):
        """HUD enemigo: arriba-derecha."""
        w = 320
        h = 108 if equipo else 90
        self._dibujar_panel((x, y, w, h), _HUD_BG, border_color=_PANEL_BD)

        # Nombre
        self._texto(pokemon.nombre, x + 12, y + 8, 'normal', COLOR_WHITE)

        # Estado
        if pokemon.estado:
            col = ESTADO_COLORES.get(pokemon.estado, COLOR_TEXT_MUTED)
            abr = ESTADO_ABREV.get(pokemon.estado, '???')
            self._texto(f'[{abr}]', x + w - 60, y + 8, 'small', col)

        # Tipos
        tx = x + 12
        for tipo in pokemon.tipos:
            tc = TIPO_COLORES.get(tipo, (100, 100, 100))
            pygame.draw.rect(self.surface, tc, (tx, y + 28, 50, 14), border_radius=3)
            self._texto(tipo[:6], tx + 2, y + 29, 'tiny', COLOR_WHITE)
            tx += 55

        # Barra HP (con animación de drenado; congelada hasta que aparezca el msg de daño)
        hp_anim = self._get_hp_animado(self._hp_anim_i, pokemon, self._hp_snapshot_ia)
        ratio = hp_anim / max(1, pokemon.hp_max)
        self._texto('HP', x + 12, y + 50, 'small', COLOR_TEXT_MUTED)
        self._dibujar_barra_hp(x + 35, y + 53, w - 50, 10, ratio)

        # Equipo rival (Pokéballs)
        if equipo:
            self._texto('Rival:', x + 12, y + 72, 'small', COLOR_TEXT_MUTED)
            for i, p in enumerate(equipo):
                pb_cx = x + 72 + i * 22
                self._dibujar_pokeball(pb_cx, y + 89, r=7, vivo=p.esta_vivo())

    def dibujar_hud_jugador(self, pokemon, equipo, x=580, y=350):
        """HUD jugador: abajo-izquierda."""
        w, h = 340, 110
        self._dibujar_panel((x, y, w, h), _HUD_BG, border_color=_PANEL_BD)

        # Nombre
        self._texto(pokemon.nombre, x + 12, y + 8, 'normal', COLOR_WHITE)

        # Estado
        if pokemon.estado:
            col = ESTADO_COLORES.get(pokemon.estado, COLOR_TEXT_MUTED)
            abr = ESTADO_ABREV.get(pokemon.estado, '???')
            self._texto(f'[{abr}]', x + w - 70, y + 8, 'small', col)

        # Tipos
        tx = x + 12
        for tipo in pokemon.tipos:
            tc = TIPO_COLORES.get(tipo, (100, 100, 100))
            pygame.draw.rect(self.surface, tc, (tx, y + 30, 50, 14), border_radius=3)
            self._texto(tipo[:6], tx + 2, y + 31, 'tiny', COLOR_WHITE)
            tx += 55

        # Barra HP + números (con animación de drenado; congelada hasta msg de daño)
        hp_anim = self._get_hp_animado(self._hp_anim_j, pokemon, self._hp_snapshot_j)
        ratio = hp_anim / max(1, pokemon.hp_max)
        self._texto('HP', x + 12, y + 52, 'small', COLOR_TEXT_MUTED)
        self._dibujar_barra_hp(x + 35, y + 55, w - 80, 10, ratio)
        self._texto(f'{int(hp_anim)}/{pokemon.hp_max}', x + w - 75, y + 50, 'small', self._color_hp(ratio))

        # Equipo (Pokéballs)
        self._texto('Equipo:', x + 12, y + 76, 'small', COLOR_TEXT_MUTED)
        for i, p in enumerate(equipo):
            pb_cx = x + 75 + i * 22
            pb_cy = y + 84
            self._dibujar_pokeball(pb_cx, pb_cy, r=7, vivo=p.esta_vivo())

    def dibujar_sprites(self, poke_ia, poke_jugador):
        tipo_ia = poke_ia.tipos[0] if poke_ia.tipos else 'Normal'
        tipo_j = poke_jugador.tipos[0] if poke_jugador.tipos else 'Normal'
        sprite_ia = cargar_sprite(poke_ia.nombre, es_espalda=False, tipo=tipo_ia, tamaño=(210, 210))
        sprite_j = cargar_sprite(poke_jugador.nombre, es_espalda=True, tipo=tipo_j, tamaño=(240, 240))
        ticks = pygame.time.get_ticks()
        # Rival arriba-derecha / jugador abajo-izquierda (pie sobre plataforma ≈ y 212 / 445)
        self.surface.blit(sprite_ia.get_frame(ticks), (605, 2))
        self.surface.blit(sprite_j.get_frame(ticks), (105, 205))

    def dibujar_panel_acciones(self, pokemon_jugador, modo, seleccion, modo_cambio_idx=None, equipo=None):
        """Panel inferior con diálogo, movimientos y botones."""
        px, py, pw, ph = 0, 480, SCREEN_WIDTH, 120

        self._dibujar_panel((px, py, pw, ph), _PANEL_BG, border=False, radius=0)
        pygame.draw.line(self.surface, _PANEL_BD, (px, py), (px + pw, py), 1)

        if modo == 'luchar':
            # Grilla 2x2 de movimientos
            mx_mouse, my_mouse = pygame.mouse.get_pos()
            for i, mov in enumerate(pokemon_jugador.movimientos[:4]):
                col = i % 2
                fila = i // 2
                bx = px + 10 + col * 240
                by = py + 10 + fila * 50
                bw, bh = 225, 42
                self._mov_rects[i] = pygame.Rect(bx, by, bw, bh)

                # Highlight: seleccionado por teclado o hover de ratón
                hover = self._mov_rects[i].collidepoint(mx_mouse, my_mouse)
                bg = _BTN_SEL if (i == seleccion or hover) else _BTN_BG
                self._dibujar_panel((bx, by, bw, bh), bg, border_color=_PANEL_BD)

                # Nombre movimiento
                self._texto(mov.nombre.replace('_', ' '), bx + 8, by + 4, 'normal', COLOR_WHITE)

                # Tipo con color
                tc = TIPO_COLORES.get(mov.tipo, (100, 100, 100))
                pygame.draw.rect(self.surface, tc, (bx + 8, by + 24, 55, 12), border_radius=3)
                self._texto(mov.tipo[:7], bx + 10, by + 25, 'tiny', COLOR_WHITE)

                # PP
                pp_col = COLOR_HP_LOW if mov.pp == 0 else (COLOR_HP_MID if mov.pp <= mov.pp_max // 3 else COLOR_TEXT_MUTED)
                self._texto(f'PP {mov.pp}/{mov.pp_max}', bx + bw - 75, by + 4, 'small', pp_col)

                # Categoría
                self._texto(mov.categoria[:3].upper(), bx + bw - 75, by + 24, 'tiny', COLOR_TEXT_MUTED)

        elif modo in ('cambiar', 'cambio_forzado') and equipo:
            # Mostrar equipo para cambio
            self._cambio_rects = []
            mx_mouse, my_mouse = pygame.mouse.get_pos()
            for i, p in enumerate(equipo):
                bx = px + 10 + i * 120
                by = py + 10
                bw, bh = 110, 100
                rect = pygame.Rect(bx, by, bw, bh)
                self._cambio_rects.append(rect)

                hover = rect.collidepoint(mx_mouse, my_mouse) and p.esta_vivo()
                if not p.esta_vivo():
                    bg = _BTN_DEAD
                elif i == modo_cambio_idx or hover:
                    bg = _BTN_SEL
                else:
                    bg = _BTN_BG

                self._dibujar_panel((bx, by, bw, bh), bg, border_color=_PANEL_BD)
                self._texto(p.nombre[:10], bx + 5, by + 5, 'small', COLOR_WHITE if p.esta_vivo() else (80, 80, 80))

                ratio = p.hp / max(1, p.hp_max)
                self._dibujar_barra_hp(bx + 5, by + 25, bw - 10, 8, ratio)
                self._texto(f'{p.hp}/{p.hp_max}', bx + 5, by + 38, 'tiny', self._color_hp(ratio) if p.esta_vivo() else (80, 80, 80))

                tipo = p.tipos[0] if p.tipos else 'Normal'
                tc = TIPO_COLORES.get(tipo, (100, 100, 100))
                pygame.draw.rect(self.surface, tc, (bx + 5, by + 55, 45, 10), border_radius=2)
                self._texto(tipo[:5], bx + 7, by + 56, 'tiny', COLOR_WHITE)

    def dibujar_botones_modo(self, modo):
        """Botones Luchar / Cambiar en la esquina derecha."""
        if modo == 'cambio_forzado':
            # Ocultar botones y mostrar aviso de cambio obligatorio
            self._btn_luchar_rect  = pygame.Rect(0, 0, 0, 0)
            self._btn_cambiar_rect = pygame.Rect(0, 0, 0, 0)
            bx = SCREEN_WIDTH - 215
            by = 490
            self._dibujar_panel((bx, by, 205, 30), (110, 20, 20))
            self._texto('¡Elige tu Pokémon!', bx + 10, by + 7, 'small', (255, 180, 180))
            return

        bx = SCREEN_WIDTH - 170
        by = 490
        mx, my = pygame.mouse.get_pos()

        self._btn_luchar_rect  = pygame.Rect(bx,      by, 75, 30)
        self._btn_cambiar_rect = pygame.Rect(bx + 85, by, 75, 30)

        # Botón Luchar
        hover_l = self._btn_luchar_rect.collidepoint(mx, my)
        bg_l = _BTN_SEL if (modo == 'luchar' or hover_l) else _BTN_BG
        self._dibujar_panel(self._btn_luchar_rect, bg_l, border_color=_PANEL_BD)
        self._texto('Luchar', bx + 8, by + 7, 'small', COLOR_WHITE)

        # Botón Cambiar
        hover_c = self._btn_cambiar_rect.collidepoint(mx, my)
        bg_c = _BTN_SEL if (modo == 'cambiar' or hover_c) else _BTN_BG
        self._dibujar_panel(self._btn_cambiar_rect, bg_c, border_color=_PANEL_BD)
        self._texto('Cambiar', bx + 93, by + 7, 'small', COLOR_WHITE)

    def dibujar_log(self, mensajes):
        """Caja de diálogo con últimos mensajes."""
        lx, ly, lw, lh = 385, 480, 410, 115
        self._dibujar_panel((lx, ly, lw, lh), COLOR_PANEL_DARK)
        ultimos = mensajes[-4:] if len(mensajes) > 4 else mensajes
        for i, msg in enumerate(ultimos):
            self._texto(msg, lx + 8, ly + 8 + i * 24, 'small', COLOR_TEXT)

    def dibujar_dialogo(self, mensaje):
        """Caja de diálogo de pantalla completa inferior — un mensaje a la vez."""
        px, py, pw, ph = 0, 480, SCREEN_WIDTH, 120
        self._dibujar_panel((px, py, pw, ph), _PANEL_BG, border=False, radius=0)
        pygame.draw.line(self.surface, _PANEL_BD, (px, py), (px + pw, py), 2)

        # Texto del mensaje
        surf = self.fonts['normal'].render(str(mensaje), True, COLOR_WHITE)
        self.surface.blit(surf, (40, py + 44))

        # Indicador parpadeante ▼
        if (pygame.time.get_ticks() // 550) % 2 == 0:
            ind = self.fonts['small'].render('▼  Pulsa cualquier tecla', True, COLOR_TEXT_MUTED)
            self.surface.blit(ind, (SCREEN_WIDTH - ind.get_width() - 18, py + ph - 22))

    def dibujar_indicador_ia(self, nivel_ia):
        nombres = {1: 'IA: Aleatorio', 2: 'IA: Heurístico', 3: 'IA: Minimax'}
        txt = nombres.get(nivel_ia, 'IA: ?')
        self._dibujar_panel((SCREEN_WIDTH - 160, 5, 155, 22), _PANEL_BG, border_color=_PANEL_BD)
        self._texto(txt, SCREEN_WIDTH - 155, 8, 'small', _PANEL_BD)

    def dibujar_resultado(self, ganador):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.surface.blit(overlay, (0, 0))

        cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
        self._dibujar_panel((cx - 200, cy - 70, 400, 140), _HUD_BG, radius=12, border_color=_PANEL_BD)

        if ganador == 'jugador':
            msg = '¡Victoria!'
            color = COLOR_HP_HIGH
        elif ganador == 'ia':
            msg = '¡Derrota!'
            color = COLOR_HP_LOW
        else:
            msg = '¡Empate!'
            color = COLOR_TEXT

        self._texto(msg, cx, cy - 40, 'title', color, centrado=True)
        self._texto('Presiona ENTER para volver al menú', cx, cy + 10, 'small', COLOR_TEXT_MUTED, centrado=True)

    def render(self, estado_batalla, nivel_ia, modo, seleccion_mov,
               modo_cambio_idx=None, mensajes=None, ganador=None,
               mensaje_dialogo=None):
        poke_ia   = estado_batalla['ia']['activo']
        poke_j    = estado_batalla['jugador']['activo']
        equipo_j  = estado_batalla['jugador']['equipo']
        equipo_ia = estado_batalla['ia']['equipo']

        self.dibujar_fondo()
        self.dibujar_sprites(poke_ia, poke_j)
        self.dibujar_hud_enemigo(poke_ia, equipo=equipo_ia)
        self.dibujar_hud_jugador(poke_j, equipo_j)

        if mensaje_dialogo is not None:
            # Modo diálogo: un mensaje a la vez, sin botones de acción
            self.dibujar_dialogo(mensaje_dialogo)
        else:
            # Modo input: panel de movimientos/cambio + botones
            self.dibujar_panel_acciones(
                poke_j, modo, seleccion_mov,
                modo_cambio_idx=modo_cambio_idx,
                equipo=equipo_j
            )
            self.dibujar_botones_modo(modo)

        self.dibujar_indicador_ia(nivel_ia)
        if ganador:
            self.dibujar_resultado(ganador)
