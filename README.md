![](https://github.com/user-attachments/assets/405ede4d-f6cc-4081-9eb3-57e6c2204dd6)
<sup><sub>- courtesy of pycon us 2026 steering council presentation</sub></sup>

# NO

... unless

### please don't use this

no seriously.  I do not need [another joke package of mine] to be deemed
"critical" to pypi [^1]

[^1]: with almost a [million downloads per month] and [45M+ total]

[another joke package of mine]: https://pypi.org/p/future-fstrings
[million downloads per month]: https://pypistats.org/packages/future-fstrings
[45M+ total]: https://pepy.tech/projects/future-fstrings

### ok how do I use it

1. `pip install future-lazy-imports`
2. add `# -*- coding: future-lazy-imports -*-` to the top of your file
  (second line if you have a shebang)
3. use `lazy import ...` and `lazy from ...` as normal!

```python
# -*- coding: future-lazy-imports -*-
lazy from asyncio import run

async def hello():
    print('hello hello world!')

def main():
    run(hello())  # lazily imported!

if __name__ == '__main__':
    raise SystemExit(main())
```

```console
$ time python3 t.py
hello hello world!

real    0m0.064s
user    0m0.061s
sys 0m0.007s
$ time python3  -c 'import t'

real    0m0.027s
user    0m0.023s
sys 0m0.005s
```

wow!

### problems

this doesn't actually implement the [PEP], notably `__lazy_imports__` doesn't
work also this adds a little bit of overhead to every function (since we don't
have the freedom to add code to `LOAD_GLOBAL`) and I'm pretty sure `lambda`
doesn't work ¯\\\_(ツ)_/¯

sometimes stacktraces point to the wrong line number (if your function starts
with a block statement)

see also [please don't use this](#please-dont-use-this)

[PEP]: https://peps.python.org/pep-0810/
