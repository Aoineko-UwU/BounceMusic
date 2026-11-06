"""Verify portable updates without accessing the network or installed application."""
import hashlib
import io
import threading
import time
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from functools import partial

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import updater
import json
prepare_update=partial(updater.prepare_update,route='ghfast',route_tests={})

def package(entries):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        for name,content in entries.items(): archive.writestr(name,content)
    return data.getvalue()

def release(data):
    return {'tag_name':'v1.6.0','assets':[{'name':'BounceMusic-v1.6.0-win64.zip',
        'browser_download_url':'https://github.com/Aoineko-UwU/BounceMusic/releases/download/v1.6.0/BounceMusic-v1.6.0-win64.zip',
        'size':len(data),'digest':'sha256:'+hashlib.sha256(data).hexdigest()}]}

def test_download_validation():
    data=package({'BounceMusic.exe':b'program','_internal/data':b'data'})
    with tempfile.TemporaryDirectory() as directory:
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',side_effect=lambda *args,**kwargs:io.BytesIO(data)):
            progress=[]
            stage=Path(prepare_update(release(data),progress=lambda *event:progress.append(event)))
            assert (stage/'files'/'BounceMusic.exe').read_bytes()==b'program'
            assert (stage/'files'/'_internal'/'data').read_bytes()==b'data'
            assert progress[:2] == [('route','ghfast',len(data)),('download',0,len(data))]
            assert ('download',len(data),len(data)) in progress
            assert [event[0] for event in progress[-2:]] == ['verify','extract']
        no_size=release(data); no_size['assets'][0]['size']=0
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',side_effect=lambda *args,**kwargs:io.BytesIO(data)):
            progress=[]
            assert (Path(prepare_update(no_size,progress=lambda *event:progress.append(event)))/'files'/'BounceMusic.exe').is_file()
            assert ('download',0,0) in progress
        bad=release(data); bad['assets'][0]['digest']='sha256:'+'0'*64
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',side_effect=lambda *args,**kwargs:io.BytesIO(data)):
            try: prepare_update(bad)
            except RuntimeError as error: assert '校验' in str(error)
            else: raise AssertionError('Corrupt update accepted')
        traversal=package({'BounceMusic.exe':b'x','_internal/x':b'x','../escape':b'x'})
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',side_effect=lambda *args,**kwargs:io.BytesIO(traversal)):
            try: prepare_update(release(traversal))
            except ValueError as error: assert '路径' in str(error)
            else: raise AssertionError('Unsafe archive accepted')
        assert not (Path(directory)/'escape').exists()
        binary=b'MZ fake installer for testing'; setup=release(binary)
        setup['assets'][0]['name']='BounceMusic-v1.6.0-Setup-win64.exe'
        setup['assets'][0]['browser_download_url']='https://github.com/Aoineko-UwU/BounceMusic/releases/download/v1.6.0/BounceMusic-v1.6.0-Setup-win64.exe'
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',side_effect=lambda *args,**kwargs:io.BytesIO(binary)):
            assert (Path(prepare_update(setup,True))/'setup.exe').read_bytes()==binary
    assert updater.version_tuple('v1.10.0') > updater.version_tuple('1.9.9')
    name='BounceMusic-v1.6.0-win64.zip'; parser=updater.AssetExtractor(name)
    parser.feed('<a href="/Aoineko-UwU/BounceMusic/releases/download/v1.6.0/'+name+'">ZIP</a>'
                '<clipboard-copy aria-label="Copy to clipboard digest for '+name+'" value="sha256:'+'f'*64+'"></clipboard-copy>')
    assert parser.path.endswith('/'+name) and parser.digest=='sha256:'+'f'*64

def test_fallback_pause_and_cancel():
    data=package({'BounceMusic.exe':b'x'*180000,'_internal/data':b'data'})
    with tempfile.TemporaryDirectory() as directory:
        urls=[]
        def open_fallback(request,timeout):
            urls.append(request.full_url)
            if len(urls)==1: raise OSError('mirror unavailable')
            return io.BytesIO(data)
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',side_effect=open_fallback):
            assert Path(prepare_update(release(data))).is_dir()
        assert urls[0].startswith(updater.MIRROR) and urls[1].startswith('https://gh-proxy.org/')
        urls.clear()
        def corrupt_mirror(request,timeout):
            urls.append(request.full_url)
            return io.BytesIO(b'wrong content' if len(urls)==1 else data)
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',side_effect=corrupt_mirror):
            assert Path(prepare_update(release(data))).is_dir()
        assert len(urls)==2
        control=updater.DownloadControl(); paused=threading.Event(); finished=threading.Event(); result=[]
        def progress(phase,size,total):
            if phase=='download' and size and not paused.is_set():
                control.pause(True); paused.set()
        def worker():
            try: prepare_update(release(data),progress=progress,control=control)
            except updater.UpdateCancelled: result.append('cancelled')
            finally: finished.set()
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',side_effect=lambda *a,**k:io.BytesIO(data)):
            before=set(Path(directory).iterdir())
            thread=threading.Thread(target=worker); thread.start()
            assert paused.wait(3) and not finished.wait(.2)
            control.cancel(); assert finished.wait(3); thread.join()
            assert result==['cancelled'] and set(Path(directory).iterdir())==before
        control=updater.DownloadControl(); control.pause(True); resumed=threading.Event()
        thread=threading.Thread(target=lambda:(control.checkpoint(),resumed.set())); thread.start()
        assert not resumed.wait(.1); control.pause(False); assert resumed.wait(2); thread.join()

def test_official_metadata_fallback():
    value={'tag_name':'v1.8.0','assets':[]}
    with patch.object(updater.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(value).encode())),patch.object(updater,'release_from_web') as web:
        assert updater.latest_release()==value
        web.assert_not_called()
    with patch.object(updater.urllib.request,'urlopen',side_effect=OSError('API offline')),patch.object(updater,'release_from_web',return_value=value):
        assert updater.latest_release()==value

if __name__=='__main__':
    test_download_validation()
    test_fallback_pause_and_cancel()
    test_official_metadata_fallback()
    print('Updater checks passed.')
