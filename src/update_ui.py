"""Shared update dialogs, also backported to the 1.7 maintenance build."""
import sys
import threading
import time
from collections import deque
import tkinter as tk
from tkinter import ttk,messagebox
import updater

def speed_text(speed):
    return f'{speed/1048576:.2f} MB/s' if speed>=1048576 else f'{speed/1024:.0f} KB/s'

class UpdatePanel:
    def __init__(self,app):
        self.app=app; self.release=None; self.dialog=None; self.route_window=None
        self.preference=tk.StringVar(app.root,value=app.config.get('update_route','auto'))
        if self.preference.get() not in {'auto',*(item['id'] for item in updater.ROUTES)}: self.preference.set('auto')
        self.fallback=tk.BooleanVar(app.root,value=app.config.get('update_fallback',True))
        self.probe_token=0; self.results={}; self.result_asset=None; self.probe_started=0.
        self.route_tree=None; self.probe_button=None; self.samples=deque(maxlen=20); self.current_route=''
        self.downloading=False

    def status(self,text):
        if not hasattr(self.app,'update_status'): self.app.update_status=tk.StringVar(self.app.root)
        self.app.update_status.set(text)

    def save_choice(self):
        self.app.config.update(update_route=self.preference.get(),update_fallback=self.fallback.get())
        self.app.save()

    def finish_window(self,window,width,height=None):
        try: window.iconbitmap(self.app.root.iconbitmap())
        except tk.TclError: pass
        self.app.apply_theme(); window.update_idletasks()
        width=min(width,window.winfo_screenwidth()-40); height=min(height or window.winfo_reqheight(),window.winfo_screenheight()-80)
        window.geometry(f'{width}x{height}+{max(0,(window.winfo_screenwidth()-width)//2)}+{max(0,(window.winfo_screenheight()-height)//2)}')
        window.resizable(False,False); window.deiconify(); window.attributes('-topmost',True); window.lift()

    def check_updates(self):
        if self.app.update_busy: return
        self.app.update_busy=True; self.status('正在从 GitHub 获取更新信息……')
        def work():
            try:
                release=updater.latest_release(); self.release=release
                self.app.events.put(('update_checked',release))
            except Exception as error: self.app.events.put(('update_error',str(error)))
        threading.Thread(target=work,daemon=True).start()

    def route_controls(self,parent):
        box=ttk.LabelFrame(parent,text='下载线路（点击选择）',padding=8); box.pack(fill='x',padx=12,pady=6)
        tree=ttk.Treeview(box,columns=('name','speed','latency','quality'),show='headings',height=5,selectmode='browse')
        for key,label,width in (('name','线路',180),('speed','参考速度',110),('latency','响应',80),('quality','状态',110)):
            tree.heading(key,text=label); tree.column(key,width=width,anchor='w',stretch=key=='name')
        tree.pack(fill='x'); self.route_tree=tree
        tree.insert('','end',iid='auto',values=('自动选择（推荐）','按测速择优','—','自动回退'))
        for item in updater.ROUTES: tree.insert('','end',iid=item['id'],values=(item['name'],'待测速','—','待测速'))
        tree.selection_set(self.preference.get())
        def select(event):
            selection=tree.selection()
            if selection:
                self.preference.set(selection[0]); self.save_choice()
                if hasattr(self,'progress_route'): self.progress_route.set(updater.route_name(selection[0]))
        tree.bind('<<TreeviewSelect>>',select)
        row=ttk.Frame(box); row.pack(fill='x',pady=(6,0))
        self.probe_button=ttk.Button(row,text='重新测速',command=self.start_probes); self.probe_button.pack(side='left')
        ttk.Checkbutton(row,text='失败时自动换线路',variable=self.fallback,command=self.save_choice).pack(side='left',padx=12)
        ttk.Label(box,text='测速仅反映当前网络；少量读取安装包测试，文件仍核对官方校验值。',wraplength=580).pack(anchor='w',pady=(5,0))
        for result in self.results.values(): self.draw_result(result)

    def show_route_settings(self):
        if self.route_window and self.route_window.winfo_exists():
            self.route_window.deiconify(); self.route_window.lift(); return
        window=tk.Toplevel(self.app.root); window.withdraw(); self.route_window=window; window.title('下载线路与测速')
        self.route_controls(window)
        ttk.Button(window,text='关闭',command=window.destroy).pack(pady=(0,10))
        self.finish_window(window,640)
        if self.release: self.start_probes()
        else:
            def work():
                try: self.app.events.put(('update_route_metadata',updater.latest_release()))
                except Exception as error: self.app.events.put(('update_route_error',str(error)))
            threading.Thread(target=work,daemon=True).start()

    def start_probes(self):
        if not self.release:
            self.status('正在获取用于测速的官方安装包信息……'); return
        try: asset=updater.release_asset(self.release,self.app.setup_install)
        except Exception as error: self.status(str(error)); return
        self.probe_token+=1; token=self.probe_token; self.results={}; self.result_asset=asset['digest']; self.probe_started=time.monotonic()
        if self.probe_button and self.probe_button.winfo_exists(): self.probe_button.state(['disabled'])
        if self.route_tree and self.route_tree.winfo_exists():
            for item in updater.ROUTES: self.route_tree.item(item['id'],values=(item['name'],'测速中','—','测速中'))
        def work():
            updater.probe_routes(asset,lambda result:self.app.events.put(('update_route_result',(token,result))))
        threading.Thread(target=work,daemon=True).start()

    def handle_event(self,kind,value):
        if kind=='update_route_result': self.route_result(*value)
        elif kind=='update_route_metadata': self.release=value; self.start_probes()
        else:
            self.status('测速资源获取失败：'+str(value))
            if self.probe_button and self.probe_button.winfo_exists(): self.probe_button.state(['!disabled'])

    def draw_result(self,result):
        if not self.route_tree or not self.route_tree.winfo_exists(): return
        ok=result.get('ok')
        self.route_tree.item(result['id'],values=(updater.route_name(result['id']),speed_text(result['speed']) if ok else '—',
            f'{result["latency"]:.0f} ms' if ok else '—',result['quality']))
        working=[item for item in self.results.values() if item.get('ok')]
        if working:
            best=max(working,key=lambda item:item['speed'])
            self.route_tree.item('auto',values=('自动选择（推荐）',speed_text(best['speed']),'—','优先 '+updater.route_name(best['id'])))

    def route_result(self,token,result):
        if token!=self.probe_token: return
        self.results[result['id']]=result; self.draw_result(result)
        if len(self.results)==len(updater.ROUTES):
            if self.probe_button and self.probe_button.winfo_exists(): self.probe_button.state(['!disabled'])

    def show_release(self,release):
        self.release=release
        dialog=tk.Toplevel(self.app.root); dialog.withdraw(); self.dialog=dialog; dialog.title('发现新版本')
        ttk.Label(dialog,text='发现新版本 '+release['tag_name'],font=('Microsoft YaHei UI',13,'bold'),padding=12).pack(anchor='w')
        row=ttk.Frame(dialog,padding=12); row.pack(side='bottom',fill='x')
        ttk.Label(dialog,text='更新内容：').pack(anchor='w',padx=12)
        content=ttk.Frame(dialog); content.pack(fill='both',expand=True,padx=12,pady=(5,0))
        notes=tk.Text(content,height=7,wrap='char',font=('Microsoft YaHei UI',10),padx=12,pady=8,relief='flat',cursor='arrow')
        scrollbar=ttk.Scrollbar(content,orient='vertical',command=notes.yview)
        notes.configure(yscrollcommand=scrollbar.set); scrollbar.pack(side='right',fill='y'); notes.pack(side='left',fill='both',expand=True)
        # Import the renderer from the existing App module without a circular module import.
        renderer=sys.modules[type(self.app).__module__].render_release_notes
        renderer(notes,release.get('body'))
        self.route_controls(dialog)
        ttk.Button(row,text='下载并更新',command=self.start_download).pack(side='left')
        ttk.Button(row,text='暂不更新',command=dialog.destroy).pack(side='right')
        self.finish_window(dialog,660,620)
        if getattr(sys,'frozen',False): self.start_probes()

    def start_download(self):
        if not getattr(sys,'frozen',False): self.status('源码运行模式请从发布页下载更新。'); return
        if not self.release: return
        if self.dialog and self.dialog.winfo_exists(): self.dialog.destroy()
        self.app.update_busy=True; self.downloading=True; self.save_choice()
        self.app.update_control=updater.DownloadControl(); self.show_progress(); control=self.app.update_control
        release=self.release; route=self.preference.get(); fallback=self.fallback.get()
        asset=updater.release_asset(release,self.app.setup_install)
        results=dict(self.results) if self.result_asset==asset['digest'] and time.monotonic()-self.probe_started<300 else None
        def work():
            try:
                stage=updater.prepare_update(release,self.app.setup_install,
                    lambda *event:self.app.events.put(('update_progress',event)),control,route,results,fallback)
                self.app.events.put(('update_ready',stage))
            except updater.UpdateCancelled: self.app.events.put(('update_cancelled',None))
            except Exception as error: self.app.events.put(('update_error',str(error)))
        threading.Thread(target=work,daemon=True).start()

    def show_progress(self):
        self.close_progress(cancel=False)
        window=tk.Toplevel(self.app.root); window.withdraw(); self.app.update_progress_window=window
        window.title('正在更新'); self.samples.clear()
        self.app.update_progress_text=tk.StringVar(self.app.root,value='正在准备下载……')
        self.route_text=tk.StringVar(self.app.root,value='线路：自动选择')
        self.rate_text=tk.StringVar(self.app.root,value='速度：等待数据    剩余时间：—')
        ttk.Label(window,text='下载并更新',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',padx=16,pady=(14,8))
        ttk.Label(window,textvariable=self.route_text).pack(anchor='w',padx=16)
        ttk.Label(window,textvariable=self.app.update_progress_text,wraplength=510).pack(anchor='w',padx=16,pady=4)
        self.app.update_progress_bar=ttk.Progressbar(window,mode='indeterminate')
        self.app.update_progress_bar.pack(fill='x',padx=16,pady=6); self.app.update_progress_bar.start(12)
        ttk.Label(window,textvariable=self.rate_text).pack(anchor='w',padx=16,pady=4)
        route_row=ttk.Frame(window); route_row.pack(fill='x',padx=16,pady=8)
        choices={'自动选择':'auto',**{item['name']:item['id'] for item in updater.ROUTES}}
        self.progress_route=tk.StringVar(self.app.root,value=next(name for name,key in choices.items() if key==self.preference.get()))
        self.progress_combo=ttk.Combobox(route_row,textvariable=self.progress_route,values=list(choices),state='readonly',width=20)
        self.progress_combo.pack(side='left')
        def switch():
            route=choices[self.progress_route.get()]; self.preference.set(route); self.save_choice()
            self.app.update_control.switch_route(route); self.samples.clear()
            self.app.update_pause_button.config(text='暂停下载')
            self.app.update_progress_text.set('正在切换线路；支持续传时保留已下载进度……')
        self.switch_button=ttk.Button(route_row,text='切换线路',command=switch); self.switch_button.pack(side='left',padx=6)
        ttk.Button(route_row,text='线路测速',command=self.show_route_settings).pack(side='left')
        if self.app.update_control is None: self.app.update_control=updater.DownloadControl()
        row=ttk.Frame(window); row.pack(fill='x',padx=16,pady=(3,12))
        def pause():
            control=self.app.update_control; control.pause(not control.paused); self.samples.clear()
            self.app.update_pause_button.config(text='继续下载' if control.paused else '暂停下载')
            if control.paused: self.app.update_progress_text.set('已暂停下载')
        def cancel():
            if not self.downloading: self.close_progress(); return
            self.app.update_control.cancel(); self.app.update_progress_text.set('正在中断并清理未完成的包……')
            self.app.update_pause_button.state(['disabled']); self.app.update_cancel_button.state(['disabled'])
        self.app.update_pause_button=ttk.Button(row,text='暂停下载',command=pause); self.app.update_pause_button.pack(side='left')
        self.app.update_cancel_button=ttk.Button(row,text='中断下载',command=cancel); self.app.update_cancel_button.pack(side='right')
        window.protocol('WM_DELETE_WINDOW',cancel)
        self.finish_window(window,570,300)

    def progress(self,phase,size,total):
        if not self.app.update_progress_window or not self.app.update_progress_window.winfo_exists(): return
        if self.app.update_control and (self.app.update_control.cancelled or self.app.update_control.paused): return
        bar=self.app.update_progress_bar; final=phase in ('verify','extract')
        for button in (self.app.update_pause_button,self.app.update_cancel_button,self.switch_button): button.state(['disabled'] if final else ['!disabled'])
        if phase in ('route','switch','restart'):
            self.current_route=size; self.samples.clear(); self.route_text.set('当前线路：'+updater.route_name(size))
            self.rate_text.set('速度：等待当前线路数据    剩余时间：—')
            message='正在连接线路……' if phase!='restart' else '此线路不支持续传，正在从头下载。'
        elif phase=='testing': message='正在并行测试线路，选择当前网络下的较快节点……'
        elif phase=='probe':
            self.results[size['id']]=size; self.draw_result(size); return
        elif phase=='retry': message=updater.route_name(size['id'])+'：'+size['reason']+'；正在重试或换线……'
        elif phase=='download':
            if total:
                bar.stop(); bar.configure(mode='determinate',maximum=total,value=min(size,total))
                message=f'正在下载：{size/1048576:.1f} / {total/1048576:.1f} MB（{min(100,size*100/total):.0f}%）'
            else: message=f'已下载 {size/1048576:.1f} MB'
            now=time.monotonic(); self.samples.append((now,size))
            while len(self.samples)>2 and now-self.samples[0][0]>3: self.samples.popleft()
            if len(self.samples)>1:
                elapsed=now-self.samples[0][0]; speed=max(0.,size-self.samples[0][1])/max(.001,elapsed)
                eta=f'{max(0,total-size)/speed:.0f} 秒' if speed and total else '—'
                self.rate_text.set('速度：'+speed_text(speed)+'    预计剩余：'+eta)
        else:
            bar.stop(); bar.configure(mode='indeterminate'); bar.start(12)
            message='正在核对官方 SHA-256 校验值……' if phase=='verify' else '正在解压更新包……'
        self.app.update_progress_text.set(message); self.status(message)

    def failed(self,error):
        self.app.update_busy=False; self.downloading=False; self.status('更新失败：'+error)
        if self.app.update_progress_window and self.app.update_progress_window.winfo_exists():
            self.app.update_progress_bar.stop(); self.app.update_progress_text.set('更新失败：'+error+'。可选择其他线路后重试。')
            self.app.update_pause_button.state(['!disabled']); self.app.update_pause_button.config(text='重试下载',command=self.retry_download)
            self.app.update_cancel_button.state(['!disabled']); self.app.update_cancel_button.config(text='关闭',command=self.close_progress)
            self.switch_button.state(['disabled'])
        else: messagebox.showerror('更新失败',error,parent=self.app.root)

    def retry_download(self):
        label=self.progress_route.get()
        self.preference.set(next((item['id'] for item in updater.ROUTES if item['name']==label),'auto'))
        self.save_choice(); self.start_download()

    def close_progress(self,cancel=True):
        window=self.app.update_progress_window
        if cancel and self.app.update_control: self.app.update_control.cancel()
        if window and window.winfo_exists(): window.destroy()
        self.app.update_progress_window=None
        if cancel: self.app.update_control=None

    def close(self):
        self.probe_token+=1
        if self.app.update_control: self.app.update_control.cancel()
