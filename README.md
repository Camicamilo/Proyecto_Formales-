# Validador JSON/XML con automatas de pila ponderados

Proyecto final de Lenguajes Formales y Automatas, 2026-2.

## Estado

| Fase | Estado |
|---|---|
| 1. Analisis lexico | Lista |
| 2. Analisis sintactico | Pendiente |
| 3 a 7 | Pendientes |

## Como correr lo que hay

Desde esta carpeta:

    python compilador/lexer.py              ejemplos de JSON y de XML
    python compilador/lexer.py pruebas/casos/payload_valido.json   tokens de un archivo
    python pruebas/test_lexer.py            todas las pruebas de la fase 1
    python docs/generar_docs.py             regenera diagramas y docs/fase1_lexico.md

Solo `generar_docs.py` necesita algo instalado: Graphviz (el comando `dot`).

## Carpetas

    compilador/   el compilador de esquemas (por ahora, el lexer)
    pruebas/      pruebas automaticas
    pruebas/casos archivos JSON y XML de ejemplo
    docs/         documentacion tecnica y diagramas
