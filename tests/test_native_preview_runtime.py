"""Optional-native runtime boundaries and actual caller-supplied font rendering."""
from __future__ import annotations

import io
import os
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from hwpx_automation.preview_runtime.render import check_input


def test_optional_modules_import_without_native_dependencies():
    code = r'''
import importlib, importlib.abc, sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PIL','fontTools','freetype','uharfbuzz'}:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, NoNative())
for name in ['backend','fonts','jobs','launcher','memory','raster','render','server',
             'windows_borders','windows_raster','windows_text']:
    importlib.import_module('hwpx_automation.preview_runtime.' + name)
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('data', [b'', b'partial save'])
def test_partial_save_is_rejected(data):
    with pytest.raises(ValueError, match='HWPX'):
        check_input(data)


def test_duplicate_archive_parts_are_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('Contents/section0.xml', '<section/>')
        with pytest.warns(UserWarning):
            archive.writestr('Contents/section0.xml', '<section/>')
    with pytest.raises(ValueError, match='ZIP'):
        check_input(data.getvalue())


def test_windows_venv_watch_does_not_measure_a_redirector(tmp_path, monkeypatch):
    from hwpx_automation.preview_runtime import jobs

    monkeypatch.setattr(jobs, 'sys', SimpleNamespace(platform='win32',
                        executable='venv-python', _base_executable='real-python'))
    with pytest.raises(ValueError, match='redirector'):
        jobs.JobManager(tmp_path / 'jobs')


def test_native_batch_render_with_explicit_fonts(tmp_path, monkeypatch):
    directory = os.environ.get('HWPX_NATIVE_PREVIEW_TEST_FONT_DIRECTORY')
    if not directory:
        pytest.skip('supply a licensed native-preview test font directory')
    pytest.importorskip('uharfbuzz')
    pytest.importorskip('hwpx.layout.object_scene')
    from hwpx import HwpxDocument
    from hwpx_automation.preview_runtime import render_bytes

    document = HwpxDocument.new()
    document.add_paragraph('Native preview 한글')
    stream = io.BytesIO()
    document.save_to_stream(stream)
    original = stream.getvalue()
    if sys.platform == 'win32':
        monkeypatch.setenv('HWPX_PREVIEW_NATIVE_TABLE_BORDERS', '1')
        monkeypatch.setenv('HWPX_PREVIEW_NATIVE_PICTURE_CROP', '1')
    output = tmp_path / 'native output'
    result = render_bytes(original, output, font_directory=directory)
    assert result['status'] == 'supported'
    assert result['qualityValidated'] is False
    assert (output / 'p0.png').read_bytes().startswith(b'\x89PNG')
    assert stream.getvalue() == original
