import os, sys, time, threading, queue, json, math, traceback
import re
from collections import deque
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import numpy as np
import pyaudiowpatch as pa
import pystray
import psutil
from proctap import ProcessAudioCapture
from PIL import Image, ImageDraw, ImageTk, ImageOps, ImageSequence

BASE = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, '设置.json')
KEY = '#ff00ff'
MAX_IMAGE_SIDE = 900
ASSET_BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOADING_GIF = os.path.join(ASSET_BASE, 'assets', 'Loading.gif')

def center_window(window, width=None, height=None):
    window.update_idletasks()
    width = width or window.winfo_reqwidth()
    height = height or window.winfo_reqheight()
    x = max(0, (window.winfo_screenwidth()-width)//2)
    y = max(0, (window.winfo_screenheight()-height)//2)
    window.geometry(f'{width}x{height}+{x}+{y}')

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

class BeatTracker:
    def __init__(self, rate=48000, chunk=1024, analysis_bias=1.0, fast_bpm_threshold=150, end_silence=5.0, octave_bias=0):
        self.rate, self.chunk, self.analysis_bias = rate, chunk, analysis_bias
        self.fast_bpm_threshold=fast_bpm_threshold
        self.end_silence=end_silence
        self.octave_bias=octave_bias
        self.flux = deque(maxlen=int(20*rate/chunk)); self.history = deque(maxlen=48)
        self.prev = None; self.bpm = 0.; self.level = 0.; self.beat = 0.; self.phase = 0.
        self.last_onset = 0.; self.steps = 0; self.prev_flux = 0.; self.prev_prev_flux = 0.; self.prev_threshold = float('inf')
        self.tempo_candidates = deque(maxlen=6); self.onsets = deque(maxlen=96)
        self.last_signal = 0.; self.last_visual = -1e9; self.last_grid = None
        self.just_locked = False; self.manual_bpm = 0.
        self.shape_target = .12; self.shape = .12; self.beat_strength = .8; self.last_time = 0.; self.song_end = False
        self.ended_bpm = 0.
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
            self.bpm=0.; self.flux.clear(); self.history.clear(); self.tempo_candidates.clear(); self.last_signal=0.
            self.manual_bpm=0.
            self.phase=0.; self.last_grid=None; self.onsets.clear()
            self.shape_target=.12
        # Slowly return toward a slender, tall resting shape between accents.
        self.shape_target += (.12-self.shape_target) * min(1., dt*1.8)
        self.shape += (self.shape_target-self.shape) * min(1., dt*12.)
        spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)))) if len(x) else np.zeros(1)
        if self.prev is None: value = 0.
        else:
            delta = np.maximum(spectrum-self.prev, 0)
            frequencies = np.fft.rfftfreq(len(x), 1/self.rate)
            low = delta[(frequencies >= 40) & (frequencies < 160)]
            mid = delta[(frequencies >= 160) & (frequencies < 1500)]
            value = float((low.mean() if len(low) else 0)*.8 + (mid.mean() if len(mid) else 0)*.2)
        self.prev = spectrum
        threshold = max(.012, float(np.mean(self.history)) + 1.15*float(np.std(self.history))) * self.analysis_bias if len(self.history)>10 else float('inf')
        peak_flux, peak_threshold = self.prev_flux, self.prev_threshold
        onset = (peak_flux > self.prev_prev_flux and peak_flux >= value and
                 peak_flux > peak_threshold and now-self.last_onset > .18 and self.level > .008)
        self.prev_prev_flux, self.prev_flux, self.prev_threshold = peak_flux, value, threshold
        self.history.append(value); self.flux.append(value); self.steps += 1
        if onset:
            self.last_onset = now
            strength = float(np.clip((peak_flux-peak_threshold)/(peak_threshold+1e-6), 0., 3.))
            self.onsets.append((now, strength))
            # 0 = slender/tall, 1 = broad/flat. Keep this as a continuous state.
            self.shape_target = float(np.clip(.18 + .82*(strength/3.), .18, 1.))
            if self.bpm and self.phase:
                period = 60/self.bpm
                error = (now-self.phase+period/2) % period-period/2
                if abs(error) < min(.09, period*.18) and strength > .35:
                    self.phase += error*.12
        if not self.bpm and self.steps % max(1, int(1.5*self.rate/self.chunk)) == 0 and len(self.flux)>6*self.rate/self.chunk:
            v = np.asarray(self.flux); v = v - v.mean(); corr = np.correlate(v, v, mode='full')[len(v)-1:]
            lo=int(60*self.rate/(220*self.chunk)); hi=min(len(corr)-2,int(60*self.rate/(60*self.chunk)))
            if hi>lo and corr[0]>.0001:
                lags=np.arange(lo,hi+1); tempos=60*self.rate/(lags*self.chunk)
                weights=np.exp(-.5*(np.log2(tempos/120)/.9)**2)
                score=corr[lo:hi+1]*weights
                if len(self.onsets)>=8:
                    recent_times=np.array([t for t,_ in self.onsets if now-t<12])
                    if len(recent_times)>=8:
                        intervals=np.diff(recent_times)
                        if len(intervals):
                            periods=60/tempos
                            support=np.exp(-.5*((intervals[:,None]-periods[None,:])/(periods[None,:]*.16))**2).mean(axis=0)
                            score*=.55+.9*support
                lag=lo+int(np.argmax(score))
                if self.octave_bias:
                    other=round(lag*(2 if self.octave_bias==-1 else .5))
                    if lo<=other<=hi and score[other-lo]>=.85*score[lag-lo]:
                        lag=other
                if corr[lag]/corr[0]>.05:
                    den=corr[lag-1]-2*corr[lag]+corr[lag+1]
                    offset=float(np.clip(.5*(corr[lag-1]-corr[lag+1])/den,-.5,.5)) if den else 0
                    candidate=60*self.rate/((lag+offset)*self.chunk); self.tempo_candidates.append(candidate)
                    needed=4
                    if len(self.tempo_candidates)>=needed:
                        recent=list(self.tempo_candidates)[-needed:]; median=float(np.median(recent))
                        if max(abs(v-median) for v in recent) < median*.06:
                            self.bpm=median; self.tempo_candidates.clear()
                            self.align_phase(now)
                            self.last_grid=None; self.just_locked=True
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

class Analyzer:
    def __init__(self, source, events, analysis_bias=1.0, fast_bpm_threshold=150, end_silence=5.0, octave_bias=0):
        self.source, self.events, self.analysis_bias = source, events, analysis_bias
        self.fast_bpm_threshold=fast_bpm_threshold; self.end_silence=end_silence; self.octave_bias=octave_bias; self.reset_epoch=0
        self.manual_bpm=0.; self.last_audible=0.; self.auto_estimate=0.
        self.running = True; self.bpm = 0.; self.level = 0.; self.lastbeat = 0.; self.shape = .12; self.beat_strength = .8; self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
    def stop(self): self.running = False
    def values(self):
        with self.lock: return self.bpm, self.level, self.lastbeat, self.shape, self.beat_strength
    def is_playing(self):
        return bool(self.running and time.monotonic()-self.last_audible < .25)
    def lock_bpm(self, bpm):
        self.manual_bpm=float(bpm)
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
            tracker=BeatTracker(rate,chunk,self.analysis_bias,self.fast_bpm_threshold,self.end_silence,self.octave_bias); pending=np.empty(0,dtype=np.float32); last_data_time=time.monotonic(); song_end_reported=False; ended_without_data=False; seen_epoch=self.reset_epoch
            self.events.put(('status', '正在监听：' + name))
            while self.running:
                if seen_epoch != self.reset_epoch:
                    seen_epoch=self.reset_epoch; tracker=BeatTracker(rate,chunk,self.analysis_bias,self.fast_bpm_threshold,self.end_silence,self.octave_bias)
                    self.manual_bpm=0.; self.last_audible=0.; self.auto_estimate=0.
                    pending=np.empty(0,dtype=np.float32); song_end_reported=False; ended_without_data=False
                    try:
                        while True: audio_queue.get_nowait()
                    except queue.Empty: pass
                    with self.lock: self.bpm=0.; self.lastbeat=0.; self.shape=.12; self.beat_strength=.8
                try: data=audio_queue.get(timeout=.2)
                except queue.Empty:
                    with self.lock: self.level=0
                    if not ended_without_data and time.monotonic()-last_data_time > self.end_silence:
                        ended_without_data=True
                        if tracker.bpm > 0 and not song_end_reported:
                            song_end_reported=True; self.events.put(('song_end', self.auto_estimate or tracker.bpm))
                        tracker=BeatTracker(rate,chunk,self.analysis_bias,self.fast_bpm_threshold,self.end_silence,self.octave_bias); pending=np.empty(0,dtype=np.float32)
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
                    tracker.end_silence=self.end_silence
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
    def __init__(self, app, sprite_id, image_path='', size=240, x=800, y=250):
        self.app, self.id = app, sprite_id
        self.image_path = image_path
        self.original = app.get_image(image_path)
        self.size = max(100, min(450, int(size)))
        self.photo = None
        self.render_key = None
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
        menu.add_command(label='打开主菜单', command=self.app.show_main)
        menu.add_command(label='打开设置', command=self.app.show_settings)
        menu.add_command(label='新增Q弹', command=self.app.add_sprite)
        menu.add_command(label='刷新 BPM', command=self.app.refresh_bpm)
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
        key = (id(original), side, w, h, flash_step, color if flash_step else None, loading_index)
        if key == self.render_key:
            return
        if key in self.app.frame_cache:
            self.photo = self.app.frame_cache[key]
            self.label.config(image=self.photo)
            self.render_key = key
            return
        canvas = Image.new('RGBA', (side, side), (255,0,255,0))
        frame = original.resize((w,h), Image.Resampling.LANCZOS)
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
                ox=max(0,min(side-overlay.width,left+w-overlay.width//2))
                oy=max(0,top-overlay.height//3)
                canvas.alpha_composite(overlay,(ox,oy))
        alpha = canvas.getchannel('A').point(lambda p: 255 if p >= 12 else 0)
        keyed = Image.composite(canvas.convert('RGB'), Image.new('RGB', canvas.size, (255,0,255)), alpha)
        self.photo = ImageTk.PhotoImage(keyed)
        self.label.config(image=self.photo)
        self.app.frame_cache[key] = self.photo
        self.render_key = key

    def record(self):
        return {'id': self.id, 'image': self.image_path, 'size': self.size,
                'x': self.win.winfo_x(), 'y': self.win.winfo_y()}


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Q弹音乐')
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
        self.sprites = []
        self.image_cache = {}
        self.frame_cache = {}
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
        self.shared_image_path = self.config.get('image','')
        self.shared_original = self.get_image(self.shared_image_path)
        self.source_mode = tk.StringVar(value='process')
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
        self.fast_bpm_threshold=tk.IntVar(value=max(80,min(240,int(self.config.get('fast_bpm_threshold',150)))))
        self.amplitude = tk.DoubleVar(value=self.config.get('amplitude',100))
        self.offset = tk.DoubleVar(value=self.config.get('offset',0))
        self.top = tk.BooleanVar(value=self.config.get('top',True))
        self.top_value = self.top.get()
        self.size = tk.IntVar(value=self.config.get('size',240))
        self.flash_enabled = tk.BooleanVar(value=self.config.get('flash_enabled',False))
        self.flash_color = self.config.get('flash_color','#ffffff')
        if not (isinstance(self.flash_color,str) and len(self.flash_color)==7 and self.flash_color.startswith('#')):
            self.flash_color='#ffffff'
        self.flash_duration = tk.DoubleVar(value=float(self.config.get('flash_duration',.55)))
        self.feedback_enabled = tk.BooleanVar(value=self.config.get('feedback_enabled',False))
        self.double_click_close = tk.BooleanVar(value=self.config.get('double_click_close',True))
        self.manual_bpm_text = tk.StringVar()
        self.end_silence = tk.DoubleVar(value=max(1.,min(30.,float(self.config.get('end_silence',5.)))))
        self.status = tk.StringVar(value='请选择音频源，然后点击开始监听')
        self.bpmtext = tk.StringVar(value='BPM：--')
        self.build_main()
        saved = self.config.get('windows')
        if isinstance(saved,list):
            for record in saved:
                if record.get('visible',True):
                    self.make_sprite(record.get('image',''), record.get('size',240),
                                     record.get('x',800), record.get('y',250))
        else:
            self.make_sprite(self.shared_image_path, self.config.get('size',240),
                             self.config.get('x',800), self.config.get('y',250))
        self.refresh_sprite_list()
        self.root.protocol('WM_DELETE_WINDOW',self.request_close)
        self.refresh_sources()
        self.make_tray()
        self.tick()

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

    def build_main(self):
        main = ttk.Frame(self.root,padding=16); main.pack(fill='both',expand=True)
        heading=ttk.Frame(main); heading.pack(fill='x')
        ttk.Label(heading,text='Q弹音乐',font=('Microsoft YaHei UI',18,'bold')).pack(side='left')
        ttk.Button(heading,text='设置',command=self.show_settings).pack(side='right')
        ttk.Label(main,text='选择音频源，然后保持Q弹！').pack(anchor='w',pady=(3,10))
        row=ttk.Frame(main); row.pack(fill='x')
        ttk.Radiobutton(row,text='指定软件进程',variable=self.source_mode,value='process',command=self.refresh_sources).pack(side='left')
        ttk.Radiobutton(row,text='播放设备',variable=self.source_mode,value='device',command=self.refresh_sources).pack(side='left',padx=12)
        ttk.Button(row,text='自动查找网易云',command=self.find_netease).pack(side='right')
        row=ttk.Frame(main); row.pack(fill='x',pady=5)
        ttk.Label(row,text='筛选进程').pack(side='left')
        ttk.Entry(row,textvariable=self.filter_text).pack(side='left',fill='x',expand=True,padx=8)
        self.filter_text.trace_add('write',lambda *_: self.apply_filter())
        row=ttk.Frame(main); row.pack(fill='x')
        self.combo=ttk.Combobox(row,state='readonly'); self.combo.pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='刷新列表',command=self.refresh_sources).pack(side='left',padx=(7,0))
        row=ttk.Frame(main); row.pack(fill='x',pady=(9,6))
        ttk.Button(row,text='开始监听',command=self.start).pack(side='left')
        ttk.Button(row,text='停止',command=self.stop).pack(side='left',padx=5)
        ttk.Button(row,text='停止并校准',command=self.stop_and_rate).pack(side='left',padx=(0,5))
        ttk.Button(row,text='刷新 BPM',command=self.refresh_bpm).pack(side='left')
        ttk.Label(row,textvariable=self.bpmtext,font=('Microsoft YaHei UI',11,'bold')).pack(side='right')
        row=ttk.Frame(main); row.pack(fill='x',pady=(0,4))
        self.manual_lock_button=ttk.Button(row,text='🔒 应用',command=self.apply_manual_bpm)
        self.manual_lock_button.pack(side='right')
        self.manual_bpm_entry=ttk.Entry(row,textvariable=self.manual_bpm_text,width=9)
        self.manual_bpm_entry.pack(side='right',padx=(0,5))
        ttk.Label(row,text='手动 BPM').pack(side='right',padx=(0,5))
        row=ttk.Frame(main); row.pack(fill='x',pady=(7,3))
        ttk.Label(row,text='图片模式').pack(side='left')
        ttk.Radiobutton(row,text='使用统一图片',variable=self.image_mode,value='uniform',command=self.set_image_mode).pack(side='left',padx=8)
        ttk.Radiobutton(row,text='使用多种图片',variable=self.image_mode,value='multiple',command=self.set_image_mode).pack(side='left')
        row=ttk.Frame(main); row.pack(fill='x',pady=4)
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
        tk.Scale(row,variable=self.amplitude,from_=0,to=150,resolution=5,orient='horizontal',showvalue=False,
                 highlightthickness=0).grid(row=0,column=1,sticky='ew',padx=8)
        ttk.Label(row,textvariable=self.amplitude,width=7,anchor='e').grid(row=0,column=2)
        ttk.Label(row,text='%').grid(row=0,column=3,padx=(4,0))
        row=ttk.Frame(main); row.pack(fill='x',pady=5); row.columnconfigure(1,weight=1)
        ttk.Label(row,text='节奏偏移',width=12,anchor='w').grid(row=0,column=0,sticky='w')
        tk.Scale(row,variable=self.offset,from_=-.25,to=.25,resolution=.01,orient='horizontal',showvalue=False,
                 highlightthickness=0).grid(row=0,column=1,sticky='ew',padx=8)
        ttk.Label(row,textvariable=self.offset,width=7,anchor='e').grid(row=0,column=2)
        ttk.Label(row,text='秒').grid(row=0,column=3,padx=(4,0))
        ttk.Checkbutton(main,text='歌曲结束后询问节奏与 BPM 是否匹配（用于校准分析）',variable=self.feedback_enabled,command=self.save).pack(anchor='w',pady=(2,3))
        ttk.Label(main,textvariable=self.status,wraplength=550,foreground='#34596a').pack(anchor='w')

    def show_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify(); self.settings_window.lift(); return
        window=tk.Toplevel(self.root); self.settings_window=window
        window.title('Q弹音乐 · 设置'); window.resizable(False,False)
        main=ttk.Frame(window,padding=16); main.pack(fill='both',expand=True)
        ttk.Label(main,text='设置',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w')
        row=ttk.Frame(main); row.pack(fill='x',pady=(12,5))
        ttk.Label(row,text='动画帧率').pack(side='left')
        ttk.Combobox(row,textvariable=self.fps,values=('15','24','30','45','60','90','120','144'),state='readonly',width=6).pack(side='left',padx=12)
        ttk.Label(row,text='帧/秒').pack(side='left')
        row=ttk.Frame(main); row.pack(fill='x',pady=5)
        ttk.Label(row,text='最高弹跳速度',width=16).pack(side='left')
        tk.Scale(row,variable=self.fast_bpm_threshold,from_=80,to=240,resolution=5,
                 orient='horizontal',length=250,showvalue=False,highlightthickness=0,
                 command=self.set_fast_threshold).pack(side='left',padx=8)
        ttk.Label(row,textvariable=self.fast_bpm_threshold,width=4,anchor='e').pack(side='left')
        ttk.Label(row,text='BPM').pack(side='left',padx=(3,0))
        row=ttk.Frame(main); row.pack(fill='x',pady=5)
        ttk.Checkbutton(row,text='BPM 锁定时闪色提示',variable=self.flash_enabled,command=self.save).pack(side='left')
        ttk.Button(row,text='选择颜色',command=self.choose_flash_color).pack(side='left',padx=8)
        self.color_preview=tk.Label(row,bg=self.flash_color,width=3,relief='solid',bd=1); self.color_preview.pack(side='left')
        row=ttk.Frame(main); row.pack(fill='x',pady=3)
        ttk.Label(row,text='渐隐时间',width=16).pack(side='left')
        tk.Scale(row,variable=self.flash_duration,from_=.1,to=2.,resolution=.05,orient='horizontal',length=250,
                 showvalue=False,highlightthickness=0).pack(side='left',padx=8)
        ttk.Label(row,textvariable=self.flash_duration,width=4,anchor='e').pack(side='left')
        ttk.Label(row,text='秒').pack(side='left',padx=(3,0))
        row=ttk.Frame(main); row.pack(fill='x',pady=3)
        ttk.Label(row,text='歌曲结束静音阈值',width=16).pack(side='left')
        tk.Scale(row,variable=self.end_silence,from_=1,to=30,resolution=.5,
                 orient='horizontal',length=250,showvalue=False,highlightthickness=0,
                 command=self.set_end_silence).pack(side='left',padx=8)
        ttk.Label(row,textvariable=self.end_silence,width=4,anchor='e').pack(side='left')
        ttk.Label(row,text='秒').pack(side='left',padx=(3,0))
        ttk.Checkbutton(main,text='双击图片时快速关闭该图片',variable=self.double_click_close,command=self.save).pack(anchor='w',pady=(4,0))
        ttk.Separator(main).pack(fill='x',pady=12)
        ttk.Label(main,text='点击主窗口 X 时').pack(anchor='w')
        row=ttk.Frame(main); row.pack(fill='x',pady=5)
        for label,value in [('隐藏到系统托盘','hide'),('直接退出','quit'),('每次询问','ask')]:
            ttk.Radiobutton(row,text=label,variable=self.close_action,value=value,command=self.save).pack(side='left',padx=(0,8))
        ttk.Label(main,text='选择“每次询问”后，可在询问框中勾选“不再询问”。',foreground='#666666').pack(anchor='w')
        ttk.Separator(main).pack(fill='x',pady=12)
        ttk.Button(main,text='清除学习与对轨数据',command=self.clear_analysis_data).pack(anchor='w')
        ttk.Label(main,text='保留图片、动画和窗口设置；重置节奏反馈、校准记录与当前 BPM。',wraplength=430,foreground='#666666').pack(anchor='w',pady=6)
        window.protocol('WM_DELETE_WINDOW',lambda: (self.save(),window.withdraw()))
        center_window(window, 500)
        window.lift()

    def request_close(self):
        action=self.close_action.get()
        if action=='hide': self.hide_main()
        elif action=='quit': self.quit()
        else:
            dialog=tk.Toplevel(self.root); dialog.title('关闭 Q弹音乐'); dialog.resizable(False,False); dialog.transient(self.root)
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
            center_window(dialog)
            dialog.lift(); dialog.grab_set()

    def show_main(self):
        self.root.deiconify(); self.root.lift(); self.root.focus_force()
    def get_image(self, path):
        if not path:
            if not hasattr(self,'default_image'): self.default_image=slime()
            return self.default_image
        if path not in self.image_cache:
            self.image_cache[path]=SpriteWindow.load_image(path)
        return self.image_cache[path]
    def prune_image_cache(self):
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

    def make_sprite(self, image='', size=240, x=800, y=250):
        sprite=SpriteWindow(self,self.next_sprite_id,image,size,x,y)
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
                break
    def on_sprite_selected(self, event=None):
        selection=self.sprite_list.curselection()
        if selection:
            sprite=self.sprites[selection[0]]
            self.selected_id=sprite.id; self.size.set(sprite.size)
    def refresh_sprite_list(self):
        self.sprite_list.delete(0,tk.END)
        for sprite in self.sprites:
            path=self.shared_image_path if self.image_mode.get()=='uniform' else sprite.image_path
            name=os.path.basename(path) if path else '默认图'
            self.sprite_list.insert(tk.END,f'图片 {sprite.id} · {name}')
        if self.selected_id is not None: self.select_sprite(self.selected_id)
    def add_sprite(self):
        path=''
        if self.image_mode.get()=='multiple':
            path=filedialog.askopenfilename(parent=self.root,title='为新窗口选择图片（取消则使用默认图）',filetypes=[('图片','*.png *.jpg *.jpeg *.webp *.bmp *.gif'),('所有文件','*.*')])
        x=800+35*len(self.sprites); y=250+35*len(self.sprites)
        sprite=self.make_sprite(path,self.size.get(),x,y)
        self.refresh_sprite_list(); self.select_sprite(sprite.id); self.save()
    def import_image(self):
        path=filedialog.askopenfilename(parent=self.root,title='导入图片',filetypes=[('图片','*.png *.jpg *.jpeg *.webp *.bmp *.gif'),('所有文件','*.*')])
        if not path: return
        try:
            self.image_cache.pop(path,None)
            original=self.get_image(path)
            if self.image_mode.get()=='uniform': self.shared_image_path=path; self.shared_original=original
            else:
                sprite=self.selected_sprite()
                if not sprite: sprite=self.make_sprite()
                sprite.image_path=path; sprite.original=original
            self.prune_image_cache(); self.refresh_sprite_list(); self.save()
        except Exception as error: messagebox.showerror('图片导入失败',str(error),parent=self.root)
    def set_image_mode(self):
        self.refresh_sprite_list(); self.save()
    def close_selected_sprite(self):
        sprite=self.selected_sprite()
        if sprite: self.close_sprite(sprite.id)
    def close_sprite(self, sprite_id):
        sprite=next((s for s in self.sprites if s.id==sprite_id),None)
        if sprite:
            sprite.win.destroy(); self.sprites.remove(sprite)
            if self.selected_id==sprite_id: self.selected_id=self.sprites[0].id if self.sprites else None
            self.prune_image_cache(); self.refresh_sprite_list(); self.save()
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
    def set_fast_threshold(self,value=None):
        if self.analyzer:
            self.analyzer.fast_bpm_threshold=self.fast_bpm_threshold.get()
        self.save()
    def clear_manual_bpm(self):
        self.manual_bpm_text.set('')
        self.manual_bpm_entry.state(['!disabled'])
        self.manual_lock_button.state(['!disabled'])
        self.manual_lock_button.config(text='🔒 应用')
        if self.analyzer: self.analyzer.manual_bpm=0.
    def record_bpm_example(self,estimated,truth,source):
        examples=self.config.setdefault('bpm_examples',[])
        examples.append({'estimated':round(estimated,2),'actual':round(truth,2),'source':source})
        del examples[:-50]
        if self.analyzer:
            self.analyzer.octave_bias=learned_octave_bias(examples)
            if source=='feedback' and not self.analyzer.is_playing():
                self.analyzer.reset_epoch+=1
    def apply_manual_bpm(self):
        if not self.analyzer or not self.analyzer.is_playing():
            self.status.set('请在音乐播放且 BPM 已识别后再上锁。'); return
        estimated=self.analyzer.values()[0]
        if not estimated:
            self.status.set('请等待 BPM 识别完成后再上锁。'); return
        try: truth=float(self.manual_bpm_text.get().strip())
        except ValueError: truth=0.
        if not math.isfinite(truth) or not 40<=truth<=300:
            messagebox.showerror('BPM 输入错误','请输入 40 到 300 之间的 BPM。',parent=self.root); return
        self.record_bpm_example(estimated,truth,'live')
        self.analyzer.lock_bpm(truth)
        self.manual_bpm_entry.state(['disabled'])
        self.manual_lock_button.config(text='🔒 已锁定')
        self.manual_lock_button.state(['disabled'])
        self.status.set(f'本首歌曲已按 {truth:g} BPM 锁定，鼓点将继续用于对轨。')
        self.save()
    def clear_analysis_data(self):
        self.analysis_bias=1.
        self.config.pop('feedback_counts',None); self.config.pop('tempo_corrections',None)
        self.config.pop('bpm_examples',None); self.offset.set(0)
        self.flash_started=-1e9
        if self.analyzer:
            self.analyzer.analysis_bias=1.; self.analyzer.reset_epoch+=1
        self.clear_manual_bpm()
        self.status.set('学习记录、BPM 锁定和对轨状态已清除。')
        self.save()
    def choose_flash_color(self):
        _,chosen=colorchooser.askcolor(color=self.flash_color,parent=self.settings_window,title='选择 BPM 锁定提示颜色')
        if chosen:
            self.flash_color=chosen; self.color_preview.config(bg=chosen); self.save()

    def find_netease(self):
        self.source_mode.set('process'); self.filter_text.set('cloudmusic'); self.refresh_sources()
        targets=[p for p in self.all_sources if p[1].lower()=='cloudmusic.exe']
        if not targets:
            self.status.set('未找到网易云音乐，请先打开播放器并开始播放。'); return
        self.status.set('正在检测网易云声音，请保持音乐播放……')
        def worker():
            totals={pid:[0.,0] for pid,_ in targets}; taps=[]
            try:
                for pid,_ in targets:
                    try:
                        def collect(data,frames,pid=pid):
                            x=np.frombuffer(data,dtype=np.float32)
                            if x.size: totals[pid][0]+=float(np.dot(x,x)); totals[pid][1]+=len(x)
                        tap=ProcessAudioCapture(pid,on_data=collect); tap.start(); taps.append(tap)
                    except Exception: pass
                time.sleep(2)
            finally:
                for tap in taps:
                    try: tap.close()
                    except Exception: pass
            pid=max(totals,key=lambda n: totals[n][0]/max(1,totals[n][1]))
            self.events.put(('found_process',(pid,totals[pid][0]/max(1,totals[pid][1]))))
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
        i=self.combo.current()
        if i<0: messagebox.showwarning('音频源','请先选择音频源。',parent=self.root); return
        self.stop(); source=self.sources[i]; mode=self.source_mode.get()
        octave_bias=learned_octave_bias(self.config.get('bpm_examples',[]))
        self.analyzer=Analyzer((mode,source),self.events,self.analysis_bias,self.fast_bpm_threshold.get(),self.end_silence.get(),octave_bias)
        self.config['process' if mode=='process' else 'device']=source[1]
        self.save()
    def stop(self):
        if self.analyzer: self.analyzer.stop(); self.analyzer=None
        self.clear_manual_bpm()
        self.bpmtext.set('BPM：--'); self.status.set('已停止监听')
    def stop_and_rate(self):
        bpm=(self.analyzer.auto_estimate or self.analyzer.values()[0]) if self.analyzer else 0.
        self.stop()
        if bpm: self.song_feedback(bpm)
        else: self.status.set('已停止监听；本次没有可评价的 BPM 结果。')

    def song_feedback(self,bpm):
        if self.feedback_dialog and self.feedback_dialog.winfo_exists(): return
        dialog=tk.Toplevel(self.root); self.feedback_dialog=dialog
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
        center_window(dialog)
        dialog.lift()

    def save(self):
        try:
            self.config.update(image=self.shared_image_path, image_mode=self.image_mode.get(),
                windows=[sprite.record() for sprite in self.sprites], top=self.top.get(),
                main_geometry=f'{max(610,self.root.winfo_width())}x{max(610,self.root.winfo_height())}',
                size=self.size.get(), fps=int(self.fps.get()), amplitude=self.amplitude.get(),
                offset=self.offset.get(), feedback_enabled=self.feedback_enabled.get(),
                end_silence=self.end_silence.get(),
                fast_bpm_threshold=self.fast_bpm_threshold.get(),
                analysis_bias=self.analysis_bias, double_click_close=self.double_click_close.get(),
                flash_enabled=self.flash_enabled.get(), flash_color=self.flash_color,
                flash_duration=self.flash_duration.get(), close_action=self.close_action.get())
            with open(CONFIG,'w',encoding='utf-8') as file:
                json.dump(self.config,file,ensure_ascii=False,indent=2)
        except Exception: pass
    def make_tray(self):
        icon=slime(); icon.thumbnail((64,64))
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
                        self.filter_text.set('cloudmusic'); self.refresh_sources()
                        index=next((i for i,p in enumerate(self.sources) if p[0]==pid),-1)
                        if index>=0: self.combo.current(index); self.status.set('已找到有声音的网易云进程，请点击开始监听。')
                        else: self.status.set('网易云进程已变化，请重新查找。')
                    elif self.source_mode.get()=='process':
                        self.status.set('未检测到网易云声音，请确认正在播放并重新查找。')
                elif kind=='song_end':
                    if self.feedback_enabled.get(): self.song_feedback(value)
                elif kind=='manual_unlock': self.clear_manual_bpm()
                elif kind=='bpm_locked':
                    if self.flash_enabled.get(): self.flash_started=time.monotonic()
                    self.status.set('BPM 已锁定：'+str(round(value)))
                elif kind=='status': self.status.set(value)
                elif kind=='error': self.status.set(value); self.bpmtext.set('BPM：--')
        except queue.Empty: pass
        bpm,level,beat,shape,strength=self.analyzer.values() if self.analyzer else (0,0,0,.12,.8)
        playing=bool(self.analyzer and self.analyzer.is_playing())
        self.bpmtext.set('BPM：'+(str(round(bpm)) if bpm and playing else ('分析中' if playing else ('等待播放' if self.analyzer else '--'))))
        now=time.monotonic(); dt=min(.2,max(.001,now-self.last_frame_time)); self.last_frame_time=now
        active=bool(playing and level>.002 and beat)
        amp=max(0.,min(1.5,self.amplitude.get()/100)) if active else 0.
        shift=self.offset.get(); event_time=beat+shift if beat else -1e9
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
        self.tick_job=self.root.after(max(1,round(1000/int(self.fps.get()))),self.tick)

if __name__ == '__main__':
    try: App().root.mainloop()
    except Exception:
        with open(os.path.join(BASE, '错误日志.txt'), 'w', encoding='utf-8') as f: traceback.print_exc(file=f)
        raise




