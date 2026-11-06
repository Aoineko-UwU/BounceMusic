"""Beat-grid animation timing and a lightweight perspective card rotation."""
import math
import numpy as np
from PIL import Image


def flip_pose(index, age, attack, hold, release, cadence):
    """Count squashes on the audio grid, including frames the UI did not render."""
    index=max(0,int(index)); cadence=max(1,int(cadence))
    before=index//cadence
    after=(index+1)//cadence
    start=180. if before%2 else 0.
    end=180. if after%2 else 0.
    progress=max(0.,min(1.,(age-attack-hold)/max(.001,release)))
    eased=progress**3*(10.+progress*(-15.+6.*progress))
    return start+(end-start)*eased


def perspective_frame(source, width, height, angle):
    """Project a transparent card around its vertical axis with depth and slight roll."""
    radians=math.radians(angle)
    cosine=math.cos(radians)
    mirrored=cosine<0
    frame=source.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirrored else source
    if abs(math.sin(radians))<.001:
        return frame.resize((width,height),Image.Resampling.BILINEAR)
    projected=max(2.,width*max(.055,abs(cosine)))
    depth=.19*math.sin(radians)*(-1. if mirrored else 1.)
    roll=.045*math.sin(2*radians)
    c,s=math.cos(roll),math.sin(roll)
    points=[]
    for x,y in ((-1,-1),(1,-1),(1,1),(-1,1)):
        scale=1./(1.-x*depth)
        px=x*projected*.5*scale; py=y*height*.5*scale*(1.-abs(depth))
        points.append((px*c-py*s,px*s+py*c))
    left=min(x for x,y in points); top=min(y for x,y in points)
    out_width=max(2,math.ceil(max(x for x,y in points)-left)+2)
    out_height=max(2,math.ceil(max(y for x,y in points)-top)+2)
    target=[(x-left+1,y-top+1) for x,y in points]
    origin=((0,0),(frame.width,0),(frame.width,frame.height),(0,frame.height))
    matrix=[]; values=[]
    for (x,y),(u,v) in zip(target,origin):
        matrix.extend(((x,y,1,0,0,0,-u*x,-u*y),(0,0,0,x,y,1,-v*x,-v*y)))
        values.extend((u,v))
    coefficients=np.linalg.solve(np.asarray(matrix),np.asarray(values))
    result=frame.transform((out_width,out_height),Image.Transform.PERSPECTIVE,coefficients,
                           Image.Resampling.BILINEAR,fillcolor=(0,0,0,0))
    # Mild side lighting preserves the original alpha, including transparent holes.
    shadow=Image.new('RGBA',result.size,(0,0,0,0)); shadow.putalpha(result.getchannel('A'))
    return Image.blend(result,shadow,.10*abs(math.sin(radians)))
