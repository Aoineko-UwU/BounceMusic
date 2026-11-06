"""Download, verify, and stage an official portable release."""
import hashlib
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import queue
import time
import urllib.request
import urllib.error
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from download_routes import (ROUTES,DownloadControl,UpdateCancelled,probe_routes,route_name,route_order,download_asset)

API = 'https://api.github.com/repos/Aoineko-UwU/BounceMusic/releases/latest'
HEADERS = {'User-Agent': 'BounceMusic-Updater', 'Accept': 'application/vnd.github+json'}
REPO = 'https://github.com/Aoineko-UwU/BounceMusic'
MIRROR = 'https://ghfast.top/'

class TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]
    def handle_starttag(self, tag, attrs):
        if tag in ('p','li','h1','h2','h3','br'): self.parts.append('\n')
    def handle_data(self, data): self.parts.append(data)
    def text(self): return re.sub(r'\n[ \t]*(?:\n[ \t]*)+','\n\n',''.join(self.parts)).strip()

class AssetExtractor(html.parser.HTMLParser):
    def __init__(self, name):
        super().__init__(); self.name=name; self.digest=None; self.path=None
    def handle_starttag(self, tag, attrs):
        attr=dict(attrs)
        if tag=='a' and attr.get('href','').endswith('/'+self.name): self.path=attr['href']
        if tag=='clipboard-copy' and attr.get('aria-label','').endswith(' for '+self.name):
            self.digest=attr.get('value')

def release_from_web():
    with urllib.request.urlopen(urllib.request.Request(REPO+'/releases/latest',headers=HEADERS),timeout=6) as response:
        final=urlparse(response.geturl())
        if final.scheme!='https' or final.hostname!='github.com': raise ValueError('更新页面地址无效')
        tag=final.path.rsplit('/',1)[-1]
    version_tuple(tag)
    with urllib.request.urlopen(urllib.request.Request(REPO+'/releases.atom',headers=HEADERS),timeout=6) as response:
        feed=ET.fromstring(response.read(2*1024*1024))
    ns={'a':'http://www.w3.org/2005/Atom'}; body=''
    for entry in feed.findall('a:entry',ns):
        link=entry.find('a:link',ns)
        if link is not None and link.get('href','').endswith('/'+tag):
            parser=TextExtractor(); parser.feed(entry.findtext('a:content','',ns)); body=parser.text(); break
    with urllib.request.urlopen(urllib.request.Request(REPO+'/releases/expanded_assets/'+tag,headers=HEADERS),timeout=6) as response:
        page=response.read(2*1024*1024).decode('utf-8')
    assets=[]
    for suffix in ('-win64.zip','-Setup-win64.exe'):
        name='BounceMusic-'+tag+suffix
        parser=AssetExtractor(name); parser.feed(page)
        if parser.path and parser.digest:
            assets.append({'name':name,'browser_download_url':'https://github.com'+parser.path,'digest':parser.digest,'size':0})
    return {'tag_name':tag,'body':body,'assets':assets}

def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    if not match: raise ValueError('版本号格式不受支持')
    return tuple(map(int, match.groups()))

def latest_release():
    mailbox=queue.Queue()
    def api():
        with urllib.request.urlopen(urllib.request.Request(API,headers=HEADERS),timeout=6) as response: return json.load(response)
    def work(fetch):
        try:
            release=fetch(); version_tuple(release.get('tag_name',''))
            if release.get('draft') or release.get('prerelease'): raise ValueError('此版本不是正式版')
            mailbox.put((release,None))
        except Exception as error: mailbox.put((None,error))
    threading.Thread(target=work,args=(api,),daemon=True).start()
    received=0; errors=[]
    try:
        release,error=mailbox.get(timeout=.8); received=1
        if release: return release
        errors.append(str(error))
    except queue.Empty: pass
    # Both channels remain on GitHub; a slow API no longer blocks the webpage fallback.
    threading.Thread(target=work,args=(release_from_web,),daemon=True).start()
    deadline=time.monotonic()+20
    while received<2 and time.monotonic()<deadline:
        try: release,error=mailbox.get(timeout=max(.01,deadline-time.monotonic()))
        except queue.Empty: break
        received+=1
        if release: return release
        errors.append(str(error))
    raise RuntimeError('无法获取官方更新信息：'+('；'.join(errors) or '请求超时'))

def release_asset(release, setup=False):
    name = 'BounceMusic-' + release['tag_name'] + ('-Setup-win64.exe' if setup else '-win64.zip')
    for asset in release.get('assets', []):
        if asset.get('name') != name: continue
        url=asset.get('browser_download_url','')
        parsed=urlparse(url)
        digest=asset.get('digest','') or ''
        if parsed.scheme != 'https' or parsed.hostname != 'github.com' or not parsed.path.startswith('/Aoineko-UwU/BounceMusic/releases/download/'):
            raise ValueError('更新下载地址无效')
        if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest):
            raise ValueError('更新包没有可验证的 SHA-256 校验值')
        return asset
    raise ValueError('发布页没有找到 Windows x64 '+('安装器' if setup else '便携包'))

def prepare_update(release, setup=False, progress=None, control=None,route='auto',route_tests=None,fallback=True):
    asset=release_asset(release,setup)
    expected_size=int(asset.get('size',0))
    if not 0 <= expected_size <= 500*1024*1024: raise ValueError('更新包大小不正确')
    stage=Path(tempfile.mkdtemp(prefix='BounceMusic-update-'))
    try:
        archive=stage/('setup.exe' if setup else 'update.zip')
        download_asset(asset,archive,progress,control,route,route_tests,fallback)
        size=archive.stat().st_size; total=size
        if setup: return str(stage)
        if progress: progress('extract',size,total)
        extracted=stage/'files'; extracted.mkdir()
        with zipfile.ZipFile(archive) as package:
            total=0
            for item in package.infolist():
                if control: control.checkpoint()
                name=item.filename.replace('\\','/')
                path=PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or ':' in name or not path.parts:
                    raise ValueError('更新包包含不安全路径')
                total+=item.file_size
                if total>1024*1024*1024: raise ValueError('解压后的更新包过大')
            package.extractall(extracted)
        if control: control.checkpoint()
        if not (extracted/'BounceMusic.exe').is_file() or not (extracted/'_internal').is_dir():
            raise ValueError('更新包缺少程序文件')
        archive.unlink()
        return str(stage)
    except Exception:
        shutil.rmtree(stage,ignore_errors=True)
        raise

def launch_updater(stage, install_dir, pid, setup=False):
    if not getattr(sys,'frozen',False): raise RuntimeError('源码运行模式请从发布页下载更新')
    helper=Path(sys._MEIPASS)/'updater.ps1'
    if not helper.is_file(): raise FileNotFoundError('更新组件不存在')
    # Copy out of the installation tree before it is replaced.
    script=Path(stage)/'updater.ps1'; shutil.copy2(helper,script)
    args=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                      '-File',str(script),'-Stage',stage,'-Install',install_dir,'-AppPid',str(pid)]
    if setup: args.append('-SetupMode')
    subprocess.Popen(args,
                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
