"""Measured download routes. Release metadata and digests remain GitHub-authenticated."""
import hashlib
import queue
import re
import threading
import time
import urllib.request
from pathlib import Path

ROUTES=(
    {'id':'ghproxy','name':'GH-Proxy','prefix':'https://gh-proxy.org/'},
    {'id':'ghfast','name':'GHFast','prefix':'https://ghfast.top/'},
    {'id':'ghproxynet','name':'GHProxy.net','prefix':'https://ghproxy.net/'},
    {'id':'github','name':'GitHub 直连','prefix':''},
)
ROUTE_IDS={route['id'] for route in ROUTES}
MAX_SIZE=500*1024*1024
HEADERS={'User-Agent':'BounceMusic-Updater','Accept':'application/octet-stream'}

class UpdateCancelled(Exception): pass
class RouteChanged(Exception): pass

class DownloadControl:
    def __init__(self):
        self.condition=threading.Condition(); self.paused=False; self.cancelled=False; self.pending_route=None
    def pause(self,paused):
        with self.condition:
            self.paused=paused; self.condition.notify_all()
    def cancel(self):
        with self.condition:
            self.cancelled=True; self.condition.notify_all()
    def switch_route(self,route):
        if route not in ROUTE_IDS and route!='auto': raise ValueError('下载线路不存在')
        with self.condition:
            self.pending_route=route; self.paused=False; self.condition.notify_all()
    def checkpoint(self):
        with self.condition:
            while self.paused and not self.cancelled and self.pending_route is None: self.condition.wait(.2)
            if self.cancelled: raise UpdateCancelled('已取消更新下载')
            if self.pending_route is not None:
                route=self.pending_route; self.pending_route=None
                raise RouteChanged(route)

def route_name(route):
    return next((item['name'] for item in ROUTES if item['id']==route),'自动选择')

def route_url(asset,route):
    item=next((item for item in ROUTES if item['id']==route),None)
    if item is None: raise ValueError('下载线路不存在')
    url=asset['browser_download_url']
    # Same-version package replacements must not retrieve an old mirror cache entry.
    if item['prefix']:
        url+=('&' if '?' in url else '?')+'bm_sha='+asset['digest'][7:23]
    return item['prefix']+url

def _status(response):
    return getattr(response,'status',200) or 200

def _read(response,size):
    return getattr(response,'read1',response.read)(size)

def _magic(asset): return b'MZ' if asset['name'].endswith('.exe') else b'PK'

def probe_route(asset,route):
    started=time.monotonic(); size=0; prefix=b''; first=None
    try:
        request=urllib.request.Request(route_url(asset,route),headers={**HEADERS,'Range':'bytes=0-524287'})
        with urllib.request.urlopen(request,timeout=4) as response:
            while size<524288 and time.monotonic()-started<5:
                block=_read(response,min(65536,524288-size))
                if not block: break
                if first is None: first=time.monotonic()
                prefix=(prefix+block)[:2]; size+=len(block)
                if len(prefix)>=2 and prefix!=_magic(asset): raise ValueError('返回的不是安装包')
        if size<2 or prefix!=_magic(asset): raise ValueError('没有收到有效数据')
        elapsed=max(.001,time.monotonic()-started)
        speed=size/elapsed; latency=max(0.,(first-started)*1000)
        quality='优' if speed>=1024*1024 else '良' if speed>=256*1024 else '较慢'
        return {'id':route,'ok':True,'speed':speed,'latency':latency,'quality':quality,'tested':time.time()}
    except Exception as error:
        return {'id':route,'ok':False,'speed':0.,'latency':0.,'quality':'不可用','error':str(error),'tested':time.time()}

def probe_routes(asset,callback=None,control=None):
    results={}; mailbox=queue.Queue()
    def worker(route): mailbox.put(probe_route(asset,route))
    for item in ROUTES: threading.Thread(target=worker,args=(item['id'],),daemon=True).start()
    deadline=time.monotonic()+7
    while len(results)<len(ROUTES) and time.monotonic()<deadline:
        if control: control.checkpoint()
        try: result=mailbox.get(timeout=.1)
        except queue.Empty: continue
        results[result['id']]=result
        if callback: callback(result)
    for item in ROUTES:
        if item['id'] not in results:
            result={'id':item['id'],'ok':False,'speed':0.,'latency':0.,'quality':'超时','error':'测速超时','tested':time.time()}
            results[item['id']]=result
            if callback: callback(result)
    return results

def route_order(preference='auto',results=None,fallback=True):
    if preference not in ROUTE_IDS and preference!='auto': preference='auto'
    results=results or {}
    def score(item):
        result=results.get(item['id'])
        if result and result.get('ok'): return (0,-result['speed'],result['latency'])
        return (2 if result else 1,0,0)
    ordered=[item['id'] for item in sorted(ROUTES,key=score)]
    if preference!='auto': ordered=[preference]+[item for item in ordered if item!=preference]
    return ordered if fallback else ordered[:1]

def _stream(asset,archive,route,progress,control):
    expected=int(asset.get('size',0)); offset=archive.stat().st_size if archive.exists() else 0
    headers=dict(HEADERS)
    if offset: headers['Range']=f'bytes={offset}-'
    if progress: progress('route',route,expected)
    request=urllib.request.Request(route_url(asset,route),headers=headers)
    with urllib.request.urlopen(request,timeout=6) as response:
        total=expected; status=_status(response)
        content_range=response.headers.get('Content-Range','') if hasattr(response,'headers') else ''
        match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',content_range)
        if status==206:
            if not match or int(match[1])!=offset or not int(match[1])<=int(match[2])<int(match[3]):
                raise ValueError('线路返回的续传范围无效')
            reported=int(match[3])
            if expected and reported!=expected: raise ValueError('线路返回的安装包大小不符')
            total=reported
        elif status==200:
            if offset:
                offset=0
                if progress: progress('restart',route,expected)
            if not total and hasattr(response,'headers'):
                try: total=int(response.headers.get('Content-Length',0))
                except (ValueError,TypeError): total=0
        else: raise OSError(f'下载服务器返回 HTTP {status}')
        if not 0<=total<=MAX_SIZE: raise ValueError('更新包大小不正确')
        size=offset; first=b''; last_report=0.
        with archive.open('ab' if offset else 'wb') as output:
            if progress: progress('download',size,total)
            while True:
                if control: control.checkpoint()
                block=_read(response,65536)
                if control: control.checkpoint()
                if not block: break
                if not offset and len(first)<2:
                    first=(first+block)[:2]
                    if len(first)>=2 and first!=_magic(asset): raise ValueError('线路返回网页或无效安装包')
                size+=len(block)
                if size>(total or MAX_SIZE): raise ValueError('更新包大小超过预期')
                output.write(block)
                now=time.monotonic()
                if progress and (now-last_report>=.15 or total and size==total):
                    progress('download',size,total); last_report=now
        if total and size<total: raise OSError('下载中断，保留已下载部分继续尝试')
    if control: control.checkpoint()
    if progress: progress('verify',size,total)
    digest=hashlib.sha256()
    with archive.open('rb') as downloaded:
        while True:
            if control: control.checkpoint()
            block=downloaded.read(1024*1024)
            if not block: break
            digest.update(block)
    if not size or expected and size!=expected or digest.hexdigest().lower()!=asset['digest'][7:].lower():
        raise ValueError('更新包校验失败')

def download_asset(asset,archive,progress=None,control=None,preference='auto',results=None,fallback=True):
    archive=Path(archive)
    if not 0<=int(asset.get('size',0))<=MAX_SIZE: raise ValueError('更新包大小不正确')
    if preference=='auto' and results is None:
        if progress: progress('testing',0,0)
        try:
            results=probe_routes(asset,lambda result:progress('probe',result,0) if progress else None,control)
        except RouteChanged as changed: preference=changed.args[0]; results={}
    order=route_order(preference,results,fallback); attempts={item:0 for item in ROUTE_IDS}; current=order[0]
    last_error=None
    while True:
        try:
            if control: control.checkpoint()
            attempts[current]+=1
            _stream(asset,archive,current,progress,control)
            return
        except RouteChanged as changed:
            selected=changed.args[0]
            order=route_order(selected,results,fallback); current=order[0]; attempts[current]=0
            if progress: progress('switch',current,0)
        except UpdateCancelled: raise
        except (OSError,ValueError) as error:
            last_error=error
            if isinstance(error,ValueError): archive.unlink(missing_ok=True)
            if progress: progress('retry',{'id':current,'reason':str(error)},0)
            candidates=[route for route in order if attempts[route]<1]+[route for route in order if attempts[route]<2]
            if not candidates: raise RuntimeError('可选下载线路均未完成下载：'+str(last_error)) from last_error
            current=candidates[0]
