import vapoursynth as vs
import vsTAAmbk as taa  # https://github.com/HomeOfVapourSynthEvolution/vsTAAmbk
import fvsfunc as fvf  # https://github.com/Irrational-Encoding-Wizardry/fvsfunc
import mvsfunc as mvf  # https://github.com/HomeOfVapourSynthEvolution/mvsfunc
import havsfunc as haf  # https://github.com/HomeOfVapourSynthEvolution/havsfunc

core = vs.core

"""
lvsfunc = Light's Vapoursynth Functions
Scripts I (stole) 'borrowed' from other people and modified to my own liking. If something breaks, blame them.
"""


def fix_eedi3(clip, strength=1, alpha=0.25, beta=0.5, gamma=40, nrad=2, mdis=20, nsize=3, nns=3, qual=1):
    """
    Script stolen from Zastin. What it does is clamp the "change" done by eedi3 to the "change" of nnedi3. This should
    fix every issue created by eedi3, like for example this: https://i.imgur.com/hYVhetS.jpg
    
    Tested on Uchiage no Hanabi by Zastin, should work fine for everything else. Supposedly, at least.
    """

    if clip.format.bits_per_sample != 16:
        clip = fvf.Depth(clip, 16)
    bits = clip.format.bits_per_sample - 8
    thr = strength * (1 >> bits)
    strong = taa.TAAmbk(clip, aatype='Eedi3', alpha=alpha, beta=beta, gamma=gamma, nrad=nrad, mdis=mdis, mtype=0)
    weak = taa.TAAmbk(clip, aatype='Nnedi3', nsize=nsize, nns=nns, qual=qual, mtype=0)
    expr = 'x z - y z - * 0 < y x y {l} + min y {l} - max ?'.format(l=thr)
    if clip.format.num_planes > 1:
        expr = [expr, '']
    aa = core.std.Expr([strong, weak, clip], expr)
    mask = clip.std.Prewitt(planes=0).std.Binarize(50 >> bits, planes=0).std.Maximum(planes=0).std.Convolution([1] * 9,
                                                                                                               planes=0)
    return clip.std.MaskedMerge(aa, mask, planes=0)


def compare(clips, frames, match_clips=True):
    """
    Script stolen from XEL8o9 and slightly modified by me. Grabs a given frame from two clips for easier comparison.
    Intended order is [src, filtered].
    
    Example use:
    lvf.compare([src, filtered], [10, 20, 30, 40, 50], match_clips=True)
    """
    if len(clips) < 2:
        raise ValueError('compare: There must be at least two clips')
    width = clips[0].width
    height = clips[0].height
    for i in range(0, len(clips)):
        if clips[i].format.bits_per_sample != 16:
            clips[i] = fvf.Depth(clips[i], 16)
    final = None
    for frame in frames:
        newClip = core.std.Trim(clips[0], frame, frame)
        for i in range(1, len(clips)):
            nextFrame = core.std.Trim(clips[i], frame, frame)
            if nextFrame.width != width or nextFrame.height != height:
                if match_clips:
                    nextFrame = core.resize.Spline36(nextFrame, width, height)
                else:
                    raise ValueError('compare: The dimensions of each clip must be equal')
            newClip += nextFrame
        if final is None:
            final = newClip
        else:
            final += newClip
    return final


def super_aa(clip, mode=1):
    """
    Script stolen from Zastin and slightly modified by me. Was originally written to deal with Yuru Camp's odd line art,
    but can be used for other sources with botched line art and heavy aliasing.
    
    Mode 1 = Nnedi3 
    Mode 2 = Eedi3
    """
    if clip.format.bits_per_sample != 16:
        clip = fvf.Depth(clip, 16)
    clip_copy = clip
    srcY = clip.std.ShufflePlanes(0, vs.GRAY)
    if mode is 1:
        def aa(srcY):
            w, h = srcY.width, srcY.height
            srcY = srcY.std.Transpose()
            srcY = srcY.nnedi3.nnedi3(0, 1, 0, 3, 3, 2)
            srcY = srcY.nnedi3.nnedi3(1, 0, 0, 3, 3, 2)
            srcY = srcY.resize.Spline36(h, w, src_top=.5)
            srcY = srcY.std.Transpose()
            srcY = srcY.nnedi3.nnedi3(0, 1, 0, 3, 3, 2)
            srcY = srcY.nnedi3.nnedi3(1, 0, 0, 3, 3, 2)
            srcY = srcY.resize.Spline36(w, h, src_top=.5)
            return srcY
    elif mode is 2:
        def aa(srcY):
            w, h = srcY.width, srcY.height
            srcY = srcY.std.Transpose()
            srcY = srcY.eedi3m.EEDI3(0, 1, 0, 0.5, 0.2)
            srcY = srcY.znedi3.nnedi3(1, 0, 0, 3, 4, 2)
            srcY = srcY.resize.Spline36(h, w, src_top=.5)
            srcY = srcY.std.Transpose()
            srcY = srcY.eedi3m.EEDI3(0, 1, 0, 0.5, 0.2)
            srcY = srcY.znedi3.nnedi3(1, 0, 0, 3, 4, 2)
            srcY = srcY.resize.Spline36(w, h, src_top=.5)
            return srcY
    else:
        raise ValueError('super_aa: unknown mode')

    def csharp(flt, src):
        blur = core.std.Convolution(flt, [1] * 9)
        return core.std.Expr([flt, src, blur], 'x y < x x + z - x max y min x x + z - x min y max ?')

    aaclip = aa(srcY)
    aaclip = csharp(aaclip, srcY).rgvs.Repair(srcY, 13)

    if clip_copy.format.color_family is vs.GRAY:
        return aaclip
    elif clip_copy.format.color_family is not vs.GRAY:
        srcU = clip.std.ShufflePlanes(1, vs.GRAY)
        srcV = clip.std.ShufflePlanes(2, vs.GRAY)
        merged = core.std.ShufflePlanes([aaclip, srcU, srcV], 0, vs.YUV)
        return merged


def denoise(clip, mode=1, bm3d=True, sigma=4, h=1.0, tr=2, refine_motion=True, sbsize=16, sosize=12):
    """
    Generic denoising. Denoising is done by BM3D with other denoisers being used for ref. Will use the ref denoiser if
    BM3D=False.

    Mode 1 = KNLMeansCL
    Mode 2 = SMDegrain
    Mode 3 = DFTTest
    """
    if clip.format.bits_per_sample != 16:
        clip = fvf.Depth(clip, 16)
    clip_copy = clip
    clipY = core.std.ShufflePlanes(clip, 0, vs.GRAY)

    if mode is 1:
        denoiseY = clipY.knlm.KNLMeansCL(d=3, a=2, h=h)
    elif mode is 2:
        denoiseY = haf.SMDegrain(clipY, tr=tr, prefilter=3, RefineMotion=refine_motion)
    elif mode is 3:
        denoiseY = clipY.dfttest.DFTTest(sigma=4.0, tbsize=1, sbsize=sbsize, sosize=sosize)
    else:
        raise ValueError('denoise: unknown mode')

    if bm3d is True:
        denoisedY = mvf.BM3D(clipY, sigma=sigma, psample=0, radius1=1, ref=denoiseY)
    else:
        return denoiseY

    if clip_copy is vs.GRAY:
        return denoiseY
    else:
        clipU = core.std.ShufflePlanes(clip, 1, colorfamily=vs.GRAY)
        clipV = core.std.ShufflePlanes(clip, 2, colorfamily=vs.GRAY)
        merged = core.std.ShufflePlanes(clips=[denoisedY, clipU, clipV], planes=[0, 0, 0], colorfamily=vs.YUV)
        return merged
