import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('bootstrap_env', ROOT/'tools/bootstrap_env.py')
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='push env ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root/'requirements.txt').write_text('pyusb==1.3.1\n')
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_platform_and_architecture_names(self):
        for system,machine,expected in (
            ('Darwin','arm64','macos-arm64'), ('Darwin','x86_64','macos-x86_64'),
            ('Windows','AMD64','windows-amd64'), ('Windows','x86_64','windows-amd64'),
            ('Windows','ARM64','windows-arm64')):
            self.assertEqual(bootstrap.platform_tag(system,machine),expected)
        for system,machine in (('Linux','x86_64'),('Windows','x86')):
            with self.assertRaises(ValueError):bootstrap.platform_tag(system,machine)

    def fake_run(self, command, **kwargs):
        if len(command)>1 and command[1]=='venv':
            env=Path(command[-1])
            interpreter=bootstrap.interpreter_path(env,bootstrap.platform.system())
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            (env/'pyvenv.cfg').write_text('version = 3.11\n')
        if command[-1]==bootstrap.PROBE:
            python=Path(command[0])
            return types.SimpleNamespace(stdout=json.dumps(dict(system=bootstrap.platform.system(),
                machine=bootstrap.current_machine(bootstrap.platform.system()),version=[3,11],prefix=str(python.parent.parent))))
        return types.SimpleNamespace(returncode=0)

    def check_create_and_reuse(self, system, machine, executable_suffix):
        with patch.object(bootstrap.platform,'system',return_value=system), \
             patch.object(bootstrap,'current_machine',return_value=machine), \
             patch.object(bootstrap.shutil,'which',return_value='/tools/uv'), \
             patch.object(bootstrap.subprocess,'run',side_effect=self.fake_run) as run:
            interpreter=bootstrap.bootstrap(self.root)
            self.assertTrue(interpreter.as_posix().endswith(executable_suffix))
            commands=[call.args[0] for call in run.call_args_list]
            self.assertEqual(sum(c[1]=='venv' for c in commands),1)
            self.assertTrue(any(c[1:3]==['pip','install'] for c in commands))
            self.assertTrue(any(c[1:3]==['pip','check'] for c in commands))
            self.assertTrue(all(isinstance(c,list) for c in commands))
            run.reset_mock()
            bootstrap.bootstrap(self.root)
            self.assertFalse(any(c.args[0][1]=='venv' for c in run.call_args_list))

    def test_macos_create_and_reuse(self):
        self.check_create_and_reuse('Darwin','arm64','macos-arm64/bin/python3')

    def test_windows_create_and_reuse(self):
        self.check_create_and_reuse('Windows','AMD64','windows-amd64/Scripts/python.exe')

    def test_dry_run_does_not_create_or_install(self):
        with patch.object(bootstrap.shutil,'which',return_value='/tools/uv'), \
             patch.object(bootstrap.platform,'system',return_value='Darwin'), \
             patch.object(bootstrap,'current_machine',return_value='arm64'), \
             patch.object(bootstrap.subprocess,'run') as run:
            bootstrap.bootstrap(self.root,dry_run=True)
            self.assertFalse((self.root/'.venvs').exists())
            run.assert_not_called()

    def test_incomplete_environment_is_not_overwritten(self):
        env=self.root/'.venvs/macos-arm64'
        env.mkdir(parents=True)
        marker=env/'keep.txt'
        marker.write_text('keep')
        with patch.object(bootstrap.shutil,'which',return_value='/tools/uv'), \
             patch.object(bootstrap.platform,'system',return_value='Darwin'), \
             patch.object(bootstrap,'current_machine',return_value='arm64'), \
             patch.object(bootstrap.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'incomplete'):bootstrap.bootstrap(self.root)
            self.assertEqual(marker.read_text(),'keep')
            run.assert_not_called()

    def test_wrong_architecture_is_rejected(self):
        env=self.root/'.venvs/macos-arm64'
        info=dict(system='Darwin',machine='x86_64',version=[3,11],prefix=str(env))
        with patch.object(bootstrap.subprocess,'run',return_value=types.SimpleNamespace(stdout=json.dumps(info))):
            with self.assertRaisesRegex(ValueError,'different OS/architecture'):
                bootstrap.validate_environment(env,env/'bin/python3','macos-arm64',self.root)

    def test_missing_uv_has_clear_error(self):
        with patch.object(bootstrap.shutil,'which',return_value=None):
            with self.assertRaisesRegex(ValueError,'uv was not found'):bootstrap.bootstrap(self.root)


if __name__=='__main__':unittest.main()
