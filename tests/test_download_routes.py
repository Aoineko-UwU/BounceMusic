"""Resume, route switching and integrity checks with deterministic HTTP responses."""
import hashlib,io,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import download_routes as routes

class Response(io.BytesIO):
    def __init__(self,data,status=200,headers=None,fail_after=None):
        super().__init__(data); self.status=status; self.headers=headers or {}; self.fail_after=fail_after
    def read1(self,size=-1):
        if self.fail_after is not None and self.tell()>=self.fail_after: raise OSError('simulated connection loss')
        if self.fail_after is not None: size=min(size,self.fail_after-self.tell())
        return self.read(size)

def asset(data):
    return {'name':'BounceMusic-v1.8.0-win64.zip','size':len(data),'digest':'sha256:'+hashlib.sha256(data).hexdigest(),
            'browser_download_url':'https://github.com/Aoineko-UwU/BounceMusic/releases/download/v1.8.0/BounceMusic-v1.8.0-win64.zip'}

def resumed(data,offset):
    return Response(data[offset:],206,{'Content-Range':f'bytes {offset}-{len(data)-1}/{len(data)}'})

def test_resume_and_unsupported_range():
    data=b'PK'+bytes(range(256))*1000
    for supports_range in (True,False):
        requests=[]; progress=[]
        def open_request(request,timeout):
            requests.append(request)
            if len(requests)==1: return Response(data,fail_after=65536)
            assert request.get_header('Range')=='bytes=65536-'
            return resumed(data,65536) if supports_range else Response(data)
        with tempfile.TemporaryDirectory() as directory,patch.object(routes.urllib.request,'urlopen',side_effect=open_request):
            target=Path(directory)/'part'
            routes.download_asset(asset(data),target,lambda *event:progress.append(event),preference='ghfast',results={})
            assert target.read_bytes()==data and len(requests)==2
            assert any(phase=='restart' for phase,_,_ in progress)==(not supports_range)

def test_live_route_switch():
    data=b'PK'+b'x'*200000; control=routes.DownloadControl(); requests=[]; changed=False
    def open_request(request,timeout):
        requests.append(request)
        if len(requests)==1: return Response(data)
        assert request.full_url.startswith('https://github.com/')
        assert request.get_header('Range')=='bytes=65536-'
        return resumed(data,65536)
    def progress(phase,size,total):
        nonlocal changed
        if phase=='download' and size and not changed:
            changed=True; control.switch_route('github')
    with tempfile.TemporaryDirectory() as directory,patch.object(routes.urllib.request,'urlopen',side_effect=open_request):
        target=Path(directory)/'part'
        routes.download_asset(asset(data),target,progress,control,'ghfast',{},False)
        assert target.read_bytes()==data and len(requests)==2

def test_bad_range_and_manual_only():
    data=b'PK'+b'z'*200000; requests=[]
    def open_request(request,timeout):
        requests.append(request)
        if len(requests)==1: return Response(data,fail_after=65536)
        if len(requests)==2: return resumed(data,65537)
        assert request.get_header('Range') is None
        return Response(data)
    with tempfile.TemporaryDirectory() as directory,patch.object(routes.urllib.request,'urlopen',side_effect=open_request):
        target=Path(directory)/'part'
        routes.download_asset(asset(data),target,preference='ghfast',results={})
        assert target.read_bytes()==data and len(requests)==3
    requests=[]
    def unavailable(request,timeout): requests.append(request.full_url); raise OSError('offline')
    with tempfile.TemporaryDirectory() as directory,patch.object(routes.urllib.request,'urlopen',side_effect=unavailable):
        try: routes.download_asset(asset(data),Path(directory)/'part',preference='github',results={},fallback=False)
        except RuntimeError: pass
        else: raise AssertionError('Unavailable manual route accepted')
    assert len(requests)==2 and all(url.startswith('https://github.com/') for url in requests)

def test_probe_ranking_and_cache_key():
    data=b'PK'+b'a'*20000; meta=asset(data)
    with patch.object(routes.urllib.request,'urlopen',return_value=Response(data)):
        assert routes.probe_route(meta,'ghfast')['ok']
    with patch.object(routes.urllib.request,'urlopen',return_value=Response(b'<html>not a download</html>')):
        assert not routes.probe_route(meta,'ghfast')['ok']
    results={'ghfast':{'ok':True,'speed':1000,'latency':100},'github':{'ok':True,'speed':1000000,'latency':500}}
    assert routes.route_order('auto',results)[0]=='github'
    assert routes.route_order('ghfast',results,False)==['ghfast']
    assert meta['digest'][7:23] in routes.route_url(meta,'ghfast')
    assert routes.route_url(meta,'github')==meta['browser_download_url']
    control=routes.DownloadControl(); control.pause(True); control.switch_route('github')
    try: control.checkpoint()
    except routes.RouteChanged as changed: assert changed.args==('github',)
    else: raise AssertionError('Paused route switch was ignored')

if __name__=='__main__':
    test_resume_and_unsupported_range(); test_live_route_switch(); test_bad_range_and_manual_only(); test_probe_ranking_and_cache_key()
    print('Download route checks passed.')
