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
    def __init__(self,pid,on_data): self.on_data=on_data; self.running=True
    def start(self):
        def work():
            samples=np.full(2048,.03,dtype=np.float32).tobytes()
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
            monitor.state='playing'; time.sleep(.2); monitor.track=('Song B','Artist'); time.sleep(.3)
            while not events.empty(): captured.append(events.get_nowait())
            assert sum(kind=='song_end' for kind,_ in captured)==1
            assert any(kind=='song_changed' for kind,_ in captured)
        finally:
            analyzer.stop(); analyzer.thread.join(timeout=2)

if __name__=='__main__':
    test_pause_is_not_song_end_and_track_change_is()
    print('Analyzer media checks passed.')
