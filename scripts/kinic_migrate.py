"""Bounded, resumable cleanup of the two approved historical test namespaces.

Migrate substantive pages first, then snapshot retained destinations with this
journal. snapshot() only reads the wiki. run() defaults to dry-run. This module
never copies pages, invents approvals, or deletes the substantive e2e namespace.
The journal contains complete old nodes, including content, metadata and etags.
"""
import copy
import json
import html
import posixpath
import re
from urllib.parse import unquote, urlsplit
from pathlib import Path, PurePosixPath
from kinic_project import ProjectError, _save

ALLOWED_PREFIXES = (
    '/Knowledge/kinic-superpowers/live-check-d5c15c8572e24a189d40939ea15a4e7e',
    '/Knowledge/kinic-superpowers/onboarding-20261015',
)
LIMIT = 10000


def _inside(path, prefix):
    return path == prefix or path.startswith(prefix + '/')


def references_cleanup(path, node, prefixes):
    """Conservatively resolve link/path tokens relative to their source page.

    Cleanup is destructive: plain path mentions, code examples and metadata
    count too. Tokenization covers Markdown destinations/reference definitions,
    Wiki links, HTML attributes and JSON strings without relying on one markup
    dialect. False positives stop cleanup for inspection rather than lose data.
    """
    text = html.unescape(node.get('content', '') + '\n' + str(node.get('metadata_json', '')))
    # Decode before tokenization so encoded absolute/relative links and HTML
    # entities receive the same protection as literal Wiki paths.
    text = unquote(text).replace('\\/', '/')
    if any(prefix in text for prefix in prefixes):
        return True
    for token in re.split(r"[\s<>\[\]()\"'|=,{}]+", text):
        if not token:
            continue
        try:
            link = urlsplit(token)
        except ValueError:
            continue
        if link.scheme or link.netloc or not link.path:
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), link.path))
        if any(_inside(resolved, prefix) for prefix in prefixes):
            return True
    return False


def _connection(project):
    return {k: project.config.get(k) for k in ('database_id', 'canister_id', 'replica_host', 'identity')}


def inventory(project, root='/Knowledge', limit=LIMIT):
    """Read a complete bounded subtree; reject malformed/partial listing shapes."""
    nodes, pending = {}, [root]
    while pending:
        path = pending.pop()
        if path in nodes:
            raise ProjectError('duplicate inventory path')
        node = project._read_node(path)
        if node is None:
            raise ProjectError('inventory node disappeared: ' + path)
        if node.get('path') != path or not isinstance(node.get('etag'), str):
            raise ProjectError('invalid inventory node')
        nodes[path] = copy.deepcopy(node)
        if len(nodes) > limit:
            raise ProjectError('inventory bound exceeded; no deletion attempted')
        if node.get('kind') == 'folder':
            children = project.transport(['list-children', '--path', path, '--json'])
            if not isinstance(children, list):
                raise ProjectError('unsupported or paginated listing; refusing partial inventory')
            for child in children:
                child_path = child.get('path')
                if not isinstance(child_path, str) or str(PurePosixPath(child_path).parent) != path:
                    raise ProjectError('invalid child path')
                pending.append(child_path)
        elif node.get('kind') != 'file':
            raise ProjectError('unsupported node kind')
    return nodes


def snapshot(project, journal_path, prefixes, retained_paths=(), reference_root='/Knowledge'):
    """Create immutable inventory before cleanup; never overwrite a journal."""
    journal_path = Path(journal_path)
    if journal_path.exists():
        raise ProjectError('journal already exists; resume it instead')
    prefixes = list(prefixes)
    if not prefixes or len(set(prefixes)) != len(prefixes) or not set(prefixes) <= set(ALLOWED_PREFIXES):
        raise ProjectError('cleanup prefix not explicitly authorized')
    if reference_root != '/Knowledge':
        raise ProjectError('reference scan must cover /Knowledge')
    nodes = inventory(project, reference_root)
    targets = {p:n for p,n in nodes.items() if any(_inside(p,r) for r in prefixes)}
    if not targets or any(p not in targets for p in prefixes):
        raise ProjectError('cleanup prefix missing')
    retained = {}
    for path in retained_paths:
        if path in targets or path not in nodes or nodes[path]['kind'] != 'file':
            raise ProjectError('retained destination must be an existing file outside cleanup')
        retained[path] = nodes[path]
    record = dict(version=1, connection=_connection(project), prefixes=prefixes,
                  nodes=targets, retained=retained, deleted=[], pending=None,
                  reference_root=reference_root, log=[])
    _save(journal_path, record)
    return record


def run(project, journal_path, apply=False):
    """Preflight all snapshots/references, then delete deepest nodes with etags.

    An uncertain delete is journaled before sending; resume accepts its absence.
    Unexpected missing files, extra children, changed files or surviving links
    stop the operation. Concurrent cross-document references cannot be locked;
    each call rescans, but this is not a multi-document transaction.
    """
    journal_path = Path(journal_path)
    record = json.loads(journal_path.read_text())
    prefixes = record.get('prefixes', [])
    if (record.get('version') != 1 or record.get('connection') != _connection(project)
            or not prefixes or not set(prefixes) <= set(ALLOWED_PREFIXES)
            or record.get('reference_root') != '/Knowledge'):
        raise ProjectError('invalid journal or connection mismatch')
    targets = record['nodes']
    if any(not any(_inside(p,r) for r in prefixes) or n.get('path') != p
           for p,n in targets.items()):
        raise ProjectError('journal target outside authorized prefixes')
    deleted = set(record['deleted'])
    if not deleted <= targets.keys() or record['pending'] not in (None, *targets):
        raise ProjectError('invalid deletion journal state')
    current = inventory(project)
    for path, node in record['retained'].items():
        if current.get(path) != node:
            raise ProjectError('retained migration destination changed: ' + path)
    extra = [p for p in current if any(_inside(p,r) for r in prefixes) and p not in targets]
    if extra:
        raise ProjectError('new children in cleanup scope: ' + ', '.join(extra))
    for path, original in targets.items():
        actual = current.get(path)
        if path in deleted:
            if actual is not None:
                raise ProjectError('deleted path recreated: ' + path)
            continue
        if actual is None:
            if path != record['pending']:
                raise ProjectError('unaccounted missing source: ' + path)
            continue
        # A folder etag can change as our own children are removed. Its contents
        # and metadata must remain unchanged, and deletion below checks emptiness.
        if original['kind'] == 'folder' and (deleted or record['pending']):
            if {k:v for k,v in actual.items() if k != 'etag'} != {k:v for k,v in original.items() if k != 'etag'}:
                raise ProjectError('folder changed: ' + path)
        elif actual != original:
            raise ProjectError('source changed: ' + path)
    for path, node in current.items():
        if path in targets or node['kind'] != 'file':
            continue
        if references_cleanup(path, node, prefixes):
            raise ProjectError('surviving reference must be resolved first: ' + path)
    todo = sorted(set(targets)-deleted, key=lambda p:(-len(PurePosixPath(p).parts), p))
    if not apply:
        return dict(applied=False, delete=todo, retained=list(record['retained']))
    for path in todo:
        actual = project._read_node(path)
        if actual is None:
            if record['pending'] != path:
                raise ProjectError('source disappeared during apply: ' + path)
        else:
            original = current[path]
            if actual != original:
                # Changes to folder etags due to our successful child deletions
                # are expected; other changes and new children remain blocking.
                if actual['kind'] != 'folder' or {k:v for k,v in actual.items() if k != 'etag'} != {k:v for k,v in original.items() if k != 'etag'}:
                    raise ProjectError('source changed during apply: ' + path)
            if actual['kind'] == 'folder' and project.transport(['list-children','--path',path,'--json']) != []:
                raise ProjectError('folder not empty: ' + path)
            record['pending'] = path
            _save(journal_path, record)
            project.transport(['delete-node','--path',path,'--expected-etag',actual['etag'],'--json'])
            if project._read_node(path) is not None:
                raise ProjectError('delete readback failed: ' + path)
        record['deleted'].append(path)
        record['pending'] = None
        record['log'].append({'action':'deleted', 'path':path, 'source_etag':targets[path]['etag']})
        _save(journal_path, record)
    return dict(applied=True, deleted=record['deleted'], retained=list(record['retained']))
