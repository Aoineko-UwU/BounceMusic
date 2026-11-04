"""Synthetic drum pattern regression checks. Run on Windows with requirements.txt installed."""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app import BeatTracker, learned_octave_bias, process_capture_supported, local_half_tempo_preference

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

def test_manual_lock_still_corrects_phase():
    tracker=BeatTracker()
    tracker.manual_bpm=120.; tracker.bpm=120.; tracker.phase=.45
    signal=render(duration=10)
    for i in range(0,len(signal)-CHUNK,CHUNK):
        tracker.feed(signal[i:i+CHUNK],i/RATE)
    assert .46 < tracker.phase < .52

def test_phase_correction_recovers_large_drift():
    tracker=BeatTracker(phase_correction='high')
    tracker.manual_bpm=120.; tracker.bpm=120.; tracker.phase=.20
    signal=render(duration=18)
    for i in range(0,len(signal)-CHUNK,CHUNK): tracker.feed(signal[i:i+CHUNK],i/RATE)
    error=(tracker.phase+.25)%.5-.25
    assert abs(error)<.06, error

def test_windows_capture_capability():
    assert not process_capture_supported(19045)
    assert process_capture_supported(22000)

def test_tempo_changes_are_corrected_gradually():
    signal=np.concatenate((render(duration=28,bpm=120),render(duration=40,bpm=140)))
    tracker=BeatTracker(bpm_correction='high',phase_correction='high')
    for i in range(0,len(signal)-CHUNK,CHUNK):
        tracker.feed(signal[i:i+CHUNK],i/RATE)
    assert 128 < tracker.bpm < 145, tracker.bpm
    assert tracker.correction_interval('low') > tracker.correction_interval('medium') > tracker.correction_interval('high')
    assert tracker.correction_interval('low',True) > tracker.correction_interval('high',True)

def test_subdivision_does_not_double_slow_songs_or_halve_fast_songs():
    for tempo in (60,80,90,120,160,180):
        signal=np.zeros(RATE*27,dtype=np.float32)
        t=np.arange(2600); click=np.sin(2*np.pi*95*t/RATE)*np.exp(-t/400)
        for beat in np.arange(.5,25,60/tempo):
            i=round(beat*RATE); j=round((beat+30/tempo)*RATE)
            signal[i:i+len(t)]+=.8*click; signal[j:j+len(t)]+=.4*click
        tracker=BeatTracker()
        for i in range(0,len(signal)-CHUNK,CHUNK): tracker.feed(signal[i:i+CHUNK],i/RATE)
        assert abs(tracker.bpm-tempo) < tempo*.08, (tempo,tracker.bpm)

def test_personalized_octave_evidence_is_local_and_bounded():
    examples=[{'estimated':160,'actual':80}]*3
    assert local_half_tempo_preference(examples,160)
    assert not local_half_tempo_preference(examples,100)
    assert not local_half_tempo_preference(examples[:1],160)
    assert not local_half_tempo_preference(examples+[{'estimated':160,'actual':160}]*8,160)

def test_media_pause_clock_shifts_phase_without_changing_tempo():
    tracker=BeatTracker(); tracker.bpm=120; tracker.phase=10.; tracker.last_signal=10.5
    tracker.onsets.append((10.25,1.))
    tracker.shift_clock(5.)
    assert tracker.bpm==120 and tracker.phase==15. and tracker.last_signal==15.5
    assert tracker.onsets[0][0]==15.25

if __name__ == '__main__':
    test_fixed_grid()
    test_distinct_songs_keep_independent_tempo()
    test_configured_speed_limit()
    test_end_silence_threshold_and_reference_bpm()
    test_feedback_needs_repeated_evidence()
    test_manual_lock_keeps_current_song_tempo()
    test_manual_lock_still_corrects_phase()
    test_phase_correction_recovers_large_drift()
    test_windows_capture_capability()
    test_tempo_changes_are_corrected_gradually()
    test_subdivision_does_not_double_slow_songs_or_halve_fast_songs()
    test_personalized_octave_evidence_is_local_and_bounded()
    test_media_pause_clock_shifts_phase_without_changing_tempo()
    print('Rhythm checks passed.')
