"""Optional read-only Windows media-session status for the selected music player."""
import asyncio
import threading
import time

def source_matches(source_id, process_name):
    name=(process_name or '').lower().removesuffix('.exe')
    identity=(source_id or '').lower()
    aliases={'cloudmusic':('cloudmusic','netease','ncm'), 'qqmusic':('qqmusic','qq音乐')}
    return name in aliases and any(alias in identity for alias in aliases[name])

class MediaMonitor:
    def __init__(self, process_name):
        self.process_name=process_name
        self.running=True; self.lock=threading.Lock(); self.value=None
        self.thread=threading.Thread(target=self.run,daemon=True); self.thread.start()
    def stop(self): self.running=False
    def snapshot(self):
        with self.lock: value=self.value
        return value if value and time.monotonic()-value['observed']<3 else None
    def run(self):
        try: asyncio.run(self.poll())
        except Exception:
            with self.lock: self.value=None
    async def poll(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
        manager=await Manager.request_async()
        while self.running:
            try:
                sessions=[session for session in manager.get_sessions() if source_matches(session.source_app_user_model_id,self.process_name)]
                session=next((s for s in sessions if s.get_playback_info().playback_status==Status.PLAYING),sessions[0] if sessions else None)
                value=None
                if session:
                    status=session.get_playback_info().playback_status
                    state={Status.PLAYING:'playing',Status.PAUSED:'paused',Status.STOPPED:'stopped'}.get(status)
                    if state:
                        title=''; artist=''
                        try:
                            props=await asyncio.wait_for(session.try_get_media_properties_async(),2.)
                            title=(props.title or '').strip(); artist=(props.artist or '').strip()
                        except Exception: pass
                        value={'state':state,'track':(title,artist) if title else None,'observed':time.monotonic()}
                with self.lock: self.value=value
            except Exception:
                with self.lock: self.value=None
            await asyncio.sleep(.5)
