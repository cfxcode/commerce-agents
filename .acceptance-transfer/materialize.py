"""Temporary verified transport; exports blobs only, never refs or releases."""
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
EXPECTED = 'b0a50b772d0d8a034ec18c08b3c74380f0e9654fa748f2a7b4a9251aa6dffefd'
parts = [(ROOT / '.acceptance-transfer' / f'part-{i}').read_text() for i in range(6)]
# Restore the separately verified final byte of transport chunk 2.
if len(parts[2]) == 5999:
    parts[2] += '0'
patch = lzma.decompress(base64.b64decode(''.join(parts), validate=True))
if hashlib.sha256(patch).hexdigest() != EXPECTED:
    raise SystemExit('Transport checksum mismatch')
rows = subprocess.check_output(['git', 'apply', '--numstat', '-'], input=patch).decode().splitlines()
paths = [row.split('\t', 2)[2] for row in rows]
if len(paths) != 20 or len(set(paths)) != 20:
    raise SystemExit('Unexpected source file set')
for name in paths:
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT) or name.startswith(('knowledge/releases/', '.env', '.git/')) or name == 'configs/reasoning.yaml':
        raise SystemExit('Disallowed source destination')
if sys.argv[1] == 'apply':
    subprocess.run(['git', 'apply', '--check', '-'], input=patch, check=True)
    subprocess.run(['git', 'apply', '-'], input=patch, check=True)
    print('Applied 20 checksum-verified source files; no release activation.')
elif sys.argv[1] == 'export':
    entries = []
    token = os.environ['GH_TOKEN']
    for name in paths:
        data = (ROOT / name).read_bytes()
        payload = json.dumps({'content': base64.b64encode(data).decode(), 'encoding': 'base64'}).encode()
        request = urllib.request.Request('https://api.github.com/repos/cfxcode/commerce-agents/git/blobs', data=payload, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            sha = json.load(response)['sha']
        expected_sha = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
        if sha != expected_sha:
            raise SystemExit('Blob checksum mismatch')
        entries.append({'path': name, 'mode': '100644', 'type': 'blob', 'sha': sha})
    out = ROOT / 'acceptance-evidence'
    out.mkdir(exist_ok=True)
    (out / 'tree-entries.json').write_text(json.dumps(entries, indent=2) + '\n')
    print('Exported verified source blobs without changing any branch or release.')
else:
    raise SystemExit('Unsupported operation')
