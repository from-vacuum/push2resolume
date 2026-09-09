#!/usr/bin/env python3
"""Create or populate this machine's environment using Python 3.11+ and uv."""
import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 11)
PROBE = """
import json, os, platform, sys
machine = (os.environ.get('PROCESSOR_ARCHITECTURE') or platform.machine()) if sys.platform == 'win32' else platform.machine()
print(json.dumps(dict(system=platform.system(), machine=machine,
                     version=list(sys.version_info[:2]), prefix=sys.prefix)))
"""
CHECK_IMPORTS = """
import attrs, cryptography, mcp, usb, yaml
from importlib.metadata import version
for name in ('attrs', 'cryptography', 'mcp', 'pyusb', 'PyYAML'):
    print(name + '==' + version(name))
"""


def platform_tag(system, machine):
    machine = machine.lower()
    if machine in ('aarch64', 'arm64'):
        arch = 'arm64'
    elif machine in ('amd64', 'x86_64', 'x64'):
        arch = 'amd64' if system == 'Windows' else 'x86_64'
    else:
        raise ValueError('Unsupported Python architecture: ' + machine)
    if system not in ('Darwin', 'Windows'):
        raise ValueError('Supported operating systems are macOS and Windows, not ' + system)
    return ('macos-' if system == 'Darwin' else 'windows-') + arch


def current_machine(system):
    if system == 'Windows':
        return os.environ.get('PROCESSOR_ARCHITECTURE') or platform.machine()
    return platform.machine()


def interpreter_path(environment, system):
    return environment / ('Scripts/python.exe' if system == 'Windows' else 'bin/python3')


def run_command(command, root, dry_run=False):
    display = subprocess.list2cmdline(command) if platform.system() == 'Windows' else shlex.join(command)
    print('+ ' + display, flush=True)
    if not dry_run:
        subprocess.run(command, cwd=root, check=True)


def validate_environment(environment, python, tag, root):
    result = subprocess.run([str(python), '-c', PROBE], cwd=root, check=True,
                            capture_output=True, text=True, timeout=30)
    info = json.loads(result.stdout)
    if tuple(info['version']) < MIN_PYTHON:
        raise ValueError('Existing environment needs Python 3.11 or newer: ' + str(environment))
    if platform_tag(info['system'], info['machine']) != tag:
        raise ValueError('Existing environment belongs to a different OS/architecture: ' + str(environment))
    if Path(info['prefix']).resolve() != environment.resolve():
        raise ValueError('Interpreter is not using the expected environment: ' + str(python))


def bootstrap(root=ROOT, dry_run=False):
    if sys.version_info[:2] < MIN_PYTHON:
        raise ValueError('Run this script with Python 3.11 or newer.')
    uv = shutil.which('uv')
    if not uv:
        raise ValueError('uv was not found on PATH.')
    root = Path(root).resolve()
    requirements = root / 'requirements.txt'
    if not requirements.is_file():
        raise ValueError('Missing dependency manifest: ' + str(requirements))
    system = platform.system()
    tag = platform_tag(system, current_machine(system))
    environment = root / '.venvs' / tag
    python = interpreter_path(environment, system)
    print('Environment: ' + str(environment), flush=True)

    # Never let uv replace an existing directory, including a broken env.
    if environment.is_symlink():
        raise ValueError('Refusing to install through an environment symlink: ' + str(environment))
    if environment.exists():
        if not (environment / 'pyvenv.cfg').is_file() or not python.is_file():
            raise ValueError('Existing environment is incomplete; rename it before retrying: ' + str(environment))
        print('Reusing existing environment.', flush=True)
    else:
        if not dry_run:
            environment.parent.mkdir(parents=True, exist_ok=True)
        run_command([uv, 'venv', '--no-project', '--relocatable', '--python',
                     sys.executable, str(environment)], root, dry_run)

    if not dry_run:
        validate_environment(environment, python, tag, root)
    run_command([uv, 'pip', 'install', '--python', str(python),
                 '--requirement', str(requirements)], root, dry_run)
    run_command([uv, 'pip', 'check', '--python', str(python)], root, dry_run)
    run_command([str(python), '-c', CHECK_IMPORTS], root, dry_run)
    print(('Planned interpreter: ' if dry_run else 'Ready: ') + str(python), flush=True)
    print('TD helper interpreter setting: ' + python.relative_to(root).as_posix())
    if system == 'Darwin':
        print('Physical LCD also requires system libusb (brew install libusb).')
    else:
        print('Windows LCD currently uses a stub; this script does not install USB drivers.')
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Print the setup commands without modifying anything.')
    args = parser.parse_args()
    try:
        bootstrap(dry_run=args.dry_run)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Environment setup failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
