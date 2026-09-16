"""Temporary verified source transfer. Exports blobs only; never writes any Git ref."""
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path.cwd().resolve()
TRANSFER = ROOT / '.semantic-transfer'
MANIFEST = json.loads((TRANSFER / 'manifest.json').read_text())
REPOSITORY = 'cfxcode/commerce-agents'


def git(*args, **kwargs):
    return subprocess.check_output(['git', *args], cwd=ROOT, **kwargs)


def verify_files():
    expected = MANIFEST['files']
    if len(expected) != 39:
        raise ValueError('Unexpected file set')
    for name, sha in expected.items():
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink():
            raise ValueError('Invalid source path')
        if any(part in {'runtime', '.git', 'node_modules', 'releases'} or part.startswith('.env') for part in path.relative_to(ROOT).parts):
            raise ValueError('Forbidden source path')
        data = path.read_bytes()
        data.decode('utf-8')
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != sha:
            raise ValueError('Source hash mismatch: ' + name)
    return expected


if sys.argv[1] == 'apply':
    git('merge-base', '--is-ancestor', MANIFEST['base_commit'], 'HEAD')
    if git('status', '--porcelain', '-uno').strip():
        raise ValueError('Expected clean checkout')
    chunks = ''.join((TRANSFER / f'part{i}.txt').read_text().strip() for i in range(1, MANIFEST['chunk_count'] + 1))
    archive = base64.b64decode(chunks, validate=True)
    if hashlib.sha256(archive).hexdigest() != MANIFEST['archive_sha256']:
        for i in range(1, 7):
            value = (TRANSFER / f'part{i}.txt').read_bytes()
            print(f'chunk {i} length={len(value)} sha256={hashlib.sha256(value).hexdigest()}')
        raise ValueError('Archive checksum mismatch')
    patch = lzma.decompress(archive, memlimit=128 * 1024 * 1024)
    if len(patch) > 2_000_000 or hashlib.sha256(patch).hexdigest() != MANIFEST['patch_sha256']:
        raise ValueError('Patch checksum mismatch')
    subprocess.run(['git', 'apply', '--check', '-'], input=patch, cwd=ROOT, check=True)
    subprocess.run(['git', 'apply', '-'], input=patch, cwd=ROOT, check=True)
    files = verify_files()
    changed = set(git('diff', '--name-only', text=True).splitlines())
    untracked = set(git('ls-files', '--others', '--exclude-standard', text=True).splitlines())
    if changed | untracked != set(files):
        raise ValueError('Patch changed paths outside manifest')
    print(f'Applied and verified {len(files)} source files; no release activation.')
elif sys.argv[1] == 'export':
    files = verify_files()
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise ValueError('Repository mismatch')
    token = os.environ['GH_TOKEN']
    exported = []
    for name, expected in sorted(files.items()):
        data = (ROOT / name).read_bytes()
        payload = json.dumps({'content': base64.b64encode(data).decode(), 'encoding': 'base64'}).encode()
        request = urllib.request.Request(
            f'https://api.github.com/repos/{REPOSITORY}/git/blobs',
            data=payload,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            actual = json.load(response)['sha']
        if actual != expected:
            raise ValueError('GitHub blob hash mismatch')
        exported.append({'path': name, 'sha': actual, 'mode': '100644', 'type': 'blob'})
        print(name, actual, flush=True)
    evidence = ROOT / 'semantic-materialize-evidence'
    evidence.mkdir(exist_ok=True)
    (evidence / 'exported-blobs.json').write_text(json.dumps(exported, indent=2) + '\n')
    print('Exported 39 verified blobs. No commit, ref, release, or inventory changed.')
else:
    raise SystemExit('Expected apply or export')
