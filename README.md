# apluggy

[![PyPI - Version](https://img.shields.io/pypi/v/apluggy.svg)](https://pypi.org/project/apluggy)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/apluggy.svg)](https://pypi.org/project/apluggy)

[![Test Status](https://github.com/nextline-dev/apluggy/actions/workflows/unit-test.yml/badge.svg)](https://github.com/nextline-dev/apluggy/actions/workflows/unit-test.yml)
[![Test Status](https://github.com/nextline-dev/apluggy/actions/workflows/type-check.yml/badge.svg)](https://github.com/nextline-dev/apluggy/actions/workflows/type-check.yml)
[![codecov](https://codecov.io/gh/nextline-dev/apluggy/branch/main/graph/badge.svg)](https://codecov.io/gh/nextline-dev/apluggy)

A wrapper of [pluggy](https://pluggy.readthedocs.io/) to support asyncio and context managers.

This package provides a subclass of
[`pluggy.PluginManager`](https://pluggy.readthedocs.io/en/stable/api_reference.html#pluggy.PluginManager)
which

- allows async functions, context managers, and async context managers to be hooks
- supports `firstresult=True` for async hooks
- and accepts plugin factories in addition to plugin instances for registration.

---

**Table of Contents**

- [Installation](#installation)
- [How to use](#how-to-use)
  - [Start Python](#start-python)
  - [Import packages](#import-packages)
  - [Create hook specification and implementation decorators](#create-hook-specification-and-implementation-decorators)
  - [Define hook specifications](#define-hook-specifications)
  - [Define plugins](#define-plugins)
  - [Create a plugin manager and register plugins](#create-a-plugin-manager-and-register-plugins)
  - [Call hooks](#call-hooks)
    - [Async function](#async-function)
      - [firstresult=True](#firstresulttrue)
    - [Context manager](#context-manager)
    - [Async context manager](#async-context-manager)
- [Links](#links)
- [License](#license)

---

## Installation

You can install apluggy with pip:

```console
pip install apluggy
```

---

## How to use

Here, we show a simple example of how to use apluggy.

We only describe the usage of additional features provided by apluggy. For the
usage of pluggy itself, please refer to the [pluggy
documentation](https://pluggy.readthedocs.io/).

### Start Python

You can try this example in a Python interpreter.

```console
$ python
Python 3.10.13 (...)
...
...
>>>
```

### Import packages

Import necessary packages of this example.

```python
>>> import asyncio
>>> from contextlib import asynccontextmanager, contextmanager
>>> import apluggy as pluggy

```

In this example, `apluggy` is imported with the alias `pluggy`.

### Create hook specification and implementation decorators

```python
>>> hookspec = pluggy.HookspecMarker('project')
>>> hookimpl = pluggy.HookimplMarker('project')

```

### Define hook specifications

In this example, we define three hooks: async function, context manager, and
async context manager.

```python
>>> class Spec:
...     """A hook specification namespace."""
...
...     @hookspec
...     async def afunc(self, arg1, arg2):
...         pass
...
...     @hookspec
...     @contextmanager
...     def context(self, arg1, arg2):
...         pass
...
...     @hookspec
...     @asynccontextmanager
...     async def acontext(self, arg1, arg2):
...         pass

```

### Define plugins

We define two plugins as classes. Each plugin implements the three hooks
defined above.

```python
>>> class Plugin_1:
...     """A hook implementation namespace."""
...
...     @hookimpl
...     async def afunc(self, arg1, arg2):
...         print('inside Plugin_1.afunc()')
...         return arg1 + arg2
...
...     @hookimpl
...     @contextmanager
...     def context(self, arg1, arg2):
...         print('inside Plugin_1.context(): before')
...         yield arg1 + arg2
...         print('inside Plugin_1.context(): after')
...
...     @hookimpl
...     @asynccontextmanager
...     async def acontext(self, arg1, arg2):
...         print('inside Plugin_1.acontext(): before')
...         yield arg1 + arg2
...         print('inside Plugin_1.acontext(): after')

>>> class Plugin_2:
...     """A 2nd hook implementation namespace."""
...
...     @hookimpl
...     async def afunc(self, arg1, arg2):
...         print('inside Plugin_2.afunc()')
...         return arg1 - arg2
...
...     @hookimpl
...     @contextmanager
...     def context(self, arg1, arg2):
...         print('inside Plugin_2.context(): before')
...         yield arg1 - arg2
...         print('inside Plugin_2.context(): after')
...
...     @hookimpl
...     @asynccontextmanager
...     async def acontext(self, arg1, arg2):
...         print('inside Plugin_2.acontext(): before')
...         yield arg1 - arg2
...         print('inside Plugin_2.acontext(): after')

```

### Create a plugin manager and register plugins

Plugins can be registered as instances or factories. In the following
example, we register two plugins: `Plugin_1` as an instance, and `Plugin_2`
as a factory.

```python
>>> pm = pluggy.PluginManager('project')
>>> pm.add_hookspecs(Spec)
>>> _ = pm.register(Plugin_1())  # instantiation is optional.
>>> _ = pm.register(Plugin_2)  # callable is considered a plugin factory.

```

[Pluggy accepts a class or
module](https://pluggy.readthedocs.io/en/stable/#define-and-collect-hooks) as a
plugin. However, it actually accepts a class instance, not a class itself.
Consequently, when plugins are loaded with
[`load_setuptools_entrypoints()`](https://pluggy.readthedocs.io/en/stable/api_reference.html#pluggy.PluginManager.load_setuptools_entrypoints),
the entry points must be class instances or modules. Classes themselves cannot
be used as entry points (if understood correctly).

So that classes themselves can be entry points, apluggy accepts a class itself for
a plugin registration. When apluggy receives a callable object, apluggy considers
the object as a plugin factory.

### Call hooks

The following example shows how to call hooks.

#### Async function

```python
>>> async def call_afunc():
...     results = await pm.ahook.afunc(arg1=1, arg2=2)  # ahook instead of hook
...     print(results)

>>> asyncio.run(call_afunc())
inside Plugin_2.afunc()
inside Plugin_1.afunc()
[-1, 3]

```

##### firstresult=True

When the hookspec is defined with `firstresult=True`, `ahook` returns the
first non-`None` result instead of a list. Implementations are awaited
sequentially in pluggy's standard execution order (reverse registration order,
with `tryfirst` and `trylast` modifiers respected) and the chain stops at the
first non-`None` return value. This is unlike the default behavior, where all
implementations are gathered concurrently.

```python
>>> class SpecFR:
...     @hookspec(firstresult=True)
...     async def afunc_first(self, arg1, arg2):
...         pass

>>> class Plugin_FR:
...     @hookimpl
...     async def afunc_first(self, arg1, arg2):
...         return arg1 + arg2

>>> pm_fr = pluggy.PluginManager('project')
>>> pm_fr.add_hookspecs(SpecFR)
>>> _ = pm_fr.register(Plugin_FR())

>>> async def call_afunc_first():
...     result = await pm_fr.ahook.afunc_first(arg1=1, arg2=2)
...     print(result)

>>> asyncio.run(call_afunc_first())
3

```

#### Context manager

```python
>>> with pm.with_.context(arg1=1, arg2=2) as y:  # with_ instead of hook
...     print(y)
inside Plugin_2.context(): before
inside Plugin_1.context(): before
[-1, 3]
inside Plugin_1.context(): after
inside Plugin_2.context(): after

```

In the reverse order:

```python
>>> with pm.with_reverse.context(arg1=1, arg2=2) as y:  # with_reverse instead of hook
...     print(y)
inside Plugin_1.context(): before
inside Plugin_2.context(): before
[3, -1]
inside Plugin_2.context(): after
inside Plugin_1.context(): after

```

#### Async context manager

```python
>>> async def call_acontext():
...     async with pm.awith.acontext(arg1=1, arg2=2) as y:  # awith instead of hook
...         print(y)

>>> asyncio.run(call_acontext())
inside Plugin_2.acontext(): before
inside Plugin_1.acontext(): before
[-1, 3]
inside Plugin_1.acontext(): after
inside Plugin_2.acontext(): after

```

In the reverse order:

```python
>>> async def call_acontext():
...     async with pm.awith_reverse.acontext(arg1=1, arg2=2) as y:  # awith_reverse instead of hook
...         print(y)

>>> asyncio.run(call_acontext())
inside Plugin_1.acontext(): before
inside Plugin_2.acontext(): before
[3, -1]
inside Plugin_2.acontext(): after
inside Plugin_1.acontext(): after

```

---

## Links

- [pluggy](https://pluggy.readthedocs.io/)

---

## License

- _apluggy_ is licensed under the [MIT](https://spdx.org/licenses/MIT.html) license.
