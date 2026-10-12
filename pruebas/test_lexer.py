"""
Pruebas de la fase 1 (lexer).

Como correrlas, desde la carpeta proyecto/:
    python pruebas/test_lexer.py

No necesita instalar nada. Cada prueba imprime OK o FALLA.
"""

import itertools
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from compilador.lexer import AFD_JSON, AFD_XML, ErrorLexico, tokenizar  # noqa: E402

# ---------------------------------------------------------------------
# A. Casos con la respuesta escrita a mano
# ---------------------------------------------------------------------
# (entrada, lista de (tipo, texto) esperada)
VALIDOS_JSON = [
    ('{"id": 7}', [("LLAVE_ABRE", "{"), ("CADENA", '"id"'), ("DOS_PUNTOS", ":"),
                   ("NUMERO", "7"), ("LLAVE_CIERRA", "}")]),
    ('[10, "a b"]', [("CORCHETE_ABRE", "["), ("NUMERO", "10"), ("COMA", ","),
                     ("CADENA", '"a b"'), ("CORCHETE_CIERRA", "]")]),
    ('{"x": -3.5}', [("LLAVE_ABRE", "{"), ("CADENA", '"x"'), ("DOS_PUNTOS", ":"),
                     ("NUMERO", "-3.5"), ("LLAVE_CIERRA", "}")]),
    ("[1, 2, 3]", [("CORCHETE_ABRE", "["), ("NUMERO", "1"), ("COMA", ","),
                   ("NUMERO", "2"), ("COMA", ","), ("NUMERO", "3"),
                   ("CORCHETE_CIERRA", "]")]),
    ('{"a": -0.25}', [("LLAVE_ABRE", "{"), ("CADENA", '"a"'), ("DOS_PUNTOS", ":"),
                      ("NUMERO", "-0.25"), ("LLAVE_CIERRA", "}")]),
    ("2E-3", [("NUMERO", "2E-3")]),
    ("-1.5e+3", [("NUMERO", "-1.5e+3")]),
    ("0", [("NUMERO", "0")]),
    ("6.02e23", [("NUMERO", "6.02e23")]),
    ('"5:30"', [("CADENA", '"5:30"')]),
    ('"dijo \\"hola\\""', [("CADENA", '"dijo \\"hola\\""')]),
    ('"l\\u00f1"', [("CADENA", '"l\\u00f1"')]),
    ('"a\\\\b\\/c\\n"', [("CADENA", '"a\\\\b\\/c\\n"')]),
    ('"Boyacá 中 \U0001F600"', [("CADENA", '"Boyacá 中 \U0001F600"')]),
    ('""', [("CADENA", '""')]),
    ("true false null", [("LITERAL", "true"), ("LITERAL", "false"), ("LITERAL", "null")]),
    ("[true,null]", [("CORCHETE_ABRE", "["), ("LITERAL", "true"), ("COMA", ","),
                     ("LITERAL", "null"), ("CORCHETE_CIERRA", "]")]),
    ("}{ 7 : :", [("LLAVE_CIERRA", "}"), ("LLAVE_ABRE", "{"), ("NUMERO", "7"),
                  ("DOS_PUNTOS", ":"), ("DOS_PUNTOS", ":")]),
    ("  \n\t ", []),
    ("", []),
]

# (entrada, byte donde debe fallar)
ERRORES_JSON = [
    ('{"id": 7@}', 8),        # @ despues de un numero
    ('{"id": "hola}', 13),    # la cadena nunca cierra
    ('{"id": 01}', 8),        # cero a la izquierda
    ("[-]", 2),               # signo sin digitos
    ("1.e3", 2),              # punto sin decimales
    ("5.", 2),                # idem, al final de la entrada
    ("1e", 2),                # e sin exponente
    ("1e+", 3),               # signo del exponente sin digitos
    ("e5", 0),                # un numero no empieza por e
    ("+5", 0),                # ni por +
    (".5", 0),                # ni por punto
    ("verdadero", 0),         # palabra desconocida
    ("nulo", 3),              # se parece a null pero no es
    ("truex", 4),             # literal pegado a una letra
    ('"mal \\q"', 6),         # escape que no existe
    ('"\\u12G4"', 5),         # \u con algo que no es hexadecimal
    ('"salto\nreal"', 6),     # salto de linea crudo dentro de una cadena
    (b'"\xff"', 1),           # byte que nunca es UTF-8
    (b'"\xc3"', 2),           # caracter UTF-8 cortado
    (b'"\xe4\xb8"', 3),       # idem, de 3 bytes
    (b'"\x80"', 1),           # byte de continuacion suelto
]

VALIDOS_XML = [
    ("<a>7</a>", [("ETIQUETA_ABRE", "<a>"), ("TEXTO", "7"), ("ETIQUETA_CIERRA", "</a>")]),
    ("<persona><id>7</id><activo/></persona>",
     [("ETIQUETA_ABRE", "<persona>"), ("ETIQUETA_ABRE", "<id>"), ("TEXTO", "7"),
      ("ETIQUETA_CIERRA", "</id>"), ("ETIQUETA_VACIA", "<activo/>"),
      ("ETIQUETA_CIERRA", "</persona>")]),
    ("<a>\n  <b>hola mundo</b>\n</a>",
     [("ETIQUETA_ABRE", "<a>"), ("ETIQUETA_ABRE", "<b>"), ("TEXTO", "hola mundo"),
      ("ETIQUETA_CIERRA", "</b>"), ("ETIQUETA_CIERRA", "</a>")]),
    ("<mi-etiqueta_2.x/>", [("ETIQUETA_VACIA", "<mi-etiqueta_2.x/>")]),
    ("</b><a>", [("ETIQUETA_CIERRA", "</b>"), ("ETIQUETA_ABRE", "<a>")]),
]

ERRORES_XML = [
    ("<a><b>sin cerrar</a", 19),   # se acaba a mitad de la etiqueta
    ("<!DOCTYPE x><a/>", 1),       # DOCTYPE no se admite
    ("<?xml version='1.0'?>", 1),  # ni instrucciones de proceso
    ("<a b='1'>", 2),              # ni atributos
    ("<1a>", 1),                   # un nombre no empieza por digito
    ("<a/ >", 3),                  # espacio donde debia ir >
    ("<>", 1),                     # etiqueta sin nombre
]

# ---------------------------------------------------------------------
# Mini-corredor de pruebas
# ---------------------------------------------------------------------
resultados = {"ok": 0, "falla": 0}


def comprobar(nombre, condicion, detalle=""):
    if condicion:
        resultados["ok"] += 1
    else:
        resultados["falla"] += 1
        print("  FALLA  %s  %s" % (nombre, detalle))


def pares(tokens):
    return [(t.tipo, t.texto) for t in tokens]


def intento(entrada, afd, bloque=None):
    """Devuelve ('ok', tokens) o ('error', posicion)."""
    try:
        return ("ok", pares(tokenizar(entrada, afd, bloque)))
    except ErrorLexico as e:
        return ("error", e.posicion)


def prueba_casos():
    print("A. Casos escritos a mano")
    for entrada, esperado in VALIDOS_JSON:
        comprobar("json %r" % (entrada,), intento(entrada, AFD_JSON) == ("ok", esperado),
                  str(intento(entrada, AFD_JSON)))
    for entrada, posicion in ERRORES_JSON:
        comprobar("json error %r" % (entrada,), intento(entrada, AFD_JSON) == ("error", posicion),
                  str(intento(entrada, AFD_JSON)))
    for entrada, esperado in VALIDOS_XML:
        comprobar("xml %r" % (entrada,), intento(entrada, AFD_XML) == ("ok", esperado),
                  str(intento(entrada, AFD_XML)))
    for entrada, posicion in ERRORES_XML:
        comprobar("xml error %r" % (entrada,), intento(entrada, AFD_XML) == ("error", posicion),
                  str(intento(entrada, AFD_XML)))


def prueba_streaming():
    """Partir la entrada en bloques no debe cambiar NADA del resultado."""
    print("B. Streaming: mismo resultado sin importar el tamano del bloque")
    todos = [(e, AFD_JSON) for e, _ in VALIDOS_JSON + ERRORES_JSON]
    todos += [(e, AFD_XML) for e, _ in VALIDOS_XML + ERRORES_XML]
    for entrada, afd in todos:
        completo = intento(entrada, afd)
        for bloque in (1, 2, 3, 7):
            comprobar("bloque=%d %r" % (bloque, entrada),
                      intento(entrada, afd, bloque) == completo)


# La definicion oficial de numero en JSON (RFC 8259), como expresion regular.
NUMERO_OFICIAL = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")


def prueba_numeros_exhaustiva(largo_maximo=5):
    """
    Genera TODAS las combinaciones de estos 8 simbolos hasta cierto largo y
    compara el veredicto del AFD con el de la definicion oficial.
    """
    print("C. Numeros: AFD contra la definicion oficial (exhaustivo)")
    simbolos = "-+.eE019"
    total = desacuerdos = 0
    for largo in range(1, largo_maximo + 1):
        for combinacion in itertools.product(simbolos, repeat=largo):
            texto = "".join(combinacion)
            oficial = NUMERO_OFICIAL.fullmatch(texto) is not None
            nuestro = intento(texto, AFD_JSON) == ("ok", [("NUMERO", texto)])
            total += 1
            if oficial != nuestro:
                desacuerdos += 1
                if desacuerdos <= 5:
                    print("    desacuerdo en %r: oficial=%s, AFD=%s" % (texto, oficial, nuestro))
    comprobar("numeros exhaustivo (%d cadenas)" % total, desacuerdos == 0,
              "%d desacuerdos" % desacuerdos)
    print("   %d cadenas comparadas, %d desacuerdos" % (total, desacuerdos))


def _valor_al_azar(rng, profundidad=0):
    opciones = ["numero", "cadena", "literal"]
    if profundidad < 3:
        opciones += ["lista", "objeto"]
    tipo = rng.choice(opciones)
    if tipo == "numero":
        return rng.choice([0, -7, 15, 3.25, -0.5, 1e21, 2.5e-7, 123456789])
    if tipo == "cadena":
        letras = 'abc xyzñá中\U0001F600"\\/\n\t{}[]:,'
        return "".join(rng.choice(letras) for _ in range(rng.randint(0, 8)))
    if tipo == "literal":
        return rng.choice([True, False, None])
    if tipo == "lista":
        return [_valor_al_azar(rng, profundidad + 1) for _ in range(rng.randint(0, 4))]
    return {"k%d" % i: _valor_al_azar(rng, profundidad + 1) for i in range(rng.randint(0, 4))}


def prueba_documentos_al_azar(cuantos=300):
    """
    Todo JSON valido escrito por la libreria estandar debe pasar el lexer,
    y cada CADENA y NUMERO que salga debe ser, por si solo, JSON valido.
    """
    print("D. Documentos JSON generados al azar")
    rng = random.Random(2026)
    fallos = 0
    for _ in range(cuantos):
        valor = _valor_al_azar(rng)
        for ascii_puro in (True, False):
            texto = json.dumps(valor, ensure_ascii=ascii_puro, indent=rng.choice([None, 2]))
            try:
                tokens = tokenizar(texto, AFD_JSON, bloque=rng.choice([None, 1, 5]))
                for t in tokens:
                    if t.tipo in ("CADENA", "NUMERO", "LITERAL"):
                        json.loads(t.texto)
            except (ErrorLexico, ValueError) as e:
                fallos += 1
                if fallos <= 3:
                    print("    fallo con %r: %s" % (texto, e))
    comprobar("documentos al azar", fallos == 0, "%d fallos" % fallos)
    print("   %d documentos, %d fallos" % (cuantos * 2, fallos))


def prueba_determinismo():
    """Cada (estado, clase) tiene a lo sumo un destino, y todo estado sirve."""
    print("E. Las tablas son deterministas y no tienen estados sueltos")
    for afd in (AFD_JSON, AFD_XML):
        suma = sum(len(t) for t in afd.familias.values())
        comprobar("determinismo %s" % afd.nombre, suma == len(afd.transiciones))
        alcanzables = {afd.inicial}
        cambio = True
        while cambio:
            cambio = False
            for (origen, _), destino in afd.transiciones.items():
                if origen in alcanzables and destino not in alcanzables:
                    alcanzables.add(destino)
                    cambio = True
        comprobar("alcanzables %s" % afd.nombre, alcanzables == afd.estados())
        comprobar("descripciones %s" % afd.nombre, afd.estados() <= set(afd.descripcion))
        comprobar("aceptacion %s" % afd.nombre, set(afd.aceptacion) <= afd.estados())


if __name__ == "__main__":
    prueba_casos()
    prueba_streaming()
    prueba_numeros_exhaustiva()
    prueba_documentos_al_azar()
    prueba_determinismo()
    print("\nResultado: %d comprobaciones correctas, %d fallas"
          % (resultados["ok"], resultados["falla"]))
    sys.exit(1 if resultados["falla"] else 0)
