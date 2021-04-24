# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
handy utilities
"""
import sys
import time
import inspect
import functools
import json
import logging
import uuid as mod_uuid
import importlib
import pkgutil


class ESLError(Exception):
    """An error pertaining to the connection"""


class TimeoutError(Exception):
    """Timing error"""


class ConfigurationError(Exception):
    """Config error"""


class APIError(ESLError):
    """ESL api error"""


# fs-like log format with a thread name prefix
PREFIX = "%(asctime)s (%(threadName)s) "
LEVEL = "[%(levelname)s] "
LOG_FORMAT = PREFIX + LEVEL + (
    "%(name)s %(filename)s:%(lineno)d : %(message)s")
DATE_FORMAT = '%b %d %H:%M:%S'
TRACE = 5


def get_logger(name=None):
    '''Return the package log or a sub-log for `name` if provided.
    '''
    log = rlog = logging.getLogger('switchio')
    if name and name != 'switchio':
        log = rlog.getChild(name)
        log.level = rlog.level
    return log


def log_to_stderr(level=None):
    '''Turn on logging and add a handler which writes to stderr
    '''
    log = logging.getLogger()  # the root logger
    if level:
        log.setLevel(level.upper() if not isinstance(level, int) else level)
    if not any(
        handler.stream == sys.stderr for handler in log.handlers
        if getattr(handler, 'stream', None)
    ):
        handler = logging.StreamHandler()
        # do colours if we can
        try:
            import colorlog
            fs_colors = {
                'CRITICAL': 'bold_red',
                'ERROR': 'red',
                'WARNING': 'purple',
                'INFO': 'green',
                'DEBUG': 'yellow',
                'TRACE': 'cyan',
            }
            logging.addLevelName(TRACE, 'TRACE')
            formatter = colorlog.ColoredFormatter(
                "%(log_color)s" + LOG_FORMAT,
                datefmt=DATE_FORMAT,
                log_colors=fs_colors
            )
        except ImportError:
            logging.warning("Colour logging not supported. Please install"
                            " the colorlog module to enable\n")
            formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

        handler.setFormatter(formatter)
        log.addHandler(handler)
    return log


def dirinfo(inst):
    """Return common info useful for dir output
    """
    return sorted(set(dir(type(inst)) + list(inst.__dict__.keys())))


def xheaderify(header_name):
    '''Prefix the given name with the freeswitch xheader token
    thus transforming it into an fs xheader variable
    '''
    return 'sip_h_X-{}'.format(header_name)


def param2header(name):
    """Return the appropriate event header name corresponding to the named
    parameter `name` which should be used when the param is received as a
    header in event data.

    Most often this is just the original parameter name with a ``'variable_'``
    prefix. This is pretty much a shitty hack (thanks goes to FS for the
    asymmetry in variable referencing...)
    """
    var_keys = {
        'sip_h_X-',  # is it an x-header?
        'switchio',  # custom switchio variable?
    }
    for key in var_keys:
        if key in name:
            return 'variable_{}'.format(name)
    return name


def pstr(self, host='unknown-host'):
    """Pretty str repr of connection-like instances.
    """
    return '{}@{}'.format(
        type(self).__name__,
        getattr(self, 'host', host)
    )


def get_name(obj):
    """Return a name for object checking the usual places
    """
    try:
        return obj.__name__
    except AttributeError:
        return obj.__class__.__name__


def event2dict(event):
    '''Return event serialized data in a python dict
    Warning: this function is kinda slow!
    '''
    return json.loads(event.serialize('json').replace('\t', ''))


def uncons(first, *rest):
    """Unpack args into first element and tail as tuple
    """
    return first, rest


def compose(func_1, func_2):
    """(f1, f2) -> function
    The function returned is a composition of f1 and f2.
    """
    if not callable(func_1):
        raise TypeError("First arg must be callable")
    if not callable(func_2):
        raise TypeError("Second arg must be callable")

    def composition(*args, **kwargs):
        return func_1(func_2(*args, **kwargs))
    return composition


def ncompose(*funcs):
    """Perform n-function composition
    """
    return functools.reduce(
        lambda f, g: lambda x: f(g(x)), funcs, lambda x: x
    )


def get_args(func):
    """Return the argument names found in func's signature in a tuple

    :return: the argnames, kwargnames defined by func
    :rtype: tuple
    """
    argspec = inspect.getfullargspec(func)
    index = -len(argspec.defaults) if argspec.defaults else None
    return argspec.args[slice(0, index)], argspec.args[slice(index, None if index else 0)]


def is_callback(func):
    """Check whether func is valid as a callback
    """
    return inspect.isroutine(func)


def uuid():
    """Return a new uuid1 string
    """
    return str(mod_uuid.uuid1())


def get_event_time(event, epoch=0.0):
    '''Return micro-second time stamp value in seconds
    '''
    value = event.get('Event-Date-Timestamp')
    if value is None:
        get_logger().warning("Event '{}' has no timestamp!?".format(
                             event.get("Event-Name")))
        return None
    return float(value) / 1e6 - epoch


class Timer(object):
    """Simple timer that reports an elapsed duration since the last reset.
    """
    def __init__(self, timer=None):
        self.time = timer or time
        self._last = 0

    def elapsed(self):
        """Returns the elapsed time since the last reset
        """
        return self.time.time() - self._last

    def reset(self):
        """Reset the timer start point to now
        """
        self._last = self.time.time()

    @property
    def last_time(self):
        '''Last time the timer was reset
        '''
        return self._last


def DictProxy(d, extra_attrs={}):
    """A dictionary proxy object which provides attribute access to elements
    """
    attrs = [
        '__repr__',
        '__getitem__',
        '__setitem__',
        '__contains__',
    ]
    attr_map = {attr: getattr(d, attr) for attr in attrs}
    attr_map.update(extra_attrs)
    proxy = type('DictProxy', (), attr_map)()
    proxy.__dict__ = d
    return proxy


# based on
# http://stackoverflow.com/questions/3365740/how-to-import-all-submodules
def iter_import_submods(packages, recursive=False, imp_excs=()):
    """Iteratively import all submodules of a module, including subpackages
    with optional recursion.

    :param package: package (name or actual module)
    :type package: str | module
    :rtype: (dict[str, types.ModuleType], dict[str, ImportError])
    """
    def try_import(package):
        try:
            return importlib.import_module(package)
        except ImportError as ie:
            dep = ie.message.split()[-1]
            if dep in imp_excs:
                return ie
            else:
                raise

    for package in packages:

        if isinstance(package, str):
            package = try_import(package)
        pkgpath = getattr(package, '__path__', None)

        if pkgpath:
            for loader, name, is_pkg in pkgutil.walk_packages(pkgpath):
                full_name = package.__name__ + '.' + name
                yield full_name, try_import(full_name)

                if recursive and is_pkg:
                    for res in iter_import_submods(
                        [full_name], recursive=recursive, imp_excs=imp_excs
                    ):
                        yield res


def waitwhile(predicate, timeout=float('inf'), period=0.1, exc=True):
    """Block until `predicate` evaluates to `False`.

    :param predicate: predicate function
    :type predicate: function
    :param float timeout: time to wait in seconds for predicate to eval False
    :param float period: poll loop sleep period in seconds
    :raises TimeoutError: if predicate does not eval to False within `timeout`
    """
    start = time.time()
    while predicate():
        time.sleep(period)
        if time.time() - start > timeout:
            if exc:
                raise TimeoutError(
                    "'{}' failed to be True".format(
                        predicate)
                )
            return False
    return True


def con_repr(self):
    """Repr with a [<connection-status>] slapped in"""
    rep = object.__repr__(self).strip('<>')
    return "<{} [{}]>".format(
        rep, "connected" if self.connected() else "disconnected")
