# SPDX-License-Identifier: Apache-2.0
"""Rasterize caller-supplied glyphs into a private GDI bitmap.

Uses bundled or explicitly selected font files and authored scene positions.
No windows, SDK, reference images, network, or persistent font installation.
"""
import ctypes as C
from typing import Any, cast
import io
import hashlib
from pathlib import Path

P=C.c_void_p
I=C.c_int
U=C.c_uint32
S=C.c_uint16


class _Header(C.Structure):
    _fields_=[('size',U),('width',I),('height',I),('planes',S),('bits',S),
              ('compression',U),('imageSize',U),('xppm',I),('yppm',I),('used',U),('important',U)]


class _BitmapInfo(C.Structure):
    _fields_=[('header',_Header),('colors',U*3)]


class _Transform(C.Structure):
    _fields_=[(key,C.c_float) for key in ['xx','yx','xy','yy','dx','dy']]


def _verify_used_glyphs(expected,actual,indices):
    # Different releases can share unchanged glyphs. Require equivalence of
    # all drawing inputs, not merely a matching family name or bounding box.
    for tag in ['cmap','hhea','maxp','fpgm','prep','cvt ','gasp']:
        if tag not in expected or tag not in actual or expected.getTableData(tag)!=actual.getTableData(tag):
            return False
    if any(getattr(expected['head'],key)!=getattr(actual['head'],key) for key in ['unitsPerEm','flags']):return False
    fields=['usWeightClass','usWidthClass','usWinAscent','usWinDescent','sTypoAscender','sTypoDescender','sTypoLineGap','fsSelection']
    if any(getattr(expected['OS/2'],key)!=getattr(actual['OS/2'],key) for key in fields):return False
    old_order=actual.getGlyphOrder();new_order=expected.getGlyphOrder()
    pending=list(indices);seen=set()
    while pending:
        index=pending.pop()
        if index in seen:continue
        seen.add(index)
        if index>=len(old_order) or index>=len(new_order):return False
        old_name=old_order[index];new_name=new_order[index]
        if actual['hmtx'].metrics[old_name]!=expected['hmtx'].metrics[new_name]:return False
        old_glyph=actual['glyf'][old_name];new_glyph=expected['glyf'][new_name]
        if old_glyph.compile(actual['glyf'])!=new_glyph.compile(expected['glyf']):return False
        if new_glyph.isComposite():
            pending.extend(expected.getGlyphID(component.glyphName) for component in new_glyph.components)
    return True


def draw_glyphs(image,page,dpi=300,validation_reports=None):
    from fontTools.ttLib import TTFont as _TTFont  # pyright: ignore[reportMissingImports] -- optional native-preview extra
    TTFont = cast(Any, _TTFont)
    from PIL import Image  # pyright: ignore[reportMissingImports] -- optional native-preview extra
    width,height=image.size
    if min(image.size)<=0 or width*height>32000000:
        raise ValueError('text output raster exceeds runtime limit')
    lib=getattr(C,'WinDLL')('gdi32',use_last_error=True)
    def bind(name,args,result: Any=I):
        function=getattr(lib,name);function.argtypes=args;function.restype=result
        return function
    create_dc=bind('CreateCompatibleDC',[P],P)
    create_bitmap=bind('CreateDIBSection',[P,C.POINTER(_BitmapInfo),U,C.POINTER(P),P,U],P)
    select=bind('SelectObject',[P,P],P)
    delete_object=bind('DeleteObject',[P])
    delete_dc=bind('DeleteDC',[P])
    create_font=bind('CreateFontW',[I,I,I,I,I,U,U,U,U,U,U,U,U,C.c_wchar_p],P)
    add_font=bind('AddFontMemResourceEx',[P,U,P,C.POINTER(U)],P)
    remove_font=bind('RemoveFontMemResourceEx',[P])
    text_out=bind('ExtTextOutW',[P,I,I,U,P,C.POINTER(S),U,C.POINTER(I)])
    set_color=bind('SetTextColor',[P,U],U)
    transform=bind('SetWorldTransform',[P,C.POINTER(_Transform)])
    get_font_data=bind('GetFontData',[P,U,U,P,U],U)
    set_mode=bind('SetGraphicsMode',[P,I])
    align=bind('SetTextAlign',[P,U],U)
    background=bind('SetBkMode',[P,I])
    # Realize fonts only after private resources are present in the process.
    preload={}
    for line in page['lines']:
        for glyph in line['glyphRuns']:
            path=glyph['fontFile']
            if not glyph['glyphId'] or path in preload:continue
            try:
                data=Path(path).read_bytes();buffer=C.create_string_buffer(data);loaded=U()
                handle=add_font(buffer,len(data),None,C.byref(loaded))
                if not handle or not loaded.value:raise OSError('Private font loading failed')
                preload[path]=handle
                # GDI owns a copy after AddFontMemResourceEx succeeds:
                # https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-addfontmemresourceex
                del data,buffer
            except OSError:
                for prior in preload.values():remove_font(prior)
                raise OSError('Private font loading failed')
    dc=create_dc(None)
    if not dc:
        for handle in preload.values():remove_font(handle)
        raise OSError('CreateCompatibleDC failed')
    bitmap=None;old_bitmap=None;old_font=None
    fonts={};resources={};verified=set()
    used={}
    for line in page['lines']:
        for glyph in line['glyphRuns']:
            if glyph['glyphId']:used.setdefault(glyph['fontFile'],set()).add(glyph['glyphId'])
    try:
        if not set_mode(dc,2):raise OSError('SetGraphicsMode failed')
        align(dc,24)  # TA_LEFT | TA_BASELINE; caller determines all advances.
        if not background(dc,1):raise OSError('SetBkMode failed')
        header=_Header(C.sizeof(_Header),width,-height,1,32,0,width*height*4,0,0,0,0)
        info=_BitmapInfo(header);bits=P()
        bitmap=create_bitmap(dc,C.byref(info),0,C.byref(bits),None,0)
        if not bitmap or not bits:raise OSError('CreateDIBSection failed')
        old_bitmap=select(dc,bitmap)
        pixels=image.convert('RGBA').tobytes('raw','BGRA')
        C.memmove(bits,pixels,len(pixels));del pixels
        scale=dpi/7200
        for line in page['lines']:
            for glyph in line['glyphRuns']:
                if glyph['glyphId']==0:continue
                if not 0<glyph['glyphId']<=65535:raise ValueError('GDI glyph index exceeds 16 bits')
                path=glyph['fontFile']
                if path not in resources:
                    # Memory fonts are private and non-enumerable; the bytes
                    # remain unmodified and the owned handle is released.
                    handle=preload[path]
                    resources[path]=(handle,None)
                    with TTFont(path) as tt:
                        family=next((entry.toUnicode() for entry in tt['name'].names if entry.nameID==1 and entry.platformID==3 and entry.langID==1042),tt['name'].getDebugName(1))
                        resources[path]=(handle,(family,tt['OS/2'].usWeightClass,
                                         {tag:tt.getTableData(tag) for tag in ['head','cmap']}))
                    del tt
                family,weight,tables=resources[path][1]
                key=(path,glyph['height'],glyph['italic'],bool(glyph.get('syntheticBold')))
                if key not in fonts:
                    font=create_font(-max(1,round(glyph['height']*scale)),0,0,0,
                                     700 if glyph.get('syntheticBold') else weight,
                                     int(glyph['italic']),0,0,1,4,0,5,0,family)
                    if not font:raise OSError('CreateFontW failed')
                    fonts[key]=font
                previous=select(dc,fonts[key])
                if not old_font:old_font=previous
                if key not in verified:
                    # Reject font mapper substitution or a different installed
                    # version before using caller-supplied glyph IDs.
                    equivalent=False
                    for tag,expected in tables.items():
                        buffer=C.create_string_buffer(len(expected))
                        actual_size=get_font_data(dc,int.from_bytes(tag.encode('ascii'),'little'),0,buffer,len(expected))
                        if actual_size!=len(expected) or buffer.raw!=expected:
                            length=get_font_data(dc,0,0,None,0)
                            if length==0xFFFFFFFF or length>32000000:raise ValueError('GDI font resource could not be verified')
                            raw=C.create_string_buffer(length)
                            if get_font_data(dc,0,0,raw,length)!=length:raise ValueError('GDI font data read failed')
                            with TTFont(path) as expected_font,TTFont(io.BytesIO(raw.raw)) as actual_font:
                                equivalent=_verify_used_glyphs(expected_font,actual_font,used[path])
                            # Closing TTFont releases the stream but retains
                            # decoded tables on the object. Drop both objects
                            # before allocating the final page pixel buffer.
                            del expected_font,actual_font,raw
                            if not equivalent:raise ValueError('GDI selected different glyph outlines, metrics or hinting: '+family)
                            break
                    if validation_reports is not None:
                        validation_reports.append(dict(requestedFontFile=path,fontFamily=family,
                            mode='identical used-glyph outlines, metrics and hinting verified across font releases' if equivalent else 'exact head/cmap font tables',
                            usedGlyphCount=len(used[path]),glyphIds=sorted(used[path]),selectedTableSha256=hashlib.sha256(buffer.raw).hexdigest()))
                    verified.add(key)
                value=glyph['color'].lstrip('#')
                if len(value)!=6:raise ValueError('Invalid glyph RGB color')
                red,green,blue=(int(value[index:index+2],16) for index in [0,2,4])
                if set_color(dc,red|(green<<8)|(blue<<16))==0xFFFFFFFF:
                    raise OSError('SetTextColor failed')
                x=(glyph['origin'][0]+glyph['offset'][0])*scale
                y=(glyph['origin'][1]+glyph['offset'][1])*scale
                matrix=_Transform(glyph['ratio']/100,0,0,1,round(x),round(y))
                if not transform(dc,C.byref(matrix)):raise OSError('SetWorldTransform failed')
                index=(S*1)(glyph['glyphId'])
                if not text_out(dc,0,0,0x10,None,index,1,None):raise OSError('ExtTextOutW failed')
        # The public result is RGB. Decode BGRX directly instead of allocating
        # an additional full-page RGBA image before discarding its alpha.
        return Image.frombytes('RGB',image.size,C.string_at(bits,width*height*4),'raw','BGRX')
    finally:
        if old_font:select(dc,old_font)
        if old_bitmap:select(dc,old_bitmap)
        for font in fonts.values():delete_object(font)
        if bitmap:delete_object(bitmap)
        delete_dc(dc)
        for handle in preload.values():remove_font(handle)
