import os
import re
import sys
import queue
import threading
import subprocess
import urllib.request
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

OWNER = "Lyn"
HERE = os.path.dirname(os.path.abspath(__file__))
MODDIR = os.path.join(HERE, "modules")
SERVERDIR = os.path.join(HERE, "servers")
OUTPUT_DIR = os.path.join(HERE, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

PYCACHE_DIR = os.path.join(HERE, "__pycache__")
sys.pycache_prefix = PYCACHE_DIR
os.environ["PYTHONPYCACHEPREFIX"] = PYCACHE_DIR


def find_binary(name):
    for base in (os.path.join(HERE, "bin", "luau"), os.path.join(HERE, "bin"), HERE,
                 os.path.dirname(HERE), os.path.join(os.path.expanduser("~"), "Downloads")):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return name


LUAU = find_binary("luau.exe")
LUAU_ANALYZE = find_binary("luau-analyze.exe")
LUAU_AST = find_binary("luau-ast.exe")
LUAU_COMPILE = find_binary("luau-compile.exe")

PYENGINE_DIR = os.path.join(HERE, "pyengine")
PYENGINE_DEOBFUSCATOR = os.path.join(PYENGINE_DIR, "deobfuscator.py")

PYENGINE_MOONSEC_DIR = os.path.join(HERE, "pyengine_moonsec")
PYENGINE_MOONSEC_DEOBFUSCATOR = os.path.join(PYENGINE_MOONSEC_DIR, "moonsec_deobfuscator.py")

PYENGINE_LURAPH_DIR = os.path.join(HERE, "pyengine_luraph")
PYENGINE_LURAPH_DEOBFUSCATOR = os.path.join(PYENGINE_LURAPH_DIR, "luraph_deobfuscator.py")
PYENGINE_LURAPH_UNFLATTEN = os.path.join(PYENGINE_LURAPH_DIR, "luraph_unflatten.py")

BG = "#f0efec"
FIELD = "#ffffff"
FG = "#242422"
MUTE = "#8c8b86"
LINE = "#d9d8d3"
HOVER = "#e6e5e1"
DANGER = "#9c3a34"
UIFONT = ("Segoe UI", 10)
SMALLFONT = ("Segoe UI", 8)
MONO = ("Consolas", 10)


def read_module(name):
    with open(os.path.join(MODDIR, name), encoding="utf-8") as f:
        return f.read()


def long_bracket(s):
    level = 0
    while True:
        close = "]" + "=" * level + "]"
        if close not in s:
            break
        level += 1
    eq = "=" * level
    return "[" + eq + "[\n" + s + "\n]" + eq + "]"


def lua_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_header(**kw):
    lines = ['local OWNER = "Lyn"']
    lines.append('local OUTDIR = ' + lua_str(kw.get("outdir", "lyn_debug")))
    lines.append('local MODE = ' + lua_str(kw.get("mode", "full")))
    lines.append('local SCRIPT_KEY = ' + lua_str(kw.get("script_key", "")))
    lines.append('local LIVE_URL = ' + lua_str(kw.get("live_url", "")))
    lines.append('local RUN_SECONDS = ' + str(int(kw.get("run_seconds", 90))))
    lines.append('local SRC_FILE = ' + lua_str(kw.get("src_file", "")))
    lines.append('local FUZZ_BASE = ' + lua_str(kw.get("fuzz_base", "http://127.0.0.1:8790")))
    lines.append('local FUZZ_WS = ' + lua_str(kw.get("fuzz_ws", "ws://127.0.0.1:8790")))
    src = kw.get("target_source", "")
    if src:
        lines.append("local TARGET_SOURCE = " + long_bracket(src))
    else:
        lines.append('local TARGET_SOURCE = ""')
    return "\n".join(lines) + "\n"


class App:
    TARGET_HINT = ('a file path, a script\'s source pasted directly, a URL, or\n'
                   'loadstring(game:HttpGet("https://.../source"))()   — or click browse')

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.proc = None
        root.title("re script tool")
        root.geometry("980x660")
        root.minsize(820, 560)
        root.configure(bg=BG)
        self._build()
        self._pump()

    def _build(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 10))
        tk.Label(head, text="re script tool", bg=BG, fg=FG, font=("Segoe UI", 15)).pack(side="left")
        tk.Label(head, text="lyn <3", bg=BG, fg=MUTE, font=SMALLFONT).pack(side="right", pady=(6, 0))
        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x")

        self.loader = tk.StringVar()
        self.live_url = tk.StringVar()
        self.run_seconds = tk.StringVar(value="90")
        self.outdir = tk.StringVar(value="lyn_debug")
        self.exec_name = tk.StringVar(value="Synapse X")
        self.exec_agent = tk.StringVar(value="2.0.0")

        cfg = tk.Frame(self.root, bg=BG)
        cfg.pack(fill="x", padx=18, pady=(12, 6))

        tr = tk.Frame(cfg, bg=BG)
        tr.pack(fill="x", pady=3)
        top = tk.Frame(tr, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="target", anchor="w", bg=BG, fg=MUTE, font=SMALLFONT).pack(side="left")
        self._btn(top, "browse", lambda: self._pick(self.target), pad=(10, 0),
                  side="right", fill=None)
        wrap = tk.Frame(tr, bg=LINE, padx=1, pady=1)
        wrap.pack(fill="x", pady=(2, 0))
        self.target = tk.Text(wrap, height=4, font=MONO, bg=FIELD, fg=FG, insertbackground=FG,
                              relief="flat", bd=0, padx=8, pady=6, wrap="word")
        self.target.pack(fill="x")
        self._placeholder(self.target, self.TARGET_HINT)

        self._row(cfg, "loader", self.loader, browse=True)
        self._row(cfg, "url", self.live_url)
        r = tk.Frame(cfg, bg=BG)
        r.pack(fill="x", pady=3)
        tk.Label(r, text="secs", width=8, anchor="w", bg=BG, fg=MUTE, font=SMALLFONT).pack(side="left")
        self._entry(r, self.run_seconds, width=6).pack(side="left")
        tk.Label(r, text="out", bg=BG, fg=MUTE, font=SMALLFONT).pack(side="left", padx=(12, 4))
        self._entry(r, self.outdir, width=14).pack(side="left")

        er = tk.Frame(cfg, bg=BG)
        er.pack(fill="x", pady=3)
        tk.Label(er, text="exec name", width=8, anchor="w", bg=BG, fg=MUTE, font=SMALLFONT).pack(side="left")
        self._entry(er, self.exec_name, width=14).pack(side="left")
        tk.Label(er, text="agent", bg=BG, fg=MUTE, font=SMALLFONT).pack(side="left", padx=(12, 4))
        self._entry(er, self.exec_agent, width=14).pack(side="left")
        tk.Label(er, text="(emulate roblox: fake identity + User-Agent when fetching url)", bg=BG, fg=MUTE,
                 font=SMALLFONT).pack(side="left", padx=(12, 0))

        prog = tk.Frame(self.root, bg=BG)
        prog.pack(fill="x", padx=18, pady=(0, 4))
        self.progress_text = tk.StringVar(value="")
        tk.Label(prog, textvariable=self.progress_text, bg=BG, fg=MUTE, font=SMALLFONT).pack(side="left")
        self.progress_bar = ttk.Progressbar(prog, mode="indeterminate", length=160)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(6, 16))

        left_shell = tk.Frame(body, width=228, bg=BG)
        left_shell.pack(side="left", fill="y")
        left_shell.pack_propagate(False)

        left_canvas = tk.Canvas(left_shell, bg=BG, highlightthickness=0)
        left_scroll = tk.Scrollbar(left_shell, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_canvas.pack(side="left", fill="both", expand=True)
        left_scroll.pack(side="right", fill="y")

        left = tk.Frame(left_canvas, bg=BG)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _left_configure(_e):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        left.bind("<Configure>", _left_configure)

        def _canvas_configure(e):
            left_canvas.itemconfig(left_window, width=e.width)
        left_canvas.bind("<Configure>", _canvas_configure)

        def _mousewheel(e):
            left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        left_canvas.bind("<Enter>", lambda e: left_canvas.bind_all("<MouseWheel>", _mousewheel))
        left_canvas.bind("<Leave>", lambda e: left_canvas.unbind_all("<MouseWheel>"))

        self._group(left, "local", [
            ("run link in executor vm", self.act_execenv),
            ("deobfuscate / vm dump", self.act_deob),
            ("emulate roblox", self.act_emulate),
            ("behavioural trace", self.act_behave),
            ("lint", self.act_lint),
            ("dump ast", self.act_ast),
            ("compile bytecode", self.act_compile),
        ])
        self._group(left, "executor", [
            ("instrument", lambda: self.act_executor("instrument.luau", mode="full")),
            ("instrument (stealth)", lambda: self.act_executor("instrument.luau", mode="stealth")),
            ("memory scan", lambda: self.act_executor("memscan.luau")),
            ("extract strings", lambda: self.act_executor("strings.luau", need_target=True)),
            ("self-audit", lambda: self.act_executor("selfaudit.luau")),
            ("fuzz harness", lambda: self.act_executor("fuzz_harness.luau")),
        ])
        self._group(left, "servers", [
            ("fuzz server", lambda: self.spawn_console([sys.executable, os.path.join(SERVERDIR, "fuzz_server.py")])),
            ("header echo", lambda: self.spawn_console([sys.executable, os.path.join(SERVERDIR, "header_echo.py")])),
            ("netwatch", lambda: self.spawn_console(["powershell", "-ExecutionPolicy", "Bypass", "-File", os.path.join(SERVERDIR, "netwatch.ps1")])),
        ])
        self._group(left, "deobfuscate", [
            ("wearedevs", self.act_wearedevs),
            ("moonsecv3", self.act_moonsecv3),
            ("luraph", self.act_luraph),
            ("luraph (cleaned)", self.act_luraph_cleaned),
        ])
        tk.Frame(left, bg=BG, height=8).pack(fill="x")
        self._btn(left, "stop", self.stop_proc, danger=True)
        self._btn(left, "clear", self.clear)

        right = tk.Frame(body, bg=LINE, padx=1, pady=1)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.out = scrolledtext.ScrolledText(right, bg=FIELD, fg="#333330", insertbackground=FG,
                                             font=MONO, wrap="word", relief="flat", bd=0,
                                             padx=12, pady=10)
        self.out.pack(fill="both", expand=True)
        self.log("ready")
        self.log("select a target, then run something")
        self.log("")

    def _entry(self, parent, var, width=None):
        e = tk.Entry(parent, textvariable=var, font=UIFONT, bg=FIELD, fg=FG,
                     insertbackground=FG, relief="flat", highlightthickness=1,
                     highlightbackground=LINE, highlightcolor=MUTE)
        if width:
            e.configure(width=width)
        return e

    def _row(self, parent, label, var, browse=False):
        r = tk.Frame(parent, bg=BG)
        r.pack(fill="x", pady=3)
        tk.Label(r, text=label, width=8, anchor="w", bg=BG, fg=MUTE, font=SMALLFONT).pack(side="left")
        self._entry(r, var).pack(side="left", fill="x", expand=True)
        if browse:
            self._btn(r, "browse", lambda: self._pick(var), pad=(10, 0),
                      side="left", fill=None, padx=(6, 0))

    def _pick(self, var):
        p = filedialog.askopenfilename(filetypes=[("Luau", "*.luau *.lua"), ("All", "*.*")])
        if not p:
            return
        if isinstance(var, tk.Text):
            var.delete("1.0", "end")
            var.configure(fg=FG)
            var._empty = False
            var.insert("1.0", p)
        else:
            var.set(p)

    def _placeholder(self, widget, hint):
        widget._empty = True
        widget.insert("1.0", hint)
        widget.configure(fg=MUTE)

        def on_in(_):
            if widget._empty:
                widget.delete("1.0", "end")
                widget.configure(fg=FG)
                widget._empty = False

        def on_out(_):
            if not widget.get("1.0", "end").strip():
                widget._empty = True
                widget.insert("1.0", hint)
                widget.configure(fg=MUTE)

        widget.bind("<FocusIn>", on_in)
        widget.bind("<FocusOut>", on_out)

    def target_text(self):
        if getattr(self.target, "_empty", False):
            return ""
        return self.target.get("1.0", "end").strip()

    def _btn(self, parent, text, cmd, danger=False, pad=(12, 5), side="top", fill="x", padx=0):
        b = tk.Label(parent, text=text, anchor="w", bg=BG, fg=(DANGER if danger else FG),
                     font=UIFONT, padx=pad[0], pady=pad[1], cursor="hand2")
        b.pack(side=side, fill=fill, padx=padx)
        b.bind("<Enter>", lambda e: b.configure(bg=HOVER))
        b.bind("<Leave>", lambda e: b.configure(bg=BG))
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _group(self, parent, title, items):
        tk.Label(parent, text=title, anchor="w", bg=BG, fg=MUTE,
                 font=SMALLFONT).pack(fill="x", pady=(12, 2))
        for label, cmd in items:
            self._btn(parent, label, cmd)

    LOG_LINE_CAP = 20000
    PUMP_BATCH = 300
    STOP_BUSY = "\x00STOP_BUSY\x00"

    def start_busy(self, label):
        self.busy = True
        self.progress_text.set(label)
        self.progress_bar.pack(side="right")
        self.progress_bar.start(12)

    def stop_busy(self):
        if not getattr(self, "busy", False):
            return
        self.busy = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.progress_text.set("")

    MAX_LOG_MSG_LEN = 4000

    def log(self, s=""):
        s = str(s)
        if len(s) > self.MAX_LOG_MSG_LEN:
            s = s[:self.MAX_LOG_MSG_LEN] + f"...<truncated, {len(s)} chars total -- see the saved report/output file for the rest>"
        self.out.insert("end", s + "\n")
        if int(self.out.index("end-1c").split(".")[0]) > self.LOG_LINE_CAP:
            self.out.delete("1.0", "%d.0" % (self.LOG_LINE_CAP // 4))
        self.out.see("end")

    def clear(self):
        self.out.delete("1.0", "end")

    def _pump(self):
        drained = 0
        try:
            while drained < self.PUMP_BATCH:
                item = self.q.get_nowait()
                if item == self.STOP_BUSY:
                    self.stop_busy()
                else:
                    self.log(item)
                drained += 1
        except queue.Empty:
            pass
        self.root.after(5 if drained == self.PUMP_BATCH else 80, self._pump)

    def fetch_url(self, url, user_agent="Mozilla/5.0"):
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace")

    def get_target_source(self, required=True):
        text = self.target_text()
        if not text:
            if required:
                messagebox.showwarning("re script tool", "give me a target first")
            return None

        if os.path.isfile(text):
            with open(text, encoding="utf-8", errors="replace") as f:
                return f.read()

        low = text.lower()
        is_url = bool(re.fullmatch(r"https?://\S+", text))
        is_bootstrap = low.startswith("loadstring") and ("httpget" in low or "http_get" in low)
        if is_url or is_bootstrap:
            m = re.search(r'https?://[^\s"\'\)]+', text)
            if not m:
                return text
            url = m.group(0)
            self.log("fetching " + url)
            try:
                return self.fetch_url(url)
            except Exception as e:
                self.log("fetch failed: " + str(e))
                return None

        return text

    def to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def act_executor(self, module, mode="full", need_target=False):
        src = ""
        if need_target or self.live_url.get().strip() == "":
            src = self.get_target_source(required=need_target) or ""
        header = build_header(
            outdir=self.outdir.get().strip() or "lyn_debug",
            mode=mode,
            script_key="",
            live_url=self.live_url.get().strip(),
            run_seconds=self.run_seconds.get().strip() or "90",
            target_source=src,
        )
        payload = header + "\n" + read_module("compat.luau") + "\n" + read_module(module)
        self.to_clipboard(payload)
        self.log("%s (%s) copied, %d bytes" % (module.replace(".luau", ""), mode, len(payload)))
        self.log("paste the copied code in your executor")
        if self.live_url.get().strip():
            self.log("  fetches " + self.live_url.get().strip())
        elif src:
            self.log("  target embedded, runs under the hooks")
        else:
            self.log("  hooks only; run the target script after pasting")
        self.log("")

    def build_local_runner(self, prelude_module, src=None):
        if src is None:
            src = self.get_target_source()
        if src is None:
            return None
        parts = []
        loader = self.loader.get().strip()
        if loader and os.path.isfile(loader):
            with open(loader, encoding="utf-8", errors="replace") as f:
                parts.append(f.read())
        parts.append(read_module(prelude_module))
        parts.append(src)
        runner = os.path.join(OUTPUT_DIR, "_runner.luau")
        with open(runner, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(parts))
        return runner

    def run_local(self, prelude_module, label, save_as=None, src=None, busy_label=None):
        runner = self.build_local_runner(prelude_module, src=src)
        if not runner:
            return
        self.log(label + " ...")
        if busy_label:
            self.start_busy(busy_label)
        threading.Thread(target=self._run_luau, args=(runner, save_as), daemon=True).start()

    def _run_luau(self, runner, save_as=None):
        try:
            self.proc = subprocess.Popen([LUAU, runner], stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
                                         cwd=OUTPUT_DIR)
        except Exception as e:
            self.q.put("could not launch luau.exe: " + str(e))
            self.q.put(self.STOP_BUSY)
            return
        kept = [] if save_as else None
        for line in self.proc.stdout:
            if line.startswith("[dump-pad]"):
                continue
            line = line.rstrip("\n")
            self.q.put(line)
            if kept is not None:
                kept.append(line)
        self.proc.wait()
        self.proc = None
        if kept is not None:
            report_path = os.path.join(OUTPUT_DIR, save_as)
            with open(report_path, "w", encoding="utf-8", newline="") as f:
                f.write("\n".join(kept))
            self.q.put("")
            self.q.put("report saved: " + report_path)
            try:
                os.startfile(report_path)
            except Exception:
                pass
        self.q.put("done")
        self.q.put("")
        self.q.put(self.STOP_BUSY)

    def stop_proc(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.log("stopped")
        self.stop_busy()

    def act_execenv(self):
        self.run_local("execenv.luau", "executor vm")

    def act_deob(self):
        self.run_local("deob_prelude.luau", "deobfuscate")

    def act_emulate(self):
        live_url = self.live_url.get().strip()
        if live_url:
            ua = self.exec_agent.get().strip() or self.exec_name.get().strip() or "Synapse X"
            self.log("fetching " + live_url + '  (User-Agent: "%s")' % ua)
            try:
                src = self.fetch_url(live_url, user_agent=ua)
            except Exception as e:
                self.log("fetch failed: " + str(e))
                return
        else:
            src = self.get_target_source()
            if src is None:
                return

        header = ('local EXECUTOR_NAME = ' + lua_str(self.exec_name.get().strip() or "Synapse X") + "\n"
                   + 'local EXECUTOR_AGENT = ' + lua_str(self.exec_agent.get().strip() or "2.0.0") + "\n")
        parts = [header]
        loader = self.loader.get().strip()
        if loader and os.path.isfile(loader):
            with open(loader, encoding="utf-8", errors="replace") as f:
                parts.append(f.read())
        parts.append(read_module("emulate.luau"))
        parts.append(src)
        runner = os.path.join(OUTPUT_DIR, "_runner.luau")
        with open(runner, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(parts))

        self.log("emulate roblox ...")
        self.log("  executor identity: %s / %s" % (self.exec_name.get().strip() or "Synapse X",
                                                     self.exec_agent.get().strip() or "2.0.0"))
        threading.Thread(target=self._run_luau, args=(runner,), daemon=True).start()

    def act_behave(self):
        self.run_local("behave.luau", "behavioural trace")

    def run_static(self, binary, label, extra=None):
        p = self.target.get().strip()
        if not p or not os.path.isfile(p):
            messagebox.showwarning("re script tool", "select a target script first")
            return
        cmd = [binary] + (extra or []) + [p]
        self.log(label + " ...")
        threading.Thread(target=self._run_static, args=(cmd,), daemon=True).start()

    def _run_static(self, cmd):
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, errors="replace", bufsize=1)
        except Exception as e:
            self.q.put("could not launch: " + str(e))
            return
        for line in self.proc.stdout:
            self.q.put(line.rstrip("\n"))
        self.proc.wait()
        self.q.put("done")
        self.q.put("")
        self.proc = None

    def act_lint(self):
        self.run_static(LUAU_ANALYZE, "lint")

    def act_ast(self):
        self.run_static(LUAU_AST, "dump ast")

    def act_compile(self):
        self.run_static(LUAU_COMPILE, "compile bytecode", extra=["-O2"])

    def act_wearedevs(self):
        text = self.target_text()
        if not text:
            messagebox.showwarning("re script tool", "give me a target first")
            return

        if os.path.isfile(text):
            path = text
        else:
            src = self.get_target_source(required=True)
            if src is None:
                return
            path = os.path.join(OUTPUT_DIR, "_wearedevs_target.lua")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(src)

        self.log("deobfuscating target (wearedevs) ...")
        self.start_busy("wearedevs deobfuscator running...")
        threading.Thread(target=self._run_deobfuscator, args=(path, PYENGINE_DEOBFUSCATOR, PYENGINE_DIR,
                                                               "Prometheus/WeAreDevs-style"), daemon=True).start()

    def act_moonsecv3(self):
        text = self.target_text()
        if not text:
            messagebox.showwarning("re script tool", "give me a target first")
            return

        if os.path.isfile(text):
            path = text
        else:
            src = self.get_target_source(required=True)
            if src is None:
                return
            path = os.path.join(OUTPUT_DIR, "_moonsecv3_target.lua")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(src)

        self.log("deobfuscating target (moonsecv3) ...")
        self.start_busy("moonsecv3 deobfuscator running...")
        threading.Thread(target=self._run_deobfuscator, args=(path, PYENGINE_MOONSEC_DEOBFUSCATOR,
                                                               PYENGINE_MOONSEC_DIR, "MoonSecV3"), daemon=True).start()

    def act_luraph(self):
        text = self.target_text()
        if not text:
            messagebox.showwarning("re script tool", "give me a target first")
            return

        if os.path.isfile(text):
            path = text
        else:
            src = self.get_target_source(required=True)
            if src is None:
                return
            path = os.path.join(OUTPUT_DIR, "_luraph_target.lua")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(src)

        self.log("deobfuscating target (luraph) ...")
        self.log("traces real game/API/global/loadstring activity under a sandboxed Luau env "
                  "and reconstructs it as pseudo-Lua, same technique as moonsecv3 -- pure "
                  "internal VM computation that never touches something observable stays "
                  "invisible, and a nested loadstring'd wrapper gets saved as its own "
                  ".stageN.lua for you to re-run this on, one layer at a time.")
        self.start_busy("luraph deobfuscator running...")
        threading.Thread(target=self._run_deobfuscator, args=(path, PYENGINE_LURAPH_DEOBFUSCATOR,
                                                               PYENGINE_LURAPH_DIR, "Luraph"), daemon=True).start()

    def act_luraph_cleaned(self):
        text = self.target_text()
        if not text:
            messagebox.showwarning("re script tool", "give me a target first")
            return

        if os.path.isfile(text):
            path = text
        else:
            src = self.get_target_source(required=True)
            if src is None:
                return
            path = os.path.join(OUTPUT_DIR, "_luraph_target.lua")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(src)

        base = os.path.basename(path)
        stage_re = re.compile(r"^" + re.escape(base) + r"\.stage\d+\.lua$")
        stage_paths = []
        try:
            for fname in sorted(os.listdir(OUTPUT_DIR)):
                if stage_re.match(fname):
                    stage_paths.append(os.path.join(OUTPUT_DIR, fname))
        except OSError:
            pass
        queue = [path] + stage_paths

        self.log("un-flattening target (luraph cleaned) ...")
        if stage_paths:
            self.log(f"also found {len(stage_paths)} already-extracted stage file(s) from a prior "
                      f"'luraph' run -- cleaning those too: " + ", ".join(os.path.basename(p) for p in stage_paths))
        self.log("a purely static, no-execution pass: finds `while true do <numeric-state "
                  "dispatch> end` control-flow-flattening (Luraph's own outer loader uses this, "
                  "and so do plenty of its unpacked stages) and mechanically converts it into a "
                  "table of small named functions driven by one real while-loop, instead of the "
                  "deeply nested if-chain. Verified byte-for-byte identical behavior against a "
                  "real sample before this was wired in here. This does NOT recover original "
                  "names/comments (permanently gone) and can't touch a custom byte-level VM "
                  "(that's the OTHER kind of Luraph obfuscation, not this one). Any matching "
                  ".keymap.txt from a prior 'luraph' run gets merged in too.")
        self.start_busy("un-flattening...")
        threading.Thread(target=self._run_unflatten, args=(queue,), daemon=True).start()

    def _run_unflatten(self, paths):
        last_out_path = None
        for path in paths:
            out_path = os.path.join(OUTPUT_DIR, os.path.basename(path) + ".cleaned.lua")
            cmd = [sys.executable, PYENGINE_LURAPH_UNFLATTEN, path, out_path]
            try:
                self.proc = subprocess.Popen(cmd, cwd=PYENGINE_LURAPH_DIR, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
            except Exception as e:
                self.q.put(f"could not launch the un-flattener on {path}: {e}")
                continue
            self.q.put(f"-- cleaning {os.path.basename(path)} --")
            for line in self.proc.stdout:
                self.q.put(line.rstrip("\n"))
            self.proc.wait()
            self.proc = None
            if os.path.isfile(out_path):
                last_out_path = out_path
            self.q.put("")

        if last_out_path:
            self.q.put("cleaned output (deepest/last file processed): " + last_out_path)
            try:
                os.startfile(last_out_path)
            except Exception:
                pass
        else:
            self.q.put("no cleaned file produced - see log above")
        self.q.put("done")
        self.q.put("")
        self.q.put(self.STOP_BUSY)

    def _run_deobfuscator(self, path, engine_script, engine_cwd, label):
        cmd = [sys.executable, engine_script, path, OUTPUT_DIR]
        try:
            self.proc = subprocess.Popen(cmd, cwd=engine_cwd, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        except Exception as e:
            self.q.put("could not launch deobfuscator: " + str(e))
            self.q.put(self.STOP_BUSY)
            return
        final_path = None
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            self.q.put(line)
            if line.startswith("FINAL_DEOBF_PATH --> "):
                final_path = line.split("FINAL_DEOBF_PATH --> ", 1)[1].strip()
        self.proc.wait()
        self.proc = None

        base = os.path.join(OUTPUT_DIR, os.path.basename(path))
        deobf_path = final_path or (base + ".deobf.lua")
        report_path = deobf_path.replace(".deobf.lua", ".report.txt")
        readable_path = deobf_path.replace(".deobf.lua", ".readable.lua")
        self.q.put("")
        if os.path.isfile(deobf_path):
            self.q.put("deobfuscated output: " + deobf_path)
            if os.path.isfile(report_path):
                self.q.put("full trace report: " + report_path)
            open_path = deobf_path
            if os.path.isfile(readable_path):
                try:
                    trivial = os.path.getsize(deobf_path) < 200
                except OSError:
                    trivial = False
                if trivial:
                    self.q.put("deobfuscated output is near-empty (nothing observable was traced) -- "
                                "opening the readable annotated source instead: " + readable_path)
                    open_path = readable_path
                else:
                    self.q.put("readable annotated source: " + readable_path)
            try:
                os.startfile(open_path)
            except Exception:
                pass
        else:
            self.q.put("no .deobf.lua produced - see log above "
                        f"(this engine targets {label} obfuscation)")
        self.q.put("done")
        self.q.put("")
        self.q.put(self.STOP_BUSY)

    def spawn_console(self, cmd):
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        try:
            subprocess.Popen(cmd, creationflags=flags)
            self.log("started in a new window")
        except Exception as e:
            self.log("failed: " + str(e))


def gate(root):
    return messagebox.askyesno(
        "re script tool",
        "Are you the owner of, or authorized to analyze, the script you're\n"
        "about to work on?",
        parent=root)


def main():
    root = tk.Tk()
    root.withdraw()
    if not gate(root):
        root.destroy()
        return
    root.deiconify()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
