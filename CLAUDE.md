# CLAUDE.md — Pokefisi

Simulador de combates Pokémon desarrollado para el curso de IA en la UNMSM.
Stack: **Python 3.13 + Pygame 2.6.1 + Pillow** (Windows).

Para ejecutar: `py main.py`

---

## Estructura del proyecto

```
Poke-Fisi-final/
├── main.py                  # Punto de entrada y bucle principal (state machine)
├── config.py                # Constantes globales
├── data/
│   └── pokemon_data.json    # Stats, moves pool, tabla de efectividad de tipos
├── src/
│   ├── pokemon.py           # Clases Pokemon y Movimiento
│   ├── battle_engine.py     # Motor de batalla (BattleEngine)
│   ├── ai_agent.py          # Los 3 agentes IA (Random, Heurístico, Minimax)
│   └── genetic_algorithm.py # Optimizador genético de pesos del Minimax
├── ui/
│   ├── sprites.py           # Carga y caché de sprites animados GIF
│   ├── intro_screen.py      # Pantalla de bienvenida
│   ├── menu_screen.py       # Menú principal
│   ├── config_screen.py     # Selección de equipo y dificultad
│   └── battle_screen.py     # Pantalla de combate
└── assets/
    ├── sprites/             # Cache local de GIFs descargados
    └── sounds/              # Música (intro.ogg / intro.mp3)
```

---

## Constantes clave (`config.py`)

| Constante | Valor | Descripción |
|---|---|---|
| `SCREEN_WIDTH/HEIGHT` | 1024×600 | Resolución de ventana |
| `FPS` | 60 | Tasa de frames |
| `BATTLE_TEAM_SIZE` | 4 | Pokémon por equipo |
| `MINIMAX_DEPTH` | 2 | Profundidad por defecto del Minimax |
| `GENETIC_POPULATION` | 20 | Tamaño de población del AG |
| `GENETIC_GENERATIONS` | 50 | Generaciones del AG |
| `DAMAGE_K` | 0.2 | Factor velocidad del defensor en fórmula de daño (subido de 0.1 — premia estrategias que consideran velocidad como el Minimax con `speed_ratio`) |
| `DAMAGE_SCALE` | 0.25 | Escala global de daño (~4–6 turnos por combate) |
| `SPRITE_BASE_URL` | pokemonshowdown.com/sprites/gen5ani/ | Sprites frontales |
| `SPRITE_BACK_URL` | pokemonshowdown.com/sprites/gen5ani-back/ | Sprites de espalda |

---

## Fórmula de daño

```python
damage = ((atk / max(1, defv)) * base_power - vel_oponente * DAMAGE_K) * DAMAGE_SCALE
damage = max(1, damage)
damage *= efectividad          # 0.25 / 0.5 / 1.0 / 2.0 / 4.0
if tipo_mov in atacante.tipos:
    damage *= 1.5              # STAB
```

- `atk` = `ataque` (Físico) o `sp_atk × mod_spatk` (Especial)
- `defv` = `defensa` (Físico) o `sp_def × mod_spdef` (Especial)
- La velocidad del defensor resta levemente al daño (simula evasión)
- Sin varianza aleatoria ni críticos (actualmente no implementados)

---

## Estados y efectos

### Estado principal (`Pokemon.estado`)
Solo uno a la vez: `None / "quemar" / "paralizar" / "congelar" / "envenenar" / "envenenar_grave" / "dormir"`.

Aplicados al final del turno (`aplicar_efecto_estado`):
- **Quemar**: -1/8 HP máx por turno
- **Envenenar**: -1/8 HP máx por turno
- **Envenenar grave**: daño creciente `(hp_max × contador_veneno) / 16`
- **Dormir**: inmoviliza `turnos_dormido` turnos (asignado al recibir el efecto)
- **Paralizar**: 25 % de no poder moverse; reduce velocidad efectiva al 50 %
- **Congelar**: 80 % de no poder moverse; 20 % de chance de descongelarse

### Estados volátiles (paralelos al estado principal)
- **Confusión** (`turnos_confundido`): tick por turno; 33 % de auto-daño con fórmula `ataque / defensa × 40 × 0.25`; coexiste con el estado principal
- **Drenadoras** (`tiene_drenadoras`): -1/8 HP máx por turno
- **Maldición** (`tiene_maldicion`): -1/4 HP máx por turno
- **Protegido** (`protegido`): bloquea daño ese turno; resetea al inicio del siguiente. Tiene **decay**: la probabilidad de éxito al usar Proteccion consecutivamente es `1 / 3^n` (n = usos consecutivos previos). El contador `contador_proteccion` se resetea al usar otro movimiento o al cambiar de Pokémon.

### Prioridad de movimientos
- Protección (`efecto.tipo == 'proteger'`) → `prioridad = 4`
- Resto de movimientos → `prioridad = 0` (o el valor en JSON si se especifica)
- Orden de ejecución: prioridad → velocidad → desempate aleatorio

### Reset al cambio de Pokémon
`reset_volatiles()` se llama al entrar un Pokémon al campo (cambio manual o automático). Resetea:
- Modificadores de stat (`mod_atk`, `mod_spatk`, `mod_vel`, `mod_spdef` → 1.0)
- Confusión, Drenadoras, Maldición, Protegido
- **NO** toca el estado principal ni el HP

---

## Motor de batalla (`src/battle_engine.py`)

### Flujo de un turno (`ejecutar_turno`)
1. Resolver cambios de Pokémon primero (sin gastar turno)
2. Si ambos atacan: ordenar por prioridad → velocidad → azar
3. Para cada atacante, en orden:
   - `chequear_confusion()` → posible auto-daño o salida de confusión
   - `puede_moverse()` → check dormir/parálisis/congelar
   - Si supera ambos checks: ejecutar movimiento
   - Si el defensor cae: auto-cambio o fin de batalla
4. Aplicar daños de estado al final (`aplicar_efecto_estado`)
5. Chequear condición de victoria (`ganador()`)

### `ganador()` — empate correcto
```python
ia_ko = all(not p.esta_vivo() for p in self.equipos['ia'])
j_ko  = all(not p.esta_vivo() for p in self.equipos['jugador'])
if ia_ko and j_ko:  # chequeo antes que los individuales
    return 'empate'
```

### Sentinelas en el log de mensajes
`ejecutar_turno` devuelve una lista de strings. Algunos son invisibles para el diálogo pero disparan efectos visuales en `battle_screen.py`:

| Sentinel | Efecto |
|---|---|
| `__HP_UPDATE_J__` | Actualiza barra de HP del jugador |
| `__HP_UPDATE_IA__` | Actualiza barra de HP de la IA |
| `__SWITCH_J:<idx>` | Cambia sprite activo del jugador |
| `__SWITCH_IA:<idx>` | Cambia sprite activo de la IA |

`battle_screen` hace `freeze_hp()` antes de ejecutar el turno y `unfreeze_hp_j/ia()` cuando procesa el sentinel correspondiente, desacoplando la animación del estado real del engine.

### Clonado para Minimax
`engine.clonar()` usa `to_dict()` / `from_dict()` para una copia profunda aislada del estado, sin referencias compartidas.

---

## Agentes IA (`src/ai_agent.py`)

### Nivel 1 — `RandomAgent`
Elige aleatoriamente entre movimientos con PP > 0 y cambios posibles.

### Nivel 2 — `HeuristicAgent`
Heurística básica basada **literalmente** en diferencia de HP (según enunciado del curso).

Implementa una función formal de evaluación:

```python
def evaluar_hp_diff(self, equipo_ia, equipo_j):
    return sum(p.hp for p in equipo_ia) - sum(p.hp for p in equipo_j)
```

**Algoritmo de decisión (1-step lookahead con HP_diff)**:
- Calcula `hp_diff_actual = evaluar_hp_diff(...)` al inicio del turno.
- Para cada movimiento con PP: `score = hp_diff_actual + dano_predicho`, donde `dano_predicho = min(poder × efectividad × 0.25, defensor.hp)` — proxy crudo, capado al HP real del rival ("no se puede quitar más HP del que tiene").
- Para cada cambio posible (solo si HP propio < 30 %): `score = hp_diff_actual + bonus_cambio`, donde el bonus estima HP futuros preservados por traer un Pokémon fresco y resistente.
- Elige la acción con mayor `score` → la que maximiza la diferencia de HP esperada.

**El daño predicho es solo el modelo de decisión del agente**. El daño REAL aplicado al Pokémon lo calcula el engine con su fórmula completa (ATK/DEF, STAB, velocidad, quemadura). Esa diferencia entre "modelo del agente" y "realidad del engine" es exactamente lo que el Nivel 3 (Minimax) puede explotar.

**Lo que NO considera**:
- STAB ni precision (deliberadamente — son sofisticaciones del Nv3)
- Velocidad, PP, estados, KO awareness, ATK/DEF reales del engine
- Lookahead a más de 1 turno

### Nivel 3 — `MinimaxAgent`
Minimax con poda alfa-beta, profundidad configurable (por defecto 2).
- **Maximin**: para cada acción de la IA, asume que el jugador responde óptimamente (peor caso)
- Función de evaluación compuesta (4 factores con pesos configurables):
  - `hp_ratio`: diferencia de HP total normalizado
  - `vivos_ratio`: diferencia de Pokémon vivos
  - `type_advantage`: mejor efectividad de tipo del activo, normalizada a [-1/3, 1] (no [-1,1] — ver nota abajo)
  - `speed_ratio`: ventaja de velocidad del activo
- Pesos por defecto: `[0.4, 0.3, 0.2, 0.1]`
- Si no hay `_engine` en el estado, cae a `HeuristicAgent` como fallback

---

## Algoritmo Genético (`src/genetic_algorithm.py`)

Optimiza los 4 pesos del `MinimaxAgent` maximizando el win rate contra `RandomAgent`.

- **Representación**: vector de 4 floats normalizados (suman 1)
- **Fitness**: win rate en `n_batallas=5` simuladas
- **Selección**: torneo de tamaño k=3
- **Cruzamiento**: un punto de corte aleatorio
- **Mutación**: gaussiana (prob=0.2, sigma=0.1) + renormalización
- **Elitismo**: el mejor individuo pasa directamente a la siguiente generación
- Guarda/carga pesos en JSON con historial de fitness

---

## Sprites (`ui/sprites.py`)

Los sprites son GIFs animados descargados de Pokémon Showdown y cacheados localmente.

### Pipeline de carga
1. Buscar en caché local (`assets/sprites/`)
2. Si no existe, descargar de `SPRITE_BASE_URL` / `SPRITE_BACK_URL`
3. Extraer frames con **Pillow** a tamaño nativo (~96×96 px)
4. Escalar cada frame con `_scale_pixel_art(frame, tamaño)` — aplica `scale2x` iterativo (dobla preservando bordes) hasta cerca del tamaño objetivo, luego `smoothscale` para el ajuste fino. Mucho más nítido que `smoothscale` directo desde ~96 px

### Tamaños y posiciones en batalla
- Sprite rival (frontal): 210×210 px, posición `(605, 2)`
- Sprite jugador (espalda): 240×240 px, posición `(105, 205)`

### Tamaño en intro
- Charizard: 220×220 px, posición `(SCREEN_WIDTH × 0.68, SCREEN_HEIGHT × 0.24)`

---

## Pantalla de intro (`ui/intro_screen.py`)

Fases de animación:
- 0–1 s: fade-in del fondo + título
- 0–1.8 s: sprite Charizard entra desde la derecha (ease-out cuadrático)
- 1.5 s+: texto parpadeante "Presiona cualquier tecla"
- Barra de progreso dorada durante los 5 s de duración
- Auto-avance a MENU tras 5 s; cualquier tecla/click avanza inmediatamente

---

## Datos (`data/pokemon_data.json`)

- **22 Pokémon** con stats completos (HP, ataque, defensa, sp_atk, sp_def, velocidad, tipos, movimientos)
- **~45 movimientos** con: tipo, categoría, poder, precisión, PP y objeto `efecto` opcional
- **Tabla `tipo_efectividad`**: multiplicadores para todos los pares tipo-atacante × tipo-defensor

### Formato de `efecto` en un movimiento
```json
{
  "tipo": "quemar",          // nombre del efecto
  "probabilidad": 0.3,       // 0.0–1.0
  "objetivo": "rival"        // "rival" | "usuario"
}
```
Tipos de efecto implementados: `quemar`, `paralizar`, `envenenar`, `envenenar_grave`, `dormir`, `congelar`, `confundir`, `drenadoras`, `maldicion`, `proteger`, `subir_atk`, `subir_spatk`, `subir_vel`, `subir_spdef`, `bajar_atk`, `bajar_def`, `curar`.

---

## Problemas conocidos (pendientes de corregir)

Estos bugs fueron identificados en la revisión del flujo de batalla pero aún no han sido corregidos:

| # | Área | Descripción |
|---|---|---|
| 4 | `battle_screen` | `_ganador_pendiente` no se resetea correctamente en estado `TEAM_SELECT_IA` |
| 5/6 | `genetic_algorithm` | Importaciones muertas (`numpy`, `copy`) y función `_crear_equipos_aleatorios` no usada |
| 7 | `battle_screen` | Variables `esperando_turno` / `delay_turno` declaradas pero nunca usadas |
| 10 | `pokemon.py` | `puede_moverse()` tiene side effects (modifica `estado`, `turnos_dormido`) — debería ser puro o renombrarse |
| 12 | `battle_engine` | Mensaje "no puede moverse" inconsistente en ramas de ataque individual |
| 14 | `battle_engine` | Lógica de objetivo de efecto usa prefijo de string hardcodeado (`startswith('subir')`) |
| ~~15~~ | `battle_engine` | **Resuelto**: sin PP → Pokémon KO inmediato (decisión de diseño: PP como recurso estratégico) |
| 16 | `battle_engine` | Sin varianza de daño ni golpes críticos |
| ~~18~~ | `battle_engine` | **Decisión de diseño**: Cometa Draco no tiene efecto secundario en este juego (`"efecto": null`) |
| 21–22 | `HeuristicAgent` | Aún no considera drenadoras/protección al máximo, ignora estado propio en buffs (#19, #20 corregidos) |
| 30–33 | `GeneticOptimizer` | Sin paralelismo, sin elitismo múltiple, sin diversidad explícita (#28, #29 corregidos; #23, #24, #26, #27 corregidos en evaluar) |

---

## Correcciones aplicadas (historial)

### Confusión real (antes era no-op)
- `Pokemon`: campo `turnos_confundido`, método `chequear_confusion()` con auto-daño 33 %
- `BattleEngine.aplicar_efecto`: ahora asigna `turnos_confundido = randint(2,5)` en lugar de solo loggear
- `ejecutar_turno`: llama `chequear_confusion()` antes de `puede_moverse()` en todas las ramas

### Empate detectado correctamente
- `ganador()`: chequea `ia_ko and j_ko` explícitamente antes de los chequeos individuales

### Protección funciona para Pokémon lentos
- `Movimiento.prioridad`: campo inferido del tipo de efecto (`proteger` → prioridad 4)
- `ejecutar_turno`: ordena por prioridad antes que por velocidad

### Modificadores de stat no persisten al cambio
- `reset_volatiles()`: nuevo método en `Pokemon`; llamado en `cambiar_pokemon()` y `_auto_cambiar_si_necesario()`

### HeuristicAgent simplificado al Nivel 2 del enunciado
- En una iteración previa, el Heurístico tenía KO awareness (#19, `KO_BONUS=10000` con `estimar_dano`) y cambio estratégico avanzado (#20, cambio por matchup malo además de HP bajo). Esto lo convertía en un agente casi tan fuerte como el Minimax depth=2 (~50/50), violando la progresión jerárquica que el enunciado pide.
- **Decisión**: revertir a una heurística básica según el enunciado:
  - Score de movimiento: `poder × efectividad` (sin STAB, sin precisión, sin estimar daño real — fiel al enunciado "heurística básica")
  - Cambio solo si HP < 30 %, con score por HP del candidato + vulnerabilidad de tipo simple
  - Sin KO awareness, sin matchup awareness avanzado, sin considerar velocidad
- Funciones helper `estimar_dano`, `mejor_efectividad`, `amenaza_real` eliminadas (ya no se usan)
- Resultado: progresión jerárquica restaurada — Random 4 % < Heurístico 96 % vs Random; Heurístico 41 % < Minimax 58 % vs Heurístico (150 batallas)

### Minimax con expectiminimax sobre rollouts (#25)
- `MINIMAX_SAMPLES = 3` en `config.py`; `MinimaxAgent(n_samples=...)` configurable
- `_rollout_promedio()`: cada par (accion_ia, accion_j) se simula N veces y se promedia la evaluación
- Reduce el ruido por aleatoriedad del engine (precisión, status, parálisis, confusión, descongelo)

### Optimizaciones de rendimiento del Minimax (A + B + G + A')
- **A**: `n_samples=3` (configurable, `MINIMAX_SAMPLES`) en la **raíz** del árbol; `n_samples_deep=2` (`MINIMAX_SAMPLES_DEEP`) en niveles profundos. Antes era 1 en profundo, pero degradaba ~13 puntos de win rate vs Heurístico por ruido en el lookahead. 2 es el punto dulce ruido/velocidad.
- **B**: nuevos métodos `Pokemon.clone()` y `Movimiento.clone()` con copia directa de atributos. Sustituyen el roundtrip `to_dict()/from_dict()` que era ~3.5× más lento.
- **G**: `BattleEngine.clonar()` solo clona los **Pokémon activos** (los únicos mutables en un turno). Los del banco se comparten por referencia. `cambiar_pokemon()` y `_auto_cambiar_si_necesario()` aplican **copy-on-write**: clonan al entrante justo antes de mutarlo.
- **Move ordering descartado** (lo que era "F"): un experimento de ordenar acciones por `estimar_dano × precision` antes de explorarlas para mejorar la poda alfa-beta. Aceleraba ~28 % pero **degradaba ~10 puntos** la calidad vs Heurístico. Razón: combinado con sampling ruidoso, la poda con cotas inexactas eliminaba ramas que en realidad eran las mejores. Se revirtió a `_acciones_posibles` en `minimax()` y `elegir_accion()`.
- Resultado medido (vs baseline 11.4 s/b Minimax-Random, 66 % Minimax-Heurístico):
  - `clonar()` 71 μs → 5.6 μs (~12×)
  - Minimax vs Random: 88-95 % win rate a ~2.2 s/batalla (vs 11.4 s) — **~5× más rápido**
  - Minimax vs Heurístico: 65 % win rate a ~1.6 s/batalla — **calidad preservada** con ~7× speedup

### Función `evaluar()` enriquecida (#23, #24, #26, #27)
- Antes la función usaba 4 factores: `hp_ratio`, `vivos_ratio`, `type_advantage`, `speed_ratio`.
- Ahora 7 factores (suman 1.0 por convención):
  - `hp_ratio`, `vivos_ratio`, `type_advantage`, `speed_ratio` (idem antes)
  - `estado_ratio`: gravedad de estados principales (dormir/congelar/quemar/etc.) — rival - propio. Cada estado se mapea a un score 0..1 vía `gravedad_estado()` (más grave si quedan más turnos de sueño o más contadores de veneno grave).
  - `dot_ratio`: DoT residual (drenadoras, maldición, confusión) — rival - propio, vía `dot_residual()`.
  - `pp_ratio`: PP del activo (propio - rival) — un Pokémon sin PP es inútil.
- Todos los factores apuntan a [-1, 1], con una excepción: `type_advantage` tiene rango real **[-1/3, 1]**. Fórmula: `(mejor_ventaja - 1.0) / 3.0`, donde el denominador 3 hace que ×4 (superefectivo máximo) → +1 exacto, y neutral (×1) → 0. El mínimo -1/3 ocurre cuando todos los movimientos del activo son inmunes (0×) o sin PP. La asimetría es intencional: centrar en neutral=0 es más intuitivo que forzar simetría a costa de que neutro sea negativo.
- Pesos default ajustados a mano: `[0.35, 0.25, 0.15, 0.05, 0.10, 0.07, 0.03]`. Mantienen dominante a `hp_ratio` y `vivos_ratio` (lo más importante en el corto plazo) y reparten el resto entre los nuevos factores.
- Constante `N_FACTORES_EVAL = 7` en `ai_agent.py` (usada por el GeneticOptimizer para crear individuos del tamaño correcto).
- Resultado: Minimax vs Heurístico subió de ~51 % (4 factores) a ~53-60 % (7 factores con pesos default).

### Intento de optimización con GA (descartado)
- Se intentó usar el `GeneticOptimizer` para encontrar pesos óptimos contra `HeuristicAgent`.
- Dos configuraciones probadas (n_batallas=5 y n_batallas=15, pop=6-8, 6-8 gens): **ambas produjeron pesos peores que los defaults a mano**.
- Diagnóstico: el espacio de pesos es traicionero. El GA converge prematuramente a un óptimo local que gana 100 % en su sample pero generaliza mal. Con n=15 el CI para `p=1.0` sigue en [0.78, 1.0] — no es suficiente para evitar overfitting.
- `simular_batalla()` y `_jugar_batalla()` ahora aceptan parámetro `rival='heuristic'|'random'` (antes era hardcoded a Random — bug #30 parcialmente corregido), incluyen manejo de `necesita_cambio_jugador` para evitar atascos.
- Si se quiere retomar: necesitaría n_batallas≥30, pop≥12, gens≥20 (probablemente 4-6 horas en serie), o paralelización (#30-#33 pendientes).

### Proteccion con decay (#8b)
- Antes Proteccion era 100 % éxito siempre → la IA spammeaba el movimiento haciéndose invencible
- `Pokemon.contador_proteccion`: nuevo campo, persistido en `to_dict`/`from_dict` para el clonado del Minimax
- `BattleEngine.aplicar_efecto` (caso `'proteger'`): probabilidad de éxito `1 / 3^n`; en éxito incrementa contador, en fallo lo resetea
- `BattleEngine.ejecutar_ataque`: si el movimiento ejecutado **no** es Proteccion, resetea el contador (cualquier otra acción rompe la cadena)
- `reset_volatiles()`: incluye el contador al cambiar de Pokémon
- `HeuristicAgent._score_movimiento`: ahora pondera Proteccion por su valor esperado (`base / 3^n`), evitando que el heurístico la repita ciegamente
- Verificado empíricamente: 3000 muestras dan empírica vs teórica = 100/100, 32/33, 12/11, 2/4 %

### GA con fitness más estable y justo (#28, #29)
- `GENETIC_BATTLES_PER_EVAL = 15` por defecto (antes 5) → menos varianza en el fitness
- `generar_escenarios(n)`: lista de tuplas `(nombres_j, nombres_i)` reproducibles
- `evolucionar()`: todos los individuos de la **misma generación** se evalúan contra los **mismos escenarios** (fairness); cambian entre generaciones (presión selectiva renovada)
- Elitismo re-evalúa al campeón con los escenarios nuevos para no arrastrar fitness "suertudos"
