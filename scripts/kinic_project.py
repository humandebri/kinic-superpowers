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
import tempfile
import uuid
from contextlib import contextmanager


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
    paths = ['.superpowers/', '.kinic-superpowers.json', '.kinic-superpowers.json.v1-backup']
    if target.is_relative_to(root):
        paths += ['/' + str(target.relative_to(root)), '/' + str(target.relative_to(root)) + '.v1-backup']
    additions = [line for line in dict.fromkeys(paths) if line not in contents.splitlines()]
    if additions:
        ignore.write_text(contents + ('\n' if contents and not contents.endswith('\n') else '') + '\n'.join(additions) + '\n')


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
                if shared.exists():
                    return root, shared
    return root, local


def _invoke(cli, cwd, args):
    try:
        result = subprocess.run([cli, *args], cwd=cwd, capture_output=True,
                                text=True, encoding='utf-8', timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectError(f'kinic-vfs-cli could not finish: {exc}') from exc
    if result.returncode:
        raise ProjectError(result.stderr.strip())
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise ProjectError('kinic-vfs-cli returned invalid JSON') from exc


def _path(value):
    if not isinstance(value, str) or not value.startswith('/') or value == '/' or str(PurePosixPath(value)) != value or '..' in PurePosixPath(value).parts:
        raise ProjectError('scope must be a canonical absolute wiki path below /Knowledge')
    if not value.startswith('/Knowledge/'):
        raise ProjectError('scope must be below /Knowledge')
    return value


def _validate_connection(config):
    if not isinstance(config, dict) or config.get('version') != 2:
        raise ProjectError('expected version 2 connection configuration')
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
    slug = re.sub(r'[^a-z0-9._-]+', '-', root.name.lower()).strip('.-_')[:64] or 'project'
    return f'/Knowledge/projects/{slug}-{_hash(str(root.resolve()))[:10]}'


def _database_name(databases, database_id):
    if not isinstance(databases, list):
        raise ProjectError('invalid database list response')
    for item in databases:
        if isinstance(item, dict) and item.get('database_id') == database_id:
            return item.get('name') or (item.get('metadata') or {}).get('name')
    return None


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
        if not legacy:
            project = Project(root, target, run=run)
            project._validate_identity()
            if inspect:
                name = _database_name(project.transport(['database', 'list', '--json']), database_id)
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
    invoke = run if run is not None else lambda args: _invoke(executable, root, args)
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
    candidates = []
    if database_id is None:
        database_id = connection.get('database_id')
        if database_id is None:
            databases = invoke([*args, 'database', 'list', '--json'])
            if not isinstance(databases, list):
                raise ProjectError('invalid database list response')
            for item in databases:
                if (isinstance(item, dict) and item.get('status') == 'active'
                        and item.get('role') in ('owner', 'writer')
                        and item.get('cycles_suspended_at_ms') is None
                        and item.get('deleted_at_ms') is None
                        and isinstance(item.get('database_id'), str) and item['database_id']):
                    candidates.append({'database_id': item['database_id'],
                                       'name': item.get('name') or (item.get('metadata') or {}).get('name') or item['database_id'],
                                       'role': item['role']})
            if len(candidates) == 1:
                database_id = candidates[0]['database_id']
    config = dict(version=2, database_id=database_id, scope=scope, cli=executable,
                  canister_id=canister_id or connection.get('canister_id'),
                  replica_host=replica_host or connection.get('replica_host'),
                  identity={'principal': principal, 'allow_non_ii_identity': bool(allow_non_ii_identity)})
    if database_id is None:
        if inspect:
            return {**config, 'selection_required': True, 'database_candidates': candidates}
        choices = ', '.join(f'{item["name"]} ({item["database_id"]})' for item in candidates)
        raise ProjectError('database selection required; run init --inspect and select a database by name: '
                           + (choices or 'no active writable databases found'))
    _validate_connection(config)
    # Pin the inspected endpoint for the authenticated access check.
    verify_args = ['--database-id', database_id, '--identity-mode', 'identity',
                   '--canister-id', config['canister_id'], '--replica-host', config['replica_host']]
    if allow_non_ii_identity:
        verify_args += ['--allow-non-ii-identity']
    invoke([*verify_args, 'status', '--json'])
    if inspect:
        inventory = candidates or invoke([*args, 'database', 'list', '--json'])
        return {**config, 'database_name': _database_name(inventory, database_id),
                'selection_required': False, 'database_candidates': candidates,
                'migration_required': legacy is not None}
    _ensure_ignored(root, target)
    if legacy:
        backup = target.with_name(target.name + '.v1-backup')
        if backup.exists() and _read(backup) != legacy:
            raise ProjectError('existing version 1 backup differs; preserve it before migrating')
        _save(backup, legacy)
        # Keep exact legacy artifact maps; publishing the migration manifest never
        # rewrites pre-existing source documents or their cached etags.
        config['legacy_artifacts'] = legacy.get('artifacts', {})
        config['legacy_workflow_id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint(config) + json.dumps(legacy, sort_keys=True)))
    _save(target, config)
    if legacy:
        Project(root, target, run=run)._migrate_legacy()
    return config


class Project:
    def __init__(self, cwd, config_path=None, cli_override=None, allow_non_ii_identity=False, run=None):
        self.root, self.config_path = discover(cwd, config_path)
        self.config = _read(self.config_path)
        self.version = self.config.get('version')
        if self.version not in (1, 2):
            raise ProjectError('unsupported project config version')
        self.cli = cli_override or self.config.get('cli', 'kinic-vfs-cli')
        self._run = run if run is not None else lambda args: _invoke(self.cli, self.root, args)
        self.directory = self._state(self.root / '.superpowers/kinic-project')
        if self.version == 2:
            _validate_connection(self.config)

    def _state(self, path):
        return _contained(self.root, path)

    def _read_state(self, path):
        return _read(self._state(path))

    def _save_state(self, path, data):
        return _save(self._state(path), data)

    def _args(self):
        args = ['--database-id', self.config['database_id'], '--identity-mode', 'identity']
        for key in ('canister_id', 'replica_host'):
            if self.config.get(key):
                args += ['--' + key.replace('_', '-'), self.config[key]]
        if self.config.get('identity', {}).get('allow_non_ii_identity'):
            args += ['--allow-non-ii-identity']
        return args

    def _validate_identity(self):
        result = self._run([*self._args(), 'identity', 'show', '--json'])
        if result.get('principal') != self.config.get('identity', {}).get('principal'):
            raise ProjectError('selected identity principal changed; refusing access')

    def transport(self, args):
        self._validate_identity()
        # Legacy Workspace supplies its own database prefix; saved connection wins.
        args = list(args)
        if '--database-id' in args:
            index = args.index('--database-id')
            if args[index + 1] != self.config['database_id']:
                raise ProjectError('database mismatch')
            del args[index:index + 2]
        return self._run([*self._args(), *args])

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
        if self.version != 2:
            raise ProjectError('workflow creation requires version 2 configuration')
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
                    prefix = self._manifest_path(wid).rsplit('/', 1)[0]
                    artifacts = {}
                    for role in ('spec', 'plan', 'progress', 'review', 'completion'):
                        local = f'.superpowers/workflows/{wid}/{wid if role == "plan" else role}.md'
                        if role == 'progress':
                            local = f'.superpowers/sdd/{wid}/progress.md'
                        artifacts[role] = {'path': f'{prefix}/{role}.md', 'local': local}
                    record = dict(version=1, id=wid, title=title.strip(), nonce=str(uuid.uuid4()), state='initializing', artifacts=artifacts, project_fingerprint=fingerprint(self.config))
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
        if not isinstance(manifest, dict) or manifest.get('version') != 1:
            raise ProjectError('invalid workflow record version')
        self._id(manifest.get('id'))
        if workflow_id is not None and manifest['id'] != workflow_id:
            raise ProjectError('manifest workflow id mismatch')
        self._id(manifest.get('nonce'))
        if not isinstance(manifest.get('title'), str) or not manifest['title'].strip():
            raise ProjectError('invalid workflow title')
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
        return {'version': 1, 'database_id': self.config['database_id'], 'artifacts': manifest['artifacts']}
