"""exec_tick: the ONLY clock in the project. 30 Hz at a 60 fps timeline
(DESIGN.md 6)."""


def onFrameStart(frame):
	if frame % 2:
		return
	parent.PushResolume.Tick()
	return


def onStart():
	return


def onCreate():
	return


def onExit():
	return


def onFrameEnd(frame):
	return


def onPlayStateChange(state):
	return


def onDeviceChange():
	return


def onProjectPreSave():
	return


def onProjectPostSave():
	return
