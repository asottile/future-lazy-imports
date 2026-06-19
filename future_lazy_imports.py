from __future__ import annotations

import argparse
import ast
import codecs
import io
import re
import sys
from collections.abc import Sequence
from encodings import utf_8
from typing import Any
from typing import NamedTuple
from typing import TYPE_CHECKING

import tokenize_rt

if TYPE_CHECKING:
    from codecs import _ReadableStream
    from typing_extensions import Buffer


_PRE = '_lazy__'

_LAZY = re.compile(
    r'^[ \f\t]*lazy[ \f\t]+'
    r'(?:from|import)(?=[ \f\t]+)'
    r'(?:[ \f\t]+|\w+|[,.*]|\\\n|\((?:\s+|,|\w+|\\\n|#[^\r\n]*)*\))*'
    r'(?P<comment>(?:#[^\r\n]*)?)(?:\n|$)',
    re.M,
)

_BLOCKS = {
    'if', 'def', 'async', 'class', 'for', 'while', 'with', 'match', 'try',
}


class _LAZY_P(NamedTuple):
    mod: str
    attr: str | None = None


def _LAZY_r(g: dict[str, object], n: str) -> object:
    current = g[n]
    if type(current) is _LAZY_P:
        t = n.removeprefix(_PRE)
        if current.attr:
            mod = __import__(current.mod, fromlist=['_trash'])
            current = g[n] = g[t] = getattr(mod, current.attr)
        else:
            current = g[n] = g[t] = __import__(current.mod)
    return current


def _LAZY_g(g: dict[str, Any], n: str) -> object:
    lazy = f'{_PRE}{n}'
    if lazy in g:
        return _LAZY_r(g, lazy)

    fn = g.get(f'{_PRE}__getattr__')
    if fn is not None:
        return fn(n)
    else:
        raise AttributeError(n)


class _FuncInfo(NamedTuple):
    offset: tuple[int, int]
    has_docstring: bool
    names: list[str]
    offsets: list[tuple[int, int]]


class V(ast.NodeVisitor):
    def __init__(self, names: Sequence[str]) -> None:
        self.names = names
        self.done: dict[tokenize_rt.Offset, _FuncInfo] = {}
        self.functions: list[_FuncInfo] = []
        self.getattr_func: tuple[int, int] | None = None

    def visit_FunctionDef(
            self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        if node.name == '__getattr__' and node.col_offset == 0:
            self.getattr_func = (node.lineno, node.col_offset)

        has_docstring = (
            bool(node.body) and
            isinstance(node.body[0], ast.Expr) and
            isinstance(node.body[0].value, ast.Constant) and
            isinstance(node.body[0].value.value, str)
        )
        info = _FuncInfo((node.lineno, node.col_offset), has_docstring, [], [])
        self.functions.append(info)
        self.generic_visit(node)
        self.functions.pop()
        if info.names:
            self.done[info.offset] = info

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.names and self.functions:
            self.functions[-1].names.append(node.id)
            self.functions[-1].offsets.append((node.lineno, node.col_offset))
        self.generic_visit(node)


def decode(b: Buffer, errors: str = 'strict') -> tuple[str, int]:
    u, length = utf_8.decode(b, errors)

    imported_p = False
    lazy_names = []

    def _cb(m: re.Match[str]) -> str:
        nonlocal imported_p

        o, = ast.parse(m[0].lstrip().removeprefix('lazy').lstrip()).body
        assert isinstance(o, (ast.Import, ast.ImportFrom)), o
        if imported_p:
            parts = []
        else:
            imported_p = True
            parts = [
                'from future_lazy_imports import _LAZY_P, _LAZY_r, _LAZY_g',
                'from functools import cache',
                '_LAZY__r = cache(lambda n: _LAZY_r(globals(), n))',
                '__getattr__ = lambda n: _LAZY_g(globals(), n)',
            ]
        if isinstance(o, ast.Import):
            for n in o.names:
                if n.asname is not None:
                    t = n.asname
                else:
                    t, _, _ = n.name.partition('.')
                lazy_names.append(t)
                parts.append(f'{_PRE}{t} = _LAZY_P({n.name!r})')
        else:
            for n in o.names:
                if n.asname is not None:
                    t = n.asname
                else:
                    t = n.name
                lazy_names.append(t)
                parts.append(f'{_PRE}{t} = _LAZY_P({o.module!r}, {n.name!r})')
        nlcount = m[0].count('\n')
        return (
            '; '.join(parts) +
            '\n' * (nlcount > 0) +
            '# lazy padding\n' * (nlcount - 1)
        )

    u = _LAZY.sub(_cb, u)

    v = V(lazy_names)
    v.visit(ast.parse(u))

    name_offsets = {o for f in v.done.values() for o in f.offsets}

    tokens = tokenize_rt.src_to_tokens(u)
    for i, token in tokenize_rt.reversed_enumerate(tokens):
        if token.name == 'NAME' and token.offset in v.done:
            func = v.done[token.offset]
            depth = 0
            j = i + 1
            while depth != 0 or not tokens[j].matches(name='OP', src=':'):
                if tokens[j].name == 'OP' and tokens[j].src in '([{':
                    depth += 1
                elif tokens[j].name == 'OP' and tokens[j].src in ')]}':
                    depth -= 1
                j += 1
            j += 1

            if func.has_docstring:
                while tokens[j].name != 'STRING':
                    j += 1
                while tokens[j].name != 'NEWLINE':
                    j += 1
                before = '; '
            else:
                saw_nl = None
                while tokens[j].name != 'INDENT':
                    if tokens[j].name == 'NL':
                        saw_nl = j
                    j += 1
                j += 1

                if saw_nl is not None:
                    before = tokens[j - 1].src
                    j = saw_nl
                elif tokens[j].src in _BLOCKS:
                    before = ''
                    nl = tokenize_rt.Token('CODE', f'\n{tokens[j - 1].src}')
                    tokens.insert(j, nl)
                else:
                    before = ''
                    tokens.insert(j, tokenize_rt.Token('CODE', '; '))

            code = '; '.join(
                f'_LAZY__r({f"{_PRE}{n}"!r})'
                for n in func.names
            )
            tok = tokenize_rt.Token('CODE', src=f'{before}{code}')
            tokens.insert(j, tok)

        elif token.name == 'NAME' and token.offset in name_offsets:
            tokens[i] = token._replace(src=f'{_PRE}{token.src}')
        elif token.name == 'NAME' and token.offset == v.getattr_func:
            j = i + 1
            while not tokens[j].matches(name='NAME', src='__getattr__'):
                j += 1
            tokens[j] = tokens[j]._replace(src=f'{_PRE}{tokens[j].src}')

    return tokenize_rt.tokens_to_src(tokens), length


class IncrementalDecoder(codecs.BufferedIncrementalDecoder):
    def _buffer_decode(  # pragma: no cover
            self,
            input: Buffer,
            errors: str,
            final: bool,
    ) -> tuple[str, int]:
        if final:
            return decode(input, errors)
        else:
            return '', 0


class StreamReader(utf_8.StreamReader):
    """decode is deferred to support better error messages"""
    _stream = None
    _decoded = False

    @property
    def stream(self) -> _ReadableStream:
        assert self._stream is not None
        if not self._decoded:
            text, _ = decode(self._stream.read())
            self._stream = io.BytesIO(text.encode('UTF-8'))
            self._decoded = True
        return self._stream

    @stream.setter
    def stream(self, stream: _ReadableStream) -> None:
        self._stream = stream
        self._decoded = False

# codec api


codec_map = {
    name: codecs.CodecInfo(
        name=name,
        encode=utf_8.encode,
        decode=decode,
        incrementalencoder=utf_8.IncrementalEncoder,
        incrementaldecoder=IncrementalDecoder,
        streamreader=StreamReader,
        streamwriter=utf_8.StreamWriter,
    )
    for name in ('future-lazy-imports', 'future_lazy_imports')
}


def register() -> None:  # pragma: no cover
    codecs.register(codec_map.get)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Prints transformed source.')
    parser.add_argument('filename')
    args = parser.parse_args(argv)

    with open(args.filename, 'rb') as f:
        text, _ = decode(f.read())
    sys.stdout.buffer.write(text.encode())

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
