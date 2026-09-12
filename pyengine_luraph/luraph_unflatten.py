"""
"luraph (cleaned)" engine: mechanically un-flattens the numeric-state-machine
control-flow obfuscation pattern common in Luraph output (and control-flow
flattening generally), WITHOUT trying to guess/reconstruct if/while nesting.

The pattern looks like:
    local y = 16
    while true do
        if y <= 7 then
            if y <= 3 then ... y = 9 ...
            elseif y <= 2 then ... y = 1 ...
            else ... end
        elseif y <= 11 then ...
        ...
        end
    end

Instead of solving the (genuinely hard, sometimes ambiguous for
data-dependent branches) problem of reconstructing structured if/while code
from this, this converts each reachable state into its own local function,
and replaces "set the state variable to N and loop" with a real Lua tail
call `return state_N()`. Proper tail calls in Lua/Luau make this exactly
semantically equivalent to the original -- not an approximation -- while
eliminating the deeply nested if-chain entirely in favor of separate, named,
sequentially-readable functions.

Luau does not support goto/labels (confirmed by direct testing -- this is a
deliberate Luau deviation from standard Lua), which is why this uses tail
calls rather than the goto-based transform that would be the obvious choice
in stock Lua 5.2+.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)


def get_luau_ast_executable():
    if os.name == "nt":
        candidate = os.path.join(PROJECT_ROOT, "bin", "luau", "luau-ast.exe")
        if os.path.isfile(candidate):
            return candidate
    return "luau-ast"


_LINE_STARTS = None


def set_line_index(content):
    """luau-ast reports locations as (line, column), both 0-indexed, with
    column relative to the start of THAT line -- not a flat file offset.
    Precompute each line's starting absolute offset so locations can be
    converted correctly for a real multi-line file (this file's own test
    suite caught this: it only looked correct against da0.lua because that
    entire file happens to be on a single line)."""
    global _LINE_STARTS
    starts = [0]
    for line in content.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    _LINE_STARTS = starts


def parse_loc(loc):
    a, b = loc.split(" - ")
    al, ac = map(int, a.split(","))
    bl, bc = map(int, b.split(","))
    return _LINE_STARTS[al] + ac, _LINE_STARTS[bl] + bc


def walk(node, cb, stop_at_function=False):
    if isinstance(node, dict):
        if stop_at_function and node.get("type") in ("AstExprFunction",):
            return
        cb(node)
        for v in node.values():
            walk(v, cb, stop_at_function)
    elif isinstance(node, list):
        for item in node:
            walk(item, cb, stop_at_function)


CMP_OPS = {"CompareLe", "CompareLt", "CompareGe", "CompareGt", "CompareEq", "CompareNe"}


def is_dispatch_condition(cond, statevar_loc):
    """True if `cond` is (statevar OP constant) or (constant OP statevar)."""
    if not isinstance(cond, dict) or cond.get("type") != "AstExprBinary":
        return False
    if cond.get("op") not in CMP_OPS:
        return False
    left, right = cond["left"], cond["right"]

    def is_statevar(n):
        return isinstance(n, dict) and n.get("type") == "AstExprLocal" and n["local"]["location"] == statevar_loc

    def is_const(n):
        return isinstance(n, dict) and n.get("type") == "AstExprConstantNumber"

    return (is_statevar(left) and is_const(right)) or (is_const(left) and is_statevar(right))


def eval_condition(cond, statevar_loc, testval):
    left, right = cond["left"], cond["right"]

    def val(n):
        if n.get("type") == "AstExprConstantNumber":
            return n["value"]
        return testval

    lv, rv = val(left), val(right)
    op = cond["op"]
    if op == "CompareLe":
        return lv <= rv
    if op == "CompareLt":
        return lv < rv
    if op == "CompareGe":
        return lv >= rv
    if op == "CompareGt":
        return lv > rv
    if op == "CompareEq":
        return lv == rv
    if op == "CompareNe":
        return lv != rv
    raise ValueError(op)


def resolve_leaf(node, statevar_loc, testval):
    """Walk down the if/elseif/else chain for a specific candidate state
    value and return the terminal leaf's list of statements."""
    while True:
        if isinstance(node, dict) and node.get("type") == "AstStatIf":
            cond = node["condition"]
            if not is_dispatch_condition(cond, statevar_loc):
                return None
            taken = eval_condition(cond, statevar_loc, testval)
            branch = node["thenbody"] if taken else node.get("elsebody")
            if branch is None:
                return []
            node = branch
            continue
        body = node.get("body") if isinstance(node, dict) and "type" in node and node.get("type") == "AstStatBlock" else node
        if isinstance(body, dict) and body.get("type") == "AstStatIf":
            node = body
            continue
        if isinstance(node, dict) and node.get("type") == "AstStatIf":
            node = node
            continue
        if isinstance(node, dict) and "body" in node:
            stmts = node["body"]
        else:
            stmts = node if isinstance(node, list) else [node]
        if len(stmts) == 1 and isinstance(stmts[0], dict) and stmts[0].get("type") == "AstStatIf" \
                and is_dispatch_condition(stmts[0]["condition"], statevar_loc):
            node = stmts[0]
            continue
        return stmts


def find_local_initial_value(ast_root, statevar_loc):
    """The state variable's value at its own `local` declaration, so the
    un-flattened code knows which state function to call first."""
    found = []

    def visit(node):
        if not isinstance(node, dict) or node.get("type") != "AstStatLocal":
            return
        for i, v in enumerate(node["vars"]):
            if v["location"] == statevar_loc:
                values = node.get("values", [])
                if i < len(values):
                    found.append(values[i])

    walk(ast_root, visit)
    if found and found[0].get("type") == "AstExprConstantNumber":
        return found[0]["value"]
    return None


def find_dispatch_whiles(ast_root):
    """Find every `while true do <if-chain on one local> end` with enough
    branches to be worth un-flattening."""
    results = []

    def visit(node):
        if not isinstance(node, dict) or node.get("type") != "AstStatWhile":
            return
        cond = node.get("condition", {})
        if not (cond.get("type") == "AstExprConstantBool" and cond.get("value") is True):
            return
        body = node["body"]["body"] if "body" in node["body"] else node["body"]
        if len(body) != 1 or not isinstance(body[0], dict) or body[0].get("type") != "AstStatIf":
            return
        top_if = body[0]
        cond0 = top_if["condition"]
        if not isinstance(cond0, dict) or cond0.get("type") != "AstExprBinary":
            return
        statevar = None
        for side in (cond0.get("left"), cond0.get("right")):
            if isinstance(side, dict) and side.get("type") == "AstExprLocal":
                statevar = side["local"]
                break
        if statevar is None:
            return
        results.append({"while_node": node, "top_if": top_if, "statevar": statevar})

    walk(ast_root, visit)
    return results


def collect_constants(node, statevar_loc, acc):
    """Gather every constant this dispatch chain compares the state var
    against, to know the candidate state values worth testing."""
    if isinstance(node, dict) and node.get("type") == "AstStatIf":
        cond = node["condition"]
        if is_dispatch_condition(cond, statevar_loc):
            for side in (cond["left"], cond["right"]):
                if side.get("type") == "AstExprConstantNumber":
                    acc.add(side["value"])
            collect_constants(node["thenbody"], statevar_loc, acc)
            if node.get("elsebody"):
                collect_constants(node["elsebody"], statevar_loc, acc)
        return
    stmts = node["body"] if isinstance(node, dict) and "body" in node else (node if isinstance(node, list) else [node])
    if len(stmts) == 1 and isinstance(stmts[0], dict) and stmts[0].get("type") == "AstStatIf":
        collect_constants(stmts[0], statevar_loc, acc)


def enumerate_states(top_if, statevar):
    """Brute-force every candidate integer near the seen constants to map
    state-number -> its terminal leaf (as an identity-keyed dict, since two
    different state numbers can share the exact same leaf list object when
    a branch handles more than one state)."""
    consts = set()
    collect_constants(top_if, statevar["location"], consts)
    if not consts:
        return {}
    lo, hi = min(0, int(min(consts))), int(max(consts)) + 2
    state_to_leaf = {}
    for v in range(lo, hi):
        leaf = resolve_leaf(top_if, statevar["location"], v)
        if leaf is not None:
            state_to_leaf[v] = id(leaf)
    return state_to_leaf, {id(resolve_leaf(top_if, statevar["location"], v)): resolve_leaf(top_if, statevar["location"], v) for v in state_to_leaf}


ASSIGN_TYPES = ("AstStatAssign",)


def find_state_assigns(stmts, statevar_loc):
    """Every AstStatAssign anywhere in `stmts` (recursing into nested
    if/do/while/repeat but NOT into nested function bodies, which have
    their own separate scope) that targets the state variable."""
    found = []

    def visit(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "AstStatAssign":
            for i, v in enumerate(node["vars"]):
                if v.get("type") == "AstExprLocal" and v["local"]["location"] == statevar_loc:
                    found.append((node, i))
                    break

    walk(stmts, visit, stop_at_function=True)
    return found


def render_expr(node, content):
    if not isinstance(node, dict):
        return repr(node)
    sc, ec = parse_loc(node["location"])
    return content[sc:ec]


def is_and_or_ternary(value_node):
    """Detect Lua's `COND and A or B` idiom compiled as nested AstExprBinary
    (op=Or, left=(op=And, left=COND, right=A), right=B), where A and B are
    both constant numbers -- the only shape this can safely convert to an
    `if COND then return state_A() else return state_B() end`."""
    if not isinstance(value_node, dict) or value_node.get("type") != "AstExprBinary" or value_node.get("op") != "Or":
        return None
    left, right = value_node["left"], value_node["right"]
    if not (isinstance(left, dict) and left.get("type") == "AstExprBinary" and left.get("op") == "And"):
        return None
    if right.get("type") != "AstExprConstantNumber":
        return None
    a_side = left["right"]
    if a_side.get("type") != "AstExprConstantNumber":
        return None
    return left["left"], a_side["value"], right["value"]


def leaf_span(stmts):
    if not stmts:
        return None
    sc, _ = parse_loc(stmts[0]["location"])
    _, ec = parse_loc(stmts[-1]["location"])
    return sc, ec


def transform_leaf(stmts, statevar_loc, content, fname_of, all_states, warnings):
    """Return the transformed source text for one leaf's statement list,
    with every assignment to the state variable replaced by a real Lua tail
    call to the corresponding state function."""
    if not stmts:
        return ""
    sc, ec = leaf_span(stmts)
    body_text = content[sc:ec]
    edits = []

    for node, idx in find_state_assigns(stmts, statevar_loc):
        vars_, values = node["vars"], node["values"]
        target_value = values[idx] if idx < len(values) else None
        leftover_pairs = [(v, val) for i, (v, val) in enumerate(zip(vars_, values)) if i != idx]
        leftover_text = ""
        if leftover_pairs:
            vtext = ", ".join(render_expr(v, content) for v, _ in leftover_pairs)
            valtext = ", ".join(render_expr(val, content) for _, val in leftover_pairs)
            leftover_text = f"{vtext} = {valtext}; "

        if target_value is None:
            continue
        if target_value.get("type") == "AstExprConstantNumber":
            n = target_value["value"]
            repl = f"{leftover_text}return {n};"
        else:
            ternary = is_and_or_ternary(target_value)
            if ternary:
                cond_node, a, b = ternary
                cond_text = render_expr(cond_node, content)
                repl = f"{leftover_text}if {cond_text} then return {a} else return {b} end"
            else:
                val_text = render_expr(target_value, content)
                repl = f"{leftover_text}return ({val_text});"

        node_sc, node_ec = parse_loc(node["location"])
        edits.append((node_sc, node_ec, " " + repl + " "))

    def find_returns(n):
        if isinstance(n, dict) and n.get("type") == "AstStatReturn":
            vals = n.get("list", [])
            val_text = ", ".join(render_expr(v, content) for v in vals)
            repl = "return nil, " + val_text if vals else "return nil"
            rsc, rec = parse_loc(n["location"])
            edits.append((rsc, rec, " " + repl + " "))
    walk(stmts, find_returns, stop_at_function=True)

    has_break = [False]

    def find_break(n):
        if isinstance(n, dict) and n.get("type") == "AstStatBreak":
            has_break[0] = True
            bsc, bec = parse_loc(n["location"])
            edits.append((bsc, bec, " return nil "))
    walk(stmts, find_break, stop_at_function=True)
    if has_break[0]:
        warnings.append("a leaf contains a 'break' -- converted to 'return nil' (best effort: ends the state "
                         "machine with no value, since the loop it used to break out of no longer exists)")

    edits.sort(key=lambda e: -e[0])
    text = body_text
    base = sc
    for node_sc, node_ec, repl in edits:
        rel_s, rel_e = node_sc - base, node_ec - base
        text = text[:rel_s] + repl + text[rel_e:]

    last_stmt = stmts[-1]
    ends_terminal = last_stmt.get("type") in ("AstStatReturn", "AstStatBreak")
    if last_stmt.get("type") == "AstStatAssign":
        for v in last_stmt["vars"]:
            if v.get("type") == "AstExprLocal" and v["local"]["location"] == statevar_loc:
                ends_terminal = True
                break

    return text, ends_terminal


def unflatten_one(dispatch, content, warnings, dispatch_index=0):
    statevar = dispatch["statevar"]
    top_if = dispatch["top_if"]
    while_node = dispatch["while_node"]

    state_to_leafid, leafid_to_stmts = enumerate_states(top_if, statevar)
    if not state_to_leafid:
        return None

    leafid_to_states = {}
    for n, lid in state_to_leafid.items():
        leafid_to_states.setdefault(lid, []).append(n)

    tblname = f"__states{dispatch_index}"
    pieces = []
    all_state_numbers = []
    for lid, states in sorted(leafid_to_states.items(), key=lambda kv: min(kv[1])):
        stmts = leafid_to_stmts[lid]
        primary = min(states)
        body_text, ends_terminal = transform_leaf(stmts, statevar["location"], content, None, None, warnings)
        if not ends_terminal:
            body_text = body_text.rstrip()
            if body_text and not body_text.endswith(";"):
                body_text += ";"
            body_text += f" return {primary};"
        entry = f"{tblname}[{primary}] = function()\n{body_text}\nend"
        pieces.append(entry)
        all_state_numbers.append(primary)
        for n in states:
            if n != primary:
                pieces.append(f"{tblname}[{n}] = {tblname}[{primary}]")

    initial = dispatch["initial_state"]
    trampoline = (
        f"local {tblname} = {{}}\n"
        + "\n".join(pieces)
        + f"\nlocal __st{dispatch_index} = {initial}\n"
        f"while true do\n"
        f"    local __r{dispatch_index} = table.pack({tblname}[__st{dispatch_index}]())\n"
        f"    if __r{dispatch_index}[1] == nil then return table.unpack(__r{dispatch_index}, 2, __r{dispatch_index}.n) end\n"
        f"    __st{dispatch_index} = __r{dispatch_index}[1]\n"
        f"end"
    )

    wc, wec = parse_loc(while_node["location"])
    return wc, wec, "\n" + trampoline + "\n"


def unflatten_source(content, filepath):
    ast_json_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lua", delete=False, encoding="utf-8") as tf:
            tf.write(content)
            src_path = tf.name
        result = subprocess.run([get_luau_ast_executable(), src_path], capture_output=True,
                                encoding="utf-8", errors="replace", timeout=60)
        if result.returncode != 0:
            return None, [], [f"luau-ast failed to parse this file: {result.stderr.strip()[:500]}"]
        ast = json.loads(result.stdout)
        set_line_index(content)
    finally:
        if ast_json_path and os.path.exists(ast_json_path):
            os.remove(ast_json_path)
        try:
            os.remove(src_path)
        except Exception:
            pass

    dispatches = find_dispatch_whiles(ast["root"])
    if not dispatches:
        return content, [], ["no `while true do <numeric-state dispatch> end` pattern found -- nothing to un-flatten in this file"]

    warnings = []
    edits = []
    notes = []
    for i, d in enumerate(dispatches, start=1):
        initial = find_local_initial_value(ast["root"], d["statevar"]["location"])
        if initial is None:
            warnings.append(f"dispatch loop #{i} at {d['while_node']['location']}: couldn't statically determine the "
                             f"state variable's initial value -- skipped")
            continue
        d["initial_state"] = initial
        result = unflatten_one(d, content, warnings, dispatch_index=i)
        if result is None:
            warnings.append(f"dispatch loop #{i} at {d['while_node']['location']}: state enumeration failed -- skipped")
            continue
        sc, ec, replacement = result
        edits.append((sc, ec, replacement))
        notes.append(f"un-flattened dispatch loop #{i} at char {sc} into {replacement.count('function()')} state function(s)")

    if not edits:
        return content, notes, warnings

    edits.sort(key=lambda e: -e[0])
    out = content
    for sc, ec, repl in edits:
        out = out[:sc] + repl + out[ec:]
    return out, notes, warnings


def apply_keymap_annotations(content, keymap_path):
    """Splice in the auto-discovered key -> real-function comments (from a
    prior `luraph` run's .keymap.txt) on top of the un-flattened source, so
    the one output file carries both cleanups instead of making someone
    cross-reference two separate files."""
    key_map = {}
    for line in open(keymap_path, encoding="utf-8", errors="replace"):
        m = re.match(r"\[(\S+)\] = (\S+)", line.strip())
        if m:
            key_map[m.group(1)] = m.group(2)
    if not key_map:
        return content, 0

    def repl(mo):
        name = key_map.get(mo.group(1))
        return f"[{mo.group(1)}--[[{name}]]]" if name else mo.group(0)

    return re.sub(r"\[(\d+)\]", repl, content), len(key_map)


def main():
    if len(sys.argv) < 3:
        print("usage: luraph_unflatten.py <input.lua> <output.lua>")
        sys.exit(1)
    in_path, out_path = sys.argv[1], sys.argv[2]
    content = open(in_path, encoding="utf-8", errors="replace").read()
    out, notes, warnings = unflatten_source(content, in_path)
    for n in notes:
        print("[+] " + n)
    for w in warnings:
        print("[!] " + w)
    if out is None:
        print("FAILED: could not parse input as Luau")
        sys.exit(1)

    keymap_path = in_path + ".keymap.txt"
    if not os.path.isfile(keymap_path):
        keymap_path = os.path.join(os.path.dirname(out_path) or ".", os.path.basename(in_path) + ".keymap.txt")
    if os.path.isfile(keymap_path):
        out, n_keys = apply_keymap_annotations(out, keymap_path)
        if n_keys:
            print(f"[+] merged in {n_keys} key -> real-function annotations from {keymap_path}")

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
