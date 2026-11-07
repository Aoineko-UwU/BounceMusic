"""Windows per-pixel transparent surface for desktop sprites."""
import ctypes
from PIL import Image

_user32=ctypes.WinDLL('user32',use_last_error=True)
_gdi32=ctypes.WinDLL('gdi32',use_last_error=True)
_HANDLE=ctypes.c_void_p
_INT=ctypes.c_int
_UINT=ctypes.c_uint


class _POINT(ctypes.Structure):
    _fields_=[('x',_INT),('y',_INT)]


class _SIZE(ctypes.Structure):
    _fields_=[('cx',_INT),('cy',_INT)]


class _BLEND(ctypes.Structure):
    _fields_=[('BlendOp',ctypes.c_ubyte),('BlendFlags',ctypes.c_ubyte),
              ('SourceConstantAlpha',ctypes.c_ubyte),('AlphaFormat',ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_=[('biSize',_UINT),('biWidth',_INT),('biHeight',_INT),
              ('biPlanes',ctypes.c_ushort),('biBitCount',ctypes.c_ushort),
              ('biCompression',_UINT),('biSizeImage',_UINT),
              ('biXPelsPerMeter',_INT),('biYPelsPerMeter',_INT),
              ('biClrUsed',_UINT),('biClrImportant',_UINT)]


class _BITMAPINFO(ctypes.Structure):
    _fields_=[('bmiHeader',_BITMAPINFOHEADER),('bmiColors',_UINT*3)]


_user32.GetParent.argtypes=[_HANDLE]
_user32.GetParent.restype=_HANDLE
_user32.GetWindowLongPtrW.argtypes=[_HANDLE,_INT]
_user32.GetWindowLongPtrW.restype=ctypes.c_ssize_t
_user32.SetWindowLongPtrW.argtypes=[_HANDLE,_INT,ctypes.c_ssize_t]
_user32.SetWindowLongPtrW.restype=ctypes.c_ssize_t
_user32.GetDC.argtypes=[_HANDLE]
_user32.GetDC.restype=_HANDLE
_user32.ReleaseDC.argtypes=[_HANDLE,_HANDLE]
_user32.ReleaseDC.restype=_INT
_user32.UpdateLayeredWindow.argtypes=[_HANDLE,_HANDLE,ctypes.POINTER(_POINT),ctypes.POINTER(_SIZE),
                                      _HANDLE,ctypes.POINTER(_POINT),_UINT,ctypes.POINTER(_BLEND),_UINT]
_user32.UpdateLayeredWindow.restype=_INT
_gdi32.CreateCompatibleDC.argtypes=[_HANDLE]
_gdi32.CreateCompatibleDC.restype=_HANDLE
_gdi32.CreateDIBSection.argtypes=[_HANDLE,ctypes.POINTER(_BITMAPINFO),_UINT,
                                   ctypes.POINTER(_HANDLE),_HANDLE,_UINT]
_gdi32.CreateDIBSection.restype=_HANDLE
_gdi32.SelectObject.argtypes=[_HANDLE,_HANDLE]
_gdi32.SelectObject.restype=_HANDLE
_gdi32.DeleteObject.argtypes=[_HANDLE]
_gdi32.DeleteObject.restype=_INT
_gdi32.DeleteDC.argtypes=[_HANDLE]
_gdi32.DeleteDC.restype=_INT


class LayeredSurface:
    """Draw RGBA frames onto a borderless Tk Toplevel without a color key."""
    def __init__(self,window):
        self.window=window
        window.update_idletasks()
        self.hwnd=_user32.GetParent(window.winfo_id())
        if not self.hwnd: raise ctypes.WinError(ctypes.get_last_error())
        style=_user32.GetWindowLongPtrW(self.hwnd,-20)
        if not style & 0x80000:
            ctypes.set_last_error(0)
            _user32.SetWindowLongPtrW(self.hwnd,-20,style|0x80000)  # WS_EX_LAYERED
            if ctypes.get_last_error(): raise ctypes.WinError(ctypes.get_last_error())
        self.screen_dc=_user32.GetDC(None)
        self.memory_dc=_gdi32.CreateCompatibleDC(self.screen_dc)
        if not self.screen_dc or not self.memory_dc: raise ctypes.WinError(ctypes.get_last_error())
        self.bitmap=None
        self.previous_bitmap=None
        self.bits=None
        self.size=None

    def _allocate(self,width,height):
        if self.bitmap:
            _gdi32.SelectObject(self.memory_dc,self.previous_bitmap)
            _gdi32.DeleteObject(self.bitmap)
            self.bitmap=None
            self.bits=None
        info=_BITMAPINFO()
        info.bmiHeader=_BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER),width,-height,
                                          1,32,0,0,0,0,0,0)
        bits=_HANDLE()
        bitmap=_gdi32.CreateDIBSection(self.screen_dc,ctypes.byref(info),0,ctypes.byref(bits),None,0)
        if not bitmap or not bits.value: raise ctypes.WinError(ctypes.get_last_error())
        previous=_gdi32.SelectObject(self.memory_dc,bitmap)
        if not previous: raise ctypes.WinError(ctypes.get_last_error())
        self.bitmap=bitmap
        self.previous_bitmap=previous
        self.bits=bits
        self.size=(width,height)

    def draw(self,frame):
        if frame.mode!='RGBA': frame=frame.convert('RGBA')
        width,height=frame.size
        if self.size!=(width,height):
            self._allocate(width,height)
            self.window.geometry(f'{width}x{height}')
            self.window.update_idletasks()
        pixels=frame.convert('RGBa').tobytes('raw','BGRa')  # Premultiplied BGRA for AC_SRC_ALPHA.
        ctypes.memmove(self.bits,pixels,len(pixels))
        position=_POINT(self.window.winfo_x(),self.window.winfo_y())
        size=_SIZE(width,height)
        source=_POINT(0,0)
        blend=_BLEND(0,0,255,1)
        if not _user32.UpdateLayeredWindow(self.hwnd,self.screen_dc,ctypes.byref(position),
                                            ctypes.byref(size),self.memory_dc,ctypes.byref(source),
                                            0,ctypes.byref(blend),2):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.bitmap:
            _gdi32.SelectObject(self.memory_dc,self.previous_bitmap)
            _gdi32.DeleteObject(self.bitmap)
            self.bitmap=None
        if self.memory_dc:
            _gdi32.DeleteDC(self.memory_dc)
            self.memory_dc=None
        if self.screen_dc:
            _user32.ReleaseDC(None,self.screen_dc)
            self.screen_dc=None
