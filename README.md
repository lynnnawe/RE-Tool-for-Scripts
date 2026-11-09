# Lyn's Debugging Tool

Ultimate debugging / analysis tool for Roblox scripts made by Lyn <3

An authorization window asks whether you own / are authorized to analyze the
target script. Everything is gated behind it. Obviously don't click yes if you do not own the script (wink wink).

## Lanes

- LOCAL (runs here via luau.exe): Deobfuscate/VM dump, Emulate in fake Roblox,
  Behavioural trace, Static lint / AST / bytecode
- EXECUTOR (paste into you're executor): Instrument & capture (stealthy), Memory scan, String-constant
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
- script_key / Live loader URL: for instrument live mode; emulate roblox also
  fetches this URL as its target source when set (falls back to the target
  field otherwise)
- run secs / out dir: capture window and executor output folder
- exec name / agent: fake identifyexecutor()/getexecutorname() identity used
  by emulate roblox (defaults to Synapse X / 2.0.0). When emulate fetches the
  url field, `agent` (falling back to `exec name`) is also sent as the
  request's `User-Agent` header, for loaders that gate on it (a common
  pattern: `Headers={["User-Agent"]="Eclipse"}`)

## PS

I tried reversing Luarmor but like, its fucking impossible and I will not succeed so yeah sorry!
