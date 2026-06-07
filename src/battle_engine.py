import json
import os
import random
import copy

from config import DAMAGE_K, DAMAGE_SCALE
from src.pokemon import Pokemon, cargar_pokemon

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'pokemon_data.json')

_efectividad_cache = None

def _get_efectividad():
    global _efectividad_cache
    if _efectividad_cache is None:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _efectividad_cache = data['tipo_efectividad']
    return _efectividad_cache


def calcular_efectividad(tipo_mov, tipos_defensor):
    tabla = _get_efectividad()
    mult = 1.0
    fila = tabla.get(tipo_mov, {})
    for t in tipos_defensor:
        mult *= fila.get(t, 1.0)
    return mult


class BattleEngine:
    def __init__(self, equipo_jugador, equipo_ia):
        # Cada equipo es una lista de Pokemon
        self.equipos = {
            'jugador': equipo_jugador,
            'ia': equipo_ia,
        }
        self.activos = {
            'jugador': 0,
            'ia': 0,
        }
        self.log = []          # mensajes del turno
        self.turno = 0
        # True cuando el Pokémon activo del jugador se debilitó y debe elegir sustituto
        self.necesita_cambio_jugador = False

    def pokemon_activo(self, lado):
        idx = self.activos[lado]
        return self.equipos[lado][idx]

    def calcular_daño(self, atacante, defensor, movimiento):
        if movimiento.poder == 0:
            return 0
        atk = atacante.get_ataque_efectivo(movimiento.categoria)
        defv = defensor.get_defensa_efectiva(movimiento.categoria)
        vel_op = defensor.get_velocidad_efectiva()
        base = movimiento.poder

        damage = ((atk / max(1, defv)) * base - vel_op * DAMAGE_K) * DAMAGE_SCALE
        damage = max(1, damage)

        efectividad = calcular_efectividad(movimiento.tipo, defensor.tipos)
        damage *= efectividad

        # STAB (Same Type Attack Bonus)
        if movimiento.tipo in atacante.tipos:
            damage *= 1.5

        # Quemadura reduce daño físico a la mitad
        if atacante.estado == 'quemar' and movimiento.categoria == 'Fisico':
            damage *= 0.5

        return int(damage), efectividad

    def aplicar_efecto(self, usuario, objetivo, efecto):
        if efecto is None:
            return []
        msgs = []
        prob = efecto.get('probabilidad', 1.0)
        if random.random() > prob:
            return msgs
        tipo_efecto = efecto['tipo']

        if tipo_efecto in ('quemar', 'paralizar', 'congelar', 'envenenar', 'envenenar_grave'):
            if objetivo.estado is None:
                objetivo.estado = tipo_efecto
                msgs.append(f"{objetivo.nombre} ahora está {tipo_efecto}!")
        elif tipo_efecto == 'dormir':
            if objetivo.estado is None:
                objetivo.estado = 'dormir'
                objetivo.turnos_dormido = random.randint(2, 5)
                msgs.append(f"{objetivo.nombre} se quedó dormido!")
        elif tipo_efecto == 'confundir':
            # Estado volátil paralelo: convive con quemar/paralizar/etc.
            if objetivo.turnos_confundido <= 0:
                objetivo.turnos_confundido = random.randint(2, 5)
                msgs.append(f"¡{objetivo.nombre} fue confundido!")
        elif tipo_efecto == 'bajar_spdef':
            objetivo.mod_spdef = max(0.25, objetivo.mod_spdef * 0.75)
            msgs.append(f"La Def. Esp. de {objetivo.nombre} bajó!")
        elif tipo_efecto == 'subir_atk':
            usuario.mod_atk = min(4.0, usuario.mod_atk * 2.0)
            msgs.append(f"¡El Ataque de {usuario.nombre} subió mucho!")
        elif tipo_efecto == 'subir_vel':
            usuario.mod_vel = min(4.0, usuario.mod_vel * 2.0)
            msgs.append(f"¡La Velocidad de {usuario.nombre} subió mucho!")
        elif tipo_efecto == 'subir_spatk':
            usuario.mod_spatk = min(4.0, usuario.mod_spatk * 2.0)
            msgs.append(f"¡El At. Esp. de {usuario.nombre} subió mucho!")
        elif tipo_efecto == 'drenar_hp':
            objetivo.tiene_drenadoras = True
            msgs.append(f"{objetivo.nombre} fue atrapado por Drenadoras!")
        elif tipo_efecto == 'drenar_hp_rival':
            objetivo.tiene_maldicion = True
            msgs.append(f"{objetivo.nombre} recibió una maldición!")
        elif tipo_efecto == 'proteger':
            # Decay: la probabilidad de éxito cae 1/3 por cada uso consecutivo.
            # 1ª vez: 100 %, 2ª: 33 %, 3ª: 11 %, 4ª: ~4 %, etc.
            n = usuario.contador_proteccion
            exito_prob = 1.0 / (3 ** n)
            if random.random() < exito_prob:
                usuario.protegido = True
                usuario.contador_proteccion = n + 1
                msgs.append(f"{usuario.nombre} se protegió!")
            else:
                usuario.contador_proteccion = 0
                msgs.append(f"¡Pero {usuario.nombre} falló al protegerse!")

        return msgs

    def ejecutar_ataque(self, atacante, defensor, movimiento):
        msgs = []
        if not movimiento.tiene_pp():
            msgs.append(f"{atacante.nombre} no tiene PP para {movimiento.nombre}!")
            return msgs

        movimiento.usar()

        # Si NO es un movimiento de Proteccion, se rompe la cadena de protección
        # (Pokémon real: cualquier acción que no sea Protect resetea el decay).
        es_proteccion = movimiento.efecto is not None and movimiento.efecto.get('tipo') == 'proteger'
        if not es_proteccion:
            atacante.contador_proteccion = 0

        # Verificar precisión
        if random.random() * 100 > movimiento.precision:
            msgs.append(f"¡El ataque de {atacante.nombre} falló!")
            return msgs

        # Si el defensor está protegido
        if defensor.protegido and movimiento.poder > 0:
            msgs.append(f"¡{defensor.nombre} se protegió del ataque!")
            return msgs

        if movimiento.poder > 0:
            daño, efectividad = self.calcular_daño(atacante, defensor, movimiento)
            defensor.recibir_daño(daño)
            msgs.append(f"{atacante.nombre} usó {movimiento.nombre}! ({daño} daño)")
            if efectividad > 1.0:
                msgs.append("¡Es muy eficaz!")
            elif efectividad < 1.0 and efectividad > 0:
                msgs.append("No es muy eficaz...")
            elif efectividad == 0:
                msgs.append("¡No afecta!")

            if movimiento.efecto:
                msgs += self.aplicar_efecto(atacante, defensor, movimiento.efecto)
        else:
            msgs.append(f"{atacante.nombre} usó {movimiento.nombre}!")
            if movimiento.efecto:
                msgs += self.aplicar_efecto(atacante, atacante if movimiento.efecto['tipo'].startswith('subir') or movimiento.efecto['tipo'] == 'proteger' else defensor, movimiento.efecto)

        return msgs

    def ejecutar_turno(self, accion_jugador, accion_ia):
        """
        accion_jugador / accion_ia: dict con claves:
          {'tipo': 'movimiento', 'indice': i}
          {'tipo': 'cambio', 'indice': i}
        """
        self.turno += 1
        self.log = []
        msgs = []

        pj = self.pokemon_activo('jugador')
        pi = self.pokemon_activo('ia')

        # Reiniciar protección
        pj.reiniciar_turno()
        pi.reiniciar_turno()

        # Resolver cambios primero
        cambio_j = accion_jugador['tipo'] == 'cambio'
        cambio_i = accion_ia['tipo'] == 'cambio'

        if cambio_j:
            self.cambiar_pokemon('jugador', accion_jugador['indice'])
            pj = self.pokemon_activo('jugador')
            msgs.append(f"__SWITCH_J:{accion_jugador['indice']}")
            msgs.append(f"Jugador cambió a {pj.nombre}!")
        if cambio_i:
            self.cambiar_pokemon('ia', accion_ia['indice'])
            pi = self.pokemon_activo('ia')
            msgs.append(f"__SWITCH_IA:{accion_ia['indice']}")
            msgs.append(f"IA cambió a {pi.nombre}!")

        # Si ambos atacan, el orden se decide por (1) prioridad del movimiento, (2) velocidad
        if not cambio_j and not cambio_i:
            vel_j = pj.get_velocidad_efectiva()
            vel_i = pi.get_velocidad_efectiva()

            # Prioridad del movimiento elegido (Proteccion = +4, resto = 0 por defecto)
            idx_j = accion_jugador['indice']
            idx_i = accion_ia['indice']
            prio_j = pj.movimientos[idx_j].prioridad if idx_j < len(pj.movimientos) else 0
            prio_i = pi.movimientos[idx_i].prioridad if idx_i < len(pi.movimientos) else 0

            if prio_j > prio_i:
                orden = [('jugador', accion_jugador), ('ia', accion_ia)]
            elif prio_i > prio_j:
                orden = [('ia', accion_ia), ('jugador', accion_jugador)]
            elif vel_j > vel_i:
                orden = [('jugador', accion_jugador), ('ia', accion_ia)]
            elif vel_i > vel_j:
                orden = [('ia', accion_ia), ('jugador', accion_jugador)]
            else:
                # Empate de velocidad → orden aleatorio
                orden = random.choice([
                    [('jugador', accion_jugador), ('ia', accion_ia)],
                    [('ia', accion_ia), ('jugador', accion_jugador)],
                ])

            for lado, accion in orden:
                atacante = self.pokemon_activo(lado)
                defensor = self.pokemon_activo('ia' if lado == 'jugador' else 'jugador')

                if not atacante.esta_vivo():
                    continue

                # Confusión: tick + posible auto-daño antes de chequear estado principal
                puede_conf, msgs_conf = atacante.chequear_confusion()
                if msgs_conf:
                    sentinel = '__HP_UPDATE_J__' if lado == 'jugador' else '__HP_UPDATE_IA__'
                    msgs.append(sentinel)
                    msgs += msgs_conf
                if not puede_conf:
                    if not atacante.esta_vivo():
                        msgs.append(f"¡{atacante.nombre} se debilitó!")
                        nombre_nuevo = self._auto_cambiar_si_necesario(lado)
                        if nombre_nuevo and lado == 'ia':
                            msgs.append(f"__SWITCH_IA:{self.activos['ia']}")
                            msgs.append(f"¡El rival envía a {nombre_nuevo}!")
                    continue

                if not atacante.puede_moverse():
                    msgs.append(f"{atacante.nombre} no puede moverse!")
                    continue

                idx_mov = accion['indice']
                movs_validos = [m for m in atacante.movimientos if m.tiene_pp()]
                if not movs_validos:
                    sentinel_atk = '__HP_UPDATE_J__' if lado == 'jugador' else '__HP_UPDATE_IA__'
                    msgs.append(sentinel_atk)
                    atacante.hp = 0
                    msgs.append(f"¡{atacante.nombre} no tiene más movimientos y no puede continuar!")
                    nombre_nuevo = self._auto_cambiar_si_necesario(lado)
                    if nombre_nuevo and lado == 'ia':
                        msgs.append(f"__SWITCH_IA:{self.activos['ia']}")
                        msgs.append(f"¡El rival envía a {nombre_nuevo}!")
                    continue

                if idx_mov < len(atacante.movimientos) and atacante.movimientos[idx_mov].tiene_pp():
                    mov = atacante.movimientos[idx_mov]
                else:
                    mov = random.choice(movs_validos)

                # Centinela: congela animación HP del defensor hasta que aparezca este msg
                sentinel = '__HP_UPDATE_IA__' if lado == 'jugador' else '__HP_UPDATE_J__'
                msgs.append(sentinel)
                msgs += self.ejecutar_ataque(atacante, defensor, mov)

                if not defensor.esta_vivo():
                    msgs.append(f"¡{defensor.nombre} se debilitó!")
                    lado_def = 'ia' if lado == 'jugador' else 'jugador'
                    nombre_nuevo = self._auto_cambiar_si_necesario(lado_def)
                    if nombre_nuevo:
                        # Centinela: cambia el sprite del rival JUSTO cuando aparece el mensaje
                        msgs.append(f"__SWITCH_IA:{self.activos['ia']}")
                        msgs.append(f"¡El rival envía a {nombre_nuevo}!")

        elif not cambio_j and cambio_i:
            # Solo jugador ataca
            puede_conf, msgs_conf = pj.chequear_confusion()
            if msgs_conf:
                msgs.append('__HP_UPDATE_J__')
                msgs += msgs_conf
            if puede_conf and pj.puede_moverse():
                idx_mov = accion_jugador['indice']
                movs_validos = [m for m in pj.movimientos if m.tiene_pp()]
                if movs_validos:
                    mov = pj.movimientos[idx_mov] if idx_mov < len(pj.movimientos) and pj.movimientos[idx_mov].tiene_pp() else random.choice(movs_validos)
                    msgs.append('__HP_UPDATE_IA__')
                    msgs += self.ejecutar_ataque(pj, pi, mov)
                    if not pi.esta_vivo():
                        msgs.append(f"¡{pi.nombre} se debilitó!")
                        nombre_nuevo = self._auto_cambiar_si_necesario('ia')
                        if nombre_nuevo:
                            msgs.append(f"__SWITCH_IA:{self.activos['ia']}")
                            msgs.append(f"¡El rival envía a {nombre_nuevo}!")
                else:
                    msgs.append('__HP_UPDATE_J__')
                    pj.hp = 0
                    msgs.append(f"¡{pj.nombre} no tiene más movimientos y no puede continuar!")
                    self._auto_cambiar_si_necesario('jugador')
            elif not pj.esta_vivo():
                msgs.append(f"¡{pj.nombre} se debilitó!")
                self._auto_cambiar_si_necesario('jugador')

        elif cambio_j and not cambio_i:
            # Solo IA ataca
            puede_conf, msgs_conf = pi.chequear_confusion()
            if msgs_conf:
                msgs.append('__HP_UPDATE_IA__')
                msgs += msgs_conf
            if puede_conf and pi.puede_moverse():
                idx_mov = accion_ia['indice']
                movs_validos = [m for m in pi.movimientos if m.tiene_pp()]
                if movs_validos:
                    mov = pi.movimientos[idx_mov] if idx_mov < len(pi.movimientos) and pi.movimientos[idx_mov].tiene_pp() else random.choice(movs_validos)
                    msgs.append('__HP_UPDATE_J__')
                    msgs += self.ejecutar_ataque(pi, pj, mov)
                    if not pj.esta_vivo():
                        msgs.append(f"¡{pj.nombre} se debilitó!")
                        self._auto_cambiar_si_necesario('jugador')
                else:
                    msgs.append('__HP_UPDATE_IA__')
                    pi.hp = 0
                    msgs.append(f"¡{pi.nombre} no tiene más movimientos y no puede continuar!")
                    nombre_nuevo = self._auto_cambiar_si_necesario('ia')
                    if nombre_nuevo:
                        msgs.append(f"__SWITCH_IA:{self.activos['ia']}")
                        msgs.append(f"¡El rival envía a {nombre_nuevo}!")
            elif not pi.esta_vivo():
                msgs.append(f"¡{pi.nombre} se debilitó!")
                nombre_nuevo = self._auto_cambiar_si_necesario('ia')
                if nombre_nuevo:
                    msgs.append(f"__SWITCH_IA:{self.activos['ia']}")
                    msgs.append(f"¡El rival envía a {nombre_nuevo}!")

        # Efectos de estado al final del turno
        for lado in ('jugador', 'ia'):
            poke = self.pokemon_activo(lado)
            if poke.esta_vivo():
                estado_msgs = poke.aplicar_efecto_estado()
                if estado_msgs:
                    sentinel = '__HP_UPDATE_J__' if lado == 'jugador' else '__HP_UPDATE_IA__'
                    msgs.append(sentinel)
                    msgs += estado_msgs
                if not poke.esta_vivo():
                    msgs.append(f"¡{poke.nombre} se debilitó por el estado!")
                    nombre_nuevo = self._auto_cambiar_si_necesario(lado)
                    if nombre_nuevo:
                        if lado == 'ia':
                            msgs.append(f"__SWITCH_IA:{self.activos['ia']}")
                        msgs.append(f"¡El rival envía a {nombre_nuevo}!")

        self.log = msgs
        return msgs

    def _auto_cambiar_si_necesario(self, lado):
        equipo = self.equipos[lado]
        actual = self.activos[lado]
        if not equipo[actual].esta_vivo():
            if lado == 'ia':
                for i, p in enumerate(equipo):
                    if p.esta_vivo():
                        # Copy-on-write: el Pokémon del banco puede estar compartido
                        # con otro clon del engine; clonarlo antes de mutarlo.
                        nuevo = p.clone()
                        equipo[i] = nuevo
                        self.activos[lado] = i
                        nuevo.reset_volatiles()   # entra limpio (sin mods ni confusión)
                        return nuevo.nombre        # nombre del nuevo activo
            else:  # jugador debe elegir manualmente
                if any(p.esta_vivo() for p in equipo):
                    self.necesita_cambio_jugador = True
        return None

    def cambiar_pokemon(self, lado, indice):
        equipo = self.equipos[lado]
        if 0 <= indice < len(equipo) and equipo[indice].esta_vivo():
            # Copy-on-write: el Pokémon entrante puede estar compartido con otro clon
            nuevo = equipo[indice].clone()
            equipo[indice] = nuevo
            self.activos[lado] = indice
            nuevo.reset_volatiles()   # entra limpio (sin mods ni confusión)
            return True
        return False

    def batalla_terminada(self):
        for lado in ('jugador', 'ia'):
            if all(not p.esta_vivo() for p in self.equipos[lado]):
                return True
        return False

    def ganador(self):
        ia_ko = all(not p.esta_vivo() for p in self.equipos['ia'])
        j_ko  = all(not p.esta_vivo() for p in self.equipos['jugador'])
        if ia_ko and j_ko:
            return 'empate'
        if ia_ko:
            return 'jugador'
        if j_ko:
            return 'ia'
        return None

    def get_estado(self):
        """Retorna un dict con el estado actual para los agentes."""
        return {
            'jugador': {
                'equipo': self.equipos['jugador'],
                'activo_idx': self.activos['jugador'],
                'activo': self.pokemon_activo('jugador'),
            },
            'ia': {
                'equipo': self.equipos['ia'],
                'activo_idx': self.activos['ia'],
                'activo': self.pokemon_activo('ia'),
            },
            'turno': self.turno,
        }

    def clonar(self):
        """Crea una copia "casi" profunda del engine para simulaciones.
        Solo se clonan los Pokémon ACTIVOS — los únicos que pueden mutarse
        durante `ejecutar_turno`. Los del banco se comparten por referencia
        (copy-on-write): si más tarde uno del banco se activa por cambio o
        auto-cambio, `cambiar_pokemon` / `_auto_cambiar_si_necesario` lo clonan
        en ese momento para garantizar aislamiento."""
        nuevo = BattleEngine.__new__(BattleEngine)
        eq_j = list(self.equipos['jugador'])
        eq_i = list(self.equipos['ia'])
        idx_j = self.activos['jugador']
        idx_i = self.activos['ia']
        eq_j[idx_j] = eq_j[idx_j].clone()
        eq_i[idx_i] = eq_i[idx_i].clone()
        nuevo.equipos = {'jugador': eq_j, 'ia': eq_i}
        nuevo.activos = dict(self.activos)
        nuevo.log = []
        nuevo.turno = self.turno
        nuevo.necesita_cambio_jugador = self.necesita_cambio_jugador
        return nuevo
