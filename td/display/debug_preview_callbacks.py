"""
Script TOP Callbacks -- debug mirror of the exact 960x160 RGBA buffer sent
to the Push 2 helper (Phase 6f), before RGB565+XOR encoding. Display sets
scriptOp.store('frame', array) then calls scriptOp.cook(force=True); this
callback just displays whatever was last stored. capture_top on this op
shows precisely what the physical screen is receiving.

IMPORTANT: copyNumpyArray() crashed TD outright (confirmed live) when fed a
non-contiguous array (e.g. straight from np.flipud(), which returns a
negative-stride view, not a copy). Always pass a real contiguous array --
np.ascontiguousarray() here is a defensive second guard on top of the
caller (mod_display.RefreshDebugPreview) already copying before storing.

me - this DAT
scriptOp - the OP which is cooking
"""

import numpy


def onSetupParameters(scriptOp: scriptTOP):
	return


def onPulse(par: Par):
	return


def onCook(scriptOp: scriptTOP):
	arr = scriptOp.fetch('frame', None, search=False)
	if arr is None:
		arr = numpy.zeros((160, 960, 4), dtype='uint8')
	scriptOp.copyNumpyArray(numpy.ascontiguousarray(arr))
	return


def onGetCookLevel(scriptOp: scriptTOP) -> CookLevel:
	return CookLevel.ON_CHANGE
