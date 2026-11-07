"""Windows sprite surfaces keep the original RGBA coverage."""
import ctypes
import sys
import tkinter as tk
from pathlib import Path
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from layered import LayeredSurface, _user32


def test_native_alpha_and_resize():
    root=tk.Tk(); root.withdraw()
    window=tk.Toplevel(root); window.withdraw(); window.overrideredirect(True)
    window.geometry('2x2+100+100')
    label=tk.Label(window); label.pack(fill='both',expand=True)
    surface=LayeredSurface(window)
    try:
        assert _user32.GetWindowLongPtrW(surface.hwnd,-20)&0x80000
        image=Image.new('RGBA',(2,2),(0,0,0,0))
        image.putpixel((0,0),(255,0,0,128))
        image.putpixel((1,0),(20,40,60,255))
        surface.draw(image)
        pixels=ctypes.string_at(surface.bits,16)
        assert pixels[:4]==bytes((0,0,128,128))
        assert pixels[4:8]==bytes((60,40,20,255))
        assert pixels[8:]==bytes(8)
        window.deiconify(); window.update()
        image=Image.new('RGBA',(3,2),(0,255,0,64))
        surface.draw(image); window.update()
        assert surface.size==(3,2) and ctypes.string_at(surface.bits,4)==bytes((0,64,0,64))
        assert window.winfo_width()==3 and window.winfo_height()==2
    finally:
        surface.close()
        window.destroy(); root.destroy()


if __name__=='__main__':
    test_native_alpha_and_resize()
    print('Layered surface checks passed.')
