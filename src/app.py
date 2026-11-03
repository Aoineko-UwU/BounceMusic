import os, sys, time, threading, queue, json, math, traceback
from collections import deque
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import pyaudiowpatch as pa
import pystray
import psutil
from proctap import ProcessAudioCapture
from PIL import Image, ImageDraw, ImageTk, ImageOps

BASE = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, '设置.json')
KEY = '#ff00ff'

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

class BeatTracker:
    def __init__(self, rate=48000, chunk=1024, analysis_bias=1.0):
        self.rate, self.chunk, self.analysis_bias = rate, chunk, analysis_bias
        self.flux = deque(maxlen=int(20*rate/chunk)); self.history = deque(maxlen=48)
        self.prev = None; self.bpm = 0.; self.level = 0.; self.beat = 0.; self.phase = 0.
        self.last_onset = 0.; self.steps = 0; self.prev_flux = 0.; self.prev_prev_flux = 0.; self.prev_threshold = float('inf')
        self.tempo_candidates = deque(maxlen=6); self.last_signal = 0.; self.last_visual = -1e9
        self.shape_target = .12; self.shape = .12; self.beat_strength = .8; self.last_time = 0.; self.song_end = False
    def feed(self, x, now):
        dt = min(.2, max(.001, now-self.last_time)) if self.last_time else .02
        self.last_time = now
        rms = float(np.sqrt(np.mean(x*x))) if len(x) else 0.
        self.level = max(min(1., rms*7), self.level*.94)
        if rms > .001:
            self.last_signal = now; self.song_end = False
        elif self.last_signal and now-self.last_signal > 5:
            self.song_end = True
            self.bpm=0.; self.flux.clear(); self.history.clear(); self.tempo_candidates.clear(); self.last_signal=0.
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
                 peak_flux > peak_threshold and now-self.last_onset > (max(.20, .55*60/self.bpm) if self.bpm else .20) and self.level > .008)
        self.prev_prev_flux, self.prev_flux, self.prev_threshold = peak_flux, value, threshold
        self.history.append(value); self.flux.append(value); self.steps += 1
        if onset:
            self.last_onset = now
            strength = float(np.clip((peak_flux-peak_threshold)/(peak_threshold+1e-6), 0., 3.))
            # 0 = slender/tall, 1 = broad/flat. Keep this as a continuous state.
            self.shape_target = float(np.clip(.18 + .82*(strength/3.), .18, 1.))
            # Each accepted beat starts a fresh animation cycle; fast tracks skip only beats that would overlap.
            if now-self.last_visual >= .39:
                self.beat = now; self.last_visual = now; self.beat_strength = float(np.clip(.45 + .55*(strength/3.), .45, 1.))
        if self.steps % max(1, int(1.5*self.rate/self.chunk)) == 0 and len(self.flux)>6*self.rate/self.chunk:
            v = np.asarray(self.flux); v = v - v.mean(); corr = np.correlate(v, v, mode='full')[len(v)-1:]
            lo=int(60*self.rate/(180*self.chunk)); hi=min(len(corr)-2,int(60*self.rate/(70*self.chunk)))
            if hi>lo and corr[0]>.0001:
                lags=np.arange(lo,hi+1); tempos=60*self.rate/(lags*self.chunk)
                weights=np.exp(-.5*(np.log2(tempos/120)/.9)**2)
                if self.bpm: weights *= .7 + .3*np.exp(-.5*(np.log2(tempos/self.bpm)/.13)**2)
                score=corr[lo:hi+1]*weights; lag=lo+int(np.argmax(score))
                if corr[lag]/corr[0]>.05:
                    den=corr[lag-1]-2*corr[lag]+corr[lag+1]
                    offset=float(np.clip(.5*(corr[lag-1]-corr[lag+1])/den,-.5,.5)) if den else 0
                    candidate=60*self.rate/((lag+offset)*self.chunk); self.tempo_candidates.append(candidate)
                    needed=4 if not self.bpm else 6
                    if len(self.tempo_candidates)>=needed:
                        recent=list(self.tempo_candidates)[-needed:]; median=float(np.median(recent))
                        if max(abs(v-median) for v in recent) < median*.06:
                            if not self.bpm or abs(median-self.bpm)>self.bpm*.09:
                                self.bpm=median; self.tempo_candidates.clear()
        return self.bpm, self.level, self.beat, float(np.clip(self.shape, .05, 1.0)), self.song_end, self.beat_strength

class Analyzer:
    def __init__(self, source, events, analysis_bias=1.0):
        self.source, self.events, self.analysis_bias = source, events, analysis_bias
        self.running = True; self.bpm = 0.; self.level = 0.; self.lastbeat = 0.; self.shape = .12; self.beat_strength = .8; self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
    def stop(self): self.running = False
    def values(self):
        with self.lock: return self.bpm, self.level, self.lastbeat, self.shape, self.beat_strength
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
            tracker=BeatTracker(rate,chunk,self.analysis_bias); pending=np.empty(0,dtype=np.float32); last_data_time=time.monotonic(); song_end_reported=False
            self.events.put(('status', '正在监听：' + name))
            while self.running:
                try: data=audio_queue.get(timeout=.2)
                except queue.Empty:
                    with self.lock: self.level=0
                    if time.monotonic()-last_data_time > 5:
                        if tracker.bpm > 0 and not song_end_reported:
                            song_end_reported=True; self.events.put(('song_end', tracker.bpm))
                        tracker=BeatTracker(rate,chunk,self.analysis_bias); pending=np.empty(0,dtype=np.float32)
                        with self.lock: self.bpm=0.; self.lastbeat=0.; self.shape=.12; self.beat_strength=.8
                    continue
                last_data_time=time.monotonic()
                x=np.frombuffer(data,dtype=np.float32)
                if len(x)%channels: continue
                x=x.reshape(-1,channels).mean(axis=1); pending=np.concatenate((pending,x))
                while len(pending)>=chunk:
                    frame=pending[:chunk]; pending=pending[chunk:]
                    now=time.monotonic()-len(pending)/rate
                    tracker.analysis_bias=self.analysis_bias
                    bpm,level,beat,shape,song_end,beat_strength=tracker.feed(frame,now)
                    with self.lock: self.bpm,self.level,self.lastbeat,self.shape,self.beat_strength=bpm,level,beat,shape,beat_strength
                    if song_end and not song_end_reported:
                        song_end_reported=True; self.events.put(('song_end', bpm))
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

class App:
    def __init__(self):
        self.root = tk.Tk(); self.root.title('Q弹音乐'); self.root.geometry('570x565'); self.root.resizable(False, False)
        self.events = queue.Queue(); self.analyzer = None; self.analysis_bias = float(self.config.get('analysis_bias', 1.0)) if hasattr(self, 'config') else 1.0; self.anim_sx = 1.0; self.anim_sy = 1.0; self.last_frame_time = time.monotonic(); self.dev = []; self.sources = []; self.mode = tk.StringVar(value='process'); self.filter_text = tk.StringVar(); self.all_sources = []; self.drag = None; self.tray = None; self.photo = None
        try:
            with open(CONFIG, encoding='utf-8') as f: self.config = json.load(f)
        except Exception: self.config = {}
        self.analysis_bias = float(self.config.get('analysis_bias', 1.0)); self.feedback_enabled = tk.BooleanVar(value=bool(self.config.get('feedback_enabled', False)))
        self.original = slime(); self.image_path = self.config.get('image', '')
        if self.image_path:
            try: self.original = Image.open(self.image_path).convert('RGBA')
            except Exception: self.image_path = ''
        self.fps = tk.StringVar(value=str(self.config.get('fps', 30)));
        if self.fps.get() not in ('15','24','30','45','60','90','120','144'): self.fps.set('30')
        self.amplitude = tk.DoubleVar(value=self.config.get('amplitude', 100)); self.offset = tk.DoubleVar(value=self.config.get('offset', 0)); self.top = tk.BooleanVar(value=self.config.get('top', True)); self.size = tk.IntVar(value=self.config.get('size', 240)); self.status = tk.StringVar(value='请选择播放设备，然后点击开始监听'); self.bpmtext = tk.StringVar(value='BPM：分析中')
        self.top_value = self.top.get(); self.win = tk.Toplevel(self.root); self.win.overrideredirect(True); self.win.configure(bg=KEY); self.win.wm_attributes('-transparentcolor', KEY); self.win.attributes('-topmost', self.top.get())
        self.label = tk.Label(self.win, bg=KEY, bd=0); self.label.pack(); self.label.bind('<ButtonPress-1>', self.press); self.label.bind('<B1-Motion>', self.move); self.label.bind('<Button-3>', lambda e: self.show_settings()); self.label.bind('<MouseWheel>', self.wheel)
        self.win.geometry('+%d+%d' % (self.config.get('x', 800), self.config.get('y', 250)))
        main = ttk.Frame(self.root, padding=16); main.pack(fill='both', expand=True)
        ttk.Label(main, text='Q弹音乐', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(main, text='选择音乐软件或播放设备，让图片跟随强弱节奏连续变形。').pack(anchor='w', pady=(2, 8))
        modes = ttk.Frame(main); modes.pack(fill='x', pady=(0, 5))
        ttk.Radiobutton(modes, text='指定软件进程', variable=self.mode, value='process', command=self.refresh).pack(side='left')
        ttk.Radiobutton(modes, text='播放设备（系统声音）', variable=self.mode, value='device', command=self.refresh).pack(side='left', padx=14)
        ttk.Button(modes, text='自动查找网易云', command=self.find_netease).pack(side='right')
        search = ttk.Frame(main); search.pack(fill='x', pady=(0, 5))
        ttk.Label(search, text='筛选进程名').pack(side='left'); ttk.Entry(search, textvariable=self.filter_text).pack(side='left', fill='x', expand=True, padx=(8,0))
        self.filter_text.trace_add('write', lambda *_: self.apply_filter())
        row = ttk.Frame(main); row.pack(fill='x'); self.combo = ttk.Combobox(row, state='readonly'); self.combo.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='刷新', width=6, command=self.refresh).pack(side='left', padx=(6, 0))
        row = ttk.Frame(main); row.pack(fill='x', pady=10)
        ttk.Button(row, text='开始监听', command=self.start).pack(side='left'); ttk.Button(row, text='停止', command=self.stop).pack(side='left', padx=7)
        ttk.Button(row, text='导入图片', command=self.import_image).pack(side='left'); ttk.Label(row, textvariable=self.bpmtext, font=('Microsoft YaHei UI', 11, 'bold')).pack(side='right')
        row = ttk.Frame(main); row.pack(fill='x', pady=3)
        ttk.Label(row, text='图片大小').pack(side='left'); ttk.Scale(row, from_=100, to=450, variable=self.size, orient='horizontal').pack(side='left', fill='x', expand=True, padx=12)
        ttk.Checkbutton(row, text='图片置顶', variable=self.top, command=self.set_top).pack(side='left')
        row = ttk.Frame(main); row.pack(fill='x', pady=(5, 0))
        ttk.Label(row, text='动画帧率').pack(side='left'); ttk.Combobox(row, textvariable=self.fps, values=('15','24','30','45','60','90','120','144'), state='readonly', width=5).pack(side='left', padx=10); ttk.Label(row, text='帧/秒').pack(side='left')
        row = ttk.Frame(main); row.pack(fill='x')
        ttk.Label(row, text='动画幅度').pack(side='left'); tk.Scale(row, variable=self.amplitude, from_=0, to=150, resolution=5, orient='horizontal', showvalue=True, length=320).pack(side='left', padx=8); ttk.Label(row, text='%').pack(side='left')
        row = ttk.Frame(main); row.pack(fill='x')
        ttk.Label(row, text='节奏偏移').pack(side='left'); tk.Scale(row, variable=self.offset, from_=-.25, to=.25, resolution=.01, orient='horizontal', showvalue=True, length=320).pack(side='left', padx=8); ttk.Label(row, text='秒').pack(side='left')
        ttk.Label(main, text='负值提前（根据稳定节奏预测）；正值延后。', foreground='#666666').pack(anchor='w')
        ttk.Checkbutton(main, text='启用歌曲结束反馈（播放结束后询问动画是否正确）', variable=self.feedback_enabled, command=self.save).pack(anchor='w', pady=(4, 0))
        ttk.Label(main, textvariable=self.status, wraplength=470, foreground='#34596a').pack(anchor='w', pady=(10, 0))
        ttk.Label(main, text='强拍会过渡到扁，轻拍会过渡到瘦高；形变连续衔接，不会每拍重置。拖动图片可移动，滚轮缩放，右键打开设置。', wraplength=500, foreground='#666666').pack(anchor='w', pady=(6, 0))
        self.root.protocol('WM_DELETE_WINDOW', self.hide_settings); self.refresh(); self.make_tray(); self.tick()
    def find_netease(self):
        self.mode.set('process'); self.filter_text.set('cloudmusic'); self.refresh()
        targets=[p for p in self.all_sources if p[1].lower()=='cloudmusic.exe']
        if not targets:
            self.status.set('未找到网易云音乐，请先打开播放器并开始播放。'); return
        self.status.set('正在检测网易云声音，请保持音乐播放……')
        def worker():
            totals={pid:[0.,0] for pid,_ in targets}; taps=[]
            try:
                for pid,_ in targets:
                    try:
                        def collect(data, frames, pid=pid):
                            x=np.frombuffer(data, dtype=np.float32)
                            if x.size: totals[pid][0]+=float(np.dot(x,x)); totals[pid][1]+=len(x)
                        tap=ProcessAudioCapture(pid,on_data=collect); tap.start(); taps.append(tap)
                    except Exception: pass
                time.sleep(2)
            finally:
                for tap in taps:
                    try: tap.close()
                    except Exception: pass
            pid=max(totals, key=lambda n: totals[n][0]/max(1,totals[n][1]))
            power=totals[pid][0]/max(1,totals[pid][1])
            self.events.put(('found_process',(pid,power)))
        threading.Thread(target=worker,daemon=True).start()
    def refresh(self):
        try:
            self.all_sources = processes() if self.mode.get() == 'process' else devices()
            self.apply_filter()
        except Exception as e: self.status.set('获取音频源失败：' + str(e))
    def apply_filter(self):
        if not hasattr(self, 'combo'): return
        if self.mode.get() == 'process':
            key=self.filter_text.get().strip().lower()
            self.sources=[p for p in self.all_sources if key in p[1].lower() or key in str(p[0])]
            self.combo['values']=[f'{name}   (PID {pid})' for pid,name in self.sources]
            wanted=self.config.get('process', '')
            index=next((i for i,(_,name) in enumerate(self.sources) if name.lower()==wanted.lower()),0)
        else:
            self.sources=self.all_sources; self.combo['values']=[d[1] for d in self.sources]
            wanted=self.config.get('device', '')
            index=next((i for i,d in enumerate(self.sources) if d[1]==wanted),0)
        if self.sources: self.combo.current(index)
        else: self.combo.set(''); self.status.set('没有匹配的音频源，请打开音乐软件或清除筛选后刷新。')
    def start(self):
        i=self.combo.current()
        if i<0: messagebox.showwarning('音频源','请先选择音频源。'); return
        self.stop(); source=self.sources[i]; mode=self.mode.get()
        self.analyzer=Analyzer((mode,source),self.events,self.analysis_bias)
        self.config['process' if mode=='process' else 'device']=source[1]; self.save()
    def stop(self):
        if self.analyzer: self.analyzer.stop(); self.analyzer = None
        self.bpmtext.set('BPM：--'); self.status.set('已停止监听')
    def import_image(self):
        path = filedialog.askopenfilename(title='选择图片', filetypes=[('图片', '*.png *.jpg *.jpeg *.webp *.bmp *.gif'), ('所有文件', '*.*')])
        if path:
            try:
                im = Image.open(path); im.seek(0); self.original = ImageOps.exif_transpose(im).convert('RGBA'); self.image_path = path; self.save()
            except Exception as e: messagebox.showerror('图片读取失败', str(e))
    def song_feedback(self, bpm):
        answer = messagebox.askyesno('动画是否正确', '这首歌似乎已经播放结束。刚才的动画节奏是否合适？\n\n选择“是”会保持并略微增强当前分析偏好；选择“否”会降低误触发敏感度。')
        if answer:
            self.analysis_bias = max(.82, self.analysis_bias - .03);
            if self.analyzer: self.analyzer.analysis_bias = self.analysis_bias; self.status.set('已记录：动画合适，继续保持当前分析偏好。')
        else:
            self.analysis_bias = min(1.45, self.analysis_bias + .08);
            if self.analyzer: self.analyzer.analysis_bias = self.analysis_bias; self.status.set('已记录：下次将减少弱节奏误触发。')
        self.save()
    def set_top(self): self.top_value = self.top.get(); self.win.attributes('-topmost', self.top_value); self.save()
    def wheel(self, e):
        self.size.set(max(100, min(450, self.size.get() + (20 if e.delta > 0 else -20)))); self.save()
    def press(self, e): self.drag = (e.x_root-self.win.winfo_x(), e.y_root-self.win.winfo_y())
    def move(self, e):
        if self.drag: self.win.geometry('+%d+%d' % (max(0,e.x_root-self.drag[0]), max(0,e.y_root-self.drag[1])))
    def save(self):
        try:
            self.config.update(image=self.image_path, size=self.size.get(), top=self.top.get(), fps=int(self.fps.get()), amplitude=self.amplitude.get(), offset=self.offset.get(), feedback_enabled=self.feedback_enabled.get(), analysis_bias=self.analysis_bias, x=self.win.winfo_x(), y=self.win.winfo_y())
            with open(CONFIG, 'w', encoding='utf-8') as f: json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception: pass
    def make_tray(self):
        icon = slime(); icon.thumbnail((64,64))
        self.tray = pystray.Icon('Q弹音乐', icon, 'Q弹音乐', menu=pystray.Menu(pystray.MenuItem('打开设置', lambda: self.events.put(('show','')), default=True), pystray.MenuItem('图片置顶', lambda: self.events.put(('top','')), checked=lambda item: self.top_value), pystray.MenuItem('退出', lambda: self.events.put(('quit','')))))
        threading.Thread(target=self.tray.run, daemon=True).start()
    def show_settings(self): self.root.deiconify(); self.root.lift(); self.root.focus_force()
    def hide_settings(self): self.save(); self.root.withdraw()
    def quit(self):
        self.save(); self.stop(); self.tray.stop(); self.root.destroy()
    def tick(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'show': self.show_settings()
                elif kind == 'top': self.top.set(not self.top.get()); self.set_top()
                elif kind == 'quit': self.quit(); return
                elif kind == 'found_process':
                    pid, power = value
                    if self.mode.get() == 'process' and power > 1e-9:
                        self.filter_text.set('cloudmusic'); self.refresh()
                        index = next((i for i,p in enumerate(self.sources) if p[0]==pid), -1)
                        if index >= 0: self.combo.current(index); self.status.set('已找到有声音的网易云进程，请点击开始监听。')
                        else: self.status.set('网易云进程已变化，请重新查找。')
                    elif self.mode.get() == 'process': self.status.set('未检测到网易云声音，请确认正在播放并重新查找。')
                elif kind == 'song_end':
                    if self.feedback_enabled.get(): self.song_feedback(value)
                elif kind == 'status': self.status.set(value)
                elif kind == 'error': self.status.set(value); self.bpmtext.set('BPM：--')
        except queue.Empty: pass
        bpm, level, beat, shape, beat_strength = self.analyzer.values() if self.analyzer else (0,0,0,.12,.8)
        self.bpmtext.set('BPM：' + (str(int(bpm)) if bpm and level > .002 else ('分析中' if self.analyzer else '--')))
        # Every accepted beat resets this keyframed cycle. The cycle itself is smooth, matching the reference GIF.
        now=time.monotonic(); dt=min(.2, max(.001, now-self.last_frame_time)); self.last_frame_time=now
        active = bool(self.analyzer and level > .002 and beat)
        amp=max(0., min(1.5, self.amplitude.get()/100)) if active else 0.
        event_time=beat + self.offset.get() if beat else -1e9
        age=now-event_time
        period=60/bpm if bpm and bpm>0 else .65
        cycle=min(.82, max(.48, period*.92))
        attack=min(.16, cycle*.28); hold=min(.14, cycle*.23); release=max(.24, cycle-attack-hold)
        if not active or age < 0 or age >= cycle: pulse=0.
        elif age < attack: pulse=0.5*(1-math.cos(math.pi*age/attack))
        elif age < attack+hold: pulse=1.
        else:
            u=(age-attack-hold)/release; pulse=max(0., 0.5*(1+math.cos(math.pi*min(1.,u))))
        pulse*=max(.45, min(1., beat_strength))
        base_sx=1.0-.10*amp; base_sy=1.0+.08*amp
        sx_target=base_sx + pulse*.34*amp
        sy_target=base_sy - pulse*.30*amp
        ease=min(1., dt*30.)
        self.anim_sx += (sx_target-self.anim_sx)*ease; self.anim_sy += (sy_target-self.anim_sy)*ease
        size = self.size.get(); w0, h0 = self.original.size; ratio = min(size / max(w0,h0), 1e5)
        w, h = max(1,int(w0*ratio*self.anim_sx)), max(1,int(h0*ratio*self.anim_sy))
        canvas = Image.new('RGBA', (int(size*1.55), int(size*1.55)), (255,0,255,0)); frame = self.original.resize((w,h), Image.Resampling.LANCZOS); canvas.alpha_composite(frame, ((canvas.width-w)//2, int(canvas.height*.84)-h))
        # Tk's Windows color-key transparency cannot display partial alpha reliably.
        # Use a binary alpha key with the original edge RGB values, avoiding purple/magenta fringes.
        alpha=canvas.getchannel('A').point(lambda p: 255 if p >= 12 else 0)
        keyed=Image.composite(canvas.convert('RGB'), Image.new('RGB', canvas.size, (255,0,255)), alpha)
        self.photo = ImageTk.PhotoImage(keyed); self.label.config(image=self.photo)
        self.root.after(max(1, round(1000/int(self.fps.get()))), self.tick)

if __name__ == '__main__':
    try: App().root.mainloop()
    except Exception:
        with open(os.path.join(BASE, '错误日志.txt'), 'w', encoding='utf-8') as f: traceback.print_exc(file=f)
        raise




