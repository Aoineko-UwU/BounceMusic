"""Verify portable updates without accessing the network or installed application."""
import hashlib
import io
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import updater

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
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',return_value=io.BytesIO(data)):
            progress=[]
            stage=Path(updater.prepare_update(release(data),progress=lambda *event:progress.append(event)))
            assert (stage/'files'/'BounceMusic.exe').read_bytes()==b'program'
            assert (stage/'files'/'_internal'/'data').read_bytes()==b'data'
            assert progress[0] == ('download',0,len(data))
            assert ('download',len(data),len(data)) in progress
            assert [event[0] for event in progress[-2:]] == ['verify','extract']
        no_size=release(data); no_size['assets'][0]['size']=0
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',return_value=io.BytesIO(data)):
            progress=[]
            assert (Path(updater.prepare_update(no_size,progress=lambda *event:progress.append(event)))/'files'/'BounceMusic.exe').is_file()
            assert progress[0] == ('download',0,0)
        bad=release(data); bad['assets'][0]['digest']='sha256:'+'0'*64
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',return_value=io.BytesIO(data)):
            try: updater.prepare_update(bad)
            except ValueError as error: assert '校验' in str(error)
            else: raise AssertionError('Corrupt update accepted')
        traversal=package({'BounceMusic.exe':b'x','_internal/x':b'x','../escape':b'x'})
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',return_value=io.BytesIO(traversal)):
            try: updater.prepare_update(release(traversal))
            except ValueError as error: assert '路径' in str(error)
            else: raise AssertionError('Unsafe archive accepted')
        assert not (Path(directory)/'escape').exists()
        binary=b'fake installer for testing'; setup=release(binary)
        setup['assets'][0]['name']='BounceMusic-v1.6.0-Setup-win64.exe'
        setup['assets'][0]['browser_download_url']='https://github.com/Aoineko-UwU/BounceMusic/releases/download/v1.6.0/BounceMusic-v1.6.0-Setup-win64.exe'
        with patch.object(updater.tempfile,'tempdir',directory),patch.object(updater.urllib.request,'urlopen',return_value=io.BytesIO(binary)):
            assert (Path(updater.prepare_update(setup,True))/'setup.exe').read_bytes()==binary
    assert updater.version_tuple('v1.10.0') > updater.version_tuple('1.9.9')
    name='BounceMusic-v1.6.0-win64.zip'; parser=updater.AssetExtractor(name)
    parser.feed('<a href="/Aoineko-UwU/BounceMusic/releases/download/v1.6.0/'+name+'">ZIP</a>'
                '<clipboard-copy aria-label="Copy to clipboard digest for '+name+'" value="sha256:'+'f'*64+'"></clipboard-copy>')
    assert parser.path.endswith('/'+name) and parser.digest=='sha256:'+'f'*64

if __name__=='__main__':
    test_download_validation()
    print('Updater checks passed.')
