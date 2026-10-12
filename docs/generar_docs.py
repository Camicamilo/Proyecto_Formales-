"""
Genera la documentacion de la fase 1 a partir de las MISMAS tablas que usa
el lexer, para que el dibujo, la gramatica y el codigo nunca se contradigan.

Produce:
    docs/diagramas/*.png y *.dot   un diagrama por familia de tokens
    docs/fase1_lexico.md           alfabeto, tokens, estados, tablas y gramaticas

Como correrlo, desde la carpeta proyecto/:
    python docs/generar_docs.py

Necesita Graphviz instalado (el comando "dot") para los PNG. Si no esta,
igual escribe los .dot y el .md.
"""

import os
import shutil
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))

from compilador import lexer as L  # noqa: E402

DIAGRAMAS = os.path.join(AQUI, "diagramas")

# ---------------------------------------------------------------------
# Etiquetas legibles para grupos de clases
# ---------------------------------------------------------------------
# (conjunto de clases, etiqueta en el diagrama, etiqueta en la gramatica)
GRUPOS_JSON = [
    (L.NORMAL, "normal", "NORMAL"),
    (L.HEX, "hex", "HEX"),
    (L.ESCAPES, '" \\ / b f n r t', "ESC"),
    (L.DIG, "0-9", "[0-9]"),
    (L.EXP, "e, E", "[eE]"),
    (L.SIGNO, "+, -", "[+-]"),
]
SUELTAS_JSON = {
    "llave_abre": "{", "llave_cierra": "}", "corchete_abre": "[",
    "corchete_cierra": "]", "dos_puntos": ":", "coma": ",",
    "comilla": '"', "barra": "\\", "diagonal": "/", "menos": "-", "mas": "+",
    "punto": ".", "cero": "0", "digito": "1-9", "E_may": "E",
    "cont": "cont", "lider2": "lider2", "lider3": "lider3", "lider4": "lider4",
}
GRUPOS_XML = [
    (L.TEXTO | {"espacio"}, "todo menos <", "TEXTO_O_ESPACIO"),
    (L.TEXTO, "todo menos < y espacio", "TEXTO"),
    (L.NOMBRE, "letra, digito, - .", "NOMBRE"),
]
SUELTAS_XML = {"menor": "<", "mayor": ">", "diagonal": "/", "letra": "letra"}


def etiqueta(clases, grupos, sueltas, gramatica=False):
    """Convierte un conjunto de clases en un texto corto."""
    resto = set(clases)
    partes = []
    for conjunto, en_diagrama, en_gramatica in grupos:
        if conjunto <= resto:
            partes.append(en_gramatica if gramatica else en_diagrama)
            resto -= conjunto
    for c in sorted(resto):
        texto = sueltas.get(c, c)
        if gramatica:
            if texto == "1-9":
                texto = "[1-9]"
            elif texto in ("cont", "lider2", "lider3", "lider4", "letra"):
                texto = texto.upper()
            elif c == "comilla":
                texto = "COMILLA"
            elif c == "barra":
                texto = "BARRA"
            else:
                texto = '"%s"' % texto
        partes.append(texto)
    return (" | " if gramatica else ", ").join(partes)


def orden(estado):
    letras = "".join(ch for ch in estado if not ch.isdigit())
    numero = "".join(ch for ch in estado if ch.isdigit())
    prioridad = 0 if estado == "q0" else 1
    return (prioridad, letras, int(numero) if numero else 0)


def agrupar(tabla):
    """{(origen, destino): conjunto de clases}"""
    flechas = {}
    for (origen, clase), destino in tabla.items():
        flechas.setdefault((origen, destino), set()).add(clase)
    return flechas


# ---------------------------------------------------------------------
# Diagramas con Graphviz
# ---------------------------------------------------------------------
def escapar(texto):
    return texto.replace("\\", "\\\\").replace('"', '\\"')


def escribir_diagrama(afd, nombre_archivo, tablas, grupos, sueltas):
    tabla = {}
    for t in tablas:
        tabla.update(t)
    estados = set()
    for (origen, _), destino in tabla.items():
        estados.add(origen)
        estados.add(destino)

    lineas = [
        "digraph AFD {",
        "  rankdir=LR; bgcolor=white; nodesep=0.45; ranksep=0.7;",
        '  node [fontname="Helvetica", fontsize=13, shape=circle, style=filled,'
        ' fillcolor="#F1EFE8", color="#5F5E5A", fixedsize=true, width=0.62];',
        '  edge [fontname="Helvetica", fontsize=11, color="#444441", arrowsize=0.7];',
    ]
    if afd.inicial in estados:
        lineas.append("  inicio [shape=point, width=0.01, style=invis];")
        lineas.append("  inicio -> %s;" % afd.inicial)
    for e in sorted(estados, key=orden):
        if e in afd.aceptacion:
            lineas.append('  %s [shape=doublecircle, fillcolor="#E1F5EE", color="#0F6E56"];' % e)
            # Cartel que dice que token sale al terminar en este estado
            lineas.append(
                '  tok_%s [shape=plaintext, style="", fixedsize=false, fontsize=10,'
                ' fontcolor="#0F6E56", label="emite %s"];' % (e, afd.aceptacion[e]))
            lineas.append(
                '  %s -> tok_%s [style=dashed, color="#0F6E56", arrowhead=none];' % (e, e))
        else:
            lineas.append("  %s;" % e)
    for (origen, destino), clases in sorted(agrupar(tabla).items(),
                                           key=lambda kv: (orden(kv[0][0]), orden(kv[0][1]))):
        texto = etiqueta(clases, grupos, sueltas)
        if texto == ".":
            texto = ". (punto)"       # un punto solo casi no se ve en el dibujo
        lineas.append('  %s -> %s [label=" %s "];' % (origen, destino, escapar(texto)))
    lineas.append("}")

    ruta_dot = os.path.join(DIAGRAMAS, nombre_archivo + ".dot")
    with open(ruta_dot, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    if shutil.which("dot"):
        subprocess.run(["dot", "-Tpng", "-Gdpi=170", ruta_dot, "-o",
                        os.path.join(DIAGRAMAS, nombre_archivo + ".png")], check=True)
        return True
    return False


# ---------------------------------------------------------------------
# Gramaticas regulares (lineales por la derecha)
# ---------------------------------------------------------------------
def gramatica(afd, tablas, grupos, sueltas):
    """
    Regla de conversion AFD -> gramatica regular:
        por cada flecha  A --c--> B   se escribe   A -> c B
        y si B es de aceptacion, ademas            A -> c
    """
    tabla = {}
    for t in tablas:
        tabla.update(t)
    con_salida = {origen for (origen, _) in afd.transiciones}
    flechas = agrupar(tabla)
    origenes = sorted({o for (o, _) in flechas}, key=orden)
    lineas = []
    for origen in origenes:
        producciones = []
        destinos = sorted((d for (o, d) in flechas if o == origen), key=orden)
        for destino in destinos:
            for terminal in etiqueta(flechas[(origen, destino)], grupos, sueltas, True).split(" | "):
                if destino in con_salida:
                    producciones.append("%s <%s>" % (terminal, destino))
                if destino in afd.aceptacion:
                    producciones.append(terminal)
        lineas.append("<%s> -> %s" % (origen, " | ".join(producciones)))
    return "\n".join(lineas)


# ---------------------------------------------------------------------
# Documento Markdown
# ---------------------------------------------------------------------
def rangos_hex(afd, clase):
    bytes_ = [b for b in range(256) if afd.clase[b] == clase]
    partes = []
    inicio = previo = None
    for b in bytes_ + [None]:
        if inicio is None:
            inicio = previo = b
        elif b is not None and b == previo + 1:
            previo = b
        else:
            partes.append("%02X" % inicio if inicio == previo else "%02X-%02X" % (inicio, previo))
            inicio = previo = b
    return ", ".join(partes)


SIGNIFICADO_JSON = {
    "control": "caracteres de control; prohibidos dentro de una cadena",
    "salto": "tabulador, salto de linea, retorno de carro",
    "espacio": "espacio",
    "otro": "resto de ASCII imprimible (letras g-z sin papel especial, signos...)",
    "llave_abre": "{", "llave_cierra": "}", "corchete_abre": "[",
    "corchete_cierra": "]", "dos_puntos": ":", "coma": ",",
    "comilla": "comilla doble", "barra": "barra invertida", "diagonal": "/",
    "menos": "-", "mas": "+", "punto": ".", "cero": "0", "digito": "1 a 9",
    "E_may": "E mayuscula (exponente y hexadecimal)",
    "hex_may": "A, B, C, D, F (hexadecimal)",
    "cont": "byte de continuacion de un caracter UTF-8",
    "lider2": "primer byte de un caracter UTF-8 de 2 bytes",
    "lider3": "primer byte de un caracter UTF-8 de 3 bytes",
    "lider4": "primer byte de un caracter UTF-8 de 4 bytes",
    "invalido": "bytes que nunca aparecen en UTF-8 valido",
}
SIGNIFICADO_XML = {
    "espacio": "espacio, tabulador, salto de linea, retorno",
    "letra": "A-Z, a-z y guion bajo", "digito": "0 a 9",
    "guion_punto": "guion y punto", "menor": "<", "mayor": ">", "diagonal": "/",
    "otro": "cualquier otro byte",
}


def tabla_clases(afd, significado):
    filas = ["| Clase | Bytes (hexadecimal) | Que es |", "|---|---|---|"]
    for clase in sorted(set(afd.clase), key=lambda c: afd.clase.index(c)):
        que = significado.get(clase, "la letra %s" % clase if len(clase) == 1 else clase)
        filas.append("| `%s` | %s | %s |" % (clase, rangos_hex(afd, clase), que))
    return "\n".join(filas)


def tabla_estados(afd, tablas):
    estados = set()
    for t in tablas:
        for (origen, _), destino in t.items():
            estados.add(origen)
            estados.add(destino)
    filas = ["| Estado | Significado | Aceptacion |", "|---|---|---|"]
    for e in sorted(estados, key=orden):
        filas.append("| %s | %s | %s |" % (e, afd.descripcion[e], afd.aceptacion.get(e, "no")))
    return "\n".join(filas)


def tabla_flechas(tablas, grupos, sueltas):
    tabla = {}
    for t in tablas:
        tabla.update(t)
    filas = ["| Estando en | Si leo | Paso a |", "|---|---|---|"]
    for (origen, destino), clases in sorted(agrupar(tabla).items(),
                                           key=lambda kv: (orden(kv[0][0]), orden(kv[0][1]))):
        texto = etiqueta(clases, grupos, sueltas).replace("|", "\\|")
        filas.append("| %s | `%s` | %s |" % (origen, texto, destino))
    return "\n".join(filas)


SECCIONES = [
    # (afd, archivo, titulo, tablas, grupos, sueltas)
    (L.AFD_JSON, "json_simbolos", "JSON: simbolos de un byte", [L.T_SIMBOLOS], GRUPOS_JSON, SUELTAS_JSON),
    (L.AFD_JSON, "json_numeros", "JSON: numeros", [L.T_NUMERO], GRUPOS_JSON, SUELTAS_JSON),
    (L.AFD_JSON, "json_cadenas", "JSON: cadenas con escapes", [L.T_CADENA], GRUPOS_JSON, SUELTAS_JSON),
    (L.AFD_JSON, "json_utf8", "JSON: caracteres UTF-8 de varios bytes dentro de una cadena", [L.T_UTF8], GRUPOS_JSON, SUELTAS_JSON),
    (L.AFD_JSON, "json_literales", "JSON: literales true, false y null", [L.T_LITERAL], GRUPOS_JSON, SUELTAS_JSON),
    (L.AFD_XML, "xml_etiquetas", "XML: etiquetas y texto", [L.T_ETIQUETA, L.T_TEXTO], GRUPOS_XML, SUELTAS_XML),
]


def main():
    os.makedirs(DIAGRAMAS, exist_ok=True)
    md = []
    md.append("# Fase 1: analisis lexico\n")
    md.append("Documento generado por `docs/generar_docs.py` a partir de las tablas de "
              "`compilador/lexer.py`. No se edita a mano: si cambia una tabla, se vuelve a generar.\n")

    md.append("## 1. Alfabeto\n")
    md.append("El alfabeto de entrada son los 256 valores posibles de un byte. Para que las tablas "
              "sean pequenas, los bytes se agrupan en clases: el automata no pregunta \"que byte es\" "
              "sino \"de que clase es\".\n")
    md.append("### Clases de bytes para JSON (%d clases)\n" % len(set(L.CLASE_JSON)))
    md.append(tabla_clases(L.AFD_JSON, SIGNIFICADO_JSON) + "\n")
    md.append("Grupos que se usan como abreviatura en tablas, diagramas y gramaticas:\n")
    md.append("- `0-9` o `[0-9]`: las clases `cero` y `digito`.\n"
              "- `hex` o `HEX`: digitos hexadecimales, 0-9, a-f, A-F.\n"
              "- `ESC`: lo que puede seguir a una barra invertida: `\" \\ / b f n r t`.\n"
              "- `normal` o `NORMAL`: cualquier byte ASCII imprimible (20 a 7F) excepto la comilla "
              "y la barra invertida.\n")
    md.append("### Clases de bytes para XML (%d clases)\n" % len(set(L.CLASE_XML)))
    md.append(tabla_clases(L.AFD_XML, SIGNIFICADO_XML) + "\n")

    md.append("## 2. Tokens\n")
    md.append("| Lenguaje | Token | Ejemplo |\n|---|---|---|\n"
              "| JSON | LLAVE_ABRE, LLAVE_CIERRA | `{` `}` |\n"
              "| JSON | CORCHETE_ABRE, CORCHETE_CIERRA | `[` `]` |\n"
              "| JSON | DOS_PUNTOS, COMA | `:` `,` |\n"
              "| JSON | CADENA | `\"hola\"` |\n"
              "| JSON | NUMERO | `-3.5e10` |\n"
              "| JSON | LITERAL | `true` `false` `null` |\n"
              "| XML | ETIQUETA_ABRE | `<id>` |\n"
              "| XML | ETIQUETA_CIERRA | `</id>` |\n"
              "| XML | ETIQUETA_VACIA | `<activo/>` |\n"
              "| XML | TEXTO | `Ana Ruiz` |\n")
    md.append("Los espacios fuera de las cadenas (y entre etiquetas, en XML) no generan token. "
              "Un JSON Schema es un documento JSON, asi que el lexer del esquema es el mismo lexer de JSON.\n")

    md.append("## 3. Automatas y gramaticas regulares\n")
    md.append("Todos los automatas comparten el estado inicial q0. Cada gramatica se obtiene del "
              "automata con una regla mecanica: por cada flecha de A a B con el simbolo c se escribe "
              "`<A> -> c <B>`, y si B es de aceptacion se agrega `<A> -> c`.\n")
    hay_dot = True
    for afd, archivo, titulo, tablas, grupos, sueltas in SECCIONES:
        hay_dot = escribir_diagrama(afd, archivo, tablas, grupos, sueltas) and hay_dot
        md.append("### %s\n" % titulo)
        md.append("![%s](diagramas/%s.png)\n" % (titulo, archivo))
        md.append(tabla_estados(afd, tablas) + "\n")
        md.append(tabla_flechas(tablas, grupos, sueltas) + "\n")
        md.append("Gramatica regular:\n")
        md.append("```\n" + gramatica(afd, tablas, grupos, sueltas) + "\n```\n")

    md.append("## 4. Como recorre el motor las tablas\n")
    md.append("Para cada byte que llega, en este orden:\n\n"
              "1. Si esta en q0 y el byte es un espacio, lo bota.\n"
              "2. Si hay flecha para (estado, clase), avanza y guarda el byte.\n"
              "3. Si no hay flecha pero el estado es de aceptacion, emite el token, vuelve a q0 y "
              "revisa ese mismo byte otra vez.\n"
              "4. Si no hay flecha y el estado no es de aceptacion, es un error lexico y se reporta "
              "la posicion en bytes.\n")
    md.append("Regla de frontera: despues de un NUMERO o un LITERAL solo puede venir un delimitador "
              "(espacio o uno de los seis simbolos) o el fin de la entrada. Por eso `01`, `5.x` y "
              "`truex` son errores.\n")
    md.append("Streaming: entre un bloque y el siguiente el lexer solo conserva el estado, el token "
              "en construccion y la posicion. El resultado no depende de como se parta la entrada.\n")

    md.append("## 5. Limites conocidos\n")
    md.append("- UTF-8: se comprueba la estructura (byte lider seguido del numero correcto de "
              "continuaciones). No se rechazan las codificaciones sobrelargas ni los sustitutos.\n"
              "- XML: sin atributos, comentarios, CDATA, DOCTYPE ni instrucciones de proceso. "
              "Las entidades como `&amp;` se dejan como texto, sin expandir.\n"
              "- El texto de XML conserva los espacios finales antes de la siguiente etiqueta.\n")

    with open(os.path.join(AQUI, "fase1_lexico.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("Escrito docs/fase1_lexico.md")
    print("Diagramas PNG generados" if hay_dot else
          "Graphviz no esta instalado: solo se escribieron los .dot")


if __name__ == "__main__":
    main()
