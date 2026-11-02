"""Repository connection, recoverable wiki workflows and per-chat selection.

Only public configuration is persisted. The remote namespace is UUID based;
creation has local exclusion, not a server-side transaction or distributed lock.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kinic_workspace import execution_workspace, exclude_document_copy


class ProjectError(Exception):
    pass


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(config):
    return _hash(json.dumps([config.get(k) for k in
                            ('database_id', 'canister_id', 'replica_host', 'scope')], sort_keys=True))


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ProjectError(f'cannot read {path}: {exc}') from exc


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as out:
        name = out.name
        json.dump(data, out, indent=2)
        out.write('\n')
    try:
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _contained(root, path):
    """Reject symlinked state paths, including dangling file symlinks."""
    root = Path(root).resolve()
    path = Path(path)
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise ProjectError('local state path escapes project') from exc
    current = root
    for part in parts:
        if part in ('.', '..'):
            raise ProjectError('local state path escapes project')
        current = current / part
        if current.is_symlink():
            raise ProjectError(f'local state symlink is not permitted: {current}')
    if not path.resolve().is_relative_to(root):
        raise ProjectError('local state path escapes project')
    return path


def _ensure_ignored(root, target):
    ignore = _contained(root, root / '.gitignore')
    contents = ignore.read_text() if ignore.exists() else ''
    paths = ['.superpowers/', '.kinic-superpowers.json', '.kinic-superpowers.json.v1-backup', '.kinic-superpowers.json.v2-backup']
    if target.is_relative_to(root):
        paths += ['/' + str(target.relative_to(root)), '/' + str(target.relative_to(root)) + '.v1-backup', '/' + str(target.relative_to(root)) + '.v2-backup']
    additions = [line for line in dict.fromkeys(paths) if line not in contents.splitlines()]
    if additions:
        ignore.write_text(contents + ('\n' if contents and not contents.endswith('\n') else '') + '\n'.join(additions) + '\n')
    # The connection can live in the primary checkout while local copies live
    # here. Ignore the shared configuration in its owning checkout as well.
    _, shared = discover(root)
    if target == shared and target.parent != root:
        _ensure_ignored(target.parent, target)


def discover(cwd, config_path=None):
    """Discover current checkout and shared config with filesystem reads only."""
    cwd = Path(cwd).resolve()
    root = cwd
    for candidate in (cwd, *cwd.parents):
        if (candidate / '.git').exists():
            root = candidate
            break
        if not config_path and (candidate / '.kinic-superpowers.json').exists():
            root = candidate
            break
    if config_path:
        return root, Path(config_path).resolve()
    local = root / '.kinic-superpowers.json'
    if local.exists():
        return root, local
    git = root / '.git'
    if git.is_file():
        text = git.read_text().strip()
        if text.startswith('gitdir: '):
            directory = (root / text[8:]).resolve()
            common = directory / 'commondir'
            if common.is_file():
                shared = (directory / common.read_text().strip()).resolve().parent / local.name
                return root, shared
    return root, local


def _invoke(cli, cwd, args):
    try:
        result = subprocess.run([cli, *args], cwd=cwd, capture_output=True,
                                text=True, encoding='utf-8', timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectError(f'kinic-vfs-cli could not finish: {exc}') from exc
    if result.returncode and not ('agent' in args and 'doctor' in args and result.stdout.strip()):
        raise ProjectError(result.stderr.strip())
    if 'database' in args and 'link' in args:
        return {'path': result.stdout.strip()}
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise ProjectError('kinic-vfs-cli returned invalid JSON') from exc


def _path(value):
    if not isinstance(value, str) or not value.startswith('/') or value == '/' or str(PurePosixPath(value)) != value or '..' in PurePosixPath(value).parts:
        raise ProjectError('scope must be a canonical absolute wiki path below /Knowledge')
    if not value.startswith(('/Knowledge/', '/Testing/kinic-superpowers/')):
        raise ProjectError('scope must be below /Knowledge or /Testing/kinic-superpowers')
    return value


def _validate_connection(config):
    if not isinstance(config, dict) or config.get('version') not in (2, 3):
        raise ProjectError('expected version 2 or 3 connection configuration')
    for key in ('database_id', 'canister_id', 'replica_host', 'cli'):
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProjectError(f'configured {key} must be a nonempty string')
    _path(config.get('scope'))
    identity = config.get('identity')
    if not isinstance(identity, dict):
        raise ProjectError('configured identity must be an object')
    principal = identity.get('principal')
    if not isinstance(principal, str) or not principal.strip() or principal == '2vxsx-fae':
        raise ProjectError('configured identity principal must be an authenticated nonempty string')
    if type(identity.get('allow_non_ii_identity')) is not bool:
        raise ProjectError('configured allow_non_ii_identity must be a boolean')


def _default_scope(root):
    from kinic_registry import propose
    return '/Knowledge/' + propose(root)['project_name']


def _database_name(databases, database_id):
    if not isinstance(databases, list):
        raise ProjectError('invalid database list response')
    for item in databases:
        if isinstance(item, dict) and item.get('database_id') == database_id:
            return item.get('name') or (item.get('metadata') or {}).get('name')
    return None


def _writable_database(item):
    return (isinstance(item, dict) and item.get('status') == 'active'
            and item.get('role') in ('owner', 'writer')
            and item.get('cycles_suspended_at_ms') is None
            and item.get('deleted_at_ms') is None
            and isinstance(item.get('database_id'), str) and bool(item['database_id']))


def _require_writable_database(databases, database_id):
    if not isinstance(databases, list):
        raise ProjectError('invalid database list response')
    for item in databases:
        if isinstance(item, dict) and item.get('database_id') == database_id:
            if _writable_database(item):
                return
            name = _database_name(databases, database_id) or database_id
            raise ProjectError(f'database {name!r} is not writable; choose an active owner/writer database')
    raise ProjectError(f'database {database_id!r} is not writable; current identity has no listed write access')


CONNECTION_KEYS = ('database_id', 'canister_id', 'replica_host')


def _auth_args(config):
    args = ['--identity-mode', 'identity']
    if config.get('identity', {}).get('allow_non_ii_identity'):
        args += ['--allow-non-ii-identity']
    return args


def _connection_args(connection, config):
    args = _auth_args(config)
    for key in CONNECTION_KEYS:
        args += ['--' + key.replace('_', '-'), connection[key]]
    return args


def _migration_conflicts(config, effective):
    for key in CONNECTION_KEYS:
        value = effective.get(key)
        source = (effective.get('sources') or {}).get(key, effective.get(key + '_source'))
        if value is not None and value != config.get(key) and source not in ('default', 'mainnet default'):
            raise ProjectError('common CLI configuration conflicts with saved connection: ' + key)


def _backup(target, old):
    backup = target.with_name(target.name + '.v' + str(old['version']) + '-backup')
    if backup.exists():
        if _read(backup) != old:
            raise ProjectError('existing backup differs; preserve it before migrating')
    else:
        _save(backup, old)


def _link_and_verify(invoke, config):
    invoke([*_connection_args(config, config), 'database', 'link', config['database_id']])
    effective = invoke([*_auth_args(config), 'database', 'current', '--json'])
    if any(effective.get(key) != config[key] for key in CONNECTION_KEYS):
        raise ProjectError('linked CLI connection differs from project binding; reconcile overriding settings and retry')


def initialize(cwd, database_id=None, scope=None, cli_path='kinic-vfs-cli',
               allow_non_ii_identity=False, canister_id=None, replica_host=None, run=None,
               migrate=False, config_path=None, inspect=False):
    root, target = discover(cwd, config_path)
    legacy = None
    old = _read(target) if target.exists() else None
    if database_id is None and old:
        database_id = old.get('database_id')
    if scope is None:
        scope = (old or {}).get('scope') or _default_scope(target.parent)
    _path(scope)
    if database_id is not None and (not isinstance(database_id, str) or not database_id.strip()):
        raise ProjectError('database_id must be a nonempty string')
    if old is not None:
        if old.get('version') == 1:
            if not migrate and not inspect:
                raise ProjectError('version 1 configuration retained; migrate explicitly before init')
            if old.get('database_id') != database_id:
                raise ProjectError('migration database must match version 1 configuration')
            legacy = old
        if not legacy:
            _validate_connection(old)
        if not legacy and (old.get('database_id') != database_id or old.get('scope') != scope or (canister_id and canister_id != old.get('canister_id')) or (replica_host and replica_host != old.get('replica_host'))):
            raise ProjectError('connection already configured; refusing to retarget existing configuration')
        if not legacy and old.get('version') == 2 and migrate and not inspect:
            executable = old['cli']
            invoke = run if run is not None else lambda args: _invoke(executable, target.parent, args)
            auth = _auth_args(old)
            effective = invoke([*auth, 'database', 'current', '--json'])
            _migration_conflicts(old, effective)
            project = Project(root, target, run=run)
            project._validate_identity()
            _require_writable_database(project.transport(['database', 'list', '--json']), database_id)
            project.transport(['status', '--json'])
            _backup(target, old)
            _link_and_verify(invoke, old)
            config = {**old, 'version': 3}
            _ensure_ignored(root, target)
            _save(target, config)
            return config
        if not legacy:
            project = Project(root, target, run=run)
            project._checked_args()
            databases = project.transport(['database', 'list', '--json'])
            _require_writable_database(databases, database_id)
            if inspect:
                name = _database_name(databases, database_id)
                return {**old, 'database_name': name, 'selection_required': False, 'database_candidates': []}
            _ensure_ignored(root, target)
            if old.get('legacy_workflow_id'):
                project._migrate_legacy()
            return old
    located = shutil.which(cli_path)
    executable = located or cli_path
    if located or os.path.dirname(executable):
        # Resolve relative PATH entries and explicit paths against the invoking
        # shell's cwd before transport changes cwd to the selected checkout.
        executable = str(Path(executable).resolve())
    invoke = run if run is not None else lambda args: _invoke(executable, target.parent, args)
    args = ['--identity-mode', 'identity']
    if database_id:
        args += ['--database-id', database_id]
    if canister_id:
        args += ['--canister-id', canister_id]
    if replica_host:
        args += ['--replica-host', replica_host]
    if allow_non_ii_identity:
        args += ['--allow-non-ii-identity']
    ident = invoke([*args, 'identity', 'show', '--json'])
    principal = ident.get('principal')
    if not isinstance(principal, str) or not principal or principal == '2vxsx-fae':
        raise ProjectError('authenticated identity principal required')
    connection = invoke([*args, 'database', 'current', '--json'])
    databases = invoke([*args, 'database', 'list', '--json'])
    if not isinstance(databases, list):
        raise ProjectError('invalid database list response')
    candidates = []
    if database_id is None:
        database_id = connection.get('database_id')
        if database_id is None:
            for item in databases:
                if _writable_database(item):
                    candidates.append({'database_id': item['database_id'],
                                       'name': item.get('name') or (item.get('metadata') or {}).get('name') or item['database_id'],
                                       'role': item['role']})
            if len(candidates) == 1:
                database_id = candidates[0]['database_id']
    config = dict(version=3, database_id=database_id, scope=scope, cli=executable,
                  canister_id=canister_id or connection.get('canister_id'),
                  replica_host=replica_host or connection.get('replica_host'),
                  identity={'principal': principal, 'allow_non_ii_identity': bool(allow_non_ii_identity)})
    if old is None:
        config['registry_required'] = True
    if database_id is None:
        if inspect:
            return {**config, 'selection_required': True, 'database_candidates': candidates}
        choices = ', '.join(f'{item["name"]} ({item["database_id"]})' for item in candidates)
        raise ProjectError('database selection required; run init --inspect and select a database by name: '
                           + (choices or 'no active writable databases found'))
    _validate_connection(config)
    _require_writable_database(databases, database_id)
    # Pin the inspected endpoint for the authenticated access check.
    verify_args = ['--database-id', database_id, '--identity-mode', 'identity',
                   '--canister-id', config['canister_id'], '--replica-host', config['replica_host']]
    if allow_non_ii_identity:
        verify_args += ['--allow-non-ii-identity']
    invoke([*verify_args, 'status', '--json'])
    if inspect:
        return {**config, 'database_name': _database_name(databases, database_id),
                'selection_required': False, 'database_candidates': candidates,
                'migration_required': legacy is not None}
    if legacy:
        effective = invoke([*_auth_args(config), 'database', 'current', '--json'])
        _migration_conflicts(config, effective)
        _backup(target, legacy)
    _link_and_verify(invoke, config)
    _ensure_ignored(root, target)
    if legacy:
        # Keep exact legacy artifact maps; publishing the migration manifest never
        # rewrites pre-existing source documents or their cached etags.
        config['legacy_artifacts'] = legacy.get('artifacts', {})
        config['legacy_workflow_id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint(config) + json.dumps(legacy, sort_keys=True)))
    _save(target, config)
    if legacy:
        Project(root, target, run=run)._migrate_legacy()
    return config


class Project:
    def __init__(self, cwd, config_path=None, cli_override=None, allow_non_ii_identity=False, run=None, allow_migration=False):
        self.root, self.config_path = discover(cwd, config_path)
        self.config = _read(self.config_path)
        if not allow_migration:
            migration = self.config_path.parent / '.superpowers/kinic-project/scope-migration.json'
            if migration.exists() and _read(migration).get('phase') != 'complete':
                raise ProjectError('scope migration is incomplete; resume project migrate before other operations')
        self.version = self.config.get('version')
        if self.version not in (1, 2, 3):
            raise ProjectError('unsupported project config version')
        self.cli = cli_override or self.config.get('cli', 'kinic-vfs-cli')
        self._run = run if run is not None else lambda args: _invoke(self.cli, self.config_path.parent if self.version == 3 else self.root, args)
        self.directory = self._state(self.root / '.superpowers/kinic-project')
        if self.version in (2, 3):
            _validate_connection(self.config)

    def _state(self, path):
        return _contained(self.root, path)

    def _read_state(self, path):
        return _read(self._state(path))

    def _save_state(self, path, data):
        return _save(self._state(path), data)

    def _args(self, connection=None):
        if connection is not None:
            return _connection_args(connection, self.config)
        args = ['--database-id', self.config['database_id'], '--identity-mode', 'identity']
        for key in ('canister_id', 'replica_host'):
            if self.config.get(key):
                args += ['--' + key.replace('_', '-'), self.config[key]]
        if self.config.get('identity', {}).get('allow_non_ii_identity'):
            args += ['--allow-non-ii-identity']
        return args

    def _validate_identity(self, args=None):
        result = self._run([*(self._args() if args is None else args), 'identity', 'show', '--json'])
        if result.get('principal') != self.config.get('identity', {}).get('principal'):
            raise ProjectError('selected identity principal changed; refusing access')

    def _checked_args(self):
        if self.version == 3:
            connection = self._run([*_auth_args(self.config), 'database', 'current', '--json'])
            if any(connection.get(key) != self.config[key] for key in CONNECTION_KEYS):
                raise ProjectError('effective CLI connection differs from project binding; reconcile shared settings before access')
            args = self._args(connection)
        else:
            args = self._args()
        self._validate_identity(args)
        return args

    def transport(self, args):
        checked = self._checked_args()
        # Legacy Workspace supplies its own database prefix; saved connection wins.
        args = list(args)
        if '--database-id' in args:
            index = args.index('--database-id')
            if args[index + 1] != self.config['database_id']:
                raise ProjectError('database mismatch')
            del args[index:index + 2]
        return self._run([*checked, *args])

    def doctor(self, session=None):
        """Read-only diagnostics; optional learning support never gates documents."""
        checks = [{'id': 'adapter.configuration', 'status': 'ok', 'required': True,
                   'version': self.version, 'path': str(self.config_path)}]
        transport = 'unknown'
        required = ('identity', 'database.caller', 'database.read', 'api.read_node')
        try:
            if self.version == 3:
                effective = self._run([*_auth_args(self.config), 'database', 'current', '--json'])
                if any(effective.get(key) != self.config.get(key) for key in CONNECTION_KEYS):
                    transport = 'error'
                    raise ProjectError('effective CLI connection differs from project binding')
                diagnostic_args = _connection_args(effective, self.config)
            else:
                # Legacy operations use saved pins until explicit migration.
                # Diagnose that same destination, even without a common link.
                diagnostic_args = self._args()
            checks.append({'id': 'adapter.binding', 'status': 'ok', 'required': True})
            native = self._run([*diagnostic_args, 'agent', 'doctor', '--json'])
            native_checks = native.get('checks')
            if not isinstance(native_checks, list):
                raise ProjectError('invalid agent doctor response')
            statuses = {}
            for check in native_checks:
                if isinstance(check, dict):
                    statuses[check.get('id')] = check.get('status')
                    checks.append({**check, 'required': check.get('id') in required})
            if any(statuses.get(key) == 'error' for key in required):
                transport = 'error'
            elif all(statuses.get(key) == 'ok' for key in required):
                transport = 'ok'
            # Native diagnostics do not expose the principal. Preserve that
            # limitation instead of running identity show (may access keychain).
            checks.append({'id': 'adapter.authorized_principal', 'status': 'unknown',
                           'required': True, 'detail': 'Native doctor does not expose the caller principal; ordinary operations verify it before access.'})
        except (ProjectError, ValueError, TypeError, AttributeError) as exc:
            checks.append({'id': 'adapter.binding', 'status': 'error' if transport == 'error' else 'unknown', 'required': True,
                           'detail': str(exc)})
        checks.append({'id': 'adapter.document_transport', 'status': transport, 'required': True})
        selection = {'id': 'adapter.session', 'status': 'unknown', 'required': False,
                     'detail': 'No local session selection requested.'}
        if session:
            try:
                manifest = self.resolve(session=session, remote=False)
                selection.update(status='ok', detail='Local binding and cached manifest agree.', workflow_id=manifest['id'])
            except (ProjectError, OSError, ValueError, TypeError) as exc:
                selection.update(detail=str(exc))
        checks.append(selection)
        required_statuses = [c['status'] for c in checks if c['required']]
        status = 'error' if 'error' in required_statuses else ('ok' if all(s == 'ok' for s in required_statuses) else 'unknown')
        return {'schema_version': 1, 'status': status,
                'document_transport': transport, 'checks': checks}

    def _read_node(self, path):
        try:
            node = self.transport(['read-node', '--path', path, '--json'])
        except ProjectError as exc:
            if str(exc).strip() in (f'node not found: {path}', f'error: node not found: {path}', f'Error: node not found: {path}'):
                return None
            raise
        if not isinstance(node, dict) or node.get('path') != path or not isinstance(node.get('etag'), str):
            raise ProjectError('invalid read-node acknowledgement')
        return node

    def _id(self, value):
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProjectError('workflow id must be a canonical UUID') from exc
        return value

    def _migrate_legacy(self):
        wid = self.config['legacy_workflow_id']
        journal = self._state(self.directory / 'journals' / (wid + '.json'))
        if not journal.exists():
            existing = self._read_node(self._manifest_path(wid))
            if existing:
                record = json.loads(existing['content'])
                self._validate_manifest(record, workflow_id=wid, ready_required=False)
                if record.get('legacy') is not True:
                    raise ProjectError('migration manifest is not a legacy workflow')
                self._verify_owner(existing, record, 'manifest')
            else:
                record = dict(version=1, id=wid, title='Imported workflow',
                              nonce=str(uuid.uuid4()), state='initializing', legacy=True,
                              artifacts=self.config['legacy_artifacts'],
                              project_fingerprint=fingerprint(self.config))
            self._save_state(journal, record)
        return self.new(resume=wid)

    def _manifest_path(self, wid):
        return f"{self.config['scope']}/workflows/{self._id(wid)}/manifest.json"

    def _owner(self, record, role):
        return {'kinic_superpowers': {'workflow_id': record['id'], 'nonce': record['nonce'], 'role': role}}

    def _verify_owner(self, node, record, role):
        try:
            owner = json.loads(node.get('metadata_json', '{}'))
        except ValueError:
            owner = {}
        if node.get('kind') != 'file' or owner != self._owner(record, role):
            raise ProjectError(f"foreign node collision at {node.get('path')}")

    def _write(self, path, content, record, role, etag=None):
        with tempfile.TemporaryDirectory(prefix='kinic-create-') as tmp:
            source = Path(tmp) / 'content'
            source.write_text(content)
            args = ['write-node', '--path', path, '--kind', 'file', '--input', str(source), '--metadata-json', json.dumps(self._owner(record, role)), '--json']
            if etag:
                args += ['--expected-etag', etag]
            try:
                self.transport(args)
            except ProjectError:
                # A timed out write may have landed. Confirm ownership/content.
                node = self._read_node(path)
                if node is None:
                    raise
                self._verify_owner(node, record, role)
                if node.get('content') != content:
                    raise
        node = self._read_node(path)
        if node is None:
            raise ProjectError('write acknowledgement missing; resume initialization')
        self._verify_owner(node, record, role)
        if node.get('content') != content:
            raise ProjectError('write content changed; reconcile before resuming')
        return node

    @contextmanager
    def _lock(self, wid):
        import fcntl
        path = self._state(self.directory / 'locks' / (wid + '.lock'))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProjectError('initialization already running locally') from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def new(self, title=None, resume=None):
        if self.version not in (2, 3):
            raise ProjectError('workflow creation requires version 2 or 3 configuration')
        wid = self._id(resume) if resume else str(uuid.uuid4())
        journal = self._state(self.directory / 'journals' / (wid + '.json'))
        try:
            with self._lock(wid):
                if resume:
                    record = self._read_state(journal)
                    self._validate_manifest(record, workflow_id=wid, ready_required=False)
                else:
                    if not isinstance(title, str) or not title.strip():
                        raise ProjectError('workflow title is required')
                    record = dict(version=2, id=wid, title=title.strip(), nonce=str(uuid.uuid4()), state='initializing', artifacts={}, project_fingerprint=fingerprint(self.config))
                    self._save_state(journal, record)  # Persist recovery identity before any remote writes.
                manifest_path = self._manifest_path(wid)
                existing = self._read_node(manifest_path)
                if existing:
                    self._verify_owner(existing, record, 'manifest')
                    manifest = json.loads(existing['content'])
                    if manifest.get('state') == 'ready':
                        self._validate_manifest(manifest, workflow_id=wid)
                        if manifest['nonce'] != record['nonce']:
                            raise ProjectError('manifest ownership nonce differs from journal')
                        self._save_state(self.directory / 'manifests' / (wid + '.json'), manifest)
                        return manifest
                else:
                    parts = PurePosixPath(manifest_path).parent.parts
                    for n in range(2, len(parts) + 1):
                        path = str(PurePosixPath(*parts[:n]))
                        node = self._read_node(path)
                        if node is None:
                            self.transport(['mkdir-node', '--path', path, '--json'])
                        elif node.get('kind') not in ('folder', 'dir', 'directory'):
                            raise ProjectError(f'foreign non-directory at {path}')
                    existing = self._write(manifest_path, json.dumps(record, indent=2), record, 'manifest')
                for role, artifact in record['artifacts'].items():
                    node = self._read_node(artifact['path'])
                    if node:
                        if not record.get('legacy'):
                            self._verify_owner(node, record, role)
                        elif node.get('kind') != 'file':
                            raise ProjectError('legacy artifact is not a file')
                    else:
                        if record.get('legacy'):
                            raise ProjectError('legacy artifact missing; restore it before resuming migration')
                        content = f'# {record["title"]}: {role}\n\n'
                        content += ('## Current state\n\nDesign\n\n## History\n\n- Workflow initialized.\n' if role == 'progress' else '')
                        self._write(artifact['path'], content, record, role)
                record['state'] = 'ready'
                self._write(manifest_path, json.dumps(record, indent=2), record, 'manifest', existing['etag'])
                self._save_state(journal, record)
                self._save_state(self.directory / 'manifests' / (wid + '.json'), record)
                return record
        except ProjectError as exc:
            if journal.exists():
                raise ProjectError(f'{exc}; initialization may be resumed with workflow new --resume {wid}') from exc
            raise

    def _validate_manifest(self, manifest, workflow_id=None, ready_required=True):
        if not isinstance(manifest, dict) or manifest.get('version') not in (1, 2):
            raise ProjectError('invalid workflow record version')
        self._id(manifest.get('id'))
        if workflow_id is not None and manifest['id'] != workflow_id:
            raise ProjectError('manifest workflow id mismatch')
        self._id(manifest.get('nonce'))
        if not isinstance(manifest.get('title'), str) or not manifest['title'].strip():
            raise ProjectError('invalid workflow title')
        if 'current_state' in manifest and (not isinstance(manifest['current_state'], str) or not manifest['current_state'].strip()):
            raise ProjectError('invalid current state summary')
        if manifest.get('state') not in ('initializing', 'ready'):
            raise ProjectError('invalid workflow state')
        if manifest.get('project_fingerprint') != fingerprint(self.config):
            raise ProjectError('manifest belongs to a different connection')
        if ready_required and manifest.get('state') != 'ready':
            raise ProjectError('workflow initialization incomplete; resume it before use')
        expected = self._manifest_path(manifest['id']).rsplit('/', 1)[0]
        if manifest.get('legacy'):
            if manifest['id'] != self.config.get('legacy_workflow_id') or manifest.get('artifacts') != self.config.get('legacy_artifacts'):
                raise ProjectError('legacy artifact map differs from preserved configuration')
            roles = manifest['artifacts']
        elif manifest['version'] == 2:
            if not isinstance(manifest.get('artifacts'), dict):
                raise ProjectError('invalid artifact map')
            for role, item in manifest['artifacts'].items():
                if not isinstance(item, dict) or item != self._document_mapping(role, item.get('local'), manifest):
                    raise ProjectError('invalid document mapping')
            return manifest
        else:
            roles = ('spec', 'plan', 'progress', 'review', 'completion')
            if not isinstance(manifest.get('artifacts'), dict) or set(manifest['artifacts']) != set(roles):
                raise ProjectError('workflow needs exactly five artifact roles')
        for role in roles:
            item = manifest.get('artifacts', {}).get(role, {})
            if not isinstance(item, dict):
                raise ProjectError('invalid workflow artifact')
            if not manifest.get('legacy') and item.get('path') != f'{expected}/{role}.md':
                raise ProjectError('invalid manifest artifact path')
            local = item.get('local', '')
            expected_local = f'.superpowers/workflows/{manifest["id"]}/{manifest["id"] if role == "plan" else role}.md'
            if role == 'progress':
                expected_local = f'.superpowers/sdd/{manifest["id"]}/progress.md'
            if not manifest.get('legacy') and local != expected_local:
                raise ProjectError('invalid manifest local artifact mapping')
            target = (self.root / local).resolve()
            if not local or Path(local).is_absolute() or target == self.root or not target.is_relative_to(self.root) or (not manifest.get('legacy') and not target.is_relative_to(self.root / '.superpowers')):
                raise ProjectError('invalid manifest local path')
        return manifest

    def _document_mapping(self, role, local, record):
        if not isinstance(local, str) or str(PurePosixPath(local)) != local or '..' in PurePosixPath(local).parts or Path(local).is_absolute():
            raise ProjectError('document file must be a canonical relative path')
        self._state(self.root / local)
        if role in ('spec', 'plan'):
            folder = 'specs' if role == 'spec' else 'plans'
            suffix = '-design' if role == 'spec' else ''
            if not re.fullmatch(r'docs/superpowers/' + folder + r'/\d{4}-\d{2}-\d{2}-[^/]+' + suffix + r'\.md', local):
                raise ProjectError('document must use the upstream dated spec/plan path')
            remote = folder + '/' + Path(local).name
        elif role in ('progress', 'review', 'completion'):
            plan = record['artifacts'].get('plan')
            if not plan:
                raise ProjectError('register the plan before execution documents')
            if not re.fullmatch(r'\.superpowers/sdd/[^/]+/' + role + r'\.md', local):
                raise ProjectError('execution document must use its upstream workspace')
            remote = 'execution/' + Path(plan['local']).stem + '/' + role + '.md'
        else:
            raise ProjectError('unknown document role')
        return {'local': local, 'path': self.config['scope'] + '/' + remote}

    def _parents(self, path):
        parts = PurePosixPath(path).parent.parts
        for n in range(2, len(parts) + 1):
            parent = str(PurePosixPath(*parts[:n]))
            node = self._read_node(parent)
            if node is None:
                self.transport(['mkdir-node', '--path', parent, '--json'])
            elif node.get('kind') not in ('folder', 'dir', 'directory'):
                raise ProjectError('foreign non-directory at ' + parent)

    def document(self, role, file, session=None, workflow_id=None):
        record = self.resolve(session=session, workflow_id=workflow_id)
        if record['version'] != 2:
            raise ProjectError('legacy workflows retain their existing artifact map')
        with self._lock(record['id']):
            manifest_node = self._read_node(self._manifest_path(record['id']))
            self._verify_owner(manifest_node, record, 'manifest')
            current = json.loads(manifest_node['content'])
            self._validate_manifest(current, workflow_id=record['id'])
            if current['nonce'] != record['nonce']:
                raise ProjectError('manifest ownership changed during publication')
            record = current
            item = self._document_mapping(role, file, record)
            content = self._state(self.root / file).read_text(encoding='utf-8')
            if not any(line.strip() and not line.lstrip().startswith('#') for line in content.splitlines()):
                raise ProjectError('document needs authored content beyond headings')
            if role == 'progress':
                plan = record['artifacts']['plan']['local']
                if content.splitlines()[0] != '# SDD ledger — plan: ' + plan:
                    raise ProjectError('ledger first line must identify the registered repository-relative plan path; invoke the helper with a repository-relative plan')
            if role in ('progress', 'review', 'completion'):
                plan = record['artifacts']['plan']['local']
                try:
                    expected = execution_workspace(self.root, plan)
                except ValueError as exc:
                    raise ProjectError(str(exc)) from exc
                if (self.root / file).parent != expected:
                    raise ProjectError('use the execution workspace resolved by sdd-workspace for the registered plan')
            previous = record['artifacts'].get(role)
            if previous and previous != item and (role not in ('progress', 'review', 'completion') or previous['path'] != item['path']):
                raise ProjectError('document already registered at another path')
            node = self._read_node(item['path'])
            if node:
                self._verify_owner(node, record, role)
                if node['content'] != content:
                    raise ProjectError('document already exists with different content; use pull/check/push')
            else:
                if previous:
                    raise ProjectError('registered document missing; restore before continuing')
                self._parents(item['path'])
                node = self._write(item['path'], content, record, role)
            # Keep shared registration stable; checkout-specific helper paths
            # are resolved locally when creating the Workspace configuration.
            record['artifacts'][role] = previous or item
            self._write(manifest_node['path'], json.dumps(record, indent=2), record, 'manifest', manifest_node['etag'])
            self.cache_manifest(record)
            # Initial publication establishes the same snapshot as pull without
            # replacing the author's local document.
            cache_key = _hash(json.dumps([self.config['database_id'], item['path'], item['local']]))
            self._save_state(self.root / '.superpowers/kinic' / (cache_key + '.json'),
                             {'etag': node['etag'], 'sha256': _hash(content), 'metadata_json': node['metadata_json']})
            exclude_document_copy(self.root, file)
            return record

    def state(self, summary, session=None, workflow_id=None):
        if not isinstance(summary, str) or not summary.strip():
            raise ProjectError('current state summary must be nonempty')
        record = self.resolve(session=session, workflow_id=workflow_id)
        with self._lock(record['id']):
            node = self._read_node(self._manifest_path(record['id']))
            self._verify_owner(node, record, 'manifest')
            current = json.loads(node['content'])
            self._validate_manifest(current, workflow_id=record['id'])
            if current['nonce'] != record['nonce']:
                raise ProjectError('manifest ownership changed during state update')
            current['current_state'] = summary.strip()
            self._write(node['path'], json.dumps(current, indent=2), current, 'manifest', node['etag'])
            self.cache_manifest(current)
            return current

    def index(self):
        records = self.list()
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint(self.config)))
        owner = {'id': identity, 'nonce': identity}
        path = self.config['scope'] + '/index.md'
        node = self._read_node(path)
        if node:
            self._verify_owner(node, owner, 'index')
        name = self.config.get('project_name') or self.config['scope'].rsplit('/', 1)[-1]
        lines = ['# ' + name, '', '## Work', '']
        for record in records:
            self._validate_manifest(record, ready_required=False)
            title = record['title'].replace('\n', ' ')
            lines += ['### ' + title, '', 'Registration: ' + record['state'], '']
            lines += ['Current state: ' + record.get('current_state', 'Not recorded.'), '']
            for role, item in record['artifacts'].items():
                lines += ['- [' + role + '](' + item['path'] + ')']
            if not record['artifacts']:
                lines += ['No documents published yet.']
            lines += ['']
        self._parents(path)
        return self._write(path, '\n'.join(lines), owner, 'index', node['etag'] if node else None)

    def list(self):
        base = self.config['scope'] + '/workflows'
        if self._read_node(base) is None:
            return []
        entries = self.transport(['list-children', '--path', base, '--json'])
        if not isinstance(entries, list):
            raise ProjectError('invalid list-children response')
        result = []
        for entry in entries:
            if entry.get('kind') not in ('folder', 'dir', 'directory'):
                continue
            wid = entry.get('path', '').rsplit('/', 1)[-1]
            try:
                self._id(wid)
            except ProjectError:
                continue
            node = self._read_node(self._manifest_path(wid))
            if node:
                record = json.loads(node['content'])
                self._verify_owner(node, record, 'manifest')
                if record.get('project_fingerprint') != fingerprint(self.config):
                    raise ProjectError('manifest connection mismatch')
                result.append(record)
        return sorted(result, key=lambda item: (item.get('title', ''), item['id']))

    def _binding_path(self, session):
        if not isinstance(session, str) or not session:
            raise ProjectError('session id is required')
        return self._state(self.root / '.superpowers/kinic/sessions' / (_hash(session) + '.json'))

    def use(self, workflow_id, session):
        manifest = self.resolve(workflow_id=workflow_id)
        self.cache_manifest(manifest)
        binding = dict(session_id=session, workflow_id=manifest['id'], project_fingerprint=fingerprint(self.config))
        self._save_state(self._binding_path(session), binding)
        return binding

    def cache_manifest(self, manifest):
        self._validate_manifest(manifest)
        self._save_state(self.directory / 'manifests' / (manifest['id'] + '.json'), manifest)

    def resolve(self, session=None, workflow_id=None, remote=True):
        bound = None
        if session:
            path = self._binding_path(session)
            if path.exists():
                binding = self._read_state(path)
                if binding.get('session_id') != session or binding.get('project_fingerprint') != fingerprint(self.config):
                    raise ProjectError('session binding belongs to another connection')
                bound = binding.get('workflow_id')
        if workflow_id and bound and workflow_id != bound:
            raise ProjectError('workflow differs from session binding; explicitly use it first')
        wid = workflow_id or bound
        if not wid:
            raise ProjectError('no workflow selected; list workflows and use one for this session')
        self._id(wid)
        cache = self._state(self.directory / 'manifests' / (wid + '.json'))
        if remote:
            node = self._read_node(self._manifest_path(wid))
            if node is None:
                raise ProjectError('workflow manifest missing')
            manifest = json.loads(node['content'])
            self._verify_owner(node, manifest, 'manifest')
            self._validate_manifest(manifest)
            if manifest['id'] != wid:
                raise ProjectError('manifest workflow id mismatch')
        else:
            manifest = self._validate_manifest(self._read_state(cache), workflow_id=wid)
        return manifest

    def workspace_data(self, manifest):
        self._validate_manifest(manifest)
        artifacts = {role: dict(item) for role, item in manifest['artifacts'].items()}
        if manifest['version'] == 2:
            for role in ('progress', 'review', 'completion'):
                if role in artifacts:
                    try:
                        directory = execution_workspace(self.root, artifacts['plan']['local'])
                    except ValueError as exc:
                        raise ProjectError(str(exc)) from exc
                    artifacts[role]['local'] = str((directory / (role + '.md')).relative_to(self.root))
        return {'version': 1, 'database_id': self.config['database_id'], 'artifacts': artifacts, 'lazy_documents': manifest['version'] == 2}
