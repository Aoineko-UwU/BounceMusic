"""Exercise player pause and song change using simulated audio and media state."""
import queue
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import app

class FakeMedia:
    def __init__(self): self.state='playing'; self.track=('Song A','Artist')
    def snapshot(self): return {'state':self.state,'track':self.track}
    def stop(self): pass

class FakeTap:
    level=.03
    def __init__(self,pid,on_data): self.on_data=on_data; self.running=True; FakeTap.latest=self
    def start(self):
        def work():
            samples=np.full(2048,self.level,dtype=np.float32).tobytes()
            while self.running:
                self.on_data(samples,1024); time.sleep(.02)
        threading.Thread(target=work,daemon=True).start()
    def close(self): self.running=False

class LockedTracker(app.BeatTracker):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.bpm=120.; self.phase=time.monotonic()

def test_pause_is_not_song_end_and_track_change_is():
    monitor=FakeMedia(); events=queue.Queue()
    with patch.object(app,'MediaMonitor',return_value=monitor),patch.object(app,'ProcessAudioCapture',FakeTap),patch.object(app,'BeatTracker',LockedTracker):
        analyzer=app.Analyzer(('process',(123,'cloudmusic.exe')),events,end_silence=.2)
        try:
            time.sleep(.2); monitor.state='paused'; time.sleep(.5)
            captured=[]
            while not events.empty(): captured.append(events.get_nowait())
            assert not any(kind=='song_end' for kind,_ in captured)
            assert not analyzer.is_playing()
            assert not analyzer.has_ended()
            monitor.state='playing'; time.sleep(.2); monitor.track=('Song B','Artist'); time.sleep(.3)
            while not events.empty(): captured.append(events.get_nowait())
            assert sum(kind=='song_end' for kind,_ in captured)==1
            assert any(kind=='song_changed' for kind,_ in captured)
            monitor.state='stopped'; time.sleep(.3)
            assert analyzer.has_ended() and not analyzer.is_playing()
            monitor.state='playing'; time.sleep(.3)
            assert not analyzer.has_ended()
        finally:
            analyzer.stop(); analyzer.thread.join(timeout=2)


def wait_until(predicate):
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(.02)
    assert predicate()


def test_confirmed_end_without_locked_bpm():
    events=queue.Queue()
    with patch.object(app,'ProcessAudioCapture',FakeTap):
        analyzer=app.Analyzer(('process',(123,'player.exe')),events,end_silence=.25)
        try:
            wait_until(lambda:analyzer.has_started)
            assert not analyzer.has_ended() and analyzer.values()[0]==0.
            FakeTap.latest.running=False
            time.sleep(.1); assert not analyzer.has_ended()
            wait_until(analyzer.has_ended)
            assert not analyzer.is_playing()
        finally: analyzer.stop(); analyzer.thread.join(timeout=2)
    class SilentTap(FakeTap): level=0.
    with patch.object(app,'ProcessAudioCapture',SilentTap):
        analyzer=app.Analyzer(('process',(123,'player.exe')),queue.Queue(),end_silence=.2)
        try:
            time.sleep(.5)
            assert not analyzer.has_started and not analyzer.has_ended()
        finally: analyzer.stop(); analyzer.thread.join(timeout=2)
    monitor=FakeMedia(); monitor.state='stopped'
    with patch.object(app,'MediaMonitor',return_value=monitor),patch.object(app,'ProcessAudioCapture',FakeTap):
        analyzer=app.Analyzer(('process',(123,'cloudmusic.exe')),queue.Queue(),end_silence=.2)
        try:
            wait_until(analyzer.has_ended)
            assert analyzer.values()[0]==0.
            monitor.state='paused'; wait_until(lambda:not analyzer.has_ended())
        finally: analyzer.stop(); analyzer.thread.join(timeout=2)

if __name__=='__main__':
    test_pause_is_not_song_end_and_track_change_is()
    test_confirmed_end_without_locked_bpm()
    print('Analyzer media checks passed.')
