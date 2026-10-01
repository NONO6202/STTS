import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import runtime
import driver_setup
import launcher


class RuntimePolicyTests(unittest.TestCase):
    def test_task_runs_as_current_user_without_password_limits_or_automatic_restarts(self):
        sid = 'S-1-5-21-123'
        for login in (False, True):
            root = ET.fromstring(runtime.task_xml(sid, [r'D:\Steam Library\STTS\STTSRuntime.exe', '--background-runtime'], login))
            namespace = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
            value = lambda path: root.find('t:' + path.replace('/', '/t:'), namespace)
            self.assertEqual(value('Principals/Principal/UserId').text, sid)
            self.assertEqual(value('Principals/Principal/LogonType').text, 'InteractiveToken')
            self.assertEqual(value('Principals/Principal/RunLevel').text, 'LeastPrivilege')
            self.assertEqual(value('Settings/MultipleInstancesPolicy').text, 'IgnoreNew')
            self.assertEqual(value('Settings/ExecutionTimeLimit').text, 'PT0S')
            self.assertEqual(value('Settings/StopIfGoingOnBatteries').text, 'false')
            self.assertIsNone(value('Settings/RestartOnFailure'))
            self.assertEqual(value('Actions/Exec/Command').text, r'D:\Steam Library\STTS\STTSRuntime.exe')
            self.assertEqual(value('Actions/Exec/Arguments').text, '--background-runtime')
            self.assertEqual(value('Triggers/LogonTrigger') is not None, login)

    def test_reopen_existing_runtime_does_not_start_another_task(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, 'data_directory', return_value=Path(folder)), \
             patch.object(runtime, 'user_sid', return_value='S-1-5-21-123'), patch.object(runtime, 'configure', return_value='task') as configure, \
             patch.object(runtime, 'request', return_value={'pid': 7}) as request, patch.object(runtime, 'system_command') as command:
            (Path(folder) / 'settings.json').write_text(json.dumps({'setup_completed': True, 'login': False}))
            runtime.launch()
            configure.assert_called_once_with(False, 'S-1-5-21-123')
            request.assert_called_once_with('show', 'S-1-5-21-123'); command.assert_not_called()

    def test_quit_controller_never_launches_or_restarts_a_runtime(self):
        with patch.object(sys, 'argv', ['STTS.exe', '--quit']), patch.object(runtime, 'request', return_value={'pid': 7}) as request, patch.object(runtime, 'launch') as launch:
            self.assertEqual(launcher.main(), 0)
            request.assert_called_once_with('quit'); launch.assert_not_called()

    def test_successful_driver_install_keeps_default_device_restore_and_gives_conditional_restart_advice(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(driver_setup, 'installer') as installer, \
             patch.object(driver_setup, 'driver_exists', return_value=False), patch.object(driver_setup, '_helper') as helper, \
             patch.object(driver_setup, '_run_elevated', return_value=driver_setup.RESTART):
            installer.return_value.is_file.return_value = True
            message = driver_setup.setup()
            self.assertEqual(message, '가상 마이크를 설치했습니다. Discord 입력 장치에서 STTS를 선택하세요. 목록에 없으면 Discord를 다시 켜거나 PC를 재시작하세요.')
            self.assertEqual([call.args for call in helper.call_args_list], [('--save-defaults',), ('--restore-defaults',)])


class RuntimeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)
        spec = importlib.util.spec_from_file_location('stts_runtime_ui', Path(__file__).parents[1] / 'Windows/app.py')
        cls.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.module)

    def test_window_close_hides_or_minimizes_without_quitting_including_legacy_choice(self):
        app = self.module.App.__new__(self.module.App)
        app.tools = Mock(); app.recording_key = False; app.voice_cancel = None
        app.root = Mock(); app.quit = Mock()
        for action in ('앱 종료', '백그라운드 실행', '최소화'):
            app.config = {'close': action}; app.root.reset_mock()
            app.close_window()
            app.quit.assert_not_called()
            if action == '최소화': app.root.showMinimized.assert_called_once()
            else: app.root.hide.assert_called_once()

    def test_controller_disconnect_and_window_close_leave_same_runtime_available(self):
        from PySide6.QtWidgets import QWidget
        from PySide6.QtNetwork import QLocalSocket
        import time, uuid
        root = QWidget(); app = Mock(root=root)
        app.show.side_effect = root.show; app.close_window.side_effect = root.hide
        with patch.object(runtime, 'control_name', return_value='stts-check-' + uuid.uuid4().hex):
            server = self.module.ControlServer(root); server.app = app
        try:
            name = server.server.serverName()
            pid = None
            for command in ('show', 'hide', 'show', 'status'):
                client = QLocalSocket(); client.connectToServer(name)
                self.assertTrue(client.waitForConnected(1000))
                client.write(json.dumps({'command': command}).encode() + b'\n'); client.flush()
                deadline = time.monotonic() + 2
                while not client.canReadLine() and time.monotonic() < deadline: self.qt.processEvents()
                response = json.loads(bytes(client.readLine()))
                self.assertEqual(response['pid'], pid or os.getpid()); pid = response['pid']
                self.assertEqual(response['visible'], command != 'hide')
                client.abort(); self.qt.processEvents()
                app.quit.assert_not_called(); self.assertTrue(server.server.isListening())
        finally: server.stop(); root.close(); root.deleteLater(); self.qt.processEvents()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows named-pipe client')
    def test_native_launcher_client_reaches_qt_runtime_and_uses_the_same_control_protocol(self):
        from concurrent.futures import ThreadPoolExecutor
        from PySide6.QtWidgets import QWidget
        import time, uuid
        root = QWidget(); app = Mock(root=root)
        app.show.side_effect = root.show; app.close_window.side_effect = root.hide
        with patch.object(runtime, 'control_name', return_value='stts-native-check-' + uuid.uuid4().hex):
            server = self.module.ControlServer(root); server.app = app
            try:
                with self.assertRaises(RuntimeError): self.module.ControlServer(QWidget())
                with ThreadPoolExecutor(max_workers=1) as executor:
                    for command in ('show', 'hide', 'status'):
                        response = executor.submit(runtime.request, command)
                        deadline = time.monotonic() + 3
                        while not response.done() and time.monotonic() < deadline: self.qt.processEvents()
                        result = response.result(timeout=1)
                        self.assertIsNotNone(result)
                        self.assertEqual(result['pid'], os.getpid())
                        self.assertEqual(result['visible'], command == 'show')
                        app.quit.assert_not_called()
            finally: server.stop(); root.close(); root.deleteLater(); self.qt.processEvents()


if __name__ == '__main__': unittest.main()
