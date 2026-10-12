"""Find the places first-party page scripts write markup, read WHOLE (#548).

A line-wise ``grep innerHTML | grep '${'`` finds a tenth of these: a template
literal usually opens on the ``innerHTML =`` line and interpolates on the lines
below it, which is exactly where #324's ``${chip.label}`` sat. So this reads
each sink's right-hand side as one expression -- strings, template literals,
nested ``${...}`` and comments tracked -- and reports what it interpolates.

It is an instrument for the sweep and for ``tests/test_web_escaping.py``, not a
judge: whether an interpolation is a defect depends on whether a student can
put text in it, which no scanner can know.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / 'src' / 'web' / 'js'
VENDORED = ('lib',)

#: `x.innerHTML = …`, `x.innerHTML += …`, `x.outerHTML = …`, and
#: `x.insertAdjacentHTML(pos, …)`. Not `==`/`===` (a comparison).
SINK = re.compile(
    r"\.(?P<prop>innerHTML|outerHTML)\s*(?P<op>\+?=)(?!=)"
    r"|\.(?P<call>insertAdjacentHTML)\s*\(")


@dataclass
class Sink:
    path: Path
    line: int
    kind: str
    expression: str
    interpolations: List[str] = field(default_factory=list)
    concatenates: bool = False

    @property
    def interpolates(self) -> bool:
        return bool(self.interpolations) or self.concatenates

    def where(self) -> str:
        return f'{self.path.relative_to(ROOT)}:{self.line}'


def first_party_js() -> List[Path]:
    return sorted(p for p in WEB_JS.rglob('*.js')
                  if not any(part in VENDORED for part in p.relative_to(WEB_JS).parts))


def _read_expression(text: str, start: int, *, call: bool) -> tuple[str, List[str], bool]:
    """Read from ``start`` to the end of the expression.

    For an assignment that is the first ``;`` (or a newline that cannot
    continue the expression) at depth 0; for ``insertAdjacentHTML(`` it is the
    closing parenthesis. Returns (expression, ``${}`` bodies, whether a ``+``
    joins a non-literal at depth 0).
    """
    i, n = start, len(text)
    depth = 1 if call else 0
    out: List[str] = []
    interps: List[str] = []
    concat = False
    stack: List[str] = []          # template-literal / ${ nesting
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        mode = stack[-1] if stack else None
        if mode == '`':
            if c == '\\':
                out.append(text[i:i + 2]); i += 2; continue
            if two == '${':
                stack.append('${'); out.append(two); i += 2
                interps.append('')
                continue
            if c == '`':
                stack.pop(); out.append(c); i += 1; continue
            out.append(c); i += 1; continue
        # code (top level or inside ${ })
        if two == '//':
            j = text.find('\n', i); j = n if j < 0 else j
            i = j; continue
        if two == '/*':
            j = text.find('*/', i + 2); j = n if j < 0 else j + 2
            i = j; continue
        if c in '\'"':
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == '\\' else 1
            out.append(text[i:j + 1])
            if stack and stack[-1] == '${':
                interps[-1] += text[i:j + 1]
            i = j + 1; continue
        if c == '`':
            stack.append('`'); out.append(c); i += 1; continue
        if mode == '${':
            if c == '{':
                stack.append('{')
            elif c == '}':
                stack.pop(); out.append(c); i += 1; continue
            interps[-1] += c
            out.append(c); i += 1; continue
        if mode == '{':
            if c == '}':
                stack.pop()
            elif c == '{':
                stack.append('{')
            if stack and stack[-1] == '${' or (stack and stack[-1] == '{'):
                pass
            # keep collecting into the enclosing ${ if there is one
            for m in reversed(stack):
                if m == '${':
                    interps[-1] += c
                    break
            out.append(c); i += 1; continue
        # depth-0 code
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
            if call and depth == 0:
                break
        elif c == ';' and depth == 0:
            break
        elif c == '+' and depth == (1 if call else 0):
            concat = True
        out.append(c); i += 1
    expr = ''.join(out).strip()
    return expr, [s.strip() for s in interps], concat and _concat_joins_code(expr)


def _concat_joins_code(expr: str) -> bool:
    """`'a' + 'b'` is a literal; `'<b>' + name` is an interpolation."""
    stripped = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`[^`$]*`", '', expr)
    return bool(re.search(r'[A-Za-z_$]', stripped))


def sinks_in(path: Path, text: str | None = None) -> List[Sink]:
    text = path.read_text(encoding='utf-8') if text is None else text
    found: List[Sink] = []
    for m in SINK.finditer(text):
        # skip matches inside a // comment line
        line_start = text.rfind('\n', 0, m.start()) + 1
        if text[line_start:m.start()].lstrip().startswith(('//', '*', '/*')):
            continue
        call = bool(m.group('call'))
        start = m.end()
        if call:  # skip the position argument: everything up to the first top-level comma
            k, d = start, 0
            while k < len(text):
                ch = text[k]
                if ch in '([{':
                    d += 1
                elif ch in ')]}':
                    d -= 1
                elif ch == ',' and d == 0:
                    break
                k += 1
            start = k + 1
        expr, interps, concat = _read_expression(text, start, call=call)
        kind = m.group('call') or f"{m.group('prop')} {m.group('op')}"
        found.append(Sink(path, text.count('\n', 0, m.start()) + 1, kind, expr,
                          interps, concat))
    return found


def all_sinks() -> List[Sink]:
    out: List[Sink] = []
    for p in first_party_js():
        out.extend(sinks_in(p))
    return out


#: A local escaping helper: `function escapeX(`, `escapeX(x) {` (a method),
#: or `const escapeX = (`/`function`. Usages (`escapeX(value)` in an
#: expression) are not definitions.
ESCAPE_DEFINITION = re.compile(
    r"^\s*(?:"
    r"function\s+(?P<f>_?escape\w*)\s*\("
    r"|(?:const|let|var)\s+(?P<v>_?escape\w*)\s*=\s*(?:function\b|\(|\w+\s*=>)"
    r"|(?:static\s+)?(?P<m>_?escape\w*)\s*\([^)]*\)\s*\{"
    r")", re.M)


def escape_definitions(path: Path, text: str | None = None) -> List[tuple[int, str]]:
    text = path.read_text(encoding='utf-8') if text is None else text
    return [(text.count('\n', 0, m.start()) + 1, m.group('f') or m.group('v') or m.group('m'))
            for m in ESCAPE_DEFINITION.finditer(text)]
