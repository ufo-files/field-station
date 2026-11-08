"""Finite, shaped International Morse/CW bursts; no device access."""
import math
import numpy as np

RATE=8_000_000
OFFSET=100_000
AMPLITUDE=24
FREQUENCY=441_500_000
WPM=20
MAX_SECONDS=30
MORSE=dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,?/=-',
 '.- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- .-..- -.-- --.. ----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----. .-.-.- --..-- ..--.. -..-. -...- -....-'.split()))
# X is -..- (keep the table explicit and tested).
MORSE['X']='-..-'

def plan(message,callsign):
    if not isinstance(message,str):raise ValueError('Enter a message.')
    text=' '.join(message.upper().split())
    if not text or len(text)>64:raise ValueError('Use 1–64 characters for a Morse transmission.')
    if any(c not in MORSE and c!=' ' for c in text):raise ValueError('Morse supports A–Z, 0–9, spaces, and . , ? / = -')
    if any(c not in MORSE for c in callsign):raise ValueError('Invalid station identification.')
    text += ' DE '+callsign
    # All intervals in dot units. Seven units between words, three between letters.
    spans=[]
    for wi,word in enumerate(text.split()):
        if wi:spans.append((False,7))
        for ci,char in enumerate(word):
            if ci:spans.append((False,3))
            for si,mark in enumerate(MORSE[char]):
                if si:spans.append((False,1))
                spans.append((True,3 if mark=='-' else 1))
    spans=[(False,2)]+spans+[(False,2)]
    durations=[(on,round(units*1.2/WPM*RATE)) for on,units in spans]
    samples=sum(n for _,n in durations)
    if samples/RATE>MAX_SECONDS:raise ValueError('Message plus station ID exceeds 30 seconds. Shorten the message.')
    return dict(text=text,spans=durations,samples=samples,seconds=samples/RATE,frequency_hz=FREQUENCY,sample_rate=RATE,encoding='International Morse / CW, 20 WPM',bytes=samples*2)

def write_iq(path,p,cancel=lambda:False):
    # Offset from LO keeps its leakage outside the narrow wanted channel.
    # A physical output filter and measured power remain required.
    total=0;ramp=round(.005*RATE);period=RATE//OFFSET
    phase=2*np.pi*np.arange(period)/period
    lut=np.column_stack((np.cos(phase),np.sin(phase)))
    with open(path,'wb') as out:
        for on,count in p['spans']:
            for start in range(0,count,400_000):
                if cancel():raise ValueError('Transmission cancelled before RF output.')
                n=min(400_000,count-start)
                if on:
                    indexes=np.arange(n);pos=indexes+start
                    envelope=np.minimum(np.minimum(pos/ramp,(count-1-pos)/ramp),1).clip(0,1)
                    # Raised-cosine edges avoid hard keying clicks.
                    envelope=.5-.5*np.cos(np.pi*envelope)
                    values=np.rint(AMPLITUDE*lut[(indexes+total)%period]*envelope[:,None]).astype(np.int8)
                else:values=np.zeros((n,2),dtype=np.int8)
                out.write(values.tobytes());total+=n
    return total
