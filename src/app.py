import os, sys, time, threading, queue, json, math, traceback
import ctypes, webbrowser
import re
from collections import deque, OrderedDict
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import numpy as np
import pyaudiowpatch as pa
import pystray
import psutil
from pycaw.pycaw import AudioUtilities, AudioSession, IAudioSessionControl2
import comtypes
from proctap import ProcessAudioCapture
from PIL import Image, ImageDraw, ImageTk, ImageOps, ImageSequence, ImageFont
import updater
from media_status import MediaMonitor

BASE = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, '设置.json')
KEY = '#ff00ff'
MAX_IMAGE_SIDE = 900
ASSET_BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOADING_GIF = os.path.join(ASSET_BASE, 'assets', 'Loading.gif')
APP_ICON = os.path.join(ASSET_BASE, 'assets', 'icon.ico')
MATOU_IMAGE = os.path.join(ASSET_BASE, 'assets', 'matou.png')
VERSION = '1.6.1'
AUTHOR = '葵猫猫'

def acquire_single_instance():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, 'Local\\BounceMusic-Desktop-SingleInstance')
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(ctypes.c_void_p(handle))
        return None
    return handle

def center_window(window, width=None, height=None):
    window.update_idletasks()
    width = width or window.winfo_reqwidth()
    height = height or window.winfo_reqheight()
    x = max(0, (window.winfo_screenwidth()-width)//2)
    y = max(0, (window.winfo_screenheight()-height)//2)
    window.geometry(f'{width}x{height}+{x}+{y}')

def render_release_notes(widget, body):
    """Render the common release-note Markdown without executing embedded content."""
    widget.tag_configure('heading', font=('Microsoft YaHei UI', 11, 'bold'), spacing1=10, spacing3=5)
    widget.tag_configure('bullet', lmargin1=12, lmargin2=30, spacing3=5)
    widget.tag_configure('paragraph', spacing3=5)
    widget.tag_configure('bold', font=('Microsoft YaHei UI', 10, 'bold'))
    widget.tag_configure('link', foreground='#1681d4', underline=True)
    inline = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`')
    def insert_inline(line):
        position=0
        for match in inline.finditer(line):
            widget.insert('end',line[position:match.start()])
            if match.group(1):
                tag='release_link_'+str(match.start())+'_'+str(widget.index('end-1c')).replace('.','_')
                widget.insert('end',match.group(1),('link',tag))
                url=match.group(2)
                widget.tag_bind(tag,'<Button-1>',lambda event, target=url:webbrowser.open(target))
            else: widget.insert('end',match.group(3) or match.group(4),'bold')
            position=match.end()
        widget.insert('end',line[position:])
    for line in (body or '该版本未提供更新说明。').splitlines():
        heading=re.match(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$',line)
        bullet=re.match(r'^\s*[-*+]\s+(.+)$',line)
        start=widget.index('end-1c')
        if heading: insert_inline(heading.group(1)); tag='heading'
        elif bullet: widget.insert('end','•  '); insert_inline(bullet.group(1)); tag='bullet'
        else: insert_inline(line); tag='paragraph'
        widget.insert('end','\n')
        widget.tag_add(tag,start,'end-1c')
    widget.config(state='disabled')

def amplitude_from_config(config):
    if 'amplitude' not in config: return 100.
    value=float(config['amplitude'])
    if config.get('amplitude_scale_version') != 2: value /= 1.25
    return max(50.,min(150.,value))

def animation_amplitude(value):
    return max(.625,min(1.875,float(value)*.0125))

def set_window_icon(window):
    try: window.iconbitmap(APP_ICON)
    except tk.TclError: pass

def slime():
    im = Image.new('RGBA', (360, 320)); d = ImageDraw.Draw(im)
    d.ellipse((20, 36, 340, 306), fill=(89, 207, 214, 255), outline=(28, 141, 158, 255), width=7)
    d.ellipse((82, 70, 210, 118), fill=(188, 250, 244, 170))
    d.ellipse((105, 148, 127, 183), fill=(29, 71, 86, 255)); d.ellipse((232, 148, 254, 183), fill=(29, 71, 86, 255))
    d.arc((150, 150, 210, 211), 10, 170, fill=(29, 71, 86, 255), width=5)
    d.ellipse((68, 190, 107, 209), fill=(255, 150, 171, 160)); d.ellipse((253, 190, 292, 209), fill=(255, 150, 171, 160))
    return im

def devices():
    p = pa.PyAudio()
    try: return [(d['index'], d['name'], int(d['maxInputChannels']), int(d['defaultSampleRate'])) for d in p.get_loopback_device_info_generator()]
    finally: p.terminate()

def processes():
    found = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            name = proc.info['name'] or ''
            if name.lower().endswith('.exe') and proc.pid != os.getpid():
                found.append((proc.pid, name))
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    return sorted(found, key=lambda p: (p[1].lower(), p[0]))

def process_capture_supported(build=None):
    build=sys.getwindowsversion().build if build is None else build
    return build>=20348

def learned_octave_bias(examples):
    votes={-1:0.,0:0.,1:0.}
    for example in examples[-50:]:
        try:
            ratio=float(example['actual'])/float(example['estimated'])
            octave=math.log2(ratio)
        except (KeyError, TypeError, ValueError, ZeroDivisionError): continue
        rounded=round(octave)
        if rounded in votes and abs(octave-rounded)<.12:
            votes[rounded]+=1. if example.get('source')=='feedback' else .3
    total=sum(votes.values())
    for direction in (-1,1):
        if votes[direction]>=4 and votes[direction]>=.75*total:
            return direction
    return 0

def local_half_tempo_preference(examples, tempo):
    """Use nearby, explicitly supplied examples only to resolve an ambiguous octave."""
    half=0.; same=0.
    for sample in examples[-50:]:
        try:
            estimated=float(sample['estimated']); actual=float(sample['actual'])
            if not (40<=estimated<=300 and 40<=actual<=300): continue
            weight=math.exp(-.5*((estimated-tempo)/14.)**2)
            ratio=actual/estimated
            if .43<=ratio<=.58: half+=weight
            elif .87<=ratio<=1.13: same+=weight
        except (KeyError,TypeError,ValueError,ZeroDivisionError): continue
    return half>=2.5 and (half+.4)/(half+same+.8)>=.52

class BeatTracker:
    def __init__(self, rate=48000, chunk=1024, analysis_bias=1.0, fast_bpm_threshold=190, end_silence=3.5, octave_bias=0, bpm_correction='auto', phase_correction='auto', examples=None):
        self.rate, self.chunk, self.analysis_bias = rate, chunk, analysis_bias
        self.fast_bpm_threshold=fast_bpm_threshold
        self.end_silence=end_silence
        self.octave_bias=octave_bias
        self.examples=list(examples or [])
        self.bpm_correction=bpm_correction; self.phase_correction=phase_correction
        self.last_tempo_check=0.; self.last_phase_adjust=0.
        self.flux = deque(maxlen=int(20*rate/chunk)); self.history = deque(maxlen=48)
        self.high_flux = deque(maxlen=int(20*rate/chunk))
        self.prev = None; self.bpm = 0.; self.level = 0.; self.beat = 0.; self.phase = 0.
        self.last_onset = 0.; self.steps = 0; self.prev_flux = 0.; self.prev_prev_flux = 0.; self.prev_threshold = float('inf')
        self.tempo_candidates = deque(maxlen=6); self.onsets = deque(maxlen=96)
        self.last_signal = 0.; self.last_visual = -1e9; self.last_grid = None
        self.just_locked = False; self.manual_bpm = 0.
        self.octave_uncertain=False
        self.shape_target = .12; self.shape = .12; self.beat_strength = .8; self.last_time = 0.; self.song_end = False
        self.ended_bpm = 0.
    def correction_interval(self, setting, phase=False):
        intervals = {'low': (20., 4.), 'medium': (10., 1.5), 'high': (4., .35)}
        if setting in intervals: return intervals[setting][int(phase)]
        times=[t for t,_ in self.onsets][-12:]
        if len(times)<6: return 10. if not phase else 1.5
        gaps=np.diff(times)
        variation=float(np.std(gaps)/max(.001,np.mean(gaps)))
        level='high' if variation>.25 else ('medium' if variation>.10 else 'low')
        return intervals[level][int(phase)]
    def feed(self, x, now):
        self.just_locked = False
        dt = min(.2, max(.001, now-self.last_time)) if self.last_time else .02
        self.last_time = now
        rms = float(np.sqrt(np.mean(x*x))) if len(x) else 0.
        self.level = max(min(1., rms*7), self.level*.94)
        if rms > .001:
            self.last_signal = now; self.song_end = False
        elif self.last_signal and now-self.last_signal > self.end_silence:
            self.song_end = True
            self.ended_bpm = self.bpm
            self.bpm=0.; self.flux.clear(); self.high_flux.clear(); self.history.clear(); self.tempo_candidates.clear(); self.last_signal=0.
            self.manual_bpm=0.
            self.phase=0.; self.last_grid=None; self.onsets.clear()
            self.last_tempo_check=0.; self.last_phase_adjust=0.
            self.octave_uncertain=False
            self.shape_target=.12
        # Slowly return toward a slender, tall resting shape between accents.
        self.shape_target += (.12-self.shape_target) * min(1., dt*1.8)
        self.shape += (self.shape_target-self.shape) * min(1., dt*12.)
        spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)))) if len(x) else np.zeros(1)
        high_value=0.
        if self.prev is None: value = 0.
        else:
            delta = np.maximum(spectrum-self.prev, 0)
            frequencies = np.fft.rfftfreq(len(x), 1/self.rate)
            low = delta[(frequencies >= 40) & (frequencies < 160)]
            mid = delta[(frequencies >= 160) & (frequencies < 1500)]
            high = delta[(frequencies >= 2500) & (frequencies < 10000)]
            value = float((low.mean() if len(low) else 0)*.8 + (mid.mean() if len(mid) else 0)*.2)
            high_value=float(high.mean()) if len(high) else 0.
        self.prev = spectrum
        threshold = max(.012, float(np.mean(self.history)) + 1.15*float(np.std(self.history))) * self.analysis_bias if len(self.history)>10 else float('inf')
        peak_flux, peak_threshold = self.prev_flux, self.prev_threshold
        onset = (peak_flux > self.prev_prev_flux and peak_flux >= value and
                 peak_flux > peak_threshold and now-self.last_onset > .18 and self.level > .008)
        self.prev_prev_flux, self.prev_flux, self.prev_threshold = peak_flux, value, threshold
        self.history.append(value); self.flux.append(value); self.high_flux.append(high_value); self.steps += 1
        if onset:
            self.last_onset = now
            strength = float(np.clip((peak_flux-peak_threshold)/(peak_threshold+1e-6), 0., 3.))
            onset_time=now-self.chunk/self.rate
            self.onsets.append((onset_time, strength))
            # 0 = slender/tall, 1 = broad/flat. Keep this as a continuous state.
            self.shape_target = float(np.clip(.18 + .82*(strength/3.), .18, 1.))
            if self.bpm and self.phase:
                period = 60/self.bpm
                error = (onset_time-self.phase+period/2) % period-period/2
                if abs(error) < min(.09, period*.18) and strength > .35 and now-self.last_phase_adjust >= self.correction_interval(self.phase_correction,True):
                    self.phase += error*.12
                    self.last_phase_adjust=now
        check_tempo = (not self.bpm and self.steps % max(1, int(1.5*self.rate/self.chunk)) == 0 or
                       self.bpm and not self.manual_bpm and now-self.last_tempo_check >= self.correction_interval(self.bpm_correction))
        if check_tempo and len(self.flux)>6*self.rate/self.chunk:
            self.last_tempo_check=now
            v = np.asarray(self.flux); v = v - v.mean(); corr = np.correlate(v, v, mode='full')[len(v)-1:]
            nfft=4096
            rhythm=np.abs(np.fft.rfft(v*np.hanning(len(v)),n=nfft))
            rhythm_freq=np.fft.rfftfreq(nfft,self.chunk/self.rate)
            hv=np.asarray(self.high_flux); hv=hv-hv.mean()
            high_rhythm=np.abs(np.fft.rfft(hv*np.hanning(len(hv)),n=nfft))
            lo=math.ceil(60*self.rate/(220*self.chunk)); hi=min(len(corr)-2,math.floor(60*self.rate/(55*self.chunk)))
            if hi>lo and corr[0]>.0001:
                lags=np.arange(lo,hi+1); tempos=60*self.rate/(lags*self.chunk)
                weights=np.exp(-.5*(np.log2(tempos/120)/.9)**2)
                score=corr[lo:hi+1]*weights
                periodicity=np.interp(tempos/60,rhythm_freq,rhythm)+1.1*np.interp(tempos/120,rhythm_freq,rhythm)
                score *= .1+.9*periodicity/max(1e-9,float(periodicity.max()))
                if self.bpm:
                    score *= .65 + .35*np.exp(-.5*(np.log2(tempos/self.bpm)/.18)**2)
                if len(self.onsets)>=8:
                    recent_times=np.array([t for t,_ in self.onsets if now-t<12])
                    if len(recent_times)>=8:
                        intervals=np.diff(recent_times)
                        if len(intervals):
                            periods=60/tempos
                            support=np.exp(-.5*((intervals[:,None]-periods[None,:])/(periods[None,:]*.16))**2).mean(axis=0)
                            score*=.55+.9*support
                lag=lo+int(np.argmax(score))
                # A three-beat cycle can otherwise win over a stronger two-beat pulse.
                faster_lag=round(lag*2/3)
                if not self.bpm and 60*self.rate/(lag*self.chunk)<100 and lo<=faster_lag<=hi:
                    candidate_range=range(max(lo,faster_lag-1),min(hi,faster_lag+1)+1)
                    faster_lag=max(candidate_range,key=lambda n:score[n-lo])
                    if (score[faster_lag-lo]>=.75*score[lag-lo] and
                            periodicity[faster_lag-lo]>1.25*periodicity[lag-lo]):
                        lag=faster_lag
                tempo=60*self.rate/(lag*self.chunk)
                half_lag=round(lag*2)
                if not self.bpm and tempo>=115 and half_lag<=hi and corr[lag]>0:
                    window_start=max(lo,half_lag-3); window_end=min(hi,half_lag+3)
                    half_lag=window_start+int(np.argmax(corr[window_start:window_end+1]))
                    relative=corr[half_lag]/corr[lag]
                    full=float(np.interp(tempo/60,rhythm_freq,rhythm))
                    half=float(np.interp(tempo/120,rhythm_freq,rhythm))
                    accent=half/max(full,1e-9)
                    high_full=float(np.interp(tempo/60,rhythm_freq,high_rhythm))
                    high_half=float(np.interp(tempo/120,rhythm_freq,high_rhythm))
                    high_support=(high_full>1.15*max(high_half,1e-9) and
                                  high_full>.05*max(1e-9,float(high_rhythm.max())) and
                                  float(np.mean(self.high_flux))>.01*max(1e-9,float(np.mean(self.flux))))
                    learned=local_half_tempo_preference(self.examples,tempo)
                    if relative>=.70 and (accent>=.18 or learned): self.octave_uncertain=True
                    if relative>=.70 and (learned or (accent>=.28 and not high_support)): lag=half_lag
                if self.octave_bias:
                    other=round(lag*(2 if self.octave_bias==-1 else .5))
                    if lo<=other<=hi and score[other-lo]>=.85*score[lag-lo]:
                        lag=other
                ready=not (not self.bpm and self.octave_uncertain and len(v)<14*self.rate/self.chunk)
                if not ready: self.tempo_candidates.clear()
                if ready and corr[lag]/corr[0]>.05:
                    den=corr[lag-1]-2*corr[lag]+corr[lag+1]
                    offset=float(np.clip(.5*(corr[lag-1]-corr[lag+1])/den,-.5,.5)) if den else 0
                    candidate=60*self.rate/((lag+offset)*self.chunk); self.tempo_candidates.append(candidate)
                    needed=4 if not self.bpm else 3
                    if len(self.tempo_candidates)>=needed:
                        recent=list(self.tempo_candidates)[-needed:]; median=float(np.median(recent))
                        if max(abs(v-median) for v in recent) < median*.06:
                            if not self.bpm:
                                self.bpm=median; self.align_phase(now)
                                self.last_grid=None; self.just_locked=True
                            elif .03 < abs(median-self.bpm)/self.bpm < .20:
                                old_period=60/self.bpm
                                fraction=((now-self.phase)%old_period)/old_period
                                self.bpm += .35*(median-self.bpm)
                                self.phase=now-fraction*60/self.bpm
                                self.last_grid=None
                            self.tempo_candidates.clear()
        if self.bpm and self.phase and self.level > .008 and now-self.last_onset < 2:
            # At fast tempos use every other grid beat so one full squash cycle can finish.
            stride = max(1,math.ceil(self.bpm/self.fast_bpm_threshold))
            interval = stride*60/self.bpm
            index = math.floor((now-self.phase)/interval)
            if index >= 0 and index != self.last_grid:
                grid_time = self.phase+index*interval
                if 0 <= now-grid_time < .09 and grid_time-self.last_visual >= 60/self.fast_bpm_threshold:
                    self.beat=grid_time; self.last_visual=grid_time
                    self.beat_strength=.8; self.last_grid=index
        return self.bpm, self.level, self.beat, float(np.clip(self.shape, .05, 1.0)), self.song_end, self.beat_strength

    def align_phase(self, now):
        period=60/self.bpm
        recent=[(t,s) for t,s in self.onsets if now-t < 12]
        if not recent: self.phase=now; return
        # The stronger low-frequency onsets carry more weight than vocals and hi-hats.
        strengths=np.array([s for _,s in recent]); cutoff=float(np.quantile(strengths,.55))
        chosen=[(t,s) for t,s in recent if s>=cutoff]
        angles=np.array([2*math.pi*t/period for t,_ in chosen])
        weights=np.array([.5+s for _,s in chosen])
        vector=np.sum(weights*np.exp(1j*angles))
        if abs(vector) < .15*weights.sum(): self.phase=chosen[-1][0]; return
        position=(np.angle(vector)%(2*math.pi))/(2*math.pi)*period
        self.phase=now-((now-position)%period)

    def shift_clock(self, seconds):
        for name in ('last_signal','last_onset','last_time','phase','beat','last_tempo_check','last_phase_adjust'):
            value=getattr(self,name)
            if value: setattr(self,name,value+seconds)
        if self.last_visual > -1e8: self.last_visual+=seconds
        self.onsets=deque(((t+seconds,s) for t,s in self.onsets),maxlen=self.onsets.maxlen)

class Analyzer:
    def __init__(self, source, events, analysis_bias=1.0, fast_bpm_threshold=190, end_silence=3.5, octave_bias=0, bpm_correction='auto', phase_correction='auto', examples=None):
        self.source, self.events, self.analysis_bias = source, events, analysis_bias
        self.fast_bpm_threshold=fast_bpm_threshold; self.end_silence=end_silence; self.octave_bias=octave_bias; self.reset_epoch=0
        self.bpm_correction=bpm_correction; self.phase_correction=phase_correction
        self.examples=list(examples or [])
        self.manual_bpm=0.; self.last_audible=0.; self.auto_estimate=0.
        self.align_epoch=0
        self.media=MediaMonitor(source[1][1]) if source[0]=='process' and source[1][1].lower() in ('cloudmusic.exe','qqmusic.exe') else None
        self.running = True; self.bpm = 0.; self.level = 0.; self.lastbeat = 0.; self.shape = .12; self.beat_strength = .8; self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
    def stop(self):
        self.running = False
        if self.media: self.media.stop()
    def values(self):
        with self.lock: return self.bpm, self.level, self.lastbeat, self.shape, self.beat_strength
    def is_playing(self):
        return bool(self.running and time.monotonic()-self.last_audible < .25)
    def lock_bpm(self, bpm):
        self.manual_bpm=float(bpm)
    def realign(self):
        self.align_epoch+=1
    def run(self):
        p = None; stream = None; tap = None
        try:
            mode, source = self.source; audio_queue = queue.Queue(maxsize=64); chunk=1024
            def push(data):
                try: audio_queue.put_nowait(data)
                except queue.Full: pass
            if mode == 'process':
                pid, name = source; channels=2; rate=48000
                tap = ProcessAudioCapture(pid, on_data=lambda data, frames: push(data))
                tap.start()
            else:
                idx, name, channels, rate = source; p=pa.PyAudio()
                def callback(data, frame_count, time_info, status):
                    push(data); return (None, pa.paContinue)
                stream=p.open(format=pa.paFloat32, channels=channels, rate=rate, input=True, input_device_index=idx, frames_per_buffer=chunk, stream_callback=callback)
            tracker=BeatTracker(rate,chunk,self.analysis_bias,self.fast_bpm_threshold,self.end_silence,self.octave_bias,examples=self.examples); pending=np.empty(0,dtype=np.float32); last_data_time=time.monotonic(); song_end_reported=False; ended_without_data=False; seen_epoch=self.reset_epoch; seen_align=self.align_epoch
            media_track=None; media_stopped=False; paused_at=0.
            self.events.put(('status', '正在监听：' + name))
            while self.running:
                if seen_epoch != self.reset_epoch:
                    seen_epoch=self.reset_epoch; tracker=BeatTracker(rate,chunk,self.analysis_bias,self.fast_bpm_threshold,self.end_silence,self.octave_bias,examples=self.examples)
                    self.manual_bpm=0.; self.last_audible=0.; self.auto_estimate=0.
                    pending=np.empty(0,dtype=np.float32); song_end_reported=False; ended_without_data=False
                    try:
                        while True: audio_queue.get_nowait()
                    except queue.Empty: pass
                    with self.lock: self.bpm=0.; self.lastbeat=0.; self.shape=.12; self.beat_strength=.8
                media=self.media.snapshot() if self.media else None
                if media and media.get('track'):
                    if media_track and media['track'] != media_track:
                        if tracker.bpm and not media_stopped: self.events.put(('song_end', self.auto_estimate or tracker.bpm))
                        self.events.put(('song_changed',None))
                        tracker=BeatTracker(rate,chunk,self.analysis_bias,self.fast_bpm_threshold,self.end_silence,self.octave_bias,examples=self.examples)
                        self.manual_bpm=0.; self.auto_estimate=0.; self.last_audible=0.; self.events.put(('manual_unlock',None))
                        pending=np.empty(0,dtype=np.float32); song_end_reported=False; paused_at=0.; media_stopped=False
                    media_track=media['track']
                state=media.get('state') if media else None
                if state in ('paused','stopped'):
                    if not paused_at: paused_at=time.monotonic()
                    if state=='stopped' and not media_stopped:
                        if tracker.bpm: self.events.put(('song_end',self.auto_estimate or tracker.bpm))
                        tracker=BeatTracker(rate,chunk,self.analysis_bias,self.fast_bpm_threshold,self.end_silence,self.octave_bias,examples=self.examples)
                        self.manual_bpm=0.; self.auto_estimate=0.; self.events.put(('manual_unlock',None)); media_stopped=True
                    self.last_audible=0.
                    with self.lock: self.level=0.; self.lastbeat=0.
                    try: audio_queue.get(timeout=.2)
                    except queue.Empty: pass
                    continue
                if paused_at:
                    tracker.shift_clock(time.monotonic()-paused_at); paused_at=0.; last_data_time=time.monotonic()
                    pending=np.empty(0,dtype=np.float32); media_stopped=False
                try: data=audio_queue.get(timeout=.2)
                except queue.Empty:
                    with self.lock: self.level=0
                    if state!='playing' and not ended_without_data and time.monotonic()-last_data_time > self.end_silence:
                        ended_without_data=True
                        if tracker.bpm > 0 and not song_end_reported:
                            song_end_reported=True; self.events.put(('song_end', self.auto_estimate or tracker.bpm))
                        tracker=BeatTracker(rate,chunk,self.analysis_bias,self.fast_bpm_threshold,self.end_silence,self.octave_bias,examples=self.examples); pending=np.empty(0,dtype=np.float32)
                        self.manual_bpm=0.; self.last_audible=0.; self.auto_estimate=0.; self.events.put(('manual_unlock',None))
                        with self.lock: self.bpm=0.; self.lastbeat=0.; self.shape=.12; self.beat_strength=.8
                    continue
                last_data_time=time.monotonic()
                ended_without_data=False
                x=np.frombuffer(data,dtype=np.float32)
                if len(x)%channels: continue
                x=x.reshape(-1,channels).mean(axis=1); pending=np.concatenate((pending,x))
                while len(pending)>=chunk:
                    frame=pending[:chunk]; pending=pending[chunk:]
                    now=time.monotonic()-len(pending)/rate
                    tracker.analysis_bias=self.analysis_bias
                    tracker.fast_bpm_threshold=self.fast_bpm_threshold
                    tracker.end_silence=float('inf') if state=='playing' else self.end_silence
                    tracker.bpm_correction=self.bpm_correction; tracker.phase_correction=self.phase_correction
                    tracker.examples=self.examples
                    if seen_align != self.align_epoch:
                        seen_align=self.align_epoch
                        if tracker.bpm and any(now-t < 12 for t,_ in tracker.onsets):
                            tracker.align_phase(now); tracker.last_grid=None
                            self.events.put(('status','已根据近期鼓点重新对齐节奏，BPM 保持不变。'))
                        else: self.events.put(('status','近期鼓点不足，暂时无法对齐，请保持音乐播放后重试。'))
                    if self.manual_bpm and tracker.manual_bpm != self.manual_bpm:
                        tracker.manual_bpm=self.manual_bpm; tracker.bpm=self.manual_bpm
                        tracker.align_phase(now); tracker.last_grid=None; tracker.tempo_candidates.clear()
                    if tracker.last_signal and now-tracker.last_signal < .25:
                        self.last_audible=time.monotonic()
                    old_bpm=tracker.bpm
                    bpm,level,beat,shape,song_end,beat_strength=tracker.feed(frame,now)
                    if tracker.last_signal and now-tracker.last_signal < .25:
                        self.last_audible=time.monotonic()
                    with self.lock: self.bpm,self.level,self.lastbeat,self.shape,self.beat_strength=bpm,level,beat,shape,beat_strength
                    if tracker.just_locked and (not old_bpm or abs(bpm-old_bpm)>old_bpm*.09):
                        self.auto_estimate=bpm
                        self.events.put(('bpm_locked', bpm))
                    if song_end and not song_end_reported:
                        song_end_reported=True; self.events.put(('song_end', self.auto_estimate or tracker.ended_bpm))
                        self.manual_bpm=0.; self.last_audible=0.; self.auto_estimate=0.; self.events.put(('manual_unlock',None))
                    elif not song_end:
                        song_end_reported=False
        except Exception as e: self.events.put(('error', '无法监听此音频源：' + str(e)))
        finally:
            if tap:
                try: tap.close()
                except Exception: pass
            if stream:
                try: stream.stop_stream(); stream.close()
                except Exception: pass
            if p: p.terminate()

class SpriteWindow:
    def __init__(self, app, sprite_id, image_path='', size=240, x=800, y=250, loading_x=85, loading_y=12):
        self.app, self.id = app, sprite_id
        self.image_path = image_path
        self.original = app.get_image(image_path)
        self.size = max(100, min(450, int(size)))
        self.loading_x=max(0,min(100,int(loading_x)))
        self.loading_y=max(0,min(100,int(loading_y)))
        self.photo = None
        self.render_key = None
        self.notice_window = None
        self.drag = None
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.configure(bg=KEY)
        self.win.wm_attributes('-transparentcolor', KEY)
        self.win.attributes('-topmost', app.top.get())
        self.label = tk.Label(self.win, bg=KEY, bd=0)
        self.label.pack()
        self.label.bind('<ButtonPress-1>', self.press)
        self.label.bind('<B1-Motion>', self.move)
        self.label.bind('<Double-Button-1>', self.double_click)
        self.label.bind('<Button-3>', self.context_menu)
        self.label.bind('<MouseWheel>', self.wheel)
        self.win.geometry('+%d+%d' % (max(0,int(x)), max(0,int(y))))

    @staticmethod
    def load_image(path):
        if path:
            try:
                with Image.open(path) as image:
                    image.seek(0)
                    image.draft('RGB', (MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
                    result = ImageOps.exif_transpose(image).convert('RGBA')
                    result.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
                    return result
            except Exception:
                pass
        return slime()

    def press(self, event):
        self.app.select_sprite(self.id)
        self.drag = (event.x_root-self.win.winfo_x(), event.y_root-self.win.winfo_y())

    def move(self, event):
        if self.drag:
            self.win.geometry('+%d+%d' % (max(0,event.x_root-self.drag[0]), max(0,event.y_root-self.drag[1])))
    def double_click(self, event):
        if self.app.double_click_close.get():
            self.app.close_sprite(self.id)

    def wheel(self, event):
        self.size = max(100, min(450, self.size + (20 if event.delta > 0 else -20)))
        self.app.select_sprite(self.id)
        self.app.size.set(self.size)
        self.app.save()

    def context_menu(self, event):
        self.app.select_sprite(self.id)
        menu = tk.Menu(self.win, tearoff=False)
        if self.app.theme_mode.get()=='dark':
            menu.configure(bg='#30343d',fg='#f2f3f5',activebackground='#505866',activeforeground='#ffffff')
        menu.add_command(label='打开主菜单', command=self.app.show_main)
        menu.add_command(label='打开设置', command=self.app.show_settings)
        menu.add_command(label='新增Q弹', command=self.app.add_sprite)
        menu.add_command(label='刷新 BPM', command=self.app.refresh_bpm)
        menu.add_command(label='立即对齐节奏', command=self.app.realign_rhythm)
        menu.add_command(label='统一取消置顶' if self.app.top.get() else '统一置顶', command=self.app.toggle_top)
        menu.add_separator()
        menu.add_command(label='关闭图片', command=lambda: self.app.close_sprite(self.id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def render(self, sx, sy, flash, color, loading_index=-1):
        original = self.app.shared_original if self.app.image_mode.get() == 'uniform' else self.original
        side = int(self.size*1.55)
        w0, h0 = original.size
        ratio = self.size / max(w0, h0)
        w = max(1, int(w0*ratio*sx)); h = max(1, int(h0*ratio*sy))
        flash_step = round(flash*32)
        loading_position=self.app.get_loading_position(self) if loading_index>=0 else None
        key = (id(original), side, w, h, flash_step, color if flash_step else None, loading_position, loading_index)
        if key == self.render_key:
            return
        if key in self.app.frame_cache:
            self.photo = self.app.frame_cache[key]
            self.label.config(image=self.photo)
            self.render_key = key
            return
        canvas = Image.new('RGBA', (side, side), (255,0,255,0))
        frame = self.app.render_source(original,self.size).resize((w,h), Image.Resampling.BILINEAR)
        canvas.alpha_composite(frame, ((side-w)//2, int(side*.84)-h))
        if flash_step:
            alpha = canvas.getchannel('A')
            tinted = Image.blend(canvas.convert('RGB'), Image.new('RGB', canvas.size, color), flash_step/32)
            tinted.putalpha(alpha)
            canvas = tinted
        if loading_index >= 0:
            frames=self.app.loading_frames_for(self.size)
            if frames:
                overlay=frames[loading_index % len(frames)]
                left=(side-w)//2
                top=int(side*.84)-h
                position_x,position_y=loading_position
                ox=max(0,min(side-overlay.width,round(left+w*position_x/100-overlay.width/2)))
                oy=max(0,min(side-overlay.height,round(top+h*position_y/100-overlay.height/2)))
                canvas.alpha_composite(overlay,(ox,oy))
        alpha = canvas.getchannel('A').point(lambda p: 255 if p >= 12 else 0)
        keyed = Image.composite(canvas.convert('RGB'), Image.new('RGB', canvas.size, (255,0,255)), alpha)
        self.photo = ImageTk.PhotoImage(keyed)
        self.label.config(image=self.photo)
        self.app.frame_cache[key] = self.photo
        self.render_key = key

    def update_notice(self, now):
        duration=max(1.,self.app.notice_duration.get())
        age=now-self.app.bpm_notice_started
        if not self.app.notice_enabled.get() or not 0 <= age < duration:
            if self.notice_window:
                self.notice_window.destroy(); self.notice_window=None
            return
        if self.notice_window is None:
            window=tk.Toplevel(self.app.root); self.notice_window=window
            window.overrideredirect(True); window.configure(bg=KEY)
            label=tk.Label(window,bg=KEY,bd=0,highlightthickness=0)
            label.pack(); self.notice_label=label
            self.notice_render_key=None; self.notice_top=None
            window.update_idletasks()
            try:
                user32=ctypes.windll.user32
                hwnd=user32.GetParent(window.winfo_id()) or window.winfo_id()
                style=user32.GetWindowLongW(hwnd,-20)
                user32.SetWindowLongW(hwnd,-20,style | 0x20 | 0x80 | 0x08000000)
            except Exception: pass
        text=f'BPM {round(self.app.bpm_notice_value)}'
        key=(text,self.size,self.app.notice_color,self.app.notice_outline.get(),self.app.notice_outline_color)
        if key != self.notice_render_key:
            fontsize=max(16,min(36,self.size//12))
            try: font=ImageFont.truetype(os.path.join(os.environ.get('WINDIR',r'C:\Windows'),'Fonts','msyhbd.ttc'),fontsize)
            except OSError: font=ImageFont.load_default(size=fontsize)
            stroke=2 if self.app.notice_outline.get() else 0
            box=font.getbbox(text,stroke_width=stroke)
            size=(box[2]-box[0]+4,box[3]-box[1]+4); xy=(2-box[0],2-box[1])
            text_mask=Image.new('L',size,0); ImageDraw.Draw(text_mask).text(xy,text,font=font,fill=255)
            keycolor=next(c for c in ('#ff00ff','#00ff00','#00ffff') if c.lower() not in (self.app.notice_color.lower(),self.app.notice_outline_color.lower()))
            bitmap=Image.new('RGB',size,keycolor)
            if stroke:
                outline=Image.new('L',size,0)
                ImageDraw.Draw(outline).text(xy,text,font=font,fill=255,stroke_width=stroke,stroke_fill=255)
                bitmap.paste(self.app.notice_outline_color,mask=outline.point(lambda value: 255 if value >= 128 else 0))
            bitmap.paste(self.app.notice_color,mask=text_mask.point(lambda value: 255 if value >= 128 else 0))
            self.notice_bitmap=bitmap
            self.notice_photo=ImageTk.PhotoImage(bitmap)
            self.notice_window.configure(bg=keycolor); self.notice_window.wm_attributes('-transparentcolor',keycolor)
            self.notice_label.config(image=self.notice_photo,bg=keycolor)
            self.notice_window.update_idletasks(); self.notice_render_key=key; self.notice_text=text
        alpha=min(1.,age/min(.45,duration*.2),(duration-age)/min(.65,duration*.25))
        self.notice_window.attributes('-alpha',max(.01,alpha))
        if self.notice_top != self.app.top_value:
            self.notice_window.attributes('-topmost',self.app.top_value); self.notice_top=self.app.top_value
        x=self.win.winfo_x()+(self.win.winfo_width()-self.notice_window.winfo_reqwidth())//2
        y=self.win.winfo_y()+round(self.size*.48-age/duration*self.size*.75)
        self.notice_window.geometry(f'+{max(0,x)}+{max(0,y)}')

    def record(self):
        return {'id': self.id, 'image': self.image_path, 'size': self.size,
                'x': self.win.winfo_x(), 'y': self.win.winfo_y(),
                'loading_x':self.loading_x,'loading_y':self.loading_y}


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Q弹音乐')
        set_window_icon(self.root)
        try: self.root.iconbitmap(default=APP_ICON)
        except tk.TclError: pass
        try:
            with open(CONFIG, encoding='utf-8') as file:
                self.config = json.load(file)
        except Exception:
            self.config = {}
        geometry = self.config.get('main_geometry', '680x650')
        self.root.geometry(geometry if isinstance(geometry,str) and re.fullmatch(r'\d{3,4}x\d{3,4}',geometry) else '680x650')
        self.root.minsize(610,610)
        self.root.resizable(True,True)
        self.events = queue.Queue()
        self.analyzer = None
        self.tray = None
        self.feedback_dialog = None
        self.settings_window = None
        self.image_picker = None
        self.sprites = []
        self.image_cache = {}
        self.picker_thumbnails = {}
        recent=self.config.get('recent_images')
        if not isinstance(recent,list):
            recent=[self.config.get('image','')]
            windows=self.config.get('windows',[])
            if isinstance(windows,list): recent.extend(record.get('image','') for record in windows if isinstance(record,dict))
        self.recent_images=[p for p in recent if isinstance(p,str) and os.path.isfile(p)][:30] if isinstance(recent,list) else []
        self.recent_images=list(dict.fromkeys(self.recent_images))
        self.frame_cache = {}
        self.resize_cache = OrderedDict()
        self.loading_source_frames=[]; self.loading_durations=[]; self.loading_cache={}
        try:
            with Image.open(LOADING_GIF) as gif:
                for frame in ImageSequence.Iterator(gif):
                    self.loading_source_frames.append(frame.convert('RGBA'))
                    self.loading_durations.append(max(.02,float(frame.info.get('duration',50))/1000))
        except (OSError, ValueError): pass
        self.selected_id = None
        self.next_sprite_id = 1
        self.sources = []
        self.all_sources = []
        self.analysis_bias = 1.0
        self.anim_sx = 1.0; self.anim_sy = 1.0
        self.last_frame_time = time.monotonic()
        self.tick_job = None
        self.flash_started = -1e9
        self.bpm_notice_started = -1e9; self.bpm_notice_value = 0
        self.update_busy = False; self.update_release = None; self.update_progress_window = None
        self.setup_install = os.path.isfile(os.path.join(BASE,'.bounce-installed'))
        self.shared_image_path = self.config.get('image','')
        self.shared_original = self.get_image(self.shared_image_path)
        self.source_mode = tk.StringVar(value='process' if process_capture_supported() else 'device')
        self.filter_text = tk.StringVar()
        self.image_mode = tk.StringVar(value=self.config.get('image_mode','uniform'))
        if self.image_mode.get() not in ('uniform','multiple'):
            self.image_mode.set('uniform')
        self.close_action = tk.StringVar(value=self.config.get('close_action','hide'))
        if self.close_action.get() not in ('hide','quit','ask'):
            self.close_action.set('hide')
        self.fps = tk.StringVar(value=str(self.config.get('fps',30)))
        if self.fps.get() not in ('15','24','30','45','60','90','120','144'):
            self.fps.set('30')
        self.fast_bpm_threshold=tk.IntVar(value=max(80,min(240,int(self.config.get('fast_bpm_threshold',190)))))
        self.amplitude = tk.DoubleVar(value=amplitude_from_config(self.config))
        # Manual alignment is temporary for the current song; previous songs do not leak into the next one.
        self.offset = tk.DoubleVar(value=0.)
        self.offset_label=tk.StringVar(value='自动对齐')
        self.top = tk.BooleanVar(value=self.config.get('top',True))
        self.top_value = self.top.get()
        self.size = tk.IntVar(value=self.config.get('size',240))
        self.flash_enabled = tk.BooleanVar(value=self.config.get('flash_enabled',True))
        self.flash_color = self.config.get('flash_color','#ffff00')
        if not isinstance(self.flash_color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',self.flash_color):
            self.flash_color='#ffff00'
        self.flash_duration = tk.DoubleVar(value=float(self.config.get('flash_duration',.55)))
        self.notice_enabled = tk.BooleanVar(value=self.config.get('notice_enabled',True))
        self.notice_color = self.config.get('notice_color','#ffff00')
        if not isinstance(self.notice_color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',self.notice_color): self.notice_color='#ffff00'
        self.notice_outline = tk.BooleanVar(value=self.config.get('notice_outline',True))
        self.notice_outline_color = self.config.get('notice_outline_color','#000000')
        if not isinstance(self.notice_outline_color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',self.notice_outline_color): self.notice_outline_color='#000000'
        self.theme_mode = tk.StringVar(value=self.config.get('theme_mode','light'))
        if self.theme_mode.get() not in ('light','dark'): self.theme_mode.set('light')
        self.notice_duration = tk.DoubleVar(value=max(1.,min(6.,float(self.config.get('notice_duration',3.)))))
        self.bpm_correction = tk.StringVar(value=self.config.get('bpm_correction','auto'))
        self.phase_correction = tk.StringVar(value=self.config.get('phase_correction','auto'))
        for variable in (self.bpm_correction,self.phase_correction):
            if variable.get() not in ('low','medium','high','auto'): variable.set('auto')
        self.feedback_enabled = tk.BooleanVar(value=self.config.get('feedback_enabled',False))
        self.double_click_close = tk.BooleanVar(value=self.config.get('double_click_close',True))
        self.shared_loading_x=max(0,min(100,int(self.config.get('loading_x',85))))
        self.shared_loading_y=max(0,min(100,int(self.config.get('loading_y',12))))
        self.loading_x = tk.IntVar(value=self.shared_loading_x)
        self.loading_y = tk.IntVar(value=self.shared_loading_y)
        self.loading_syncing=False
        self.preview_key=None
        self.manual_bpm_text = tk.StringVar()
        self.end_silence = tk.DoubleVar(value=max(1.,min(30.,float(self.config.get('end_silence',3.5)))))
        self.status = tk.StringVar(value=('请选择音频源，然后点击开始监听' if process_capture_supported() else
                                          '此版 Windows 10 请使用播放设备监听；进程音频接口不可用。'))
        self.bpmtext = tk.StringVar(value='BPM：--')
        self.build_main()
        self.apply_theme()
        saved = self.config.get('windows')
        if isinstance(saved,list):
            for record in saved:
                if record.get('visible',True):
                    self.make_sprite(record.get('image',''), record.get('size',240),
                                     record.get('x',800), record.get('y',250),
                                     record.get('loading_x',85), record.get('loading_y',12))
        else:
            self.make_sprite(self.shared_image_path, self.config.get('size',240),
                             self.config.get('x',800), self.config.get('y',250))
        self.refresh_sprite_list()
        self.root.protocol('WM_DELETE_WINDOW',self.request_close)
        self.refresh_sources()
        self.make_tray()
        self.tick()

    def apply_theme(self):
        dark=self.theme_mode.get()=='dark'
        bg,fg,field,button,muted = (('#202329','#f2f3f5','#30343d','#383d47','#bcc4cf') if dark else
                                    ('#f3f3f3','#161616','#ffffff','#e4e4e4','#555555'))
        style=ttk.Style(self.root); style.theme_use('clam')
        style.configure('.',background=bg,foreground=fg,fieldbackground=field)
        for name in ('TFrame','TLabel','TCheckbutton','TRadiobutton','TNotebook'):
            style.configure(name,background=bg,foreground=fg)
        style.configure('TButton',background=button,foreground=fg,padding=4)
        style.map('TButton',background=[('active','#505866' if dark else '#d6d6d6')],foreground=[('disabled',muted)])
        for name in ('TCheckbutton','TRadiobutton'):
            style.map(name,background=[('active',bg)],foreground=[('disabled',muted)])
        style.configure('TEntry',fieldbackground=field,foreground=fg,insertcolor=fg)
        style.configure('TCombobox',fieldbackground=field,foreground=fg,background=button,arrowcolor=fg)
        style.map('TCombobox',fieldbackground=[('readonly',field)],foreground=[('readonly',fg)])
        style.configure('TNotebook.Tab',padding=(20,6),background=button,foreground=fg)
        style.map('TNotebook.Tab',padding=[('selected',(26,6)),('!selected',(20,6))],
                  background=[('selected',field)],foreground=[('selected',fg)])
        style.configure('Link.TLabel',background=bg,foreground='#75baff' if dark else '#0069c2')
        self.root.option_add('*TCombobox*Listbox.background',field)
        self.root.option_add('*TCombobox*Listbox.foreground',fg)
        excluded={sprite.win for sprite in self.sprites}
        excluded.update(sprite.notice_window for sprite in self.sprites if sprite.notice_window)
        def paint(widget):
            if widget in excluded: return
            try:
                if isinstance(widget,(tk.Tk,tk.Toplevel)): widget.configure(bg=bg)
                elif isinstance(widget,tk.Scale): widget.configure(bg=bg,fg=fg,troughcolor=button,activebackground=field,highlightbackground=bg)
                elif isinstance(widget,tk.Listbox):
                    widget.configure(bg=field,fg=fg,selectbackground='#2769ad',selectforeground='#ffffff')
                elif isinstance(widget,(tk.Text,tk.Entry)):
                    widget.configure(bg=field,fg=fg,insertbackground=fg,selectbackground='#2769ad',selectforeground='#ffffff')
                elif isinstance(widget,ttk.Label) and widget.cget('style') != 'Link.TLabel':
                    if widget.cget('foreground'): widget.configure(foreground=muted if widget.cget('foreground') in ('#666666','#34596a',muted) else fg)
            except tk.TclError: pass
            for child in widget.winfo_children(): paint(child)
        paint(self.root)
    def set_theme(self):
        self.apply_theme(); self.save()

    def loading_frames_for(self,size):
        if not self.loading_source_frames: return []
        side=max(24,min(42,round(size*.18)))
        if side not in self.loading_cache:
            self.loading_cache[side]=[frame.resize((side,side),Image.Resampling.LANCZOS)
                                      for frame in self.loading_source_frames]
        return self.loading_cache[side]
    def loading_frame_index(self,now):
        if not self.loading_durations: return -1
        t=now % sum(self.loading_durations)
        for index,duration in enumerate(self.loading_durations):
            if t<duration: return index
            t-=duration
        return len(self.loading_durations)-1
    def update_loading_preview(self):
        if not hasattr(self,'loading_preview') or not self.loading_preview.winfo_exists(): return
        sprite=self.selected_sprite()
        original=(self.shared_original if self.image_mode.get()=='uniform' else
                  sprite.original if sprite else self.shared_original)
        index=self.loading_frame_index(time.monotonic())
        position_x,position_y=self.get_loading_position(sprite)
        key=(id(original),position_x,position_y,index)
        if key==self.preview_key: return
        canvas=Image.new('RGBA',(170,170),(246,247,249,255))
        frame=original.copy()
        frame.thumbnail((140,140),Image.Resampling.LANCZOS)
        w,h=frame.size; left=(170-w)//2; top=155-h
        canvas.alpha_composite(frame,(left,top))
        frames=self.loading_frames_for(155)
        if frames and index>=0:
            overlay=frames[index % len(frames)]
            ox=max(0,min(170-overlay.width,round(left+w*position_x/100-overlay.width/2)))
            oy=max(0,min(170-overlay.height,round(top+h*position_y/100-overlay.height/2)))
            canvas.alpha_composite(overlay,(ox,oy))
        self.preview_photo=ImageTk.PhotoImage(canvas)
        self.loading_preview.config(image=self.preview_photo)
        self.preview_key=key
    def set_loading_position(self,value=None):
        if self.loading_syncing: return
        sprite=self.selected_sprite()
        if self.image_mode.get()=='multiple' and sprite:
            sprite.loading_x=self.loading_x.get(); sprite.loading_y=self.loading_y.get()
        else:
            self.shared_loading_x=self.loading_x.get(); self.shared_loading_y=self.loading_y.get()
        self.preview_key=None
        self.update_loading_preview()
        self.save()
    def get_loading_position(self,sprite=None):
        if self.image_mode.get()=='multiple' and sprite:
            return sprite.loading_x,sprite.loading_y
        return self.shared_loading_x,self.shared_loading_y
    def sync_loading_position(self):
        self.loading_syncing=True
        self.loading_x.set(self.get_loading_position(self.selected_sprite())[0])
        self.loading_y.set(self.get_loading_position(self.selected_sprite())[1])
        self.loading_syncing=False
        self.preview_key=None
        self.update_loading_preview()

    def build_main(self):
        main = ttk.Frame(self.root,padding=16); main.pack(fill='both',expand=True)
        heading=ttk.Frame(main); heading.pack(fill='x')
        ttk.Label(heading,text='Q弹音乐',font=('Microsoft YaHei UI',18,'bold')).pack(side='left')
        ttk.Button(heading,text='设置',command=self.show_settings).pack(side='right')
        ttk.Label(main,text='选择音频源，然后保持Q弹！').pack(anchor='w',pady=(3,10))
        row=ttk.Frame(main); row.pack(fill='x')
        process_button=ttk.Radiobutton(row,text='指定软件进程',variable=self.source_mode,value='process',command=self.refresh_sources)
        process_button.pack(side='left')
        if not process_capture_supported(): process_button.state(['disabled'])
        ttk.Radiobutton(row,text='播放设备',variable=self.source_mode,value='device',command=self.refresh_sources).pack(side='left',padx=12)
        netease_button=ttk.Button(row,text='自动查找播放进程',command=self.find_playing_process)
        netease_button.pack(side='right')
        if not process_capture_supported(): netease_button.state(['disabled'])
        row=ttk.Frame(main); row.pack(fill='x',pady=5)
        ttk.Label(row,text='筛选进程').pack(side='left')
        ttk.Entry(row,textvariable=self.filter_text).pack(side='left',fill='x',expand=True,padx=8)
        self.filter_text.trace_add('write',lambda *_: self.apply_filter())
        row=ttk.Frame(main); row.pack(fill='x')
        self.combo=ttk.Combobox(row,state='readonly'); self.combo.pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='刷新列表',command=self.refresh_sources).pack(side='left',padx=(7,0))
        row=ttk.Frame(main); row.pack(fill='x',pady=(9,6))
        ttk.Button(row,text='开始监听',command=self.start).pack(side='left')
        ttk.Button(row,text='停止Q弹',command=self.stop).pack(side='left',padx=5)
        ttk.Button(row,text='停止并校准',command=self.stop_and_rate).pack(side='left',padx=(0,5))
        ttk.Button(row,text='刷新 BPM',command=self.refresh_bpm).pack(side='left')
        ttk.Button(row,text='立即对齐节奏',command=self.realign_rhythm).pack(side='left',padx=5)
        ttk.Label(row,textvariable=self.bpmtext,font=('Microsoft YaHei UI',11,'bold')).pack(side='right')
        row=ttk.Frame(main); row.pack(fill='x',pady=(0,4))
        self.manual_learn_button=ttk.Button(row,text='应用并学习',command=lambda:self.apply_manual_bpm(True))
        self.manual_learn_button.pack(side='right')
        self.manual_lock_button=ttk.Button(row,text='仅应用',command=lambda:self.apply_manual_bpm(False))
        self.manual_lock_button.pack(side='right',padx=5)
        self.manual_bpm_entry=ttk.Entry(row,textvariable=self.manual_bpm_text,width=9)
        self.manual_bpm_entry.pack(side='right',padx=(0,5))
        ttk.Label(row,text='手动 BPM').pack(side='right',padx=(0,5))
        row=ttk.Frame(main); row.pack(fill='x',pady=(7,3))
        ttk.Label(row,text='图片模式').pack(side='left')
        ttk.Radiobutton(row,text='使用统一图片',variable=self.image_mode,value='uniform',command=self.set_image_mode).pack(side='left',padx=8)
        ttk.Radiobutton(row,text='使用多种图片',variable=self.image_mode,value='multiple',command=self.set_image_mode).pack(side='left')
        row=ttk.Frame(main); row.pack(fill='x',pady=4)
        self.image_picker_button=ttk.Button(row,text='选择图片',command=self.show_image_picker)
        self.image_picker_button.pack(side='left',padx=(0,7))
        ttk.Button(row,text='导入图片',command=self.import_image).pack(side='left')
        ttk.Button(row,text='新增Q弹',command=self.add_sprite).pack(side='left',padx=7)
        ttk.Button(row,text='关闭所选图片',command=self.close_selected_sprite).pack(side='left')
        ttk.Checkbutton(row,text='全部置顶',variable=self.top,command=self.set_top).pack(side='right')
        ttk.Label(main,text='图片窗口').pack(anchor='w',pady=(4,2))
        self.sprite_list=tk.Listbox(main,height=3,exportselection=False)
        self.sprite_list.pack(fill='both',expand=True)
        self.sprite_list.bind('<<ListboxSelect>>',self.on_sprite_selected)
        row=ttk.Frame(main); row.pack(fill='x',pady=(5,0)); row.columnconfigure(1,weight=1)
        ttk.Label(row,text='所选图片大小',width=12,anchor='w').grid(row=0,column=0,sticky='w')
        ttk.Scale(row,from_=100,to=450,variable=self.size,orient='horizontal',command=self.change_selected_size).grid(row=0,column=1,sticky='ew',padx=8)
        ttk.Label(row,textvariable=self.size,width=7,anchor='e').grid(row=0,column=2)
        row=ttk.Frame(main); row.pack(fill='x',pady=5); row.columnconfigure(1,weight=1)
        ttk.Label(row,text='动画幅度',width=12,anchor='w').grid(row=0,column=0,sticky='w')
        tk.Scale(row,variable=self.amplitude,from_=50,to=150,resolution=5,orient='horizontal',showvalue=False,
                 highlightthickness=0).grid(row=0,column=1,sticky='ew',padx=8)
        ttk.Label(row,textvariable=self.amplitude,width=7,anchor='e').grid(row=0,column=2)
        ttk.Label(row,text='%').grid(row=0,column=3,padx=(4,0))
        row=ttk.Frame(main); row.pack(fill='x',pady=5)
        ttk.Label(row,text='本曲节奏微调',width=14).pack(side='left')
        ttk.Button(row,text='提前一点',command=lambda:self.adjust_offset(-.02)).pack(side='left')
        ttk.Button(row,text='延后一点',command=lambda:self.adjust_offset(.02)).pack(side='left',padx=5)
        ttk.Button(row,text='恢复自动',command=self.reset_alignment).pack(side='left')
        ttk.Label(row,textvariable=self.offset_label).pack(side='left',padx=10)
        ttk.Label(main,text='微调只影响当前播放；停止或检测到换曲后恢复。',foreground='#666666').pack(anchor='w')
        ttk.Checkbutton(main,text='歌曲结束后询问节奏与 BPM 是否匹配（用于校准分析）',variable=self.feedback_enabled,command=self.save).pack(anchor='w',pady=(2,3))
        ttk.Label(main,textvariable=self.status,wraplength=550,foreground='#34596a').pack(anchor='w')

    def color_swatch(self,parent,color,command):
        swatch=tk.Label(parent,bg=color,width=4,height=1,relief='solid',bd=1,cursor='hand2',takefocus=True)
        swatch.bind('<Button-1>',lambda event:command())
        swatch.bind('<Return>',lambda event:command())
        swatch.bind('<space>',lambda event:command())
        swatch.pack(side='left',padx=8)
        return swatch

    def show_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify(); self.settings_window.lift()
            self.preview_key=None; self.update_loading_preview(); return
        window=tk.Toplevel(self.root); self.settings_window=window
        set_window_icon(window)
        window.title('Q弹音乐 · 设置'); window.resizable(False,False)
        notebook=ttk.Notebook(window); notebook.pack(fill='both',expand=True,padx=12,pady=12)
        general=ttk.Frame(notebook,padding=14); feature=ttk.Frame(notebook,padding=14); about=ttk.Frame(notebook,padding=18)
        notebook.add(general,text='常规'); notebook.add(feature,text='功能'); notebook.add(about,text='关于')
        self.settings_notebook=notebook
        row=ttk.Frame(general); row.pack(fill='x',pady=6)
        ttk.Label(row,text='动画帧率',width=18).pack(side='left')
        fps=ttk.Combobox(row,textvariable=self.fps,values=('15','24','30','45','60','90','120','144'),state='readonly',width=6)
        fps.pack(side='left'); fps.bind('<<ComboboxSelected>>',lambda event:self.save())
        ttk.Label(row,text='帧/秒').pack(side='left',padx=8)
        row=ttk.Frame(general); row.pack(fill='x',pady=6)
        ttk.Label(row,text='界面模式',width=18).pack(side='left')
        for label,value in [('浅色','light'),('深色','dark')]:
            ttk.Radiobutton(row,text=label,variable=self.theme_mode,value=value,command=self.set_theme).pack(side='left',padx=4)
        row=ttk.Frame(general); row.pack(fill='x',pady=6)
        ttk.Label(row,text='歌曲结束判定阈值',width=18).pack(side='left')
        tk.Scale(row,variable=self.end_silence,from_=1,to=30,resolution=.5,orient='horizontal',length=200,
                 showvalue=False,highlightthickness=0,command=self.set_end_silence).pack(side='left',padx=6)
        ttk.Label(row,textvariable=self.end_silence,width=4).pack(side='left'); ttk.Label(row,text='秒').pack(side='left')
        ttk.Checkbutton(general,text='双击图片时快速关闭该图片',variable=self.double_click_close,command=self.save).pack(anchor='w',pady=8)
        ttk.Separator(general).pack(fill='x',pady=10)
        ttk.Label(general,text='点击主窗口关闭时').pack(anchor='w')
        row=ttk.Frame(general); row.pack(fill='x',pady=6)
        for label,value in [('隐藏到系统托盘','hide'),('直接退出','quit'),('每次询问','ask')]:
            ttk.Radiobutton(row,text=label,variable=self.close_action,value=value,command=self.save).pack(side='left',padx=(0,8))
        ttk.Label(general,text='选择“每次询问”后，可在询问框中勾选“不再询问”。',foreground='#666666').pack(anchor='w')
        ttk.Separator(general).pack(fill='x',pady=10)
        ttk.Button(general,text='清除学习与对轨数据',command=self.clear_analysis_data).pack(anchor='w')
        ttk.Label(general,text='重置节奏反馈、校准记录与当前 BPM。',foreground='#666666').pack(anchor='w',pady=6)

        row=ttk.Frame(feature); row.pack(fill='x',pady=3)
        ttk.Label(row,text='最高弹跳速度',width=16).pack(side='left')
        tk.Scale(row,variable=self.fast_bpm_threshold,from_=80,to=240,resolution=5,orient='horizontal',length=190,
                 showvalue=False,highlightthickness=0,command=self.set_fast_threshold).pack(side='left',padx=6)
        ttk.Label(row,textvariable=self.fast_bpm_threshold,width=4).pack(side='left'); ttk.Label(row,text='BPM').pack(side='left')
        for title,variable in [('BPM 矫正频率',self.bpm_correction),('节奏矫正频率',self.phase_correction)]:
            row=ttk.Frame(feature); row.pack(fill='x',pady=3)
            ttk.Label(row,text=title,width=16).pack(side='left')
            for label,value in [('低','low'),('中','medium'),('高','high'),('自动','auto')]:
                ttk.Radiobutton(row,text=label,value=value,variable=variable,command=self.set_corrections).pack(side='left',padx=4)
        row=ttk.Frame(feature); row.pack(fill='x',pady=3)
        ttk.Checkbutton(row,text='BPM 锁定时闪色提示',variable=self.flash_enabled,command=self.save).pack(side='left')
        self.color_preview=self.color_swatch(row,self.flash_color,self.choose_flash_color)
        row=ttk.Frame(feature); row.pack(fill='x')
        ttk.Label(row,text='渐隐时间',width=16).pack(side='left')
        tk.Scale(row,variable=self.flash_duration,from_=.1,to=2.,resolution=.05,orient='horizontal',length=190,
                 showvalue=False,highlightthickness=0,command=lambda value:self.save()).pack(side='left',padx=6)
        ttk.Label(row,textvariable=self.flash_duration,width=4).pack(side='left'); ttk.Label(row,text='秒').pack(side='left')
        row=ttk.Frame(feature); row.pack(fill='x',pady=3)
        ttk.Checkbutton(row,text='锁定时显示 BPM 浮动文字',variable=self.notice_enabled,command=self.save).pack(side='left')
        self.notice_preview=self.color_swatch(row,self.notice_color,self.choose_notice_color)
        row=ttk.Frame(feature); row.pack(fill='x',pady=2)
        ttk.Checkbutton(row,text='文字描边',variable=self.notice_outline,command=self.save).pack(side='left')
        self.outline_preview=self.color_swatch(row,self.notice_outline_color,self.choose_outline_color)
        row=ttk.Frame(feature); row.pack(fill='x')
        ttk.Label(row,text='文字显示时长',width=16).pack(side='left')
        tk.Scale(row,variable=self.notice_duration,from_=1,to=6,resolution=.25,orient='horizontal',length=190,
                 showvalue=False,highlightthickness=0,command=lambda value:self.save()).pack(side='left',padx=6)
        ttk.Label(row,textvariable=self.notice_duration,width=4).pack(side='left'); ttk.Label(row,text='秒').pack(side='left')
        ttk.Separator(feature).pack(fill='x',pady=7)
        row=ttk.Frame(feature); row.pack(fill='x')
        ttk.Label(row,text='加载动图位置').pack(side='left')
        self.loading_target=ttk.Combobox(row,state='readonly',width=24); self.loading_target.pack(side='left',padx=8)
        self.loading_target.bind('<<ComboboxSelected>>',self.on_loading_target_selected); self.refresh_loading_targets()
        position_row=ttk.Frame(feature); position_row.pack(fill='x',pady=4)
        controls=ttk.Frame(position_row); controls.pack(side='left',fill='x',expand=True)
        for title,variable in [('横向',self.loading_x),('纵向',self.loading_y)]:
            control=ttk.Frame(controls); control.pack(fill='x',pady=7)
            ttk.Label(control,text=title,width=4).pack(side='left')
            tk.Scale(control,variable=variable,from_=0,to=100,resolution=1,orient='horizontal',showvalue=False,
                     highlightthickness=0,length=170,command=self.set_loading_position).pack(side='left',fill='x',expand=True,padx=5)
            ttk.Label(control,textvariable=variable,width=4).pack(side='left')
        preview_frame=ttk.Frame(position_row,width=150,height=150,relief='solid',borderwidth=1)
        preview_frame.pack(side='right',padx=(8,0)); preview_frame.pack_propagate(False)
        self.loading_preview=tk.Label(preview_frame,bg='#f6f7f9',bd=0); self.loading_preview.pack(fill='both',expand=True)
        self.preview_key=None; self.update_loading_preview()

        ttk.Label(about,text='Q弹音乐 / BounceMusic',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=(0,14))
        ttk.Label(about,text='当前版本：v'+VERSION).pack(anchor='w',pady=5)
        ttk.Label(about,text='项目作者：'+AUTHOR).pack(anchor='w',pady=5)
        for label,url in [('B站：https://space.bilibili.com/200696277','https://space.bilibili.com/200696277'),
                          ('GitHub：https://github.com/Aoineko-UwU','https://github.com/Aoineko-UwU')]:
            link=ttk.Label(about,text=label,style='Link.TLabel',cursor='hand2')
            link.pack(anchor='w',pady=3); link.bind('<Button-1>',lambda event,target=url:webbrowser.open(target))
        self.update_status=tk.StringVar(value='点击检查更新，获取最新版本信息。')
        ttk.Button(about,text='检查更新',command=self.check_updates).pack(anchor='w',pady=(16,8))
        ttk.Label(about,textvariable=self.update_status,wraplength=440).pack(anchor='w')
        window.protocol('WM_DELETE_WINDOW',lambda: (self.save(),window.withdraw()))
        self.apply_theme()
        center_window(window,540); window.attributes('-topmost',True); window.lift()
        window.after_idle(lambda: center_window(window,540) if window.winfo_exists() else None)

    def request_close(self):
        action=self.close_action.get()
        if action=='hide': self.hide_main()
        elif action=='quit': self.quit()
        else:
            dialog=tk.Toplevel(self.root); set_window_icon(dialog); dialog.title('关闭 Q弹音乐'); dialog.resizable(False,False); dialog.transient(self.root)
            ttk.Label(dialog,text='关闭主窗口后要执行什么操作？',padding=14).pack()
            never=tk.BooleanVar(value=False)
            ttk.Checkbutton(dialog,text='不再询问，记住本次选择',variable=never).pack(anchor='w',padx=14)
            row=ttk.Frame(dialog,padding=14); row.pack()
            def choose(choice):
                if never.get(): self.close_action.set(choice)
                dialog.destroy(); self.save()
                if choice=='hide': self.hide_main()
                else: self.quit()
            ttk.Button(row,text='隐藏到托盘',command=lambda: choose('hide')).pack(side='left',padx=4)
            ttk.Button(row,text='直接退出',command=lambda: choose('quit')).pack(side='left',padx=4)
            ttk.Button(row,text='取消',command=dialog.destroy).pack(side='left',padx=4)
            dialog.protocol('WM_DELETE_WINDOW',dialog.destroy)
            self.apply_theme()
            center_window(dialog)
            dialog.lift(); dialog.grab_set()

    def show_main(self):
        self.root.deiconify(); self.root.lift(); self.root.focus_force()
    def get_image(self, path):
        if not path:
            if not hasattr(self,'default_image'): self.default_image=slime()
            return self.default_image
        if path not in self.image_cache:
            self.image_cache[path]=SpriteWindow.load_image(MATOU_IMAGE if path=='preset:matou' else path)
        return self.image_cache[path]
    def image_name(self,path):
        return '默认图片' if not path else ('玛头' if path=='preset:matou' else os.path.basename(path))
    def render_source(self, original, size):
        limit=max(128,int(size*1.4)); key=(id(original),limit)
        if key not in self.resize_cache:
            image=original.copy(); image.thumbnail((limit,limit),Image.Resampling.LANCZOS)
            self.resize_cache[key]=image
            while len(self.resize_cache)>12: self.resize_cache.popitem(last=False)
        self.resize_cache.move_to_end(key)
        return self.resize_cache[key]
    def prune_image_cache(self):
        self.resize_cache.clear()
        used={self.shared_image_path} | {sprite.image_path for sprite in self.sprites}
        for path in list(self.image_cache):
            if path not in used: del self.image_cache[path]
    def hide_main(self):
        self.save()
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.withdraw()
        self.root.withdraw()
    def quit(self):
        self.save()
        if self.tick_job:
            try: self.root.after_cancel(self.tick_job)
            except tk.TclError: pass
        if self.analyzer: self.analyzer.stop(); self.analyzer=None
        if self.tray: self.tray.stop()
        self.root.destroy()

    def make_sprite(self, image='', size=240, x=800, y=250, loading_x=85, loading_y=12):
        sprite=SpriteWindow(self,self.next_sprite_id,image,size,x,y,loading_x,loading_y)
        self.next_sprite_id+=1; self.sprites.append(sprite)
        if self.selected_id is None: self.selected_id=sprite.id; self.size.set(sprite.size)
        return sprite
    def selected_sprite(self):
        return next((sprite for sprite in self.sprites if sprite.id==self.selected_id),None)
    def select_sprite(self, sprite_id):
        self.selected_id=sprite_id
        for i,sprite in enumerate(self.sprites):
            if sprite.id==sprite_id:
                self.sprite_list.selection_clear(0,tk.END)
                self.sprite_list.selection_set(i)
                self.sprite_list.see(i)
                self.size.set(sprite.size)
                self.sync_loading_position()
                if hasattr(self,'loading_target') and self.loading_target.winfo_exists() and self.image_mode.get()=='multiple':
                    self.loading_target.current(i)
                break
    def on_sprite_selected(self, event=None):
        selection=self.sprite_list.curselection()
        if selection:
            sprite=self.sprites[selection[0]]
            self.selected_id=sprite.id; self.size.set(sprite.size)
            self.sync_loading_position()
    def refresh_sprite_list(self):
        self.sprite_list.delete(0,tk.END)
        for sprite in self.sprites:
            path=self.shared_image_path if self.image_mode.get()=='uniform' else sprite.image_path
            name=self.image_name(path)
            self.sprite_list.insert(tk.END,f'图片 {sprite.id} · {name}')
        if self.selected_id is not None: self.select_sprite(self.selected_id)
        self.refresh_loading_targets()
    def refresh_loading_targets(self):
        if not hasattr(self,'loading_target') or not self.loading_target.winfo_exists(): return
        if self.image_mode.get()=='uniform':
            self.loading_target['values']=['统一图片']
            self.loading_target.current(0)
        else:
            values=[f'图片 {sprite.id} · {self.image_name(sprite.image_path)}' for sprite in self.sprites]
            self.loading_target['values']=values or ['默认图']
            index=next((i for i,sprite in enumerate(self.sprites) if sprite.id==self.selected_id),0)
            self.loading_target.current(index)
    def on_loading_target_selected(self,event=None):
        index=self.loading_target.current()
        if self.image_mode.get()=='multiple' and 0<=index<len(self.sprites):
            self.select_sprite(self.sprites[index].id)
    def add_sprite(self):
        path=''
        if self.image_mode.get()=='multiple':
            path=filedialog.askopenfilename(parent=self.root,title='为新窗口选择图片（取消则使用默认图）',filetypes=[('图片','*.png *.jpg *.jpeg *.webp *.bmp *.gif'),('所有文件','*.*')])
        x=800+35*len(self.sprites); y=250+35*len(self.sprites)
        sprite=self.make_sprite(path,self.size.get(),x,y)
        if path: self.remember_image(path)
        self.refresh_sprite_list(); self.select_sprite(sprite.id); self.save()
    def import_image(self):
        path=filedialog.askopenfilename(parent=self.root,title='导入图片',filetypes=[('图片','*.png *.jpg *.jpeg *.webp *.bmp *.gif'),('所有文件','*.*')])
        if not path: return
        self.choose_image(path,remember=True)
    def remember_image(self,path):
        self.recent_images=[p for p in self.recent_images if os.path.normcase(p)!=os.path.normcase(path)]
        self.recent_images.insert(0,path); del self.recent_images[30:]
    def picker_thumbnail(self,path):
        if path not in self.picker_thumbnails:
            try:
                if not path: image=slime()
                else:
                    with Image.open(MATOU_IMAGE if path=='preset:matou' else path) as opened:
                        opened.seek(0); opened.draft('RGB',(72,72)); image=ImageOps.exif_transpose(opened).convert('RGBA')
                image.thumbnail((58,58),Image.Resampling.LANCZOS)
                self.picker_thumbnails[path]=ImageTk.PhotoImage(image)
            except Exception: self.picker_thumbnails[path]=ImageTk.PhotoImage(slime().resize((58,52)))
        return self.picker_thumbnails[path]
    def show_image_picker(self):
        if self.image_picker and self.image_picker.winfo_exists():
            self.image_picker.destroy(); self.image_picker=None; return
        picker=tk.Toplevel(self.root); self.image_picker=picker
        picker.overrideredirect(True); picker.attributes('-topmost',True)
        shell=ttk.Frame(picker,padding=8,relief='solid',borderwidth=1); shell.pack(fill='both',expand=True)
        header=ttk.Frame(shell); header.pack(fill='x')
        ttk.Label(header,text='选择图片',font=('Microsoft YaHei UI',10,'bold')).pack(side='left')
        ttk.Button(header,text='×',width=3,command=picker.destroy).pack(side='right')
        body=ttk.Frame(shell); body.pack(fill='both',expand=True)
        def tile(parent,path,column,row):
            button=ttk.Button(parent,text=self.image_name(path),image=self.picker_thumbnail(path),compound='top',
                              width=11,command=lambda p=path:self.choose_image(p))
            button.grid(row=row,column=column,padx=3,pady=3,sticky='nsew')
            return button
        def populate(expanded=False):
            for child in body.winfo_children(): child.destroy()
            ttk.Label(body,text='预设图片').pack(anchor='w',pady=(4,0))
            presets=ttk.Frame(body); presets.pack(anchor='w')
            tile(presets,'',0,0); tile(presets,'preset:matou',1,0)
            ttk.Label(body,text='最近图片').pack(anchor='w',pady=(7,0))
            if not self.recent_images:
                ttk.Label(body,text='导入图片后会显示在这里。',foreground='#777777').pack(anchor='w',pady=6); return
            if expanded:
                wrap=ttk.Frame(body); wrap.pack(fill='both',expand=True)
                canvas=tk.Canvas(wrap,width=360,height=240,highlightthickness=0,
                                 bg='#202329' if self.theme_mode.get()=='dark' else '#f3f3f3')
                bar=ttk.Scrollbar(wrap,orient='vertical',command=canvas.yview)
                canvas.configure(yscrollcommand=bar.set); canvas.pack(side='left',fill='both',expand=True); bar.pack(side='right',fill='y')
                grid=ttk.Frame(canvas); canvas.create_window((0,0),window=grid,anchor='nw')
                grid.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
                def scroll(event): canvas.yview_scroll(-int(event.delta/120),'units')
                canvas.bind('<MouseWheel>',scroll); grid.bind('<MouseWheel>',scroll)
                for i,path in enumerate(self.recent_images): tile(grid,path,i%3,i//3).bind('<MouseWheel>',scroll)
            else:
                grid=ttk.Frame(body); grid.pack(anchor='w')
                for i,path in enumerate(self.recent_images[:5]): tile(grid,path,i%3,i//3)
                if len(self.recent_images)>5:
                    ttk.Button(grid,text='…',width=11,command=lambda:populate(True)).grid(row=1,column=2,padx=3,pady=3,sticky='nsew')
        populate()
        picker.bind('<Escape>',lambda event:picker.destroy()); self.apply_theme()
        picker.update_idletasks()
        x=self.image_picker_button.winfo_rootx()+self.image_picker_button.winfo_width()+8
        y=self.image_picker_button.winfo_rooty()
        x=max(0,min(x,picker.winfo_screenwidth()-picker.winfo_reqwidth()))
        y=max(0,min(y,picker.winfo_screenheight()-picker.winfo_reqheight()))
        picker.geometry(f'+{x}+{y}'); picker.lift()
    def choose_image(self,path,remember=False):
        if path and not path.startswith('preset:') and not os.path.isfile(path):
            self.status.set('图片文件不存在，请重新导入。'); return
        try:
            if remember:
                self.image_cache.pop(path,None); self.picker_thumbnails.pop(path,None)
            original=self.get_image(path)
            if self.image_mode.get()=='uniform': self.shared_image_path=path; self.shared_original=original
            else:
                sprite=self.selected_sprite()
                if not sprite: sprite=self.make_sprite()
                sprite.image_path=path; sprite.original=original
            if remember: self.remember_image(path)
            self.prune_image_cache(); self.refresh_sprite_list(); self.update_loading_preview(); self.save()
            if self.image_picker and self.image_picker.winfo_exists(): self.image_picker.destroy(); self.image_picker=None
        except Exception as error: messagebox.showerror('图片导入失败',str(error),parent=self.root)
    def set_image_mode(self):
        self.refresh_sprite_list(); self.sync_loading_position(); self.save()
    def close_selected_sprite(self):
        sprite=self.selected_sprite()
        if sprite: self.close_sprite(sprite.id)
    def close_sprite(self, sprite_id):
        sprite=next((s for s in self.sprites if s.id==sprite_id),None)
        if sprite:
            if sprite.notice_window: sprite.notice_window.destroy()
            sprite.win.destroy(); self.sprites.remove(sprite)
            if self.selected_id==sprite_id: self.selected_id=self.sprites[0].id if self.sprites else None
            self.prune_image_cache(); self.refresh_sprite_list(); self.sync_loading_position(); self.save()
    def change_selected_size(self,value):
        sprite=self.selected_sprite()
        if sprite: sprite.size=max(100,min(450,int(float(value)))); self.save()
    def set_top(self):
        self.top_value=self.top.get()
        for sprite in self.sprites: sprite.win.attributes('-topmost',self.top_value)
        self.save()
    def toggle_top(self):
        self.top.set(not self.top.get()); self.set_top()
    def set_end_silence(self,value=None):
        if self.analyzer: self.analyzer.end_silence=self.end_silence.get()
        self.save()

    def refresh_bpm(self):
        if self.analyzer:
            self.clear_manual_bpm()
            self.analyzer.reset_epoch += 1
            self.bpmtext.set('BPM：重新分析中')
            self.status.set('已重新开始 BPM 和对轨分析。')
        else:
            self.status.set('请先开始监听音频，再刷新 BPM。')
    def realign_rhythm(self):
        if not self.analyzer or not self.analyzer.is_playing() or not self.analyzer.values()[0]:
            self.status.set('请先播放音乐并等待 BPM 识别完成。'); return
        self.analyzer.realign()
        self.status.set('正在根据近期鼓点重新对齐节奏……')
    def adjust_offset(self,amount):
        value=round(max(-.25,min(.25,self.offset.get()+amount)),2)
        self.offset.set(value)
        self.offset_label.set('自动对齐' if not value else ('提前 ' if value<0 else '延后 ')+f'{abs(value):.2f} 秒')
    def reset_alignment(self):
        self.offset.set(0.); self.offset_label.set('自动对齐')
        if self.analyzer and self.analyzer.is_playing() and self.analyzer.values()[0]: self.realign_rhythm()
        else: self.status.set('已恢复自动对齐。')
    def set_fast_threshold(self,value=None):
        if self.analyzer:
            self.analyzer.fast_bpm_threshold=self.fast_bpm_threshold.get()
        self.save()
    def set_corrections(self):
        if self.analyzer:
            self.analyzer.bpm_correction=self.bpm_correction.get()
            self.analyzer.phase_correction=self.phase_correction.get()
        self.save()
    def clear_manual_bpm(self):
        self.manual_bpm_text.set('')
        self.manual_bpm_entry.state(['!disabled'])
        self.manual_lock_button.state(['!disabled'])
        self.manual_learn_button.state(['!disabled'])
        self.manual_lock_button.config(text='仅应用')
        self.manual_learn_button.config(text='应用并学习')
        if self.analyzer: self.analyzer.manual_bpm=0.
    def record_bpm_example(self,estimated,truth,source):
        examples=self.config.setdefault('bpm_examples',[])
        examples.append({'estimated':round(estimated,2),'actual':round(truth,2),'source':source})
        del examples[:-50]
        if self.analyzer:
            self.analyzer.octave_bias=learned_octave_bias(examples)
            self.analyzer.examples=list(examples)
            if source=='feedback' and not self.analyzer.is_playing():
                self.analyzer.reset_epoch+=1
    def apply_manual_bpm(self,learn=False):
        if not self.analyzer or not self.analyzer.is_playing():
            self.status.set('请在音乐播放且 BPM 已识别后再上锁。'); return
        estimated=self.analyzer.values()[0]
        if not estimated:
            self.status.set('请等待 BPM 识别完成后再上锁。'); return
        try: truth=float(self.manual_bpm_text.get().strip())
        except ValueError: truth=0.
        if not math.isfinite(truth) or not 40<=truth<=300:
            messagebox.showerror('BPM 输入错误','请输入 40 到 300 之间的 BPM。',parent=self.root); return
        if learn: self.record_bpm_example(estimated,truth,'live')
        self.analyzer.lock_bpm(truth)
        self.manual_bpm_entry.state(['disabled'])
        self.manual_lock_button.config(text='已锁定')
        self.manual_lock_button.state(['disabled'])
        self.manual_learn_button.state(['disabled'])
        self.status.set(f'本首歌曲已按 {truth:g} BPM 锁定，'+('已记录学习样本。' if learn else '未记录学习样本。'))
        self.save()
    def clear_analysis_data(self):
        self.analysis_bias=1.
        self.config.pop('feedback_counts',None); self.config.pop('tempo_corrections',None)
        self.config.pop('bpm_examples',None); self.offset.set(0); self.offset_label.set('自动对齐')
        self.flash_started=-1e9
        if self.analyzer:
            self.analyzer.analysis_bias=1.; self.analyzer.octave_bias=0; self.analyzer.examples=[]; self.analyzer.reset_epoch+=1
        self.clear_manual_bpm()
        self.status.set('学习记录、BPM 锁定和对轨状态已清除。')
        self.save()
    def choose_flash_color(self):
        _,chosen=colorchooser.askcolor(color=self.flash_color,parent=self.settings_window,title='选择 BPM 锁定提示颜色')
        if chosen:
            self.flash_color=chosen; self.color_preview.config(bg=chosen); self.save()
    def choose_notice_color(self):
        _,chosen=colorchooser.askcolor(color=self.notice_color,parent=self.settings_window,title='选择 BPM 文字颜色')
        if chosen:
            self.notice_color=chosen; self.notice_preview.config(bg=chosen); self.save()
    def choose_outline_color(self):
        _,chosen=colorchooser.askcolor(color=self.notice_outline_color,parent=self.settings_window,title='选择 BPM 文字描边颜色')
        if chosen:
            self.notice_outline_color=chosen; self.outline_preview.config(bg=chosen); self.save()
    def check_updates(self):
        if self.update_busy: return
        self.update_busy=True; self.update_status.set('正在检查更新……')
        def worker():
            try: self.events.put(('update_checked',updater.latest_release()))
            except Exception as error: self.events.put(('update_error',str(error)))
        threading.Thread(target=worker,daemon=True).start()
    def show_update_progress(self):
        window=tk.Toplevel(self.root); window.withdraw(); self.update_progress_window=window
        set_window_icon(window); window.title('正在更新'); window.resizable(False,False)
        self.update_progress_text=tk.StringVar(value='正在连接下载服务器……')
        ttk.Label(window,text='正在准备更新',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',padx=18,pady=(16,8))
        ttk.Label(window,textvariable=self.update_progress_text).pack(anchor='w',padx=18)
        self.update_progress_bar=ttk.Progressbar(window,mode='indeterminate')
        self.update_progress_bar.pack(fill='x',padx=18,pady=(12,16)); self.update_progress_bar.start(12)
        window.protocol('WM_DELETE_WINDOW',window.withdraw)
        self.apply_theme(); center_window(window,460,150); window.deiconify(); window.attributes('-topmost',True); window.lift()
        window.after_idle(lambda: center_window(window,460,150) if window.winfo_exists() else None)
    def update_download_progress(self, phase, size, total):
        window=self.update_progress_window
        if not window or not window.winfo_exists(): return
        bar=self.update_progress_bar
        if phase=='download':
            if total:
                bar.stop(); bar.configure(mode='determinate',maximum=total,value=min(size,total))
                message=f'正在下载：{size/1048576:.1f} / {total/1048576:.1f} MB（{min(100,size*100/total):.0f}%）'
            else:
                if str(bar.cget('mode'))!='indeterminate': bar.configure(mode='indeterminate'); bar.start(12)
                message=f'正在下载：{size/1048576:.1f} MB'
        else:
            bar.stop(); bar.configure(mode='indeterminate'); bar.start(12)
            message='正在校验更新包……' if phase=='verify' else '正在解压更新包……'
        self.update_progress_text.set(message); self.update_status.set(message)
    def close_update_progress(self):
        window=self.update_progress_window; self.update_progress_window=None
        if window and window.winfo_exists(): window.destroy()
    def show_update(self,release):
        dialog=tk.Toplevel(self.root); dialog.withdraw(); set_window_icon(dialog); dialog.title('发现新版本'); dialog.resizable(False,False)
        ttk.Label(dialog,text='发现新版本 '+release['tag_name'],font=('Microsoft YaHei UI',13,'bold'),padding=12).pack(anchor='w')
        ttk.Label(dialog,text='更新内容：').pack(anchor='w',padx=12)
        content=ttk.Frame(dialog); content.pack(fill='both',expand=True,padx=12,pady=8)
        notes=tk.Text(content,wrap='word',font=('Microsoft YaHei UI',10),padx=12,pady=8,relief='flat',cursor='arrow')
        scrollbar=ttk.Scrollbar(content,orient='vertical',command=notes.yview)
        notes.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y'); notes.pack(side='left',fill='both',expand=True)
        render_release_notes(notes,release.get('body'))
        row=ttk.Frame(dialog,padding=12); row.pack(fill='x')
        def accept():
            dialog.destroy()
            if not getattr(sys,'frozen',False):
                self.update_status.set('源码运行模式请从发布页下载便携包。'); return
            self.update_busy=True; self.update_status.set('正在下载并校验更新，请稍候……')
            self.show_update_progress()
            def worker():
                try: self.events.put(('update_ready',updater.prepare_update(release,self.setup_install,lambda *progress:self.events.put(('update_progress',progress)))))
                except Exception as error: self.events.put(('update_error',str(error)))
            threading.Thread(target=worker,daemon=True).start()
        ttk.Button(row,text='更新并重启',command=accept).pack(side='left')
        ttk.Button(row,text='暂不更新',command=dialog.destroy).pack(side='right')
        self.apply_theme()
        center_window(dialog,600,520); dialog.deiconify(); dialog.attributes('-topmost',True); dialog.lift()
        dialog.after_idle(lambda: center_window(dialog,600,520) if dialog.winfo_exists() else None)

    def find_playing_process(self):
        if not process_capture_supported():
            self.status.set('此版 Windows 10 请使用播放设备监听。'); return
        self.source_mode.set('process'); self.filter_text.set(''); self.refresh_sources()
        self.status.set('正在检测播放设备上的活动音频进程，请保持音乐播放……')
        def worker():
            totals={}; taps=[]
            try:
                comtypes.CoInitialize()
                for device in AudioUtilities.GetAllDevices(data_flow=0,device_state=1):
                    try:
                        manager=device.AudioSessionManager
                        enumerator=manager.GetSessionEnumerator()
                        for index in range(enumerator.GetCount()):
                            try:
                                control=enumerator.GetSession(index).QueryInterface(IAudioSessionControl2)
                                session=AudioSession(control); pid=session.ProcessId
                                if session.State == 1 and pid and pid != os.getpid(): totals[pid]=[0.,0]
                            except Exception: pass
                    except Exception: pass
                for pid in list(totals)[:24]:
                    try:
                        def collect(data,frames,pid=pid):
                            x=np.frombuffer(data,dtype=np.float32)
                            if x.size: totals[pid][0]+=float(np.dot(x,x)); totals[pid][1]+=len(x)
                        tap=ProcessAudioCapture(pid,on_data=collect); tap.start(); taps.append(tap)
                    except Exception: pass
                time.sleep(2)
            except Exception as error:
                self.events.put(('status','查找播放进程失败：'+str(error)))
                return
            finally:
                for tap in taps:
                    try: tap.close()
                    except Exception: pass
                try: comtypes.CoUninitialize()
                except Exception: pass
            if totals:
                pid=max(totals,key=lambda n: totals[n][0]/max(1,totals[n][1]))
                self.events.put(('found_process',(pid,totals[pid][0]/max(1,totals[pid][1]))))
            else: self.events.put(('found_process',(0,0.)))
        threading.Thread(target=worker,daemon=True).start()
    def refresh_sources(self):
        try:
            self.all_sources=processes() if self.source_mode.get()=='process' else devices()
            self.apply_filter()
        except Exception as error: self.status.set('获取音频源失败：'+str(error))
    def apply_filter(self):
        if not hasattr(self,'combo'): return
        if self.source_mode.get()=='process':
            key=self.filter_text.get().strip().lower()
            self.sources=[p for p in self.all_sources if key in p[1].lower() or key in str(p[0])]
            self.combo['values']=[f'{name}   (PID {pid})' for pid,name in self.sources]
            wanted=self.config.get('process','')
            index=next((i for i,(_,name) in enumerate(self.sources) if name.lower()==wanted.lower()),0)
        else:
            self.sources=self.all_sources; self.combo['values']=[d[1] for d in self.sources]
            wanted=self.config.get('device','')
            index=next((i for i,d in enumerate(self.sources) if d[1]==wanted),0)
        if self.sources: self.combo.current(index)
        else: self.combo.set(''); self.status.set('没有匹配的音频源，请打开音乐软件或清除筛选后刷新。')
    def start(self):
        if self.source_mode.get()=='process' and not process_capture_supported():
            self.source_mode.set('device'); self.refresh_sources()
            messagebox.showinfo('Windows 10 音频监听','当前系统不支持单软件进程音频捕获，请选择播放设备后再开始监听。',parent=self.root)
            return
        i=self.combo.current()
        if i<0: messagebox.showwarning('音频源','请先选择音频源。',parent=self.root); return
        self.stop(); self.reset_alignment(); source=self.sources[i]; mode=self.source_mode.get()
        octave_bias=learned_octave_bias(self.config.get('bpm_examples',[]))
        self.analyzer=Analyzer((mode,source),self.events,self.analysis_bias,self.fast_bpm_threshold.get(),self.end_silence.get(),octave_bias,self.bpm_correction.get(),self.phase_correction.get(),self.config.get('bpm_examples',[]))
        self.config['process' if mode=='process' else 'device']=source[1]
        self.save()
    def stop(self):
        if self.analyzer: self.analyzer.stop(); self.analyzer=None
        self.clear_manual_bpm()
        self.offset.set(0.); self.offset_label.set('自动对齐')
        self.bpmtext.set('BPM：--'); self.status.set('已停止监听')
    def stop_and_rate(self):
        bpm=(self.analyzer.auto_estimate or self.analyzer.values()[0]) if self.analyzer else 0.
        self.stop()
        if bpm: self.song_feedback(bpm)
        else: self.status.set('已停止监听；本次没有可评价的 BPM 结果。')

    def song_feedback(self,bpm):
        if self.feedback_dialog and self.feedback_dialog.winfo_exists(): return
        dialog=tk.Toplevel(self.root); self.feedback_dialog=dialog
        set_window_icon(dialog)
        dialog.title('节奏与 BPM 校准反馈'); dialog.resizable(False,False); dialog.transient(self.root)
        ttk.Label(dialog,text=f'刚才的动画是否与音乐节奏匹配？（估算 BPM：{round(bpm) if bpm else "--"}）',padding=14).pack()
        bpm_row=ttk.Frame(dialog,padding=(14,0,14,8)); bpm_row.pack(fill='x')
        ttk.Label(bpm_row,text='真实 BPM（可选）').pack(side='left')
        true_bpm=tk.StringVar()
        ttk.Entry(bpm_row,textvariable=true_bpm,width=9).pack(side='left',padx=8)
        ttk.Label(bpm_row,text='可从音乐软件填写').pack(side='left')
        buttons=ttk.Frame(dialog,padding=(12,0,12,12)); buttons.pack()
        def rate(label=None,adjust=0.):
            raw=true_bpm.get().strip()
            if raw:
                try: truth=float(raw)
                except ValueError: truth=0.
                if not math.isfinite(truth) or not 40<=truth<=300:
                    messagebox.showerror('BPM 输入错误','请输入 40 到 300 之间的 BPM，或留空。',parent=dialog)
                    return
                if bpm:
                    self.record_bpm_example(bpm,truth,'feedback')
            if label:
                counts=self.config.setdefault('feedback_counts',{})
                counts[label]=int(counts.get(label,0))+1
                # An opinion alone cannot identify tempo direction or phase error.
            self.status.set('已记录'+('评价：'+label if label else '真实 BPM')+('及真实 BPM' if label and raw else ''))
            self.save(); dialog.destroy(); self.feedback_dialog=None
        for label,adjust in [('极差',.12),('较差',.07),('一般',.02),('合适',-.02),('完美',-.04)]:
            ttk.Button(buttons,text=label,width=6,command=lambda l=label,a=adjust: rate(l,a)).pack(side='left',padx=2)
        def cancel(): dialog.destroy(); self.feedback_dialog=None
        ttk.Button(dialog,text='仅提交 BPM',command=lambda: rate() if true_bpm.get().strip() else None).pack(pady=(0,4))
        ttk.Button(dialog,text='取消',command=cancel).pack(pady=(0,12))
        dialog.protocol('WM_DELETE_WINDOW',cancel)
        self.apply_theme()
        center_window(dialog)
        dialog.lift()

    def save(self):
        try:
            self.config.update(image=self.shared_image_path, image_mode=self.image_mode.get(),
                windows=[sprite.record() for sprite in self.sprites], top=self.top.get(),
                loading_x=self.shared_loading_x, loading_y=self.shared_loading_y,
                main_geometry=f'{max(610,self.root.winfo_width())}x{max(610,self.root.winfo_height())}',
                size=self.size.get(), fps=int(self.fps.get()), amplitude=self.amplitude.get(), amplitude_scale_version=2,
                offset=0., feedback_enabled=self.feedback_enabled.get(),
                end_silence=self.end_silence.get(),
                fast_bpm_threshold=self.fast_bpm_threshold.get(),
                analysis_bias=self.analysis_bias, double_click_close=self.double_click_close.get(),
                flash_enabled=self.flash_enabled.get(), flash_color=self.flash_color,
                flash_duration=self.flash_duration.get(), close_action=self.close_action.get(),
                notice_enabled=self.notice_enabled.get(), notice_color=self.notice_color, notice_duration=self.notice_duration.get(),
                notice_outline=self.notice_outline.get(), notice_outline_color=self.notice_outline_color, theme_mode=self.theme_mode.get(),
                bpm_correction=self.bpm_correction.get(), phase_correction=self.phase_correction.get())
            self.config['recent_images']=self.recent_images
            with open(CONFIG,'w',encoding='utf-8') as file:
                json.dump(self.config,file,ensure_ascii=False,indent=2)
        except Exception: pass
    def make_tray(self):
        try:
            with Image.open(APP_ICON) as source: icon=source.convert('RGBA')
        except OSError: icon=slime()
        icon.thumbnail((64,64),Image.Resampling.LANCZOS)
        self.tray=pystray.Icon('Q弹音乐',icon,'Q弹音乐',menu=pystray.Menu(
            pystray.MenuItem('打开主页面',lambda: self.events.put(('show_main','')),default=True),
            pystray.MenuItem('打开设置',lambda: self.events.put(('show_settings',''))),
            pystray.MenuItem('新增Q弹',lambda: self.events.put(('add_sprite',''))),
            pystray.MenuItem('全部置顶',lambda: self.events.put(('top','')),checked=lambda item: self.top_value),
            pystray.MenuItem('退出',lambda: self.events.put(('quit','')))))
        threading.Thread(target=self.tray.run,daemon=True).start()

    def tick(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='show_main': self.show_main()
                elif kind=='show_settings': self.show_settings()
                elif kind=='add_sprite': self.add_sprite()
                elif kind=='top': self.top.set(not self.top.get()); self.set_top()
                elif kind=='quit': self.quit(); return
                elif kind=='found_process':
                    pid,power=value
                    if self.source_mode.get()=='process' and power>1e-9:
                        self.filter_text.set(''); self.refresh_sources()
                        index=next((i for i,p in enumerate(self.sources) if p[0]==pid),-1)
                        if index>=0: self.combo.current(index); self.status.set('已找到有声音的进程，请确认来源并点击开始监听。')
                        else: self.status.set('播放进程已变化，请重新查找。')
                    elif self.source_mode.get()=='process':
                        self.status.set('未检测到播放中的声音，请确认播放器正在播放并重新查找。')
                elif kind=='song_end':
                    self.offset.set(0.); self.offset_label.set('自动对齐')
                    if self.feedback_enabled.get(): self.song_feedback(value)
                elif kind=='song_changed':
                    self.offset.set(0.); self.offset_label.set('自动对齐')
                elif kind=='manual_unlock': self.clear_manual_bpm()
                elif kind=='bpm_locked':
                    if self.flash_enabled.get(): self.flash_started=time.monotonic()
                    if self.notice_enabled.get():
                        self.bpm_notice_started=time.monotonic(); self.bpm_notice_value=value
                    self.status.set('BPM 已锁定：'+str(round(value)))
                elif kind=='update_checked':
                    self.update_busy=False
                    try:
                        if updater.version_tuple(value['tag_name']) > updater.version_tuple(VERSION):
                            updater.release_asset(value,self.setup_install)
                            self.update_status.set('发现新版本 '+value['tag_name']); self.show_update(value)
                        else: self.update_status.set('当前已是最新版本。')
                    except Exception as error: self.update_status.set('检查更新失败：'+str(error))
                elif kind=='update_error':
                    self.close_update_progress(); self.update_busy=False; self.update_status.set('更新失败：'+str(value))
                    messagebox.showerror('更新失败',str(value),parent=self.root)
                elif kind=='update_progress': self.update_download_progress(*value)
                elif kind=='update_ready':
                    self.close_update_progress(); self.update_busy=False
                    try:
                        self.save(); updater.launch_updater(value,BASE,os.getpid(),self.setup_install); self.quit(); return
                    except Exception as error: self.update_status.set('无法启动更新：'+str(error))
                elif kind=='status': self.status.set(value)
                elif kind=='error': self.status.set(value); self.bpmtext.set('BPM：--')
        except queue.Empty: pass
        bpm,level,beat,shape,strength=self.analyzer.values() if self.analyzer else (0,0,0,.12,.8)
        playing=bool(self.analyzer and self.analyzer.is_playing())
        self.bpmtext.set('BPM：'+(str(round(bpm)) if bpm and playing else ('分析中' if playing else ('等待播放' if self.analyzer else '--'))))
        now=time.monotonic(); dt=min(.2,max(.001,now-self.last_frame_time)); self.last_frame_time=now
        active=bool(playing and level>.002 and beat)
        amp=animation_amplitude(self.amplitude.get()) if active else 0.
        # The squash reaches its peak after its attack; predict the grid to center it on the beat.
        shift=self.offset.get()-.08; event_time=beat+shift if beat else -1e9
        if beat and bpm and shift<0:
            interval=max(1,math.ceil(bpm/self.fast_bpm_threshold.get()))*60/bpm
            next_time=beat+interval+shift
            if next_time<=now<beat+interval+.08 and level>.008: event_time=next_time
        age=now-event_time
        period=max(1,math.ceil(bpm/self.fast_bpm_threshold.get()))*60/bpm if bpm and bpm>0 else .65
        cycle=min(.82,max(.28,period*.92))
        attack=min(.16,cycle*.28); hold=min(.14,cycle*.23); release=max(.05,cycle-attack-hold)
        if not active or age<0 or age>=cycle: pulse=0.
        elif age<attack: pulse=.5*(1-math.cos(math.pi*age/attack))
        elif age<attack+hold: pulse=1.
        else:
            u=(age-attack-hold)/release
            pulse=max(0.,.5*(1+math.cos(math.pi*min(1.,u))))
        pulse*=max(.45,min(1.,strength))
        base_sx=1.-.10*amp; base_sy=1.+.08*amp
        sx_target=base_sx+pulse*.34*amp; sy_target=base_sy-pulse*.30*amp
        ease=min(1.,dt*30.)
        self.anim_sx+=(sx_target-self.anim_sx)*ease; self.anim_sy+=(sy_target-self.anim_sy)*ease
        elapsed=now-self.flash_started; duration=max(.1,float(self.flash_duration.get()))
        flash=1-elapsed/duration if self.flash_enabled.get() and 0<=elapsed<duration else 0.
        color=tuple(int(self.flash_color[i:i+2],16) for i in (1,3,5))
        loading_index=self.loading_frame_index(now) if playing and not bpm else -1
        self.frame_cache={}
        for sprite in self.sprites:
            sprite.render(self.anim_sx,self.anim_sy,flash,color,loading_index)
            sprite.update_notice(now)
        if self.settings_window and self.settings_window.winfo_exists() and self.settings_window.winfo_viewable():
            self.update_loading_preview()
        self.tick_job=self.root.after(max(1,round(1000/int(self.fps.get()))),self.tick)

if __name__ == '__main__':
    instance_handle=acquire_single_instance()
    if not instance_handle:
        ctypes.windll.user32.MessageBoxW(None,'Q弹音乐已经在运行，请检查系统托盘。','Q弹音乐',0x40)
        sys.exit(0)
    try: App().root.mainloop()
    except Exception:
        with open(os.path.join(BASE, '错误日志.txt'), 'w', encoding='utf-8') as f: traceback.print_exc(file=f)
        raise




