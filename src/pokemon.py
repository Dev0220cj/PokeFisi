import json
import os
import random

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'pokemon_data.json')

_data_cache = None

def _get_data():
    global _data_cache
    if _data_cache is None:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            _data_cache = json.load(f)
    return _data_cache


class Movimiento:
    def __init__(self, nombre, datos):
        self.nombre = nombre
        self.tipo = datos['tipo']
        self.categoria = datos['categoria']
        self.poder = datos['poder']
        self.precision = datos['precision']
        self.pp = datos['pp']
        self.pp_max = datos['pp']
        self.efecto = datos.get('efecto')
        # Prioridad del movimiento: Proteccion (efecto 'proteger') siempre actúa primero
        if self.efecto and self.efecto.get('tipo') == 'proteger':
            self.prioridad = 4
        else:
            self.prioridad = datos.get('prioridad', 0)

    def tiene_pp(self):
        return self.pp > 0

    def usar(self):
        if self.pp > 0:
            self.pp -= 1

    def clone(self):
        """Copia rápida — comparte `efecto` (dict de solo lectura tras crear el Movimiento)."""
        nuevo = Movimiento.__new__(Movimiento)
        nuevo.nombre = self.nombre
        nuevo.tipo = self.tipo
        nuevo.categoria = self.categoria
        nuevo.poder = self.poder
        nuevo.precision = self.precision
        nuevo.pp = self.pp
        nuevo.pp_max = self.pp_max
        nuevo.efecto = self.efecto
        nuevo.prioridad = self.prioridad
        return nuevo

    def to_dict(self):
        return {
            'nombre': self.nombre,
            'tipo': self.tipo,
            'categoria': self.categoria,
            'poder': self.poder,
            'precision': self.precision,
            'pp': self.pp,
            'pp_max': self.pp_max,
            'efecto': self.efecto,
        }

    @classmethod
    def from_dict(cls, d):
        datos = {
            'tipo': d['tipo'],
            'categoria': d['categoria'],
            'poder': d['poder'],
            'precision': d['precision'],
            'pp': d['pp_max'],
            'efecto': d.get('efecto'),
        }
        mov = cls(d['nombre'], datos)
        mov.pp = d['pp']
        return mov


class Pokemon:
    def __init__(self, nombre, tipos, hp, ataque, defensa, sp_atk, sp_def, velocidad, movimientos):
        self.nombre = nombre
        self.tipos = tipos
        self.hp_max = hp
        self.hp = hp
        self.ataque = ataque
        self.defensa = defensa
        self.sp_atk = sp_atk
        self.sp_def = sp_def
        self.velocidad = velocidad
        self.movimientos = movimientos  # list of Movimiento

        self.estado = None          # None / "quemar" / "paralizar" / "congelar" / "envenenar" / "envenenar_grave" / "dormir"
        self.turnos_dormido = 0
        self.turnos_confundido = 0  # estado volátil paralelo (no ocupa slot de `estado`)
        self.contador_veneno = 0    # para envenenamiento grave (toxicidad creciente)
        self.tiene_drenadoras = False
        self.tiene_maldicion = False
        self.protegido = False
        self.contador_proteccion = 0  # usos consecutivos de Proteccion (decay 1/3^n)

        # Modificadores de stat (multiplicadores)
        self.mod_atk = 1.0
        self.mod_spatk = 1.0
        self.mod_vel = 1.0
        self.mod_spdef = 1.0

    def esta_vivo(self):
        return self.hp > 0

    def recibir_daño(self, cantidad):
        cantidad = max(0, int(cantidad))
        self.hp = max(0, self.hp - cantidad)

    def curar(self, cantidad):
        self.hp = min(self.hp_max, self.hp + int(cantidad))

    def puede_moverse(self):
        if self.estado == 'dormir':
            if self.turnos_dormido <= 0:
                self.estado = None
                return True
            self.turnos_dormido -= 1
            return False
        if self.estado == 'paralizar':
            if random.random() < 0.25:
                return False
        if self.estado == 'congelar':
            if random.random() < 0.80:
                return False
            else:
                self.estado = None
        return True

    def chequear_confusion(self):
        """Tick de confusión antes de un ataque. Devuelve (puede_actuar, mensajes).
        Decrementa el contador y, si está confundido, hay 33% de auto-daño."""
        if self.turnos_confundido <= 0:
            return True, []

        self.turnos_confundido -= 1
        if self.turnos_confundido == 0:
            return True, [f"¡{self.nombre} salió de su confusión!"]

        msgs = [f"{self.nombre} está confundido..."]
        if random.random() < 0.33:
            # Auto-daño: forma simplificada de la fórmula física, sin STAB ni efectividad
            auto_dmg = max(1, int(self.ataque / max(1, self.defensa) * 40 * 0.25))
            self.recibir_daño(auto_dmg)
            msgs.append(f"¡Se hirió a sí mismo en su confusión! ({auto_dmg} daño)")
            return False, msgs
        return True, msgs

    def reset_volatiles(self):
        """Resetea estados volátiles y modificadores. Se llama al entrar a batalla.
        NO toca el estado principal (quemar/paralizar/etc.) ni HP."""
        self.mod_atk = 1.0
        self.mod_spatk = 1.0
        self.mod_vel = 1.0
        self.mod_spdef = 1.0
        self.turnos_confundido = 0
        self.tiene_drenadoras = False
        self.tiene_maldicion = False
        self.protegido = False
        self.contador_proteccion = 0

    def aplicar_efecto_estado(self):
        """Aplica daño de estado al final del turno. Retorna mensaje."""
        msgs = []
        if self.estado == 'quemar':
            dmg = max(1, self.hp_max // 8)
            self.recibir_daño(dmg)
            msgs.append(f"{self.nombre} sufre quemadura ({dmg} daño).")
        elif self.estado == 'envenenar':
            dmg = max(1, self.hp_max // 8)
            self.recibir_daño(dmg)
            msgs.append(f"{self.nombre} sufre veneno ({dmg} daño).")
        elif self.estado == 'envenenar_grave':
            self.contador_veneno += 1
            dmg = max(1, (self.hp_max * self.contador_veneno) // 16)
            self.recibir_daño(dmg)
            msgs.append(f"{self.nombre} sufre veneno grave ({dmg} daño).")

        if self.tiene_drenadoras:
            dmg = max(1, self.hp_max // 8)
            self.recibir_daño(dmg)
            msgs.append(f"{self.nombre} es drenado por Drenadoras ({dmg} daño).")

        if self.tiene_maldicion:
            dmg = max(1, self.hp_max // 4)
            self.recibir_daño(dmg)
            msgs.append(f"{self.nombre} sufre la maldición ({dmg} daño).")

        return msgs

    def get_ataque_efectivo(self, categoria):
        if categoria == 'Fisico':
            return int(self.ataque * self.mod_atk)
        return int(self.sp_atk * self.mod_spatk)

    def get_defensa_efectiva(self, categoria):
        if categoria == 'Fisico':
            return max(1, self.defensa)
        return max(1, int(self.sp_def * self.mod_spdef))

    def get_velocidad_efectiva(self):
        vel = self.velocidad * self.mod_vel
        if self.estado == 'paralizar':
            vel *= 0.5
        return max(1, int(vel))

    def reiniciar_turno(self):
        self.protegido = False

    def clone(self):
        """Copia rápida del estado completo (incluye `protegido`, que `to_dict` no serializa).
        Comparte `tipos` (lista nunca mutada) por referencia."""
        nuevo = Pokemon.__new__(Pokemon)
        nuevo.nombre = self.nombre
        nuevo.tipos = self.tipos
        nuevo.hp_max = self.hp_max
        nuevo.hp = self.hp
        nuevo.ataque = self.ataque
        nuevo.defensa = self.defensa
        nuevo.sp_atk = self.sp_atk
        nuevo.sp_def = self.sp_def
        nuevo.velocidad = self.velocidad
        nuevo.movimientos = [m.clone() for m in self.movimientos]
        nuevo.estado = self.estado
        nuevo.turnos_dormido = self.turnos_dormido
        nuevo.turnos_confundido = self.turnos_confundido
        nuevo.contador_veneno = self.contador_veneno
        nuevo.tiene_drenadoras = self.tiene_drenadoras
        nuevo.tiene_maldicion = self.tiene_maldicion
        nuevo.protegido = self.protegido
        nuevo.contador_proteccion = self.contador_proteccion
        nuevo.mod_atk = self.mod_atk
        nuevo.mod_spatk = self.mod_spatk
        nuevo.mod_vel = self.mod_vel
        nuevo.mod_spdef = self.mod_spdef
        return nuevo

    def to_dict(self):
        return {
            'nombre': self.nombre,
            'tipos': self.tipos,
            'hp': self.hp,
            'hp_max': self.hp_max,
            'ataque': self.ataque,
            'defensa': self.defensa,
            'sp_atk': self.sp_atk,
            'sp_def': self.sp_def,
            'velocidad': self.velocidad,
            'movimientos': [m.to_dict() for m in self.movimientos],
            'estado': self.estado,
            'turnos_dormido': self.turnos_dormido,
            'turnos_confundido': self.turnos_confundido,
            'contador_veneno': self.contador_veneno,
            'tiene_drenadoras': self.tiene_drenadoras,
            'tiene_maldicion': self.tiene_maldicion,
            'contador_proteccion': self.contador_proteccion,
            'mod_atk': self.mod_atk,
            'mod_spatk': self.mod_spatk,
            'mod_vel': self.mod_vel,
            'mod_spdef': self.mod_spdef,
        }

    @classmethod
    def from_dict(cls, d):
        movs = [Movimiento.from_dict(m) for m in d['movimientos']]
        p = cls(
            d['nombre'], d['tipos'], d['hp_max'],
            d['ataque'], d['defensa'], d['sp_atk'], d['sp_def'], d['velocidad'],
            movs
        )
        p.hp = d['hp']
        p.estado = d.get('estado')
        p.turnos_dormido = d.get('turnos_dormido', 0)
        p.turnos_confundido = d.get('turnos_confundido', 0)
        p.contador_veneno = d.get('contador_veneno', 0)
        p.tiene_drenadoras = d.get('tiene_drenadoras', False)
        p.tiene_maldicion = d.get('tiene_maldicion', False)
        p.contador_proteccion = d.get('contador_proteccion', 0)
        p.mod_atk = d.get('mod_atk', 1.0)
        p.mod_spatk = d.get('mod_spatk', 1.0)
        p.mod_vel = d.get('mod_vel', 1.0)
        p.mod_spdef = d.get('mod_spdef', 1.0)
        return p


def cargar_pokemon(nombre):
    data = _get_data()
    pdata = data['pokemon'].get(nombre)
    if pdata is None:
        raise ValueError(f"Pokemon '{nombre}' no encontrado en los datos.")
    moves_pool = data['moves_pool']
    movimientos = []
    for m_nombre in pdata['movimientos']:
        if m_nombre in moves_pool:
            movimientos.append(Movimiento(m_nombre, moves_pool[m_nombre]))
    return Pokemon(
        nombre=nombre,
        tipos=pdata['tipo'],
        hp=pdata['hp'],
        ataque=pdata['ataque'],
        defensa=pdata['defensa'],
        sp_atk=pdata['sp_atk'],
        sp_def=pdata['sp_def'],
        velocidad=pdata['velocidad'],
        movimientos=movimientos,
    )


def lista_nombres_pokemon():
    data = _get_data()
    return list(data['pokemon'].keys())
