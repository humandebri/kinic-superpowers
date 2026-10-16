"""Resumable scope relocation. Copies evidence; never deletes source nodes.

This is a journaled sequence of conditional writes, not a server transaction.
Local clients are blocked during cutover; remote writers must be quiescent.
"""
import copy
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import uuid

from kinic_project import (ProjectError, _contained, _ensure_ignored, _hash,
                           _path, _read, _save, fingerprint)
from kinic_registry import register, _record

LIMIT = 10000


def journal_path(project):
    owner = project.config_path.parent
    return _contained(owner, owner / '.superpowers/kinic-project/scope-migration.json')


def _inside(path, scope):
    return path == scope or path.startswith(scope + '/')


def _map(path, old, new):
    return new + path[len(old):] if _inside(path, old) else path


def _inventory(project, scope):
    nodes, pending = {}, [scope]
    while pending:
        path = pending.pop()
        if path in nodes or len(nodes) >= LIMIT:
            raise ProjectError('duplicate or oversized scope inventory')
        node = project._read_node(path)
        if not node or node.get('kind') not in ('file', 'folder', 'dir', 'directory'):
            raise ProjectError('invalid or missing inventory node: ' + path)
        if node['kind'] == 'file' and (not isinstance(node.get('content'), str) or not isinstance(node.get('metadata_json'), str)):
            raise ProjectError('incomplete source file: ' + path)
        nodes[path] = copy.deepcopy(node)
        if node['kind'] != 'file':
            children = project.transport(['list-children', '--path', path, '--json'])
            if not isinstance(children, list) or len(children) >= LIMIT:
                raise ProjectError('unsupported, truncated or oversized child listing')
            for child in children:
                if not isinstance(child, dict) or not isinstance(child.get('path'), str) or str(PurePosixPath(child['path']).parent) != path:
                    raise ProjectError('malformed child listing')
                pending.append(child['path'])
    return nodes


def _roots(project):
    roots = {project.root.resolve(), project.config_path.parent.resolve()}
    result = subprocess.run(['git', '-C', str(project.config_path.parent), 'worktree', 'list', '--porcelain', '-z'], capture_output=True, check=False)
    if result.returncode == 0:
        for field in result.stdout.decode().split('\0'):
            if field.startswith('worktree '):
                root = Path(field[9:]).resolve()
                if not root.is_dir():
                    raise ProjectError('linked worktree unavailable: ' + str(root))
                roots.add(root)
    elif (project.config_path.parent / '.git').exists():
        raise ProjectError('cannot inventory linked worktrees')
    for root in roots:
        config = root / '.kinic-superpowers.json'
        if config.exists() and config.resolve() != project.config_path.resolve():
            raise ProjectError('linked worktree has a separate config; reconcile before migration: ' + str(config))
    return sorted(roots)


def _manifest(value, old, new, new_config):
    value = copy.deepcopy(value)
    value['project_fingerprint'] = fingerprint(new_config)
    for item in value.get('artifacts', {}).values():
        item['path'] = _map(item['path'], old, new)
    return value


def _payloads(project, nodes, old, new, config):
    payloads = {}
    manifests = []
    for path, node in nodes.items():
        if node['kind'] != 'file':
            continue
        content, metadata = node['content'], node['metadata_json']
        if re.fullmatch(re.escape(old) + r'/workflows/[^/]+/manifest\.json', path):
            value = json.loads(content)
            project._validate_manifest(value, ready_required=False)
            project._verify_owner(node, value, 'manifest')
            manifests.append(value)
            content = json.dumps(_manifest(value, old, new, config), indent=2)
        elif path == old + '/index.md':
            # Retarget navigation destinations only; historical text stays exact.
            content = re.sub(r'(?<=\]\()' + re.escape(old) + r'(?=[/#)]|$)', new, content)
            owner = json.loads(metadata)
            identity = str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint(project.config)))
            if owner == project._owner({'id': identity, 'nonce': identity}, 'index'):
                identity = str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint(config)))
                metadata = json.dumps(project._owner({'id': identity, 'nonce': identity}, 'index'))
        payloads[_map(path, old, new)] = dict(content=content, metadata_json=metadata, kind='file')
    return payloads, manifests


def _local_snapshot(project, roots, manifests, config, old, new):
    changes = {}
    def add(path, after, before=None):
        path = Path(path)
        actual = _read(path) if path.exists() else None
        if before is not None and actual != before:
            raise ProjectError('local state changed while snapshotting')
        changes[str(path)] = {'before': actual, 'after': after}
    for root in roots:
        for folder in ('.superpowers/kinic/sessions', '.superpowers/kinic-project/manifests', '.superpowers/kinic-project/journals'):
            directory = _contained(root, root / folder)
            for path in sorted(directory.glob('*.json')):
                value = _read(_contained(root, path))
                if not isinstance(value, dict) or not isinstance(value.get('project_fingerprint'), str):
                    raise ProjectError('invalid local binding/cache: ' + str(path))
                if value['project_fingerprint'] != fingerprint(project.config):
                    changes[str(path)] = {'before': value, 'after': value, 'skipped': True}
                    continue
                updated = _manifest(value, old, new, config) if 'artifacts' in value else {**value, 'project_fingerprint': fingerprint(config)}
                add(path, updated)
        for manifest in manifests:
            artifacts = list(manifest['artifacts'].values())
            # Execution copies may have checkout-specific helper directories.
            if manifest['version'] == 2 and 'plan' in manifest['artifacts']:
                from kinic_workspace import execution_workspace
                for role in ('progress', 'review', 'completion'):
                    if role in manifest['artifacts']:
                        local = str((execution_workspace(root, manifest['artifacts']['plan']['local']) / (role + '.md')).relative_to(root))
                        artifacts.append({**manifest['artifacts'][role], 'local': local})
            for artifact in artifacts:
                remote = artifact['path']
                if not _inside(remote, old):
                    continue
                key = _hash(json.dumps([config['database_id'], remote, artifact['local']]))
                source = _contained(root, root / '.superpowers/kinic' / (key + '.json'))
                if not source.exists():
                    continue
                baseline = _read(source)
                dest_key = _hash(json.dumps([config['database_id'], _map(remote, old, new), artifact['local']]))
                dest = _contained(root, source.with_name(dest_key + '.json'))
                if dest.exists():
                    raise ProjectError('destination baseline collision: ' + str(dest))
                changes[str(dest)] = {'before': None, 'after': None, 'baseline': baseline, 'source_path': str(source), 'remote': remote}
    add(project.config_path, config)
    return changes


def _write(project, path, payload, expected=None):
    with tempfile.TemporaryDirectory(prefix='kinic-scope-') as tmp:
        source = Path(tmp) / 'body'
        source.write_text(payload['content'], encoding='utf-8')
        args = ['write-node', '--path', path, '--kind', 'file', '--input', str(source), '--metadata-json', payload['metadata_json'], '--json']
        if expected is not None:
            args += ['--expected-etag', expected]
        project.transport(args)


def _matches(node, payload):
    return node is not None and all(node.get(k) == v for k, v in payload.items())


def _copy(project, journal, save):
    for source, original in sorted(journal['nodes'].items()):
        if original['kind'] != 'file':
            target = journal['mapping'][source]
            project._parents(target + '/.directory-check')
    for target, payload in sorted(journal['payloads'].items()):
        node = project._read_node(target)
        ack = journal['copied'].get(target)
        if ack:
            if node != ack:
                raise ProjectError('copied target changed: ' + target)
            continue
        if node:
            if target not in journal['pending'] or not _matches(node, payload):
                raise ProjectError('foreign destination collision: ' + target)
        else:
            project._parents(target)
            journal['pending'][target] = payload
            save()
            _write(project, target, payload)
            node = project._read_node(target)
        if not _matches(node, payload):
            raise ProjectError('copy readback differs: ' + target)
        journal['copied'][target] = node
        save()


def _source_valid(project, journal):
    current = _inventory(project, journal['old_scope'])
    original = journal['nodes']
    if set(current) != set(original):
        raise ProjectError('source changed: scope membership differs')
    for path, node in current.items():
        if path == journal['old_scope'] + '/index.md' and journal.get('redirect_pending'):
            if _matches(node, journal['redirect']):
                if journal.get('redirect_ack') and node != journal['redirect_ack']:
                    raise ProjectError('source redirect changed')
                continue
        if node != original[path]:
            raise ProjectError('source changed: ' + path)


def _local_valid(project, journal):
    if [str(p) for p in _roots(project)] != journal['roots']:
        raise ProjectError('linked worktrees changed during migration')
    known = set(journal['local'])
    for root_text in journal['roots']:
        root = Path(root_text)
        for folder in ('.superpowers/kinic/sessions', '.superpowers/kinic-project/manifests', '.superpowers/kinic-project/journals'):
            for path in (root / folder).glob('*.json'):
                if str(path) not in known:
                    raise ProjectError('new local binding/cache during migration: ' + str(path))
    for path_text, change in journal['local'].items():
        path = Path(path_text)
        owner = next((Path(root) for root in journal['roots'] if path.is_relative_to(Path(root))), None)
        if owner is None:
            raise ProjectError('local migration path outside recorded roots')
        _contained(owner, path)
        value = _read(path) if path.exists() else None
        if value not in (change['before'], change['after']):
            raise ProjectError('local state changed during migration: ' + str(path))
        if 'source_path' in change and _read(Path(change['source_path'])) != change['baseline']:
            raise ProjectError('local baseline changed during migration')


def _summary(journal, apply):
    return {'applied': apply, 'phase': journal['phase'], 'old_scope': journal['old_scope'], 'new_scope': journal['new_scope'],
            'files': len(journal['payloads']), 'copied': len(journal['copied']), 'conflicts': [],
            'local_skipped': sum(bool(c.get('skipped')) for c in journal['local'].values()),
            'journal': journal.get('journal'), 'transaction': 'conditional writes; remote writers must be quiescent; original evidence retained'}


def migrate(project, scope, apply=False):
    _path(scope)
    path = journal_path(project)
    if not apply:
        return _migrate(project, scope, False, path)
    # Use the primary checkout even when invoked from a linked worktree.
    import fcntl
    lock_path = _contained(project.config_path.parent, path.with_suffix('.lock'))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProjectError('scope migration is already running') from exc
        return _migrate(project, scope, apply, path)


def _migrate(project, scope, apply, path):
    if path.exists():
        journal = _read(path)
        if journal['new_scope'] != scope:
            raise ProjectError('another scope migration journal exists; inspect it before starting another move')
        if project.config not in (journal['old_config'], journal['new_config']):
            raise ProjectError('configuration differs from migration journal')
    else:
        old = project.config['scope']
        if _inside(old, scope) or _inside(scope, old):
            raise ProjectError('migration scopes must be distinct non-overlapping trees')
        if not project.config.get('project_id'):
            if not apply:
                return {'applied': False, 'phase': 'registration_required', 'old_scope': old, 'new_scope': scope, 'conflicts': [], 'files': 0, 'copied': 0}
            register(project)
        config = copy.deepcopy(project.config)
        config['scope'] = scope
        for item in config.get('legacy_artifacts', {}).values():
            item['path'] = _map(item['path'], old, scope)
        nodes = _inventory(project, old)
        registration = nodes.get(old + '/project.json')
        if not registration or _record(project, registration, config.get('repository_key'))['id'] != config['project_id']:
            raise ProjectError('source project registration differs from config')
        payloads, manifests = _payloads(project, nodes, old, scope, config)
        roots = _roots(project)
        journal = dict(version=1, id=str(uuid.uuid4()), journal=str(path), phase='copy', old_scope=old, new_scope=scope,
                       old_config=copy.deepcopy(project.config), new_config=config, nodes=nodes,
                       mapping={p: _map(p, old, scope) for p in nodes}, payloads=payloads,
                       copied={}, pending={}, roots=[str(r) for r in roots],
                       local=_local_snapshot(project, roots, manifests, config, old, scope))
        # Foreign files block before the first copy. Unrelated children survive.
        for target in payloads:
            if project._read_node(target) is not None:
                raise ProjectError('foreign destination collision: ' + target)
        if not apply:
            return _summary(journal, False)
        _ensure_ignored(project.root, project.config_path)
        _save(path, journal)
    if not apply:
        return _summary(journal, False)
    if journal['phase'] == 'complete':
        return _summary(journal, True)
    def save():
        _save(path, journal)
    _source_valid(project, journal)
    _copy(project, journal, save)
    _source_valid(project, journal)
    if journal['phase'] == 'copy':
        for change in journal['local'].values():
            if 'baseline' not in change:
                continue
            original = journal['nodes'].get(change['remote'])
            baseline = change['baseline']
            if original and baseline.get('etag') == original['etag'] and baseline.get('sha256') == _hash(original['content']):
                copied = journal['copied'][journal['mapping'][change['remote']]]
                change['after'] = {**baseline, 'etag': copied['etag'], 'metadata_json': copied['metadata_json']}
        _local_valid(project, journal)
        journal['phase'] = 'local_cutover'
        save()
    _local_valid(project, journal)
    for filename, change in journal['local'].items():
        if change['after'] is not None and not change.get('skipped'):
            _save(Path(filename), change['after'])
    project.config = copy.deepcopy(journal['new_config'])
    journal['phase'] = 'redirect'
    save()
    _source_valid(project, journal)
    _copy(project, journal, save)
    index = journal['old_scope'] + '/index.md'
    original = journal['nodes'].get(index)
    if original:
        journal['redirect'] = dict(kind='file', content='# Project moved\n\n[Open project](' + scope + '/index.md)\n\nOriginal index and source versions are retained in migration journal ' + journal['id'] + '.\n', metadata_json=original['metadata_json'])
        journal['redirect_pending'] = True
        save()
        node = project._read_node(index)
        if node == original:
            _write(project, index, journal['redirect'], original['etag'])
            node = project._read_node(index)
        if not _matches(node, journal['redirect']):
            raise ProjectError('source index changed before redirect')
        journal['redirect_ack'] = node
        save()
    journal['phase'] = 'complete'
    save()
    return _summary(journal, True)
