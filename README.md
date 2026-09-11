# Lyn's Debugging Tool

Ultimate debugging / analysis tool for Roblox scripts made by Lyn <3

An authorization window asks whether you own / are authorized to analyze the
target script. Everything is gated behind it. Executor-side scripts self-gate
again with a message box on executors that expose one

## Lanes

- LOCAL (runs here via luau.exe): Deobfuscate/VM dump, Emulate in fake Roblox,
  Behavioural trace, Static lint / AST / bytecode
- EXECUTOR (copies a single script to your clipboard; paste it in your
  executor): Instrument & capture (full/stealth), Memory scan, String-constant
  extractor, Self-audit, Parser fuzz harness
- SERVERS: fuzz server, header echo, netwatch

## Any script / any executor

Executor scripts are prefixed with a compatibility core that feature-detects
across executor API name variants (request/http_request/syn.request,
hookfunction/replaceclosure/detour, getgc/get_gc_objects,
setreadonly/make_writeable, WebSocket/syn.websocket, and more). Local runs let
you optionally prepend a loader file, then the chosen prelude, then your target

## Config fields

- Target script: the file under analysis
- Optional loader/prelude to prepend (local runs)
- script_key / Live loader URL: for instrument live mode
- run secs / out dir: capture window and executor output folder

- ## Deobfuscator

- Wearedevs
- MoonsecV3
- luarmor next trusttrusttrust
