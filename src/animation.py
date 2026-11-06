"""Beat-grid timing, flat image turns, and alpha-preserving feedback effects."""
import math
from functools import lru_cache
import numpy as np
from PIL import Image


def flip_pose(index, age, attack, hold, release, cadence):
    index=max(0,int(index)); cadence=max(1,int(cadence))
    before=index//cadence; after=(index+1)//cadence
    start=180. if before%2 else 0.; end=180. if after%2 else 0.
    progress=max(0.,min(1.,(age-attack-hold)/max(.001,release)))
    eased=progress*progress*(3.-2.*progress)
    return start+(end-start)*eased


def flat_frame(source, width, height, angle):
    projection=math.cos(math.radians(angle))
    frame=source.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if projection<0 else source
    return frame.resize((max(1,round(width*max(.06,abs(projection)))),height),Image.Resampling.BILINEAR)


def breathing_step(now, frequency):
    return round((.5-.5*math.cos(2*math.pi*frequency*now))*64)


@lru_cache(maxsize=12)
def diagonal_coordinates(width,height):
    return np.arange(height,dtype=np.float32)[:,None]+np.arange(width,dtype=np.float32)[None,:]


def feedback_frame(frame, idle_step=-1, idle_color=(255,255,255), shine_step=-1, shine_color=(255,255,255)):
    if idle_step<0 and shine_step<0: return frame
    alpha=frame.getchannel('A'); rgb=frame.convert('RGB')
    if idle_step>=0:
        wave=max(0.,min(1.,idle_step/64.))
        rgb=Image.blend(rgb,Image.new('RGB',rgb.size,'black'),.58*(1.-wave))
        rgb=Image.blend(rgb,Image.new('RGB',rgb.size,idle_color),.28*wave)
    if shine_step>=0:
        progress=max(0.,min(1.,shine_step/64.))
        width,height=rgb.size; band=max(12.,min(width,height)*.24)
        center=-band+progress*(width+height+2*band)
        values=np.clip(1.-np.abs(diagonal_coordinates(width,height)-center)/band,0.,1.)
        mask=Image.fromarray(np.asarray(values*175,dtype=np.uint8))
        rgb=Image.composite(Image.new('RGB',rgb.size,shine_color),rgb,mask)
    rgb.putalpha(alpha)
    return rgb
