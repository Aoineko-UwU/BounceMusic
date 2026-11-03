"""Small Windows GUI regression check; no audio hardware is required."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import app as module


def near_center(window):
    window.update_idletasks()
    expected_x = (window.winfo_screenwidth() - window.winfo_width()) / 2
    expected_y = (window.winfo_screenheight() - window.winfo_height()) / 2
    assert abs(window.winfo_x() - expected_x) < 3
    assert abs(window.winfo_y() - expected_y) < 3


def test_window_and_image_flow():
    with tempfile.TemporaryDirectory() as directory:
        config = str(Path(directory) / '设置.json')
        image_path = str(Path(directory) / 'large.png')
        Image.new('RGBA', (1800, 1200), (20, 180, 200, 255)).save(image_path)
        with patch.object(module, 'CONFIG', config), patch.object(module.App, 'make_tray'), patch.object(module.App, 'refresh_sources'):
            application = module.App()
            try:
                assert application.root.resizable() == (1, 1)
                assert application.root.minsize() == (610, 610)
                application.root.geometry('800x720')
                application.root.update_idletasks()
                application.image_mode.set('multiple')
                first = application.make_sprite(image_path, 240, 100, 100)
                second = application.make_sprite(image_path, 240, 400, 100)
                assert max(first.original.size) <= module.MAX_IMAGE_SIDE
                assert first.original is second.original
                application.frame_cache = {}
                first.render(1., 1., 0., (255, 255, 255))
                second.render(1., 1., 0., (255, 255, 255))
                assert first.photo is second.photo
                application.close_sprite(first.id)
                assert first not in application.sprites
                assert len(json.loads(Path(config).read_text(encoding='utf-8'))['windows']) == 2
                application.show_settings()
                near_center(application.settings_window)
                application.song_feedback(120.)
                near_center(application.feedback_dialog)
                bpm_row = application.feedback_dialog.winfo_children()[1]
                entry = next(child for child in bpm_row.winfo_children() if isinstance(child, module.ttk.Entry))
                entry.insert(0, '110')
                button = next(child for child in application.feedback_dialog.winfo_children()
                              if isinstance(child, module.ttk.Button) and child.cget('text') == '仅提交 BPM')
                button.invoke()
                assert abs(application.tempo_factor - 110/120) < .001
                application.clear_analysis_data()
                assert application.tempo_factor == 1.
                application.save()
                assert json.loads(Path(config).read_text(encoding='utf-8'))['main_geometry'] == '800x720'
            finally:
                application.quit()


if __name__ == '__main__':
    test_window_and_image_flow()
    print('UI checks passed.')
