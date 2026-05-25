# Notas del proyecto Pokefisi — análisis y decisiones de diseño

> Este documento complementa `CLAUDE.md` (que cubre la arquitectura y constantes del código). Aquí se registran **decisiones de diseño**, **observaciones empíricas** y **análisis de resultados** que son relevantes para futuras iteraciones o para el informe del curso. Todo lo aquí escrito proviene de experimentos y conversaciones de desarrollo, no de la documentación general del proyecto.

---

## 1. Interpretación del enunciado del curso

El proyecto pide **tres niveles de agentes IA**:

| Nivel | Descripción del enunciado | Implementación |
|---|---|---|
| **1** | Comportamiento aleatorio (baseline) | `RandomAgent` |
| **2** | Heurística básica basada en **diferencia de HP** | `HeuristicAgent` con `poder × ef × STAB × precision` |
| **3** | Heurística **avanzada** (función compuesta normalizada) + ajuste manual + GA + **Minimax con poda alfa-beta y profundidad configurable** | `MinimaxAgent` con `evaluar()` de 7 factores |

**Punto clave que se malinterpretó inicialmente**: el "Nivel 3" del enunciado no son dos cosas separadas (un heurístico avanzado + un Minimax). Es **una sola cosa**: el Minimax usa la heurística avanzada como su función `evaluar()` para puntuar hojas del árbol de búsqueda. Los pesos de esa función son los que se optimizan a mano y/o con el GA.

---

## 2. Análisis empírico: por qué el Minimax NO arrasa al Heurístico

### El fenómeno observado

Después de implementar todo, el benchmark muestra:

```
Random      vs Heurístico  →  Heurístico ~90 % (clarísimo)
Random      vs Minimax     →  Minimax    ~92 % (clarísimo)
Heurístico  vs Minimax     →  Minimax    ~56-62 % (margen estrecho)
```

El margen Minimax vs Heurístico es **menor de lo esperado intuitivamente** (cabría esperar 70-80 %). Esto **no es un bug**, es un resultado real con explicación profunda.

### Causa raíz: la calidad de la `evaluar()` limita el lookahead

El Minimax a depth=2 simula dos turnos hacia adelante y luego invoca `evaluar()` sobre el estado futuro. Toda la "inteligencia" del lookahead **se filtra por la calidad de esa función**. Si `evaluar()` no captura un concepto, el lookahead no compensa esa ceguera.

La `evaluar()` actual tiene 7 factores (hp, vivos, type, vel, estado, dot, pp) pero es lineal — no captura **interacciones** entre factores (por ejemplo, "estoy paralizado Y soy más lento" debería puntuar mucho peor que la suma lineal de ambos, pero la función actual lo trata como suma).

### Iteración descartada: Heurístico "avanzado"

En una iteración temprana, el `HeuristicAgent` tenía:
- KO awareness con `estimar_dano()` (bonus 10000 si el daño esperado ≥ HP rival)
- Cambio estratégico (cambia si matchup ≤ 0.5 o el rival tiene super-efectivos)
- Escala unificada (% HP rival × 100)

Con esto, el Heurístico subió de 40 % vs Random a **77 %**. Pero el costo fue: **vs Minimax también subió a ~50/50**, eliminando la progresión jerárquica.

**Decisión tomada**: revertir el Heurístico a su forma básica (HP + cambio simple por HP < 30 %). Esto restaura la progresión Random < Heurístico < Minimax y cumple con el enunciado del curso, que pide Nivel 2 "basado en diferencia de HP".

**Lección de IA de juegos**: este fenómeno tiene nombre — **horizon effect**. Cuando una heurística captura ya la decisión óptima local, el lookahead no aporta ventaja. Resultado válido para el informe del curso como demostración empírica de un principio teórico.

---

## 3. Análisis empírico: paradojas del benchmark

### 3.1 ¿Por qué Random vs Minimax tarda MÁS que Heurístico vs Minimax?

Datos típicos (N=100, equipos 3 vs 3):

| Match | Tiempo / batalla |
|---|---|
| Random vs Minimax | ~1.32–1.47 s |
| Heurístico vs Minimax | ~1.07 s |

**Diferencia ~25 % a favor del Heurístico** (más rápido). Contraintuitivo porque el Heurístico es "más inteligente".

**Explicación**: el tiempo del agente Random es despreciable (microsegundos). El cuello de botella es el Minimax, que tarda ~constante por turno (~6-7k simulaciones internas). Lo que varía es **cuántos turnos dura la batalla**:

- **Heurístico** elige consistentemente el movimiento de máximo daño → batallas cortas (10-15 turnos)
- **Random** tira movimientos débiles, Proteccion en momentos absurdos, no remata KOs → batallas largas (25-40 turnos)

Tiempo total ≈ `turnos × costo_minimax_por_turno`. Random alarga la batalla → más cómputo total.

### 3.2 ¿Por qué Random a veces gana MÁS al Minimax que al Heurístico?

Fenómeno observado en varios benchmarks: Random gana 14 % a Minimax pero solo 10 % al Heurístico (o variantes similares). Es **inconsistente con la jerarquía Random < Heurístico < Minimax** que se observa en agregado.

**Causa raíz**: **opponent modeling problem**.

El Minimax usa **maximin pesimista**: asume que el rival juega óptimamente (worst case para él). Pero Random NO juega óptimamente:

1. Minimax calcula "si yo hago X, el rival va a responder con la mejor jugada Y para él"
2. Pero Random no elige Y, elige al azar
3. Minimax termina **defendiéndose de jugadas que nunca van a pasar** (cambia de Pokémon, usa Proteccion preventiva, etc.) — turnos desperdiciados

El **Heurístico** no tiene este problema: solo busca máximo daño greedy. Contra Random, greedy ES óptimo porque Random no responde estratégicamente.

**Capa adicional — sampling estocástico**: el Minimax promedia 3 rollouts en raíz, 2 en profundidad. Si esos rollouts producen casos pesimistas (rival paraliza, congela), el Minimax sobreestima la amenaza y juega aún más defensivo.

**Nombre académico del fenómeno**: `opponent modeling problem`. Algoritmos como **Counterfactual Regret Minimization (CFR)** lo resuelven modelando distribuciones de rivales en vez de un único rival óptimo.

**Conclusión**: el Minimax sigue siendo el mejor en promedio (vs Heurístico, vs Random en agregado), pero su modelo de rival lo penaliza levemente contra rivales muy sub-óptimos. Es un trade-off inherente al diseño maximin, no un bug.

---

## 4. Trampas conocidas y patrones a evitar

### 4.1 Los agentes NO detectan su propio activo muerto

`HeuristicAgent` y `MinimaxAgent` no manejan el caso "mi activo está muerto, debo cambiar". Devuelven una acción de movimiento normal. El game loop debe detectar `engine.necesita_cambio_jugador` y hacer el cambio manualmente (así lo hace `benchmark.py` líneas 102-108).

Si escribes un script de test ad-hoc y olvidas este manejo, la batalla se eternizará en timeout. Los win rates serán 0/0/N, con N empates.

### 4.2 El `to_dict()` de `Pokemon` NO incluye `protegido`

Es legacy. El nuevo `clone()` sí lo incluye. En la práctica no afectaba nada porque `reiniciar_turno()` lo resetea al inicio del siguiente turno, pero si alguna vez se usa `to_dict()/from_dict()` para guardar mid-turn, se perderá el flag.

### 4.3 El GA con `n_batallas` bajo produce overfitting severo

Experimento real: GA con `n_batallas=5` encontró pesos con fitness 1.0 (5/5) que generalizaban al 38 % en validación. Con `n_batallas=15` (default actual) sigue convergiendo a óptimos locales engañosos.

**Conclusión empírica**: el GeneticOptimizer **no es viable** con presupuesto razonable (~1 hora) para este problema. Los pesos default ajustados a mano (`PESOS_EVAL_DEFAULT`) son **mejores** que cualquier cosa que el GA encontró en múltiples corridas. Si se quiere retomar el GA en serio, hacen falta:

- `n_batallas ≥ 30` (para que el CI del fitness sea ±10 %)
- `pop ≥ 12` (para diversidad)
- `gens ≥ 20`
- **Paralelización** (bugs #30-#33 pendientes) — sin esto son 4-6 horas en serie

### 4.4 Move ordering con sampling es contraproducente

Se implementó "Opt F" (move ordering por `estimar_dano × precision` antes de explorar las acciones en alfa-beta). En teoría debe acelerar la poda. **Empíricamente degradaba 10 puntos la calidad** vs Heurístico, porque con valores ruidosos (sampling), las cotas alfa/beta inexactas eliminan ramas que en realidad eran las mejores. **Se revirtió.**

### 4.5 `n_samples_deep=1` degrada el lookahead

Por ahorrar tiempo, se probó hacer 1 solo rollout en niveles profundos del Minimax. Resultado: degradó ~13 puntos de win rate vs Heurístico (de 60 % a 47 %). Razón: la decisión "min" del rival simulado se basa en una sola tirada de dados ruidosa.

**Valor estable actual**: `MINIMAX_SAMPLES_DEEP = 2`. Compromiso ruido/velocidad.

---

## 5. Estado final del proyecto

### 5.1 Performance vs baseline

| Métrica | Baseline original | Estado actual | Mejora |
|---|---|---|---|
| Heurístico vs Random | 40 % | **96 %** | +56 pts |
| Minimax vs Random | 90 % | **92-94 %** | sin cambio |
| Minimax vs Heurístico | 66 % (n=50 ruidoso) | **58 %** (n=150 estable) | medida más confiable |
| Tiempo Minimax / batalla | 11.4 s | **~1.2 s** | **~9× speedup** |
| `clonar()` | 71 μs | **5.6 μs** | ~12× |

### 5.2 Optimizaciones aplicadas

Ver detalle en CLAUDE.md sección "Optimizaciones de rendimiento del Minimax":

- **A**: `n_samples=3` en raíz, `n_samples_deep=2` en profundo
- **B**: `Pokemon.clone()` / `Movimiento.clone()` directos (vs `to_dict/from_dict`)
- **G**: solo clonar activos en `BattleEngine.clonar()`, banco compartido con copy-on-write
- **A'**: separar `n_samples` raíz de `n_samples_deep`

Descartadas:
- **F** (move ordering): degradaba calidad

### 5.3 Función `evaluar()` del Minimax

7 factores en [-1, 1]:

```
[0] hp_ratio        diferencia de HP total normalizado
[1] vivos_ratio     diferencia de Pokémon vivos
[2] type_advantage  mejor efectividad ofensiva del activo
[3] speed_ratio     ventaja de velocidad
[4] estado_ratio    gravedad de estados (rival - propio)
[5] dot_ratio       drenadoras + maldición + confusión (rival - propio)
[6] pp_ratio        PP disponible del activo (propio - rival)
```

Pesos default ajustados a mano: `[0.35, 0.25, 0.15, 0.05, 0.10, 0.07, 0.03]`. Empíricamente **mejores que cualquier cosa que el GA encontró**.

---

## 6. Material para el informe del curso

Algunos hallazgos que pueden incluirse como análisis sofisticado:

### Sobre el horizon effect

> "Inicialmente diseñamos una heurística avanzada con KO awareness y cambio estratégico. Empíricamente, esto producía un win rate cercano al 50 % contra el Minimax depth=2, lo cual demuestra que **cuando la heurística captura ya la decisión óptima local, el lookahead no aporta ventaja significativa** (horizon effect). Restringimos el Nivel 2 a la heurística básica que pide el enunciado, obteniendo la progresión jerárquica esperada."

### Sobre el opponent modeling problem

> "Observamos que el Minimax (Nivel 3) ocasionalmente pierde más batallas contra Random (Nivel 1) que el Heurístico (Nivel 2). Esto **no es un bug**, sino una consecuencia directa del **opponent modeling problem**: el algoritmo maximin asume rival óptimo, por lo que toma decisiones defensivas innecesarias contra un rival aleatorio. El Heurístico, al ser puramente greedy, no sufre de esta sobre-defensividad. **El Minimax sigue siendo el mejor en promedio, pero su modelo de rival lo penaliza levemente contra rivales muy sub-óptimos**."

### Sobre el GA y la dificultad de optimización

> "Implementamos un GeneticOptimizer (población = 6-8, generaciones = 5-10, batallas/eval = 5-15). En múltiples corridas, los pesos descubiertos por el GA **resultaron peores que los pesos ajustados a mano** en validación con muestras grandes (N=60+). Diagnóstico: el espacio de pesos es traicionero y la métrica de fitness (win rate) tiene varianza alta. El GA converge prematuramente a óptimos locales que ganan en el sample de entrenamiento pero generalizan mal. **Este es un resultado válido y conocido en optimización evolutiva con fitness ruidoso**: la herramienta no siempre mejora soluciones bien diseñadas."

### Sobre la calidad de la `evaluar()`

> "El Minimax depth=2 muestra una mejora marginal (~10-15 puntos) sobre el Heurístico básico, no la mejora dramática que cabría esperar. La causa es que la función `evaluar()` es lineal y no captura interacciones entre factores. Por ejemplo, 'Pokémon paralizado Y lento' es mucho peor que la suma lineal de ambos factores. Una `evaluar()` más sofisticada (no-lineal, con términos cruzados, o incluso una red neuronal entrenada) podría aprovechar mejor el lookahead. Esto sugiere una dirección de mejora futura: **la profundidad del Minimax solo paga si la función de evaluación es lo bastante rica para discriminar estados sutiles del juego**."

---

## 7. Bugs pendientes (no corregidos)

Ver lista completa en CLAUDE.md sección "Problemas conocidos". Los más relevantes:

- **#15**: Sin Struggle cuando todos los movimientos quedan sin PP
- **#16**: Sin varianza de daño ni críticos (engine completamente determinista)
- **#18**: Cometa Draco no aplica reducción de SpAtk propia tras usarse
- **#21-#22**: HeuristicAgent (versión actual simple) no considera drenadoras/protección al máximo
- **#30-#33**: GA sin paralelismo, sin elitismo múltiple, sin diversidad explícita

---

*Última actualización: 2026-05-23*
