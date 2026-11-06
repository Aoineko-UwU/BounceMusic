"""Fixed mouse shortcuts; ordinary drag and context-menu clicks stay available."""
DEFAULTS={'align':'middle','earlier':'shift+left','later':'shift+right','auto':'shift+middle'}
BINDING_LABELS={'middle':'鼠标中键','shift+left':'Shift+鼠标左键',
                'shift+right':'Shift+鼠标右键','shift+middle':'Shift+鼠标中键'}


def mouse_code(number,state=0):
    button={1:'left',2:'middle',3:'right'}.get(number,'')
    modifiers=[]
    if state&0x4: modifiers.append('ctrl')
    if state&(0x8|0x20000): modifiers.append('alt')
    if state&0x1: modifiers.append('shift')
    return '+'.join(modifiers+[button]) if button else ''
