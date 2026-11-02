"""Local workspace selection and Git exclusion for Wiki working copies."""
from pathlib import Path


def execution_workspace(root, plan):
    root = Path(root).resolve()
    plan = Path(plan)
    if plan.is_absolute() or '..' in plan.parts:
        raise ValueError('sdd-workspace plan path must be repository-relative')
    base = root / '.superpowers/sdd'
    candidate = base / plan.stem
    counter = 1
    while True:
        marker = candidate / 'plan-path'
        current = root
        for part in marker.relative_to(root).parts:
            current /= part
            if current.is_symlink():
                raise ValueError('sdd-workspace paths and markers must not be symlinks')
        if not marker.exists() or marker.read_text().strip() == plan.as_posix():
            return candidate
        candidate = base / (plan.stem + '-' + plan.parent.name + ('' if counter == 1 else '-' + str(counter)))
        counter += 1


def exclude_document_copy(root, relative):
    """Exclude one successful wiki working copy without changing tracked files.

Git resolves info/exclude through the common directory for linked worktrees.
Never create Git metadata when the supplied root is not a checkout root.
"""
    import fcntl
    import subprocess
    root = Path(root).resolve()
    if not relative.startswith(('docs/superpowers/specs/', 'docs/superpowers/plans/')):
        return
    if '\n' in relative or '\r' in relative:
        raise ValueError('document path cannot contain line breaks')
    def git(*args):
        return subprocess.run(['git', '--literal-pathspecs', '-C', str(root), *args],
                              capture_output=True, text=True, timeout=10, check=False)
    try:
        top = git('rev-parse', '--show-toplevel')
    except FileNotFoundError:
        return
    if top.returncode or Path(top.stdout.strip()).resolve() != root:
        return
    tracked = git('ls-files', '--error-unmatch', '--', relative)
    if tracked.returncode == 0:
        return
    location = git('rev-parse', '--path-format=absolute', '--git-path', 'info/exclude')
    if location.returncode:
        raise ValueError('cannot resolve Git info/exclude for wiki working copy')
    exclude = Path(location.stdout.strip())
    if exclude.is_symlink():
        raise ValueError('Git info/exclude must not be a symlink')
    # Slash anchors the pattern to the repository root. Escape glob characters
    # so publishing test[1].md cannot inadvertently hide test1.md.
    pattern = '/' + ''.join('\\' + char if char in '\\*?[]!# ' else char for char in relative)
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open('a+', encoding='utf-8') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        content = stream.read()
        if pattern not in content.splitlines():
            stream.seek(0, 2)
            stream.write(('\n' if content and not content.endswith('\n') else '') + pattern + '\n')
