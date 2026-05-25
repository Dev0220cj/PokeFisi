# Pantalla
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 600
FPS = 60
TITLE = "Pokefisi"

# Colores (paleta oscura)
COLOR_BG = (26, 26, 46)
COLOR_PANEL = (15, 52, 96)
COLOR_PANEL_DARK = (10, 10, 26)
COLOR_BORDER = (55, 138, 221)
COLOR_TEXT = (181, 212, 244)
COLOR_TEXT_MUTED = (133, 183, 235)
COLOR_HP_HIGH = (99, 153, 34)
COLOR_HP_MID = (186, 117, 23)
COLOR_HP_LOW = (226, 75, 74)
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)

# Batalla
BATTLE_TEAM_SIZE = 4
MINIMAX_DEPTH = 2
MINIMAX_SAMPLES = 3            # rollouts por par (accion_ia, accion_j) en la RAÍZ del árbol
MINIMAX_SAMPLES_DEEP = 1       # rollouts en niveles profundos (1 con CRN: las iteraciones
                               # consecutivas no son independientes — consumen dados sucesivos
                               # del mismo stream seedado, así que promediarlas no reduce ruido real)
GENETIC_POPULATION = 20
GENETIC_GENERATIONS = 50
GENETIC_BATTLES_PER_EVAL = 15  # batallas por individuo (más = menos ruido en el fitness)
DAMAGE_K     = 0.1
DAMAGE_SCALE = 0.25   # factor global de escala de daño (1.0 = sin escala, 0.25 = ~4-6 turnos por combate)

# Sprites gen 5 Pokémon Showdown
SPRITE_BASE_URL = "https://play.pokemonshowdown.com/sprites/gen5ani/"
SPRITE_BACK_URL = "https://play.pokemonshowdown.com/sprites/gen5ani-back/"
