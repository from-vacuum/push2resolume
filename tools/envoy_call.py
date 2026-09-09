#!/usr/bin/env python3
"""Call the project's loopback Envoy MCP from a JSON request file."""
import argparse
import ast
import json
from pathlib import Path
import urllib.request


def call(name, arguments):
    registry = json.loads(Path('.embody/envoy.json').read_text())
    port = registry['instances'][registry['active']]['port']
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': name, 'arguments': arguments}}).encode()
    request = urllib.request.Request(
        'http://127.0.0.1:%d/mcp' % port, data=body,
        headers={'Content-Type': 'application/json',
                 'Accept': 'application/json, text/event-stream',
                 'X-Envoy-Session': 'codex-layout-implementation'})
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read().decode()
    messages = [json.loads(line[6:]) for line in raw.splitlines()
                if line.startswith('data: ')] if raw.startswith('event:') else [json.loads(raw)]
    message = next(m for m in messages if m.get('id') == 1)
    if 'error' in message:
        raise RuntimeError(message['error'])
    result = message['result']
    content = result.get('content', [])
    values = [json.loads(c['text']) for c in content if c.get('type') == 'text']
    if result.get('isError'):
        raise RuntimeError(values)
    value = values[0] if len(values) == 1 else values
    if isinstance(value, dict) and value.get('success') is False:
        raise RuntimeError(value)
    if name == 'execute_python' and isinstance(value, dict):
        inner = value.get('result')
        if isinstance(inner, str):
            try:
                value['result'] = ast.literal_eval(inner)
            except (ValueError, SyntaxError):
                pass
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('tool')
    parser.add_argument('--args', default='{}')
    parser.add_argument('--file')
    parser.add_argument('--output')
    args = parser.parse_args()
    params = json.loads(Path(args.file).read_text() if args.file else args.args)
    result = call(args.tool, params)
    encoded = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(encoded + '\n')
        print(args.output)
    else:
        print(encoded)
