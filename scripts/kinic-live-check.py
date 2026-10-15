#!/usr/bin/env python3
"""Opt-in live adapter check; creates five synthetic wiki pages and retains them.

This tests document transport, not agent workflow execution or human approvals.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import uuid


MODULE = Path(__file__).with_name('kinic-workflow.py')
spec = importlib.util.spec_from_file_location('kinic_workflow', MODULE)
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


def is_etag_conflict(message):
    # A decode error can list every error code; match the actual selected code.
    return ('expected_etag does not match current etag' in message or
            'unknown variant `EtagConflict`' in message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-id', required=True)
    parser.add_argument('--cli', required=True)
    parser.add_argument('--allow-non-ii-identity', action='store_true')
    parser.add_argument('--create-test-pages', action='store_true', required=True)
    args = parser.parse_args()
    root = MODULE.resolve().parents[1]
    run_id = uuid.uuid4().hex
    prefix = f'/Knowledge/kinic-superpowers/live-check-{run_id}'
    local = root / '.superpowers' / 'live-check' / run_id
    local.mkdir(parents=True)
    cli = workflow.CLI(str(Path(args.cli).resolve()), cwd=root,
                       allow_non_ii_identity=args.allow_non_ii_identity)
    report = {'database_id': args.database_id, 'prefix': prefix,
              'run_id': run_id, 'checks': [], 'status': 'running'}
    report_file = local / 'report.json'

    def save():
        workflow.atomic_write(report_file, json.dumps(report, indent=2))

    def check(name, **details):
        report['checks'].append({'check': name, 'passed': True, **details})
        save()
        print(json.dumps(report['checks'][-1]), flush=True)

    connection = ['--database-id', args.database_id]
    artifacts = {role: {'path': f'{prefix}/{role}.md', 'local': f'{role}.md'}
                 for role in ('spec', 'plan', 'progress', 'review', 'completion')}
    config_data = {'version': 1, 'database_id': args.database_id, 'artifacts': artifacts}
    configs = []
    for name in ('controller', 'other-session'):
        config = local / name / '.kinic-superpowers.json'
        workflow.atomic_write(config, json.dumps(config_data, indent=2))
        configs.append(config)
    save()
    try:
        inventory = cli([*connection, 'list-nodes', '--prefix', prefix,
                         '--recursive', '--json'])
        if inventory != []:
            raise workflow.WorkflowError('fresh test prefix unexpectedly occupied')
        cli([*connection, 'mkdir-node', '--path', prefix, '--json'])
        # Explicit bootstrap of unique test-only nodes; production adapter never
        # treats an arbitrary failed read as permission to create a page.
        for role, item in artifacts.items():
            text = f'# Kinic Superpowers live test: {role}\n\nSynthetic adapter test only.\nRun: {run_id}\n'
            seed = local / f'seed-{role}.md'
            seed.write_text(text, encoding='utf-8')
            created = cli([*connection, 'write-node', '--path', item['path'],
                           '--kind', 'file', '--input', str(seed), '--json'])
            if created.get('created') is not True:
                raise workflow.WorkflowError('bootstrap did not create a new test page')
            check(f'create:{role}', path=item['path'], etag=created['node']['etag'])

        work = workflow.Workspace(configs[0], cli)
        for role, item in artifacts.items():
            before = work.pull(role)
            target = configs[0].parent / item['local']
            target.write_text(target.read_text(encoding='utf-8') + '\nRound trip verified.\n', encoding='utf-8')
            after = work.push(role)
            if after['etag'] == before['etag']:
                raise workflow.WorkflowError('content change did not change etag')
            restarted = workflow.Workspace(configs[1], cli)
            verified = restarted.pull(role)
            if (configs[1].parent / item['local']).read_text() != target.read_text():
                raise workflow.WorkflowError('fresh-session content differs')
            if verified['etag'] != after['etag']:
                raise workflow.WorkflowError('fresh-session etag differs')
            check(f'round-trip-and-resume:{role}', etag=after['etag'])

        other = workflow.Workspace(configs[1], cli)
        other.pull('progress')
        stale_etag = other.status('progress')['etag']
        first = configs[0].parent / 'progress.md'
        first.write_text(first.read_text() + '\nController update wins.\n')
        winning = work.push('progress')
        second = configs[1].parent / 'progress.md'
        second.write_text(second.read_text() + '\nStale update must be rejected.\n')
        try:
            other.push('progress')
        except workflow.WorkflowError as exc:
            if not is_etag_conflict(str(exc)):
                raise
            if other.status('progress')['etag'] != stale_etag:
                raise workflow.WorkflowError('rejected write advanced local baseline')
            check('stale-write-rejected', error=str(exc))
        else:
            raise workflow.WorkflowError('stale write unexpectedly succeeded')

        # Reread after the intentional failed mutation; never retry the stale write.
        remote = cli([*connection, 'read-node', '--path', artifacts['progress']['path'], '--json'])
        if remote['etag'] != winning['etag'] or remote['content'] != first.read_text():
            raise workflow.WorkflowError('rejected write changed remote state')
        check('winning-content-preserved', etag=remote['etag'])
        try:
            other.pull('progress')
        except workflow.WorkflowError as exc:
            if 'unpublished local changes' not in str(exc):
                raise
            check('dirty-copy-preserved')
        else:
            raise workflow.WorkflowError('dirty copy unexpectedly overwritten')
        report['status'] = 'passed'
        save()
        print(json.dumps({'report': str(report_file), 'status': 'passed', 'prefix': prefix}), flush=True)
        return 0
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = str(exc)
        save()
        print(f'Live check failed; inspect {report_file}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
