"""Grid timing and alpha-preserving flat image feedback, without audio hardware."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from animation import flip_pose, flat_frame, feedback_frame, breathing_step
from shortcuts import mouse_code


def test_flip_grid():
    def pose(index,age,cadence=2): return flip_pose(index,age,.10,.08,.30,cadence)
    assert [pose(i,.5) for i in range(8)]==[0.,180.,180.,0.,0.,180.,180.,0.]
    assert [pose(i,.5,1) for i in range(4)]==[180.,0.,180.,0.]
    assert pose(1,.17)==0. and 0.<pose(1,.32)<180.
    assert pose(2,0.)==pose(1,.5)
    # Sampling after skipped frames and reanchoring at index zero need no UI counter.
    assert pose(7,.5)==0. and pose(0,.5)==0.
    assert pose(1,.28)<pose(1,.38)


def test_flat_alpha():
    source=Image.new('RGBA',(100,100),(0,0,0,0))
    draw=ImageDraw.Draw(source)
    draw.rectangle((10,10,49,89),fill='red'); draw.rectangle((50,10,89,89),fill='blue')
    front=flat_frame(source,100,100,0.)
    back=flat_frame(source,100,100,180.)
    assert front.getpixel((25,50))==(255,0,0,255)
    assert back.getpixel((25,50))==(0,0,255,255)
    for angle in (30.,60.,90.,120.,150.):
        frame=flat_frame(source,100,100,angle)
        assert frame.mode=='RGBA' and frame.getchannel('A').getextrema()==(0,255)
        assert frame.getpixel((0,0))[3]==0
        assert frame.height==100
    assert flat_frame(source,100,100,90.).width==6
    assert source.getpixel((0,0))==(0,0,0,0)


def test_waiting_and_shine_alpha():
    source=Image.new('RGBA',(100,100),(40,80,160,255))
    source.putpixel((0,0),(0,0,0,0)); source.putpixel((50,50),(20,30,40,100))
    dark=feedback_frame(source,0); bright=feedback_frame(source,64)
    shine=feedback_frame(source,shine_step=32,shine_color=(0,255,0))
    for frame in (dark,bright,shine): assert frame.getchannel('A').tobytes()==source.getchannel('A').tobytes()
    assert sum(dark.getpixel((20,20))[:3])<sum(bright.getpixel((20,20))[:3])
    assert shine.getpixel((30,70))[1]>source.getpixel((30,70))[1]
    assert feedback_frame(source,shine_step=0).tobytes()==source.tobytes()
    assert feedback_frame(source,shine_step=64).tobytes()==source.tobytes()
    assert breathing_step(0,.5)==0 and breathing_step(1,.5)==64 and breathing_step(2,.5)==0
    assert mouse_code(1,1)=='shift+left' and mouse_code(2,1)=='shift+middle' and mouse_code(3,1)=='shift+right'


if __name__=='__main__':
    test_flip_grid(); test_flat_alpha(); test_waiting_and_shine_alpha()
    print('Animation checks passed.')
