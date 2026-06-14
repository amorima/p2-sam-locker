#!/usr/bin/env python3
"""
(Opcional) Gera assets/logo.png a partir do logótipo SVG da marca, para um
logótipo pixel-perfect na aplicação do cacifo. Sem este PNG, a app desenha o
logótipo como texto.

Requer cairosvg:  pip install cairosvg
Uso:              python render_logo.py
"""
import os

try:
    import cairosvg
except ImportError:
    raise SystemExit("cairosvg não instalado. Execute: pip install cairosvg")

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "logo_big.svg")
OUT = os.path.join(HERE, "logo.png")

if __name__ == "__main__":
    cairosvg.svg2png(url=SRC, write_to=OUT, output_width=520)
    print(f"Gerado {OUT}")
