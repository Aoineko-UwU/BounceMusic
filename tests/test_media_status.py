import sys
import threading
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from media_status import MediaMonitor, source_matches

def test_session_is_bound_to_selected_player():
    assert source_matches('C:\\Apps\\CloudMusic.exe','cloudmusic.exe')
    assert source_matches('Tencent.QQMusic.Player','QQMusic.exe')
    assert not source_matches('Tencent.QQMusic.Player','cloudmusic.exe')
    assert not source_matches('Google.Chrome','chrome.exe')

def test_expired_session_falls_back_to_audio():
    monitor=MediaMonitor.__new__(MediaMonitor)
    monitor.lock=threading.Lock()
    monitor.value={'state':'paused','track':None,'observed':time.monotonic()}
    assert monitor.snapshot()['state']=='paused'
    monitor.value['observed']-=5
    assert monitor.snapshot() is None

if __name__=='__main__':
    test_session_is_bound_to_selected_player()
    test_expired_session_falls_back_to_audio()
    print('Media status checks passed.')
