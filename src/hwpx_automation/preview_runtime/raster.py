# SPDX-License-Identifier: Apache-2.0
"""OS-specific draw adapters; non-Windows picture fidelity remains unvalidated."""
import os
import math


def picture_crop_region(obj,pixel_size,*,integer_density=False):
    normalized=obj.get('cropNormalized')
    if normalized is None:return None
    if len(normalized)!=4 or any(not math.isfinite(v) for v in normalized):raise ValueError('invalid picture crop')
    if not (0<=normalized[0]<normalized[2]<=1 and 0<=normalized[1]<normalized[3]<=1):raise ValueError('invalid picture crop')
    if not integer_density:return tuple(v*pixel_size[i%2] for i,v in enumerate(normalized))
    canvas=obj.get('cropSourceCanvasHwpunit')
    if canvas is None:raise ValueError('experimental crop needs authored source canvas')
    if len(canvas)!=2 or min(canvas)<=0 or any(not math.isfinite(v) for v in canvas):raise ValueError('invalid source canvas')
    density=[round(7200*size/canvas[i]) for i,size in enumerate(pixel_size)]
    if min(density)<=0:raise ValueError('experimental source density is not supported')
    region=tuple(pixel_size[i%2] if v==1 else v*canvas[i%2]*density[i%2]/7200 for i,v in enumerate(normalized))
    if not (0<=region[0]<region[2]<=pixel_size[0] and 0<=region[1]<region[3]<=pixel_size[1]):raise ValueError('experimental crop exceeds source pixels')
    return region

class PortablePictureSampler:
    name='Pillow BICUBIC; rounded extents; non-Windows fidelity unvalidated'
    def resize(self,src,size,*,crop=None,background=None):
        from PIL import Image  # pyright: ignore[reportMissingImports] -- optional native-preview extra
        if min(size)<=0 or size[0]*size[1]>32000000:raise ValueError('picture output raster exceeds runtime limit')
        image=src.convert('RGBA').resize(tuple(size),Image.Resampling.BICUBIC,box=crop)
        output=background.copy().convert('RGB') if background is not None else Image.new('RGB',tuple(size),'white')
        output.paste(image,(0,0),image);return output
    def close(self):pass

def policy():
    return dict(name='Windows GDI+ HighQualityBicubic' if os.name=='nt' else PortablePictureSampler.name,
                quantization='round origin and each extent independently',network=False,
                platformFidelity='Windows retained-reference calibration' if os.name=='nt' else 'not validated')

def create_sampler():
    if os.name=='nt':
        from .windows_raster import WindowsPictureSampler
        return WindowsPictureSampler()
    return PortablePictureSampler()
