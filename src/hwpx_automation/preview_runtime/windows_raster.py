# SPDX-License-Identifier: Apache-2.0
"""Windows built-in GDI+ picture sampler. No Hancom/SDK dependency.

Source pixels/crop and output dimensions are caller supplied. This module has
no access to document layout caches, reference images, or evaluation files.
"""
import ctypes as C

P=C.c_void_p;I=C.c_int;U=C.c_uint;F=C.c_float
class _Startup(C.Structure):
    _fields_=[('version',U),('callback',P),('background',I),('codecs',I)]
class _Rect(C.Structure):
    _fields_=[('x',I),('y',I),('width',I),('height',I)]
class _Bits(C.Structure):
    _fields_=[('width',U),('height',U),('stride',I),('format',I),('scan0',P),('reserved',C.c_size_t)]

class WindowsPictureSampler:
    name='Windows GDI+ HighQualityBicubic; default pixel offset; rounded extents'
    def __init__(self):
        self.lib=getattr(C,'WinDLL')('gdiplus');self.token=C.c_size_t();self.closed=False
        def bind(name,args):
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=I
            def call(*values):
                status=fn(*values)
                if status:raise RuntimeError(name+': '+str(status))
            return call
        self.create=bind('GdipCreateBitmapFromScan0',[I,I,I,I,P,C.POINTER(P)])
        self.graphics=bind('GdipGetImageGraphicsContext',[P,C.POINTER(P)])
        self.clear=bind('GdipGraphicsClear',[P,U])
        self.interpolate=bind('GdipSetInterpolationMode',[P,I])
        self.draw=bind('GdipDrawImageRectRect',[P,P,F,F,F,F,F,F,F,F,I,P,P,P])
        self.lock=bind('GdipBitmapLockBits',[P,C.POINTER(_Rect),U,I,C.POINTER(_Bits)])
        self.unlock=bind('GdipBitmapUnlockBits',[P,C.POINTER(_Bits)])
        self.dispose=bind('GdipDisposeImage',[P]);self.delete=bind('GdipDeleteGraphics',[P])
        bind('GdiplusStartup',[C.POINTER(C.c_size_t),C.POINTER(_Startup),P])(
            C.byref(self.token),C.byref(_Startup(1,None,0,0)),None)
        self.lib.GdiplusShutdown.argtypes=[C.c_size_t]

    def close(self):
        if not self.closed:
            self.lib.GdiplusShutdown(self.token);self.closed=True

    def resize(self,src,size,*,crop=None,background=None):
        from PIL import Image  # pyright: ignore[reportMissingImports] -- optional native-preview extra
        if self.closed:raise RuntimeError('picture sampler is closed')
        if min(size)<=0 or size[0]*size[1]>32000000:
            raise ValueError('picture output raster exceeds runtime limit')
        src=src.convert('RGBA');buffer=C.create_string_buffer(src.tobytes('raw','BGRA'))
        source=P();target=P();ctx=P();fmt=0x26200A
        self.create(src.width,src.height,src.width*4,fmt,buffer,C.byref(source))
        try:
            target_buffer=None
            if background is not None:
                if background.size!=tuple(size):raise ValueError('picture background size mismatch')
                target_buffer=C.create_string_buffer(background.convert('RGBA').tobytes('raw','BGRA'))
            self.create(size[0],size[1],size[0]*4 if target_buffer is not None else 0,fmt,target_buffer,C.byref(target))
            try:
                self.graphics(target,C.byref(ctx))
                try:
                    if background is None:self.clear(ctx,0xFFFFFFFF)
                    self.interpolate(ctx,7)
                    x1,y1,x2,y2=crop or (0,0,src.width,src.height)
                    self.draw(ctx,source,0,0,*size,x1,y1,x2-x1,y2-y1,2,None,None,None)
                finally:self.delete(ctx)
                rect=_Rect(0,0,*size);bits=_Bits();self.lock(target,C.byref(rect),1,fmt,C.byref(bits))
                try:
                    raw=b''.join(C.string_at(bits.scan0+y*bits.stride,size[0]*4) for y in range(size[1]))
                    return Image.frombytes('RGB',size,raw,'raw','BGRX')
                finally:self.unlock(target,C.byref(bits))
            finally:self.dispose(target)
        finally:self.dispose(source)
