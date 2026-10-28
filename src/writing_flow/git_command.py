"""Shared parsing for hooks that inspect a git command on PreToolUse:Bash.

Four guards read the same shell string and need the same two things from it:
the body of any heredoc removed, and the arguments that actually sit in a given
git subcommand's argument position.

Both exist because of a reported false positive. `git-no-md-commits` blocked a
`cat > notes.md <<'EOF'` heredoc that invoked no git command at all: the heredoc
body contained the words "staged" and "committed" near a `.md` path, and a
substring match on the whole command string cannot tell prose in a heredoc from
an argument to git. Matching on command position, over a string whose heredoc
bodies are gone, is the fix.
"""

import re

# A heredoc opener: << or <<-, optional quoting, then the delimiter word.
_HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def heredoc_bodies(command: str) -> tuple:
    """(`command` with heredoc bodies removed, [(opener line, body), ...]).

    The rest of the opener line survives, so a redirect after the opener, as in
    `cat <<EOF > out.txt`, still reads as shell. The body and its closing
    delimiter are removed without a placeholder, so stripping twice gives the
    same text. Callers that must know what a shell will run get each body back
    with the line that consumes it.
    """
    out = []
    bodies = []
    i = 0
    text = command
    while True:
        match = _HEREDOC_OPEN.search(text, i)
        if not match:
            out.append(text[i:])
            break
        delimiter = match.group(2)
        newline = text.find("\n", match.end())
        if newline == -1:
            out.append(text[i:])
            break
        line_start = text.rfind("\n", 0, match.start()) + 1
        opener_line = text[line_start:newline]
        # Drop the `<<EOF` token itself, so a second pass finds no opener.
        out.append(text[i:match.start()] + text[match.end():newline + 1])
        # Body runs to a line that is exactly the delimiter, allowing leading
        # tabs for the <<- form. Unterminated means the rest is body.
        close = re.compile(rf"^[ \t]*{re.escape(delimiter)}[ \t]*$", re.MULTILINE)
        closing = close.search(text, newline + 1)
        end = closing.start() if closing else len(text)
        bodies.append((opener_line, text[newline + 1:end]))
        i = closing.end() if closing else len(text)
    return "".join(out), bodies


def strip_heredocs(command: str) -> str:
    """`command` with every heredoc body removed.

    A heredoc body is data the command consumes, so a guard that reasons about
    what a command does should not read it as shell. The one exception is a
    body fed to a shell, which `heredoc_bodies` returns for the caller to check.
    """
    return heredoc_bodies(command)[0]


# Global options that take a separate value, as in `git -C /repo push`.
_GIT_VALUE_OPTS = frozenset((
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
    "--super-prefix", "--config-env",
))


def git_subcommand(args: list) -> tuple:
    """(subcommand, its arguments) from the argv that follows `git`.

    Global options and their values are skipped, so `git -C /repo push -f`
    gives ("push", ["-f"]). An argv with no subcommand gives ("", []).
    """
    rest = list(args)
    while rest and rest[0].startswith("-"):
        option = rest.pop(0)
        if option in _GIT_VALUE_OPTS and rest:
            rest.pop(0)
    if not rest:
        return "", []
    return rest[0], rest[1:]


def has_short_flag(args: list, letter: str) -> bool:
    """True when a short-option cluster such as `-fd` carries `letter`."""
    return any(
        re.fullmatch(rf"-[A-Za-z]*{re.escape(letter)}[A-Za-z]*", arg) for arg in args
    )


def _split_commands(command: str) -> list:
    """Split a shell string on separators that introduce a new command."""
    return re.split(r"(?:&&|\|\||\||;|\n)", command)


def git_invocations(command: str, subcommand: str) -> list:
    """Argument strings for each `git <subcommand>` in `command`.

    Heredoc bodies are stripped first, and each segment must open with git
    (allowing a leading `sudo`, an env assignment, or a `-C <dir>` flag) before
    its arguments count. A mention of the subcommand inside a quoted message or
    a heredoc body yields nothing.
    """
    found = []
    pattern = re.compile(
        r"^\s*(?:sudo\s+)?(?:[A-Za-z_]\w*=\S*\s+)*git\b(?P<pre>(?:\s+-[^\s]+(?:\s+\S+)?)*)"
        rf"\s+{re.escape(subcommand)}\b(?P<args>.*)$"
    )
    for segment in _split_commands(strip_heredocs(command)):
        match = pattern.match(segment)
        if match:
            found.append(match.group("args").strip())
    return found


def is_git_subcommand(command: str, subcommand: str) -> bool:
    """True when `command` actually invokes `git <subcommand>`."""
    return bool(git_invocations(command, subcommand))


_QUOTED = re.compile(r"""(?:"([^"]*)"|'([^']*)')""")


def unquoted_args(args: str) -> list:
    """Argument tokens from one invocation's argument string.

    Quoted runs stay whole so a commit message counts as one token rather than
    a stream of words that could be mistaken for paths.
    """
    tokens = []
    index = 0
    for match in _QUOTED.finditer(args):
        tokens.extend(args[index:match.start()].split())
        tokens.append(match.group(1) if match.group(1) is not None else match.group(2))
        index = match.end()
    tokens.extend(args[index:].split())
    return tokens
