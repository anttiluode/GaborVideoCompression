"""Offline verification of the SlapStackVideoCompression coder loop.
Mirrors the JS encoder exactly: Landweber refit (8 it, step 0.45) -> deaths
(|a|<thr) -> MP births (<=B/frame) -> 1+4 bit log quantizer (fixed range)
-> decode from quantized amps. Moving test pattern, 60 frames.
PASS criteria: churn well below 100%, event bits << intra bits after
warm-up, PSNR stable and comparable to static experiment.
"""
import numpy as np
from math import lgamma
SZ=64; NPX=SZ*SZ
rng=np.random.default_rng(0)

# dictionary (same as demo)
scales=[(2,4),(4,8),(8,16),(16,32)]
atoms=[]; meta=[]
g=np.arange(SZ)
for si,(sig,st) in enumerate(scales):
    lam=2.2*sig
    for y0 in range(st//2,SZ,st):
        for x0 in range(st//2,SZ,st):
            Xr=g[None,:]-x0; Yr=g[:,None]-y0
            env=np.exp(-(Xr**2+Yr**2)/(2*sig**2))
            atoms.append(env.copy()); meta.append((si,sig,x0,y0))
            for o in range(4):
                th=np.pi*o/4; u=Xr*np.cos(th)+Yr*np.sin(th)
                for ph in (0.0,np.pi/2):
                    atoms.append(env*np.cos(2*np.pi*u/lam+ph)); meta.append((si,sig,x0,y0))
D=np.stack([a.ravel() for a in atoms]).T
D/=np.linalg.norm(D,axis=0,keepdims=True)
NA=D.shape[1]

QLO,QHI,QL=np.log(0.01),np.log(25),16
def quant(v):
    m=np.clip(abs(v),0.01,25)
    q=round((np.log(m)-QLO)/(QHI-QLO)*(QL-1))
    return q,np.sign(v)*np.exp(QLO+q/(QL-1)*(QHI-QLO))

def frame(t):
    x=np.arange(SZ); X,Y=np.meshgrid(x,x)
    cx=32+16*np.cos(0.6*t); cy=32+12*np.sin(0.9*t)
    v=0.30+0.25*Y/SZ
    m=(X-cx)**2+(Y-cy)**2<130
    v[m]=0.5+0.35*np.sin(0.9*X[m]+2*t)
    v[(np.abs(X-46)<8)&(np.abs(Y-18)<8)]=0.12
    return np.clip(v,0,1).ravel()

def lgC(n,k): return (lgamma(n+1)-lgamma(k+1)-lgamma(n-k+1))/np.log(2)

K,B,DTH=140,5,0.02
active={}   # atom -> [amp, qcode, qsign, age]
tot_ev=tot_intra=0; churns=[]; psnrs=[]
print(f"{'f':>3} {'gates':>5} {'birth':>5} {'death':>5} {'upd':>4} {'churn%':>7} {'evbits':>7} {'intrabits':>9} {'PSNR':>6}")
for f in range(60):
    img=frame(f/12.0)          # ~12 fps equivalent motion
    ids=list(active.keys())
    # refit
    for _ in range(8):
        rec=D[:,ids]@np.array([active[a][0] for a in ids]) if ids else np.zeros(NPX)
        r=img-rec
        if ids:
            c=D[:,ids].T@r
            for a,ci in zip(ids,c): active[a][0]+=0.45*ci
    # deaths
    deaths=[a for a in ids if abs(active[a][0])<DTH]
    for a in deaths: del active[a]
    ids=list(active.keys())
    rec=D[:,ids]@np.array([active[a][0] for a in ids]) if ids else np.zeros(NPX)
    r=img-rec
    # births
    births=0
    for _ in range(B):
        if len(active)>=K: break
        c=D.T@r; c[ids]=0 if ids else c[[]]
        for a in ids: c[a]=0
        j=int(np.argmax(np.abs(c)))
        if abs(c[j])<DTH*1.6: break
        active[j]=[c[j],None,None,0]; births+=1
        r-=c[j]*D[:,j]; ids.append(j)
    # quantize + updates + age
    upd=0
    for a,(amp,qc,qs,age) in list(active.items()):
        q,val=quant(amp)
        s=np.sign(amp)
        if age>0 and (q!=qc or s!=qs): upd+=1
        active[a]=[amp,q,s,age+1]
    # decode from quantized
    qv=np.array([np.sign(active[a][0])*np.exp(QLO+active[a][1]/(QL-1)*(QHI-QLO)) for a in active])
    rec_q=D[:,list(active.keys())]@qv if active else np.zeros(NPX)
    ps=10*np.log10(1.0/max(np.mean((img-rec_q)**2),1e-12))
    ev=births*(12+5)+len(deaths)*8+upd*(8+5)+16
    intra=round(lgC(NA,max(len(active),1)))+len(active)*5
    churn=100*(births+len(deaths))/max(len(active),1)
    if f>=10: tot_ev+=ev; tot_intra+=intra; churns.append(churn); psnrs.append(ps)
    if f%6==0 or f<4:
        print(f"{f:>3} {len(active):>5} {births:>5} {len(deaths):>5} {upd:>4} {churn:>7.1f} {ev:>7} {intra:>9} {ps:>6.2f}")
print("-"*62)
print(f"steady state (frames 10-59): churn {np.mean(churns):.1f}%  "
      f"event bits/frame {tot_ev/50:.0f}  intra {tot_intra/50:.0f}  "
      f"ratio intra/event {tot_intra/max(tot_ev,1):.1f}x  raw/event {32768/(tot_ev/50):.0f}x  "
      f"PSNR {np.mean(psnrs):.2f} dB")
