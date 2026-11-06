"""Shared updater UI works without audio devices, network access or a frozen build."""
import json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import app

def test_routes_and_progress():
    with tempfile.TemporaryDirectory() as directory,patch.object(app,'CONFIG',str(Path(directory)/'设置.json')), \
         patch.object(app.App,'make_tray'),patch.object(app.App,'refresh_sources'):
        application=app.App()
        try:
            release={'tag_name':'v9.9.9','body':'## 本次更新\n1、简短更新',
                'assets':[{'name':'BounceMusic-v9.9.9-win64.zip','size':100000,'digest':'sha256:'+'a'*64,
                'browser_download_url':'https://github.com/Aoineko-UwU/BounceMusic/releases/download/v9.9.9/BounceMusic-v9.9.9-win64.zip'}]}
            panel=application.update_ui; panel.show_release(release); application.root.update()
            tree=panel.route_tree
            assert len(tree.get_children())==5
            style=app.ttk.Style(application.root)
            for mode,foreground,background in [('dark','#f2f3f5','#30343d'),('light','#161616','#ffffff')]:
                application.theme_mode.set(mode); application.apply_theme()
                assert style.lookup('Treeview','foreground')==foreground
                assert style.lookup('Treeview','background')==background
                assert style.lookup('Treeview','fieldbackground')==background
                assert style.lookup('Treeview','foreground',('selected',))=='#ffffff'
                assert style.lookup('Treeview','background',('selected',))=='#2769ad'
                assert style.lookup('Treeview.Heading','foreground')==foreground
                def has_focus(layout):
                    return any(name.lower().endswith('.focus') or has_focus(options.get('children',[])) for name,options in layout)
                for name in ('TButton','TCheckbutton','TRadiobutton','TNotebook.Tab'):
                    assert not has_focus(style.layout(name))
                def element_names(layout):
                    return [value for name,options in layout for value in [name,*element_names(options.get('children',[]))]]
                assert 'TickCheck.indicator' in element_names(style.layout('TCheckbutton'))
                assert all(str(photo) in application.root.tk.call('image','names') for photo in application.checkmark_images.values())
            result={'id':'github','ok':True,'speed':2097152.,'latency':123.,'quality':'优'}
            panel.route_result(panel.probe_token,result)
            assert tree.item('github','values')[1]=='2.00 MB/s'
            tree.selection_set('github'); application.root.update()
            assert panel.preference.get()=='github'
            assert json.loads(Path(app.CONFIG).read_text(encoding='utf-8'))['update_route']=='github'
            panel.dialog.destroy(); panel.show_progress(); application.root.update()
            panel.progress('route','github',100000)
            with patch.object(app.time,'monotonic',return_value=100.): panel.progress('download',10000,100000)
            with patch.object(app.time,'monotonic',return_value=101.): panel.progress('download',60000,100000)
            assert 'KB/s' in panel.rate_text.get() and '预计剩余' in panel.rate_text.get()
            assert '60%' in application.update_progress_text.get()
            panel.progress_route.set('GHFast')
            panel.switch_button.invoke()
            assert application.update_control.pending_route=='ghfast'
            application.update_control.pending_route=None
            panel.failed('模拟网络断开')
            assert application.update_pause_button.cget('text')=='重试下载'
            panel.progress_route.set('GitHub 直连')
            with patch.object(panel,'start_download') as retry:
                application.update_pause_button.invoke(); retry.assert_called_once()
            assert panel.preference.get()=='github'
            panel.close_progress()
            assert application.update_progress_window is None and application.update_control is None
        finally: application.quit()

if __name__=='__main__':
    test_routes_and_progress(); print('Update UI checks passed.')
