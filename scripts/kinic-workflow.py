#!/usr/bin/env python3
"""Version-bound working copies of existing Kinic Wiki workflow documents.

Uses kinic-vfs-cli for authentication and transport. Initialize a saved connection,
create workflows, and bind them to chats before working with wiki documents.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile


class WorkflowError(Exception):
    pass


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(content)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


class CLI:
    def __init__(self, executable='kinic-vfs-cli', cwd=None, allow_non_ii_identity=False):
        self.executable = executable
        self.cwd = cwd
        self.connection_args = ['--allow-non-ii-identity'] if allow_non_ii_identity else []

    def __call__(self, args):
        try:
            result = subprocess.run([self.executable, *self.connection_args, *args], cwd=self.cwd,
                                    capture_output=True, text=True, encoding='utf-8',
                                    timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkflowError(f'kinic-vfs-cli could not finish: {exc}') from exc
        if result.returncode:
            raise WorkflowError(f'kinic-vfs-cli failed: {result.stderr.strip()}')
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WorkflowError('kinic-vfs-cli returned invalid JSON') from exc


class Workspace:
    def __init__(self, config, run=None, data=None, root=None):
        self.config = Path(config).resolve()
        self.root = Path(root).resolve() if root is not None else self.config.parent
        self.data = data if data is not None else json.loads(self.config.read_text(encoding='utf-8'))
        if self.data.get('version') != 1:
            raise WorkflowError('config version must be 1')
        self.database = self.data.get('database_id')
        if not isinstance(self.database, str) or not self.database.strip():
            raise WorkflowError('database_id is required')
        self.artifacts = self.data.get('artifacts')
        if not isinstance(self.artifacts, dict) or not self.artifacts:
            raise WorkflowError('artifacts must be a nonempty object')
        remote_paths, local_paths = set(), set()
        for role, item in self.artifacts.items():
            if not isinstance(item, dict):
                raise WorkflowError(f'invalid artifact: {role}')
            remote = item.get('path', '')
            local = item.get('local', '')
            if (not isinstance(remote, str) or not remote.startswith('/') or
                    '..' in PurePosixPath(remote).parts or
                    str(PurePosixPath(remote)) != remote or remote == '/'):
                raise WorkflowError(f'invalid wiki path for {role}')
            if not isinstance(local, str) or not local or Path(local).is_absolute():
                raise WorkflowError(f'local path must be relative: {role}')
            target = self.local_path(local)
            if remote in remote_paths or target in local_paths:
                raise WorkflowError('each artifact needs a distinct wiki and local path')
            remote_paths.add(remote)
            local_paths.add(target)
        self.run = run if run is not None else CLI(cwd=self.root)

    def local_path(self, relative):
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise WorkflowError('local path escapes project')
        # Do not allow configuration to overwrite Git state, configuration, or
        # the bridge snapshots themselves, including through a symlink.
        parts = target.relative_to(self.root).parts
        if ('.git' in parts or target == self.config or
                parts[:2] == ('.superpowers', 'kinic')):
            raise WorkflowError('artifact targets a reserved path')
        return target

    def artifact(self, role):
        if role not in self.artifacts:
            raise WorkflowError(f'unknown artifact: {role}')
        item = self.artifacts[role]
        local = self.local_path(item['local'])
        key = digest(json.dumps([self.database, item['path'], item['local']]))
        cache = (self.root / '.superpowers' / 'kinic').resolve()
        if not cache.is_relative_to(self.root):
            raise WorkflowError('snapshot directory escapes project')
        return item, local, cache / (key + '.json')

    def snapshot(self, path):
        if not path.exists():
            raise WorkflowError('no baseline; pull this artifact before pushing')
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value.get('etag'), str) or not value['etag']:
            raise WorkflowError('snapshot has no etag')
        return value

    def pull(self, role):
        item, local, cache = self.artifact(role)
        if local.exists():
            baseline = self.snapshot(cache)
            if digest(local.read_text(encoding='utf-8')) != baseline['sha256']:
                raise WorkflowError('unpublished local changes; preserve and reconcile before pulling')
        node = self.read_node(item)
        atomic_write(local, node['content'])
        atomic_write(cache, json.dumps({
            'etag': node['etag'], 'sha256': digest(node['content']),
            'metadata_json': node['metadata_json'],
        }))
        return {**self.status(role), 'remote_checked': True}

    def push(self, role):
        item, local, cache = self.artifact(role)
        baseline = self.snapshot(cache)
        content = local.read_text(encoding='utf-8')
        if digest(content) == baseline['sha256']:
            node = self.run(['--database-id', self.database, 'read-node',
                             '--path', item['path'], '--json'])
            if (not isinstance(node, dict) or node.get('path') != item['path'] or
                    node.get('etag') != baseline['etag']):
                raise WorkflowError('remote revision changed; pull and reconcile before handoff')
            return {**self.status(role), 'remote_checked': True}
        # Freeze the exact content sent, so a concurrent local edit cannot be
        # mistaken for the content acknowledged by the server.
        with tempfile.TemporaryDirectory(prefix='kinic-push-') as directory:
            upload = Path(directory) / 'content.md'
            upload.write_text(content, encoding='utf-8')
            result = self.run([
                '--database-id', self.database, 'write-node',
                '--path', item['path'], '--kind', 'file', '--input', str(upload),
                '--metadata-json', baseline['metadata_json'],
                '--expected-etag', baseline['etag'], '--json',
            ])
        ack = result.get('node', {}) if isinstance(result, dict) else {}
        if (ack.get('path') != item['path'] or
                not isinstance(ack.get('etag'), str) or not ack['etag']):
            raise WorkflowError('write acknowledgement invalid; reconcile remote before retrying')
        atomic_write(cache, json.dumps({
            **baseline, 'etag': ack['etag'], 'sha256': digest(content),
        }))
        return {**self.status(role), 'remote_checked': True}

    def read_node(self, item):
        node = self.run(['--database-id', self.database, 'read-node',
                         '--path', item['path'], '--json'])
        if (not isinstance(node, dict) or node.get('path') != item['path'] or
                node.get('kind') != 'file' or
                not isinstance(node.get('content'), str) or
                not isinstance(node.get('etag'), str) or not node['etag'] or
                not isinstance(node.get('metadata_json'), str)):
            raise WorkflowError('expected a file node with matching path, content, etag and metadata_json')
        return node

    def check(self, role):
        item, _, _ = self.artifact(role)
        result = self.status(role)
        node = self.read_node(item)
        if result['etag'] is None:
            state = 'untracked'
        elif result['dirty'] is None:
            state = 'missing_local'
        elif node['etag'] != result['etag']:
            state = 'conflict' if result['dirty'] else 'remote_changed'
        else:
            state = 'local_changed' if result['dirty'] else 'clean'
        return {**result, 'state': state, 'remote_etag': node['etag'],
                'remote_checked': True}

    def status(self, role):
        item, local, cache = self.artifact(role)
        baseline = self.snapshot(cache) if cache.exists() else None
        return {
            'role': role, 'database_id': self.database, 'path': item['path'],
            'local': str(local), 'etag': baseline['etag'] if baseline else None,
            'dirty': (digest(local.read_text(encoding='utf-8')) != baseline['sha256']
                      if baseline and local.exists() else None),
            'remote_checked': False,
        }


def connection_flags(parser, inherited=False):
    default = argparse.SUPPRESS if inherited else None
    for name in ('config', 'cli', 'canister-id', 'replica-host', 'session', 'workflow', 'project-root'):
        parser.add_argument('--' + name, default=default)
    parser.add_argument('--allow-non-ii-identity', action='store_true',
                        default=argparse.SUPPRESS if inherited else False,
                        help='Explicitly authorize the selected local icp-cli identity')


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    connection_flags(parser)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Verify and save a repository connection')
    connection_flags(init, inherited=True)
    init.add_argument('--database-id', required=True)
    init.add_argument('--scope', required=True)
    init.add_argument('--migrate', action='store_true', help='Import an existing v1 workflow')
    workflow = commands.add_parser('workflow', help='Create, list or select wiki workflows')
    connection_flags(workflow, inherited=True)
    actions = workflow.add_subparsers(dest='action', required=True)
    new = actions.add_parser('new', help='Create a workflow, or resume incomplete initialization')
    connection_flags(new, inherited=True)
    new.add_argument('--title')
    new.add_argument('--resume', metavar='WORKFLOW_ID')
    listed = actions.add_parser('list', help='List workflows from the wiki')
    connection_flags(listed, inherited=True)
    use = actions.add_parser('use', help='Explicitly select a workflow for one chat')
    connection_flags(use, inherited=True)
    use.add_argument('workflow_id')
    for name in ('pull', 'push', 'status', 'check'):
        command = commands.add_parser(name)
        connection_flags(command, inherited=True)
        command.add_argument('role', nargs='?')
    return parser


def main():
    parser = argument_parser()
    args = parser.parse_args()
    if args.command == 'workflow' and args.action == 'use' and not args.session:
        parser.error('workflow use requires --session SESSION')
    # Script execution and importlib-based callers both resolve the companion
    # runtime relative to this installation, rather than the user's project.
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from kinic_project import Project, ProjectError, initialize
    try:
        if args.command == 'init':
            options = dict(cwd=Path(args.project_root or Path.cwd()),
                           config_path=args.config, database_id=args.database_id, scope=args.scope,
                           cli_path=args.cli or 'kinic-vfs-cli',
                           allow_non_ii_identity=args.allow_non_ii_identity,
                           canister_id=args.canister_id, replica_host=args.replica_host)
            if args.migrate:
                options['migrate'] = True
            print(json.dumps(initialize(**options), ensure_ascii=False))
            return 0
        project = Project(cwd=Path(args.project_root or Path.cwd()), config_path=args.config,
                          cli_override=args.cli,
                          allow_non_ii_identity=args.allow_non_ii_identity)
        if args.command == 'workflow':
            if args.action == 'new':
                result = project.new(title=args.title, resume=args.resume)
                if args.session:
                    project.use(result['id'], args.session)
            elif args.action == 'list':
                result = project.list()
            else:
                result = project.use(args.workflow_id, args.session)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        workflow_context = {}
        if project.version == 1:
            if args.workflow not in (None, 'legacy'):
                raise WorkflowError('v1 configuration contains only the legacy workflow')
            workspace_root = (project.root if args.project_root or args.config is None
                              else project.config_path.parent)
            transport = CLI(args.cli or 'kinic-vfs-cli', cwd=workspace_root,
                            allow_non_ii_identity=args.allow_non_ii_identity)
            work = Workspace(project.config_path, transport, root=workspace_root)
        else:
            manifest = project.resolve(session=args.session, workflow_id=args.workflow,
                                       remote=args.command != 'status')
            workflow_context = {'workflow_id': manifest['id'],
                                'workflow_title': manifest['title']}
            work = Workspace(project.config_path, project.transport,
                             data=project.workspace_data(manifest), root=project.root)
        if args.command in ('pull', 'push') and args.role is None:
            raise WorkflowError('pull/push require one artifact role')
        roles = [args.role] if args.role is not None else list(work.artifacts)
        # Reject selection mistakes before doing any transport work.
        for role in roles:
            work.artifact(role)
        # Pull and push require a role; check and status can read all roles.
        exit_code = 0
        for role in roles:
            try:
                result = getattr(work, args.command)(role)
            except (WorkflowError, ProjectError, OSError, ValueError, KeyError, TypeError) as exc:
                if args.command != 'check':
                    raise
                result = {'role': role, 'state': 'error',
                          'remote_checked': False, 'error': str(exc)}
            print(json.dumps({**workflow_context, **result}, ensure_ascii=False))
            if args.command == 'check' and result['state'] != 'clean':
                exit_code = 1
    except (WorkflowError, ProjectError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f'kinic-workflow: {exc}', file=sys.stderr)
        return 1
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
