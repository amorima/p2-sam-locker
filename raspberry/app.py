#!/usr/bin/env python3
"""
SAM — Aplicação do Cacifo (Raspberry Pi 400)

Interface gráfica em ecrã inteiro com o logótipo SAM, fundo azul clássico e um
pinpad virtual (táctil + numpad físico). Fluxo:

  1. O cidadão insere o PIN de entrega.
  2. A app valida o PIN no backend (endpoint /lockers/:id/verify-pin).
  3. Se válido, mostra "Por favor deposite o <bem> no cacifo 1" e fica à escuta
     do estado da porta (sensor magnético reportado pelo Arduino).
  4. Quando a porta abre e volta a fechar, confirma a doação
     (endpoint /lockers/:id/confirm-deposit) e mostra o ecrã de sucesso.

Modos de teste (ver config.py): DEMO_MODE e SIMULATE_DOOR permitem experimentar
a interface e o fluxo sem backend nem Arduino, usando o teclado.
"""

import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

import config
from sam_client import SamClient, SamApiError


def _enable_dpi_awareness():
    """No Windows, sem isto o Tk pede uma janela em pixéis 'lógicos' que o
    sistema estica (DPI > 100%): a janela fica maior que o ecrã (o fundo sai
    para fora) e tudo fica desfocado. Tem de ser chamado ANTES de criar o Tk."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """Desenha um retângulo de cantos arredondados num Canvas."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [
        x1 + r,
        y1,
        x2 - r,
        y1,
        x2,
        y1,
        x2,
        y1 + r,
        x2,
        y2 - r,
        x2,
        y2,
        x2 - r,
        y2,
        x1 + r,
        y2,
        x1,
        y2,
        x1,
        y2 - r,
        x1,
        y1 + r,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class LockerApp:
    def __init__(self, root):
        self.root = root
        self.c = config.COLORS
        self.client = None if config.DEMO_MODE else SamClient()

        # --- Estado da aplicação ---------------------------------------
        self.screen = "pin"  # "pin" | "deposit" | "success"
        self.pin = ""  # PIN em construção
        self.busy = False  # a validar / a confirmar (bloqueia input)
        self.error_text = ""  # mensagem de erro no ecrã do PIN
        self.active_lead = None  # lead resolvido pelo PIN

        # Estado da porta / fluxo de depósito
        self.deposit_substate = None  # "wait_open" | "wait_close"
        self.deposit_start = 0.0
        self.door_estado = "DESCONHECIDA"
        self.door_online = False
        self._door_stop = threading.Event()
        self._door_thread = None
        self._sim_door = "FECHADA"  # usado em DEMO_MODE / SIMULATE_DOOR

        self.W = config.WINDOW_W
        self.H = config.WINDOW_H
        self._last_size = (0, 0)

        self._setup_window()
        self.font_family = self._pick_font_family()
        self._setup_fonts()
        self._try_load_logo()

        self.canvas = tk.Canvas(root, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._widgets = []

        self._bind_keys()
        self.canvas.bind("<Configure>", self._on_resize)

        # Telemetria periódica do cacifo (para aparecer em "Equipamentos").
        self._tele_stop = threading.Event()
        self._tele_thread = None

        self.root.after(50, self._render)
        self._start_telemetry()

    # ------------------------------------------------------------------ setup
    def _apply_fullscreen(self):
        """Aplica (e reforça) o ecrã inteiro. No Raspberry, o gestor de janelas
        ignora por vezes o pedido feito antes de a janela estar mapeada — por
        isso reaplica-se. Também usa a resolução do ecrã como rede de segurança."""
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"{sw}x{sh}+0+0")
            self.root.attributes("-fullscreen", True)
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            self.root.geometry(f"{config.WINDOW_W}x{config.WINDOW_H}")

    def _setup_window(self):
        self.root.title("SAM — Cacifo Inteligente")
        self.root.configure(bg=self.c["bg_top"])
        if config.FULLSCREEN:
            self._apply_fullscreen()
            # Reforça após o WM mapear a janela (Pi/X11/Wayland pode ignorar à 1ª).
            for delay in (150, 600, 1500):
                self.root.after(delay, self._apply_fullscreen)
        else:
            # Janela limitada ao ecrã (margem para barra de título/tarefas),
            # PRESERVANDO o rácio para o layout não ficar esmagado.
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            aspect = config.WINDOW_W / config.WINDOW_H
            h = min(config.WINDOW_H, sh - 90)
            w = min(config.WINDOW_W, sw - 40, int(h * aspect))
            h = int(w / aspect)
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2 - 20)
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        if config.HIDE_CURSOR:
            try:
                self.root.config(cursor="none")
            except tk.TclError:
                pass

    def _pick_font_family(self):
        """Escolhe a primeira fonte disponível no sistema. Evita que o Tk
        substitua silenciosamente uma fonte inexistente (ex.: 'DejaVu Sans' no
        Windows), o que desalinhava o logótipo por métricas diferentes."""
        prefer = [
            config.FONT_FAMILY,
            "Segoe UI",
            "DejaVu Sans",
            "Helvetica",
            "Arial",
            "Liberation Sans",
        ]
        try:
            available = set(tkfont.families())
        except tk.TclError:
            return config.FONT_FAMILY
        for fam in prefer:
            if fam in available:
                return fam
        return "TkDefaultFont"

    def _setup_fonts(self):
        fam = self.font_family
        self.fonts = {
            "logo": tkfont.Font(family=fam, size=54, weight="bold"),
            "subtitle": tkfont.Font(family=fam, size=14),
            "title": tkfont.Font(family=fam, size=30, weight="bold"),
            "pin": tkfont.Font(family=fam, size=40, weight="bold"),
            "key": tkfont.Font(family=fam, size=30, weight="bold"),
            "status": tkfont.Font(family=fam, size=18),
            "big": tkfont.Font(family=fam, size=40, weight="bold"),
            "item": tkfont.Font(family=fam, size=44, weight="bold"),
            "icon": tkfont.Font(family=fam, size=90, weight="bold"),
        }

    def _scale_fonts(self):
        """Ajusta os tamanhos das fontes à resolução atual (base 1024x600)."""
        s = max(0.6, min(self.W / 1024.0, self.H / 600.0))
        base = {
            "logo": 54,
            "subtitle": 14,
            "title": 30,
            "pin": 40,
            "key": 30,
            "status": 18,
            "big": 40,
            "item": 44,
            "icon": 90,
        }
        for name, size in base.items():
            self.fonts[name].configure(size=max(9, int(size * s)))

    def _try_load_logo(self):
        """Carrega assets/logo.png (renderizado do SVG da marca) com Pillow.
        Guarda a imagem original para ser redimensionada por ecrã. Sem Pillow ou
        sem o ficheiro, o logótipo é desenhado como texto (fallback)."""
        self._logo_src = None
        self._logo_cache = {}
        try:
            import os
            from PIL import Image  # type: ignore

            path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
            if os.path.exists(path):
                self._logo_src = Image.open(path).convert("RGBA")
        except Exception:
            self._logo_src = None

    def _bind_keys(self):
        for i in range(10):
            self.root.bind(str(i), self._on_key_digit)
            # Numpad físico (NumLock ligado) envia keysyms KP_0..KP_9.
            self.root.bind(f"<KP_{i}>", self._on_key_digit)
        self.root.bind("<BackSpace>", lambda e: self._on_backspace())
        self.root.bind("<Return>", lambda e: self._on_enter())
        self.root.bind("<KP_Enter>", lambda e: self._on_enter())
        self.root.bind("<Escape>", lambda e: self._quit())
        self.root.bind("<F11>", lambda e: self._toggle_fullscreen())
        # Simulação da porta pelo teclado (modos de teste).
        self.root.bind("o", lambda e: self._sim_set_door("ABERTA"))
        self.root.bind("c", lambda e: self._sim_set_door("FECHADA"))

    def _toggle_fullscreen(self):
        is_fs = bool(self.root.attributes("-fullscreen"))
        self.root.attributes("-fullscreen", not is_fs)
        if not is_fs:
            self.root.lift()
            self.root.focus_force()

    # --------------------------------------------------------------- rendering
    def _on_resize(self, event):
        if (event.width, event.height) == self._last_size:
            return
        self._last_size = (event.width, event.height)
        self.W, self.H = event.width, event.height
        self._render()

    def _clear(self):
        for w in self._widgets:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._widgets = []
        self.canvas.delete("all")
        self._draw_background()

    def _draw_background(self):
        """Gradiente vertical azul clássico."""
        top = self.root.winfo_rgb(self.c["bg_top"])
        bot = self.root.winfo_rgb(self.c["bg_bottom"])
        steps = max(32, self.H // 4)
        for i in range(steps):
            t = i / (steps - 1)
            r = int(top[0] + (bot[0] - top[0]) * t) >> 8
            g = int(top[1] + (bot[1] - top[1]) * t) >> 8
            b = int(top[2] + (bot[2] - top[2]) * t) >> 8
            color = f"#{r:02x}{g:02x}{b:02x}"
            y1 = int(self.H * i / steps)
            y2 = int(self.H * (i + 1) / steps) + 1
            self.canvas.create_rectangle(0, y1, self.W, y2, outline="", fill=color)

    def _grad_at(self, frac):
        """Cor do gradiente à fração vertical `frac` (0=topo, 1=base). Usada
        para fundir painéis no fundo, sem retângulos visíveis."""
        frac = max(0.0, min(1.0, frac))
        top = self.root.winfo_rgb(self.c["bg_top"])
        bot = self.root.winfo_rgb(self.c["bg_bottom"])
        r = int(top[0] + (bot[0] - top[0]) * frac) >> 8
        g = int(top[1] + (bot[1] - top[1]) * frac) >> 8
        b = int(top[2] + (bot[2] - top[2]) * frac) >> 8
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw_logo(self, cx, cy):
        # Logótipo oficial (SVG → PNG), redimensionado ao ecrã e centrado.
        if getattr(self, "_logo_src", None) is not None:
            try:
                from PIL import Image, ImageTk  # type: ignore

                target_w = max(140, int(min(self.W * 0.32, self._logo_src.width)))
                photo = self._logo_cache.get(target_w)
                if photo is None:
                    ratio = target_w / self._logo_src.width
                    target_h = max(1, int(self._logo_src.height * ratio))
                    img = self._logo_src.resize((target_w, target_h), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self._logo_cache[target_w] = photo  # manter referência (GC)
                self.canvas.create_image(cx, cy, image=photo)
                return
            except Exception:
                pass
        # Fallback desenhado: "SAM" branco + barra-acento laranja centrada por
        # baixo + subtítulo. Geometria ancorada ao texto (robusta a fontes).
        logo_f = self.fonts["logo"]
        w = logo_f.measure("SAM")
        h = logo_f.metrics("linespace")
        self.canvas.create_text(cx, cy, text="SAM", font=logo_f, fill=self.c["text"])
        # Barra laranja centrada sob as letras.
        bar_w = w * 0.5
        bar_h = max(4, h * 0.09)
        bar_y = cy + h * 0.34
        _round_rect(
            self.canvas,
            cx - bar_w / 2,
            bar_y,
            cx + bar_w / 2,
            bar_y + bar_h,
            bar_h / 2,
            fill=self.c["accent"],
            outline="",
        )
        self.canvas.create_text(
            cx,
            bar_y + bar_h + h * 0.18,
            text="SISTEMA DE APOIO MUNICIPAL",
            font=self.fonts["subtitle"],
            fill=self.c["muted"],
        )

    def _draw_box_icon(self, cx, cy, size):
        """Ícone de cacifo/encomenda desenhado (sem depender de emoji)."""
        h = size
        w = size * 1.05
        x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        _round_rect(
            self.canvas,
            x1,
            y1,
            x2,
            y2,
            size * 0.10,
            fill="",
            outline=self.c["text"],
            width=max(3, int(size * 0.05)),
        )
        # "fita" horizontal e vertical da encomenda
        self.canvas.create_line(
            x1, cy, x2, cy, fill=self.c["accent"], width=max(3, int(size * 0.05))
        )
        self.canvas.create_line(
            cx, y1, cx, y2, fill=self.c["text"], width=max(2, int(size * 0.03))
        )

    def _draw_check(self, cx, cy, size):
        """Visto (checkmark) dentro de um círculo, desenhado."""
        r = size / 2
        self.canvas.create_oval(
            cx - r,
            cy - r,
            cx + r,
            cy + r,
            outline=self.c["success"],
            width=max(4, int(size * 0.06)),
        )
        w = max(5, int(size * 0.08))
        self.canvas.create_line(
            cx - r * 0.45,
            cy + r * 0.05,
            cx - r * 0.05,
            cy + r * 0.42,
            fill=self.c["success"],
            width=w,
            capstyle="round",
            joinstyle="round",
        )
        self.canvas.create_line(
            cx - r * 0.05,
            cy + r * 0.42,
            cx + r * 0.5,
            cy - r * 0.4,
            fill=self.c["success"],
            width=w,
            capstyle="round",
            joinstyle="round",
        )

    def _render(self):
        self._scale_fonts()
        self._clear()
        if self.screen == "pin":
            self._render_pin()
        elif self.screen == "deposit":
            self._render_deposit()
        elif self.screen == "success":
            self._render_success()

    # ----------------------------------------------------------- ecrã do PIN
    def _render_pin(self):
        cx = self.W / 2
        self._draw_logo(cx, self.H * 0.11)

        self.canvas.create_text(
            cx,
            self.H * 0.25,
            text="Insira o seu PIN",
            font=self.fonts["title"],
            fill=self.c["text"],
        )

        # Geometria das caixas do PIN (guardada para redesenho parcial).
        n = config.PIN_LENGTH
        box = min(self.W * 0.085, self.H * 0.095)
        gap = box * 0.35
        total = n * box + (n - 1) * gap
        x0 = cx - total / 2
        y = self.H * 0.305
        status_y = y + box + self.H * 0.04
        self._pin_geom = (cx, n, box, gap, x0, y, status_y)

        # Só as caixas + linha de estado são dinâmicas (tag "pin_dyn"); o resto
        # (fundo, logo, pinpad) fica fixo, evitando o "pisca" a cada tecla.
        self._draw_pin_dynamic()

        # Pinpad desenhado no canvas (teclas arredondadas). Por ser desenho
        # vetorial dentro do canvas, cabe sempre no ecrã e não há painéis/widgets.
        pad_top = status_y + self.H * 0.03
        pad_bottom = self.H * 0.95
        self._build_pinpad(cx, pad_top, pad_bottom - pad_top, self.W * 0.62)

    def _draw_pin_dynamic(self):
        """Desenha apenas as caixas do PIN e a linha de estado (tag pin_dyn)."""
        cx, n, box, gap, x0, y, status_y = self._pin_geom
        for i in range(n):
            x1 = x0 + i * (box + gap)
            filled = i < len(self.pin)
            edge = self.c["error"] if self.error_text else self.c["card_edge"]
            _round_rect(
                self.canvas,
                x1,
                y,
                x1 + box,
                y + box,
                box * 0.18,
                fill=self.c["card"],
                outline=edge,
                width=2,
                tags="pin_dyn",
            )
            if filled:
                self.canvas.create_text(
                    x1 + box / 2,
                    y + box / 2,
                    text=self.pin[i],
                    font=self.fonts["pin"],
                    fill=self.c["text"],
                    tags="pin_dyn",
                )
        msg = self.error_text or ("A validar…" if self.busy else "")
        color = self.c["error"] if self.error_text else self.c["muted"]
        self.canvas.create_text(
            cx,
            status_y,
            text=msg,
            font=self.fonts["status"],
            fill=color,
            tags="pin_dyn",
        )

    def _update_pin_display(self):
        """Redesenha só a parte dinâmica do ecrã do PIN (sem flicker)."""
        if self.screen != "pin" or not hasattr(self, "_pin_geom"):
            self._render()
            return
        self.canvas.delete("pin_dyn")
        self._draw_pin_dynamic()

    def _build_pinpad(self, cx, top_y, avail_h, avail_w):
        # Teclas desenhadas no canvas: dimensão derivada do espaço real, por
        # isso o pinpad é sempre proporcional e nunca sai do ecrã.
        gap = max(8, avail_h * 0.05)
        key_h = (avail_h - 3 * gap) / 4
        key_w = min((avail_w - 2 * gap) / 3, key_h * 1.45)
        grid_w = 3 * key_w + 2 * gap
        x0 = cx - grid_w / 2
        radius = max(8, key_h * 0.18)
        self._pad_font = tkfont.Font(
            family=self.font_family, size=max(14, int(key_h * 0.42)), weight="bold"
        )

        layout = [
            ("1", "d"),
            ("2", "d"),
            ("3", "d"),
            ("4", "d"),
            ("5", "d"),
            ("6", "d"),
            ("7", "d"),
            ("8", "d"),
            ("9", "d"),
            ("←", "clear"),
            ("0", "d"),
            ("OK", "ok"),
        ]
        styles = {
            #          base       active     texto       contorno
            "d": ("#1C5BB0", "#2E72C8", "#FFFFFF", "#3E7AC9"),
            "clear": ("#143F7E", "#1C5BB0", "#CFE0F5", "#2B5896"),
            "ok": ("#F28D38", "#FF9E4D", "#1A1A1A", "#FFB877"),
        }
        commands = {"ok": self._on_enter, "clear": self._on_backspace}

        self._keys = {}
        for idx, (label, kind) in enumerate(layout):
            r, col = divmod(idx, 3)
            kx = x0 + col * (key_w + gap)
            ky = top_y + r * (key_h + gap)
            base, active, fg, border = styles[kind]
            cmd = commands.get(kind, (lambda d=label: self._add_digit(d)))
            tag = f"key{idx}"
            rect = _round_rect(
                self.canvas,
                kx,
                ky,
                kx + key_w,
                ky + key_h,
                radius,
                fill=base,
                outline=border,
                width=2,
                tags=("pinkey", tag),
            )
            self.canvas.create_text(
                kx + key_w / 2,
                ky + key_h / 2,
                text=label,
                font=self._pad_font,
                fill=fg,
                tags=("pinkey", tag),
            )
            self._keys[tag] = {"rect": rect, "base": base, "active": active, "cmd": cmd}
            self.canvas.tag_bind(
                tag, "<ButtonPress-1>", lambda e, t=tag: self._key_press(t)
            )
            self.canvas.tag_bind(
                tag, "<ButtonRelease-1>", lambda e, t=tag: self._key_release(t)
            )

    def _key_press(self, tag):
        key = self._keys.get(tag)
        if key:
            self.canvas.itemconfig(key["rect"], fill=key["active"])

    def _key_release(self, tag):
        key = self._keys.get(tag)
        if not key:
            return
        self.canvas.itemconfig(key["rect"], fill=key["base"])
        key["cmd"]()

    # -------------------------------------------------------- entrada do PIN
    def _on_key_digit(self, event):
        ch = event.char
        # Fallback para o numpad: se o char vier vazio, usa a keysym KP_<n>.
        if (not ch or not ch.isdigit()) and event.keysym.startswith("KP_"):
            suffix = event.keysym[3:]
            if suffix.isdigit():
                ch = suffix
        if ch and ch.isdigit():
            self._add_digit(ch)

    def _add_digit(self, d):
        if self.screen != "pin" or self.busy:
            return
        if len(self.pin) >= config.PIN_LENGTH:
            return
        if self.error_text:
            self.error_text = ""
        self.pin += d
        self._update_pin_display()
        if len(self.pin) == config.PIN_LENGTH:
            # Auto-submissão quando o PIN fica completo (cómodo no ecrã táctil).
            self.root.after(120, self._on_enter)

    def _on_backspace(self):
        if self.screen != "pin" or self.busy:
            return
        self.error_text = ""
        self.pin = self.pin[:-1]
        self._update_pin_display()

    def _on_enter(self):
        if self.screen != "pin" or self.busy:
            return
        if len(self.pin) < config.PIN_LENGTH:
            self._flash_error("PIN incompleto")
            return
        self.busy = True
        self.error_text = ""
        self._update_pin_display()
        pin = self.pin
        self._run_async(
            lambda: self._do_verify(pin), self._on_verify_done, self._on_verify_error
        )

    def _do_verify(self, pin):
        if config.DEMO_MODE:
            time.sleep(0.4)
            if pin == config.DEMO_PIN:
                return {
                    "id_lead": 0,
                    "item_pedido": config.DEMO_ITEM,
                    "nome_cidadao": "Demonstração",
                }
            return None
        return self.client.verify_pin(pin)

    def _on_verify_done(self, result):
        self.busy = False
        if result:
            self.active_lead = result
            self.pin = ""
            self._start_deposit()
        else:
            self._flash_error("PIN inválido")
            self.pin = ""

    def _on_verify_error(self, exc):
        self.busy = False
        self.pin = ""
        # Mostra o erro real na consola para diagnóstico (SSL, DNS, timeout…).
        print(f"[verify] FALHA: {exc!r}", file=sys.stderr, flush=True)
        self._flash_error("Sem ligação ao servidor")

    def _flash_error(self, text):
        self.error_text = text
        self._render()

    # ----------------------------------------------------- fluxo de depósito
    def _start_deposit(self):
        self.screen = "deposit"
        self.deposit_substate = "wait_open"
        self.deposit_start = time.time()
        self.door_estado = "DESCONHECIDA"
        self._render()
        self._start_door_watch()

    def _render_deposit(self):
        cx = self.W / 2
        item = (self.active_lead or {}).get("item_pedido", "bem")

        self._draw_logo(cx, self.H * 0.13)

        # Ícone de cacifo/encomenda
        self._draw_box_icon(cx, self.H * 0.34, self.H * 0.16)

        self.canvas.create_text(
            cx,
            self.H * 0.52,
            text="Por favor deposite o",
            font=self.fonts["title"],
            fill=self.c["text"],
        )
        self.canvas.create_text(
            cx, self.H * 0.60, text=item, font=self.fonts["item"], fill=self.c["accent"]
        )
        self.canvas.create_text(
            cx,
            self.H * 0.68,
            text=f"no cacifo {config.LOCKER_ID}",
            font=self.fonts["title"],
            fill=self.c["text"],
        )

        # Indicador da porta
        if self.deposit_substate == "wait_open":
            instr = "Abra a porta do cacifo para colocar o bem"
        else:
            instr = "Feche a porta para concluir a doação"
        self.canvas.create_text(
            cx,
            self.H * 0.80,
            text=instr,
            font=self.fonts["status"],
            fill=self.c["muted"],
        )

        self._draw_door_badge(cx, self.H * 0.90)

    def _draw_door_badge(self, cx, cy):
        estado = self.door_estado
        if estado == "ABERTA":
            color, label = self.c["door_open"], "PORTA ABERTA"
        elif estado == "FECHADA":
            color, label = self.c["door_closed"], "PORTA FECHADA"
        else:
            color, label = self.c["door_unknown"], "A LIGAR AO SENSOR…"
        if not self.door_online and estado != "DESCONHECIDA":
            color, label = self.c["door_unknown"], "SENSOR OFFLINE"
        r = self.H * 0.015
        self.canvas.create_oval(
            cx - 110 - r, cy - r, cx - 110 + r, cy + r, fill=color, outline=""
        )
        self.canvas.create_text(
            cx - 90, cy, text=label, anchor="w", font=self.fonts["status"], fill=color
        )

    # ----------------------------------------------------- vigilância porta
    def _start_door_watch(self):
        self._door_stop.clear()
        self._door_thread = threading.Thread(target=self._door_loop, daemon=True)
        self._door_thread.start()

    def _stop_door_watch(self):
        self._door_stop.set()

    def _door_loop(self):
        while not self._door_stop.is_set():
            if config.DEMO_MODE or config.SIMULATE_DOOR:
                estado, online = self._sim_door, True
            else:
                try:
                    snap = self.client.get_door()
                    estado = str(snap.get("estado", "DESCONHECIDA")).upper()
                    online = bool(snap.get("online", False))
                except SamApiError:
                    estado, online = "DESCONHECIDA", False
            self.root.after(0, self._on_door_snapshot, estado, online)
            self._door_stop.wait(config.DOOR_POLL_MS / 1000.0)

    def _on_door_snapshot(self, estado, online):
        if self.screen != "deposit":
            return
        changed = (estado != self.door_estado) or (online != self.door_online)
        self.door_estado = estado
        self.door_online = online

        # Timeout à espera de abertura
        if (
            self.deposit_substate == "wait_open"
            and time.time() - self.deposit_start > config.DEPOSIT_TIMEOUT_S
        ):
            self._cancel_deposit("Tempo esgotado. Tente novamente.")
            return

        if self.deposit_substate == "wait_open" and estado == "ABERTA":
            self.deposit_substate = "wait_close"
            self._render()
            return
        if self.deposit_substate == "wait_close" and estado == "FECHADA":
            self.deposit_substate = "confirming"
            self._stop_door_watch()
            self._confirm_deposit()
            return
        if changed:
            self._render()

    def _cancel_deposit(self, message):
        self._stop_door_watch()
        self.active_lead = None
        self.screen = "pin"
        self._flash_error(message)

    def _confirm_deposit(self):
        lead = self.active_lead or {}
        lead_id = lead.get("id_lead", 0)

        def task():
            if config.DEMO_MODE:
                time.sleep(0.4)
                return {"confirmed": True}
            return self.client.confirm_deposit(lead_id)

        self._run_async(
            task, lambda r: self._show_success(), lambda e: self._show_success()
        )

    # --------------------------------------------------------- ecrã sucesso
    def _show_success(self):
        self.screen = "success"
        self._render()
        self.root.after(config.SUCCESS_DWELL_S * 1000, self._reset_to_pin)

    def _render_success(self):
        cx = self.W / 2
        self._draw_logo(cx, self.H * 0.16)
        self._draw_check(cx, self.H * 0.42, self.H * 0.18)
        self.canvas.create_text(
            cx,
            self.H * 0.62,
            text="Doação confirmada!",
            font=self.fonts["big"],
            fill=self.c["text"],
        )
        self.canvas.create_text(
            cx,
            self.H * 0.72,
            text="Obrigado pela sua contribuição.",
            font=self.fonts["status"],
            fill=self.c["muted"],
        )

    def _reset_to_pin(self):
        self.active_lead = None
        self.deposit_substate = None
        self.pin = ""
        self.error_text = ""
        self.screen = "pin"
        self._render()

    # ------------------------------------------------------------- utilidades
    def _sim_set_door(self, estado):
        """Simulação da porta pelo teclado (DEMO_MODE / SIMULATE_DOOR)."""
        if config.DEMO_MODE or config.SIMULATE_DOOR:
            self._sim_door = estado

    def _run_async(self, fn, on_done=None, on_error=None):
        def worker():
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - reportado à UI
                if on_error:
                    self.root.after(0, on_error, exc)
                return
            if on_done:
                self.root.after(0, on_done, result)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------- telemetria cacifo
    def _cpu_temp(self):
        """Temperatura do CPU (°C). Lê o sensor do Raspberry Pi; fora do Pi
        (ex.: Windows de desenvolvimento) devolve um valor por omissão."""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", encoding="ascii") as fh:
                return round(int(fh.read()) / 1000.0, 1)
        except Exception:
            return 45.0

    def _door_for_telemetry(self):
        if config.DEMO_MODE or config.SIMULATE_DOOR:
            return self._sim_door
        try:
            return str(self.client.get_door().get("estado", "DESCONHECIDA"))
        except SamApiError:
            return "DESCONHECIDA"

    def _push_telemetry(self):
        if self.client is None:
            return
        temp = self._cpu_temp()
        aviso = "temperatura elevada" if temp and temp > 80 else None
        payload = {
            "locker_id": config.LOCKER_ID,
            "tipo": "locker",
            "evento": "warn" if aviso else "ping",
            "geo_latitude": config.GEO_LAT,
            "geo_longitude": config.GEO_LON,
            "bateria_estado": 100,          # cacifo alimentado da rede
            "cpu_temperatura": temp,
            "dnb_sinal": 4,
            "aviso": aviso,
            "versao": config.APP_VERSION,
            # O cacifo só monitoriza o sensor da porta (o "numpad" é o ecrã
            # táctil, não um sensor de hardware).
            "status": {"sensor_porta": self._door_for_telemetry()},
        }
        self.client.send_telemetry(payload)

    def _telemetry_loop(self):
        # Envia já o primeiro registo e depois a cada TELEMETRY_MS.
        while True:
            try:
                self._push_telemetry()
            except Exception:  # noqa: BLE001 - telemetria nunca pode crashar a app
                pass
            if self._tele_stop.wait(config.TELEMETRY_MS / 1000.0):
                break

    def _start_telemetry(self):
        if config.DEMO_MODE or config.TELEMETRY_MS <= 0 or self.client is None:
            return
        self._tele_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        self._tele_thread.start()

    def _quit(self):
        self._stop_door_watch()
        self._tele_stop.set()
        self.root.destroy()


def main():
    _enable_dpi_awareness()
    # Mostra a configuração efetiva (útil quando uma variável de ambiente da
    # sessão sobrepõe o .env, ex.: SAM_BACKEND_URL apontado para localhost).
    print(
        f"[SAM cacifo] backend={config.BACKEND_URL} locker={config.LOCKER_ID} "
        f"demo={config.DEMO_MODE} simulate_door={config.SIMULATE_DOOR}",
        flush=True,
    )
    root = tk.Tk()
    LockerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
