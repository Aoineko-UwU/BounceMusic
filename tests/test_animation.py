"""Grid timing and transparent perspective rendering, without audio hardware."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from animation import flip_pose, perspective_frame


def test_flip_grid():
    def pose(index,age,cadence=2): return flip_pose(index,age,.10,.08,.30,cadence)
    assert [pose(i,.5) for i in range(8)]==[0.,180.,180.,0.,0.,180.,180.,0.]
    assert [pose(i,.5,1) for i in range(4)]==[180.,0.,180.,0.]
    assert pose(1,.17)==0. and 0.<pose(1,.32)<180.
    assert pose(2,0.)==pose(1,.5)
    # Sampling after skipped frames and reanchoring at index zero need no UI counter.
    assert pose(7,.5)==0. and pose(0,.5)==0.
    assert pose(1,.28)<pose(1,.38)


def test_perspective_alpha():
    source=Image.new('RGBA',(100,100),(0,0,0,0))
    draw=ImageDraw.Draw(source)
    draw.rectangle((10,10,49,89),fill='red'); draw.rectangle((50,10,89,89),fill='blue')
    front=perspective_frame(source,100,100,0.)
    back=perspective_frame(source,100,100,180.)
    assert front.getpixel((25,50))==(255,0,0,255)
    assert back.getpixel((25,50))==(0,0,255,255)
    for angle in (30.,60.,90.,120.,150.):
        frame=perspective_frame(source,100,100,angle)
        assert frame.mode=='RGBA' and frame.getchannel('A').getextrema()==(0,255)
        assert frame.getpixel((0,0))[3]==0
        assert frame.height<=110
    assert perspective_frame(source,100,100,90.).width<20
    assert source.getpixel((0,0))==(0,0,0,0)


if __name__=='__main__':
    test_flip_grid(); test_perspective_alpha()
    print('Animation checks passed.')
