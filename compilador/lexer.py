"""
lexer.py - Fase 1 del proyecto: analisis lexico (version 2)

Que hace
--------
Recibe BYTES (de un JSON, de un JSON Schema o de un XML) y los parte en
tokens. Un token es:  (tipo, texto, inicio, fin)

Como esta armado
----------------
1. CLASES DE BYTES   Cada uno de los 256 bytes posibles pertenece a una clase
                     ("digito", "comilla", "espacio"...). Es el alfabeto.
2. TABLAS (AFD)      (estado, clase) -> estado siguiente. Son solo datos.
3. MOTOR             Un unico bucle que recorre los bytes consultando la tabla.
                     Sirve igual para JSON y para XML: solo cambia la tabla.

El motor trabaja "en streaming": se le pueden dar los bytes por bloques
(alimentar) y recuerda en que estado quedo entre un bloque y el siguiente.

Como correrlo
-------------
    python compilador/lexer.py                 -> ejemplos de JSON y de XML
    python compilador/lexer.py archivo.json    -> tokens de ese archivo
    python compilador/lexer.py archivo.xml     -> idem, con el lexer de XML
"""

import sys
from collections import namedtuple

Token = namedtuple("Token", "tipo texto inicio fin")


class ErrorLexico(Exception):
    """Un pedazo de la entrada no forma ningun token valido."""

    def __init__(self, mensaje, posicion):
        super().__init__("Error lexico en el byte %d: %s" % (posicion, mensaje))
        self.mensaje = mensaje
        self.posicion = posicion


class AFD:
    """Un automata finito determinista descrito solo con datos."""

    def __init__(self, nombre, clase, familias, aceptacion, ignorar,
                 frontera, descripcion, inicial="q0"):
        self.nombre = nombre
        self.clase = clase              # lista de 256 nombres de clase
        self.familias = familias        # {titulo: {(estado, clase): estado}}
        self.aceptacion = aceptacion    # {estado: tipo de token}
        self.ignorar = ignorar          # clases que se botan estando en q0
        self.frontera = frontera        # {tipo: clases que pueden venir despues}
        self.descripcion = descripcion  # {estado: explicacion en espanol}
        self.inicial = inicial
        # La tabla completa es la union de las tablas de cada familia.
        self.transiciones = {}
        for tabla in familias.values():
            for clave, destino in tabla.items():
                if clave in self.transiciones:
                    raise ValueError("No es determinista: %r repetida" % (clave,))
                self.transiciones[clave] = destino
        # Estados "inmediatos": de aceptacion, sin flechas de salida y sin
        # regla de frontera. Al llegar a ellos el token ya esta completo y
        # se puede emitir sin esperar el byte siguiente (por ejemplo "{").
        con_salida = {origen for (origen, _) in self.transiciones}
        self.inmediatos = {
            e for e, tipo in aceptacion.items()
            if e not in con_salida and tipo not in frontera
        }

    def estados(self):
        vistos = {self.inicial}
        for (origen, _), destino in self.transiciones.items():
            vistos.add(origen)
            vistos.add(destino)
        return vistos


# =====================================================================
# 1. JSON: CLASES DE BYTES (el alfabeto)
# =====================================================================
def _clases_json():
    c = ["invalido"] * 256                 # C0, C1, F5..FF nunca son UTF-8
    for b in range(0x00, 0x20):
        c[b] = "control"                   # prohibidos dentro de una cadena
    for b in range(0x20, 0x80):
        c[b] = "otro"                      # ASCII imprimible sin papel especial
    for b in (0x09, 0x0A, 0x0D):
        c[b] = "salto"                     # tabulador, salto de linea, retorno
    c[0x20] = "espacio"
    unicos = {
        "{": "llave_abre", "}": "llave_cierra",
        "[": "corchete_abre", "]": "corchete_cierra",
        ":": "dos_puntos", ",": "coma",
        '"': "comilla", "\\": "barra", "/": "diagonal",
        "-": "menos", "+": "mas", ".": "punto", "0": "cero",
        "E": "E_may",
    }
    for caracter, nombre in unicos.items():
        c[ord(caracter)] = nombre
    for d in "123456789":
        c[ord(d)] = "digito"
    # Estas letras tienen clase propia porque el automata las distingue:
    # a-f son digitos hexadecimales, y varias aparecen en true/false/null
    # y en los escapes (\b \f \n \r \t \u).
    for letra in "abcdeflnrstu":
        c[ord(letra)] = letra
    for letra in "ABCDF":
        c[ord(letra)] = "hex_may"
    # Bytes de un caracter UTF-8 de varios bytes (enie, tildes, emojis...)
    for b in range(0x80, 0xC0):
        c[b] = "cont"                      # byte de continuacion
    for b in range(0xC2, 0xE0):
        c[b] = "lider2"                    # empieza un caracter de 2 bytes
    for b in range(0xE0, 0xF0):
        c[b] = "lider3"                    # ... de 3 bytes
    for b in range(0xF0, 0xF5):
        c[b] = "lider4"                    # ... de 4 bytes
    return c


CLASE_JSON = _clases_json()

# Grupos de clases, para no repetir filas al escribir las tablas
SIMBOLOS = {"llave_abre", "llave_cierra", "corchete_abre", "corchete_cierra",
            "dos_puntos", "coma"}
DIG = {"cero", "digito"}                                   # 0-9
EXP = {"e", "E_may"}                                       # e, E
SIGNO = {"mas", "menos"}                                   # +, -
HEX = DIG | set("abcdef") | {"hex_may", "E_may"}           # 0-9 a-f A-F
ESCAPES = {"comilla", "barra", "diagonal", "b", "f", "n", "r", "t"}
# Todo lo que puede ir tal cual dentro de una cadena (un solo byte):
NORMAL = (set(CLASE_JSON[0x20:0x80]) | {"espacio"}) - {"comilla", "barra"}
DELIMITADORES = SIMBOLOS | {"espacio", "salto"}


def _desde(tabla, origen, clases, destino):
    """Agrega una flecha por cada clase del grupo."""
    for c in clases:
        tabla[(origen, c)] = destino


# =====================================================================
# 2. JSON: LAS TABLAS DE TRANSICION
# =====================================================================
# --- Simbolos de un solo byte -----------------------------------------
T_SIMBOLOS = {
    ("q0", "llave_abre"): "s1",
    ("q0", "llave_cierra"): "s2",
    ("q0", "corchete_abre"): "s3",
    ("q0", "corchete_cierra"): "s4",
    ("q0", "dos_puntos"): "s5",
    ("q0", "coma"): "s6",
}

# --- Numeros: el diagrama q0..q8 --------------------------------------
T_NUMERO = {
    ("q0", "menos"): "q1",
    ("q0", "cero"): "q2",
    ("q0", "digito"): "q3",
    ("q1", "cero"): "q2",
    ("q1", "digito"): "q3",
    ("q2", "punto"): "q4",
    ("q3", "punto"): "q4",
}
_desde(T_NUMERO, "q3", DIG, "q3")
_desde(T_NUMERO, "q4", DIG, "q5")
_desde(T_NUMERO, "q5", DIG, "q5")
_desde(T_NUMERO, "q2", EXP, "q6")
_desde(T_NUMERO, "q3", EXP, "q6")
_desde(T_NUMERO, "q5", EXP, "q6")
_desde(T_NUMERO, "q6", SIGNO, "q7")
_desde(T_NUMERO, "q6", DIG, "q8")
_desde(T_NUMERO, "q7", DIG, "q8")
_desde(T_NUMERO, "q8", DIG, "q8")

# --- Cadenas con escapes ----------------------------------------------
T_CADENA = {
    ("q0", "comilla"): "c1",      # se abre la cadena
    ("c1", "comilla"): "c7",      # se cierra: token CADENA
    ("c1", "barra"): "c2",        # empieza un escape
    ("c2", "u"): "c3",            # \u : faltan 4 digitos hexadecimales
}
_desde(T_CADENA, "c1", NORMAL, "c1")
_desde(T_CADENA, "c2", ESCAPES, "c1")
_desde(T_CADENA, "c3", HEX, "c4")
_desde(T_CADENA, "c4", HEX, "c5")
_desde(T_CADENA, "c5", HEX, "c6")
_desde(T_CADENA, "c6", HEX, "c1")

# --- Caracteres UTF-8 de varios bytes, dentro de una cadena ------------
# El primer byte (lider) dice cuantos bytes de continuacion deben seguir.
T_UTF8 = {
    ("c1", "lider2"): "u1",       # caracter de 2 bytes: falta 1
    ("c1", "lider3"): "u2",       # caracter de 3 bytes: faltan 2
    ("c1", "lider4"): "u3",       # caracter de 4 bytes: faltan 3
    ("u3", "cont"): "u2",
    ("u2", "cont"): "u1",
    ("u1", "cont"): "c1",         # caracter completo: sigo en la cadena
}

# --- Literales: true, false, null -------------------------------------
T_LITERAL = {
    ("q0", "t"): "t1", ("t1", "r"): "t2", ("t2", "u"): "t3", ("t3", "e"): "t4",
    ("q0", "f"): "f1", ("f1", "a"): "f2", ("f2", "l"): "f3", ("f3", "s"): "f4",
    ("f4", "e"): "f5",
    ("q0", "n"): "n1", ("n1", "u"): "n2", ("n2", "l"): "n3", ("n3", "l"): "n4",
}

AFD_JSON = AFD(
    nombre="JSON",
    clase=CLASE_JSON,
    familias={
        "simbolos": T_SIMBOLOS,
        "numeros": T_NUMERO,
        "cadenas": T_CADENA,
        "utf8": T_UTF8,
        "literales": T_LITERAL,
    },
    aceptacion={
        "s1": "LLAVE_ABRE", "s2": "LLAVE_CIERRA",
        "s3": "CORCHETE_ABRE", "s4": "CORCHETE_CIERRA",
        "s5": "DOS_PUNTOS", "s6": "COMA",
        "q2": "NUMERO", "q3": "NUMERO", "q5": "NUMERO", "q8": "NUMERO",
        "c7": "CADENA",
        "t4": "LITERAL", "f5": "LITERAL", "n4": "LITERAL",
    },
    ignorar={"espacio", "salto"},
    # Regla de frontera: despues de un numero o de un literal solo puede
    # venir un delimitador. Por eso 01, 5.x o truex son errores.
    frontera={"NUMERO": DELIMITADORES, "LITERAL": DELIMITADORES},
    descripcion={
        "q0": "esperando un token nuevo",
        "q1": "lei el signo; falta el primer digito",
        "q2": "lei un 0",
        "q3": "leyendo la parte entera",
        "q4": "lei el punto; falta al menos un decimal",
        "q5": "leyendo decimales",
        "q6": "lei la e; falta el exponente",
        "q7": "lei el signo del exponente; faltan sus digitos",
        "q8": "leyendo el exponente",
        "c1": "dentro de una cadena",
        "c2": "lei una barra invertida; falta la letra del escape",
        "c3": "lei \\u; faltan 4 digitos hexadecimales",
        "c4": "lei \\u; faltan 3 digitos hexadecimales",
        "c5": "lei \\u; faltan 2 digitos hexadecimales",
        "c6": "lei \\u; falta 1 digito hexadecimal",
        "c7": "cadena cerrada",
        "u1": "caracter UTF-8 a medias; falta 1 byte",
        "u2": "caracter UTF-8 a medias; faltan 2 bytes",
        "u3": "caracter UTF-8 a medias; faltan 3 bytes",
        "t1": "leyendo true", "t2": "leyendo true", "t3": "leyendo true",
        "t4": "lei true",
        "f1": "leyendo false", "f2": "leyendo false", "f3": "leyendo false",
        "f4": "leyendo false", "f5": "lei false",
        "n1": "leyendo null", "n2": "leyendo null", "n3": "leyendo null",
        "n4": "lei null",
        "s1": "lei {", "s2": "lei }", "s3": "lei [", "s4": "lei ]",
        "s5": "lei :", "s6": "lei ,",
    },
)


# =====================================================================
# 3. XML MINIMO: CLASES Y TABLA
# =====================================================================
# Subconjunto: <nombre>  </nombre>  <nombre/>  y texto entre etiquetas.
# Sin atributos, comentarios, CDATA ni DOCTYPE: cualquier "<!" o "<?" es
# un error lexico (asi no hay expansion de entidades ni ataques XXE).
def _clases_xml():
    c = ["otro"] * 256
    for b in (0x20, 0x09, 0x0A, 0x0D):
        c[b] = "espacio"
    for b in list(range(ord("a"), ord("z") + 1)) + list(range(ord("A"), ord("Z") + 1)):
        c[b] = "letra"
    c[ord("_")] = "letra"
    for d in "0123456789":
        c[ord(d)] = "digito"
    c[ord("-")] = "guion_punto"
    c[ord(".")] = "guion_punto"
    c[ord("<")] = "menor"
    c[ord(">")] = "mayor"
    c[ord("/")] = "diagonal"
    return c


CLASE_XML = _clases_xml()
NOMBRE = {"letra", "digito", "guion_punto"}        # caracteres de un nombre
TEXTO = {"letra", "digito", "guion_punto", "otro", "diagonal", "mayor"}

T_ETIQUETA = {
    ("q0", "menor"): "x1",        # lei <
    ("x1", "letra"): "x2",        # empieza el nombre:  <a
    ("x2", "mayor"): "x3",        # <a>   token ETIQUETA_ABRE
    ("x2", "diagonal"): "x4",     # <a/
    ("x4", "mayor"): "x5",        # <a/>  token ETIQUETA_VACIA
    ("x1", "diagonal"): "x6",     # </
    ("x6", "letra"): "x7",        # </a
    ("x7", "mayor"): "x8",        # </a>  token ETIQUETA_CIERRA
}
_desde(T_ETIQUETA, "x2", NOMBRE, "x2")
_desde(T_ETIQUETA, "x7", NOMBRE, "x7")

T_TEXTO = {}
_desde(T_TEXTO, "q0", TEXTO, "xt")
_desde(T_TEXTO, "xt", TEXTO | {"espacio"}, "xt")

AFD_XML = AFD(
    nombre="XML",
    clase=CLASE_XML,
    familias={"etiquetas": T_ETIQUETA, "texto": T_TEXTO},
    aceptacion={
        "x3": "ETIQUETA_ABRE", "x5": "ETIQUETA_VACIA",
        "x8": "ETIQUETA_CIERRA", "xt": "TEXTO",
    },
    ignorar={"espacio"},
    frontera={},
    descripcion={
        "q0": "esperando un token nuevo",
        "x1": "lei <; falta el nombre de la etiqueta o una /",
        "x2": "leyendo el nombre de una etiqueta de apertura",
        "x3": "etiqueta de apertura completa",
        "x4": "lei <nombre/; falta el >",
        "x5": "etiqueta vacia completa",
        "x6": "lei </; falta el nombre",
        "x7": "leyendo el nombre de una etiqueta de cierre",
        "x8": "etiqueta de cierre completa",
        "xt": "leyendo texto",
    },
)


# =====================================================================
# 4. EL MOTOR (igual para cualquier tabla)
# =====================================================================
class Lexer:
    """
    Tokenizador en streaming.

        lexer = Lexer(AFD_JSON)
        tokens = lexer.alimentar(b'{"id": 1')    # primer bloque
        tokens += lexer.alimentar(b'5}')          # segundo bloque
        tokens += lexer.terminar()                # ya no llega nada mas

    Entre bloque y bloque solo recuerda: el estado, el pedazo en
    construccion y la posicion. Nunca guarda la entrada completa.
    """

    def __init__(self, afd):
        self.afd = afd
        self.estado = afd.inicial
        self.pedazo = bytearray()   # bytes del token en construccion
        self.inicio = 0             # byte donde empezo ese token
        self.pos = 0                # bytes leidos hasta ahora

    def alimentar(self, bloque):
        if isinstance(bloque, str):
            bloque = bloque.encode("utf-8")
        afd = self.afd
        tabla = afd.transiciones
        salida = []
        for byte in bloque:
            clase = afd.clase[byte]
            while True:
                # 1) Estando en q0, los espacios se botan.
                if self.estado == afd.inicial and clase in afd.ignorar:
                    break
                # 2) Hay flecha: avanzo y guardo el byte.
                siguiente = tabla.get((self.estado, clase))
                if siguiente is not None:
                    if self.estado == afd.inicial:
                        self.inicio = self.pos
                    self.estado = siguiente
                    self.pedazo.append(byte)
                    if siguiente in afd.inmediatos:
                        salida.append(self._emitir(None, None, self.pos + 1))
                    break
                # 3) No hay flecha, pero estoy en aceptacion: el token
                #    llego hasta aqui. Lo emito, vuelvo a q0 y reviso
                #    ESTE MISMO byte otra vez (no se consume).
                if self.estado in afd.aceptacion:
                    salida.append(self._emitir(clase, byte, self.pos))
                    continue
                # 4) No hay flecha y no estoy en aceptacion: error.
                self._error(byte)
            self.pos += 1
        return salida

    def terminar(self):
        """Se acabo la entrada: cerrar lo que haya quedado abierto."""
        if self.estado == self.afd.inicial:
            return []
        if self.estado in self.afd.aceptacion:
            return [self._emitir(None, None, self.pos)]
        raise ErrorLexico(
            "la entrada se acabo a mitad de un token (%s)"
            % self.afd.descripcion.get(self.estado, self.estado), self.pos)

    def _emitir(self, clase_siguiente, byte_siguiente, fin):
        tipo = self.afd.aceptacion[self.estado]
        texto = bytes(self.pedazo).decode("utf-8", errors="replace")
        permitidas = self.afd.frontera.get(tipo)
        if (clase_siguiente is not None and permitidas is not None
                and clase_siguiente not in permitidas):
            raise ErrorLexico(
                "%s mal formado: despues de %s no puede venir %s"
                % (tipo.lower(), texto, _mostrar(byte_siguiente)), self.pos)
        token = Token(tipo, texto, self.inicio, fin)
        self.estado = self.afd.inicial
        self.pedazo = bytearray()
        return token

    def _error(self, byte):
        if self.estado == self.afd.inicial:
            raise ErrorLexico("caracter no permitido %s" % _mostrar(byte), self.pos)
        raise ErrorLexico(
            "no se esperaba %s (%s)"
            % (_mostrar(byte), self.afd.descripcion.get(self.estado, self.estado)),
            self.pos)


def _mostrar(byte):
    if 0x20 < byte < 0x7F:
        return "'%s'" % chr(byte)
    return "el byte 0x%02X" % byte


def tokenizar(entrada, afd=AFD_JSON, bloque=None):
    """
    Atajo: devuelve la lista completa de tokens.
    Con bloque=N, la entrada se entrega de a N bytes (para probar streaming).
    """
    if isinstance(entrada, str):
        entrada = entrada.encode("utf-8")
    lexer = Lexer(afd)
    tokens = []
    paso = bloque or max(len(entrada), 1)
    for i in range(0, len(entrada), paso):
        tokens.extend(lexer.alimentar(entrada[i:i + paso]))
    tokens.extend(lexer.terminar())
    return tokens


# =====================================================================
# 5. DEMOSTRACION
# =====================================================================
EJEMPLOS_JSON = [
    '{"id": 7}',
    '[10, "a b"]',
    '{"x": -3.5}',
    '{"masa": 6.02e23, "error": 2E-3}',
    '{"frase": "dijo \\"hola\\"", "letra": "\\u00f1"}',
    '{"ciudad": "Sogamoso, Boyacá"}',
    '{"ok": true, "nada": null}',
    '{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}',
    '}{ 7 : :',
    '{"id": 7@}',
    '{"id": "hola}',
    '{"id": 01}',
    '{"id": 1.e3}',
    '{"id": "mal \\q escape"}',
    '{"ok": verdadero}',
]

EJEMPLOS_XML = [
    '<persona><id>7</id><nombre>Ana Ruiz</nombre><activo/></persona>',
    '<a>\n  <b>hola</b>\n</a>',
    '<a><b>sin cerrar</a',
    '<!DOCTYPE x><a/>',
]


def mostrar(entrada, afd):
    print("\nEntrada (%s): %s" % (afd.nombre, entrada))
    try:
        tokens = tokenizar(entrada, afd)
    except ErrorLexico as e:
        print("  %s" % e)
        return
    for numero, t in enumerate(tokens, start=1):
        print("  %2d. %-16s %-28s bytes %d-%d" % (numero, t.tipo, t.texto, t.inicio, t.fin))
    print("  Total: %d tokens" % len(tokens))


def tokenizar_archivo(ruta, afd=None, tamano_bloque=4096):
    """
    Lee un archivo DE VERDAD en streaming: de a 4096 bytes, sin cargarlo
    completo en memoria. Va entregando los tokens a medida que salen.
    Si no se indica el afd, se escoge por la extension (.xml o JSON).
    """
    if afd is None:
        afd = AFD_XML if ruta.lower().endswith(".xml") else AFD_JSON
    lexer = Lexer(afd)
    with open(ruta, "rb") as archivo:          # "rb": bytes crudos
        while True:
            bloque = archivo.read(tamano_bloque)
            if not bloque:
                break
            for token in lexer.alimentar(bloque):
                yield token
    for token in lexer.terminar():
        yield token


def mostrar_archivo(ruta):
    print("\nArchivo: %s" % ruta)
    numero = 0
    try:
        for numero, t in enumerate(tokenizar_archivo(ruta), start=1):
            print("  %2d. %-16s %-28s bytes %d-%d" % (numero, t.tipo, t.texto, t.inicio, t.fin))
    except ErrorLexico as e:
        print("  %s" % e)
        return
    print("  Total: %d tokens" % numero)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for ruta in sys.argv[1:]:
            mostrar_archivo(ruta)
    else:
        for ejemplo in EJEMPLOS_JSON:
            mostrar(ejemplo, AFD_JSON)
        for ejemplo in EJEMPLOS_XML:
            mostrar(ejemplo, AFD_XML)
        print("\nStreaming: el mismo JSON entregado en dos bloques")
        lexer = Lexer(AFD_JSON)
        for parte in (b'{"id": 1', b'5e3}'):
            print("  bloque %r -> %s" % (parte, [(t.tipo, t.texto) for t in lexer.alimentar(parte)]))
        print("  terminar()        -> %s" % [(t.tipo, t.texto) for t in lexer.terminar()])
