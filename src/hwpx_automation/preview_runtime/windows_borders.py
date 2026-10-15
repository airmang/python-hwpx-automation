# SPDX-License-Identifier: Apache-2.0
"""Windows geometric table strokes from authored cell rectangles and styles.

No document caches, reference pixels, SDK, or global font/system changes.
"""
import ctypes as C
from typing import Any
from itertools import groupby
from .windows_text import _Header, _BitmapInfo, _Transform

P=C.c_void_p;I=C.c_int32;U=C.c_uint32
_UNITS=100  # Retain hundredths of an authored HWPUNIT in GDI's integer grid.


class _Brush(C.Structure):
    _fields_=[('style',U),('color',U),('hatch',C.c_size_t)]


class _Point(C.Structure):
    _fields_=[('x',I),('y',I)]


class _Rect(C.Structure):
    _fields_=[('left',I),('top',I),('right',I),('bottom',I)]


def supported(cells):
    return all(edge['type'] in {'NONE','SOLID','DASH'} for cell in cells for edge in cell['borders'].values())


def _rgb(color):
    color=color.lstrip('#')
    if len(color)!=6:raise ValueError('Invalid border RGB color')
    r,g,b=(int(color[n:n+2],16) for n in [0,2,4])
    return r|(g<<8)|(b<<16)


def _segments(cell):
    x,y,w,h=cell['rect']
    left,top,right,bottom=[round(v*_UNITS) for v in [x,y,x+w,y+h]]
    if any(abs(v)>=2**31 for v in [left,top,right,bottom]):raise ValueError('Table geometry exceeds native coordinate limit')
    borders=cell['borders'];sides=['top','right','bottom','left']
    vertices=[(left,top),(right,top),(right,bottom),(left,bottom)]
    uniform=all(edge==borders['left'] for edge in borders.values())
    if uniform:return [(borders['left'],vertices+[vertices[0]],True)]
    start=next(i for i in range(4) if borders[sides[i]]!=borders[sides[(i-1)%4]])
    groups=[]
    for offset in range(4):
        i=(start+offset)%4;edge=borders[sides[i]]
        if not groups or groups[-1][0]!=edge:groups.append((edge,[vertices[i]],[]))
        groups[-1][1].append(vertices[(i+1)%4]);groups[-1][2].append(sides[i])
    result=[]
    for edge,points,group_sides in groups:
        points=list(points)
        for endpoint,side,neighbor in [(0,group_sides[0],sides[(sides.index(group_sides[0])-1)%4]),
                                      (-1,group_sides[-1],sides[(sides.index(group_sides[-1])+1)%4])]:
            perpendicular=borders[neighbor]
            if edge['type']=='DASH' and side in {'top','bottom'} and perpendicular['type']=='SOLID' and edge['width']<perpendicular['width']:
                # Horizontal dash phase begins at the left outside edge;
                # its right terminal stays inside a wider frame.
                px,py=points[endpoint]
                points[endpoint]=(round(px-perpendicular['width']*_UNITS/2),py)
                continue
            if edge['type']!='SOLID' or side not in {'top','bottom'} or perpendicular['type']!='SOLID' or edge['width']>=perpendicular['width']:continue
            # A thin horizontal frame includes the outside half-width of its
            # wider vertical neighbor. Flat caps keep unrelated incoming
            # segments intact at a change of border style.
            delta=perpendicular['width']*_UNITS/2
            px,py=points[endpoint]
            points[endpoint]=(round(px+(-delta if neighbor=='left' else delta)),py)
        result.append((edge,points,False))
    return result


def _horizontal_junction_widths(cells):
    widths={}
    for cell in cells:
        x,y,w,h=cell['rect'];owner=cell.get('strokeOwner',())
        for side,cy in [('top',y),('bottom',y+h)]:
            edge=cell['borders'][side]
            if edge['type']!='SOLID':continue
            for cx in [x,x+w]:
                key=(owner,round(cx*_UNITS),round(cy*_UNITS))
                widths[key]=max(widths.get(key,0),edge['width'])
    return widths


def _terminal_frames(cell,junctions=None):
    if cell.get('rowSpan',1)>cell.get('colSpan',1):return []
    x,y,w,h=cell['rect'];borders=cell['borders'];result=[]
    frames=[('top',y),('bottom',y+h)]
    for side,cy in frames:
        edge=borders[side]
        if edge['type']!='SOLID':continue
        if side=='top' and cell.get('colSpan',1)==1 and junctions is not None:
            owner=cell.get('strokeOwner',())
            if any(junctions.get((owner,round(cx*_UNITS),round(cy*_UNITS)),0)>edge['width'] for cx in [x,x+w]):continue
        left,right=x,x+w;extended=False
        for neighbor in ['left','right']:
            other=borders[neighbor]
            if other['type']!='SOLID' or other['width']<=edge['width']:continue
            if neighbor=='left':left-=other['width']/2
            else:right+=other['width']/2
            extended=True
        if extended:result.append((edge,[(round(left*_UNITS),round(cy*_UNITS)),(round(right*_UNITS),round(cy*_UNITS))]))
    return result


def _continuous_strokes(cells):
    bounds={}
    vertex_widths={}
    for cell in cells:
        x,y,w,h=cell['rect'];owner=cell.get('strokeOwner',())
        borders=cell['borders']
        for vx,vy,a,b in [(x,y,'left','top'),(x+w,y,'right','top'),(x,y+h,'left','bottom'),(x+w,y+h,'right','bottom')]:
            key=(owner,round(vx*_UNITS),round(vy*_UNITS))
            widths=[borders[side]['width'] for side in [a,b] if borders[side]['type']=='SOLID']
            vertex_widths[key]=max(vertex_widths.get(key,0),*widths) if widths else vertex_widths.get(key,0)
        values=[round(v*_UNITS) for v in [x,y,x+w,y+h]]
        if owner not in bounds:bounds[owner]=values
        else:
            old=bounds[owner];bounds[owner]=[min(old[0],values[0]),min(old[1],values[1]),max(old[2],values[2]),max(old[3],values[3])]
    groups={}
    for cell in cells:
        x,y,w,h=cell['rect'];owner=cell.get('strokeOwner',())
        for side,axis,fixed,start,stop in [('left','v',x,y,y+h),('right','v',x+w,y,y+h),('top','h',y,x,x+w),('bottom','h',y+h,x,x+w)]:
            edge=cell['borders'][side]
            if edge['type']!='SOLID':continue
            outer=bounds[owner]
            if round(fixed*_UNITS) not in ([outer[0],outer[2]] if axis=='v' else [outer[1],outer[3]]):continue
            key=(owner,axis,round(fixed*_UNITS),edge['color'],edge['width'])
            groups.setdefault(key,[]).append((round(start*_UNITS),round(stop*_UNITS)))
    result=[]
    for (owner,axis,fixed,color,width),intervals in groups.items():
        merged=[]
        for start,stop in sorted(set(intervals)):
            if merged and start<=merged[-1][1]:
                prior=merged[-1];prior[1]=max(prior[1],stop);prior[2]=max(prior[2],stop-start)
            else:merged.append([start,stop,stop-start])
        for start,stop,longest in merged:
            # Coincident copies of a shared edge are not a continuation.
            if stop-start<=longest:continue
            # Preserve the separately painted mixed-style end corners.
            first=(owner,fixed,start) if axis=='v' else (owner,start,fixed)
            last=(owner,fixed,stop) if axis=='v' else (owner,stop,fixed)
            start+=max(1,round(max(width,vertex_widths.get(first,0))*_UNITS/2))
            stop-=max(1,round(max(width,vertex_widths.get(last,0))*_UNITS/2))
            if stop<=start:continue
            points=[(fixed,start),(fixed,stop)] if axis=='v' else [(start,fixed),(stop,fixed)]
            result.append((dict(type='SOLID',width=width,color=color),points))
    return sorted(result,key=lambda stroke:stroke[0]['width'])


def _ordered_cells(cells):
    # Resolve same-row shared vertices after ordinary cells have been
    # painted. Keep table/story ownership and row order intact.
    for _,group in groupby(cells,key=lambda cell:(cell.get('strokeOwner',()),cell.get('row',0))):
        yield from sorted(group,key=lambda cell:cell.get('colSpan',1))


def _junction_strokes(cells):
    vertices={};bounds={}
    for cell in cells:
        x,y,w,h=cell['rect'];owner=cell.get('strokeOwner',())
        left,top,right,bottom=[round(v*_UNITS) for v in [x,y,x+w,y+h]]
        old=bounds.get(owner,[left,top,right,bottom]);bounds[owner]=[min(old[0],left),min(old[1],top),max(old[2],right),max(old[3],bottom)]
        for side,a,b in [('top',(left,top),(right,top)),('bottom',(left,bottom),(right,bottom)),('left',(left,top),(left,bottom)),('right',(right,top),(right,bottom))]:
            edge=cell['borders'][side]
            if edge['type']!='SOLID':continue
            mixed_dash=any(border['type']=='DASH' for border in cell['borders'].values())
            for point,other in [(a,b),(b,a)]:vertices.setdefault((owner,*point),[]).append((edge,other,cell.get('colSpan',1),mixed_dash))
    strokes=[]
    for (owner,x,y),incident in vertices.items():
        horizontal=[(edge,point,span,dash) for edge,point,span,dash in incident if point[1]==y]
        vertical=[(edge,point,span,dash) for edge,point,span,dash in incident if point[0]==x]
        if not horizontal or not vertical:continue
        widest=max(edge['width'] for edge,_,_,_ in horizontal)
        thin=[(edge,point,span,dash) for edge,point,span,dash in vertical if edge['width']<widest]
        if not thin:continue
        reach=round(widest*_UNITS/2)
        directions={1 if point[0]>x else -1 for edge,point,_,_ in horizontal if edge['width']==widest}
        frame_turn=len(directions)==1 and any(edge['width']==widest for edge,_,_,_ in vertical)
        exterior=x in [bounds[owner][0],bounds[owner][2]]
        merged_incoming=frame_turn and any(point[1]<y and span>1 for _,point,span,_ in thin)
        dashed_incoming=frame_turn and exterior and any(point[1]<y and dash for _,point,_,dash in thin)
        if exterior or frame_turn:
            # Preserve ordinary incoming ends. A merged divider or the end
            # of a mixed dashed cell yields to a turning wider frame.
            for edge,point,span,dash in thin:
                if (merged_incoming and span>1) or (dashed_incoming and dash and point[1]<y):continue
                if frame_turn and not exterior and point[1]>y:continue
                direction=1 if point[1]>y else -1
                strokes.append((edge,[(x,y),(x,y+direction*reach)]))
        if not (exterior or frame_turn) or merged_incoming or dashed_incoming:
            # Inside the table a wider horizontal rule spans the shared
            # vertex continuously instead of accepting a thin vertical cap.
            for edge,point,_,_ in horizontal:
                if edge['width']!=widest:continue
                direction=1 if point[0]>x else -1
                strokes.append((edge,[(x,y),(x+direction*reach,y)]))
    return strokes


def paint(image,cells,dpi=300,*,continuations_only=False,junction_cells=None):
    from PIL import Image  # pyright: ignore[reportMissingImports] -- optional native-preview extra
    if dpi not in {144,300}:raise ValueError('Unsupported table raster DPI')
    if min(image.size)<=0 or image.width*image.height>32000000:raise ValueError('table output raster exceeds runtime limit')
    if not continuations_only and not supported(cells):raise ValueError('Unsupported native table border type')
    continuations=(_continuous_strokes(cells)+_junction_strokes(cells)) if continuations_only else []
    junctions=_horizontal_junction_widths(cells if junction_cells is None else junction_cells)
    if continuations_only and not continuations:return image
    lib=getattr(C,'WinDLL')('gdi32',use_last_error=True)
    def bind(name,args,ret: Any=I):
        fn=getattr(lib,name);fn.argtypes=args;fn.restype=ret;return fn
    create_dc=bind('CreateCompatibleDC',[P],P);select=bind('SelectObject',[P,P],P)
    delete=bind('DeleteObject',[P]);delete_dc=bind('DeleteDC',[P])
    create=bind('CreateDIBSection',[P,C.POINTER(_BitmapInfo),U,C.POINTER(P),P,U],P)
    pen=bind('ExtCreatePen',[U,U,C.POINTER(_Brush),U,P],P)
    device_pen=bind('CreatePen',[I,I,U],P)
    brush=bind('CreateSolidBrush',[U],P)
    poly=bind('Polyline',[P,C.POINTER(_Point),I])
    begin=bind('BeginPath',[P]);end=bind('EndPath',[P]);close=bind('CloseFigure',[P]);stroke=bind('StrokePath',[P])
    move=bind('MoveToEx',[P,I,I,P]);line=bind('LineTo',[P,I,I])
    mode=bind('SetGraphicsMode',[P,I]);transform=bind('SetWorldTransform',[P,C.POINTER(_Transform)])
    fill=getattr(C,'WinDLL')('user32',use_last_error=True).FillRect;fill.argtypes=[P,C.POINTER(_Rect),P];fill.restype=I
    dc=create_dc(None)
    if not dc:raise OSError('CreateCompatibleDC failed')
    bitmap=None;old_bitmap=None;old_pen=None;pens={};brushes={}
    scale=dpi/7200;matrix=_Transform(scale/_UNITS,0,0,scale/_UNITS,0,0)
    try:
        w,h=image.size;bits=P();info=_BitmapInfo(_Header(C.sizeof(_Header),w,-h,1,32,0,w*h*4,0,0,0,0))
        bitmap=create(dc,C.byref(info),0,C.byref(bits),None,0)
        if not bitmap or not bits:raise OSError('CreateDIBSection failed')
        old_bitmap=select(dc,bitmap)
        if not mode(dc,2) or not transform(dc,C.byref(matrix)):raise OSError('Table world transform failed')
        pixels=image.convert('RGBA').tobytes('raw','BGRA');C.memmove(bits,pixels,len(pixels));del pixels
        def choose(edge):
            nonlocal old_pen
            width=max(1,round(edge['width']*_UNITS));color=_rgb(edge['color']);key=(width,color)
            if key not in pens:
                # PS_GEOMETRIC | PS_ENDCAP_FLAT; the default join is round.
                pens[key]=pen(0x10000|0x200,width,C.byref(_Brush(0,color,0)),0,None)
                if not pens[key]:raise OSError('ExtCreatePen failed')
            previous=select(dc,pens[key]);old_pen=old_pen or previous
        def open_stroke(edge,points):
            choose(edge)
            array=(_Point*len(points))(*(_Point(*point) for point in points[::-1]))
            if not poly(dc,array,len(points)):raise OSError('Table stroke failed')
        def manual_dashed_stroke(edge,points):
            nonlocal old_pen
            width=max(1,round(edge['width']*scale));color=_rgb(edge['color']);key=('DASH',width,color)
            if key not in pens:
                pens[key]=device_pen(0,width,color)
                if not pens[key]:raise OSError('CreatePen failed')
            previous=select(dc,pens[key]);old_pen=old_pen or previous
            identity=_Transform(1,0,0,1,0,0)
            if not transform(dc,C.byref(identity)):raise OSError('Dash transform failed')
            on=max(1,round(48*scale));off=max(1,round(72*scale))
            for first,last in zip(points,points[1:]):
                x1,y1=[round(v*scale/_UNITS) for v in first];x2,y2=[round(v*scale/_UNITS) for v in last]
                if y1==y2:x1,x2=sorted([x1,x2]);length=x2-x1
                else:y1,y2=sorted([y1,y2]);length=y2-y1
                for start in range(0,length+1,on+off):
                    stop=min(length-1,start+on-1)
                    if stop<start:continue
                    a,b=((x1+start,y1),(x1+stop+1,y1)) if y1==y2 else ((x1,y1+start),(x1,y1+stop+1))
                    if not move(dc,*a,None) or not line(dc,*b):raise OSError('Table dash stroke failed')
            if not transform(dc,C.byref(matrix)):raise OSError('Table world transform failed')
        def geometric_dashed_stroke(edge,points):
            nonlocal old_pen
            width=max(1,round(edge['width']*_UNITS));color=_rgb(edge['color']);key=('DASH_GEOMETRIC',width,color)
            if key not in pens:
                on=max(1,round(48*scale));off=max(1,round(72*scale))
                styles=(U*2)(round(on/scale*_UNITS),round(off/scale*_UNITS))
                pens[key]=pen(0x10000|0x200|7,width,C.byref(_Brush(0,color,0)),2,styles)
                if not pens[key]:raise OSError('Geometric dash pen failed')
            previous=select(dc,pens[key]);old_pen=old_pen or previous
            for first,last in zip(points,points[1:]):
                # Keep the existing positive-axis source phase, without
                # quantizing the whole source segment to device coordinates.
                first,last=sorted([first,last])
                array=(_Point*2)(_Point(*first),_Point(*last))
                if not poly(dc,array,2):raise OSError('Geometric dash stroke failed')
        def dashed_stroke(edge,points):
            for first,last in zip(points,points[1:]):
                if first[1]==last[1]:manual_dashed_stroke(edge,[first,last])
        for cell in ([] if continuations_only else _ordered_cells(cells)):
            if cell.get('fill'):
                color=_rgb(cell['fill'])
                if color not in brushes:
                    brushes[color]=brush(color)
                    if not brushes[color]:raise OSError('CreateSolidBrush failed')
                x,y,cw,ch=cell['rect'];coords=[round(v*scale) for v in [x,y,x+cw,y+ch]]
                rect=_Rect(coords[0],coords[1],coords[2]+1,coords[3]+1)
                identity=_Transform(1,0,0,1,0,0)
                if not transform(dc,C.byref(identity)):raise OSError('Fill transform failed')
                if not fill(dc,C.byref(rect),brushes[color]):raise OSError('Table cell fill failed')
                if not transform(dc,C.byref(matrix)):raise OSError('Table world transform failed')
            for edge,points,_ in _segments(cell):
                if edge['type']!='DASH':continue
                for first,last in zip(points,points[1:]):
                    # The solid horizontal rules cover incoming vertical
                    # dash ends. Keep exact authored width and origin here.
                    if first[0]==last[0]:geometric_dashed_stroke(edge,[first,last])
            dashed=[]
            for edge,points,closed in _segments(cell):
                if edge['type']=='DASH':dashed.append((edge,points));continue
                if edge['type']!='SOLID':continue
                choose(edge);points=points[::-1]
                if closed:
                    if not begin(dc) or not move(dc,*points[0],None):raise OSError('Table path failed')
                    for point in points[1:-1]:
                        if not line(dc,*point):raise OSError('Table path line failed')
                    if not close(dc) or not end(dc) or not stroke(dc):raise OSError('Table closed stroke failed')
                else:
                    array=(_Point*len(points))(*(_Point(*point) for point in points))
                    if not poly(dc,array,len(points)):raise OSError('Table stroke failed')
            for edge,points in _terminal_frames(cell,junctions):open_stroke(edge,points)
            for edge,points in dashed:dashed_stroke(edge,points)
        for edge,points in continuations:open_stroke(edge,points)
        return Image.frombytes('RGB',image.size,C.string_at(bits,w*h*4),'raw','BGRX')
    finally:
        if old_pen:select(dc,old_pen)
        if old_bitmap:select(dc,old_bitmap)
        for handle in pens.values():delete(handle)
        for handle in brushes.values():delete(handle)
        if bitmap:delete(bitmap)
        delete_dc(dc)
