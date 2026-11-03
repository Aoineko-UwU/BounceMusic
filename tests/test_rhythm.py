"""Synthetic drum pattern regression checks. Run on Windows with requirements.txt installed."""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app import BeatTracker, learned_octave_bias

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

def analyze(tempo=120):
    tracker = BeatTracker()
    events, locks = [], []
    previous = 0
    signal = render(bpm=tempo)
    for i in range(0, len(signal) - CHUNK, CHUNK):
        bpm, _, beat, _, _, _ = tracker.feed(signal[i:i + CHUNK], i / RATE)
        if tracker.just_locked:
            locks.append(bpm)
        if beat and beat != previous:
            events.append(beat); previous = beat
    return tracker, events, locks

def test_fixed_grid():
    tracker, events, locks = analyze()
    assert 115 < tracker.bpm < 125
    assert len(locks) == 1
    late = [event for event in events if event > 12]
    assert len(late) > 15
    errors = [abs(((event - .5 + .25) % .5) - .25) for event in late]
    assert np.median(errors) < .08

def test_distinct_songs_keep_independent_tempo():
    for tempo in (90, 120, 140, 180):
        tracker, _, locks = analyze(tempo)
        assert abs(tracker.bpm-tempo)<tempo*.08, (tempo,tracker.bpm)
        assert len(locks)==1

def test_configured_speed_limit():
    signal = render(bpm=140)
    counts = []
    for limit in (100, 200):
        tracker = BeatTracker(fast_bpm_threshold=limit)
        previous = 0
        hits = []
        for i in range(0, len(signal) - CHUNK, CHUNK):
            beat = tracker.feed(signal[i:i + CHUNK], i / RATE)[2]
            if beat and beat != previous:
                hits.append(beat)
                previous = beat
        counts.append(len([beat for beat in hits if beat > 12]))
    assert counts[1] > counts[0] * 1.5

def test_end_silence_threshold_and_reference_bpm():
    tracker = BeatTracker(end_silence=2.)
    tracker.bpm = 120.
    tracker.feed(np.ones(CHUNK, dtype=np.float32) * .01, 1.)
    assert not tracker.feed(np.zeros(CHUNK, dtype=np.float32), 2.9)[4]
    assert tracker.feed(np.zeros(CHUNK, dtype=np.float32), 3.1)[4]
    assert tracker.ended_bpm == 120.

def test_feedback_needs_repeated_evidence():
    examples=[{'estimated':120,'actual':60,'source':'feedback'}]*3
    assert learned_octave_bias(examples)==0
    examples.append({'estimated':120,'actual':60,'source':'feedback'})
    assert learned_octave_bias(examples)==-1
    examples.append({'estimated':90,'actual':90,'source':'feedback'})
    assert learned_octave_bias(examples)==-1
    examples.extend([{'estimated':100,'actual':100,'source':'feedback'}]*3)
    assert learned_octave_bias(examples)==0

def test_manual_lock_keeps_current_song_tempo():
    tracker=BeatTracker()
    signal=render()
    for i in range(0, len(signal)//2, CHUNK):
        tracker.feed(signal[i:i+CHUNK],i/RATE)
    assert tracker.bpm>0
    tracker.manual_bpm=110.; tracker.bpm=110.; tracker.align_phase(14.)
    for i in range(len(signal)//2, len(signal)-CHUNK, CHUNK):
        tracker.feed(signal[i:i+CHUNK],i/RATE)
    assert tracker.bpm==110.

if __name__ == '__main__':
    test_fixed_grid()
    test_distinct_songs_keep_independent_tempo()
    test_configured_speed_limit()
    test_end_silence_threshold_and_reference_bpm()
    test_feedback_needs_repeated_evidence()
    test_manual_lock_keeps_current_song_tempo()
    print('Rhythm checks passed.')
