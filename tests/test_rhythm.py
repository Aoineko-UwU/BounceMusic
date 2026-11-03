"""Synthetic drum pattern regression checks. Run on Windows with requirements.txt installed."""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app import BeatTracker

RATE = 48_000
CHUNK = 1024

def render(duration=28, bpm=120):
    samples = np.zeros(RATE * duration, dtype=np.float32)
    for beat in np.arange(.5, duration - .5, 60 / bpm):
        i = int(beat * RATE)
        t = np.arange(2500)
        samples[i:i + len(t)] += .75 * np.sin(2 * np.pi * 95 * t / RATE) * np.exp(-t / 420)
    # A weak offbeat midrange accent should not pull the fixed grid away from the bass drum.
    for beat in np.arange(.75, duration - .5, 1.):
        i = int(beat * RATE)
        t = np.arange(2500)
        samples[i:i + len(t)] += .18 * np.sin(2 * np.pi * 400 * t / RATE) * np.exp(-t / 400)
    return samples

def analyze(mode):
    tracker = BeatTracker(); tracker.mode = mode
    events, locks = [], []
    previous = 0
    signal = render()
    for i in range(0, len(signal) - CHUNK, CHUNK):
        bpm, _, beat, _, _, _ = tracker.feed(signal[i:i + CHUNK], i / RATE)
        if tracker.just_locked:
            locks.append(bpm)
        if beat and beat != previous:
            events.append(beat); previous = beat
    return tracker, events, locks

def test_fixed_grid():
    tracker, events, locks = analyze('fixed')
    assert 115 < tracker.bpm < 125
    assert len(locks) == 1
    late = [event for event in events if event > 12]
    assert len(late) > 15
    errors = [abs(((event - .5 + .25) % .5) - .25) for event in late]
    assert np.median(errors) < .08

def test_dynamic_responds_to_more_transients():
    _, fixed, _ = analyze('fixed')
    _, dynamic, _ = analyze('dynamic')
    assert len(dynamic) > len(fixed)

def test_configured_speed_limit():
    signal = render(bpm=140)
    counts = []
    for limit in (100, 200):
        tracker = BeatTracker(fast_bpm_threshold=limit)
        tracker.mode = 'fixed'
        previous = 0
        hits = []
        for i in range(0, len(signal) - CHUNK, CHUNK):
            beat = tracker.feed(signal[i:i + CHUNK], i / RATE)[2]
            if beat and beat != previous:
                hits.append(beat)
                previous = beat
        counts.append(len([beat for beat in hits if beat > 12]))
    assert counts[1] > counts[0] * 1.5

if __name__ == '__main__':
    test_fixed_grid()
    test_dynamic_responds_to_more_transients()
    test_configured_speed_limit()
    print('Rhythm checks passed.')
