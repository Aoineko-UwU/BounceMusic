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
    assert abs(window.winfo_x() - expected_x) < 3, (window.geometry(),expected_x,expected_y)
    assert abs(window.winfo_y() - expected_y) < 3, (window.geometry(),expected_x,expected_y)


def find_label(widget, text):
    if isinstance(widget, module.ttk.Label) and widget.cget('text') == text:
        return widget
    for child in widget.winfo_children():
        found = find_label(child, text)
        if found: return found
    return None


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
                application.root.update()
                for name in ('动画幅度','节奏偏移'):
                    label=find_label(application.root,name)
                    scale=next(child for child in label.master.winfo_children() if isinstance(child,module.tk.Scale))
                    label_mid=label.winfo_rooty()+label.winfo_height()/2
                    scale_mid=scale.winfo_rooty()+scale.winfo_height()/2
                    assert abs(label_mid-scale_mid)<3
                application.image_mode.set('multiple')
                first = application.make_sprite(image_path, 240, 100, 100)
                second = application.make_sprite(image_path, 240, 400, 100)
                assert max(first.original.size) <= module.MAX_IMAGE_SIDE
                assert first.original is second.original
                assert len(application.loading_source_frames) == 12
                application.frame_cache = {}
                first.render(1., 1., 0., (255, 255, 255))
                second.render(1., 1., 0., (255, 255, 255))
                assert first.photo is second.photo
                first.render(1., 1., 0., (255, 255, 255), 0)
                assert first.render_key[-1] == 0
                application.close_sprite(first.id)
                assert first not in application.sprites
                assert len(json.loads(Path(config).read_text(encoding='utf-8'))['windows']) == 2
                application.select_sprite(second.id)
                application.show_settings()
                application.settings_window.update()
                near_center(application.settings_window)
                assert application.preview_key[0] == id(second.original)
                assert application.loading_preview.cget('image')
                application.loading_x.set(25)
                application.loading_y.set(70)
                application.set_loading_position()
                assert application.preview_key[1:3] == (25,70)
                second.render(1.,1.,0.,(255,255,255),0)
                assert second.render_key[-2:] == ((25,70),0)
                saved=json.loads(Path(config).read_text(encoding='utf-8'))
                assert (saved['loading_x'],saved['loading_y']) == (85,12)
                second_record=next(record for record in saved['windows'] if record['id']==second.id)
                assert (second_record['loading_x'],second_record['loading_y']) == (25,70)
                application.select_sprite(application.sprites[0].id)
                assert (application.loading_x.get(),application.loading_y.get()) == (85,12)
                application.loading_target.current(1)
                application.on_loading_target_selected()
                assert (application.loading_x.get(),application.loading_y.get()) == (25,70)
                for name in ('最高弹跳速度','渐隐时间','歌曲结束静音阈值'):
                    label=find_label(application.settings_window,name)
                    scale=next(child for child in label.master.winfo_children() if isinstance(child,module.tk.Scale))
                    assert abs((label.winfo_rooty()+label.winfo_height()/2)
                               -(scale.winfo_rooty()+scale.winfo_height()/2))<3
                application.song_feedback(120.)
                near_center(application.feedback_dialog)
                bpm_row = application.feedback_dialog.winfo_children()[1]
                entry = next(child for child in bpm_row.winfo_children() if isinstance(child, module.ttk.Entry))
                entry.insert(0, '110')
                button = next(child for child in application.feedback_dialog.winfo_children()
                              if isinstance(child, module.ttk.Button) and child.cget('text') == '仅提交 BPM')
                button.invoke()
                assert application.config['bpm_examples'][-1] == {'estimated':120.,'actual':110.,'source':'feedback'}
                application.clear_analysis_data()
                assert 'bpm_examples' not in application.config
                assert application.double_click_close.get()
                class PlayingAnalyzer:
                    auto_estimate = 120.
                    manual_bpm = 0.
                    octave_bias = 0
                    reset_epoch = 0
                    bpm = 120.
                    playing = True
                    def is_playing(self): return self.playing
                    def values(self): return self.bpm, .2, 1., .12, .8
                    def lock_bpm(self, value): self.manual_bpm = value
                application.analyzer = PlayingAnalyzer()
                application.manual_bpm_text.set('115')
                application.apply_manual_bpm()
                assert application.analyzer.manual_bpm == 115.
                assert application.config['bpm_examples'][-1]['source'] == 'live'
                application.clear_manual_bpm()
                assert application.manual_bpm_text.get() == ''
                application.analyzer.bpm = 0.
                application.root.after_cancel(application.tick_job)
                application.tick()
                assert application.sprites[0].render_key[-1] >= 0
                application.analyzer.bpm = 120.
                application.root.after_cancel(application.tick_job)
                application.tick()
                assert application.sprites[0].render_key[-1] == -1
                application.analyzer.playing = False
                application.analyzer.bpm = 0.
                application.root.after_cancel(application.tick_job)
                application.tick()
                assert application.sprites[0].render_key[-1] == -1
                application.analyzer = None
                application.double_click_close.set(False)
                second.double_click(None)
                assert second in application.sprites
                application.double_click_close.set(True)
                second.double_click(None)
                assert second not in application.sprites
                application.save()
                assert json.loads(Path(config).read_text(encoding='utf-8'))['main_geometry'] == '800x720'
            finally:
                application.quit()


def test_windows_10_uses_device_mode():
    with tempfile.TemporaryDirectory() as directory:
        with patch.object(module,'CONFIG',str(Path(directory)/'设置.json')), \
             patch.object(module,'process_capture_supported',return_value=False), \
             patch.object(module.App,'make_tray'), patch.object(module.App,'refresh_sources'):
            application=module.App()
            try:
                assert application.source_mode.get()=='device'
                assert '播放设备' in application.status.get()
            finally:
                application.quit()


if __name__ == '__main__':
    test_window_and_image_flow()
    test_windows_10_uses_device_mode()
    print('UI checks passed.')
