# SPDX-License-Identifier: Apache-2.0
"""Explicit font resources: unmodified free download and optional OS fonts."""
from pathlib import Path
import os
import sys

def font_resources(directory=None):
    root=Path(directory) if directory else Path(__file__).with_name('resources')/'fonts'
    if os.name=='nt':
        value=os.path.abspath(root)
        if not value.startswith('\\\\?\\'):
            value=('\\\\?\\UNC\\'+value[2:]) if value.startswith('\\\\') else ('\\\\?\\'+value)
        root=Path(value)
    registry={
        '함초롬바탕':(root/'HCRBatang.ttf',root/'HCRBatang-Bold.ttf'),
        '함초롬돋움':(root/'HCRDotum.ttf',root/'HCRDotum-Bold.ttf'),
    }
    if os.name=='nt':
        system=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        if all((system/p).is_file() for p in ['malgun.ttf','malgunbd.ttf']):
            registry['맑은 고딕']=(system/'malgun.ttf',system/'malgunbd.ttf')
    elif sys.platform=='darwin':
        # Optional user-installed, licensed OS fonts. Never silently map a
        # Windows family to a different Mac family or bundle those files.
        for system in [Path.home()/'Library/Fonts',Path('/Library/Fonts')]:
            if all((system/p).is_file() for p in ['malgun.ttf','malgunbd.ttf']):
                registry['맑은 고딕']=(system/'malgun.ttf',system/'malgunbd.ttf')
                break
    return {family:pair for family,pair in registry.items() if all(p.is_file() for p in pair)}
