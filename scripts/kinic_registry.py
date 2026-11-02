"""Repository identity and explicit wiki project registration.

Repository URLs are identifiers, never credentials. The remote record owns a
stable UUID; a new checkout reuses it only after checking repository identity.
"""
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import urlsplit
import uuid

from kinic_project import ProjectError, _contained, _read, _save


def _git(root):
    try:
        result = subprocess.run(['git', '-C', str(root), 'remote', 'get-url', 'origin'],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return result.stdout.strip() if result.returncode == 0 else ''


def _slug(name):
    return re.sub(r'[^a-z0-9._-]+', '-', name.lower()).strip('.-_')[:64] or 'project'


def propose(root):
    """Read origin without network I/O; do not create configuration or IDs."""
    root = Path(root)
    remote = _git(root)
    if '://' not in remote and re.match(r'^(?:[^/@:]+@)?[^/:]+:.+', remote):
        remote = 'ssh://' + remote.replace(':', '/', 1)
    try:
        parsed = urlsplit(remote)
        host = parsed.hostname
        path = parsed.path.strip('/').removesuffix('.git')
        if parsed.scheme not in ('https', 'http', 'ssh', 'git') or not host or not path:
            return {'project_name': _slug(root.name), 'repository_key': None}
        # GitHub repository identity is case-insensitive. Other hosts may not be.
        key_path = path.lower() if host.lower() == 'github.com' else path
        port = f':{parsed.port}' if parsed.port and parsed.port not in (22, 80, 443) else ''
        key = host.lower() + port + '/' + key_path
        return {'project_name': _slug(path.rsplit('/', 1)[-1]), 'repository_key': key}
    except ValueError:
        return {'project_name': _slug(root.name), 'repository_key': None}


def create_only(project, path, content, record, role):
    """Absent expected-etag is atomic create-only in VFS update_existing_node."""
    return project._write(path, content, record, role)


def _directories(project, path):
    parts = PurePosixPath(path).parent.parts
    for n in range(2, len(parts) + 1):
        directory = str(PurePosixPath(*parts[:n]))
        node = project._read_node(directory)
        if node is None:
            project.transport(['mkdir-node', '--path', directory, '--json'])
        elif node.get('kind') not in ('folder', 'dir', 'directory'):
            raise ProjectError('project directory collision: ' + directory)


def _record(project, node, repository_key):
    try:
        record = json.loads(node['content'])
        if record.get('version') != 1 or record.get('repository_key') != repository_key:
            raise ValueError()
        project_id = record['id']
        if str(uuid.UUID(project_id)) != project_id or record.get('nonce') != project_id:
            raise ValueError()
        if not isinstance(record.get('name'), str) or not record['name']:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ProjectError('project namespace collision; choose an explicit different project name') from exc
    project._verify_owner(node, record, 'project')
    return record


def register(project, project_name=None):
    """Register current scope, or explicitly rename an empty unregistered scope.

Existing namespaces must be migrated separately. No workflow fingerprints change
on an idempotent registration. Connection config is saved only after verification.
"""
    if project.config.get('version') not in (2, 3):
        raise ProjectError('project registration requires version 2 or 3 connection configuration')
    proposal = propose(project.root)
    name = project_name or project.config.get('project_name') or proposal['project_name']
    if not isinstance(name, str) or name != _slug(name):
        raise ProjectError('project name must be a lowercase URL-safe slug')
    scope = project.config['scope']
    if project_name and project_name != PurePosixPath(scope).name:
        if project.config.get('project_id') or project.config.get('legacy_artifacts'):
            raise ProjectError('registered project scope changes require migration')
        node = project._read_node(scope)
        children = project.transport(['list-children', '--path', scope, '--json']) if node else []
        # Also check workflows for transports which do not return a scope node.
        if children or project._read_node(scope + '/workflows'):
            raise ProjectError('nonempty project scope changes require migration')
        scope = str(PurePosixPath(scope).parent / name)
    repository_key = proposal['repository_key']
    saved_key = project.config.get('repository_key')
    if saved_key:
        if repository_key and repository_key != saved_key:
            raise ProjectError('repository identity changed; explicit migration required')
        repository_key = saved_key
    if not repository_key:
        # Shared config owner gives linked worktrees one local-only identity.
        owner = project.config_path.parent.resolve()
        identity_path = _contained(owner, owner / '.superpowers/kinic-project/registration-identity.json')
        if identity_path.exists():
            local_id = _read(identity_path).get('id')
            try:
                if str(uuid.UUID(local_id)) != local_id:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError) as exc:
                raise ProjectError('invalid local repository identity') from exc
        else:
            local_id = str(uuid.uuid4())
            _save(identity_path, {'id': local_id})
        repository_key = 'local:' + local_id
    path = scope + '/project.json'
    existing = project._read_node(path)
    if existing is None:
        project_id = str(uuid.uuid4())
        candidate = dict(version=1, id=project_id, nonce=project_id, name=name,
                         repository_key=repository_key)
        _directories(project, path)
        try:
            create_only(project, path, json.dumps(candidate, indent=2) + '\n', candidate, 'project')
        except ProjectError:
            # Concurrent registration or lost acknowledgement: adopt only a
            # verified record for this exact repository, never overwrite it.
            existing = project._read_node(path)
            if existing is None:
                raise
        else:
            existing = project._read_node(path)
    record = _record(project, existing, repository_key)
    if project.config.get('project_id') not in (None, record['id']):
        raise ProjectError('registered project id changed; refusing replacement')
    config = {**project.config, 'scope': scope, 'project_id': record['id'],
              'project_name': record['name'], 'repository_key': repository_key}
    _save(project.config_path, config)
    project.config = config
    return config
