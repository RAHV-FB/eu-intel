"""The public data contract (src/types/data.ts) checked against the built JSON (public/data).

`validate --built` reads the TypeScript declarations of src/types/data.ts and checks every file the site reads
against them: required and unknown keys, null where the type does not allow it, the basic types (string, number,
boolean, arrays, records, tuples), string literal unions (enums), ISODate/ISODateTime formats, and the types
derived with Pick<>, Partial<>, intersections and indexed access (`EpVoteTitle` for votes/titles.json,
`CouncilVote['outcome']`). Nested interfaces (SourceRef, DocRef, CoverageScope, ...) are checked wherever they occur.

Which type each file has comes from the header comment of data.ts ("meta.json   Meta", "dossiers/<id>.json
DossierDetail"); a file named by `<id>` or `<code>` is checked for each entry of its folder's index (dossiers/index.json,
or people/meps.json for people/meps/<id>.json), which is how the site reaches it.

Only the TypeScript that data.ts uses is understood; a construct it does not know makes the parse fail loudly rather
than pass silently.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATA_TS = Path(__file__).resolve().parents[1] / "src" / "types" / "data.ts"

# ------------------------------------------------------------------------------------------- types
# A type is a tuple: ("prim", name) | ("lit", value) | ("ref", name) | ("array", T) | ("tuple", [T]) |
# ("union", [T]) | ("inter", [T]) | ("obj", {key: (optional, T)}) | ("generic", name, [T]) | ("index", T, key)
Type = tuple
PRIMITIVES = {"string", "number", "boolean", "null", "undefined", "unknown", "any"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
FORMATS = {"ISODate": DATE_RE, "ISODateTime": DATETIME_RE}  # aliases of string with a known format

TOKEN_RE = re.compile(
    r"\s+|//[^\n]*|/\*.*?\*/|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|-?\d+(?:\.\d+)?|[A-Za-z_$][\w$]*|[{}\[\]()<>|&;,:?=.]",
    re.S,
)


class ContractError(ValueError):
    """data.ts uses a construct this parser does not understand."""


def _tokens(text: str) -> list[str]:
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise ContractError(f"data.ts: cannot read {text[pos:pos + 40]!r}")
        tok, pos = m.group(0), m.end()
        if not (tok.isspace() or tok.startswith("//") or tok.startswith("/*")):
            out.append(tok)
    return out


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.t, self.i = tokens, 0

    def peek(self, k: int = 0) -> str | None:
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self, expected: str | None = None) -> str:
        tok = self.peek()
        if tok is None or (expected is not None and tok != expected):
            raise ContractError(f"data.ts: expected {expected!r}, found {tok!r} (token {self.i})")
        self.i += 1
        return tok

    def declarations(self) -> dict[str, Type]:
        out: dict[str, Type] = {}
        while self.peek() is not None:
            self.take("export")
            kind = self.take()
            name = self.take()
            if kind == "type":
                self.take("=")
                out[name] = self.type()
                self.take(";")
            elif kind == "interface":
                bases = []
                if self.peek() == "extends":
                    self.take()
                    bases.append(("ref", self.take()))
                    while self.peek() == ",":
                        self.take()
                        bases.append(("ref", self.take()))
                body = self.object()
                out[name] = ("inter", [*bases, body]) if bases else body
            else:
                raise ContractError(f"data.ts: unsupported declaration 'export {kind}'")
        return out

    def type(self) -> Type:
        if self.peek() == "|":
            self.take()
        alts = [self.intersection()]
        while self.peek() == "|":
            self.take()
            alts.append(self.intersection())
        return alts[0] if len(alts) == 1 else ("union", alts)

    def intersection(self) -> Type:
        parts = [self.postfix()]
        while self.peek() == "&":
            self.take()
            parts.append(self.postfix())
        return parts[0] if len(parts) == 1 else ("inter", parts)

    def postfix(self) -> Type:
        t = self.primary()
        while self.peek() == "[":
            self.take()
            if self.peek() == "]":
                self.take()
                t = ("array", t)
            else:
                key = self.take()
                self.take("]")
                t = ("index", t, _unquote(key))
        return t

    def primary(self) -> Type:
        tok = self.take()
        if tok == "(":
            t = self.type()
            self.take(")")
            return t
        if tok == "{":
            self.i -= 1
            return self.object()
        if tok == "[":
            items = []
            while self.peek() != "]":
                if self.peek(1) == ":" and self.peek(0) not in ("{", "["):  # a labelled element: [lang: string, ...]
                    self.i += 2
                items.append(self.type())
                if self.peek() == ",":
                    self.take()
            self.take("]")
            return ("tuple", items)
        if tok[0] in "'\"":
            return ("lit", _unquote(tok))
        if tok in ("true", "false"):
            return ("lit", tok == "true")
        if re.fullmatch(r"-?\d+(?:\.\d+)?", tok):
            return ("lit", float(tok) if "." in tok else int(tok))
        if tok in PRIMITIVES:
            return ("prim", tok)
        if self.peek() == "<":
            self.take()
            args = [self.type()]
            while self.peek() == ",":
                self.take()
                args.append(self.type())
            self.take(">")
            return ("generic", tok, args)
        return ("ref", tok)

    def object(self) -> Type:
        self.take("{")
        fields: dict[str, tuple[bool, Type]] = {}
        while self.peek() != "}":
            key = _unquote(self.take())
            optional = self.peek() == "?"
            if optional:
                self.take()
            self.take(":")
            fields[key] = (optional, self.type())
            if self.peek() in (";", ","):
                self.take()
        self.take("}")
        return ("obj", fields)


def _unquote(tok: str) -> str:
    return tok[1:-1] if tok[:1] in ("'", '"') else tok


def file_types(text: str) -> dict[str, str]:
    """public/data path -> its type, from the header comment of data.ts ("dossiers/<id>.json   DossierDetail")."""
    head = text.split("*/", 1)[0]
    return {m.group(1): m.group(2) for m in re.finditer(r"^\s*\*\s+([\w/<>.-]+\.json)\s+(\w+(?:\[\])?)", head, re.M)}


# ------------------------------------------------------------------------------------------- checking
@dataclass
class Problems:
    """Contract violations, grouped by file pattern, path in the type and kind of problem."""

    counts: dict[tuple[str, str, str], int] = field(default_factory=dict)
    examples: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def add(self, pattern: str, path: str, what: str, where: str) -> None:
        key = (pattern, path, what)
        self.counts[key] = self.counts.get(key, 0) + 1
        self.examples.setdefault(key, where)

    def lines(self) -> list[str]:
        return [
            f"{pattern}: {path}: {what} ({n} time{'s' if n > 1 else ''}, e.g. {self.examples[(pattern, path, what)]})"
            for (pattern, path, what), n in sorted(self.counts.items())
        ]


Checker = Callable[[Any, str, Callable[[str, str], None]], None]


def _kind(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object" if isinstance(v, dict) else type(v).__name__


def _show(v: Any) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, (dict, list)) else _kind(v)
    return s if len(s) <= 40 else s[:37] + "..."


class Contract:
    """The declarations of data.ts, compiled into checkers."""

    def __init__(self, text: str) -> None:
        self.decls = _Parser(_tokens(text)).declarations()
        self.files = file_types(text)
        self._compiled: dict[str, Checker] = {}

    @classmethod
    def load(cls, path: Path = DATA_TS) -> Contract:
        return cls(path.read_text(encoding="utf-8"))

    # ----------------------------------------------------------------- resolving
    def decl(self, name: str) -> Type:
        if name not in self.decls:
            raise ContractError(f"data.ts: unknown type {name}")
        return self.decls[name]

    def fields(self, t: Type, seen: tuple[str, ...] = ()) -> dict[str, tuple[bool, Type]]:
        """The keys of an object type: an interface with what it extends, Pick, Partial, Omit, an intersection."""
        kind = t[0]
        if kind == "obj":
            return dict(t[1])
        if kind == "ref":
            if t[1] in seen:
                raise ContractError(f"data.ts: {t[1]} extends itself")
            return self.fields(self.decl(t[1]), (*seen, t[1]))
        if kind == "inter":
            out: dict[str, tuple[bool, Type]] = {}
            for part in t[1]:
                for k, (opt, ft) in self.fields(part, seen).items():
                    out[k] = (opt and out[k][0], ft) if k in out else (opt, ft)
            return out
        if kind == "generic" and t[1] in ("Pick", "Omit"):
            base, keys = self.fields(t[2][0], seen), set(self.literals(t[2][1]))
            return {k: v for k, v in base.items() if (k in keys) == (t[1] == "Pick")}
        if kind == "generic" and t[1] == "Partial":
            return {k: (True, ft) for k, (_, ft) in self.fields(t[2][0], seen).items()}
        raise ContractError(f"data.ts: not an object type: {t!r}"[:200])

    def literals(self, t: Type) -> list[Any]:
        if t[0] == "lit":
            return [t[1]]
        if t[0] == "union":
            return [x for a in t[1] for x in self.literals(a)]
        if t[0] == "ref":
            return self.literals(self.decl(t[1]))
        raise ContractError(f"data.ts: not a union of literals: {t!r}"[:200])

    def is_object(self, t: Type) -> bool:
        if t[0] == "ref" and t[1] not in FORMATS:
            return self.is_object(self.decl(t[1]))
        return t[0] in ("obj", "inter") or (t[0] == "generic" and t[1] in ("Pick", "Omit", "Partial"))

    def alternatives(self, t: Type) -> list[Type]:
        """A union flattened through aliases (a named union of literals counts as its literals)."""
        if t[0] == "union":
            return [x for a in t[1] for x in self.alternatives(a)]
        if t[0] == "ref" and t[1] not in FORMATS and self.decl(t[1])[0] in ("union", "lit"):
            return self.alternatives(self.decl(t[1]))
        if t[0] == "index":
            return self.alternatives(self.fields(t[1])[t[2]][1])
        return [t]

    # ----------------------------------------------------------------- compiling
    def checker(self, name: str) -> Checker:
        """The checker of a named type (compiled once; recursive references resolve lazily)."""
        if name not in self._compiled:
            t = self.decl(name)
            self._compiled[name] = lambda v, path, bad: self._compiled[name](v, path, bad)  # placeholder for cycles
            self._compiled[name] = self._object(t) if self.is_object(t) else self.compile(t)
        return self._compiled[name]

    def compile(self, t: Type) -> Checker:  # noqa: C901 - one branch per kind of type
        kind = t[0]
        if kind == "ref" and t[1] in FORMATS:
            rx, label = FORMATS[t[1]], t[1]

            def fmt(v: Any, path: str, bad: Callable[[str, str], None]) -> None:
                if not isinstance(v, str):
                    bad(path, f"{_kind(v)} where {label} expected")
                elif not rx.match(v):
                    bad(path, f"{_show(v)} is not an {label}")

            return fmt
        if kind == "ref":
            return self.checker(t[1])
        if self.is_object(t):
            return self._object(t)
        if kind in ("union", "lit", "prim", "index"):
            return self._union(self.alternatives(t))
        if kind == "array":
            item = self.compile(t[1])

            def arr(v: Any, path: str, bad: Callable[[str, str], None]) -> None:
                if not isinstance(v, list):
                    bad(path, f"{_kind(v)} where an array expected")
                    return
                p = path + "[]"
                for x in v:
                    item(x, p, bad)

            return arr
        if kind == "tuple":
            items = [self.compile(x) for x in t[1]]

            def tup(v: Any, path: str, bad: Callable[[str, str], None]) -> None:
                if not isinstance(v, list) or len(v) != len(items):
                    bad(path, f"{_show(v)} where a tuple of {len(items)} expected")
                    return
                for i, (x, c) in enumerate(zip(v, items, strict=True)):
                    c(x, f"{path}[{i}]", bad)

            return tup
        if kind == "generic" and t[1] == "Record":
            keys = set(self.literals(t[2][0])) if t[2][0] != ("prim", "string") else None
            value = self.compile(t[2][1])

            def rec(v: Any, path: str, bad: Callable[[str, str], None]) -> None:
                if not isinstance(v, dict):
                    bad(path, f"{_kind(v)} where a record expected")
                    return
                p = path + "{}"
                for k, x in v.items():
                    if keys is not None and k not in keys:
                        bad(path, f"key {_show(k)} not allowed")
                    value(x, p, bad)

            return rec
        raise ContractError(f"data.ts: unsupported type {t!r}"[:200])

    def _simple(self, t: Type) -> tuple[frozenset[type], frozenset[str], re.Pattern[str] | None] | None:
        """For a union of primitives, string literals and at most one date format: the Python types it accepts, its
        literals and the format, so that an object checks such a field inline (most of the output's values)."""
        alts = self.alternatives(t)
        types: set[type] = set()
        lits: set[str] = set()
        rx = None
        for a in alts:
            if a[0] == "prim" and a[1] in ("string", "number", "boolean", "null"):
                types |= {"string": {str}, "number": {int, float}, "boolean": {bool}, "null": {type(None)}}[a[1]]
            elif a[0] == "lit" and isinstance(a[1], str):
                lits.add(a[1])
            elif a[0] == "ref" and a[1] in FORMATS and rx is None:
                rx = FORMATS[a[1]]
            else:
                return None
        return frozenset(types), frozenset(lits), rx

    def _object(self, t: Type) -> Checker:
        spec = self.fields(t)
        required = frozenset(k for k, (opt, _) in spec.items() if not opt)
        known = frozenset(spec)
        checks: dict[str, Checker] = {}
        simple = {k: s for k, (_, ft) in spec.items() if (s := self._simple(ft)) is not None}

        def obj(v: Any, path: str, bad: Callable[[str, str], None]) -> None:
            if not isinstance(v, dict):
                bad(path, f"{_show(v)} where an object expected")
                return
            keys = v.keys()
            if not required <= keys:
                for k in sorted(required - keys):
                    bad(f"{path}.{k}", "missing")
            for k, x in v.items():
                s = simple.get(k)
                if s is not None:
                    tx = type(x)
                    if tx in s[0] or (tx is str and (x in s[1] or (s[2] is not None and s[2].match(x)))):
                        continue  # valid: the full checker below only runs to describe a problem
                c = checks.get(k)
                if c is None:
                    if k not in known:
                        bad(f"{path}.{k}", "not in the contract")
                        continue
                    c = checks[k] = self.compile(spec[k][1])  # compiled on first use (types can be recursive)
                c(x, f"{path}.{k}", bad)

        return obj

    def _union(self, alts: list[Type]) -> Checker:
        prims = {a[1] for a in alts if a[0] == "prim"}
        if prims & {"unknown", "any"}:
            return lambda v, path, bad: None
        lits = {(type(a[1]) is bool, a[1]) for a in alts if a[0] == "lit"}
        names = [a[1] for a in alts if a[0] == "ref" and a[1] in FORMATS]
        formats = [FORMATS[n] for n in names]
        complex_ = [a for a in alts if a[0] not in ("prim", "lit") and not (a[0] == "ref" and a[1] in FORMATS)]
        checks = [self.compile(a) for a in complex_]
        allow_null = "null" in prims
        wants = {"string": "string" in prims, "number": "number" in prims, "boolean": "boolean" in prims}
        label = " | ".join(
            [json.dumps(x) for _, x in sorted(lits, key=str)][:8] + (["..."] if len(lits) > 8 else [])
            + sorted(p for p in prims) + [a[1] for a in alts if a[0] == "ref" and a[1] in FORMATS]
            + [a[1] if a[0] == "ref" else a[0] for a in complex_]
        )  # fmt: skip

        def union(v: Any, path: str, bad: Callable[[str, str], None]) -> None:
            if v is None:
                if not allow_null:
                    bad(path, f"null where {label} expected")
                return
            if isinstance(v, bool):
                ok = wants["boolean"] or (True, v) in lits
            elif isinstance(v, (int, float)):
                ok = wants["number"] or (False, v) in lits
            elif isinstance(v, str):
                ok = wants["string"] or (False, v) in lits or any(rx.match(v) for rx in formats)
            else:
                ok = False
                if len(checks) == 1:  # one structured alternative: its own problems are the useful ones
                    checks[0](v, path, bad)
                    return
                for c in checks:
                    found: list[tuple[str, str]] = []
                    c(v, path, lambda p, w, found=found: found.append((p, w)))
                    if not found:
                        return
            if not ok and isinstance(v, str) and formats and not lits:
                bad(path, f"{_show(v)} is not an {' or '.join(names)}")
            elif not ok:
                bad(path, f"{_show(v)} where {label} expected")

        return union

    # ----------------------------------------------------------------- the built output
    def check_value(self, value: Any, type_name: str, path: str | None = None) -> list[tuple[str, str]]:
        """(path, problem) for each violation of `type_name` (or `Name[]`) by `value`."""
        found: list[tuple[str, str]] = []
        name = type_name.removesuffix("[]")
        check = self.checker(name)
        if type_name.endswith("[]"):
            check = self.compile(("array", ("ref", name)))
        check(value, path or name, lambda p, w: found.append((p, w)))
        return found

    def files_to_check(self, public: Path, read: Callable[[str], Any]) -> Iterator[tuple[str, str, str]]:
        """(pattern, file, type) for each file of the header: the listed files, and for `<id>`/`<code>` the entries
        of their folder's index. `read` gives a parsed file or None."""
        for pattern, type_name in self.files.items():
            m = re.fullmatch(r"(.+)/<(\w+)>\.json", pattern)
            if not m:
                yield pattern, pattern, type_name
                continue
            folder, key = m.groups()
            index = next((f for f in (f"{folder}/index.json", f"{folder}.json") if f in self.files), None)
            entries = read(index) if index else None
            for e in entries if isinstance(entries, list) else []:
                if isinstance(e, dict) and isinstance(e.get(key), str) and (public / folder / f"{e[key]}.json").exists():
                    yield pattern, f"{folder}/{e[key]}.json", type_name
            for rel in self.unlisted(public, read, pattern):  # checked too: the site reaches them by a link
                yield pattern, rel, type_name

    def unlisted(self, public: Path, read: Callable[[str], Any], pattern: str) -> list[str]:
        """The files of a `<key>` pattern's folder that its index does not list (people/parties/5500.json): the site
        reaches them only by a link. Not the files the header lists by name (votes/titles.json)."""
        m = re.fullmatch(r"(.+)/<(\w+)>\.json", pattern)
        if not m:
            return []
        folder, key = m.groups()
        index = next((f for f in (f"{folder}/index.json", f"{folder}.json") if f in self.files), None)
        entries = read(index) if index else None
        listed = {e[key] for e in entries if isinstance(e, dict) and isinstance(e.get(key), str)} if isinstance(
            entries, list) else set()  # fmt: skip
        return [
            f"{folder}/{f.name}" for f in sorted((public / folder).glob("*.json"))
            if f"{folder}/{f.name}" not in self.files and f.stem not in listed
        ]  # fmt: skip


def check_public(public: Path, contract: Contract | None = None, read: Callable[[str], Any] | None = None) -> Problems:
    """Every file of public/data the contract names, against its type. `read(rel)` returns a parsed file or None
    (unreadable or missing files are reported by the other built-output checks); by default each file is read here."""
    contract = contract or Contract.load()

    def default_read(rel: str) -> Any:
        try:
            return json.loads((public / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    read = read or default_read
    problems = Problems()
    for pattern, rel, type_name in contract.files_to_check(public, read):
        doc = read(rel)
        if doc is None:
            continue
        for path, what in contract.check_value(doc, type_name):
            problems.add(pattern, path, what, rel)
    return problems
