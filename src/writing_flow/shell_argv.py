"""The argv of each simple command a shell string would run.

Guards that match raw command text treat a mention as an execution. A grep
pattern or a heredoc that names a dangerous shape gets blocked as if it ran.
Guards that read only the first word of each segment fail the other way. They
miss a dangerous command behind `sudo`, `env`, `xargs`, a full path such as
`/bin/rm`, `bash -c`, or a background `&`.

This module sits between the two. It removes heredoc bodies, tokenizes with
shlex so quoted text stays one argument, splits at control operators, drops
redirections, unwraps the common wrappers, and recurses into `-c` strings,
`eval`, `ssh` remote commands, `find -exec`, and heredocs fed to a shell.
`command_argvs` raises ValueError when shlex cannot tokenize, so a caller can
fall back to a raw-text check rather than pass the command.
"""
import os
import re
import shlex

try:
    from git_command import heredoc_bodies
except ImportError:  # loaded as lib.shell_argv, so hooks/lib is not on sys.path
    from lib.git_command import heredoc_bodies

SHELLS = frozenset(("sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "busybox"))

# Wrappers that run the rest of their argv as a command. The set per wrapper
# names the options that take a separate value, so the value is not mistaken
# for the command word.
_WRAPPERS = {
    "sudo": frozenset("-u -g -h -p -C -D -R -r -t -U -T".split()),
    "doas": frozenset("-u -C".split()),
    "env": frozenset("-u -C -S --unset --chdir --split-string".split()),
    "command": frozenset(),
    "builtin": frozenset(),
    "exec": frozenset(("-a",)),
    "nohup": frozenset(),
    "time": frozenset(("-o", "-f")),
    "nice": frozenset(("-n",)),
    "ionice": frozenset(("-c", "-n", "-p")),
    "stdbuf": frozenset(("-i", "-o", "-e")),
    "setsid": frozenset(),
    "chrt": frozenset(),
    "taskset": frozenset(),
    "unbuffer": frozenset(),
    "xargs": frozenset("-I -i -n -P -L -l -d -E -e -s -a --max-args --max-procs "
                       "--delimiter --arg-file --replace".split()),
    "watch": frozenset(("-n", "-d")),
    "timeout": frozenset(("-s", "-k", "--signal", "--kill-after")),
}
# Shell keywords that can open a segment ahead of the command word.
_KEYWORDS = frozenset(("if", "then", "else", "elif", "while", "until", "do", "{", "!"))
# Wrappers whose first positional argument is a value, not the command.
_LEADING_VALUE = {"timeout": 1, "chrt": 1, "taskset": 1}
_SSH_VALUE_OPTS = frozenset("-b -c -D -E -e -F -I -i -J -L -l -m -O -o -p -Q -R -S -W -w".split())

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_OPERATOR_CHARS = set(";&|()\n")
_MAX_DEPTH = 4


def _tokens(text: str) -> list:
    lexer = shlex.shlex(text.replace("`", " ; "), posix=True,
                        punctuation_chars=";&|()<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _is_operator(token: str) -> bool:
    return bool(token) and set(token) <= _OPERATOR_CHARS


def _is_redirect(token: str) -> bool:
    return bool(token) and set(token) <= set("<>&|") and bool(set(token) & set("<>"))


def _segments(tokens: list) -> list:
    """Token lists between control operators, with redirections removed."""
    segments, current, skip = [], [], False
    for index, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        if _is_redirect(token):
            skip = True  # the next token is the redirect's target
            continue
        if _is_operator(token):
            if current:
                segments.append(current)
            current = []
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token.isdigit() and _is_redirect(following):
            continue  # a file descriptor number such as the 2 in 2>/dev/null
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _unwrap(argv: list) -> list:
    """Strip assignments and wrapper commands until the real command word."""
    while argv:
        if _ASSIGNMENT.match(argv[0]) or argv[0] in _KEYWORDS:
            argv = argv[1:]
            continue
        word = os.path.basename(argv[0])
        if word not in _WRAPPERS and word not in _LEADING_VALUE:
            return argv
        value_opts = _WRAPPERS.get(word, frozenset())
        rest = argv[1:]
        while rest and rest[0].startswith("-") and rest[0] != "-":
            option = rest.pop(0)
            if option == "--":
                break
            if option in value_opts and rest:
                rest.pop(0)
        while rest and word == "env" and _ASSIGNMENT.match(rest[0]):
            rest.pop(0)
        for _ in range(_LEADING_VALUE.get(word, 0)):
            if rest:
                rest.pop(0)
        argv = rest
    return argv


def _nested(argv: list) -> list:
    """Command strings or argvs this argv hands to another interpreter."""
    word = os.path.basename(argv[0])
    nested = []
    if word in SHELLS:
        # `-c` may sit in a flag cluster such as `bash -lc`.
        for index, token in enumerate(argv[1:], start=1):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", token):
                if index + 1 < len(argv):
                    nested.append(argv[index + 1])
                break
    elif word == "eval":
        nested.append(" ".join(argv[1:]))
    elif word == "ssh":
        rest = argv[1:]
        while rest and rest[0].startswith("-"):
            option = rest.pop(0)
            if option in _SSH_VALUE_OPTS and rest:
                rest.pop(0)
        if len(rest) > 1:
            nested.append(" ".join(rest[1:]))
    elif word == "find":
        starts = []
        for token in argv[1:]:
            if token.startswith(("-", "(", "!")):
                break
            starts.append(token)
        for index, token in enumerate(argv):
            if token in ("-exec", "-execdir", "-ok", "-okdir"):
                inner = []
                for item in argv[index + 1:]:
                    if item in (";", "+"):
                        break
                    if item == "{}":
                        inner.extend(starts or ["{}"])
                    else:
                        inner.append(item)
                if inner:
                    nested.append(inner)
    return nested


def _shell_fed(opener_line: str) -> bool:
    """True when the line that opens a heredoc hands it to a shell."""
    try:
        argvs = _collect(opener_line, _MAX_DEPTH)
    except ValueError:
        return False
    return any(argv and os.path.basename(argv[0]) in SHELLS for argv in argvs)


def _collect(text: str, depth: int) -> list:
    stripped, bodies = heredoc_bodies(text)
    found = []
    for segment in _segments(_tokens(stripped)):
        argv = _unwrap(segment)
        if not argv:
            continue
        found.append(argv)
        if depth >= _MAX_DEPTH:
            continue
        for inner in _nested(argv):
            if isinstance(inner, list):
                found.extend(_collect(shlex.join(inner), depth + 1))
            else:
                found.extend(_collect(inner, depth + 1))
    if depth < _MAX_DEPTH:
        for opener_line, body in bodies:
            if _shell_fed(opener_line):
                found.extend(_collect(body, depth + 1))
    return found


def command_argvs(command: str) -> list:
    """Every simple command's argv, wrappers removed, nested commands included.

    Raises ValueError when the text does not tokenize, such as an unclosed
    quote. A guard should then fall back to its raw-text check.
    """
    if not command or not command.strip():
        return []
    return _collect(command, 0)
