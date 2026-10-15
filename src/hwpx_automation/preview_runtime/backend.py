# SPDX-License-Identifier: Apache-2.0
"""Companion HarfBuzz/FreeType drawing backend with explicit font resources."""
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, cast
def _load_native_dependencies():
    global hb, freetype, fontTools, TTFont, Image, ImageDraw
    try:
        import uharfbuzz as _hb  # pyright: ignore[reportMissingImports] -- optional native-preview extra
        hb = cast(Any, _hb)
        import freetype as _freetype  # pyright: ignore[reportMissingImports] -- optional native-preview extra
        freetype = cast(Any, _freetype)
        import fontTools  # pyright: ignore[reportMissingImports] -- optional native-preview extra
        from fontTools.ttLib import TTFont as _TTFont  # pyright: ignore[reportMissingImports] -- optional native-preview extra
        TTFont = cast(Any, _TTFont)
        from PIL import Image, ImageDraw  # pyright: ignore[reportMissingImports] -- optional native-preview extra
    except ImportError as exc:
        raise RuntimeError('Install python-hwpx-automation[native-preview] to render native previews.') from exc


class Backend:
    def __init__(self, *, font_files, font_substitutions=None,native_table_borders=None,native_picture_crop=None):
        _load_native_dependencies()
        self.native_table_borders=(os.environ.get('HWPX_PREVIEW_NATIVE_TABLE_BORDERS')=='1' if native_table_borders is None else bool(native_table_borders))
        if self.native_table_borders and os.name!='nt':raise ValueError('Experimental native table borders require Windows')
        self.native_picture_crop=(os.environ.get('HWPX_PREVIEW_NATIVE_PICTURE_CROP')=='1' if native_picture_crop is None else bool(native_picture_crop))
        if self.native_picture_crop and os.name!='nt':raise ValueError('Experimental picture crop requires Windows')
        self.font_files={family:tuple(str(Path(p).resolve()) for p in pair) for family,pair in font_files.items()}
        if any(len(pair)!=2 for pair in self.font_files.values()):raise ValueError('each font family needs normal and bold resources')
        self.fonts={}; self.used={};self.font_substitutions=dict(font_substitutions or {});self.substituted={};self.text_font_validation=[]
        for requested,resolved in self.font_substitutions.items():
            if not isinstance(requested,str) or resolved not in self.font_files:raise ValueError('invalid explicit font substitution')
    def inspect_picture(self,raw):
        import io
        with Image.open(io.BytesIO(raw)) as src:
            if src.format not in {'PNG','JPEG','BMP'} or src.width*src.height>16000000:
                raise ValueError('only PNG/JPEG/BMP up to 16 million pixels in this prototype')
            size=[src.width,src.height];src.verify()
        return size
    def load(self,family,bold):
        requested=family;family=self.font_substitutions.get(family,family)
        if requested!=family:self.substituted[requested]=family
        if family not in self.font_files: raise ValueError('unsupported font family: '+family)
        path=Path(self.font_files[family][int(bold)])
        key=str(path)
        if key not in self.fonts:
            data=path.read_bytes(); face=hb.Face(data); font=hb.Font(face); font.scale=(face.upem,face.upem); hb.ot_font_set_funcs(font)
            # FreeType's filename API uses narrow Windows paths. Reuse the
            # bytes already loaded for shaping so Unicode installation paths
            # work without renaming, copying, or changing the font.
            tt=TTFont(path); ft=freetype.Face.from_bytes(data)
            info=dict(family=family,file=str(path),sha256=hashlib.sha256(data).hexdigest(),faceIndex=0,
                      version=tt['name'].getDebugName(5),unitsPerEm=face.upem,bold=bold,fsType=tt['OS/2'].fsType)
            self.fonts[key]=(font,tt,ft,info)
        self.used[key]=self.fonts[key][3]; return self.fonts[key]
    def shape(self,text,attrs,style):
        family=style.hangul_face
        if style.glyph_face!=family: raise ValueError('separate script font faces unsupported')
        font,tt,ft,info=self.load(family,attrs['bold']); upem=info['unitsPerEm']; height=attrs['height']
        result=[]
        # Segment at script boundaries and explicit hard break. Features are
        # frozen off to match the first Hancom character-policy slice; HB still
        # maps/scales actual glyph IDs, clusters, offsets and advances.
        import re
        segments=re.finditer(r'[\uac00-\ud7a3]+|[^\uac00-\ud7a3\n]+|\n',text)
        for seg in segments:
            part=seg.group()
            if part=='\n': result.append(dict(glyphId=0,cluster=seg.start(),fontFile=info['file'],advance=0,spacingAdvance=0,rawAdvance=0,offset=[0,0],inkBounds=[0,0,0,0],height=height,ratio=style.ratio,italic=False)); continue
            buf=hb.Buffer(); buf.add_codepoints([ord(c) for c in part]); buf.guess_segment_properties()
            hb.shape(font,buf,{'kern':False,'liga':False,'clig':False})
            for gi,pos in zip(buf.glyph_infos,buf.glyph_positions):
                c=part[gi.cluster]
                if gi.codepoint==0: raise ValueError(f'missing glyph U+{ord(c):04X}')
                if c==' ' and not style.use_font_space: units=height//4//2
                else:
                    raw=pos.x_advance*(height//4)/upem
                    units=math.floor(raw+0.5) if style.ratio==100 else math.floor(raw*style.ratio/100)
                if c==' ' and not style.use_font_space: units=math.floor(units*style.ratio/100+0.5)
                spaced=math.floor(abs(units*style.spacing/100)+0.5)*(1 if style.spacing>=0 else -1)
                ext=font.get_glyph_extents(gi.codepoint); scale=height/upem
                shear=1/3 if attrs['italic'] else 0
                if ext:
                    xx=[ext.x_bearing,ext.x_bearing+ext.width]; yy=[ext.y_bearing,ext.y_bearing+ext.height]
                    xs=[(x+shear*y)*scale*style.ratio/100 for x in xx for y in yy]
                    bounds=[min(xs),-max(yy)*scale,max(xs),-min(yy)*scale]
                else: bounds=[0,0,0,0]
                resolved=self.font_substitutions.get(family,family)
                synthetic=bool(attrs['bold'] and self.font_files[resolved][0]==self.font_files[resolved][1])
                if synthetic:
                    strength=height/24
                    bounds=[bounds[0],bounds[1]-strength,bounds[2]+strength,bounds[3]]
                result.append(dict(glyphId=gi.codepoint,cluster=seg.start()+gi.cluster,fontFile=info['file'],faceIndex=0,
                    advance=(units+spaced)*4,spacingAdvance=spaced*4,rawAdvance=pos.x_advance*scale,
                    offset=[pos.x_offset*scale,-pos.y_offset*scale],inkBounds=bounds,
                    height=height,ratio=style.ratio,italic=bool(attrs['italic']),
                    underlinePosition=-tt['post'].underlinePosition*scale,
                    underlineThickness=tt['post'].underlineThickness*scale))
                if synthetic:result[-1]['syntheticBold']=True
        if [g['cluster'] for g in result]!=list(range(len(text))): raise ValueError('complex clusters outside slice')
        return result
    def font_metrics(self,family,height,*,bold=False):
        font,tt,ft,info=self.load(family,bold);scale=height/info['unitsPerEm']
        return dict(windowsAscent=tt['OS/2'].usWinAscent*scale,windowsDescent=tt['OS/2'].usWinDescent*scale,
                    typographicAscent=tt['OS/2'].sTypoAscender*scale,typographicDescent=-tt['OS/2'].sTypoDescender*scale)
    def manifest(self):
        value: dict[str, Any] = dict(fonts=list(self.used.values()),shapingBackend=dict(name='HarfBuzz',version=hb.version_string(),
                binding=hb.__version__,features={'kern':False,'liga':False,'clig':False}),
                drawingBackend=dict(name='FreeType',version=freetype.version(),binding='2.5.1',fontTools=fontTools.__version__))
        from .raster import policy
        picture_backend: dict[str, Any] = policy()
        value['pictureBackend']=picture_backend
        picture_backend['cropConversion']=dict(experimental=self.native_picture_crop,
            policy='authored canvas with inferred integer source density; cropped images only' if self.native_picture_crop else 'normalized authored canvas')
        value['tableRasterBackend']=dict(
            name='Windows GDI geometric solid paths with flat caps' if self.native_table_borders else 'Pillow calibrated solid strokes',
            geometry='authored cell rectangles and border widths; no saved raster/cache coordinates',
            experimental=self.native_table_borders,
            mixedWidthCorners='thin horizontal frame reaches wider vertical outside edge' if self.native_table_borders else 'retained baseline',
            dashedStrokes=('Windows device pen; calibrated 2-on/3-off policy at 300 dpi' if self.native_table_borders else
                           'calibrated Pillow 2-on/3-off policy at 300 dpi'),network=False)
        if os.name=='nt':
            value['drawingBackend']=dict(name='Windows GDI ClearType',glyphPositions='authored scene; rounded device origin and em size',fontMapping='exact tables or identical used-glyph outlines, metrics and hinting verified',fontValidation=self.text_font_validation,network=False)
        if self.substituted:value['substitutions']=[dict(requestedFont=k,resolvedFont=v,policy='explicit caller font environment') for k,v in self.substituted.items()]
        return value
    def draw(self,scene,out,dpi=300):
        from .raster import create_sampler
        sampler=create_sampler()
        try:self._draw(scene,out,dpi,sampler)
        finally:sampler.close()
    @staticmethod
    def _joins(draw,cell,scale):
        x,y,w,h=cell['rect'];borders=cell['borders']
        for a,b,cx,cy in [('left','top',x,y),('right','top',x+w,y),('left','bottom',x,y+h),('right','bottom',x+w,y+h)]:
            edge=borders[a]
            if edge!=borders[b] or edge['type']!='SOLID':continue
            thickness=max(1,round(edge['width']*scale))
            if thickness==1:continue
            cx,cy=round(cx*scale),round(cy*scale);before=thickness//2;after=thickness-before-1
            radius=thickness/2
            for jy in range(-before,after+1):
                for jx in range(-before,after+1):
                    dx=max(0,abs(jx)-.5);dy=max(0,abs(jy)-.5)
                    if dx*dx+dy*dy<=radius*radius:draw.point((cx+jx,cy+jy),fill=edge['color'])
    def _draw(self,scene,out,dpi,sampler):
        out=Path(out); out.mkdir(parents=True,exist_ok=True); scale=dpi/7200
        if self.native_table_borders:
            from .windows_borders import paint as paint_borders, supported as native_borders_supported
        for page in scene['pages']:
            im=Image.new('RGB',(round(page['size']['width']*scale),round(page['size']['height']*scale)), 'white')
            draw=ImageDraw.Draw(im)
            native_cells=[];fallback_cells=[]
            all_cells=[]
            objects=[]
            for obj in page.get('objects',[]):
                if obj['kind']=='tableRow':
                    objects.extend(dict(obj,cells=[cell]) for cell in obj['cells'])
                    owner=(obj['paragraphId'],json.dumps(obj.get('ancestors',[]),sort_keys=True),obj.get('storyRegion','body'))
                    all_cells.extend(dict(cell,strokeOwner=owner) for cell in obj['cells'])
                else:objects.append(obj)
            for obj in objects:
                native_table=self.native_table_borders and obj['kind']=='tableRow' and native_borders_supported(obj['cells'])
                if native_cells and not native_table:
                    im=paint_borders(im,native_cells,dpi,junction_cells=all_cells);draw=ImageDraw.Draw(im);native_cells=[]
                if native_table:
                    owner=(obj['paragraphId'],json.dumps(obj.get('ancestors',[]),sort_keys=True),obj.get('storyRegion','body'))
                    native_cells.extend(dict(cell,strokeOwner=owner) for cell in obj['cells']);continue
                if obj['kind']=='picture':
                    import io,base64
                    x,y,w,h=obj['rect'];origin=[round(x*scale),round(y*scale)];size=[round(w*scale),round(h*scale)]
                    with Image.open(io.BytesIO(base64.b64decode(obj['pngBase64']))) as src:
                        if src.width*src.height>16000000:raise ValueError('picture raster exceeds prototype limit')
                        from .raster import picture_crop_region
                        region=picture_crop_region(obj,src.size,integer_density=self.native_picture_crop)
                        background=im.crop((origin[0],origin[1],origin[0]+size[0],origin[1]+size[1]))
                        raster=sampler.resize(src,size,crop=region,background=background)
                    im.paste(raster,(origin[0],origin[1]))
                elif obj['kind']=='tableRow':
                    fallback_cells.extend(obj['cells'])
                    for cell in obj['cells']:
                        x,y,w,h=cell['rect']
                        if cell.get('fill'):
                            draw.rectangle([round(v*scale) for v in [x,y,x+w,y+h]],fill=cell['fill'])
                        edges=dict(left=[x,y,x,y+h],right=[x+w,y,x+w,y+h],top=[x,y,x+w,y],bottom=[x,y+h,x+w,y+h])
                        for side,border in cell['borders'].items():
                            if border['type']=='SOLID':
                                draw.line([v*scale for v in edges[side]],fill=border['color'],width=max(1,round(border['width']*scale)))
                            elif border['type']=='DASH':
                                # Thin Hancom dash: 2 on / 3 off at 300 dpi,
                                # measured independently from retained SDK
                                # horizontal and vertical raster strokes.
                                x1,y1,x2,y2=[round(v*scale) for v in edges[side]]
                                length=max(abs(x2-x1),abs(y2-y1));on=max(1,round(48*scale));off=max(1,round(72*scale))
                                for start in range(0,length+1,on+off):
                                    end=min(length,start+on-1)
                                    segment=(x1+start,y1,x1+end,y1) if y1==y2 else (x1,y1+start,x1,y1+end)
                                    draw.line(segment,fill=border['color'],width=max(1,round(border['width']*scale)))
            if native_cells:
                im=paint_borders(im,native_cells,dpi,junction_cells=all_cells);draw=ImageDraw.Draw(im)
            for cell in fallback_cells:self._joins(draw,cell,scale)
            if self.native_table_borders and all_cells:
                im=paint_borders(im,all_cells,dpi,continuations_only=True);draw=ImageDraw.Draw(im)
            native_text=os.name=='nt'
            if native_text:
                from .windows_text import draw_glyphs
                im=draw_glyphs(im,page,dpi,validation_reports=self.text_font_validation)
                draw=ImageDraw.Draw(im)
            for line in page['lines']:
                for g in line['glyphRuns']:
                    if g['glyphId']==0: continue
                    ft=self.fonts[g['fontFile']][2]
                    ft.set_char_size(round(g['height']/100*64),0,dpi,dpi)
                    matrix=freetype.Matrix(round(g['ratio']/100*65536),round((g['ratio']/300 if g['italic'] else 0)*65536),0,65536)
                    x=(g['origin'][0]+g['offset'][0])*scale; y=(g['origin'][1]+g['offset'][1])*scale
                    # Keep fractional origin in FT translation instead of integer rounding.
                    ix=math.floor(x); iy=math.floor(y)
                    ft.set_transform(matrix,freetype.Vector(round((x-ix)*64),round(-(y-iy)*64)))
                    if native_text:
                        bm=None
                    elif g.get('syntheticBold'):
                        ft.load_glyph(g['glyphId'],freetype.FT_LOAD_NO_HINTING)
                        freetype.FT_GlyphSlot_Embolden(ft.glyph._FT_GlyphSlot)
                        ft.glyph.render(freetype.FT_RENDER_MODE_NORMAL)
                    else:
                        ft.load_glyph(g['glyphId'],freetype.FT_LOAD_RENDER | freetype.FT_LOAD_NO_HINTING)
                    if not native_text:bm=ft.glyph.bitmap
                    color=g['color']; color=color if str(color).startswith('#') else '#'+color
                    if bm is not None and bm.width and bm.rows:
                        mask=Image.frombytes('L',(bm.width,bm.rows),bytes(bm.buffer), 'raw','L',bm.pitch)
                        im.paste(color,(ix+ft.glyph.bitmap_left,iy-ft.glyph.bitmap_top),mask)
                    if g['underline']:
                        # Hancom bottom underline is a layout decoration at the
                        # em box foot; font post position remains diagnostic.
                        # Bottom decorations share the line's em foot even
                        # when an underlined run is smaller than the line.
                        # Place the stroke edge below that foot, and quantize
                        # thickness down to device pixels (8pt needs 1px).
                        uy=y+line['height']*.15*scale+g['underlineThickness']*scale/2
                        draw.line((x,uy,x+(g['advance']+g['justifyAdvance'])*scale,uy),fill=color,width=max(1,math.floor(g['underlineThickness']*scale)))
            im.save(out/f'p{page["index"]}.png')
